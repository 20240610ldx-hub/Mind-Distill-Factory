"""编排上下文的两个值对象：工作区（Workspace）与 harness 档案（HarnessProfile）。

通用语言（见 docs/architecture.md「领域模型」）：
- 代码根：仓库，放 scripts/ agents/ config/；数据根：放 sources/ output/（私有语料与产物）。
- 工作区 = 代码根 + 数据根。两者不同即「分离」：worktree 里没有私有语料时，数据根经 --root 或 MDF_DATA_ROOT 指向别处。
- harness 档案：一个 harness 怎样起新进程，以及它声明了哪些能力（指定模型、推理强度、授权目录、用量输出）。
"""

from __future__ import annotations

import re
import shlex
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import harness  # noqa: E402
from workspace import ENV, Workspace  # noqa: E402

PROMPT = "读取 output/demo/briefs/extract.md 并严格按其执行，完成后报告检查点结果。"


class WorkspaceTests(unittest.TestCase):
    def test_resolution_order_is_flag_then_env_then_repo(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            self.assertEqual(Workspace.resolve(a, environ={ENV: b}).data_root, Path(a).resolve())
            self.assertEqual(Workspace.resolve(None, environ={ENV: b}).data_root, Path(b).resolve())
        self.assertEqual(Workspace.resolve(None, environ={}).data_root, ROOT)
        self.assertEqual(Workspace.resolve(None, environ={ENV: ""}).data_root, ROOT, "空字符串等于没设")

    def test_value_object_equality_ignores_spelling(self):
        self.assertEqual(Workspace(ROOT / "scripts" / ".."), Workspace(ROOT))

    def test_in_repo_workspace_needs_no_grant(self):
        workspace = Workspace.resolve(None, environ={})
        self.assertFalse(workspace.separate)
        self.assertEqual(workspace.grants(), ())

    def test_separate_workspace_grants_the_data_root_and_passes_it_down(self):
        with tempfile.TemporaryDirectory() as td:
            workspace = Workspace.resolve(td, environ={})
            self.assertTrue(workspace.separate)
            self.assertEqual(workspace.grants(), (Path(td).resolve().as_posix(),))
            env = workspace.child_env({"PATH": "x"})
            self.assertEqual((env[ENV], env["PYTHONUTF8"], env["PATH"]), (str(Path(td).resolve()), "1", "x"))

    def test_checkpoint_command_runs_repo_scripts_from_the_data_root(self):
        with tempfile.TemporaryDirectory() as data, tempfile.TemporaryDirectory() as repo:
            workspace = Workspace(Path(data), Path(repo))
            data, repo = Path(data).resolve().as_posix(), Path(repo).resolve().as_posix()
            argv = workspace.checkpoint_argv("python scripts/task_status.py summary sources/{slug}/x.json", "demo",
                                             python="py")
            self.assertEqual(argv, ["py", f"{repo}/scripts/task_status.py", "summary", "sources/demo/x.json"])
            # mdf 按 --root > MDF_DATA_ROOT > 仓库根找数据根，不看当前目录：只 cd 过去会落回仓库根（2026-10-20 实测
            # MISSING_DIR）。简报交给 GUI 子代理时没有这个环境变量，所以给人看的命令要自带。
            self.assertEqual(workspace.runnable("python scripts/mdf.py validate sources {slug}", "demo"),
                             f"cd '{data}' && MDF_DATA_ROOT='{data}' "
                             + shlex.join(["python", f"{repo}/scripts/mdf.py", "validate", "sources", "demo"]))

    def test_data_root_in_the_desktop_worktree_pool_is_ephemeral(self):
        # 2026-10-19 鲁迅 GUI 验收发现 0：worktree 被回收，被 gitignore 的 sources/、output/ 一起消失，没有提示
        repo = Path("D:/mdf")
        pooled = repo / ".claude" / "worktrees" / "lu-xun-acceptance"
        self.assertTrue(Workspace(pooled, pooled).ephemeral)
        self.assertIn("MDF_DATA_ROOT", Workspace(pooled, pooled).risk_notice())
        self.assertFalse(Workspace(repo, pooled).ephemeral, "数据根指到 worktree 外面就安全")
        self.assertFalse(Workspace(repo, repo).ephemeral)
        self.assertIsNone(Workspace(repo, repo).risk_notice())

    def test_checkpoint_must_be_a_repo_python_script(self):
        # 检查点来自阶段树，但 mdf run 会在数据根下直接执行它：只放行 python scripts/<脚本>.py
        workspace = Workspace(ROOT)
        for command in ("rm -rf output", "bash -c 'scripts/x.py'", "python -c print(1)"):
            with self.subTest(command=command), self.assertRaises(SystemExit):
                workspace.checkpoint_argv(command, "demo")

    def test_no_module_reimplements_the_data_root_rule(self):
        # 这条规则曾在 10 个模块里各写一遍；以后只在 workspace.py 里定义
        offenders = [p.name for p in (ROOT / "scripts").glob("*.py")
                     if p.name != "workspace.py" and re.search(r"environ(?:\.get\(|\[)\s*[\"']MDF_DATA_ROOT", p.read_text(encoding="utf-8"))]
        self.assertEqual(offenders, [])


class DomainDocTests(unittest.TestCase):
    def test_bounded_context_table_names_real_modules(self):
        text = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
        section = text.split("### 限界上下文", 1)[1].split("### 不变式", 1)[0]
        rows = [ln for ln in section.splitlines() if ln.startswith("| ") and not ln.startswith("| 上下文")]
        modules = {m for row in rows for m in re.findall(r"`([a-z_]+)`", row.split("|")[3])}
        self.assertGreaterEqual(len(modules), 15)
        missing = sorted(m for m in modules if not (ROOT / "scripts" / f"{m}.py").exists())
        self.assertEqual(missing, [], "限界上下文表里写的模块必须真实存在")

    def test_glossary_points_at_the_value_objects(self):
        text = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
        for name in ("workspace.Workspace", "harness.HarnessProfile", "run-record-v1",
                     "verify_provenance.EvidenceCoverage", "cost_estimator.Budget", "gate_records.package_gate_current"):
            self.assertIn(name, text)

    def test_every_code_reference_in_the_glossary_resolves(self):
        # 通用语言表里写的 `模块.名字` 必须在代码里真有——改名、删类时文档不能悄悄过期
        import importlib
        text = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
        glossary = text.split("### 通用语言", 1)[1].split("### 限界上下文", 1)[0]
        refs = sorted(ref for ref in set(re.findall(r"`([a-z_]+)\.([A-Za-z_]+)`", glossary))
                      if ref[1] not in {"py", "json", "md", "txt"})  # 文件名不是代码引用
        self.assertGreaterEqual(len(refs), 6)
        missing = [f"{mod}.{name}" for mod, name in refs
                   if not hasattr(importlib.import_module(mod), name)]
        self.assertEqual(missing, [])


class HarnessProfileTests(unittest.TestCase):
    def test_every_configured_harness_becomes_a_profile(self):
        profiles = harness.harness_profiles()
        self.assertEqual(set(profiles), {"claude-code", "codex", "pi"})
        self.assertTrue(all(isinstance(p, harness.HarnessProfile) for p in profiles.values()))

    def test_declared_capabilities(self):
        profiles = harness.harness_profiles()
        self.assertEqual({n: p.can_set_effort for n, p in profiles.items()}, {"claude-code": True, "codex": False, "pi": True})
        self.assertEqual({n: p.can_grant_directories for n, p in profiles.items()},
                         {"claude-code": True, "codex": True, "pi": False})
        self.assertEqual(profiles["claude-code"].usage_parser, "claude-json")

    def test_argv_from_profile_and_workspace(self):
        with tempfile.TemporaryDirectory() as td:
            workspace = Workspace.resolve(td, environ={})
            argv = harness.harness_profiles()["codex"].argv("codex", PROMPT, model="m", grants=workspace.grants())
        self.assertEqual(argv, ["codex", "exec", "--sandbox", "workspace-write", "--model", "m", PROMPT,
                                "--add-dir", workspace.data_root.as_posix()])

    def test_refusing_an_undeclared_capability_names_it(self):
        with self.assertRaises(SystemExit) as caught:
            harness.harness_profiles()["codex"].argv("codex", PROMPT, effort="high")
        self.assertIn("effort_flag", str(caught.exception))

    def test_template_without_prompt_slot_is_rejected(self):
        with self.assertRaises(ValueError):
            harness.HarnessProfile.from_config("broken", {"label": "坏档案", "executables": ["x"], "isolated_run": "x -p"})


if __name__ == "__main__":
    unittest.main()
