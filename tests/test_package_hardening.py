"""M4：P1–P6 加固规则 1–16 与 --strict S1–S4。

每条规则都从一个完全合规的夹具出发，只改一处，断言报出对应错误码；
同时断言合规夹具与真实样板包（gallery/zhang-juzheng-v6）不报错——
既防「该拒的报 clean」，也防「把真实内容误判」。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from sibling import load_module  # noqa: E402  按路径加载模块的唯一入口（先登记 sys.modules）
PILOT = ROOT / "gallery" / "zhang-juzheng-v6"


fx_mod = load_module(ROOT / "tests" / "test_package_v6.py", "_package_v6_fixtures_hard")
validator = fx_mod.validator
pm = load_module(ROOT / "scripts" / "package_manifest.py", "_pm_hard")
prov = load_module(ROOT / "scripts" / "verify_provenance.py", "_prov_hard")
registry_mod = load_module(ROOT / "scripts" / "source_registry.py", "_registry_hard")

CASE_INDEX = "## 案例索引\n\n| demo-c1-1 | demo-c1-2 | demo-counter-1 |\n"


def codes(errors: list[str]) -> list[str]:
    return [e.split(":", 1)[0] for e in errors]


def register_sources(root: Path, rights: str = "public_domain") -> None:
    """给夹具语料写 source_registry.json——strict S4 要求证据来源已登记且权利放行。"""
    raw = root / "sources" / "demo" / "raw"
    registry = registry_mod.build_registry(raw, rights_status=rights)
    registry_mod.write_registry(root / "sources" / "demo" / "processed" / "source_registry.json", registry)


class TempFile:
    def __init__(self, test: unittest.TestCase, name: str, text: str):
        self._td = tempfile.TemporaryDirectory()
        test.addCleanup(self._td.cleanup)
        self.path = Path(self._td.name) / name
        self.path.write_text(text, encoding="utf-8")


class PilotPassesAllRulesTests(unittest.TestCase):
    def test_pilot_structure_evidence_voice_residue(self) -> None:
        refs = PILOT / "references"
        self.assertEqual(validator.check_p6_structure(PILOT / "SKILL.md"), [])
        self.assertEqual(validator.check_evidence_cards(refs / "evidence.md", PILOT / "SKILL.md"), [])
        self.assertEqual(validator.check_voice_samples(refs / "voice.md"), [])
        self.assertEqual(
            validator.check_template_residue([PILOT / "SKILL.md", *sorted(refs.glob("*.md"))]), []
        )

    def test_pilot_cases_against_manifest_clusters(self) -> None:
        manifest, _ = pm.load_manifest(PILOT / "manifest.json")
        self.assertEqual(validator.check_p4_cases(PILOT / "references" / "cases.md", manifest["clusters"]), [])


# ── 规则 1–4、11：证据卡 ──────────────────────────────────────────────


class EvidenceTests(unittest.TestCase):
    def _check(self, evidence: str, skill: str | None = None) -> list[str]:
        ev = TempFile(self, "evidence.md", evidence)
        sk = TempFile(self, "SKILL.md", skill if skill is not None else fx_mod.build_skill_md())
        return validator.check_evidence_cards(ev.path, sk.path)

    def test_compliant_evidence_is_clean(self) -> None:
        self.assertEqual(self._check(fx_mod.build_evidence_md()), [])

    def test_rule1_empty_file(self) -> None:
        self.assertIn("EVIDENCE_EMPTY", codes(self._check("# 证据卡\n\n说明文字。\n")))

    def test_rule1_card_without_quote(self) -> None:
        text = fx_mod.build_evidence_md().replace("> 月有考，岁有稽\n", "", 1)
        self.assertIn("EVIDENCE_NO_QUOTE", codes(self._check(text)))

    def test_rule2_missing_source_or_confidence(self) -> None:
        for field in ("- 出处：《示例奏疏》\n", "- confidence：high\n"):
            with self.subTest(field=field):
                text = fx_mod.build_evidence_md().replace(field, "", 1)
                self.assertIn("EVIDENCE_MISSING_FIELD", codes(self._check(text)))

    def test_rule2_bad_confidence_value(self) -> None:
        text = fx_mod.build_evidence_md().replace("confidence：high", "confidence：很高", 1)
        self.assertIn("EVIDENCE_BAD_CONFIDENCE", codes(self._check(text)))

    def test_rule2_confidence_may_carry_annotation(self) -> None:
        text = fx_mod.build_evidence_md().replace("confidence：high", "confidence：medium（后人转引）", 1)
        self.assertEqual(self._check(text), [])

    def test_rule3_uncovered_principle(self) -> None:
        self.assertIn("EVIDENCE_PRINCIPLE_UNCOVERED", codes(self._check(fx_mod.build_evidence_md(7))))

    def test_rule3_supplement_cards_count_and_10_does_not_cover_1(self) -> None:
        cards = [fx_mod.evidence_card(i) for i in range(2, 9)]
        supplement = fx_mod.evidence_card(1).replace("### 原则 1：占位", "### 原则 1 补充：另一处")
        self.assertEqual(self._check("\n".join([supplement, *cards])), [])
        ten = fx_mod.evidence_card(10)
        errors = self._check("\n".join([ten, *cards]))
        self.assertTrue(any("核心原则 1 " in e for e in errors if e.startswith("EVIDENCE_PRINCIPLE_UNCOVERED")))

    def test_rule4_high_needs_corpus_location_medium_does_not(self) -> None:
        no_loc = fx_mod.build_evidence_md().replace("- 语料位置：`sources/demo/raw/corpus.txt`\n", "", 1)
        self.assertIn("EVIDENCE_HIGH_WITHOUT_CORPUS", codes(self._check(no_loc)))
        medium = no_loc.replace("confidence：high", "confidence：medium", 1)
        self.assertEqual(self._check(medium), [])

    def test_rule11_placeholder_adjudication(self) -> None:
        for note in ("待定", "TODO", "？", "…"):
            with self.subTest(note=note):
                card = fx_mod.evidence_card(1, extra=f"- textual_note：{note}\n")
                text = "\n".join([card] + [fx_mod.evidence_card(i) for i in range(2, 9)])
                self.assertIn("EVIDENCE_UNRESOLVED_ADJUDICATION", codes(self._check(text)))

    def test_rule11_substantive_adjudication_is_fine(self) -> None:
        card = fx_mod.evidence_card(1, extra="- textual_note：底本讹「稽」为「稿」，据万历本改。\n")
        text = "\n".join([card] + [fx_mod.evidence_card(i) for i in range(2, 9)])
        self.assertEqual(self._check(text), [])


# ── 规则 5–6：语感样本 ────────────────────────────────────────────────


class VoiceTests(unittest.TestCase):
    def _check(self, text: str) -> list[str]:
        return validator.check_voice_samples(TempFile(self, "voice.md", text).path)

    def test_compliant_voice_is_clean(self) -> None:
        self.assertEqual(self._check(fx_mod.build_voice_md()), [])

    def test_rule5_too_few(self) -> None:
        self.assertIn("VOICE_TOO_FEW", codes(self._check(fx_mod.build_voice_md(19))))

    def test_rule6_incomplete_sample(self) -> None:
        for marker in ("> 月有考，岁有稽。\n", "**为什么像他：** 斩截作结。\n", "**误写成通用分析腔会变成：** 我们需要定期复盘。\n"):
            with self.subTest(marker=marker):
                text = fx_mod.build_voice_md().replace(marker, "", 1)
                self.assertIn("VOICE_SAMPLE_INCOMPLETE", codes(self._check(text)))

    def test_rule6_accepts_feminine_pronoun(self) -> None:
        text = fx_mod.build_voice_md().replace("为什么像他", "为什么像她")
        self.assertEqual(self._check(text), [])


# ── 规则 7、12、14–16：核心层结构 ─────────────────────────────────────


class StructureTests(unittest.TestCase):
    def _check(self, skill: str) -> list[str]:
        return validator.check_p6_structure(TempFile(self, "SKILL.md", skill).path)

    def test_compliant_skill_is_clean(self) -> None:
        self.assertEqual(self._check(fx_mod.build_skill_md()), [])

    def test_rule7_missing_and_empty_dimension(self) -> None:
        base = fx_mod.build_skill_md()
        self.assertIn("P6_DNA_MISSING_DIMENSION", codes(self._check(base.replace("| 幽默风格 | 占位特征 |\n", ""))))
        self.assertIn("P6_DNA_EMPTY_DIMENSION", codes(self._check(base.replace("| 段落节奏 | 占位特征 |", "| 段落节奏 |  |"))))
        self.assertIn(
            "P6_DNA_EMPTY_DIMENSION",
            codes(self._check(base.replace("| 禁忌表达 | 占位特征 |", "| 禁忌表达 | {taboo_expressions_zh} |"))),
        )

    def test_rule7_calibration_needs_both_examples(self) -> None:
        text = fx_mod.build_skill_md().replace("- ❌ 偏离：「我们要勇敢追梦！」", "")
        self.assertIn("P6_DNA_NO_CALIBRATION", codes(self._check(text)))

    def test_rule12_needs_code_block(self) -> None:
        text = fx_mod.build_skill_md().replace("```\n第一关", "第一关").replace("渠道吗？\n```", "渠道吗？")
        self.assertIn("P6_DF_NO_CODE_BLOCK", codes(self._check(text)))

    def test_rule12_step_count_bounds(self) -> None:
        base = fx_mod.build_skill_md()
        two = base.replace("第三关·丙：留了纠错的渠道吗？\n", "").replace("执行的人选定了吗？\n    ↓\n", "执行的人选定了吗？\n")
        self.assertIn("P6_DF_STEP_COUNT", codes(self._check(two)))
        many = "\n    ↓\n".join(f"第{i}关：问题{i}？" for i in range(1, 10))
        nine = base.replace(
            "第一关·甲：这件事有可验证的目标吗？\n    ↓\n第二关·乙：执行的人选定了吗？\n    ↓\n第三关·丙：留了纠错的渠道吗？",
            many,
        )
        self.assertIn("P6_DF_STEP_COUNT", codes(self._check(nine)))

    def test_rule12_open_ended_final_step(self) -> None:
        text = fx_mod.build_skill_md().replace("留了纠错的渠道吗？", "综合判断后再决定。")
        self.assertIn("P6_DF_NOT_A_QUESTION", codes(self._check(text)))

    def test_rule12_ascii_question_mark_accepted(self) -> None:
        text = fx_mod.build_skill_md().replace("留了纠错的渠道吗？", "留了纠错的渠道吗?")
        self.assertEqual(self._check(text), [])

    def test_rule14_values_minimums(self) -> None:
        base = fx_mod.build_skill_md()
        self.assertIn("P6_VALUES_TOO_FEW", codes(self._check(base.replace("- 追求 2：占位条目。\n", ""))))
        no_tension = base.replace("### 内在张力（未解决的矛盾）\n\n- 张力 1：占位条目。", "")
        self.assertIn("P6_VALUES_TOO_FEW", codes(self._check(no_tension)))

    def test_rule15_blind_spot_mitigation(self) -> None:
        base = fx_mod.build_skill_md()
        no_mit = base.replace("2. **盲区乙**：占位解释。*缓解：* 占位缓解建议。", "2. **盲区乙**：占位解释。")
        self.assertIn("P6_BLIND_SPOT_NO_MITIGATION", codes(self._check(no_mit)))
        one = base.replace("\n2. **盲区乙**：占位解释。*缓解：* 占位缓解建议。", "")
        self.assertIn("P6_BLIND_SPOTS_TOO_FEW", codes(self._check(one)))

    def test_rule15_trailer_text_does_not_count_as_mitigation(self) -> None:
        text = fx_mod.build_skill_md().replace(
            "2. **盲区乙**：占位解释。*缓解：* 占位缓解建议。",
            "2. **盲区乙**：占位解释。\n\n**文化语境：** 此处提到应对二字也不算。",
        )
        self.assertIn("P6_BLIND_SPOT_NO_MITIGATION", codes(self._check(text)))

    def test_rule16_response_rule_counts(self) -> None:
        base = fx_mod.build_skill_md()
        self.assertIn(
            "P6_RESPONSE_RULES_TOO_FEW",
            codes(self._check(base.replace("- ⚠️ 反套公式指令 6：占位条目。\n", ""))),
        )
        self.assertIn(
            "P6_RESPONSE_RULES_TOO_FEW", codes(self._check(base.replace("### 边界规则", "### 其他规则")))
        )


# ── 规则 8–10：案例 ──────────────────────────────────────────────────


class CaseTests(unittest.TestCase):
    def _cases(self, td: str, *, clusters: int = 1, mutate=None) -> Path:
        fx = fx_mod.PackageFixture(td)
        fx.write_cases(clusters=clusters, counter=True)
        path = fx.refs / "cases.md"
        if mutate:
            path.write_text(mutate(path.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")
        return path

    def test_rule8_duplicate_case_id(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = self._cases(td, mutate=lambda t: t.replace("demo-c1-2", "demo-c1-1"))
            self.assertIn("P4_DUPLICATE_CASE_ID", codes(validator.check_p4_cases(path, ["cluster_001"])))

    def test_rule9_missing_and_unknown_cluster(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = self._cases(td, clusters=2)
            self.assertIn("P4_UNKNOWN_CLUSTER", codes(validator.check_p4_cases(path, ["cluster_001"])))
            path.write_text(
                path.read_text(encoding="utf-8").replace("**对应原则簇：** cluster_002\n", "", 1), encoding="utf-8"
            )
            self.assertIn("P4_MISSING_CLUSTER", codes(validator.check_p4_cases(path, ["cluster_001", "cluster_002"])))

    def test_rule9_unknown_not_reported_without_cluster_list(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = self._cases(td)
            self.assertNotIn("P4_UNKNOWN_CLUSTER", codes(validator.check_p4_cases(path, [])))

    def test_rule10_case_id_shape(self) -> None:
        for bad in ("demo_c1_1", "Demo-C1-1", "democ11"):
            with self.subTest(bad=bad):
                with tempfile.TemporaryDirectory() as td:
                    path = self._cases(td, mutate=lambda t, b=bad: t.replace("demo-c1-1", b))
                    self.assertIn("P4_BAD_CASE_ID", codes(validator.check_p4_cases(path, ["cluster_001"])))


# ── 规则 13：模板残留 ────────────────────────────────────────────────


class TemplateResidueTests(unittest.TestCase):
    def test_flags_placeholders_and_repeat_blocks(self) -> None:
        for text in ("# {person_name_zh}的思维框架\n", "{repeat_block: 2-4 values}\n", "> {原文片段}\n"):
            with self.subTest(text=text):
                errors = validator.check_template_residue([TempFile(self, "x.md", text).path])
                self.assertIn("TEMPLATE_RESIDUE", codes(errors))

    def test_clean_text_passes(self) -> None:
        errors = validator.check_template_residue([TempFile(self, "x.md", "月有考，岁有稽。（注）\n").path])
        self.assertEqual(errors, [])


# ── 端到端：新规则接入了 package / published ──────────────────────────


class WiringTests(unittest.TestCase):
    def test_package_stage_runs_new_rules(self) -> None:
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as td:
            fx = fx_mod.PackageFixture(td)
            fx.write_skill(fx_mod.build_skill_md(extra=CASE_INDEX))
            fx.write_ref("voice.md", fx_mod.build_voice_md(5))
            try:
                os.chdir(fx.root)
                errors = validator.validate_package("demo")
            finally:
                os.chdir(cwd)
            self.assertEqual(codes(errors), ["VOICE_TOO_FEW"])


# ── strict S1–S4 ─────────────────────────────────────────────────────


class StrictBuildTests(unittest.TestCase):
    def _validate(self, fx, strict: bool) -> list[str]:
        cwd = os.getcwd()
        try:
            os.chdir(fx.root)
            return validator.validate_package("demo", strict=strict)
        finally:
            os.chdir(cwd)

    def _fixture(self, td: str, review: str | None = "## 裁决\n\n**[PASS]**\n"):
        fx = fx_mod.PackageFixture(td)
        fx.write_skill(fx_mod.build_skill_md(extra=CASE_INDEX))
        if review is not None:
            (fx.out / "review.md").write_text(review, encoding="utf-8")
        register_sources(fx.root)
        return fx

    def test_clean_with_pass_review(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(self._validate(self._fixture(td), strict=True), [])

    def test_s2_missing_or_non_pass_review(self) -> None:
        for review in (None, "## 裁决\n\n**[REVISE: 改]**\n"):
            with self.subTest(review=review):
                with tempfile.TemporaryDirectory() as td:
                    fx = self._fixture(td, review)
                    self.assertIn("STRICT_REVIEW_NOT_PASS", codes(self._validate(fx, strict=True)))
                    self.assertEqual(self._validate(fx, strict=False), [])

    def test_s1_low_confidence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = self._fixture(td)
            fx.write_ref("evidence.md", fx_mod.build_evidence_md().replace("confidence：high", "confidence：low", 1))
            self.assertIn("STRICT_LOW_CONFIDENCE", codes(self._validate(fx, strict=True)))
            self.assertEqual(self._validate(fx, strict=False), [])


class StrictPublishedTests(unittest.TestCase):
    def _published(self, td: str, review: dict | None) -> Path:
        fx = fx_mod.PackageFixture(td)
        fx.write_skill(fx_mod.build_skill_md(extra=CASE_INDEX))
        gallery = fx.root / "gallery" / "demo"
        import shutil
        shutil.copytree(fx.out, gallery, ignore=shutil.ignore_patterns("framework_core.json"))
        register_sources(fx.root)
        p2 = pm.attest_p2(gallery / pm.EVIDENCE_REL, "demo", fx.root, prov)
        manifest = pm.build_manifest(
            gallery, "demo", format_version=6, clusters=["cluster_001"], p2_attestation=p2, review=review
        )
        pm.write_manifest(gallery / pm.MANIFEST_NAME, manifest)
        return gallery

    def test_s3_no_review_record(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            gallery = self._published(td, None)
            self.assertEqual(validator.check_published_package(gallery, "demo", Path(td)), [])
            self.assertIn("STRICT_NO_REVIEW", codes(validator.check_published_package(gallery, "demo", Path(td), strict=True)))

    def test_s2_review_not_pass(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            gallery = self._published(td, {"verdict": "MISSING", "detail": "", "review_sha256": None})
            errors = validator.check_published_package(gallery, "demo", Path(td), strict=True)
            self.assertIn("STRICT_REVIEW_NOT_PASS", codes(errors))

    def test_pass_review_is_clean_under_strict(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            gallery = self._published(td, {"verdict": "PASS", "detail": "", "review_sha256": "x" * 64})
            self.assertEqual(validator.check_published_package(gallery, "demo", Path(td), strict=True), [])


class StrictCliTests(unittest.TestCase):
    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "scripts/validate_output.py", *args], cwd=ROOT, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=120,
        )

    def test_strict_rejected_for_unsupported_stage(self) -> None:
        proc = self._run("principles", "zhang-juzheng-v6", "--strict")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("--strict", proc.stdout)

    def test_pilot_passes_strict(self) -> None:
        # 样板包已补审查（PASS）并按用户权利声明重新发布：manifest 带权利汇总，strict 应零错误。
        proc = self._run("published", "zhang-juzheng-v6", "--strict")
        self.assertEqual(proc.returncode, 0, proc.stdout)


if __name__ == "__main__":
    unittest.main()
