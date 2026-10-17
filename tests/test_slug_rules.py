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


slugs = load_module("slug_rules", ROOT / "scripts" / "slug_rules.py")

MUST_REJECT = [
    "",
    " ",
    ".",
    "..",
    "../etc",
    "a/b",
    "a\\b",
    "/abs",
    "C:\\x",
    "sun\u3000tzu",      # 全角空格
    "sun\u00a0tzu",      # 不换行空格
    "sun\ttzu",
    "sun tzu",
    "sun-tzu\n",
    "..\\..\\windows",
]


class ValidateSlugTests(unittest.TestCase):
    def test_rejects_unsafe_inputs(self) -> None:
        for raw in MUST_REJECT:
            with self.subTest(raw=raw):
                with self.assertRaises(slugs.InvalidSlug):
                    slugs.validate_slug(raw)

    def test_invalid_slug_is_a_value_error(self) -> None:
        self.assertTrue(issubclass(slugs.InvalidSlug, ValueError))

    def test_accepts_every_committed_gallery_slug(self) -> None:
        # 回归护栏：规则收紧时不能把已发布的 skill 判成非法。
        index = json.loads((ROOT / "gallery" / "index.json").read_text(encoding="utf-8"))
        for entry in index["skills"]:
            with self.subTest(slug=entry["slug"]):
                self.assertEqual(slugs.validate_slug(entry["slug"]), entry["slug"])

    def test_accepts_canonical_examples_unchanged(self) -> None:
        for raw in ("charlie-munger", "sun-tzu", "zhang-juzheng-v6", "seneca"):
            with self.subTest(raw=raw):
                self.assertEqual(slugs.validate_slug(raw), raw)

    def test_rejects_instead_of_normalizing(self) -> None:
        for raw in ("Seneca", "seneca ", " seneca", "SUN-TZU"):
            with self.subTest(raw=raw):
                with self.assertRaises(slugs.InvalidSlug):
                    slugs.validate_slug(raw)

    def test_rejects_malformed_hyphenation_and_foreign_chars(self) -> None:
        for raw in ("-seneca", "seneca-", "sun--tzu", "sun_tzu", "sun.tzu", "a:b", "sun​tzu", "孙子", "ｓｅｎｅｃａ"):
            with self.subTest(raw=raw):
                with self.assertRaises(slugs.InvalidSlug):
                    slugs.validate_slug(raw)

    def test_rejects_windows_reserved_names(self) -> None:
        for raw in ("con", "prn", "aux", "nul", "com1", "com9", "lpt1", "lpt9"):
            with self.subTest(raw=raw):
                with self.assertRaises(slugs.InvalidSlug):
                    slugs.validate_slug(raw)

    def test_reserved_name_as_segment_is_allowed(self) -> None:
        # 保留的只是整个路径段；con-wisdom、com10 都能正常建目录。
        for raw in ("con-wisdom", "nul-hypothesis", "com10", "console"):
            with self.subTest(raw=raw):
                self.assertEqual(slugs.validate_slug(raw), raw)

    def test_length_cap_is_64(self) -> None:
        self.assertEqual(slugs.validate_slug("a" * 64), "a" * 64)
        with self.assertRaises(slugs.InvalidSlug):
            slugs.validate_slug("a" * 65)

    def test_rejects_non_string(self) -> None:
        for raw in (None, 42, b"seneca"):
            with self.subTest(raw=raw):
                with self.assertRaises(slugs.InvalidSlug):
                    slugs.validate_slug(raw)  # type: ignore[arg-type]


class SlugDirTests(unittest.TestCase):
    def test_returns_child_of_base(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            self.assertEqual(slugs.slug_dir(base, "sun-tzu"), base / "sun-tzu")

    def test_rejects_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(slugs.InvalidSlug):
                slugs.slug_dir(Path(td), "../escape")


class EntryPointTests(unittest.TestCase):
    """每个把 slug 拼进路径的 CLI 都必须在碰文件系统之前拒绝非法 slug。"""

    PROBE = "../__slug_probe__"

    CASES = [
        (["scripts/validate_output.py", "package", PROBE], 1),
        (["scripts/publish_skill.py", "--slug", PROBE, "--dry-run"], 2),
        (["scripts/publish_skill.py", "--slug", "Seneca", "--dry-run"], 2),
        (["scripts/local_source_pipeline.py", "index", PROBE], 2),
        (["scripts/local_source_pipeline.py", "reduce", PROBE], 2),
        (["scripts/local_source_pipeline.py", "stats", PROBE], 2),
        (["scripts/task_status.py", "init", "stage1a", PROBE], 2),
        (["scripts/build_framework_core.py", PROBE], 1),
    ]

    def test_cli_rejects_bad_slug_before_touching_disk(self) -> None:
        import subprocess
        import sys

        for argv, expected_code in self.CASES:
            with self.subTest(argv=argv):
                proc = subprocess.run(
                    [sys.executable, *argv], cwd=ROOT, capture_output=True,
                    text=True, encoding="utf-8", errors="replace", timeout=60,
                )
                self.assertEqual(proc.returncode, expected_code, proc.stdout + proc.stderr)
                self.assertIn("slug", (proc.stdout + proc.stderr).lower())
                self.assertFalse((ROOT / "__slug_probe__").exists())
                self.assertFalse((ROOT.parent / "__slug_probe__").exists())


if __name__ == "__main__":
    unittest.main()
