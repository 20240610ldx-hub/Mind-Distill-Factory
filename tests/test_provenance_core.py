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


if __name__ == "__main__":
    unittest.main()
