from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE_SECTIONS = [
    "身份卡", "响应策略", "核心原则", "决策框架",
    "已知盲区", "表达风格 DNA", "价值取向与反模式", "溯源",
]


class V6CoreTemplateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.path = ROOT / "templates" / "skill-template.v6.zh.md"
        self.text = self.path.read_text(encoding="utf-8")

    def test_declares_format_version_6(self) -> None:
        self.assertRegex(self.text, r"(?m)^format_version:\s*6\s*$")

    def test_has_no_english_block(self) -> None:
        self.assertNotRegex(self.text, r"(?m)^##\s+English")

    def test_has_no_language_detection_header(self) -> None:
        self.assertNotIn("Language Detection", self.text)

    def test_contains_all_core_sections(self) -> None:
        for name in CORE_SECTIONS:
            with self.subTest(section=name):
                self.assertRegex(self.text, rf"(?m)^#{{2,4}}\s*.*{re.escape(name)}")

    def test_has_case_index_section(self) -> None:
        self.assertRegex(self.text, r"(?m)^##\s*案例索引\s*$")

    def test_principle_block_has_failure_boundary(self) -> None:
        self.assertIn("{failure_boundary_zh}", self.text)

    def test_principle_block_has_prerequisite_intel(self) -> None:
        self.assertIn("{prerequisite_intel_zh}", self.text)

    def test_declares_attachment_read_triggers(self) -> None:
        for ref in ("references/cases.md", "references/evidence.md", "references/voice.md"):
            with self.subTest(ref=ref):
                self.assertIn(ref, self.text)

    def test_principle_count_guidance_is_nine_to_eleven(self) -> None:
        self.assertIn("9-11", self.text)

    def test_is_under_line_cap(self) -> None:
        self.assertLessEqual(len(self.text.splitlines()), 500)


class AttachmentTemplateTests(unittest.TestCase):
    def test_all_four_attachment_templates_exist(self) -> None:
        for name in ("cases.zh.md", "evidence.zh.md", "voice.zh.md", "dossier.zh.md"):
            with self.subTest(name=name):
                self.assertTrue((ROOT / "templates" / "refs" / name).exists())

    def test_evidence_template_matches_parser_contract(self) -> None:
        text = (ROOT / "templates" / "refs" / "evidence.zh.md").read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^###\s+原则")
        self.assertRegex(text, r"(?m)^>\s")
        self.assertRegex(text, r"(?m)^-\s*confidence\s*[：:]")
        self.assertIn("textual_note", text)

    def test_cases_template_matches_parser_contract(self) -> None:
        text = (ROOT / "templates" / "refs" / "cases.zh.md").read_text(encoding="utf-8")
        self.assertIn("case_id:", text)
        self.assertRegex(text, r"(?m)^\*\*对应原则簇：\*\*")
        self.assertIn("反例", text)

    def test_voice_template_has_positive_and_negative_pair(self) -> None:
        text = (ROOT / "templates" / "refs" / "voice.zh.md").read_text(encoding="utf-8")
        self.assertIn("为什么像他", text)
        self.assertIn("误写成通用分析腔", text)

    def test_dossier_template_records_rejected_candidates(self) -> None:
        text = (ROOT / "templates" / "refs" / "dossier.zh.md").read_text(encoding="utf-8")
        self.assertIn("被舍弃", text)


class Rule4Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")

    def test_rule4_no_longer_mandates_bilingual_by_default(self) -> None:
        self.assertNotIn(
            "the final deliverable MUST be one `SKILL.md` containing both languages",
            self.text,
        )

    def test_rule4_declares_chinese_default(self) -> None:
        self.assertIn("Chinese-only by default", self.text)

    def test_rule4_declares_english_as_separate_skill(self) -> None:
        self.assertIn("{person-slug}-wisdom-en", self.text)

    def test_platform_constraint_still_states_skill_md_requirement(self) -> None:
        self.assertIn("requires exactly `SKILL.md`", self.text)


if __name__ == "__main__":
    unittest.main()
