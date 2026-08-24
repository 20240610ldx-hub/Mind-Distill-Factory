from __future__ import annotations

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
validator = load_module("validate_output", ROOT / "scripts" / "validate_output.py")


def build_v6_output(root: Path) -> Path:
    out = root / "output" / "demo"
    refs = out / "references"
    refs.mkdir(parents=True)
    (out / "SKILL.md").write_text(
        "---\nname: demo-wisdom\nformat_version: 6\n---\n\n# 示例\n", encoding="utf-8"
    )
    for name in ("cases.md", "evidence.md", "voice.md"):
        (refs / name).write_text(f"# {name}\n", encoding="utf-8")
    (out / "人物档案.md").write_text("# 档案\n", encoding="utf-8")
    return out


class CopyPackageTests(unittest.TestCase):
    def test_copies_skill_and_all_references(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out = build_v6_output(root)
            gallery = root / "gallery" / "demo"
            copied = publisher.copy_package(out, gallery, is_v6=True)
            self.assertIn("SKILL.md", copied)
            self.assertIn("references/cases.md", copied)
            self.assertTrue((gallery / "references" / "voice.md").exists())

    def test_copies_dossier_into_gallery(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out = build_v6_output(root)
            gallery = root / "gallery" / "demo"
            publisher.copy_package(out, gallery, is_v6=True)
            self.assertTrue((gallery / "人物档案.md").exists())

    def test_legacy_copies_only_skill_md(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out = root / "output" / "demo"
            out.mkdir(parents=True)
            (out / "SKILL.md").write_text("---\nname: demo-wisdom\n---\n", encoding="utf-8")
            gallery = root / "gallery" / "demo"
            copied = publisher.copy_package(out, gallery, is_v6=False)
            self.assertEqual(copied, ["SKILL.md"])


class IsV6PackageTests(unittest.TestCase):
    def test_is_v6_package_agrees_with_validator_on_legacy_doc_mentioning_v6(self) -> None:
        content = (
            "---\nname: demo-wisdom\n"
            "description: Apply demo frameworks. 运用示例框架。\n---\n\n"
            "# Language Detection · 语言检测\n\n"
            "## English\n\n### Identity Card\n略\n\n"
            "Example v6 frontmatter:\n\n```yaml\nformat_version: 6\n```\n\n"
            "## 中文版\n\n### 身份卡\n略\n"
        )
        with tempfile.TemporaryDirectory() as td:
            skill_md = Path(td) / "SKILL.md"
            skill_md.write_text(content, encoding="utf-8")
            self.assertFalse(publisher.is_v6_package(skill_md))
            self.assertEqual(publisher.is_v6_package(skill_md), validator.is_v6_skill(content))

    def test_is_v6_package_accepts_whitespace_variants(self) -> None:
        space_before_colon = (
            "---\nname: demo-wisdom\nformat_version : 6\n"
            "description: 示例。触发：示例。\n---\n\n# 标题\n"
        )
        indented = (
            "---\nname: demo-wisdom\n  format_version: 6\n"
            "description: 示例。触发：示例。\n---\n\n# 标题\n"
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path_a = root / "space.md"
            path_a.write_text(space_before_colon, encoding="utf-8")
            path_b = root / "indented.md"
            path_b.write_text(indented, encoding="utf-8")
            self.assertTrue(publisher.is_v6_package(path_a))
            self.assertTrue(publisher.is_v6_package(path_b))


class InstallIsManualNotScriptedTests(unittest.TestCase):
    """install_paths()/INSTALL_WHITELIST used to sit in publish_skill.py entirely
    unwired — main() never called install_paths(), so the whitelist it encoded was
    dead code exercised only by tests. The real ~/.claude/skills/ install is done by
    hand in commands/distill.md Sec 6.3 (same SKILL.md + references/ whitelist,
    stated in prose there). Chosen over wiring install_paths() in: doing so would make
    this script write outside the repo into the user's real ~/.claude/skills/
    directory — a materially larger behavior change than a review fix-wave should
    introduce, and untested here."""

    def test_install_paths_helper_removed(self) -> None:
        self.assertFalse(hasattr(publisher, "install_paths"))
        self.assertFalse(hasattr(publisher, "INSTALL_WHITELIST"))


class ManifestTests(unittest.TestCase):
    def test_manifest_lists_every_copied_file_with_hash(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out = build_v6_output(root)
            gallery = root / "gallery" / "demo"
            copied = publisher.copy_package(out, gallery, is_v6=True)
            manifest_path = publisher.write_manifest(gallery, copied, is_v6=True)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(sorted(manifest["files"].keys()), sorted(copied))
            for digest in manifest["files"].values():
                self.assertEqual(len(digest), 64)

    def test_manifest_hash_changes_when_a_reference_changes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out = build_v6_output(root)
            gallery = root / "gallery" / "demo"
            copied = publisher.copy_package(out, gallery, is_v6=True)
            first = json.loads(
                publisher.write_manifest(gallery, copied, is_v6=True).read_text(encoding="utf-8")
            )
            (gallery / "references" / "cases.md").write_text("# changed\n", encoding="utf-8")
            second = json.loads(
                publisher.write_manifest(gallery, copied, is_v6=True).read_text(encoding="utf-8")
            )
            self.assertNotEqual(
                first["files"]["references/cases.md"], second["files"]["references/cases.md"]
            )

    def test_manifest_records_format_version_1_for_legacy_publish(self) -> None:
        # Regression: write_manifest used to hardcode "format_version": 6
        # unconditionally, even for a legacy (non-v6) publish — contradicting the
        # same run's own stdout ("format_version=legacy") and gallery/index.json's
        # "format_version": 1 for the identical publish.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out = root / "output" / "demo"
            out.mkdir(parents=True)
            (out / "SKILL.md").write_text("---\nname: demo-wisdom\n---\n", encoding="utf-8")
            gallery = root / "gallery" / "demo"
            copied = publisher.copy_package(out, gallery, is_v6=False)
            manifest_path = publisher.write_manifest(gallery, copied, is_v6=False)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["format_version"], 1)


V6_SKILL = """---
name: demo-wisdom
format_version: 6
description: >-
  运用示例人物的框架处理决策问题。触发：示例。
---

# 张居正的思维框架

## 身份卡

| 字段 | 值 |
|------|------|
| 时代 | 明代中后期；万历朝内阁首辅。 |
| 主类 | 治理 (governance) |
| 副类 | 经营 (enterprise)、谋略 (strategy) |
| 核心张力 | 实效与人伦。 |
| 一句话哲学 | 把命令钉死在实效上。 |

## 核心原则

正文。
"""

BARE_V6_SKILL = """---
name: demo-wisdom
format_version: 6
---

# 某人的思维框架
"""


class ExtractV6MetadataTests(unittest.TestCase):
    """v6 包没有 frameworks.zh.json——元数据源于 frontmatter / H1 / 身份卡。"""

    def _write(self, td: str, text: str = V6_SKILL) -> Path:
        path = Path(td) / "SKILL.md"
        path.write_text(text, encoding="utf-8")
        return path

    def test_reads_person_name_from_h1_title(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            meta = publisher.extract_v6_metadata(self._write(td))
            self.assertEqual(meta["person_name"], "张居正")

    def test_reads_era_from_identity_card(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            meta = publisher.extract_v6_metadata(self._write(td))
            self.assertEqual(meta["era"], "明代中后期；万历朝内阁首辅。")

    def test_reads_primary_category_id_from_parenthetical(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            meta = publisher.extract_v6_metadata(self._write(td))
            self.assertEqual(meta["primary_category"], "governance")

    def test_reads_all_secondary_category_ids(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            meta = publisher.extract_v6_metadata(self._write(td))
            self.assertEqual(meta["secondary_categories"], ["enterprise", "strategy"])

    def test_missing_identity_card_yields_safe_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            meta = publisher.extract_v6_metadata(self._write(td, BARE_V6_SKILL))
            self.assertEqual(meta["era"], "Unknown")
            self.assertEqual(meta["primary_category"], "philosophy")
            self.assertEqual(meta["secondary_categories"], [])


class ResolveMetadataTests(unittest.TestCase):
    """发布入口按格式取元数据：v6 走 SKILL.md，legacy 仍走 frameworks.zh.json。"""

    def test_v6_package_resolves_without_frameworks_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "output" / "demo"
            out.mkdir(parents=True)
            (out / "SKILL.md").write_text(V6_SKILL, encoding="utf-8")
            meta = publisher.resolve_metadata(out, "zhang-juzheng-v6")
            self.assertEqual(meta["name_zh"], "张居正")
            self.assertEqual(meta["primary_cat"], "governance")
            self.assertEqual(meta["secondary_cats"], ["enterprise", "strategy"])

    def test_legacy_package_still_reads_frameworks_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "output" / "demo"
            out.mkdir(parents=True)
            (out / "SKILL.md").write_text("---\nname: demo-wisdom\n---\n\n# 忽略\n", encoding="utf-8")
            (out / "frameworks.zh.json").write_text(
                json.dumps({
                    "person_name": "李四",
                    "person_name_original": "李四",
                    "era": "唐代",
                    "primary_category": "conduct",
                    "secondary_categories": ["philosophy"],
                }, ensure_ascii=False),
                encoding="utf-8",
            )
            meta = publisher.resolve_metadata(out, "demo")
            self.assertEqual(meta["name_zh"], "李四")
            self.assertEqual(meta["era"], "唐代")
            self.assertEqual(meta["primary_cat"], "conduct")

    def test_legacy_package_without_frameworks_json_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "output" / "demo"
            out.mkdir(parents=True)
            (out / "SKILL.md").write_text("---\nname: demo-wisdom\n---\n", encoding="utf-8")
            self.assertIsNone(publisher.resolve_metadata(out, "demo"))


if __name__ == "__main__":
    unittest.main()
