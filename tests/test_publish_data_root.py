"""发布要认数据根：`--root` > MDF_DATA_ROOT > 仓库根，和其他命令一样（解析规则只在 workspace.py）。

2026-10-20 在 GUI 里按 distill.md 实跑鲁迅到阶段 6：数据根经 MDF_DATA_ROOT 放在 worktree 之外（发现 0 的
修法正是这样建议的），前面每个命令都认它，`mdf publish --dry-run` 却去仓库根找 output/，报「Compiled skill
file not found」——分离的工作区在最后一步断掉。
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import publish_skill  # noqa: E402
import validate_output  # noqa: E402
from sibling import load_module  # noqa: E402
from workspace import Workspace  # noqa: E402

pkg_fixtures = load_module(ROOT / "tests" / "test_package_v6.py", "_package_v6_fixtures_data_root")
CASE_INDEX = "## 案例索引\n\n| demo-c1-1 | demo-c1-2 | demo-counter-1 |\n"


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


class GalleryGoesToTheCodeRoot(unittest.TestCase):
    """gallery/ 入库：数据根在仓库外时，发布只改代码根下的 gallery/，数据根下不出现 gallery/。

    张居正 v6 发布时 MDF_DATA_ROOT 指向主检出，publish 把 gallery 写进了主检出里入库的文件，绕过了
    worktree 和分支（只能在 scratch 下拼一个临时根绕过去）。
    """

    def setUp(self):
        self._data, self._code = tempfile.TemporaryDirectory(), tempfile.TemporaryDirectory()
        self.fx = pkg_fixtures.PackageFixture(self._data.name)  # 数据根：output/demo + sources/demo
        self.fx.write_skill(pkg_fixtures.build_skill_md(extra=CASE_INDEX))
        self.ws = Workspace(self.fx.root, Path(self._code.name))
        self.assertTrue(self.ws.separate)

    def tearDown(self):
        self._data.cleanup()
        self._code.cleanup()

    def test_publish_writes_gallery_under_the_code_root_only(self):
        repo_index = ROOT / "gallery" / "index.json"
        repo_before = repo_index.read_bytes() if repo_index.exists() else None
        out, err = io.StringIO(), io.StringIO()
        meta = {"name_zh": "示例", "name_en": "Demo", "name_original": "示例", "era": "当代",
                "primary_cat": "governance", "secondary_cats": []}
        real_load = publish_skill._load_sibling

        def load(name):  # load_sibling 不缓存，每次都是新模块：只能在 main 取 workspace 时换掉代码根
            module = real_load(name)
            if name == "workspace":
                module.Workspace.resolve = staticmethod(lambda *a, **k: self.ws)
            return module

        with mock.patch.object(sys, "argv", ["publish_skill.py", "--slug", "demo", "--force",
                                             "--root", str(self.fx.root)]), \
                mock.patch.object(publish_skill, "_load_sibling", load), \
                mock.patch.object(publish_skill, "resolve_metadata", return_value=meta), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = publish_skill.main()
        self.assertEqual(code, 0, out.getvalue() + err.getvalue())
        self.assertIn(str(self.ws.gallery / "demo"), out.getvalue())

        gallery = self.ws.gallery
        self.assertTrue((gallery / "demo" / "manifest.json").exists())
        self.assertTrue((gallery / "demo" / "references" / "evidence.md").exists())
        entry = json.loads((gallery / "index.json").read_text(encoding="utf-8"))["skills"][0]
        self.assertEqual(entry["skill_dir"], "gallery/demo/")
        self.assertFalse((self.fx.root / "gallery").exists(), "数据根下不该出现 gallery/")
        self.assertEqual(repo_index.read_bytes() if repo_index.exists() else None, repo_before,
                         "本仓库的 gallery 不受测试影响")

        # manifest 的 hash 针对代码根下的包；validate published 按代码根找 gallery，cwd 在数据根也一样
        self.assertEqual([e for e in validate_output.validate_published("demo", self.fx.root, gallery_root=gallery)
                          if not e.startswith("WARNING:")], [])
        self.assertTrue(validate_output.validate_published("demo", self.fx.root),
                        "默认 root/gallery 在数据根下，那里什么都没有")


if __name__ == "__main__":
    unittest.main()
