"""负例夹具（evaluation/fixtures/negative）：每个负例都被闸门拦下，阳性对照零错误，且运行器本身会报红。"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


neg = load_module("_negative_fixtures_under_test", ROOT / "evaluation" / "scripts" / "check_negative_fixtures.py")


class NegativeFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = neg.run()

    def test_positive_control_is_clean_in_both_modes(self):
        self.assertEqual([c["codes"] for c in self.report["controls"]], [[], []])

    def test_every_fixture_is_caught(self):
        missed = [(r["id"], r["missing"]) for r in self.report["fixtures"] if not r["caught"]]
        self.assertEqual(missed, [])
        self.assertTrue(self.report["ok"])

    def test_covers_each_gate_family(self):
        expected = {code for f in neg.load_manifest()["fixtures"] for code in f["expect"]}
        prefixes = {code.split("_")[0] for code in expected}
        self.assertTrue({"P1", "P2", "P6", "VOICE", "QUOTE", "LIVING", "STRICT"} <= prefixes, prefixes)

    def test_fixture_ids_unique_and_documented(self):
        for f in neg.load_manifest()["fixtures"]:
            with self.subTest(fixture=f["id"]):
                self.assertTrue(f["defect"] and f["guards_against"] and f["expect"])


class RunnerCanFailTests(unittest.TestCase):
    """运行器若永远报绿，负例就失去意义：期望一个不会出现的错误码时必须报红。"""

    def _copy(self, td: str) -> Path:
        target = Path(td) / "negative"
        shutil.copytree(neg.FIXTURE_DIR, target)
        return target

    def test_unmet_expectation_turns_report_red(self):
        with tempfile.TemporaryDirectory() as td:
            fixture_dir = self._copy(td)
            manifest = json.loads((fixture_dir / "fixtures.json").read_text(encoding="utf-8"))
            manifest["fixtures"] = [{"id": "noop", "defect": "什么也没改", "guards_against": "-",
                                     "patches": [], "expect": ["P1_QUOTE_NOT_IN_EVIDENCE"]}]
            (fixture_dir / "fixtures.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            report = neg.run(fixture_dir)
            self.assertFalse(report["ok"])
            self.assertEqual(report["fixtures"][0]["missing"], ["P1_QUOTE_NOT_IN_EVIDENCE"])

    def test_dirty_base_turns_report_red(self):
        with tempfile.TemporaryDirectory() as td:
            fixture_dir = self._copy(td)
            skill = fixture_dir / "_base" / "package" / "SKILL.md"
            skill.write_text(skill.read_text(encoding="utf-8") + "\n**原文出处：**「编造的话」\n", encoding="utf-8")
            report = neg.run(fixture_dir)
            self.assertFalse(report["controls"][0]["clean"])
            self.assertFalse(report["ok"])

    def test_patch_that_no_longer_applies_is_an_error(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.md").write_text("原文", encoding="utf-8")
            with self.assertRaises(ValueError):
                neg.apply_patch(root, {"file": "a.md", "find": "不存在", "replace": "x"})
            with self.assertRaises(ValueError):
                neg.apply_patch(root, {"file": "a.md", "regex": "不存在", "replace": "x"})

    def test_repeat_patch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.md").write_text("> 甲\n", encoding="utf-8")
            neg.apply_patch(root, {"file": "a.md", "find": "> 甲", "replace": "> ", "replace_repeat": ["乙", 3]})
            neg.apply_patch(root, {"file": "a.md", "append": "\n", "append_repeat": ["丙", 2]})
            self.assertEqual((root / "a.md").read_text(encoding="utf-8"), "> 乙乙乙\n\n丙丙")


if __name__ == "__main__":
    unittest.main()
