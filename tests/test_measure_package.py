from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


measure_mod = load_module("measure_package", ROOT / "scripts" / "measure_package.py")
prov_mod = load_module("verify_provenance", ROOT / "scripts" / "verify_provenance.py")


class MeasureTests(unittest.TestCase):
    def _build(self, root: Path) -> None:
        out = root / "output" / "demo"
        refs = out / "references"
        refs.mkdir(parents=True)
        (out / "SKILL.md").write_text(
            "---\nname: demo-wisdom\nformat_version: 6\n---\n\n# 标题\n\n正文一行\n",
            encoding="utf-8",
        )
        (refs / "evidence.md").write_text(
            "### 原则 1：甲\n\n> 月有考岁有稽\n\n- confidence：high\n", encoding="utf-8"
        )
        (refs / "cases.md").write_text(
            "### 案例 1：甲（case_id: demo-a-1，high）\n\n**对应原则簇：** cluster_001\n\n略\n\n"
            "### 案例 2：乙（case_id: demo-b-1，high）\n\n**对应原则簇：** cluster_001\n\n反例：略\n",
            encoding="utf-8",
        )
        (refs / "voice.md").write_text("### 样本 1\n\n> 略\n", encoding="utf-8")
        processed = root / "sources" / "demo" / "processed"
        processed.mkdir(parents=True)
        (processed / "user_sources.json").write_text(
            '{"extracts":[{"text":"月有考岁有稽，事可责成，凡二十字整。"}]}', encoding="utf-8"
        )

    def test_counts_lines(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._build(root)
            result = measure_mod.measure("demo", root)
            # NOTE (task-10 brief defect): the brief's Step 2 asserted 7, but the
            # fixture SKILL.md text above has 8 physical lines under
            # len(text.splitlines()) — the same counting method P6 in
            # validate_output.py uses. Verified by direct count; see task-10-report.md.
            self.assertEqual(result["lines"], 8)

    def test_counts_cases_and_counter_cases(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._build(root)
            result = measure_mod.measure("demo", root)
            self.assertEqual(result["cases"], 2)
            self.assertEqual(result["counter_cases"], 1)

    def test_computes_evidence_survival_percentage(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._build(root)
            result = measure_mod.measure("demo", root)
            self.assertGreater(result["evidence_survival_pct"], 0)
            self.assertLessEqual(result["evidence_survival_pct"], 100)

    def test_evidence_survival_does_not_double_count_substrings(self) -> None:
        # A SKILL.md 原文出处 quote is frequently a *shorter* pull-quote of the
        # same passage that appears at full length in its evidence.md card —
        # not a different quotation. An exact-string set dedups only identical
        # strings, so the short pull-quote and the longer card both get
        # counted, double-billing the overlapping characters. The numerator
        # must count that passage once, at the longer card's length.
        long_card = "如此，月有考，岁有稽，不惟使声必中实，事可责成。"
        short_quote = "月有考岁有稽"
        self.assertIn(
            prov_mod.normalize(short_quote), prov_mod.normalize(long_card),
            "fixture invariant: short_quote must be a substring of long_card once normalized",
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out = root / "output" / "demo"
            refs = out / "references"
            refs.mkdir(parents=True)
            (out / "SKILL.md").write_text(
                "---\nname: demo-wisdom\nformat_version: 6\n---\n\n# 标题\n\n"
                f"**原文出处：**「{short_quote}」——某疏\n",
                encoding="utf-8",
            )
            (refs / "evidence.md").write_text(
                f"### 原则 1：甲\n\n> {long_card}\n\n- confidence：high\n", encoding="utf-8"
            )
            (refs / "cases.md").write_text(
                "### 案例 1：甲（case_id: demo-a-1，high）\n\n**对应原则簇：** cluster_001\n\n反例：略\n",
                encoding="utf-8",
            )
            (refs / "voice.md").write_text("### 样本 1\n\n> 略\n", encoding="utf-8")
            processed = root / "sources" / "demo" / "processed"
            processed.mkdir(parents=True)
            (processed / "user_sources.json").write_text(
                '{"extracts":[{"text":"如此，月有考，岁有稽，不惟使声必中实，事可责成，凡若干字。"}]}',
                encoding="utf-8",
            )

            result = measure_mod.measure("demo", root)
            expected = len(prov_mod.normalize(long_card))
            self.assertEqual(
                result["evidence_chars"], expected,
                "numerator double-counted a SKILL.md quote that is a strict "
                "substring of its evidence.md card instead of deduping it",
            )


if __name__ == "__main__":
    unittest.main()
