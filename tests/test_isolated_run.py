"""隔离执行：把一个 agent 步骤交给新的 harness 进程时，命令行怎么拼、简报怎么写。

领域约定：
- 代码根（仓库：scripts/ agents/ config/）与数据根（sources/ output/）可以不是同一个目录：
  worktree 里没有私有语料，靠 MDF_DATA_ROOT 指向别处。两者分离时，新进程要被授权访问数据根，
  简报要写明相对路径相对哪个根、检查点在本机怎么跑。
- 模型、推理强度、目录授权是 harness 档案（config/harnesses.json）声明的能力，档案没声明就明确拒绝或跳过，
  不猜参数名。
"""

from __future__ import annotations

import shlex
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import harness  # noqa: E402
import stage_runner as sr  # noqa: E402

PROMPT = "读取 output/demo/briefs/extract.md 并严格按其执行，完成后报告检查点结果。"


def profile(name: str) -> dict:
    return harness.load_profiles()["harnesses"][name]


class IsolatedArgvTests(unittest.TestCase):
    def test_claude_options_before_prompt_and_data_dir_after_variadic_tools(self):
        argv = harness.isolated_argv(profile("claude-code"), "claude", PROMPT, model="claude-sonnet-5-5",
                                     effort="high", data_dirs=["D:/data root"], usage=True)
        self.assertEqual(argv[:7], ["claude", "-p", "--model", "claude-sonnet-5-5", "--effort", "high", PROMPT])
        # --allowedTools 与 --add-dir 都是可变参数：提示词必须排在两者前面，--add-dir 之后紧跟别的选项
        self.assertLess(argv.index(PROMPT), argv.index("--allowedTools"))
        self.assertEqual(argv[argv.index("--add-dir") + 1], "D:/data root")
        self.assertLess(argv.index("--allowedTools"), argv.index("--add-dir"))
        self.assertEqual(argv[-3:], ["--output-format", "stream-json", "--verbose"])

    def test_codex_model_goes_inside_exec_and_effort_is_refused(self):
        argv = harness.isolated_argv(profile("codex"), "codex", PROMPT, model="gpt-x", data_dirs=["/data"])
        self.assertEqual(argv[:7], ["codex", "exec", "--sandbox", "workspace-write", "--model", "gpt-x", PROMPT])
        self.assertEqual(argv[-2:], ["--add-dir", "/data"])
        with self.assertRaises(SystemExit) as caught:
            harness.isolated_argv(profile("codex"), "codex", PROMPT, effort="high")
        self.assertIn("effort", str(caught.exception))

    def test_pi_thinking_level_and_no_directory_sandbox(self):
        argv = harness.isolated_argv(profile("pi"), "pi", PROMPT, model="local/9b", effort="high", data_dirs=["/data"])
        self.assertEqual(argv, ["pi", "-p", "--model", "local/9b", "--thinking", "high", PROMPT])

    def test_stage_runner_keeps_build_argv_name(self):
        self.assertEqual(sr.build_argv(profile("pi"), "pi", PROMPT), ["pi", "-p", PROMPT])

    def test_launch_commands_grant_the_data_root(self):
        commands = harness.launch_commands("D:/data/output/demo/briefs/extract.md", harness.load_profiles(),
                                           data_dirs=["D:/data"])
        self.assertIn("--add-dir D:/data", commands["claude-code"])
        self.assertIn("--add-dir D:/data", commands["codex"])
        self.assertNotIn("--add-dir", commands["pi"])


class CheckpointCommandTests(unittest.TestCase):
    def test_checkpoint_argv_uses_repo_scripts_and_given_python(self):
        argv = harness.checkpoint_argv("python scripts/task_status.py summary sources/{slug}/x.json", "demo",
                                       code_root=Path("C:/repo"), python="py")
        self.assertEqual(argv, ["py", "C:/repo/scripts/task_status.py", "summary", "sources/demo/x.json"])

    def test_runner_checkpoint_uses_the_shared_rendering(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.object(harness, "checkpoint_argv",
                                                                    wraps=harness.checkpoint_argv) as spy:
            sr._checkpoint("python scripts/mdf.py stages", "demo", Path(td))
        spy.assert_called_once()


class SeparateDataRootBriefTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        (self.root / "output" / "demo").mkdir(parents=True)

    def tearDown(self):
        self._td.cleanup()

    def test_brief_explains_paths_and_gives_a_runnable_checkpoint(self):
        _, text = harness.build_brief("demo", "extract", self.root)
        root = self.root.resolve().as_posix()
        self.assertIn("路径约定", text)
        self.assertIn(f"`sources/…`、`output/…` 都在数据根目录 `{root}` 下", text)
        runnable = f"cd '{root}' && " + shlex.join(
            ["python", f"{ROOT.as_posix()}/scripts/task_status.py", "summary",
             "sources/demo/processed/local_shards/task_status.json"])
        self.assertIn(runnable, text)

    def test_brief_in_the_repo_itself_has_no_path_note(self):
        _, text = harness.build_brief("demo", "extract", ROOT)
        self.assertNotIn("路径约定", text)


class RunStepOptionsTests(unittest.TestCase):
    def test_plan_shows_effort_and_data_root_grant(self):
        lines: list[str] = []
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "output" / "demo").mkdir(parents=True)
            code = sr.run_step("demo", "review", root, "claude-code", effort="high",
                               which=lambda exe: "/bin/claude" if exe == "claude" else None, out=lines.append)
            text = "\n".join(lines)
            self.assertEqual(code, sr.NEEDS_CONSENT)
            self.assertIn("--effort high", text)
            self.assertIn(f"--add-dir {root.resolve().as_posix()}", text)

    def test_cli_passes_effort(self):
        with mock.patch.object(sr, "run_step", return_value=0) as run:
            sr.main(["demo", "review", "--harness", "claude-code", "--effort", "high", "--root", "."])
        self.assertEqual(run.call_args.kwargs["effort"], "high")


if __name__ == "__main__":
    unittest.main()
