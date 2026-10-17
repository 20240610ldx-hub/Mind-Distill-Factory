from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


publisher = load_module("publish_skill", ROOT / "scripts" / "publish_skill.py")
pkg_fixtures = load_module("_package_v6_fixtures_tx", ROOT / "tests" / "test_package_v6.py")

CASE_INDEX = "## 案例索引\n\n| demo-c1-1 | demo-c1-2 | demo-counter-1 |\n"
META = {
    "name_zh": "示例", "name_en": "Demo", "name_original": "示例", "era": "当代",
    "primary_cat": "governance", "secondary_cats": [],
}


def snapshot(directory: Path) -> dict[str, str]:
    """目录树快照：相对路径 → sha256。用来断言「回滚后逐字节不变」。"""
    if not directory.exists():
        return {}
    return {
        p.relative_to(directory).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(directory.rglob("*")) if p.is_file()
    }


def leftovers(gallery_root: Path) -> list[str]:
    return sorted(p.name for p in gallery_root.iterdir() if p.name.startswith("."))


class Workspace:
    """临时仓库根：output/demo 是一个能完整通过 published 校验的 v6 包。"""

    def __init__(self, td: str):
        self.fx = pkg_fixtures.PackageFixture(td)
        self.fx.write_skill(pkg_fixtures.build_skill_md(extra=CASE_INDEX))
        self.root = self.fx.root
        self.out = self.fx.out
        self.gallery_root = self.root / "gallery"
        self.final = self.gallery_root / "demo"
        self.index = self.gallery_root / "index.json"

    def publish(self, review_status: str = "PASS", skill_dir: str | None = None) -> list[str]:
        def update(index: dict) -> None:
            entry = publisher.apply_index_entry(index, "demo", META, True, review_status, None, "2026-10-17")
            if skill_dir is not None:
                entry["skill_dir"] = skill_dir

        return publisher.publish_transaction(self.root, "demo", self.out, True, update)


class SuccessfulPublishTests(unittest.TestCase):
    def test_fresh_publish_creates_package_index_and_no_leftovers(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ws = Workspace(td)
            ws.publish(review_status="FORCED")
            self.assertTrue((ws.final / "manifest.json").exists())
            self.assertTrue((ws.final / "references" / "evidence.md").exists())
            entry = json.loads(ws.index.read_text(encoding="utf-8"))["skills"][0]
            self.assertEqual(entry["review_status"], "FORCED")
            self.assertEqual(leftovers(ws.gallery_root), [])

    def test_republish_drops_attachment_removed_from_output(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ws = Workspace(td)
            extra = ws.out / "references" / "extra.md"
            extra.write_text("# 旧附件\n", encoding="utf-8")
            ws.publish()
            self.assertTrue((ws.final / "references" / "extra.md").exists())
            extra.unlink()
            ws.publish()
            self.assertFalse((ws.final / "references" / "extra.md").exists())
            self.assertEqual(leftovers(ws.gallery_root), [])

    def test_index_is_written_with_lf_newlines(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ws = Workspace(td)
            ws.publish()
            self.assertNotIn(b"\r\n", ws.index.read_bytes())


class RollbackTests(unittest.TestCase):
    def _published_baseline(self, td: str) -> tuple[Workspace, dict, bytes]:
        ws = Workspace(td)
        ws.publish()
        return ws, snapshot(ws.final), ws.index.read_bytes()

    def test_staging_validation_failure_leaves_gallery_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ws, before, index_before = self._published_baseline(td)
            ws.fx.write_skill(pkg_fixtures.build_skill_md(sections=pkg_fixtures.CORE_SECTIONS[:-1], extra=CASE_INDEX))
            with self.assertRaises(publisher.PublishError) as ctx:
                ws.publish()
            self.assertTrue(any(e.startswith("P6_MISSING_SECTION") for e in ctx.exception.errors))
            self.assertEqual(snapshot(ws.final), before)
            self.assertEqual(ws.index.read_bytes(), index_before)
            self.assertEqual(leftovers(ws.gallery_root), [])

    def test_post_commit_validation_failure_restores_old_package_and_index(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ws, before, index_before = self._published_baseline(td)
            (ws.out / "references" / "voice.md").write_text("### 新样本\n\n> 新\n", encoding="utf-8")
            with self.assertRaises(publisher.PublishError) as ctx:
                ws.publish(skill_dir="gallery/elsewhere/")  # 提交后 index 校验必然失败
            self.assertTrue(any("INVALID_GALLERY_INDEX_ENTRY" in e for e in ctx.exception.errors))
            self.assertEqual(snapshot(ws.final), before)
            self.assertEqual(ws.index.read_bytes(), index_before)
            self.assertEqual(leftovers(ws.gallery_root), [])

    def test_crash_at_index_replace_restores_old_package(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ws, before, index_before = self._published_baseline(td)
            (ws.out / "references" / "voice.md").write_text("### 新样本\n\n> 新\n", encoding="utf-8")
            real_replace = publisher._replace_with_retry

            def failing_replace(src: Path, dst: Path, *a, **kw) -> None:
                if dst.name == "index.json" and src.name.startswith(".index-"):
                    raise OSError("模拟：index 替换时磁盘出错")
                real_replace(src, dst, *a, **kw)

            publisher._replace_with_retry = failing_replace
            try:
                with self.assertRaises(OSError):
                    ws.publish()
            finally:
                publisher._replace_with_retry = real_replace
            self.assertEqual(snapshot(ws.final), before)
            self.assertEqual(ws.index.read_bytes(), index_before)
            self.assertEqual(leftovers(ws.gallery_root), [])

    def test_failed_first_publish_leaves_no_package_and_no_index(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ws = Workspace(td)
            with self.assertRaises(publisher.PublishError):
                ws.publish(skill_dir="gallery/elsewhere/")
            self.assertFalse(ws.final.exists())
            self.assertFalse(ws.index.exists())
            self.assertEqual(leftovers(ws.gallery_root), [])


class RecoverInterruptedTests(unittest.TestCase):
    """模拟进程在各个时间点被杀后留下的残局。"""

    def _dir(self, path: Path, marker: str) -> None:
        path.mkdir(parents=True)
        (path / "SKILL.md").write_text(marker, encoding="utf-8")

    def test_killed_between_the_two_renames_restores_backup(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            g = Path(td)
            self._dir(g / ".backup-demo-aaaa", "旧")
            (g / ".index-demo.json.tmp").write_text("{}", encoding="utf-8")
            publisher.recover_interrupted(g, "demo")
            self.assertEqual((g / "demo" / "SKILL.md").read_text(encoding="utf-8"), "旧")
            self.assertEqual(leftovers(g), [])

    def test_killed_before_commit_point_rolls_back(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            g = Path(td)
            self._dir(g / "demo", "新")
            self._dir(g / ".backup-demo-aaaa", "旧")
            (g / ".index-demo.json.tmp").write_text("{}", encoding="utf-8")
            publisher.recover_interrupted(g, "demo")
            self.assertEqual((g / "demo" / "SKILL.md").read_text(encoding="utf-8"), "旧")
            self.assertEqual(leftovers(g), [])

    def test_killed_after_commit_point_keeps_new_package(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            g = Path(td)
            self._dir(g / "demo", "新")
            self._dir(g / ".backup-demo-aaaa", "旧")
            publisher.recover_interrupted(g, "demo")
            self.assertEqual((g / "demo" / "SKILL.md").read_text(encoding="utf-8"), "新")
            self.assertEqual(leftovers(g), [])

    def test_killed_during_staging_keeps_untouched_package(self) -> None:
        # 阶段 1 末尾已写临时 index、但旧包还没被改名：不能把旧包当成新包回滚掉。
        with tempfile.TemporaryDirectory() as td:
            g = Path(td)
            self._dir(g / "demo", "旧")
            self._dir(g / ".staging-demo-bbbb", "新")
            (g / ".index-demo.json.tmp").write_text("{}", encoding="utf-8")
            publisher.recover_interrupted(g, "demo")
            self.assertEqual((g / "demo" / "SKILL.md").read_text(encoding="utf-8"), "旧")
            self.assertEqual(leftovers(g), [])

    def test_other_slugs_are_left_alone(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            g = Path(td)
            self._dir(g / ".backup-other-aaaa", "别人的")
            publisher.recover_interrupted(g, "demo")
            self.assertTrue((g / ".backup-other-aaaa").exists())


class ReviewGateTests(unittest.TestCase):
    # (verdict, force) → (允许发布, review_status)
    TABLE = {
        ("PASS", False): (True, "PASS"),
        ("PASS", True): (True, "PASS"),
        ("REVISE", False): (False, "BLOCKED_REVISE"),
        ("REVISE", True): (True, "FORCED_REVISE"),
        ("MISSING", False): (False, "BLOCKED_MISSING"),
        ("MISSING", True): (True, "FORCED_MISSING"),
        ("FAIL", False): (False, "BLOCKED_FAIL"),
        ("FAIL", True): (False, "BLOCKED_FAIL"),
        ("UNPARSEABLE", False): (False, "BLOCKED_UNPARSEABLE"),
        ("UNPARSEABLE", True): (False, "BLOCKED_UNPARSEABLE"),
    }

    def test_policy_table(self) -> None:
        for (verdict, force), expected in self.TABLE.items():
            with self.subTest(verdict=verdict, force=force):
                self.assertEqual(publisher.review_gate(verdict, force), expected)

    def test_covers_every_verdict_the_parser_can_emit(self) -> None:
        pm = load_module("_pm_for_gate", ROOT / "scripts" / "package_manifest.py")
        self.assertEqual({v for v, _ in self.TABLE}, set(pm.REVIEW_VERDICTS))

    def test_unknown_verdict_is_refused_even_with_force(self) -> None:
        for verdict in ("pass", "LGTM", ""):
            with self.subTest(verdict=verdict):
                allowed, _ = publisher.review_gate(verdict, True)
                self.assertFalse(allowed)

    def test_forced_status_is_never_plain_pass(self) -> None:
        # M4 的 --strict 靠 review_status == "PASS" 判断是否真审过。
        for (verdict, force), (allowed, status) in self.TABLE.items():
            if allowed and verdict != "PASS":
                with self.subTest(verdict=verdict):
                    self.assertNotEqual(status, "PASS")


class ApplyIndexEntryTests(unittest.TestCase):
    def test_new_entry_has_review_status_and_v6_fields(self) -> None:
        index: dict = {}
        entry = publisher.apply_index_entry(index, "demo", META, True, "FORCED", None, "2026-10-17")
        self.assertEqual(index["skills"], [entry])
        self.assertEqual(entry["review_status"], "FORCED")
        self.assertEqual(entry["lang"], "zh")
        self.assertEqual(entry["skill_dir"], "gallery/demo/")

    def test_update_keeps_existing_notes_unless_given(self) -> None:
        index = {"skills": [{"slug": "demo", "notes": "手写备注"}]}
        publisher.apply_index_entry(index, "demo", META, False, "PASS", None, "2026-10-17")
        self.assertEqual(index["skills"][0]["notes"], "手写备注")
        self.assertNotIn("lang", index["skills"][0])
        publisher.apply_index_entry(index, "demo", META, False, "PASS", "新备注", "2026-10-17")
        self.assertEqual(index["skills"][0]["notes"], "新备注")


if __name__ == "__main__":
    unittest.main()
