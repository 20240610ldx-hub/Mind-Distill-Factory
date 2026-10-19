from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKTICK_PATH_RE = re.compile(r"`([A-Za-z0-9_一-鿿./{}-]+\.(?:md|json|py))`")
PLACEHOLDER_RE = re.compile(r"\{[a-z_]+\}")

V6_DOCS = [
    ROOT / "agents" / "skill-assembler.md",
    ROOT / "agents" / "case-builder.md",
    ROOT / "agents" / "evidence-carder.md",
    ROOT / "agents" / "quality-reviewer.md",
    ROOT / "commands" / "distill.md",
]


def resolvable(rel: str) -> bool:
    """去掉 {slug} 之类占位符后判断路径是否存在（占位路径按目录前缀判断）。"""
    if PLACEHOLDER_RE.search(rel):
        prefix = rel.split("{")[0].rstrip("/")
        return bool(prefix) and (ROOT / prefix).exists()
    return (ROOT / rel).exists()


class AgentPathTests(unittest.TestCase):
    def test_every_backtick_path_in_v6_docs_resolves(self) -> None:
        for doc in V6_DOCS:
            if not doc.exists():
                self.fail(f"missing doc: {doc}")
            for match in BACKTICK_PATH_RE.finditer(doc.read_text(encoding="utf-8")):
                rel = match.group(1)
                if rel.startswith(("http", "~")):
                    continue
                with self.subTest(doc=doc.name, path=rel):
                    self.assertTrue(resolvable(rel), f"{doc.name} references missing `{rel}`")


class AssemblerContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = (ROOT / "agents" / "skill-assembler.md").read_text(encoding="utf-8")

    def test_targets_v6_template(self) -> None:
        self.assertIn("templates/skill-template.v6.zh.md", self.text)

    def test_no_longer_merges_bilingual_blocks(self) -> None:
        self.assertNotIn("## English", self.text)

    def test_emits_format_version(self) -> None:
        self.assertIn("format_version: 6", self.text)

    def test_states_line_cap(self) -> None:
        self.assertIn("500", self.text)

    def test_allows_several_case_ids_per_index_row(self) -> None:
        # P5 已接受 case_id 列一格多 id；组装器得知道这条省行的路（鲁迅验收发现 12）
        self.assertIn("一格可放多个 case_id", self.text)


class CaseBuilderContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = (ROOT / "agents" / "case-builder.md").read_text(encoding="utf-8")

    def test_requires_proof_line(self) -> None:
        self.assertIn("首行为证", self.text)

    def test_requires_two_cases_per_cluster(self) -> None:
        self.assertIn("每个原则簇", self.text)
        self.assertIn("2", self.text)

    def test_requires_counter_case(self) -> None:
        self.assertIn("反例", self.text)


class EvidenceCarderContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = (ROOT / "agents" / "evidence-carder.md").read_text(encoding="utf-8")

    def test_forbids_stitching(self) -> None:
        self.assertIn("缝合", self.text)

    def test_mentions_textual_note_escape_hatch(self) -> None:
        self.assertIn("textual_note", self.text)

    def test_names_the_p2_gate(self) -> None:
        self.assertIn("P2", self.text)


class ReviewerContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = (ROOT / "agents" / "quality-reviewer.md").read_text(encoding="utf-8")

    def test_drops_bilingual_equivalence_from_default_path(self) -> None:
        self.assertIn("仅在英文分支", self.text)

    def test_adds_case_layer_dimension(self) -> None:
        self.assertIn("案例层", self.text)

    def test_defers_quote_verification_to_deterministic_gate(self) -> None:
        self.assertIn("verify_provenance", self.text)


class AlignmentReviewerContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = (ROOT / "agents" / "framework-alignment-reviewer.md").read_text(
            encoding="utf-8"
        )

    def test_has_a_chinese_self_check_mode(self) -> None:
        self.assertIn("中文自检", self.text)

    def test_self_check_covers_the_two_new_principle_fields(self) -> None:
        self.assertIn("失效边界", self.text)
        self.assertIn("情报前提", self.text)

    def test_bilingual_mode_is_conditional(self) -> None:
        self.assertIn("en_requested.flag", self.text)


class OrchestratorContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = (ROOT / "commands" / "distill.md").read_text(encoding="utf-8")

    def test_has_attachment_stage(self) -> None:
        self.assertIn("Stage 4.5", self.text)

    def _stage_45(self) -> str:
        match = re.search(r"^## Stage 4\.5.*?(?=^### ✓ 检查点)", self.text, re.MULTILINE | re.DOTALL)
        self.assertIsNotNone(match, "distill.md 缺少 Stage 4.5 章节")
        return match.group(0)

    def test_stage_45_names_who_writes_back_the_case_index(self) -> None:
        # 鲁迅验收发现 13：只写了「附件齐备后回写」，没说谁回写——编排器不知道该把这步派给谁
        section = self._stage_45()
        self.assertRegex(section, r"skill-assembler（续）[^\n]*回写[^\n]*案例索引|案例索引[^\n]*skill-assembler（续）")

    def test_stage_45_states_the_line_budget_for_the_write_back(self) -> None:
        # 占位行按簇写，回写成每案一行会多出二十多行；预算不写明，回写后才撞 P6 的 500 行上限
        section = self._stage_45()
        self.assertIn("500", section)
        self.assertIn("同一原则", section)

    def test_has_english_on_demand_stage(self) -> None:
        self.assertIn("Stage 6.5", self.text)

    def test_english_stage_writes_the_flag_file(self) -> None:
        self.assertIn("en_requested.flag", self.text)

    def test_english_installs_to_separate_directory(self) -> None:
        self.assertIn("{person-slug}-wisdom-en", self.text)

    def test_stage3_no_longer_runs_en_synthesizer_by_default(self) -> None:
        self.assertIn("默认只跑中文", self.text)

    def test_checkpoint_uses_package_stage(self) -> None:
        self.assertIn("validate_output.py package", self.text)

    def test_install_copies_references_directory(self) -> None:
        self.assertIn("references/", self.text)

    def test_dossier_excluded_from_install(self) -> None:
        self.assertIn("人物档案.md", self.text)
        install_section = self.text[self.text.index("### 6.3"):]
        self.assertIn("不进安装目录", install_section)


class RegressionProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = (ROOT / "evaluation" / "regression-protocol.md").read_text(encoding="utf-8")

    def test_adds_attachment_read_checkpoint(self) -> None:
        self.assertIn("附件是否被读取", self.text)

    def test_requires_two_successful_attachment_reads(self) -> None:
        self.assertIn("至少 2 次", self.text)

    def test_requires_core_only_turns_to_hold_quality(self) -> None:
        self.assertIn("未读附件", self.text)


class PrincipleCountConsistencyTests(unittest.TestCase):
    """v6 targets 9-11 core principles. That count has drifted back to the legacy 5-8 in
    files V6_DOCS never scans (templates and downstream agent docs) three separate times.
    These assertions target the specific *target-count* statement — a repeat_block's
    principle count, or a line stating "目标"/"Target" — rather than banning the "5-8"
    substring outright, because both synthesizers legitimately explain that
    format_version: 6 widens the legacy 5-8 range to v6's 8-11; that contrastive prose
    must stay untouched.
    """

    REPEAT_BLOCK_PRINCIPLE_RE = re.compile(
        r"\{repeat_block:\s*([0-9]+-[0-9]+)\s*principles", re.IGNORECASE
    )
    TARGET_RE = re.compile(r"(?:目标\s*\*{0,2}|[Tt]arget\s*\*{0,2})([0-9]+-[0-9]+)")

    def test_v6_templates_declare_9_11_principle_repeat_block(self) -> None:
        for path in (
            ROOT / "templates" / "skill-template.v6.zh.md",
            ROOT / "templates" / "skill-template.en.md",
        ):
            text = path.read_text(encoding="utf-8")
            counts = self.REPEAT_BLOCK_PRINCIPLE_RE.findall(text)
            with self.subTest(template=path.name):
                self.assertIn("9-11", counts, f"{path.name}: no repeat_block declares 9-11 principles")
                self.assertNotIn("5-8", counts, f"{path.name}: a repeat_block still declares 5-8 principles")

    def test_synthesizers_state_9_11_target_not_5_8(self) -> None:
        for path in (
            ROOT / "agents" / "framework-synthesizer-zh.md",
            ROOT / "agents" / "framework-synthesizer-en.md",
        ):
            text = path.read_text(encoding="utf-8")
            targets = self.TARGET_RE.findall(text)
            with self.subTest(agent=path.name):
                self.assertIn("9-11", targets, f"{path.name}: no explicit 9-11 target statement found")
                self.assertNotIn("5-8", targets, f"{path.name}: still states a 5-8 target")


class PipelineWiringTests(unittest.TestCase):
    """鲁迅验收修复要落到管线每个入口，而不只是校验器多一条警告。

    `mdf run` / Codex / pi 的简报只拼角色定义（agents/*.md）和阶段树的 checkpoint_note，不读 distill.md；
    Claude Code 编排者读 distill.md。两条路都得知道遇到这些信号该怎么走。
    """

    def setUp(self) -> None:
        self.orchestrator = (ROOT / "commands" / "distill.md").read_text(encoding="utf-8")
        self.carder = (ROOT / "agents" / "evidence-carder.md").read_text(encoding="utf-8")
        self.reviewer = (ROOT / "agents" / "quality-reviewer.md").read_text(encoding="utf-8")
        tree = json.loads((ROOT / "config" / "pipeline_stages.json").read_text(encoding="utf-8"))
        self.steps = {s["id"]: s for phase in tree["phases"] for s in phase["steps"]}

    def _section(self, heading: str) -> str:
        match = re.search(rf"^### ✓ {heading}.*?(?=^## |^### )", self.orchestrator, re.MULTILINE | re.DOTALL)
        self.assertIsNotNone(match, heading)
        return match.group(0)

    def test_evidence_carder_knows_the_off_corpus_cap(self) -> None:
        for code in ("P2_UNVERIFIED_HIGH", "P2_COVERAGE"):
            self.assertIn(code, self.carder)

    def test_reviewer_reports_p2_coverage(self) -> None:
        self.assertIn("P2_COVERAGE", self.reviewer)

    def test_checkpoint_4_routes_the_new_signals(self) -> None:
        section = self._section("检查点 4")
        for code in ("P2_UNVERIFIED_HIGH", "P2_COVERAGE"):
            self.assertIn(code, section)
        self.assertIn("合并", section)  # P6_TOO_LONG 先合并案例索引的行，再考虑减原则

    def test_checkpoint_1_routes_fixable_shortfalls(self) -> None:
        section = self._section("检查点 1")
        self.assertIn("[可改善]", section)
        self.assertIn("[不可改善]", section)

    def test_checkpoint_2_routes_too_few_principles(self) -> None:
        section = self._section("检查点 2")
        self.assertIn("原则候选不足", section)

    def test_briefs_carry_the_routing_for_each_harness(self) -> None:
        self.assertIn("[可改善]", self.steps["reduce"].get("checkpoint_note", ""))
        self.assertIn("原则候选不足", self.steps["principles"].get("checkpoint_note", ""))
        note = self.steps["attachments"].get("checkpoint_note", "")
        for needle in ("P2_UNVERIFIED_HIGH", "P2_COVERAGE", "500"):
            self.assertIn(needle, note)


if __name__ == "__main__":
    unittest.main()
