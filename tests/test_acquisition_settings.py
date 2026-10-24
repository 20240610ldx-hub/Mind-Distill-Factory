"""采集的联系方式与法域：问过用户后存进数据根的本地设置，之后复用，不写进入库的 acquisition_policy.json。

用户 2026-10-24 决定：「采集联系方式与法域询问用户后存入项目记忆复用」。设置放在 `{数据根}/.mdf/acquisition.json`
（.gitignore 忽略），整体复制数据根时一起带走。优先级：入库策略里的值 > 环境变量 MDF_CONTACT > 本地设置。
法域可以显式记为「暂不设定」，编排者据此不再反复问；未设定时公有领域一律待复核。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from sibling import load_module  # noqa: E402  按路径加载模块的唯一入口（先登记 sys.modules）

settings = load_module(ROOT / "scripts" / "acquisition_settings.py", "_settings_under_test")
acq = load_module(ROOT / "scripts" / "acquire.py", "_acquire_for_settings")
NOW = "2026-10-24T00:00:00+00:00"
URL = "https://github.com/20240610ldx-hub/Mind-Distill-Factory"


class SettingsStoreTests(unittest.TestCase):
    def test_round_trip_in_the_data_root(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.assertEqual(settings.load(root), settings.EMPTY)
            settings.save(root, contact=URL, now=NOW)
            settings.save(root, jurisdiction=None, now=NOW)
            path = root / ".mdf" / "acquisition.json"
            data = settings.load(root)
            self.assertEqual((data["contact"], data["jurisdiction"], data["jurisdiction_decided"]), (URL, None, True))
            self.assertNotIn(b"\r\n", path.read_bytes())
            settings.save(root, jurisdiction="sg", now=NOW)
            self.assertEqual(settings.load(root)["jurisdiction"], "SG")
            self.assertEqual(settings.load(root)["contact"], URL, "只改给出的字段")

    def test_bad_values_are_refused(self):
        with tempfile.TemporaryDirectory() as td:
            for kwargs in ({"contact": "has space"}, {"contact": ""}, {"jurisdiction": "Singapore"}):
                with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                    settings.save(Path(td), now=NOW, **kwargs)

    def test_settings_dir_is_ignored_by_git(self):
        lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn(".mdf/", lines)


class PolicyOverlayTests(unittest.TestCase):
    def test_precedence_policy_then_env_then_local(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ):
            os.environ.pop("MDF_CONTACT", None)
            root = Path(td)
            settings.save(root, contact=URL, now=NOW)
            policy = acq.load_policy(root=root)
            self.assertEqual(acq.resolve_contact(policy), URL)
            os.environ["MDF_CONTACT"] = "https://env.invalid"
            self.assertEqual(acq.resolve_contact(policy), "https://env.invalid")
            policy["contact"] = "https://committed.invalid"
            self.assertEqual(acq.resolve_contact(policy), "https://committed.invalid")

    def test_local_jurisdiction_drives_the_rights_decision(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.assertEqual(acq.rights_decision(acq.load_policy(root=root), "public_domain_us"), "review")
            settings.save(root, jurisdiction="US", now=NOW)
            self.assertEqual(acq.rights_decision(acq.load_policy(root=root), "public_domain_us"), "allow")

    def test_acquire_cli_reads_the_local_contact(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ):
            os.environ.pop("MDF_CONTACT", None)
            settings.save(Path(td), contact=URL, now=NOW)
            proc = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "acquire.py"), "demo", "--wikisource", "zh:論語",
                 "--dry-run", "--json", "--root", td],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, env=os.environ,
            )
            self.assertEqual(json.loads(proc.stdout)[0]["event"], "planned", proc.stdout + proc.stderr)


class CliTests(unittest.TestCase):
    def test_mdf_acquire_settings_saves_and_shows(self):
        with tempfile.TemporaryDirectory() as td:
            run = lambda *args: subprocess.run(  # noqa: E731
                [sys.executable, str(ROOT / "scripts" / "mdf.py"), "acquire-settings", *args, "--root", td],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
            proc = run("--contact", URL, "--no-jurisdiction")
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            shown = run().stdout
            self.assertIn(URL, shown)
            self.assertIn("待复核", shown)
            self.assertEqual(run("--jurisdiction", "Singapore").returncode, 2)


if __name__ == "__main__":
    unittest.main()
