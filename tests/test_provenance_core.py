from __future__ import annotations

import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prov = load_module("verify_provenance", ROOT / "scripts" / "verify_provenance.py")


class NormalizeTests(unittest.TestCase):
    def test_strips_chinese_punctuation_and_whitespace(self) -> None:
        self.assertEqual(prov.normalize("如此，月有考，岁有稽。"), "如此月有考岁有稽")

    def test_strips_quote_marks_and_brackets(self) -> None:
        self.assertEqual(prov.normalize("「事可责成」——《陈六事疏》"), "事可责成陈六事疏")

    def test_strips_ascii_punctuation_and_newlines(self) -> None:
        self.assertEqual(prov.normalize("a, b.\n c;"), "abc")

    def test_is_idempotent(self) -> None:
        once = prov.normalize("如此，月有考。")
        self.assertEqual(prov.normalize(once), once)


class CorpusTests(unittest.TestCase):
    def test_load_corpus_reads_txt_files_and_normalizes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw = root / "sources" / "demo" / "raw"
            raw.mkdir(parents=True)
            (raw / "a.txt").write_text("如此，月有考，岁有稽。", encoding="utf-8")
            (raw / "ignore.pdf").write_bytes(b"%PDF-1.4 binary")
            corpus = prov.load_corpus("demo", root)
            self.assertEqual(len(corpus), 1)
            self.assertEqual(corpus[0][0], "a.txt")
            self.assertEqual(corpus[0][1], "如此月有考岁有稽")

    def test_find_verbatim_returns_filename_on_hit(self) -> None:
        corpus = [("a.txt", "如此月有考岁有稽不惟使声必中实事可责成")]
        self.assertEqual(prov.find_verbatim("月有考岁有稽", corpus), "a.txt")

    def test_find_verbatim_returns_none_on_stitched_quote(self) -> None:
        corpus = [("a.txt", "如此月有考岁有稽不惟使声必中实事可责成")]
        self.assertIsNone(prov.find_verbatim("如此则月有考岁有稽名必中实事可责成", corpus))

    def test_longest_verbatim_prefix_reports_divergence_point(self) -> None:
        corpus = [("a.txt", "毋得彼此推诿徒托空言")]
        self.assertEqual(prov.longest_verbatim_prefix("毋得彼此推护徒记空言", corpus), 5)

    def test_longest_verbatim_prefix_is_zero_when_nothing_matches(self) -> None:
        corpus = [("a.txt", "毋得彼此推诿")]
        self.assertEqual(prov.longest_verbatim_prefix("完全不相干的句子", corpus), 0)

    def test_load_corpus_preserves_undecodable_bytes_as_replacement_chars(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw = root / "sources" / "demo" / "raw"
            raw.mkdir(parents=True)
            data = "张居正考成法".encode("gbk") + b"abc"
            (raw / "bad.txt").write_bytes(data)
            corpus = prov.load_corpus("demo", root)
            self.assertEqual(len(corpus), 1)
            self.assertIn("�", corpus[0][1])


class VariantFolderTests(unittest.TestCase):
    def test_get_variant_folder_returns_none_when_converter_construction_fails(self) -> None:
        fake_opencc = types.ModuleType("opencc")

        class BrokenOpenCC:
            def __init__(self, *args, **kwargs) -> None:
                raise RuntimeError("simulated broken opencc data files")

        fake_opencc.OpenCC = BrokenOpenCC  # type: ignore[attr-defined]
        with mock.patch.dict(sys.modules, {"opencc": fake_opencc}):
            self.assertIsNone(prov.get_variant_folder())


class EvidenceParseTests(unittest.TestCase):
    CARD = (
        "# 证据卡\n\n"
        "### 原则 1：立限考成\n\n"
        "> 如此，月有考，岁有稽，不惟使声必中实，事可责成\n\n"
        "- 出处：《请稽查章奏随事考成以修实政疏》（万历元年）\n"
        "- confidence：high\n\n"
        "### 原则 2：尚实黜虚\n\n"
        "> 毋得彼此推诿，徒托空言\n\n"
        "- 出处：《陈六事疏·省议论》\n"
        "- confidence：high\n"
        "- textual_note：底本作「推护」，据全集本正为「推诿」\n"
    )

    def test_parses_two_cards(self) -> None:
        cards = prov.parse_evidence_cards(self.CARD)
        self.assertEqual(len(cards), 2)
        self.assertEqual(cards[0]["title"], "原则 1：立限考成")

    def test_captures_blockquote_as_verbatim(self) -> None:
        cards = prov.parse_evidence_cards(self.CARD)
        self.assertEqual(cards[0]["verbatim"], "如此，月有考，岁有稽，不惟使声必中实，事可责成")

    def test_captures_fields(self) -> None:
        cards = prov.parse_evidence_cards(self.CARD)
        self.assertEqual(cards[0]["fields"]["confidence"], "high")

    def test_detects_textual_note(self) -> None:
        cards = prov.parse_evidence_cards(self.CARD)
        self.assertNotIn("textual_note", cards[0]["fields"])
        self.assertIn("textual_note", cards[1]["fields"])


class SkillQuoteExtractionTests(unittest.TestCase):
    SKILL = (
        "## 核心原则\n\n"
        "#### 原则 1：立限考成\n\n"
        "**理念：** 我见章奏堆积如山，「空文」二字最误国。\n\n"
        "**原文出处：**「如此，月有考，岁有稽」——《请稽查章奏疏》\n\n"
        "## 标志性名言\n\n"
        "- 「毋得彼此推诿，徒托空言」——《陈六事疏》\n"
    )

    def test_extracts_principle_source_quote(self) -> None:
        quotes = prov.extract_skill_quotes(self.SKILL)
        self.assertIn("如此，月有考，岁有稽", [q for _, q in quotes])

    def test_extracts_signature_quote(self) -> None:
        quotes = prov.extract_skill_quotes(self.SKILL)
        self.assertIn("毋得彼此推诿，徒托空言", [q for _, q in quotes])

    def test_ignores_emphasis_brackets_in_prose(self) -> None:
        quotes = prov.extract_skill_quotes(self.SKILL)
        self.assertNotIn("空文", [q for _, q in quotes])

    def test_extract_skill_quotes_tolerates_heading_drift(self) -> None:
        text = (
            "## 标志性名言与佳句\n\n"
            "- 「毋得彼此推诿，徒托空言」——《陈六事疏》\n"
        )
        quotes = prov.extract_skill_quotes(text)
        self.assertIn("毋得彼此推诿，徒托空言", [q for _, q in quotes])

    def test_extract_skill_quotes_harvests_epigraph(self) -> None:
        # The v6 template and the pilot both place exactly one blockquote near the top
        # of the file — a signature-quote epigraph before the first H2 heading — and it
        # used to be entirely outside extract_skill_quotes' scan, so the most prominent
        # quotation in the file had zero P1 coverage.
        text = (
            "---\nname: demo-wisdom\nformat_version: 6\n---\n\n"
            "# 示例人物的思维框架\n"
            "**示例人物** · 1525–1582\n\n"
            "> 「天下之事，不难于立法，而难于法之必行。」——示例人物\n\n"
            "---\n\n"
            "## 身份卡\n\n略\n"
        )
        quotes = prov.extract_skill_quotes(text)
        self.assertIn(("epigraph", "天下之事，不难于立法，而难于法之必行。"), quotes)

    def test_extract_skill_quotes_does_not_tag_blockquote_after_first_heading_as_epigraph(
        self,
    ) -> None:
        # Scope check: only a blockquote before the first H2 counts as the epigraph —
        # an ordinary blockquote inside a later section must not be swept in too.
        text = "## 身份卡\n\n> 「这不是题记，是正文里的引用。」——某人\n"
        quotes = prov.extract_skill_quotes(text)
        self.assertNotIn(("epigraph", "这不是题记，是正文里的引用。"), quotes)


class GateTests(unittest.TestCase):
    def _write(self, root: Path, skill: str, evidence: str, corpus: str) -> None:
        out = root / "output" / "demo"
        out.mkdir(parents=True)
        (out / "SKILL.md").write_text(skill, encoding="utf-8")
        refs = out / "references"
        refs.mkdir()
        (refs / "evidence.md").write_text(evidence, encoding="utf-8")
        raw = root / "sources" / "demo" / "raw"
        raw.mkdir(parents=True)
        (raw / "corpus.txt").write_text(corpus, encoding="utf-8")

    def test_p1_passes_when_quote_is_in_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write(
                root,
                "**原文出处：**「如此，月有考，岁有稽」——《疏》\n",
                "### 原则 1：甲\n\n> 如此，月有考，岁有稽\n\n- confidence：high\n",
                "如此，月有考，岁有稽，不惟使声必中实。",
            )
            errors = prov.check_p1_quote_closure(
                root / "output" / "demo" / "SKILL.md",
                root / "output" / "demo" / "references" / "evidence.md",
            )
            self.assertEqual(errors, [])

    def test_p1_fails_when_quote_missing_from_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write(
                root,
                "**原文出处：**「如此则月有考，名必中实」——《疏》\n",
                "### 原则 1：甲\n\n> 如此，月有考，岁有稽\n\n- confidence：high\n",
                "如此，月有考，岁有稽。",
            )
            errors = prov.check_p1_quote_closure(
                root / "output" / "demo" / "SKILL.md",
                root / "output" / "demo" / "references" / "evidence.md",
            )
            self.assertEqual(len(errors), 1)
            self.assertTrue(errors[0].startswith("P1_QUOTE_NOT_IN_EVIDENCE"))

    def test_p2_fails_on_stitched_quote_and_reports_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write(
                root,
                "**原文出处：**「甲」——《疏》\n",
                "### 原则 1：甲\n\n> 如此则月有考，岁有稽，名必中实，事可责成\n\n- confidence：high\n",
                "如此，月有考，岁有稽，不惟使声必中实，事可责成。",
            )
            errors = prov.check_p2_corpus_closure(
                root / "output" / "demo" / "references" / "evidence.md", "demo", root
            )
            self.assertEqual(len(errors), 1)
            self.assertTrue(errors[0].startswith("P2_NOT_IN_CORPUS"))
            self.assertIn("最长逐字前缀=2", errors[0])

    def test_p2_downgrades_to_warning_when_textual_note_present(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write(
                root,
                "**原文出处：**「甲」——《疏》\n",
                "### 原则 1：甲\n\n> 如此则月有考\n\n"
                "- confidence：high\n- textual_note：底本讹字，据received text 正之\n",
                "如此，月有考。",
            )
            errors = prov.check_p2_corpus_closure(
                root / "output" / "demo" / "references" / "evidence.md", "demo", root
            )
            self.assertEqual(len(errors), 1)
            self.assertTrue(errors[0].startswith("WARNING:"))

    def test_p2_passes_when_verbatim(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write(
                root,
                "**原文出处：**「甲」——《疏》\n",
                "### 原则 1：甲\n\n> 月有考，岁有稽\n\n- confidence：high\n",
                "如此，月有考，岁有稽，不惟使声必中实。",
            )
            errors = prov.check_p2_corpus_closure(
                root / "output" / "demo" / "references" / "evidence.md", "demo", root
            )
            self.assertEqual(errors, [])

    def test_p1_fails_on_citation_quote_that_wraps_to_next_line(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write(
                root,
                "**原文出处：**「如此，月有考，\n岁有稽」——《疏》\n",
                "### 原则 1：甲\n\n> 如此，月有考，岁有稽\n\n- confidence：high\n",
                "如此，月有考，岁有稽，不惟使声必中实。",
            )
            errors = prov.check_p1_quote_closure(
                root / "output" / "demo" / "SKILL.md",
                root / "output" / "demo" / "references" / "evidence.md",
            )
            self.assertTrue(
                any(e.startswith("P1_UNPARSEABLE_CITATION") for e in errors)
            )

    def test_p2_reports_empty_corpus_distinctly(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out = root / "output" / "demo"
            out.mkdir(parents=True)
            refs = out / "references"
            refs.mkdir()
            (refs / "evidence.md").write_text(
                "### 原则 1：甲\n\n> 月有考\n\n- confidence：high\n", encoding="utf-8"
            )
            # 故意不创建 sources/demo/raw —— load_corpus 返回空列表
            errors = prov.check_p2_corpus_closure(
                refs / "evidence.md", "demo", root
            )
            self.assertEqual(len(errors), 1)
            self.assertTrue(errors[0].startswith("EMPTY_CORPUS"))


if __name__ == "__main__":
    unittest.main()
