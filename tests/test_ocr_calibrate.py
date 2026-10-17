"""OCR 校准：指标、引擎缓存、合成扫描件走 index 同一条 PDF→OCR 路径（用假引擎，离线）。"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ocr_calibrate as oc  # noqa: E402

HAVE_RENDER = all(importlib.util.find_spec(m) is not None for m in ("fitz", "PIL"))
TRUTH = ["子曰：學而時習之，不亦說乎？有朋自遠方來，不亦樂乎？", "月有考，岁有稽，事情办没办成，到期一查便知。"]


def fake_engine(pages: list[str], corrupt=None, confidence: float = 0.97):
    """按调用顺序把第 i 次调用当作第 i 页，返回真值（可选损坏）；模拟 OCR 会在行尾断行。"""
    calls = {"n": 0}

    def run(_image: bytes) -> tuple[str, float]:
        text = pages[calls["n"] % len(pages)]
        calls["n"] += 1
        text = corrupt(text) if corrupt else text
        return text[: len(text) // 2] + "\n" + text[len(text) // 2:], confidence

    return run


def every_nth_wrong(n: int):
    return lambda text: "".join("口" if i % n == n - 1 and not ch.isspace() else ch for i, ch in enumerate(text))


class MetricTests(unittest.TestCase):
    def test_levenshtein(self):
        self.assertEqual(oc.levenshtein("", "abc"), 3)
        self.assertEqual(oc.levenshtein("考成之法", "考成之法"), 0)
        self.assertEqual(oc.levenshtein("考成之法", "考城之法"), 1)
        self.assertEqual(oc.levenshtein("abc", "ac"), 1)

    def test_line_breaks_do_not_count_as_errors(self):
        row = oc.page_metrics(TRUTH[1], "月有考，岁有稽，事情办没\n办成，到期一查便知。")
        self.assertEqual(row["cer"], 0.0)
        self.assertEqual(row["sentences_verbatim"], row["sentences"])

    def test_one_wrong_character_loses_the_sentence(self):
        row = oc.page_metrics(TRUTH[1], "月有考，岁有稽，事情办没办戍，到期一查便知。")
        self.assertGreater(row["cer"], 0)
        self.assertLess(row["sentences_verbatim"], row["sentences"])
        self.assertTrue(row["lost_sentences"])

    def test_truth_file_splits_pages(self):
        pages = oc.load_truth()
        self.assertEqual(len(pages), 3)
        self.assertTrue(all(pages))


class EngineCacheTests(unittest.TestCase):
    def tearDown(self):
        oc.pdf_quality._RUNNERS.pop("counting", None)
        oc.pdf_quality.RUNNER_FACTORIES.pop("counting", None)

    def test_engine_is_built_once_per_process(self):
        built = []

        def factory():
            built.append(1)
            return lambda image: ("文", 0.9)

        oc.pdf_quality.RUNNER_FACTORIES["counting"] = factory
        for _ in range(5):
            self.assertIs(oc.pdf_quality.get_runner("counting"), oc.pdf_quality.get_runner("counting"))
        self.assertEqual(len(built), 1, "模型加载很慢，不能每页新建一次引擎")

    def test_missing_dependency_is_not_cached(self):
        def factory():
            raise ImportError("not installed")

        oc.pdf_quality.RUNNER_FACTORIES["counting"] = factory
        with self.assertRaises(ImportError):
            oc.pdf_quality.get_runner("counting")
        self.assertNotIn("counting", oc.pdf_quality._RUNNERS)


@unittest.skipUnless(HAVE_RENDER, "需要 PyMuPDF 与 Pillow（pip install -e .[pdf,ocr]）")
class SyntheticScanTests(unittest.TestCase):
    def tearDown(self):
        oc.pdf_quality.clear_injected_runners()

    def test_perfect_engine_round_trips_through_the_index_path(self):
        oc.pdf_quality.register_runner("fake", fake_engine(TRUTH))
        report = oc.calibrate(TRUTH, font=None, degrades=["none"])
        [level] = report["levels"]
        self.assertEqual(level["document_type"], "pure_image_pdf", "合成页必须没有文字层，才会走 OCR")
        self.assertEqual((level["ocr_ok_pages"], level["pages"]), (2, 2))
        self.assertEqual(level["cer"], 0.0)
        self.assertEqual(level["verbatim_survival"], 1.0)
        self.assertNotIn("low_ocr_confidence", level["gate_flags"])

    def test_noisy_low_confidence_engine_is_flagged(self):
        oc.pdf_quality.register_runner("fake", fake_engine(TRUTH, corrupt=every_nth_wrong(9), confidence=0.5))
        [level] = oc.calibrate(TRUTH, font=None, degrades=["heavy"])["levels"]
        self.assertGreater(level["cer"], 0.05)
        self.assertLess(level["verbatim_survival"], 1.0)
        self.assertIn("low_ocr_confidence", level["gate_flags"])
        self.assertIn("逐字丢失的句子", oc.render_calibration({"font": None, "dpi": 200,
                                                          "low_confidence_threshold": 0.6, "levels": [level]}))

    def test_scan_reports_each_page(self):
        oc.pdf_quality.register_runner("fake", fake_engine(TRUTH))
        with tempfile.TemporaryDirectory() as td:
            pdf = oc.build_pdf([oc.render_page(t, None) for t in TRUTH], Path(td) / "scan.pdf")
            report = oc.scan(pdf)
        self.assertEqual(report["ocr_ok"], 2)
        self.assertEqual([r["ocr_status"] for r in report["pages"]], ["ok", "ok"])
        self.assertEqual({r["backend"] for r in report["pages"]}, {"fake"})

    def test_degrade_levels_render(self):
        for level in oc.DEGRADE:
            with self.subTest(level=level):
                self.assertTrue(oc.render_page(TRUTH[0], None, degrade=level).startswith(b"\x89PNG"))


class CliTests(unittest.TestCase):
    def test_no_engine_exits_with_install_hint(self):
        err = io.StringIO()
        with mock.patch.object(oc, "engine_available", return_value=[]), contextlib.redirect_stderr(err):
            self.assertEqual(oc.main(["calibrate"]), 2)
        self.assertIn("pip install", err.getvalue())

    def test_mdf_lists_ocr_subcommand(self):
        spec = importlib.util.spec_from_file_location("_mdf_for_ocr", ROOT / "scripts" / "mdf.py")
        mdf = importlib.util.module_from_spec(spec)
        sys.modules["_mdf_for_ocr"] = mdf
        spec.loader.exec_module(mdf)
        self.assertEqual(mdf.PASSTHROUGH["ocr"][0], "ocr_calibrate")


if __name__ == "__main__":
    unittest.main()
