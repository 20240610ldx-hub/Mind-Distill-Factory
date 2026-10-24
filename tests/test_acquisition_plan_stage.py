"""采集计划接进流水线：阶段树的「采集计划」一步、状态表、简报、子代理定义、编排协议。

阶段 1 原来第一步就是「素材入库」，raw/ 为空时只提示 `mdf acquire --help`，该采什么靠人。现在前面加一步：
acquisition-scout 凭记忆写候选（不联网）→ `mdf acquire-plan` 目录核对 → 编排者把清单给用户批 →
`mdf acquire-plan --approve` → 素材入库这一步再 `mdf acquire`。raw/ 里已有素材又没写候选时，这一步跳过。
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import harness  # noqa: E402
import pipeline_status as ps  # noqa: E402

TREE = json.loads((ROOT / "config" / "pipeline_stages.json").read_text(encoding="utf-8"))
CANDIDATES = {
    "schema": "acquisition-candidates-v1",
    "person": {"name": "墨子", "aliases": ["墨翟"], "death_year": -391, "wikisource_author": {"zh": "墨翟"}},
    "candidates": [{"id": "c01", "work": "墨子", "titles": ["墨子"], "kind": "primary", "language": "zh",
                    "why": "本人著作", "catalogs": ["wikisource"]}],
}


def plan_step() -> dict:
    stage1 = next(p for p in TREE["phases"] if p["id"] == "stage1")
    return stage1["steps"][0]


class StageTreeTests(unittest.TestCase):
    def test_plan_comes_first_in_stage1(self):
        stage1 = next(p for p in TREE["phases"] if p["id"] == "stage1")
        self.assertEqual([s["id"] for s in stage1["steps"]][:2], ["plan", "sources"])

    def test_plan_step_contract(self):
        step = plan_step()
        self.assertIn("acquisition-scout", step["agent"])
        self.assertEqual(set(step["executor"].split("|")), {"agent", "script", "human"})
        self.assertEqual(step["network"], "forbidden", "候选凭记忆写，不联网；目录核对由脚本按白名单做")
        self.assertEqual(step["checkpoint"], "python scripts/mdf.py acquire-plan {slug} --check")
        self.assertIn("python scripts/mdf.py acquire-plan {slug}", step["command"])

    def test_scout_role_definition(self):
        text = (ROOT / "agents" / "acquisition-scout.md").read_text(encoding="utf-8")
        meta = harness.parse_frontmatter(text)
        self.assertEqual(meta.get("name"), "acquisition-scout")
        for needle in ("acquisition-candidates-v1", "acquisition_candidates.json", "WebSearch", "why", "titles"):
            self.assertIn(needle, text)


class StatusTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self.src = self.root / "sources" / "mozi"
        self.src.mkdir(parents=True)

    def tearDown(self):
        self._td.cleanup()

    def plan(self):
        return next(s for s in ps.collect_status("mozi", self.root) if s.key == "plan")

    def write(self, rel: str, data) -> Path:
        path = self.src / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        return path

    def test_skipped_when_the_user_already_supplied_material(self):
        (self.src / "raw").mkdir()
        (self.src / "raw" / "mozi.txt").write_text("子墨子言曰", encoding="utf-8")
        self.assertEqual(self.plan().state, "skipped")

    def test_pending_without_candidates_points_at_the_scout(self):
        status = self.plan()
        self.assertEqual(status.state, "pending")
        self.assertIn("acquisition-scout", status.next_action)

    def test_pending_with_candidates_but_no_draft_runs_the_planner(self):
        self.write("acquisition_candidates.json", CANDIDATES)
        status = self.plan()
        self.assertEqual(status.state, "pending")
        self.assertIn("acquire-plan mozi", status.next_action)

    def test_draft_waits_for_the_user(self):
        path = self.write("acquisition_candidates.json", CANDIDATES)
        import hashlib
        self.write("processed/acquisition_plan.draft.json", {
            "schema": "acquisition-plan-draft-v1", "candidates_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "entries": [{"candidate_id": "c01", "status": "resolved", "downloadable": True}]})
        status = self.plan()
        self.assertEqual(status.state, "blocked")
        self.assertIn("AskUserQuestion", status.next_action)
        self.assertIn("--approve", status.next_action)

    def test_stale_draft_must_be_redone(self):
        self.write("acquisition_candidates.json", CANDIDATES)
        self.write("processed/acquisition_plan.draft.json", {
            "schema": "acquisition-plan-draft-v1", "candidates_sha256": "0" * 64, "entries": []})
        self.assertIn("acquire-plan mozi", self.plan().next_action)

    def test_done_once_a_plan_is_approved(self):
        self.write("acquisition_candidates.json", CANDIDATES)
        self.write("acquisition_plan.json", {"schema": "acquisition-plan-v1",
                                             "targets": [{"connector": "wikisource", "lang": "zh", "title": "墨子"}],
                                             "approvals": [{"candidates": ["c01"]}]})
        status = self.plan()
        self.assertEqual(status.state, "done")
        sources = next(s for s in ps.collect_status("mozi", self.root) if s.key == "sources")
        self.assertIn("acquire mozi", sources.next_action)


class BriefTests(unittest.TestCase):
    def test_plan_brief_hands_the_scout_its_job_and_forbids_the_network(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "sources" / "mozi").mkdir(parents=True)
            unit_id, text = harness.build_brief("mozi", "plan", Path(td))
        self.assertEqual(unit_id, "plan")
        self.assertIn("acquisition-scout", text)
        self.assertIn("sources/mozi/acquisition_candidates.json", text)
        self.assertIn("禁止网络检索", text)


class WiringTests(unittest.TestCase):
    def test_orchestration_entry_points_mention_the_plan(self):
        for rel in ("commands/distill.md", ".agents/skills/mdf-distill/SKILL.md", "AGENTS.md",
                    "docs/ethics-and-legal.md", "agents/source-researcher.md"):
            with self.subTest(file=rel):
                self.assertIn("acquire-plan", (ROOT / rel).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
