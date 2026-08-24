from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()
