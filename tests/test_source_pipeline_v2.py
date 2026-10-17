from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


pipeline = load("local_source_pipeline", ROOT / "scripts" / "local_source_pipeline.py")
pdf_quality = load("pdf_quality", ROOT / "scripts" / "pdf_quality.py")
registry = load("source_registry", ROOT / "scripts" / "source_registry.py")
sampling = load("sampling", ROOT / "scripts" / "sampling.py")
dispatch = load("worker_dispatch", ROOT / "scripts" / "worker_dispatch.py")
cost = load("cost_estimator", ROOT / "scripts" / "cost_estimator.py")


class PdfClassificationTests(unittest.TestCase):
    def test_classifies_pure_text_page(self) -> None:
        page = pdf_quality.classify_page(1, "这是一段足够长的文字。" * 20)
        self.assertEqual(page.classification, "text_only")
        self.assertFalse(page.ocr_required)

    def test_classifies_substantive_image_without_text(self) -> None:
        page = pdf_quality.classify_page(
            1, "", [{"width": 2000, "height": 2000, "bbox": [0, 0, 500, 500]}], 250000
        )
        self.assertEqual(page.classification, "image_only")
        self.assertTrue(page.ocr_required)

    def test_classifies_mixed_page(self) -> None:
        page = pdf_quality.classify_page(
            1, "正文" * 30, [{"width": 2000, "height": 2000, "bbox": [0, 0, 500, 500]}], 250000
        )
        self.assertEqual(page.classification, "mixed")
        self.assertTrue(page.ocr_required)


class RegistrySamplingTests(unittest.TestCase):
    def test_registry_recurses_and_fingerprints_content(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "nested").mkdir()
            (root / "nested" / "source.txt").write_text("内容", encoding="utf-8")
            data = registry.build_registry(root)
            self.assertEqual(len(data["sources"]), 1)
            self.assertEqual(data["sources"][0]["relative_path"], "nested/source.txt")
            self.assertTrue(data["sources"][0]["sha256"])

    def test_sampling_is_reproducible(self) -> None:
        units = [
            {"unit_id": f"u{i}", "token_estimate": 1000, "source_id": f"s{i % 2}", "language": "zh"}
            for i in range(10)
        ]
        config = sampling.SamplingConfig(mode="stratified", seed=7, broad_fraction=0.4)
        a = sampling.build_sampling_plan(units, config=config)
        b = sampling.build_sampling_plan(units, config=config)
        self.assertEqual([u["unit_id"] for u in a["selected_units"]], [u["unit_id"] for u in b["selected_units"]])

    def test_dispatch_limits_high_difficulty_concurrency(self) -> None:
        plan = dispatch.build_dispatch_plan(
            [{"unit_id": "large", "token_estimate": 55000, "ocr_required": True}, {"unit_id": "small", "token_estimate": 1000}]
        )
        self.assertLessEqual(plan["recommended_max_concurrency"], 2)
        self.assertEqual(plan["units"][0]["difficulty"], "high")

    def test_cost_without_rates_is_explicitly_unknown(self) -> None:
        estimate = cost.estimate_cost(selected_tokens=1000, total_tokens=2000, shard_count=1)
        self.assertEqual(estimate["cost"]["status"], "cost_unknown")
        self.assertIsNone(estimate["cost"]["upper"])


if __name__ == "__main__":
    unittest.main()
