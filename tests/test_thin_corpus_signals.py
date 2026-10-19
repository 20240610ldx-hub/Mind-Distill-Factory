"""素材薄时的信号要分得清：哪些是「按规则就只能这样」（不可改善），哪些是该去补的（可改善）。

2026-10-19 鲁迅 GUI 验收：
- 发现 6：检查点 1 的「high 占比 0%」四条警告，对只有一本 OCR 书、其余取自网络的人物永远出现
  （OCR 文本与网络来源按规则封顶 medium）；reduce 只出 15 条（<30）也只有一句英文 WARNING。
- 发现 8：原则提取的闸门对原则数没有下限，「少」不会被看见。
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
import validate_output  # noqa: E402


def extract(text: str, title: str, detail: str, confidence: str = "medium", url: str = "") -> dict:
    return {"text": text, "source_title": title, "source_detail": detail, "source_url": url,
            "confidence": confidence, "topic_tags": ["x"], "content_type": "principle_statement"}


class InDataRoot(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self._cwd = os.getcwd()
        os.chdir(self.root)

    def tearDown(self):
        os.chdir(self._cwd)
        self._td.cleanup()


class HighRatioWarning(InDataRoot):
    def setUp(self):
        super().setUp()
        self.processed = self.root / "sources" / "demo" / "processed"
        self.processed.mkdir(parents=True)
        (self.processed / "cleaning_report.json").write_text(json.dumps(
            {"sources": {"熱風.pdf": {"flags": ["ocr_text", "ocr_incomplete"]}, "書信.txt": {"flags": []}}}),
            encoding="utf-8")

    def write(self, name: str, source_type: str, extracts: list[dict]):
        (self.processed / name).write_text(json.dumps({"source_type": source_type, "extracts": extracts},
                                                      ensure_ascii=False), encoding="utf-8")

    def ratio_warnings(self) -> dict[str, str]:
        found = {}
        for e in validate_output.validate_sources("demo"):
            if "high 占比" in e:
                found[next(n for n in ("user_sources", "primary_sources", "letters") if n in e)] = e
        return found

    def test_ocr_and_web_caps_are_marked_inherent(self):
        self.write("user_sources.json", "user_provided",
                   [extract("原文", "熱風", "熱風.pdf, 隨感錄, OCR page 29") for _ in range(3)])
        self.write("primary_sources.json", "primary",
                   [extract("原文", "未有天才之前", "1924 年講演", url="https://zh.wikisource.org/wiki/x")])
        warnings = self.ratio_warnings()
        self.assertIn("[不可改善]", warnings["user_sources"])
        self.assertIn("OCR 文本 3 条", warnings["user_sources"])
        self.assertIn("[不可改善]", warnings["primary_sources"])
        self.assertIn("网络来源 1 条", warnings["primary_sources"])

    def test_uncapped_medium_extracts_are_marked_actionable(self):
        self.write("letters.json", "user_provided",
                   [extract("原文", "書信", "書信.txt, 致許廣平") for _ in range(2)]
                   + [extract("原文", "熱風", "熱風.pdf, OCR page 3")])
        warning = self.ratio_warnings()["letters"]
        self.assertIn("[可改善]", warning)
        self.assertIn("2 条", warning)


class ReduceShortfall(unittest.TestCase):
    def test_whole_corpus_processed_is_inherent(self):
        note = lsp.extract_shortfall(15, {"sampling_mode": "exhaustive", "shard_count": 1,
                                          "total_token_estimate": 28347},
                                     {"input_units": [{"unit_id": "shard_001"}], "completed_units": ["shard_001"]})
        self.assertIn("[不可改善]", note)
        self.assertIn("15", note)
        self.assertIn("28,347", note)

    def test_unprocessed_or_sampled_shards_are_actionable(self):
        pending = lsp.extract_shortfall(12, {"sampling_mode": "exhaustive", "shard_count": 3},
                                        {"input_units": [{"unit_id": f"shard_00{i}"} for i in (1, 2, 3)],
                                         "completed_units": ["shard_001"]})
        self.assertIn("[可改善]", pending)
        self.assertIn("2 个分片", pending)
        sampled = lsp.extract_shortfall(12, {"sampling_mode": "stratified", "shard_count": 4}, None)
        self.assertIn("[可改善]", sampled)
        self.assertIn("抽样", sampled)

    def test_enough_extracts_says_nothing(self):
        self.assertIsNone(lsp.extract_shortfall(lsp.DEFAULT_MIN_EXTRACTS, {}, None))


class PrincipleCount(InDataRoot):
    def write(self, source_type: str, count: int):
        out = self.root / "output" / "demo"
        out.mkdir(parents=True, exist_ok=True)
        principles = [{"id": f"principle_{i:03d}", "name_zh": "x", "name_en": "x", "uniqueness_score": 3,
                       "explanation_zh": "x", "explanation_en": "x", "decision_rule_zh": "x",
                       "decision_rule_en": "x", "supporting_extracts": [{"text": "x"}], "topic_tags": ["x"]}
                      for i in range(1, count + 1)]
        (out / f"principles_{source_type}.json").write_text(
            json.dumps({"source_type": source_type, "principles": principles}), encoding="utf-8")

    def test_few_thinker_candidates_are_visible(self):
        self.write("user_sources", 4)
        self.write("primary_sources", 2)
        self.write("secondary_sources", 9)  # 评论者的观点不算思想家本人的候选
        errors = validate_output.validate_principles("demo")
        thin = [e for e in errors if "原则候选" in e]
        self.assertTrue(any("本人来源 6 条" in e and "8" in e for e in thin), errors)
        self.assertTrue(any("principles_primary_sources.json" in e and "2 条" in e for e in thin), errors)
        self.assertTrue(all(e.startswith("WARNING") for e in thin), "宁少勿凑：只提醒，不拦")

    def test_enough_candidates_are_quiet(self):
        self.write("user_sources", 6)
        self.write("primary_sources", 8)
        self.assertFalse([e for e in validate_output.validate_principles("demo") if "原则候选" in e])

    def test_no_principles_at_all_is_an_error(self):
        self.write("user_sources", 0)
        errors = validate_output.validate_principles("demo")
        self.assertTrue(any(e.startswith("NO_PRINCIPLES") for e in errors), errors)


if __name__ == "__main__":
    unittest.main()
