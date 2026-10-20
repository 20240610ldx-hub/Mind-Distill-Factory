"""墨子试跑（docs/harness-trial-mozi.md）里发现并修复的问题的回归测试。"""

from __future__ import annotations

import json
import os
import re
import tempfile
import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from sibling import load_module  # noqa: E402  按路径加载模块的唯一入口（先登记 sys.modules）


harness = load_module(ROOT / "scripts" / "harness.py", "_harness_trial_fixes")
acquire = load_module(ROOT / "scripts" / "acquire.py", "_acquire_trial_fixes")
validate_output = load_module(ROOT / "scripts" / "validate_output.py", "_validate_output_trial_fixes")


class CleaningReportIsNotASourceFile(unittest.TestCase):
    """mdf index 写出的 cleaning_report.json 是元数据，不能被 `validate sources` 当来源 JSON 校验。"""

    def test_cleaning_report_is_skipped(self):
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as td:
            processed = Path(td) / "sources" / "demo" / "processed"
            processed.mkdir(parents=True)
            (processed / "cleaning_report.json").write_text(json.dumps({"sources": []}), encoding="utf-8")
            os.chdir(td)
            try:
                errors = validate_output.validate_sources("demo")
            finally:
                os.chdir(cwd)
        joined = "\n".join(errors)
        self.assertNotIn("cleaning_report.json: 'person'", joined)
        self.assertNotIn("source_type='None'", joined)
        self.assertIn("EMPTY_DIR", joined, "只有元数据文件时应报「没有来源抽取文件」")


class StepLevelCheckpoint(unittest.TestCase):
    """分片抽取是阶段 1 的中间步骤：简报不能要求它先通过整个阶段的 `validate sources`。"""

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

    def test_extract_brief_uses_task_status_checkpoint(self):
        _, text = harness.build_brief("demo", "extract", self.root)
        self.assertIn("task_status.py summary sources/demo/processed/local_shards/task_status.json", text)
        self.assertNotIn("validate sources demo", text)

    def test_reduce_brief_keeps_phase_checkpoint(self):
        _, text = harness.build_brief("demo", "reduce", self.root)
        self.assertIn("python scripts/mdf.py validate sources demo", text)

    def test_assemble_brief_explains_expected_missing_attachments(self):
        _, text = harness.build_brief("demo", "assemble", self.root)
        self.assertIn("python scripts/mdf.py validate package demo", text)
        self.assertIn("- 说明：", text)
        self.assertIn("MISSING references/*", text)

    def test_steps_without_note_have_no_note_line(self):
        _, text = harness.build_brief("demo", "extract", self.root)
        self.assertNotIn("- 说明：", text)

    def test_reduce_brief_routes_thin_corpus_labels(self):
        # 鲁迅验收发现 6 落到管线：Codex / pi / 无头进程只看简报，[可改善] 与 [不可改善] 怎么走得写在简报里
        _, text = harness.build_brief("demo", "reduce", self.root)
        self.assertIn("- 说明：", text)
        self.assertIn("[可改善]", text)
        self.assertIn("[不可改善]", text)

    def test_attachments_brief_covers_voice_and_index_backfill(self):
        # voice.md 与案例索引回写由 skill-assembler 续写完成；简报里没有这个角色，附件阶段永远过不了 P3/P5。
        _, text = harness.build_brief("demo", "attachments", self.root)
        roles = re.findall(r"^## 角色定义：(\S+)$", text, re.MULTILINE)
        self.assertEqual(roles, ["case-builder", "evidence-carder", "skill-assembler"])

    def test_review_brief_has_a_real_checkpoint(self):
        # 审查步骤曾没有检查点，执行者自己编了不存在的 `validate review`。
        _, text = harness.build_brief("demo", "review", self.root)
        self.assertIn("## 完成标准", text)
        self.assertIn("python scripts/mdf.py validate package demo --strict", text)
        self.assertIn("output/demo/review.md", text)
        self.assertNotIn("{slug}", text)


class WikisourceHeaderContainerDropped(unittest.TestCase):
    """页眉模板是 <div id="headerContainer">：不剥掉的话，「下一篇」题名会混进正文开头，误导抽取者标错篇名。"""

    PAGE = (
        '<div class="mw-parser-output"><div id="headerContainer"><table><tr>'
        '<td>目錄</td><td>墨子<br>節用上<br>作者：墨翟</td><td><a>節用中</a></td></tr></table></div>'
        '<p>聖人爲政一國，一國可倍也。</p></div>'
    )

    def test_header_navigation_is_removed(self):
        text = acquire.html_to_text(self.PAGE, "mw-parser-output")
        self.assertEqual(text.strip(), "聖人爲政一國，一國可倍也。")
        self.assertNotIn("節用中", text)


class ClaudeCodeIsolatedRun(unittest.TestCase):
    def test_headless_command_allows_shell_for_checkpoints(self):
        # 只给 acceptEdits 时，无头进程里的 Bash 被拦（实测），执行者连检查点命令都跑不了。
        profiles = harness.load_profiles()
        run = harness.launch_commands("output/demo/briefs/x.md", profiles, "claude-code")["claude-code"]
        self.assertIn("--allowedTools", run)
        self.assertIn("Bash", run.split("--allowedTools", 1)[1])


if __name__ == "__main__":
    unittest.main()
