"""Stage 3A 机械 scaffold（build_framework_core.py）与 core 闸门。

夹具按 agents/principle-extractor.md 的输出契约写：reasoning_patterns、notable_quotes 在文件顶层，
各来源文件的原则 id 都从 principle_001 起编。2026-10-19 鲁迅 GUI 验收发现 7：scaffold 按「每条原则下面」
去读推理模式与名言，读到 0；盲区去读还不存在的 frameworks.*.json，读到 0；三份文件的 id 互相重名。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_framework_core as bfc  # noqa: E402
import validate_output  # noqa: E402

SLUG = "demo"


def principle(pid: str, name_zh: str, name_en: str, tag: str, score: int, confidence: str) -> dict:
    return {
        "id": pid, "name_zh": name_zh, "name_en": name_en, "uniqueness_score": score,
        "explanation_zh": f"{name_zh}的解释", "explanation_en": f"{name_en} explained",
        "decision_rule_zh": "当……时，应当……", "decision_rule_en": "When ..., then ...",
        "supporting_extracts": [{"text": f"{name_zh}原文", "source_title": "熱風", "source_detail": "隨感錄",
                                 "confidence": confidence}],
        "topic_tags": [tag],
    }


def principles_file(source_type: str, principles: list[dict], patterns: list[dict], quotes: list[dict]) -> dict:
    return {"person_slug": SLUG, "source_type": source_type, "extracted_at": "2026-10-19",
            "principles": principles, "reasoning_patterns": patterns, "notable_quotes": quotes}


def pattern(pid: str, name_zh: str, name_en: str) -> dict:
    return {"id": pid, "name_zh": name_zh, "name_en": name_en, "description_zh": "描述", "description_en": "desc",
            "trigger_zh": "触发", "trigger_en": "trigger", "supporting_evidence": "原文"}


def quote(text: str, confidence: str) -> dict:
    return {"text_zh": text, "text_en": "", "source": "熱風", "use_case_zh": "", "use_case_en": "",
            "confidence": confidence}


class ScaffoldFixture(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self.out = self.root / "output" / SLUG
        self.out.mkdir(parents=True)
        self._env = mock.patch.dict(os.environ, {"MDF_DATA_ROOT": str(self.root)})
        self._env.start()
        self.write("user_sources",
                   [principle("principle_001", "直面惨淡", "Face the bleak", "courage", 4, "high"),
                    principle("principle_002", "疑古", "Doubt the old", "inquiry", 3, "high")],
                   [pattern("pattern_001", "揭疮疤", "Expose the sore"), pattern("pattern_002", "反讽", "Irony")],
                   [quote("真的猛士，敢于直面惨淡的人生", "high")])
        self.write("primary_sources",
                   [principle("principle_001", "韧性战斗", "Tenacious fight", "resilience", 4, "medium")],
                   [pattern("pattern_001", "揭疮疤", "Expose the sore")],
                   [quote("真的猛士，敢于直面惨淡的人生", "medium"), quote("救救孩子", "medium")])
        self.write("secondary_sources",
                   [principle("principle_001", "民族魂", "Soul of the nation", "legacy", 5, "medium")],
                   [], [])

    def tearDown(self):
        self._env.stop()
        self._td.cleanup()

    def write(self, source_type, principles, patterns, quotes):
        (self.out / f"principles_{source_type}.json").write_text(
            json.dumps(principles_file(source_type, principles, patterns, quotes), ensure_ascii=False),
            encoding="utf-8")


class FileLevelCandidates(ScaffoldFixture):
    def test_reasoning_patterns_come_from_the_file_level(self):
        names = [p["name_zh"] for p in bfc.build_core(SLUG)["reasoning_pattern_candidates"]]
        self.assertEqual(names, ["揭疮疤", "反讽"], "顶层的推理模式要读到，跨文件同名的去重")

    def test_quotes_come_from_the_file_level(self):
        quotes = bfc.build_core(SLUG)["quote_candidates"]
        self.assertEqual([q["text_zh"] for q in quotes], ["真的猛士，敢于直面惨淡的人生", "救救孩子"])
        self.assertEqual(quotes[0]["confidence"], "high", "同一句保留置信度高的那份")


class CandidateIds(ScaffoldFixture):
    def test_ids_are_unique_across_source_files(self):
        core = bfc.build_core(SLUG)
        ids = [pid for c in core["principle_clusters"] for pid in c["candidate_principle_ids"]]
        self.assertEqual(len(ids), len(set(ids)), ids)
        self.assertIn("user_sources/principle_001", ids)
        self.assertIn("secondary_sources/principle_001", ids)
        evidence_ids = {e["from_principle_id"] for c in core["principle_clusters"] for e in c["selected_evidence"]}
        ledger_ids = {pid for s in core["source_ledger"] for pid in s["used_by_principle_ids"]}
        self.assertLessEqual(evidence_ids | ledger_ids, set(ids), "证据与台账引用的是同一套 id")


class CommentaryOnlyClusters(ScaffoldFixture):
    def test_secondary_only_cluster_is_marked_and_ranked_last(self):
        clusters = bfc.build_core(SLUG)["principle_clusters"]
        last = clusters[-1]
        self.assertEqual(last["canonical_name_zh"], "民族魂", "评论者的观点哪怕 uniqueness 5 也排在思想家本人的原则后面")
        self.assertEqual(last["evidence_basis"], "secondary_only")
        self.assertTrue(all(c["evidence_basis"] == "thinker" for c in clusters[:-1]))


class BlindSpotsNeedTheAgent(ScaffoldFixture):
    def test_scaffold_says_what_the_agent_must_fill(self):
        core = bfc.build_core(SLUG)
        self.assertEqual(core["shared_blind_spot_themes"], [], "原则文件里没有盲区字段，scaffold 不编")
        self.assertIn("shared_blind_spot_themes", core["scaffold_gaps"])

    def test_core_gate_rejects_a_core_without_blind_spot_themes(self):
        core = bfc.build_core(SLUG)
        (self.out / "framework_core.json").write_text(json.dumps(core, ensure_ascii=False), encoding="utf-8")
        cwd = os.getcwd()
        os.chdir(self.root)
        try:
            errors = validate_output.validate_frameworks(SLUG)
        finally:
            os.chdir(cwd)
        self.assertTrue(any(e.startswith("TOO_FEW_BLIND_SPOTS") and "framework_core.json" in e for e in errors), errors)


if __name__ == "__main__":
    unittest.main()
