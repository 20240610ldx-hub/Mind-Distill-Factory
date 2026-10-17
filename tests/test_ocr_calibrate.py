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
        oc.pdf_quality.register_runner("fake", fake_engine(TRUTH, corrupt=every_nth_wrong(9), confidence=0.8))
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


FAKE_PADDLEOCR_JSON = r'''
import base64, json, sys
print("PaddleOCR-json v1.4", flush=True)
print("OCR init completed.", flush=True)
for line in sys.stdin:
    image = base64.b64decode(json.loads(line)["image_base64"])
    if image == b"blank":
        reply = {"code": 101, "data": "No text found in image."}
    elif image == b"broken":
        reply = {"code": 203, "data": "image decode failed"}
    else:
        reply = {"code": 100, "data": [{"box": [[0, 0]], "score": 0.9, "text": "月有考"},
                                       {"box": [[0, 9]], "score": 0.7, "text": "岁有稽"}]}
    print(json.dumps(reply), flush=True)
'''


class EngineAdapterTests(unittest.TestCase):
    def test_rapidocr_v3_output_object(self):
        out = mock.Mock(txts=("月有考", "岁有稽"), scores=(0.9, 0.7))
        fake = mock.Mock(RapidOCR=mock.Mock(return_value=mock.Mock(return_value=out)))
        with mock.patch.dict(sys.modules, {"rapidocr": fake}):
            text, conf = oc.pdf_quality._rapidocr_runner()(b"png")
        self.assertEqual(text, "月有考\n岁有稽")
        self.assertAlmostEqual(conf, 0.8)

    def test_rapidocr_falls_back_to_legacy_package(self):
        legacy = mock.Mock(RapidOCR=mock.Mock(return_value=mock.Mock(
            return_value=([[[0, 0], "月有考", 0.9], [[0, 9], "岁有稽", "0.7"]], 0.1))))
        with mock.patch.dict(sys.modules, {"rapidocr": None, "rapidocr_onnxruntime": legacy}):
            text, conf = oc.pdf_quality._rapidocr_runner()(b"png")
        self.assertEqual(text, "月有考\n岁有稽")
        self.assertAlmostEqual(conf, 0.8)

    def test_paddleocr_json_pipe_protocol(self):
        with tempfile.TemporaryDirectory() as td:
            script = Path(td) / "fake_paddleocr_json.py"
            script.write_text(FAKE_PADDLEOCR_JSON, encoding="utf-8")
            pipe = oc.pdf_quality.PaddleOcrJsonPipe([sys.executable, "-I", str(script)], cwd=Path(td))
            try:
                text, conf = pipe(b"page")
                self.assertEqual(text, "月有考\n岁有稽")
                self.assertAlmostEqual(conf, 0.8)
                self.assertEqual(pipe(b"blank"), ("", 0.0), "code 101 是图里没字，不是错误")
                with self.assertRaises(RuntimeError):
                    pipe(b"broken")
                self.assertEqual(pipe(b"page")[0], "月有考\n岁有稽", "一次失败之后进程仍可用")
            finally:
                pipe.close()

    def test_paddleocr_json_pipe_that_never_inits(self):
        with self.assertRaises(RuntimeError):
            oc.pdf_quality.PaddleOcrJsonPipe([sys.executable, "-I", "-c", "print('loading')"], init_timeout=10)

    def test_paddleocr_json_needs_explicit_location(self):
        with mock.patch.dict("os.environ", {"MDF_PADDLEOCR_JSON": ""}):
            self.assertIsNone(oc.pdf_quality.paddleocr_json_exe())
            with self.assertRaises(ImportError):
                oc.pdf_quality._paddleocr_json_runner()
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "PaddleOCR-json.exe").write_bytes(b"")
            with mock.patch.dict("os.environ", {"MDF_PADDLEOCR_JSON": td}):
                self.assertEqual(oc.pdf_quality.paddleocr_json_exe(), Path(td) / "PaddleOCR-json.exe")

    def test_backend_pin_keeps_injected_runner_first(self):
        oc.pdf_quality.register_runner("fake", lambda image: ("文", 0.9))
        try:
            with mock.patch.dict("os.environ", {"MDF_OCR_BACKEND": "paddleocr_json"}):
                self.assertEqual(oc.pdf_quality.ocr_candidates(), ["fake", "paddleocr_json"])
                self.assertEqual(oc.pdf_quality.ocr_candidates("rapidocr"), ["rapidocr"])
            with mock.patch.dict("os.environ", {"MDF_OCR_BACKEND": ""}):
                self.assertEqual(oc.pdf_quality.ocr_candidates(), ["fake", *oc.pdf_quality.RUNNER_FACTORIES])
        finally:
            oc.pdf_quality.clear_injected_runners()


@unittest.skipUnless(HAVE_RENDER, "需要 PyMuPDF 与 Pillow（pip install -e .[pdf,ocr]）")
class OcrIntoIndexTests(unittest.TestCase):
    def tearDown(self):
        oc.pdf_quality.clear_injected_runners()

    def test_each_backend_is_reported_separately(self):
        oc.pdf_quality.register_runner("good", fake_engine(TRUTH))
        oc.pdf_quality.register_runner("bad", fake_engine(TRUTH, corrupt=every_nth_wrong(5), confidence=0.5))
        report = oc.calibrate(TRUTH, font=None, degrades=["none"], backends=["good", "bad"])
        by_engine = {lv["engine"]: lv for lv in report["levels"]}
        self.assertEqual(by_engine["good"]["backend_used"], ["good"])
        self.assertEqual(by_engine["good"]["verbatim_survival"], 1.0)
        self.assertLess(by_engine["bad"]["verbatim_survival"], 1.0)
        self.assertIn("ocr_garbled", by_engine["bad"]["gate_reasons"])
        self.assertIn("| bad | none |", oc.render_calibration(report))

    def test_ocr_pages_are_marked_in_shards(self):
        oc.pdf_quality.register_runner("fake", fake_engine(TRUTH))
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "sources" / "ocr-demo" / "raw"
            raw.mkdir(parents=True)
            oc.build_pdf([oc.render_page(t, None) for t in TRUTH], raw / "scan.pdf")
            with mock.patch.dict("os.environ", {"MDF_DATA_ROOT": td}):
                segments, _files = oc.lsp.collect_segments("ocr-demo")
        text = "\n".join(s.text for s in segments)
        self.assertIn("--- Page 1 (OCR) ---", text)
        self.assertTrue(all("ocr_text" in s.quality_flags for s in segments))
        self.assertTrue(oc.clean_corpus.PAGE_MARKER_RE.match("--- Page 1 (OCR) ---"), "清洗规则不得删掉 OCR 页码标记")


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
