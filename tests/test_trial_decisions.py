"""墨子试跑之后的四项决策：类目由用户确认后落盘下传、reduce 禁用网络检索、
换行符交给运行时 agent、mdf run 的步骤级检查点与用量记录。离线、不调模型。"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import classification as cls  # noqa: E402
import stage_runner as sr  # noqa: E402

harness = sr.harness
ps = sr.ps
validate_output = ps._sibling("validate_output")


class TempRoot(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        (self.root / "output" / "demo").mkdir(parents=True)
        (self.root / "sources" / "demo").mkdir(parents=True)

    def tearDown(self):
        self._td.cleanup()

    def classify(self, primary="governance", secondary=("philosophy", "conduct")):
        return cls.write(self.root, "demo", primary, list(secondary), "墨子")

    def status(self, key):
        return next(s for s in ps.collect_status("demo", self.root) if s.key == key)


class ClassificationRules(TempRoot):
    def test_rule5_one_primary_at_most_two_secondary(self):
        taxonomy = cls.load_taxonomy()
        self.assertEqual(cls.problems("governance", ["philosophy", "conduct"], taxonomy), [])
        for primary, secondary in ((None, []), ("nope", []), ("governance", ["philosophy", "conduct", "strategy"]),
                                   ("governance", ["governance"]), ("governance", ["nope"]),
                                   ("governance", ["philosophy", "philosophy"])):
            with self.subTest(primary=primary, secondary=secondary):
                self.assertTrue(cls.problems(primary, secondary, taxonomy))

    def test_write_load_roundtrip_and_describe(self):
        path = self.classify()
        self.assertEqual(path, self.root / "sources" / "demo" / "classification.json")
        self.assertNotIn(b"\r\n", path.read_bytes())
        data = cls.load(self.root, "demo")
        self.assertEqual((data["primary"], data["secondary"], data["confirmed_by"]),
                         ("governance", ["philosophy", "conduct"], "user"))
        self.assertEqual(cls.describe(data), "主类 governance（治理）；副类 philosophy（哲理）、conduct（行事）")

    def test_invalid_write_refused_and_broken_file_not_silently_ignored(self):
        with self.assertRaises(ValueError):
            cls.write(self.root, "demo", "nope", [])
        self.assertIsNone(cls.load(self.root, "demo"))
        cls.path_for(self.root, "demo").write_text('{"primary": "nope"}', encoding="utf-8")
        with self.assertRaises(ValueError):
            cls.load(self.root, "demo")


class ClassificationInStatus(TempRoot):
    def test_pending_then_done(self):
        self.assertEqual(self.status("classify").state, "pending")
        self.assertIn("AskUserQuestion", self.status("classify").next_action)
        self.classify()
        self.assertEqual(self.status("classify").state, "done")

    def test_legacy_person_with_frameworks_is_skipped(self):
        (self.root / "output" / "demo" / "frameworks.zh.json").write_text("{}", encoding="utf-8")
        self.assertEqual(self.status("classify").state, "skipped")

    def test_broken_file_fails(self):
        cls.path_for(self.root, "demo").write_text("{", encoding="utf-8")
        self.assertEqual(self.status("classify").state, "failed")


class ClassificationInBrief(TempRoot):
    def test_steps_that_need_it_refuse_without_it(self):
        for step in ("principles", "frameworks", "assemble"):
            with self.subTest(step=step), self.assertRaises(SystemExit) as caught:
                harness.build_brief("demo", step, self.root)
            self.assertIn("mdf.py classify demo", str(caught.exception))

    def test_steps_before_it_do_not_need_it(self):
        _, text = harness.build_brief("demo", "extract", self.root)
        self.assertNotIn("类目（用户已在阶段 0 确认", text)

    def test_confirmed_categories_are_handed_down(self):
        self.classify()
        _, text = harness.build_brief("demo", "principles", self.root)
        self.assertIn("类目（用户已在阶段 0 确认，照用，不得自选或改动）：主类 governance（治理）", text)


class ClassificationGate(TempRoot):
    def frameworks_errors(self):
        cwd = os.getcwd()
        os.chdir(self.root)
        try:
            return [e for e in validate_output.validate_frameworks("demo") if "CLASSIFICATION" in e]
        finally:
            os.chdir(cwd)

    def write_fw(self, primary, secondary):
        (self.root / "output" / "demo" / "frameworks.zh.json").write_text(
            json.dumps({"primary_category": primary, "secondary_categories": secondary}), encoding="utf-8")

    def test_mismatch_is_an_error(self):
        # 墨子试跑：用户定了 governance 主类，agent 自选成 philosophy 主类，以前没有任何闸门拦。
        self.classify()
        self.write_fw("philosophy", ["governance", "pedagogy"])
        errors = self.frameworks_errors()
        self.assertTrue(errors and all(e.startswith("CLASSIFICATION_MISMATCH") for e in errors), errors)

    def test_match_and_legacy_pass(self):
        self.write_fw("philosophy", [])
        self.assertEqual(self.frameworks_errors(), [], "没有 classification.json 的旧人物不检查")
        self.classify()
        self.write_fw("governance", ["conduct", "philosophy"])
        self.assertEqual(self.frameworks_errors(), [], "副类顺序不同不算不一致")

    def test_package_identity_card_is_checked(self):
        self.classify()
        skill = self.root / "output" / "demo" / "SKILL.md"
        skill.write_text("# 墨子的思维框架\n\n| 字段 | 值 |\n|---|---|\n| 主类 | 哲理（philosophy） |\n"
                         "| 副类 | 治理（governance） |\n", encoding="utf-8")
        cwd = os.getcwd()
        os.chdir(self.root)
        try:
            errors = validate_output.validate_package("demo")
        finally:
            os.chdir(cwd)
        self.assertTrue(any(e.startswith("CLASSIFICATION_MISMATCH") and "身份卡" in e for e in errors), errors)


class ReduceWithoutNetwork(TempRoot):
    def test_brief_forbids_network(self):
        with redirect_stderr(io.StringIO()):
            _, text = harness.build_brief("demo", "reduce", self.root)
        self.assertIn("**禁止网络检索**", text)
        self.assertIn("WebSearch", text)
        self.assertIn("mdf acquire", text)

    def test_other_steps_do_not_get_the_ban(self):
        _, text = harness.build_brief("demo", "extract", self.root)
        self.assertNotIn("禁止网络检索", text)

    def test_claude_code_drops_web_tools_for_reduce_only(self):
        tree = ps.load_stage_tree()
        _, reduce_step = harness.find_step(tree, "reduce")
        _, review_step = harness.find_step(tree, "review")
        profiles = harness.load_profiles()
        cmd = harness.launch_commands("b.md", profiles, "claude-code", step=reduce_step)["claude-code"]
        self.assertIn(" --disallowedTools WebSearch,WebFetch", cmd)
        self.assertLess(cmd.index("b.md"), cmd.index("--disallowedTools"), "可变参数排在提示词后面，不吞提示词")
        self.assertNotIn("--disallowedTools", harness.launch_commands("b.md", profiles, "claude-code", step=review_step)["claude-code"])
        claude = harness.HarnessProfile.from_config("claude-code", profiles["harnesses"]["claude-code"])
        argv = claude.argv("/bin/claude", "提示词", model="sonnet", usage=True,
                           deny_network=harness.forbids_network(reduce_step))
        self.assertEqual(argv[:5], ["/bin/claude", "-p", "--model", "sonnet", "提示词"])
        self.assertEqual(argv[argv.index("--disallowedTools") + 1], "WebSearch,WebFetch")
        self.assertFalse(harness.forbids_network(review_step))
        # 没有声明 deny_network_args 的 harness 只靠简报里的禁令
        codex = harness.HarnessProfile.from_config("codex", profiles["harnesses"]["codex"])
        self.assertEqual(codex.argv("codex", "提示词", deny_network=True), codex.argv("codex", "提示词"))

    def test_status_wording(self):
        self.assertEqual(self.status("reduce").title, "合并与本地补充")


class LineEndingsRule(TempRoot):
    def test_every_brief_tells_the_agent_to_write_lf(self):
        self.classify()
        for step in ("extract", "principles", "attachments", "review"):
            with self.subTest(step=step), redirect_stderr(io.StringIO()):
                _, text = harness.build_brief("demo", step, self.root)
            self.assertIn("换行符：写出的文本文件一律 LF", text)
            self.assertIn("`\\r\\n`", text, "简报里要写字面的 \\r\\n，不能是真的回车换行")
            self.assertNotIn("\r", text)


class StrictTaskStatus(TempRoot):
    def run_summary(self, status: dict) -> int:
        path = self.root / "task_status.json"
        path.write_text(json.dumps(status), encoding="utf-8")
        done = subprocess.run([sys.executable, str(ROOT / "scripts" / "task_status.py"), "summary", str(path), "--strict"],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        return done.returncode

    def test_strict_summary_is_a_real_gate(self):
        units = [{"unit_id": "shard_001"}]
        self.assertEqual(self.run_summary({"input_units": units, "completed_units": []}), 1)
        self.assertEqual(self.run_summary({"input_units": units, "completed_units": ["shard_001"]}), 0)

    def test_extract_checkpoint_runs_from_data_root(self):
        # 非 mdf 的检查点（task_status.py）路径相对数据根目录
        status = self.root / "sources" / "demo" / "processed" / "local_shards" / "task_status.json"
        status.parent.mkdir(parents=True)
        status.write_text(json.dumps({"input_units": [{"unit_id": "shard_001"}], "completed_units": ["shard_001"]}),
                          encoding="utf-8")
        phase, step = harness.find_step(ps.load_stage_tree(), "extract")
        check = sr._checkpoint(step["checkpoint"], "demo", self.root)
        self.assertEqual(check["exit_code"], 0, check)
        self.assertTrue(check["command"].endswith("--strict"))


class UsageRecords(TempRoot):
    RESULT = {"type": "result", "subtype": "success", "num_turns": 14, "total_cost_usd": 0.4712,
              "usage": {"input_tokens": 12, "output_tokens": 9876, "cache_read_input_tokens": 1500000,
                        "cache_creation_input_tokens": 80000},
              "subagent_stats": {"spawned": 1}}

    def test_parse_claude_json_result(self):
        log = self.root / "run.log"
        log.write_text("启动中\n" + json.dumps(self.RESULT), encoding="utf-8")
        usage = sr.parse_usage(log, "claude-json")
        self.assertEqual(usage, {"cost_usd": 0.4712, "turns": 14, "input_tokens": 12, "output_tokens": 9876,
                                 "cache_read_tokens": 1500000, "cache_write_tokens": 80000, "subagents": 1})
        self.assertEqual(sr.usage_text(usage), "$0.47 · 14 轮 · 输出 9,876 token · 又派了 1 个子代理")

    def test_plain_text_log_has_no_usage(self):
        log = self.root / "run.log"
        log.write_text("完成了 {不是 JSON}", encoding="utf-8")
        self.assertIsNone(sr.parse_usage(log, "claude-json"))
        self.assertEqual(sr.usage_text(None), "")

    def test_claude_code_asks_for_json_output(self):
        claude = harness.harness_profiles()["claude-code"]
        self.assertEqual(claude.usage_parser, "claude-json")
        self.assertIn("stream-json", claude.argv("claude", "x", usage=True))

    def test_status_board_shows_usage_and_total(self):
        runs = [{"started_at": "2026-10-18 10:00:00", "step": "review", "harness": "claude-code", "seconds": 120,
                 "ok": True, "summary": "x", "usage": {"cost_usd": 0.69, "turns": 1, "subagents": 1}},
                {"started_at": "2026-10-18 09:00:00", "step": "extract", "harness": "codex", "seconds": 90,
                 "ok": True, "summary": "y"}]
        html = ps.render_html("demo", ps.collect_status("demo", self.root), runs=runs)
        self.assertIn("$0.69 · 1 轮 · 子代理 1", html)
        self.assertIn("共 2 次运行，有用量记录的 1 次合计 $0.69", html)

    def test_status_board_reads_older_flat_records(self):
        # main 上的 mdf run 曾把 cost_usd、turns 平铺在记录顶层；这些记录照样显示、计入合计
        runs = [{"started_at": "2026-10-17 10:00:00", "step": "extract", "harness": "claude-code", "seconds": 60,
                 "ok": True, "summary": "x", "cost_usd": 0.68, "turns": 10}]
        html = ps.render_html("demo", ps.collect_status("demo", self.root), runs=runs)
        self.assertIn("$0.68 · 10 轮", html)
        self.assertIn("合计 $0.68", html)
        section = html[html.index("运行记录（mdf run）"):]
        self.assertEqual(section.count("<th>"), section.split("</tr>", 2)[1].count("<td>"), "表头与每行的列数一致")


if __name__ == "__main__":
    unittest.main()
