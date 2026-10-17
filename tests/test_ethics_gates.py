"""伦理与法律闸门：引文长度（L1）、在世人物声明（L2）、证据来源权利（strict S4）与人工权利声明。

依据见 docs/ethics-and-legal.md。每条规则都从合规夹具出发只改一处，并断言真实样板包不被误伤。
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "gallery" / "zhang-juzheng-v6"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fx_mod = load_module("_package_v6_fixtures_ethics", ROOT / "tests" / "test_package_v6.py")
validator = fx_mod.validator
pm = load_module("_pm_ethics", ROOT / "scripts" / "package_manifest.py")
prov = load_module("_prov_ethics", ROOT / "scripts" / "verify_provenance.py")
registry_mod = load_module("_registry_ethics", ROOT / "scripts" / "source_registry.py")

CASE_INDEX = "## 案例索引\n\n| demo-c1-1 | demo-c1-2 | demo-counter-1 |\n"
LIMITS = validator.PACKAGE_SCHEMA["quote_max_chars"]


def codes(errors: list[str]) -> list[str]:
    return [e.split(":", 1)[0] for e in errors]


def long_text(n: int) -> str:
    return ("考成之法月有稽" * (n // 7 + 1))[:n]


class QuoteLengthTests(unittest.TestCase):
    def _check(self, fx) -> list[str]:
        refs = fx.refs
        return validator.check_quote_lengths(fx.out / "SKILL.md", refs / "evidence.md", refs / "voice.md")

    def test_compliant_fixture_and_pilot_are_clean(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(self._check(fx_mod.PackageFixture(td)), [])
        refs = PILOT / "references"
        self.assertEqual(validator.check_quote_lengths(PILOT / "SKILL.md", refs / "evidence.md", refs / "voice.md"), [])

    def test_core_quote_over_limit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = fx_mod.PackageFixture(td)
            quote = long_text(LIMITS["core"] + 1)
            fx.write_skill(fx_mod.build_skill_md(extra=f"**原文出处：**「{quote}」"))
            self.assertIn("QUOTE_TOO_LONG_CORE", codes(self._check(fx)))

    def test_core_quote_at_limit_passes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = fx_mod.PackageFixture(td)
            fx.write_skill(fx_mod.build_skill_md(extra=f"**原文出处：**「{long_text(LIMITS['core'])}」"))
            self.assertEqual(self._check(fx), [])

    def test_whitespace_does_not_count(self) -> None:
        self.assertEqual(validator._non_space_len("月 有\n考\t岁"), 4)

    def test_evidence_card_over_limit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = fx_mod.PackageFixture(td)
            cards = [fx_mod.evidence_card(1, quote=long_text(LIMITS["evidence"] + 1))]
            cards += [fx_mod.evidence_card(i) for i in range(2, 9)]
            fx.write_ref("evidence.md", "\n".join(cards))
            self.assertEqual(codes(self._check(fx)), ["QUOTE_TOO_LONG_EVIDENCE"])

    def test_evidence_total_over_limit(self) -> None:
        # 每张卡都在单卡上限内，但摘录总量达到「复制」量级。
        with tempfile.TemporaryDirectory() as td:
            fx = fx_mod.PackageFixture(td)
            per_card = LIMITS["evidence"]
            n = validator.PACKAGE_SCHEMA["evidence_total_max_chars"] // per_card + 1
            fx.write_ref("evidence.md", "\n".join(
                fx_mod.evidence_card(i, quote=long_text(per_card)) for i in range(1, n + 1)
            ))
            self.assertEqual(codes(self._check(fx)), ["EVIDENCE_TOTAL_TOO_LONG"])

    def test_voice_sample_over_limit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = fx_mod.PackageFixture(td)
            voice = fx_mod.build_voice_md().replace("> 月有考，岁有稽。", "> " + long_text(LIMITS["voice"] + 1), 1)
            fx.write_ref("voice.md", voice)
            self.assertEqual(codes(self._check(fx)), ["QUOTE_TOO_LONG_VOICE"])


def skill_with_identity(identity: str, notice: str | None = None) -> str:
    text = fx_mod.build_skill_md(extra=CASE_INDEX)
    head = identity + (f"\n{notice}" if notice else "")
    return text.replace("# 示例人物的思维框架\n", f"# 示例人物的思维框架\n{head}\n", 1)


GOOD_NOTICE = "**在世人物声明：**本框架依据示例人物公开发表的著述做研究性重建，不代表本人观点，不得冒充本人发言。"


class LivingPersonTests(unittest.TestCase):
    def _check(self, text: str) -> list[str]:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "SKILL.md"
            path.write_text(text, encoding="utf-8")
            return validator.check_living_person_notice(path)

    def test_detects_living_markers(self) -> None:
        for line in ("**某人** · 1950–", "**某人** · 1950—至今", "**某人** · 1950-present", "**某人** · 约1950年–今"):
            with self.subTest(line=line):
                self.assertTrue(validator.is_living_person(line + "\n"))

    def test_deceased_and_bce_are_not_living(self) -> None:
        for line in ("**张居正（字叔大）** · 1525–1582", "**孙武** · 约前544–前496", "**某人** · 1950–2020"):
            with self.subTest(line=line):
                self.assertFalse(validator.is_living_person(line + "\n"))
        self.assertFalse(validator.is_living_person("# 没有生卒年行\n"))

    def test_living_without_notice(self) -> None:
        self.assertEqual(codes(self._check(skill_with_identity("**某人** · 1950–"))), ["LIVING_PERSON_NOTICE_MISSING"])

    def test_living_with_incomplete_notice(self) -> None:
        text = skill_with_identity("**某人** · 1950–至今", "**在世人物声明：**这是一个思维框架。")
        self.assertEqual(codes(self._check(text)), ["LIVING_PERSON_NOTICE_INCOMPLETE"])

    def test_living_with_notice_passes(self) -> None:
        self.assertEqual(self._check(skill_with_identity("**某人** · 1950–", GOOD_NOTICE)), [])

    def test_template_comment_does_not_count_as_notice(self) -> None:
        # 模板注释里的示范行是缩进的，不能被当成已经写了声明。
        comment = "<!--\n  **在世人物声明：**本框架依据公开著述，不代表本人。\n-->"
        self.assertEqual(
            codes(self._check(skill_with_identity("**某人** · 1950–", comment))), ["LIVING_PERSON_NOTICE_MISSING"]
        )

    def test_deceased_pilot_needs_no_notice(self) -> None:
        self.assertEqual(validator.check_living_person_notice(PILOT / "SKILL.md"), [])

    def test_template_ships_the_notice_slot(self) -> None:
        template = (ROOT / "templates" / "skill-template.v6.zh.md").read_text(encoding="utf-8")
        self.assertIn(validator.PACKAGE_SCHEMA["living_notice_label"], template)


class RightsDeclarationTests(unittest.TestCase):
    def _raw(self, td: str) -> Path:
        raw = Path(td) / "sources" / "demo" / "raw"
        (raw / "bio").mkdir(parents=True)
        (raw / "bio" / "a.txt").write_text("甲", encoding="utf-8")
        (raw / "b.txt").write_text("乙", encoding="utf-8")
        return raw

    def _declare(self, td: str, declarations: list) -> Path:
        path = Path(td) / "sources" / "demo" / "rights.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"schema": "rights-declaration-v1", "declarations": declarations},
                                   ensure_ascii=False), encoding="utf-8")
        return path

    def test_declaration_applies_first_match_and_clears_review(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            raw = self._raw(td)
            decls, errors = registry_mod.load_rights_declarations(self._declare(td, [
                {"path": "bio/*", "rights_status": "user_owned_copy", "basis": "自购纸书"},
                {"path": "*", "rights_status": "public_domain", "basis": "卒于 1582 年"},
            ]))
            self.assertEqual(errors, [])
            by_path = registry_mod.registry_by_relative_path(registry_mod.build_registry(raw, declarations=decls))
            self.assertEqual(by_path["bio/a.txt"]["rights_status"], "user_owned_copy")
            self.assertEqual(by_path["bio/a.txt"]["rights_basis"], "自购纸书")
            self.assertEqual(by_path["b.txt"]["rights_status"], "public_domain")
            self.assertIs(by_path["b.txt"]["rights_review_required"], False)

    def test_invalid_declarations_are_reported_and_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            decls, errors = registry_mod.load_rights_declarations(self._declare(td, [
                {"path": "a.txt", "rights_status": "mine", "basis": "x"},
                {"path": "a.txt", "rights_status": "public_domain", "basis": "  "},
                {"rights_status": "public_domain", "basis": "x"},
            ]))
            self.assertEqual(decls, [])
            self.assertEqual(len(errors), 3)

    def test_missing_file_and_bad_schema(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(registry_mod.load_rights_declarations(Path(td) / "none.json"), ([], []))
            bad = Path(td) / "rights.json"
            bad.write_text('{"declarations": []}', encoding="utf-8")
            decls, errors = registry_mod.load_rights_declarations(bad)
            self.assertEqual((decls, codes(errors)), ([], ["RIGHTS_DECLARATION_BAD_SCHEMA"]))

    def test_without_declaration_local_files_stay_unverified(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            records = registry_mod.build_registry(self._raw(td))["sources"]
            self.assertEqual({r["rights_status"] for r in records}, {"unverified"})


class StrictRightsTests(unittest.TestCase):
    """strict S4：证据卡所在的每个语料文件都必须登记、权利放行；默认（非 strict）不拦。"""

    def _fixture(self, td: str, rights: str | None, review_required: bool = False):
        fx = fx_mod.PackageFixture(td)
        fx.write_skill(fx_mod.build_skill_md(extra=CASE_INDEX))
        (fx.out / "review.md").write_text("## 裁决\n\n**[PASS]**\n", encoding="utf-8")
        if rights is not None:
            registry = registry_mod.build_registry(fx.root / "sources" / "demo" / "raw", rights_status=rights)
            for record in registry["sources"]:
                record["rights_review_required"] = review_required
            registry_mod.write_registry(fx.root / "sources" / "demo" / "processed" / "source_registry.json", registry)
        return fx

    def _validate(self, fx, strict: bool = True) -> list[str]:
        cwd = os.getcwd()
        try:
            os.chdir(fx.root)
            return validator.validate_package("demo", strict=strict)
        finally:
            os.chdir(cwd)

    def test_allowed_rights_pass(self) -> None:
        for rights in ("public_domain", "user_owned_copy", "cc-by-sa"):
            with self.subTest(rights=rights), tempfile.TemporaryDirectory() as td:
                self.assertEqual(self._validate(self._fixture(td, rights)), [])

    def test_no_registry(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = self._fixture(td, None)
            self.assertEqual(codes(self._validate(fx)), ["STRICT_NO_RIGHTS_RECORD"])
            self.assertEqual(self._validate(fx, strict=False), [])

    def test_unverified_and_review_statuses_fail(self) -> None:
        # public_domain_us 只在 policy.jurisdiction == "US" 时放行；仓库默认 jurisdiction 为 null。
        for rights in ("unverified", "unknown", "public_domain_us", "restricted"):
            with self.subTest(rights=rights), tempfile.TemporaryDirectory() as td:
                self.assertEqual(codes(self._validate(self._fixture(td, rights))), ["STRICT_RIGHTS_UNVERIFIED"])

    def test_pending_review_flag_fails_even_with_allowed_status(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = self._fixture(td, "public_domain", review_required=True)
            self.assertEqual(codes(self._validate(fx)), ["STRICT_RIGHTS_UNVERIFIED"])

    def test_attestation_carries_rights_and_published_strict_reads_it(self) -> None:
        for rights, expected in (("public_domain", []), ("unverified", ["STRICT_RIGHTS_UNVERIFIED"])):
            with self.subTest(rights=rights), tempfile.TemporaryDirectory() as td:
                fx = self._fixture(td, rights)
                gallery = fx.root / "gallery" / "demo"
                shutil.copytree(fx.out, gallery, ignore=shutil.ignore_patterns("framework_core.json", "review.md"))
                p2 = pm.attest_p2(gallery / pm.EVIDENCE_REL, "demo", fx.root, prov)
                self.assertEqual(p2["rights"]["sources"]["corpus.txt"]["rights_status"], rights)
                self.assertEqual(p2["rights"]["sources"]["corpus.txt"]["evidence_cards"], 8)
                self.assertEqual(p2["rights"]["unlocated_cards"], 0)
                manifest = pm.build_manifest(
                    gallery, "demo", format_version=6, clusters=["cluster_001"], p2_attestation=p2,
                    review={"verdict": "PASS", "detail": "", "review_sha256": "x" * 64},
                )
                pm.write_manifest(gallery / pm.MANIFEST_NAME, manifest)
                self.assertEqual(codes(validator.check_published_package(gallery, "demo", fx.root, strict=True)), expected)
                self.assertEqual(validator.check_published_package(gallery, "demo", fx.root), [])

    def test_attestation_without_registry_has_no_rights(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = self._fixture(td, None)
            p2 = pm.attest_p2(fx.refs / "evidence.md", "demo", fx.root, prov)
            self.assertIsNone(p2["rights"])
            self.assertEqual(p2["status"], "pass")


if __name__ == "__main__":
    unittest.main()
