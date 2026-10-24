"""harness 适配层：profiles 配置、适配文件核对、安装计划、任务简报、架构图与配置同步。"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
import shutil
import tempfile
import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from sibling import load_module  # noqa: E402  按路径加载模块的唯一入口（先登记 sys.modules）


harness = load_module(ROOT / "scripts" / "harness.py", "_harness_under_test")
mdf = load_module(ROOT / "scripts" / "mdf.py", "_mdf_for_harness_test")
ps = load_module(ROOT / "scripts" / "pipeline_status.py", "_ps_for_harness_test")


def run_mdf(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = mdf.main(list(argv))
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
    return code, out.getvalue(), err.getvalue()


def mdf_subcommands() -> set[str]:
    parser = mdf.build_parser()
    action = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    return set(action.choices)


class ProfilesTests(unittest.TestCase):
    def setUp(self):
        self.profiles = harness.load_profiles()

    def test_every_harness_is_fully_described(self):
        self.assertEqual(set(self.profiles["harnesses"]), {"claude-code", "codex", "pi"})
        for name, p in self.profiles["harnesses"].items():
            with self.subTest(harness=name):
                for key in ("label", "executables", "instruction_files", "orchestrator", "skill_dirs",
                            "subagents", "isolated_run", "chapters", "sources"):
                    self.assertIn(key, p)
                self.assertIn("{prompt}", p["isolated_run"])
                self.assertTrue(p["sources"] and all(s.startswith("https://") for s in p["sources"]))
                self.assertEqual(set(p["skill_dirs"]), {"user", "project"})
                self.assertTrue((ROOT / p["orchestrator"]["file"]).exists(), p["orchestrator"]["file"])
                for f in p["instruction_files"]:
                    self.assertTrue((ROOT / f).exists(), f)

    def test_codex_exec_uses_writable_sandbox_not_removed_flag(self):
        # codex exec 默认只读沙箱；--full-auto 已不再支持（learn.chatgpt.com/docs/non-interactive-mode）。
        run = self.profiles["harnesses"]["codex"]["isolated_run"]
        self.assertIn("--sandbox workspace-write", run)
        self.assertNotIn("--full-auto", run)

    def test_bad_schema_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "config").mkdir()
            (Path(td) / "config" / "harnesses.json").write_text('{"schema": "x"}', encoding="utf-8")
            with self.assertRaises(ValueError):
                harness.load_profiles(Path(td))


class FrontmatterTests(unittest.TestCase):
    def test_plain_quoted_and_folded(self):
        text = "---\nname: \"demo\"\ndescription: >-\n  第一行\n  第二行\nmodel: haiku\n---\n正文"
        self.assertEqual(harness.parse_frontmatter(text),
                         {"name": "demo", "description": "第一行 第二行", "model": "haiku"})

    def test_no_frontmatter(self):
        self.assertEqual(harness.parse_frontmatter("# 标题\n"), {})


class ProgressSurfaceTests(unittest.TestCase):
    """进度靠章节 + harness 原生任务清单；2026-10-19 GUI 验收时每阶段发一次 status.html，用户反馈多余。"""

    PROTOCOL = ["commands/distill.md", ".agents/skills/mdf-distill/SKILL.md", "AGENTS.md"]

    def test_protocol_does_not_ask_for_the_html_board(self):
        for rel in self.PROTOCOL:
            with self.subTest(file=rel):
                self.assertNotIn("--html", (ROOT / rel).read_text(encoding="utf-8"))

    def test_every_harness_declares_its_task_list(self):
        profiles = harness.load_profiles()["harnesses"]
        for name, profile in profiles.items():
            with self.subTest(harness=name):
                self.assertIsInstance(profile["tasks"]["native"], bool)
                self.assertTrue(profile["tasks"]["how"])
        self.assertEqual(profiles["claude-code"]["tasks"]["tools"], ["TaskCreate", "TaskUpdate"])

    def test_orchestrators_name_the_task_tools(self):
        distill = (ROOT / "commands" / "distill.md").read_text(encoding="utf-8")
        for tool in ("TaskCreate", "TaskUpdate", "config/harnesses.json"):
            self.assertIn(tool, distill)
        skill = (ROOT / ".agents" / "skills" / "mdf-distill" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("任务清单", skill)


class AdapterFileTests(unittest.TestCase):
    def test_repository_adapters_pass(self):
        checks = harness.adapter_checks()
        failed = [c for c in checks if c["required"] and not c["ok"]]
        self.assertEqual(failed, [])

    def test_plugin_manifest(self):
        manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], harness.PLUGIN_NAME)
        # claude plugin validate：claude-/anthropic- 前缀与这些保留名会被拒绝。
        self.assertFalse(re.match(r"^(claude|anthropic|anthropics|cc-plugin)-", manifest["name"]))
        self.assertIn("name", manifest["author"])

    def test_orchestrator_skill_follows_agent_skills_spec(self):
        path = ROOT / harness.load_profiles()["orchestrator_skill"]
        meta = harness.parse_frontmatter(path.read_text(encoding="utf-8"))
        self.assertEqual(meta["name"], path.parent.name)
        self.assertRegex(meta["name"], harness.SKILL_NAME_RE)
        self.assertLessEqual(len(meta["description"]), harness.SKILL_DESCRIPTION_MAX)

    def test_missing_adapters_are_reported(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "config").mkdir()
            shutil.copy(ROOT / "config" / "harnesses.json", root / "config" / "harnesses.json")
            (root / "agents").mkdir()
            (root / "agents" / "x-role.md").write_text("---\nname: other\n---\n", encoding="utf-8")
            (root / "AGENTS.md").write_text("Bilingual output: ## English + ## 中文版\n", encoding="utf-8")
            by_name = {c["name"]: c for c in harness.adapter_checks(root)}
            self.assertFalse(by_name["Claude Code 插件清单"]["ok"])
            self.assertFalse(by_name["跨 harness 编排 skill（Codex / pi）"]["ok"])
            self.assertFalse(by_name["子代理定义 agents/*.md"]["ok"])
            stale = by_name["AGENTS.md 与 v6 规则一致"]
            self.assertFalse(stale["ok"])
            self.assertFalse(stale["required"], "过时的 AGENTS.md 只警告，不阻断")

    def test_detect_uses_injected_which(self):
        found = harness.detect(harness.load_profiles(), which=lambda exe: f"/bin/{exe}" if exe == "pi" else None)
        self.assertEqual(found, {"claude-code": None, "codex": None, "pi": "/bin/pi"})

    def test_docs_and_skill_only_use_real_mdf_subcommands(self):
        known = mdf_subcommands()
        files = [ROOT / "docs" / n for n in ("architecture.md", "harnesses.md", "ethics-and-legal.md", "methodology.md")]
        files.append(ROOT / harness.load_profiles()["orchestrator_skill"])
        for path in files:
            for sub in re.findall(r"python scripts/mdf\.py ([a-z]+)", path.read_text(encoding="utf-8")):
                with self.subTest(file=path.name, sub=sub):
                    self.assertIn(sub, known)


class InstallPlanTests(unittest.TestCase):
    def test_codex_user_plan_for_pilot(self):
        plan = harness.install_plan("zhang-juzheng-v6", "codex")
        self.assertEqual(plan["destination"], "~/.agents/skills/zhang-juzheng-v6-wisdom")
        bash = plan["commands"]["bash"]
        self.assertNotIn('"~', bash, "引号里的 ~ 不会展开")
        self.assertIn("$HOME/.agents/skills/zhang-juzheng-v6-wisdom", bash)
        self.assertIn(harness.DOSSIER_NAME, bash)
        self.assertIn("$HOME\\.agents\\skills\\zhang-juzheng-v6-wisdom", plan["commands"]["powershell"])
        self.assertTrue(any("argument-hint" in w for w in plan["warnings"]))

    def test_claude_code_project_scope(self):
        plan = harness.install_plan("zhang-juzheng-v6", "claude-code", scope="project")
        self.assertEqual(plan["destination"], ".claude/skills/zhang-juzheng-v6-wisdom")
        self.assertFalse(any("argument-hint" in w for w in plan["warnings"]))

    def test_unknown_target_and_unpublished_slug(self):
        with self.assertRaises(SystemExit):
            harness.install_plan("zhang-juzheng-v6", "cursor")
        with self.assertRaises(SystemExit):
            harness.install_plan("no-such-person", "codex")

    def test_plan_writes_nothing(self):
        before = sorted(p.as_posix() for p in (ROOT / "gallery").rglob("*"))
        code, out, _ = run_mdf("harness", "plan", "zhang-juzheng-v6", "--target", "pi", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["target"], "pi")
        self.assertEqual(sorted(p.as_posix() for p in (ROOT / "gallery").rglob("*")), before)


class BriefTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        (self.root / "output" / "demo").mkdir(parents=True)
        # 原则提取之后的步骤要求用户已确认的类目（阶段 0 的 mdf classify）
        (self.root / "sources" / "demo").mkdir(parents=True)
        (self.root / "sources" / "demo" / "classification.json").write_text(
            '{"primary": "governance", "secondary": ["philosophy"]}', encoding="utf-8")

    def tearDown(self):
        self._td.cleanup()

    def test_review_brief_is_self_contained_and_isolated(self):
        step, text = harness.build_brief("demo", "review", self.root)
        self.assertEqual(step, "review")
        self.assertIn("## 角色定义：quality-reviewer", text)
        self.assertIn("独立审查者", text)
        self.assertIn("## 阶段 5 · 质量审查", text)
        self.assertIn("sources/demo/raw/", text)
        self.assertIn("output/demo/review.md", text, "角色定义里的 {person_slug} 也要替换")
        for placeholder in harness.SLUG_PLACEHOLDERS:
            self.assertNotIn(placeholder, text)

    def test_multi_role_step_keeps_order(self):
        _, text = harness.build_brief("demo", "frameworks", self.root)
        roles = re.findall(r"^## 角色定义：(\S+)$", text, re.MULTILINE)
        self.assertEqual(roles, ["framework-core-synthesizer", "framework-synthesizer-zh", "framework-alignment-reviewer"])
        self.assertIn("python scripts/mdf.py validate frameworks demo", text)

    def test_default_step_with_local_material_is_shard_extraction(self):
        raw = self.root / "sources" / "demo" / "raw"
        raw.mkdir(parents=True)
        (raw / "a.txt").write_text("月有考，岁有稽。", encoding="utf-8")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            step, text = harness.build_brief("demo", None, self.root)
        self.assertEqual(step, "extract")
        self.assertIn("## 角色定义：local-source-worker", text)
        self.assertIn("WARNING", err.getvalue(), "前面还有未完成的脚本步骤（index），要提醒")

    def test_default_step_without_local_material_is_the_acquisition_scout(self):
        # 没有本地素材时，第一个 agent 步骤是采集计划：acquisition-scout 凭记忆列候选（不联网）。
        with contextlib.redirect_stderr(io.StringIO()):
            step, text = harness.build_brief("demo", None, self.root)
        self.assertEqual(step, "plan")
        self.assertIn("## 角色定义：acquisition-scout", text)

    def test_script_step_and_unknown_step_rejected(self):
        for step in ("publish", "no-such-step"):
            with self.subTest(step=step), self.assertRaises(SystemExit):
                harness.build_brief("demo", step, self.root)

    def test_cli_writes_brief_and_prints_launch_commands(self):
        code, out, _ = run_mdf("brief", "demo", "review", "--root", str(self.root), "--harness", "codex")
        self.assertEqual(code, 0)
        path = self.root / "output" / "demo" / "briefs" / "review.md"
        self.assertTrue(path.exists())
        self.assertIn("codex exec --sandbox workspace-write", out)
        self.assertNotIn("pi -p", out)

    def test_launch_commands_embed_path(self):
        commands = harness.launch_commands("output/demo/briefs/x.md", harness.load_profiles())
        self.assertEqual(set(commands), {"claude-code", "codex", "pi"})
        self.assertTrue(all("output/demo/briefs/x.md" in c for c in commands.values()))


class ArchitectureDiagramTests(unittest.TestCase):
    def test_embedded_stage_diagram_matches_config(self):
        text = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
        match = re.search(
            r"<!-- BEGIN GENERATED: mdf stages --mermaid -->\n```mermaid\n(.*?)```\n<!-- END GENERATED -->", text, re.S
        )
        self.assertIsNotNone(match, "architecture.md 缺少生成的阶段图区块")
        self.assertEqual(match.group(1), ps.render_mermaid(ps.load_stage_tree(ROOT)),
                         "阶段树改了：运行 python scripts/mdf.py stages --mermaid 并替换 architecture.md 里的区块")

    def test_mermaid_has_every_step_and_checkpoint(self):
        tree = ps.load_stage_tree(ROOT)
        diagram = ps.render_mermaid(tree)
        for phase in tree["phases"]:
            for step in phase["steps"]:
                self.assertIn(f'{phase["id"]}_{step["id"]}', diagram)
            if phase.get("checkpoint"):
                self.assertIn(f'{phase["id"]}_checkpoint', diagram)

    def test_cli_mermaid_flag(self):
        code, out, _ = run_mdf("stages", "--mermaid")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("flowchart TD"))


class HarnessCliTests(unittest.TestCase):
    def test_list_json(self):
        code, out, _ = run_mdf("harness", "--json")
        report = json.loads(out)
        self.assertEqual(report["schema"], "mdf-harness-v1")
        self.assertEqual(code, 0 if report["ok"] else 1)
        self.assertEqual({h["id"] for h in report["harnesses"]}, {"claude-code", "codex", "pi"})

    def test_list_markdown_default(self):
        code, out, _ = run_mdf("harness")
        self.assertIn("## harness 适配", out)


if __name__ == "__main__":
    unittest.main()
