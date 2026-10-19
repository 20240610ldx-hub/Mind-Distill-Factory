"""闸门通过记录：validate package 通过时记下包的指纹，mdf status 不加 --check 也能看见。

2026-10-19 鲁迅 GUI 验收发现 15：包闸门通过、阶段 5 审查也 PASS，不加 --check 的 status 仍停在
「P1–P6 未检查」，阶段卡指回阶段 4。status 只读文件，而「闸门通过」以前不落盘。
"""

from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import gate_records as gr  # noqa: E402
import pipeline_status as ps  # noqa: E402
import validate_output  # noqa: E402

V6_SKILL = "---\nname: demo-wisdom\nformat_version: 6\n---\n\n# 演示\n"


class PackageFixture(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self.out = self.root / "output" / "demo"
        (self.out / "references").mkdir(parents=True)
        (self.out / "SKILL.md").write_text(V6_SKILL, encoding="utf-8")
        for name in ("cases.md", "evidence.md", "voice.md"):
            (self.out / "references" / name).write_text(f"# {name}\n", encoding="utf-8")

    def tearDown(self):
        self._td.cleanup()


class Record(PackageFixture):
    def test_record_is_current_until_a_package_file_changes(self):
        self.assertIsNone(gr.package_gate_current(self.out), "没跑过闸门")
        gr.record_package_gate(self.out)
        self.assertTrue(gr.package_gate_current(self.out))
        (self.out / "references" / "cases.md").write_text("# 改过\n", encoding="utf-8")
        self.assertFalse(gr.package_gate_current(self.out), "闸门之后改过产物，记录作废")

    def test_record_lives_outside_what_gets_published(self):
        path = gr.record_package_gate(self.out)
        self.assertEqual(path.parent.name, gr.RECORD_DIR)
        self.assertNotIn(path, gr.package_files(self.out))


class ValidateWritesTheRecord(PackageFixture):
    def run_validate(self, errors):
        cwd = os.getcwd()
        os.chdir(self.root)
        try:
            with mock.patch.dict(validate_output.STAGES, {"package": lambda slug, **kw: errors}), \
                    mock.patch.object(sys, "argv", ["validate_output.py", "package", "demo"]), \
                    contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as exit_:
                validate_output.main()
        finally:
            os.chdir(cwd)
        return exit_.exception.code

    def test_passing_gate_records_and_failing_gate_does_not(self):
        self.assertEqual(self.run_validate(["P2_FAIL: x"]), 1)
        self.assertIsNone(gr.package_gate_current(self.out))
        self.assertEqual(self.run_validate(["WARNING: 只是警告"]), 0)
        self.assertTrue(gr.package_gate_current(self.out))


class StatusReadsTheRecord(PackageFixture):
    def gates(self):
        return next(s for s in ps.collect_status("demo", self.root) if s.key == "gates")

    def test_status_without_check_trusts_a_current_record(self):
        self.assertEqual(self.gates().state, "pending")
        gr.record_package_gate(self.out)
        step = self.gates()
        self.assertEqual(step.state, "done")
        self.assertIn("产物未改动", step.detail)
        (self.out / "SKILL.md").write_text(V6_SKILL + "改了\n", encoding="utf-8")
        step = self.gates()
        self.assertEqual(step.state, "pending")
        self.assertIn("改过", step.detail)
        self.assertIn("validate package demo", step.next_action)


if __name__ == "__main__":
    unittest.main()
