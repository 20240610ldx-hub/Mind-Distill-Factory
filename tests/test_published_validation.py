from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from sibling import load_module  # noqa: E402  按路径加载模块的唯一入口（先登记 sys.modules）


validator = load_module(ROOT / "scripts" / "validate_output.py", "validate_output")
pm = load_module(ROOT / "scripts" / "package_manifest.py", "package_manifest")
prov = load_module(ROOT / "scripts" / "verify_provenance.py", "verify_provenance")
# 复用 v6 闸门测试的包夹具；按路径加载、不导入其 TestCase，避免重复收集。
pkg_fixtures = load_module(ROOT / "tests" / "test_package_v6.py", "_package_v6_fixtures")

CASE_INDEX = "## 案例索引\n\n| demo-c1-1 | demo-c1-2 | demo-counter-1 |\n"


def quiet_backfill(*args, **kwargs) -> int:
    with contextlib.redirect_stdout(io.StringIO()):
        return pm.backfill(*args, **kwargs)


def write_index(root: Path, slugs: list[str]) -> None:
    index = {"skills": [{"slug": s, "skill_dir": f"gallery/{s}/"} for s in slugs]}
    (root / "gallery" / "index.json").write_text(json.dumps(index), encoding="utf-8")


class PublishedFixture:
    """搭一个完整、干净的已发布 v6 包，然后删掉 output/ 和 sources/。

    删除是刻意的：published 校验必须只靠 gallery/ 自身通过。
    """

    def __init__(self, td: str):
        self.root = Path(td)
        fx = pkg_fixtures.PackageFixture(td)
        fx.write_skill(pkg_fixtures.build_skill_md(extra=CASE_INDEX))
        self.gallery = self.root / "gallery" / "demo"
        shutil.copytree(fx.out, self.gallery, ignore=shutil.ignore_patterns("framework_core.json"))
        p2 = pm.attest_p2(self.gallery / pm.EVIDENCE_REL, "demo", self.root, prov)
        assert p2["status"] == "pass", p2
        self.manifest = pm.build_manifest(
            self.gallery, "demo", format_version=6, clusters=["cluster_001"], p2_attestation=p2,
        )
        self.save_manifest()
        write_index(self.root, ["demo"])
        shutil.rmtree(self.root / "output")
        shutil.rmtree(self.root / "sources")

    def save_manifest(self) -> None:
        pm.write_manifest(self.gallery / pm.MANIFEST_NAME, self.manifest)

    def validate(self, slug: str = "demo") -> list[str]:
        cwd = os.getcwd()
        try:
            os.chdir(self.root)
            return validator.validate_published(slug)
        finally:
            os.chdir(cwd)


def codes(errors: list[str]) -> list[str]:
    return [e.split(":", 1)[0] for e in errors]


class PublishedV6Tests(unittest.TestCase):
    def test_clean_package_passes_without_output_or_sources(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = PublishedFixture(td)
            self.assertFalse((fx.root / "output").exists())
            self.assertFalse((fx.root / "sources").exists())
            self.assertEqual(fx.validate(), [])

    def test_missing_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = PublishedFixture(td)
            (fx.gallery / pm.MANIFEST_NAME).unlink()
            self.assertIn("MANIFEST_MISSING", codes(fx.validate()))

    def test_v1_manifest_is_outdated(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = PublishedFixture(td)
            (fx.gallery / pm.MANIFEST_NAME).write_text(
                json.dumps({"format_version": 6, "files": fx.manifest["files"]}), encoding="utf-8"
            )
            self.assertIn("MANIFEST_OUTDATED", codes(fx.validate()))

    def test_tampered_skill_md(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = PublishedFixture(td)
            skill = fx.gallery / "SKILL.md"
            skill.write_text(skill.read_text(encoding="utf-8") + "\n追加一行\n", encoding="utf-8")
            self.assertIn("MANIFEST_HASH_MISMATCH", codes(fx.validate()))

    def test_leftover_attachment_from_previous_publish(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = PublishedFixture(td)
            (fx.gallery / "references" / "cases_old.md").write_text("# 旧\n", encoding="utf-8")
            self.assertIn("MANIFEST_UNLISTED_FILE", codes(fx.validate()))

    def test_evidence_edited_after_attestation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = PublishedFixture(td)
            evidence = fx.gallery / pm.EVIDENCE_REL
            evidence.write_text("### 原则 1：甲\n\n> 语料里没有的话\n", encoding="utf-8")
            fx.manifest["files"][pm.EVIDENCE_REL] = pm.sha256_file(evidence)
            fx.save_manifest()
            self.assertIn("MANIFEST_P2_STALE", codes(fx.validate()))

    def test_p4_uses_clusters_from_manifest(self) -> None:
        # 证明 P4 真的读了 manifest 里的簇：多声明一个没有案例的簇，必须报覆盖不足。
        with tempfile.TemporaryDirectory() as td:
            fx = PublishedFixture(td)
            fx.manifest["clusters"] = ["cluster_001", "cluster_002"]
            fx.save_manifest()
            self.assertIn("P4_TOO_FEW_CASES", codes(fx.validate()))

    def test_p6_still_runs_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = PublishedFixture(td)
            skill = fx.gallery / "SKILL.md"
            skill.write_text(
                pkg_fixtures.build_skill_md(sections=pkg_fixtures.CORE_SECTIONS[:-1], extra=CASE_INDEX),
                encoding="utf-8",
            )
            fx.manifest["files"]["SKILL.md"] = pm.sha256_file(skill)
            fx.save_manifest()
            self.assertIn("P6_MISSING_SECTION", codes(fx.validate()))

    def test_manifest_format_must_match_skill(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = PublishedFixture(td)
            fx.manifest["format_version"] = 1
            fx.save_manifest()
            self.assertIn("MANIFEST_FORMAT_MISMATCH", codes(fx.validate()))

    def test_missing_index_entry(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = PublishedFixture(td)
            write_index(fx.root, ["someone-else"])
            self.assertIn("MISSING_GALLERY_INDEX_ENTRY", codes(fx.validate()))


class PublishedLegacyTests(unittest.TestCase):
    SLUG = "chiang-kai-shek"  # 一个结构完整的已提交 legacy 包

    def _stage(self, td: str) -> Path:
        root = Path(td)
        shutil.copytree(ROOT / "gallery" / self.SLUG, root / "gallery" / self.SLUG)
        write_index(root, [self.SLUG])
        return root

    def _validate(self, root: Path) -> list[str]:
        cwd = os.getcwd()
        try:
            os.chdir(root)
            return validator.validate_published(self.SLUG)
        finally:
            os.chdir(cwd)

    def test_legacy_with_hash_manifest_passes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = self._stage(td)
            hard = [e for e in self._validate(root) if not e.startswith("WARNING:")]
            self.assertEqual(hard, [])

    def test_legacy_is_held_to_the_same_manifest_rules(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = self._stage(td)
            (root / "gallery" / self.SLUG / pm.MANIFEST_NAME).unlink()
            self.assertIn("MANIFEST_MISSING", codes(self._validate(root)))


class StageRegistryTests(unittest.TestCase):
    def test_published_stage_and_gallery_alias(self) -> None:
        self.assertIs(validator.STAGES["published"], validator.validate_published)
        self.assertIs(validator.STAGES["gallery"], validator.validate_published)


class CommittedGalleryTests(unittest.TestCase):
    """每个进版本控制的 gallery 包都必须带 v2 manifest，且 hash 与文件一致。

    改了 gallery 里的文件却忘了重发 manifest，这条会立刻失败。只看 MANIFEST_*
    错误：包内容本身的问题（如 charlie-munger 缺章节）不在这条测试的职责里。
    """

    def test_every_committed_package_has_a_consistent_manifest(self) -> None:
        index = json.loads((ROOT / "gallery" / "index.json").read_text(encoding="utf-8"))
        for entry in index["skills"]:
            slug = entry["slug"]
            with self.subTest(slug=slug):
                gallery_dir = ROOT / "gallery" / slug
                manifest, errors = pm.load_manifest(gallery_dir / pm.MANIFEST_NAME)
                self.assertEqual(errors, [])
                self.assertEqual(pm.verify_manifest(gallery_dir, manifest, slug), [])


class BackfillTests(unittest.TestCase):
    def test_legacy_backfill_writes_hash_only_manifest_then_skips(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            legacy = root / "gallery" / "legacy"
            legacy.mkdir(parents=True)
            (legacy / "SKILL.md").write_text("---\nname: legacy-wisdom\n---\n", encoding="utf-8")
            (legacy / "draft.zh.md").write_text("# 草稿\n", encoding="utf-8")
            self.assertEqual(quiet_backfill("legacy", root, root), 0)
            manifest, errors = pm.load_manifest(legacy / pm.MANIFEST_NAME)
            self.assertEqual(errors, [])
            self.assertEqual(sorted(manifest["files"]), ["SKILL.md", "draft.zh.md"])
            self.assertNotIn("review", manifest)  # 不拿 index.json 的 PASS 冒充审查
            before = (legacy / pm.MANIFEST_NAME).read_bytes()
            self.assertEqual(quiet_backfill("legacy", root, root), 0)
            self.assertEqual((legacy / pm.MANIFEST_NAME).read_bytes(), before)

    def test_v6_backfill_refuses_when_p2_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = pkg_fixtures.PackageFixture(td)
            root = fx.root
            gallery = root / "gallery" / "demo"
            shutil.copytree(fx.out, gallery, ignore=shutil.ignore_patterns("framework_core.json"))
            (gallery / pm.EVIDENCE_REL).write_text("### 甲\n\n> 语料里没有的话\n", encoding="utf-8")
            self.assertEqual(quiet_backfill("demo", root, root), 1)
            self.assertFalse((gallery / pm.MANIFEST_NAME).exists())

    def test_v6_backfill_requires_framework_core(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = pkg_fixtures.PackageFixture(td)
            gallery = fx.root / "gallery" / "demo"
            shutil.copytree(fx.out, gallery)
            (fx.out / "framework_core.json").unlink()
            self.assertEqual(quiet_backfill("demo", fx.root, fx.root), 1)

    def test_v6_backfill_attests_and_records_clusters(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = pkg_fixtures.PackageFixture(td)
            gallery = fx.root / "gallery" / "demo"
            shutil.copytree(fx.out, gallery, ignore=shutil.ignore_patterns("framework_core.json"))
            self.assertEqual(quiet_backfill("demo", fx.root, fx.root), 0)
            manifest, _ = pm.load_manifest(gallery / pm.MANIFEST_NAME)
            self.assertEqual(manifest["clusters"], ["cluster_001"])
            self.assertEqual(manifest["attestation"]["p2"]["status"], "pass")
            self.assertEqual(manifest["review"]["verdict"], "MISSING")


if __name__ == "__main__":
    unittest.main()
