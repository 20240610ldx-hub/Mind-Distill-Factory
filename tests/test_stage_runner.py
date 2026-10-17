"""mdf run（新进程执行 agent 步骤）、阶段卡、进度条与可视化面板。用假 harness，离线、不调模型。"""

from __future__ import annotations

import contextlib
import copy
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import stage_runner as sr  # noqa: E402

ps = sr.ps

FAKE_AGENT = r'''
import os, sys, time
from pathlib import Path
mode, prompt = sys.argv[1], sys.argv[2]
sys.stdout.reconfigure(encoding="utf-8")  # 真实 harness 输出 UTF-8；-I 下 PYTHONUTF8 不生效
print("收到任务：" + prompt, flush=True)
if mode == "slow":
    time.sleep(5)
time.sleep(0.6)
if mode == "fail":
    print("出错了", flush=True)
    raise SystemExit(3)
out = Path(os.environ["MDF_DATA_ROOT"]) / "output" / "demo" / "review.md"
out.write_text("# 审查\n\n## 裁决\n\n[PASS] 假 harness 写的审查结论\n", encoding="utf-8")
print("已写审查报告", flush=True)
'''


def load_mdf():
    spec = importlib.util.spec_from_file_location("_mdf_for_runner_test", ROOT / "scripts" / "mdf.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class RunnerFixture(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        (self.root / "output" / "demo").mkdir(parents=True)
        self.script = self.root / "fake_agent.py"
        self.script.write_text(FAKE_AGENT, encoding="utf-8")
        self.lines: list[str] = []

    def tearDown(self):
        self._td.cleanup()

    def profiles(self, mode: str = "ok") -> dict:
        profiles = copy.deepcopy(sr.harness.load_profiles())
        profiles["harnesses"]["fake"] = {
            "label": "假 harness", "executables": ["fakeagent"], "model_flag": "--model",
            "isolated_run": f'fakeagent -I "{self.script.as_posix()}" {mode} "{{prompt}}"',
        }
        return profiles

    def run_fake(self, mode: str = "ok", **kwargs) -> int:
        which = lambda exe: sys.executable if exe == "fakeagent" else None  # noqa: E731
        kwargs.setdefault("heartbeat", 0.2)
        return sr.run_step("demo", "review", self.root, "fake", profiles=self.profiles(mode), which=which,
                           out=self.lines.append, **kwargs)

    def records(self) -> list[dict]:
        path = self.root / "output" / "demo" / "runs" / "runs.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class ArgvTests(unittest.TestCase):
    def test_prompt_is_one_argument_and_model_follows_executable(self):
        profile = sr.harness.load_profiles()["harnesses"]["claude-code"]
        argv = sr.build_argv(profile, "/bin/claude", "读取 output/x y/briefs/review.md 并执行", model="sonnet")
        self.assertEqual(argv, ["/bin/claude", "--model", "sonnet", "-p", "--permission-mode", "acceptEdits",
                                "--allowedTools", "Bash,Read,Write,Edit,Glob,Grep", "--output-format", "json",
                                "读取 output/x y/briefs/review.md 并执行"])
        # --allowedTools 是变长参数：提示词紧跟其后会被吞成工具名，所以它后面必须先接一个定长选项。
        self.assertNotEqual(argv[argv.index("--allowedTools") + 2], argv[-1])

    def test_every_harness_declares_model_flag(self):
        for name, profile in sr.harness.load_profiles()["harnesses"].items():
            with self.subTest(harness=name):
                self.assertEqual(profile.get("model_flag"), "--model")

    def test_claude_code_names_the_chapter_tool(self):
        chapters = sr.harness.load_profiles()["harnesses"]["claude-code"]["chapters"]
        self.assertEqual(chapters["tool"], "mcp__ccd_session__mark_chapter")


class ConsentTests(RunnerFixture):
    def test_without_yes_prints_plan_and_writes_nothing(self):
        before = sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*"))
        self.assertEqual(self.run_fake(), sr.NEEDS_CONSENT)
        self.assertEqual(sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*")), before)
        text = "\n".join(self.lines)
        self.assertIn("## 阶段 5 · 质量审查", text, "先给阶段卡")
        self.assertIn("按量计费", text)
        self.assertIn("--yes", text)

    def test_missing_executable(self):
        code = sr.run_step("demo", "review", self.root, "fake", profiles=self.profiles(), which=lambda exe: None,
                           out=self.lines.append, yes=True)
        self.assertEqual(code, 2)


class RunTests(RunnerFixture):
    def test_successful_run_is_logged_and_recorded(self):
        # review 带步骤级检查点（validate package --strict）：进程正常结束后立刻跑它；
        # 这个夹具里没有包，检查点必然不过，结果如实记为未通过。
        self.assertEqual(self.run_fake(yes=True), 1)
        text = "\n".join(self.lines)
        self.assertIn("▶ 开始：阶段 5 · 质量审查 / 质量审查", text)
        self.assertIn("…", text, "运行中要有心跳")
        self.assertIn("⚠️ 进程结束，但步骤未通过", text)
        self.assertIn("步骤 ⬜ 待办 → ✅ 完成", text)
        self.assertIn("检查点 `python scripts/mdf.py validate package demo --strict`：未通过", text)
        self.assertIn("进度：", text)
        [record] = self.records()
        self.assertEqual((record["step"], record["exit_code"], record["ok"]), ("review", 0, False))
        self.assertEqual(record["checkpoint"]["command"], "python scripts/mdf.py validate package demo --strict")
        self.assertGreaterEqual(record["changed_files"], 1, "review.md 是新产物（briefs 也算）")
        log = (ROOT / record["log"]) if not Path(record["log"]).is_absolute() else Path(record["log"])
        self.assertIn("已写审查报告", log.read_text(encoding="utf-8"))
        self.assertTrue((self.root / "output" / "demo" / "briefs" / "review.md").exists())

    def test_failing_process(self):
        self.assertEqual(self.run_fake("fail", yes=True), 1)
        self.assertIn("❌ 进程退出码 3", "\n".join(self.lines))
        self.assertFalse(self.records()[0]["ok"])

    def test_timeout_kills_the_process(self):
        self.assertEqual(self.run_fake("slow", yes=True, timeout_min=0.01), 1)
        self.assertIn("⏱ 超时", "\n".join(self.lines))
        self.assertTrue(self.records()[0]["timed_out"])


class NarrationViewTests(RunnerFixture):
    def test_progress_bar_marks_the_current_phase(self):
        stages = ps.collect_status("demo", self.root)
        bar = ps.progress_bar(stages)
        self.assertEqual(len(bar.split(" ")[0]), len(ps.load_stage_tree()["phases"]))
        self.assertIn("▶", bar)
        self.assertIn(ps.next_stage(stages).chapter["title"], bar)

    def test_card_for_agent_step_mentions_mdf_run(self):
        card = ps.render_card("demo", ps.collect_status("demo", self.root), step_key="review")
        self.assertTrue(card.startswith("## 阶段 5 · 质量审查"))
        for part in ("**这一步**", "**怎么做**", "**闸门**", "**进度**", "mdf.py run demo review"):
            self.assertIn(part, card)

    def test_html_board_is_self_contained_and_lists_runs(self):
        self.run_fake(yes=True)
        stages = ps.collect_status("demo", self.root)
        html = ps.render_html("demo", stages, runs=ps.load_runs(self.root, "demo"), generated_at="2026-10-18 10:00")
        for phase in ps.load_stage_tree()["phases"]:
            self.assertIn(phase["chapter"]["title"], html)
        self.assertIn("运行记录（mdf run）", html)
        self.assertNotIn("http://", html)
        self.assertNotIn("https://", html)
        self.assertIn("prefers-color-scheme: dark", html)

    def test_mdf_cli_card_and_html(self):
        mdf = load_mdf()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(mdf.main(["next", "demo", "--card", "--root", str(self.root)]), 0)
            self.assertEqual(mdf.main(["status", "demo", "--html", "--root", str(self.root)]), 0)
        self.assertIn("**这一步**", out.getvalue())
        self.assertTrue((self.root / "output" / "demo" / "status.html").exists())
        self.assertIn("run", mdf.PASSTHROUGH)


if __name__ == "__main__":
    unittest.main()
