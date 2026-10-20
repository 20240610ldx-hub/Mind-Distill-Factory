"""发布前就要看得见的两件事（2026-10-20 鲁迅 GUI 复验问题 2、3）。

问题 2：置信度门只在 `mdf publish` 那一刻才拦。状态表的发布行写「⬜ 待办 → mdf publish」，编排者照做
才撞上 BLOCKED_LOW_CONFIDENCE——这是该在发布前问用户的决定（补素材 / 接受不入 gallery / --force）。
问题 3：模板的「质量审查：{review_status}」在 Stage 4 填写，审查在 Stage 5，这行生来就过期；gallery 里
已有「Pending」「待审」「待审核」。审查结论以 manifest / index.json 为准，技能正文不该带流水线状态。
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

import pipeline_status as ps  # noqa: E402
import validate_output as v  # noqa: E402


class PublishRowShowsTheConfidenceGate(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self.out = self.root / "output" / "demo"
        self.out.mkdir(parents=True)

    def tearDown(self):
        self._td.cleanup()

    def publish_row(self, score):
        (self.out / "frameworks.zh.json").write_text(
            json.dumps({"distill_confidence": {"score": score}}), encoding="utf-8")
        return next(s for s in ps.collect_status("demo", self.root) if s.key == "publish")

    def test_low_confidence_is_blocked_before_publish(self):
        row = self.publish_row(2)
        self.assertEqual(row.state, "blocked")
        self.assertIn("distill_confidence", row.detail)
        self.assertIn("2", row.detail)
        self.assertIn("AskUserQuestion", row.next_action)
        self.assertIn("--force", row.next_action)

    def test_passing_confidence_points_at_publish(self):
        row = self.publish_row(4)
        self.assertEqual(row.state, "pending")
        self.assertIn("publish", row.next_action)


class NoPipelineStatusInTheSkill(unittest.TestCase):
    def test_v6_template_has_no_review_status_line(self):
        for name in ("skill-template.v6.zh.md", "skill-template.en.md", "skill-template.zh.md"):
            text = (ROOT / "templates" / name).read_text(encoding="utf-8")
            self.assertNotIn("{review_status}", text, name)

    def test_package_gate_warns_on_a_review_status_line(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "output" / "demo"
            (out / "references").mkdir(parents=True)
            (out / "SKILL.md").write_text("## 溯源信息\n\n质量审查：Stage 5 质量审查待进行\n",
                                          encoding="utf-8", newline="\n")
            cwd = os.getcwd()
            os.chdir(td)
            try:
                errors = v.validate_package("demo")
            finally:
                os.chdir(cwd)
        hits = [e for e in errors if "PKG_REVIEW_STATUS_LINE" in e]
        self.assertEqual(len(hits), 1, errors)
        self.assertTrue(hits[0].startswith("WARNING:"), "提醒，不挡路：旧包里这行无害但会误导")


if __name__ == "__main__":
    unittest.main()
