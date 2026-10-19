"""发布要认数据根：`--root` > MDF_DATA_ROOT > 仓库根，和其他命令一样（解析规则只在 workspace.py）。

2026-10-20 在 GUI 里按 distill.md 实跑鲁迅到阶段 6：数据根经 MDF_DATA_ROOT 放在 worktree 之外（发现 0 的
修法正是这样建议的），前面每个命令都认它，`mdf publish --dry-run` 却去仓库根找 output/，报「Compiled skill
file not found」——分离的工作区在最后一步断掉。
"""

from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import publish_skill  # noqa: E402


class PublishHonoursTheDataRoot(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.data = Path(self._td.name)
        out = self.data / "output" / "demo-thinker"
        out.mkdir(parents=True)
        (out / "SKILL.md").write_text("---\nname: demo-thinker-wisdom\nformat_version: 6\n---\n", encoding="utf-8",
                                      newline="\n")

    def tearDown(self):
        self._td.cleanup()

    def publish(self, *args: str, env: dict | None = None):
        err = io.StringIO()
        calls = []

        def fake_run(cmd, cwd):
            calls.append((cmd, Path(cwd)))
            return 1, "", "stop here"  # 只看预检怎么调，不往下走

        with mock.patch.dict(os.environ, env or {}, clear=False), \
                mock.patch.object(sys, "argv", ["publish_skill.py", "--slug", "demo-thinker", "--dry-run", *args]), \
                mock.patch.object(publish_skill, "run_command", fake_run), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = publish_skill.main()
        return code, err.getvalue(), calls

    def test_env_data_root_is_where_output_is_read(self):
        _, err, calls = self.publish(env={"MDF_DATA_ROOT": str(self.data)})
        self.assertNotIn("not found", err)
        self.assertEqual(len(calls), 1, "预检照常运行")
        cmd, cwd = calls[0]
        self.assertEqual(cwd.resolve(), self.data.resolve(), "预检在数据根下跑，validate 才找得到 output/")
        self.assertTrue(Path(cmd[1]).is_absolute() and Path(cmd[1]).name == "validate_output.py",
                        "脚本写仓库里的绝对路径")

    def test_root_flag_wins(self):
        _, err, calls = self.publish("--root", str(self.data), env={"MDF_DATA_ROOT": str(ROOT)})
        self.assertNotIn("not found", err)
        self.assertEqual(calls[0][1].resolve(), self.data.resolve())


if __name__ == "__main__":
    unittest.main()
