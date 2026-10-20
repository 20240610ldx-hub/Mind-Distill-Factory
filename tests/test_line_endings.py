"""包里的 Markdown 必须是 LF：manifest 按字节记 hash，入库时 .gitattributes（eol=lf）会把 CRLF 改掉。

2026-10-20 在 GUI 里按 distill.md 实跑鲁迅附件回写时，子代理发现上游的 cases.md 是 CRLF（465 处），
包闸门照样通过。发布后一入库，gallery 里的字节就和 manifest 的 hash 对不上——此前只有简报里一句
「写 LF」挡着，没有确定性检查。
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import validate_output as v  # noqa: E402


class LineEndings(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self.out = self.root / "output" / "demo"
        (self.out / "references").mkdir(parents=True)
        (self.out / "SKILL.md").write_bytes(b"---\nname: demo-wisdom\nformat_version: 6\n---\n")
        (self.out / "references" / "evidence.md").write_bytes(b"# evidence\n")

    def tearDown(self):
        self._td.cleanup()

    def test_crlf_in_a_reference_is_a_hard_error(self):
        (self.out / "references" / "cases.md").write_bytes(b"# cases\r\n\r\n### a\r\n")
        errors = v.check_line_endings(self.out)
        self.assertEqual(len(errors), 1, errors)
        self.assertTrue(errors[0].startswith("PKG_CRLF"))
        self.assertIn("cases.md", errors[0])
        self.assertIn("3", errors[0])  # 说出有几处，方便判断是整份还是零星

    def test_dossier_is_published_too(self):
        (self.out / "人物档案.md").write_bytes(b"# x\r\n")
        self.assertTrue(any("人物档案.md" in e for e in v.check_line_endings(self.out)))

    def test_lf_package_is_clean(self):
        (self.out / "references" / "cases.md").write_bytes(b"# cases\n")
        self.assertEqual(v.check_line_endings(self.out), [])

    def test_package_gate_runs_the_check(self):
        (self.out / "references" / "cases.md").write_bytes(b"# cases\r\n")
        cwd = os.getcwd()
        os.chdir(self.root)
        try:
            errors = v.validate_package("demo")
        finally:
            os.chdir(cwd)
        self.assertTrue(any(e.startswith("PKG_CRLF") for e in errors), errors)


if __name__ == "__main__":
    unittest.main()
