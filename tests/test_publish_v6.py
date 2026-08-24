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


class InstallWhitelistTests(unittest.TestCase):
    def test_dossier_is_not_in_install_whitelist(self) -> None:
        self.assertNotIn("人物档案.md", publisher.INSTALL_WHITELIST)

    def test_whitelist_contains_skill_and_references(self) -> None:
        self.assertIn("SKILL.md", publisher.INSTALL_WHITELIST)
        self.assertIn("references", publisher.INSTALL_WHITELIST)


class ManifestTests(unittest.TestCase):
    def test_manifest_lists_every_copied_file_with_hash(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out = build_v6_output(root)
            gallery = root / "gallery" / "demo"
            copied = publisher.copy_package(out, gallery, is_v6=True)
            manifest_path = publisher.write_manifest(gallery, copied)
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
            first = json.loads(publisher.write_manifest(gallery, copied).read_text(encoding="utf-8"))
            (gallery / "references" / "cases.md").write_text("# changed\n", encoding="utf-8")
            second = json.loads(publisher.write_manifest(gallery, copied).read_text(encoding="utf-8"))
            self.assertNotEqual(
                first["files"]["references/cases.md"], second["files"]["references/cases.md"]
            )


if __name__ == "__main__":
    unittest.main()
