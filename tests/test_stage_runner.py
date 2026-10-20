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
from unittest import mock

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
if mode == "usage":
    print('{"type":"result","subtype":"success","num_turns":9,"total_cost_usd":0.53,"usage":{"output_tokens":1200,"cache_read_input_tokens":880000},"result":"检查点通过"}', flush=True)
if mode == "limit":  # 2026-10-20 实跑：额度用完，claude 退出码 1，原因只在结果对象里
    print('{"type":"result","subtype":"success","is_error":true,"api_error_status":429,"num_turns":1,"total_cost_usd":0,"result":"You have hit your session limit - resets 9pm"}', flush=True)
    raise SystemExit(1)
if mode == "spawn":  # 墨子试跑 review 步骤：新进程自己又派了子代理
    print('{"type":"result","subtype":"success","num_turns":1,"total_cost_usd":0.69,"subagent_stats":{"spawned":2},"result":"PASS"}', flush=True)
'''

# claude 2.1.301 的真实输出形状（2026-10-18 Sonnet 5.5 实测）：结果对象以 duration_api_ms 起头，
# "type":"result" 排在中后部；stream-json 下它也不是最后一行，后面还跟一条 task_summary。
REAL_RESULT = ('{"duration_api_ms":99856,"stop_reason":"end_turn","total_cost_usd":0.6821683,'
               '"usage":{"input_tokens":18,"cache_read_input_tokens":673463,"output_tokens":12805},'
               '"permission_denials":[{"tool_name":"Write"}],"is_error":false,"num_turns":10,"subtype":"success",'
               '"result":"已写 shard_001_extracts.json","type":"result","duration_ms":133000}')
STREAM_EVENTS = [
    '{"type":"system","subtype":"init","cwd":"C:\\\\repo"}',
    '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Read",'
    '"input":{"file_path":"D:/data/sources/demo/processed/local_shards/shard_001.json"}}]}}',
    '{"type":"user","message":{"content":[{"type":"tool_result","content":"..."}]}}',
    '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Bash",'
    '"input":{"command":"python scripts/task_status.py summary sources/demo/x.json","description":"检查点"}}]}}',
]
STREAM_TAIL = '{"type":"system","subtype":"task_summary","detail":null}'
STREAM_AGENT = r'''
import os, sys, time
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
lines = Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
for line in lines[:2]:  # 先读分片：心跳此时应报出「Read shard_001.json」
    print(line, flush=True)
time.sleep(0.8)
out = Path(os.environ["MDF_DATA_ROOT"]) / "output" / "demo" / "review.md"
out.write_text("# 审查\n\n## 裁决\n\n[PASS] 假 harness 写的审查结论\n", encoding="utf-8")
for line in lines[2:]:
    print(line, flush=True)
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
            "usage_parser": "claude-json",
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
    def test_prompt_is_one_argument_and_model_goes_right_before_it(self):
        # 模型选项插在提示词前：codex 的 --model 这样才落在 exec 子命令里（放到子命令前面没核实）
        profile = sr.harness.load_profiles()["harnesses"]["claude-code"]
        prompt = "读取 output/x y/briefs/review.md 并执行"
        argv = sr.build_argv(profile, "/bin/claude", prompt, model="sonnet")
        self.assertEqual(argv[:5], ["/bin/claude", "-p", "--model", "sonnet", prompt])
        self.assertIn("--allowedTools", argv)

    def test_prompt_is_not_swallowed_by_variadic_allowed_tools(self):
        # --allowedTools 是 <tools...> 可变参数：排在它后面的位置参数会被当成工具名（墨子试跑分支的模板就是这样）。
        profile = sr.harness.load_profiles()["harnesses"]["claude-code"]
        argv = sr.build_argv(profile, "claude", "PROMPT")
        self.assertLess(argv.index("PROMPT"), argv.index("--allowedTools"))
        tools = argv[argv.index("--allowedTools") + 1]
        self.assertEqual(tools.split(","), ["Bash", "Read", "Write", "Edit", "Glob", "Grep"])

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

    def test_plan_flags_a_data_root_inside_the_worktree_pool(self):
        pooled = self.root / ".claude" / "worktrees" / "w"
        (pooled / "output" / "demo").mkdir(parents=True)
        which = lambda exe: sys.executable if exe == "fakeagent" else None  # noqa: E731
        sr.run_step("demo", "review", pooled, "fake", profiles=self.profiles(), which=which, out=self.lines.append)
        self.assertIn("临时 worktree", "\n".join(self.lines))

    def test_missing_executable(self):
        code = sr.run_step("demo", "review", self.root, "fake", profiles=self.profiles(), which=lambda exe: None,
                           out=self.lines.append, yes=True)
        self.assertEqual(code, 2)


def passing_checkpoint(calls: list):
    def fake(command, slug, root):
        calls.append(command.replace("{slug}", slug) if command else command)
        return {"command": command.replace("{slug}", slug), "exit_code": 0, "tail": []} if command else None
    return fake


class RunTests(RunnerFixture):
    def test_successful_run_is_logged_and_recorded(self):
        calls: list = []
        with mock.patch.object(sr, "_checkpoint", passing_checkpoint(calls)):
            self.assertEqual(self.run_fake(yes=True), 0)
        self.assertEqual(calls, ["python scripts/mdf.py validate package demo --strict"],
                         "review 用步骤自带的检查点，而不是去编一个 validate review")
        text = "\n".join(self.lines)
        self.assertIn("▶ 开始：阶段 5 · 质量审查 / 质量审查", text)
        self.assertIn("…", text, "运行中要有心跳")
        self.assertIn("✅ 进程正常结束", text)
        self.assertIn("步骤 ⬜ 待办 → ✅ 完成", text)
        self.assertIn("进度：", text)
        [record] = self.records()
        self.assertEqual((record["step"], record["exit_code"], record["ok"]), ("review", 0, True))
        self.assertEqual([c["command"] for c in record["checkpoints"]],
                         ["python scripts/mdf.py validate package demo --strict"])
        self.assertGreaterEqual(record["changed_files"], 1, "review.md 是新产物（briefs 也算）")
        log = (ROOT / record["log"]) if not Path(record["log"]).is_absolute() else Path(record["log"])
        self.assertIn("已写审查报告", log.read_text(encoding="utf-8"))
        self.assertTrue((self.root / "output" / "demo" / "briefs" / "review.md").exists())

    def test_failing_step_checkpoint_fails_the_run_and_explains(self):
        failing = lambda command, slug, root: {"command": command, "exit_code": 1, "tail": ["P2 失败"]}  # noqa: E731
        with mock.patch.object(sr, "_checkpoint", failing):
            self.assertEqual(self.run_fake(yes=True), 1)
        text = "\n".join(self.lines)
        self.assertIn("⚠️ 进程结束，但步骤未通过", text)
        self.assertIn("P2 失败", text)
        self.assertIn("没有名为 review 的校验阶段", text, "checkpoint_note 在检查点失败时给出")

    def test_usage_is_parsed_into_result_line_and_record(self):
        with mock.patch.object(sr, "_checkpoint", passing_checkpoint([])):
            self.assertEqual(self.run_fake("usage", yes=True), 0)
        self.assertIn("$0.53 · 9 轮", "\n".join(self.lines))
        record = self.records()[0]
        usage = record["usage"]
        self.assertEqual((usage["cost_usd"], usage["turns"], usage["cache_read_tokens"]), (0.53, 9, 880000))
        html = ps.render_html("demo", ps.collect_status("demo", self.root), runs=ps.load_runs(self.root, "demo"))
        self.assertIn("$0.53 · 9 轮", html)

    def test_spawned_subagents_are_warned_about_and_recorded(self):
        with mock.patch.object(sr, "_checkpoint", passing_checkpoint([])):
            self.assertEqual(self.run_fake("spawn", yes=True), 0, "告警不判失败：产物要人核对，不是一律作废")
        text = "\n".join(self.lines)
        self.assertIn("⚠️", text)
        self.assertIn("又派了 2 个子代理", text)
        self.assertIn("简报禁止", text)
        record = self.records()[0]
        self.assertEqual(len(record["warnings"]), 1)
        self.assertIn("子代理", record["warnings"][0])
        html = ps.render_html("demo", ps.collect_status("demo", self.root), runs=ps.load_runs(self.root, "demo"))
        self.assertIn("⚠️ 子代理 2", html)

    def test_failed_process_says_why(self):
        self.assertEqual(self.run_fake("limit", yes=True), 1)
        text = "\n".join(self.lines)
        self.assertIn("❌ 进程退出码 1", text)
        self.assertIn("原因：You have hit your session limit - resets 9pm", text, "原因不能只埋在日志里")

    def test_no_subagents_no_warning(self):
        self.assertEqual(sr.run_warnings({"cost_usd": 0.5, "turns": 3}), [])
        self.assertEqual(sr.run_warnings(None), [])
        with mock.patch.object(sr, "_checkpoint", passing_checkpoint([])):
            self.run_fake("usage", yes=True)
        self.assertEqual(self.records()[0]["warnings"], [])

    def test_checkpoint_runs_in_the_data_root(self):
        check = sr._checkpoint("python scripts/mdf.py validate sources {slug}", "demo", self.root)
        self.assertEqual(check["command"], "python scripts/mdf.py validate sources demo")
        self.assertNotEqual(check["exit_code"], 0, "空的 demo 没有素材，检查点应当不通过")
        self.assertTrue(check["tail"])

    def test_failing_process(self):
        self.assertEqual(self.run_fake("fail", yes=True), 1)
        self.assertIn("❌ 进程退出码 3", "\n".join(self.lines))
        self.assertFalse(self.records()[0]["ok"])

    def test_timeout_kills_the_process(self):
        self.assertEqual(self.run_fake("slow", yes=True, timeout_min=0.01), 1)
        self.assertIn("⏱ 超时", "\n".join(self.lines))
        self.assertTrue(self.records()[0]["timed_out"])


class SmallCorpusRunTests(RunnerFixture):
    """只有 1 个分片：抽取、合并、原则提取在一个新进程里依次做完，三个检查点都跑（墨子试跑第 14 条）。"""

    def setUp(self):
        super().setUp()
        src = self.root / "sources" / "demo"
        (src / "raw").mkdir(parents=True)
        (src / "raw" / "墨子.txt").write_text("兼相爱，交相利。", encoding="utf-8")
        (src / "processed" / "local_shards").mkdir(parents=True)
        (src / "processed" / "local_shards" / "manifest.json").write_text(
            json.dumps({"shard_count": 1, "shards": [{"shard_id": "shard_001"}]}), encoding="utf-8")
        (src / "classification.json").write_text(
            json.dumps({"primary": "governance", "secondary": ["philosophy"]}), encoding="utf-8")

    def run_bundle(self, **kwargs) -> int:
        which = lambda exe: sys.executable if exe == "fakeagent" else None  # noqa: E731
        return sr.run_step("demo", "extract", self.root, "fake", profiles=self.profiles("ok"), which=which,
                           out=self.lines.append, heartbeat=0.2, **kwargs)

    def test_plan_names_every_step_it_will_do(self):
        self.assertEqual(self.run_bundle(), sr.NEEDS_CONSENT)
        text = "\n".join(self.lines)
        self.assertIn("分片抽取 → 合并与本地补充 → 原则提取", text)
        self.assertIn("briefs/small-corpus.md", text)

    def test_one_process_three_checkpoints_one_record(self):
        calls: list[str] = []
        with mock.patch.object(sr, "_checkpoint", passing_checkpoint(calls)):
            self.run_bundle(yes=True)
        self.assertEqual(calls, [
            "python scripts/task_status.py summary sources/demo/processed/local_shards/task_status.json --strict",
            "python scripts/mdf.py validate sources demo",
            "python scripts/mdf.py validate principles demo",
        ])
        self.assertTrue((self.root / "output" / "demo" / "briefs" / "small-corpus.md").exists())
        record = self.records()[0]
        self.assertEqual(record["step"], "small-corpus")
        self.assertEqual([m["step"] for m in record["members"]], ["extract", "reduce", "principles"])
        text = "\n".join(self.lines)
        self.assertIn("原则提取 ⬜ 待办 → ⬜ 待办", text, "结果行逐步报状态变化")
        self.assertNotIn("阶段检查点留到阶段末尾", text)


class RealClaudeOutputTests(RunnerFixture):
    """按实测的真实输出形状解析用量与进展，不依赖字段顺序，也不假定结果在最后一行。"""

    def write_log(self, lines: list[str]) -> Path:
        log = self.root / "x.log"
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return log

    def test_result_found_whatever_the_key_order(self):
        usage = sr.parse_usage(self.write_log([REAL_RESULT]), "claude-json")
        self.assertEqual((usage["cost_usd"], usage["turns"], usage["cache_read_tokens"]), (0.6821683, 10, 673463))
        self.assertEqual(usage["permission_denials"], 1, "被拒的工具调用要记下来：新进程有没有被权限拦住就看它")

    def test_stream_json_result_is_not_the_last_line(self):
        usage = sr.parse_usage(self.write_log([*STREAM_EVENTS, REAL_RESULT, STREAM_TAIL]), "claude-json")
        self.assertEqual(usage["turns"], 10)

    def test_latest_activity_reads_tool_calls(self):
        log = self.write_log(STREAM_EVENTS[:2])
        self.assertEqual(sr.latest_activity(log, "claude-json"), "Read shard_001.json")
        log = self.write_log(STREAM_EVENTS)
        self.assertEqual(sr.latest_activity(log, "claude-json"),
                         "Bash python scripts/task_status.py summary sources/demo/x.json")
        self.assertEqual(sr.latest_activity(self.write_log(["纯文本输出"]), None), "纯文本输出")

    def test_claude_profile_streams_events(self):
        flags = sr.harness.load_profiles()["harnesses"]["claude-code"]["usage_flags"]
        self.assertEqual(flags, ["--output-format", "stream-json", "--verbose"],
                         "json 要到进程结束才输出，心跳一直是「日志 0.0 KB」；stream-json 必须带 --verbose")

    def test_heartbeat_and_result_line_with_streamed_events(self):
        events = self.root / "events.jsonl"
        events.write_text("\n".join([*STREAM_EVENTS, REAL_RESULT, STREAM_TAIL]) + "\n", encoding="utf-8")
        script = self.root / "stream_agent.py"
        script.write_text(STREAM_AGENT, encoding="utf-8")
        profiles = self.profiles()
        profiles["harnesses"]["fake"]["isolated_run"] = (
            f'fakeagent -I "{script.as_posix()}" "{events.as_posix()}" "{{prompt}}"')
        which = lambda exe: sys.executable if exe == "fakeagent" else None  # noqa: E731
        with mock.patch.object(sr, "_checkpoint", passing_checkpoint([])):
            code = sr.run_step("demo", "review", self.root, "fake", profiles=profiles, which=which,
                               out=self.lines.append, yes=True, heartbeat=0.2)
        self.assertEqual(code, 0)
        text = "\n".join(self.lines)
        self.assertIn("最近：Read shard_001.json", text)
        self.assertIn("$0.68 · 10 轮", text)
        self.assertIn("1 次工具调用被拒", text)
        self.assertEqual(self.records()[0]["usage"]["permission_denials"], 1)


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
