"""「raw/ 里有哪些素材」只有一个定义（墨子试跑第 10 条）。

`mdf acquire` 把语料落在 `raw/acquired/<连接器>/…` 下，索引器、登记表、P2 都递归读；
`validate sources` 却只看第一层，采集来的语料因此不会触发「必须先 mdf index」的检查。
状态表另有一份后缀表，漏了索引器认的 `.markdown`。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import local_source_pipeline as lsp  # noqa: E402
import pipeline_status as ps  # noqa: E402
import source_registry as sr  # noqa: E402
import validate_output  # noqa: E402


class Corpus(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self.raw = self.root / "sources" / "demo" / "raw"
        self.processed = self.root / "sources" / "demo" / "processed"
        self.raw.mkdir(parents=True)
        self.processed.mkdir(parents=True)
        (self.processed / "user_sources.json").write_text(json.dumps(
            {"source_type": "user_provided", "extracts": []}), encoding="utf-8")

    def tearDown(self):
        self._td.cleanup()

    def put(self, relative: str) -> Path:
        path = self.raw / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("原文", encoding="utf-8")
        return path

    def manifest_warnings(self) -> list[str]:
        cwd = os.getcwd()
        os.chdir(self.root)
        try:
            return [e for e in validate_output.validate_sources("demo") if "local_shards" in e]
        finally:
            os.chdir(cwd)


class IndexableRawFiles(Corpus):
    def test_acquired_files_in_subfolders_count(self):
        self.put("acquired/wikisource/墨子_天志上.txt")
        self.put("notes.md")
        found = [p.relative_to(self.raw).as_posix() for p in sr.indexable_raw_files(self.raw)]
        self.assertEqual(found, ["acquired/wikisource/墨子_天志上.txt", "notes.md"])

    def test_formats_the_indexer_cannot_read_are_left_out(self):
        self.put("book.epub")  # 登记表会收，索引器报 unsupported_extension
        self.put("scan.docx")
        self.assertEqual(sr.indexable_raw_files(self.raw), [])

    def test_matches_what_the_indexer_reads(self):
        self.assertEqual(sr.INDEXABLE_EXTENSIONS, lsp.SUPPORTED_TEXT_EXTS | lsp.SUPPORTED_PDF_EXTS)

    def test_missing_raw_dir_is_empty(self):
        self.assertEqual(sr.indexable_raw_files(self.root / "nowhere"), [])


class ValidateSourcesSeesNestedCorpus(Corpus):
    def test_acquired_corpus_without_index_is_flagged(self):
        self.put("acquired/wikisource/墨子_天志上.txt")
        self.assertTrue(self.manifest_warnings(), "采集来的语料没跑 mdf index，检查点 1 应当提醒")

    def test_unreadable_files_alone_do_not_demand_an_index(self):
        self.put("scan.docx")
        self.assertEqual(self.manifest_warnings(), [])


class StatusCountsWhatTheIndexerReads(Corpus):
    def test_markdown_extension_is_usable(self):
        self.put("acquired/gutenberg/letters.markdown")
        row = next(s for s in ps.collect_status("demo", self.root) if s.key == "sources")
        self.assertEqual(row.state, "done", row.detail)
        self.assertIn("1 个可处理文件", row.detail)


if __name__ == "__main__":
    unittest.main()
