"""附件阶段恢复执行时，待办只派缺的那一份。

2026-10-19 为 PR #11 实跑 `mdf run lu-xun attachments` 前发现：cases.md、evidence.md 已经齐了，只差
voice.md 与案例索引回写，简报的「待办」却仍是「派发 case-builder / evidence-carder，再由 skill-assembler…」。
新进程照着做就会重做两份已有的附件——白花钱，还可能覆盖已经过审的产物。
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import pipeline_status as ps  # noqa: E402

V6_SKILL = "---\nname: demo-wisdom\nformat_version: 6\n---\n\n# 演示\n"


class AttachmentsResume(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self.refs = self.root / "output" / "demo" / "references"
        self.refs.mkdir(parents=True)
        (self.root / "output" / "demo" / "SKILL.md").write_text(V6_SKILL, encoding="utf-8")

    def tearDown(self):
        self._td.cleanup()

    def step(self, *present: str):
        for name in present:
            (self.refs / name).write_text(f"# {name}\n", encoding="utf-8")
        return next(s for s in ps.collect_status("demo", self.root) if s.key == "attachments")

    def test_only_voice_missing_dispatches_only_the_assembler(self):
        step = self.step("cases.md", "evidence.md")
        self.assertNotIn("case-builder", step.next_action)
        self.assertNotIn("evidence-carder", step.next_action)
        self.assertIn("skill-assembler", step.next_action)
        self.assertIn("案例索引", step.next_action)
        self.assertIn("不要重做", step.next_action)

    def test_nothing_present_dispatches_everyone(self):
        step = self.step()
        for role in ("case-builder", "evidence-carder", "skill-assembler"):
            self.assertIn(role, step.next_action)

    def test_missing_evidence_names_the_carder_and_keeps_the_rest(self):
        step = self.step("cases.md", "voice.md")
        self.assertIn("evidence-carder", step.next_action)
        self.assertNotIn("case-builder", step.next_action)


if __name__ == "__main__":
    unittest.main()
