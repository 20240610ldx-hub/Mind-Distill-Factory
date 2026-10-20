"""闸门通过记录：validate package 通过时记下包的指纹，mdf status 不加 --check 也能看见。

2026-10-19 鲁迅 GUI 验收发现 15：包闸门通过、阶段 5 审查也 PASS，不加 --check 的 status 仍停在
「P1–P6 未检查」，阶段卡指回阶段 4。status 只读文件，而「闸门通过」以前不落盘。
"""

from __future__ import annotations

import contextlib
import io
import json
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
import verify_provenance as prov  # noqa: E402

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

    def test_record_carries_the_coverage_line_forward(self):
        # 发现 11 落到管线：覆盖率不能只在校验器输出里闪一下，状态表和阶段卡要一直看得见
        coverage = "WARNING: P2_COVERAGE: evidence.md: 逐字核对覆盖 12/28 张证据卡；16 张…"
        self.assertEqual(self.run_validate(["WARNING: 只是警告", coverage]), 0)
        self.assertEqual(gr.package_gate_notes(self.out), [coverage.removeprefix("WARNING: ")])
        (self.out / "SKILL.md").write_text(V6_SKILL + "改了\n", encoding="utf-8")
        self.assertEqual(gr.package_gate_notes(self.out), [], "记录作废，附注一起作废")


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

    def test_status_shows_partial_coverage_without_check(self):
        line = prov.EvidenceCoverage(12, 28, 16).warning("evidence.md", "demo")
        gr.record_package_gate(self.out, notes=gr.carried_notes([line]))
        step = self.gates()
        self.assertEqual(step.state, "done", "覆盖不全是警告，不挡路")
        self.assertIn("12/28", step.detail)
        self.assertIn("mdf acquire", step.detail)

    def test_status_shows_partial_coverage_with_check(self):
        coverage = prov.EvidenceCoverage(3, 5, 2).warning("evidence.md", "demo")
        ctx = ps.Ctx(slug="demo", root=self.root, check=True)
        ctx.is_v6 = True
        with mock.patch.object(ps, "_validator") as validator:
            validator.return_value.validate_package = lambda slug: [coverage]
            step = ps._stage_gates(ctx)
        self.assertEqual(step.state, "done")
        self.assertIn("3/5", step.detail)


class CarriedCodesStayInSync(unittest.TestCase):
    def test_gate_records_carries_the_domain_code(self):
        self.assertIn(prov.EvidenceCoverage.CODE, gr.CARRIED_CODES)


class PublishShowsCoverage(PackageFixture):
    """发布后看 gallery 那份包：manifest 的 P2 证明记着逐字覆盖几张，状态表的发布一行要说出来。"""

    def publish_row(self, p2: dict):
        gallery = self.root / "gallery" / "demo"
        gallery.mkdir(parents=True)
        pm = ps._sibling("package_manifest")
        (gallery / pm.MANIFEST_NAME).write_text(json.dumps({
            "manifest_version": pm.MANIFEST_VERSION, "attestation": {"p2": p2},
            "review": {"verdict": "PASS"}}), encoding="utf-8")
        return next(s for s in ps.collect_status("demo", self.root) if s.key == "publish")

    def test_partial_coverage_is_named(self):
        row = self.publish_row({"status": "pass", **prov.EvidenceCoverage(12, 28, 16).to_attestation()})
        self.assertEqual(row.state, "done")
        self.assertIn("12/28", row.detail)

    def test_full_coverage_stays_quiet(self):
        row = self.publish_row({"status": "pass", "cards_verified": 5, "cards_total": 5})
        self.assertNotIn("逐字", row.detail)


if __name__ == "__main__":
    unittest.main()
