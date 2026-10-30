"""gallery 全量 published 校验（scripts/validate_gallery_all.py）的例外清单行为。"""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from sibling import load_module  # noqa: E402  按路径加载模块的唯一入口（先登记 sys.modules）

gallery_all = load_module(ROOT / "scripts" / "validate_gallery_all.py", "validate_gallery_all")
# 复用 published 校验测试的干净包夹具；按路径加载、不导入其 TestCase，避免重复收集。
published_fixtures = load_module(ROOT / "tests" / "test_published_validation.py", "_published_fixtures")


def run_check(root: Path, exceptions: dict[str, str]) -> tuple[list[str], list[str]]:
    with contextlib.redirect_stdout(io.StringIO()):
        return gallery_all.check_gallery(root, exceptions)


class CheckGalleryTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.fx = published_fixtures.PublishedFixture(self._td.name)

    def break_package(self):
        skill = self.fx.gallery / "SKILL.md"
        skill.write_text(skill.read_text(encoding="utf-8") + "\n篡改\n", encoding="utf-8")

    def test_clean_package_passes(self):
        self.assertEqual(run_check(self.fx.root, {}), ([], []))

    def test_broken_package_fails(self):
        self.break_package()
        failures, notices = run_check(self.fx.root, {})
        self.assertEqual(len(failures), 1)
        self.assertTrue(failures[0].startswith("demo:"))
        self.assertEqual(notices, [])

    def test_broken_known_exception_is_not_a_failure(self):
        self.break_package()
        self.assertEqual(run_check(self.fx.root, {"demo": "legacy"}), ([], []))

    def test_passing_known_exception_asks_for_removal(self):
        failures, notices = run_check(self.fx.root, {"demo": "legacy"})
        self.assertEqual(failures, [])
        self.assertEqual(len(notices), 1)
        self.assertIn("demo", notices[0])
        self.assertIn("KNOWN_EXCEPTIONS", notices[0])

    def test_exception_missing_from_gallery_asks_for_removal(self):
        failures, notices = run_check(self.fx.root, {"ghost": "legacy"})
        self.assertEqual(failures, [])
        self.assertEqual(len(notices), 1)
        self.assertIn("ghost", notices[0])

    def test_empty_gallery_fails(self):
        with tempfile.TemporaryDirectory() as td:
            failures, _ = run_check(Path(td), {})
        self.assertEqual(len(failures), 1)


class ExceptionListTests(unittest.TestCase):
    def test_every_exception_has_reason_and_exists(self):
        for slug, reason in gallery_all.KNOWN_EXCEPTIONS.items():
            self.assertTrue(reason.strip(), slug)
            self.assertTrue((ROOT / "gallery" / slug).is_dir(), slug)

    def test_charlie_munger_is_the_only_exception(self):
        self.assertEqual(set(gallery_all.KNOWN_EXCEPTIONS), {"charlie-munger"})

    def test_workflow_does_not_list_exceptions(self):
        workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
        self.assertIn("scripts/validate_gallery_all.py", workflow)
        for slug in gallery_all.KNOWN_EXCEPTIONS:
            self.assertNotIn(slug, workflow)


if __name__ == "__main__":
    unittest.main()
