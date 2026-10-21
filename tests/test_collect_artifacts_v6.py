"""评测收集器认 v6 包（HANDOFF P2）。

v6 = 中文单语包（SKILL.md 带 `format_version: 6`，框架 8–11 条原则），英文是按需另出的 `{slug}-en` 技能。
原来的 collect_artifacts 仍按旧的双语单文件打分：原则数 5–8 之外就扣、没有 `## English` 就扣、描述不双语就扣，
v6 包在「跨语言」一项被系统性压分；包闸门 P1–P6 也没进评分。现在：
- 原则数区间跟框架的 format_version 走（v6 8–11，legacy 5–8）；
- 中文单语、没要英文分支的 v6 包不因缺英文扣分；要了英文分支，就查 frameworks.en.json 和 output/{slug}-en/SKILL.md；
- v6 包跑包闸门（经 validate_output 的 skill 阶段转入，不写闸门记录——评测只读），不过就是关键闸门；
- 校验器用仓库里的那份，在数据根下跑，数据根不在仓库里也能评。
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from sibling import load_module  # noqa: E402  按路径加载模块的唯一入口（先登记 sys.modules）


collector = load_module(ROOT / "evaluation" / "scripts" / "collect_artifacts.py", "collect_artifacts_v6")

V6_SKILL = """---
name: demo-wisdom
description: 用守城者的眼光判断取舍；遇到攻防、资源分配时触发。
format_version: 6
---
# 守城者

## 身份卡
我一辈子在守城，文化背景是战国。

## 决策框架
## 已知盲区
缓解办法写在这里。
## 溯源
"""

LEGACY_SKILL = """---
name: demo-wisdom
description: Demo skill. 演示技能。
---
## English
Cultural context here.
## 中文版
"""


def framework(lang: str, principles: int, *, v6: bool) -> dict:
    data = {"lang": lang, "core_principles": [{"id": i} for i in range(principles)]}
    if v6:
        data["format_version"] = 6
    return data


def make_root(td: str, skill: str, *, zh: int | None = 9, en: int | None = None, v6: bool = True,
              en_flag: bool = False, en_skill: bool = False) -> Path:
    root = Path(td)
    out = root / "output" / "demo"
    out.mkdir(parents=True)
    (out / "SKILL.md").write_text(skill, encoding="utf-8")
    (out / "review.md").write_text("[PASS]", encoding="utf-8")
    if zh is not None:
        (out / "frameworks.zh.json").write_text(json.dumps(framework("zh", zh, v6=v6)), encoding="utf-8")
    if en is not None:
        (out / "frameworks.en.json").write_text(json.dumps(framework("en", en, v6=v6)), encoding="utf-8")
    if en_flag:
        (out / "en_requested.flag").write_text("requested", encoding="utf-8")
    if en_skill:
        (root / "output" / "demo-en").mkdir(parents=True)
        (root / "output" / "demo-en" / "SKILL.md").write_text("# Demo EN", encoding="utf-8")
    return root


class FakeValidation:
    def __init__(self, passed: bool = True):
        self.passed = passed
        self.stages: list[str] = []

    def __call__(self, root, stage, slug):
        self.stages.append(stage)
        return {"stage": stage, "skipped": False, "exit_code": 0 if self.passed else 1, "passed": self.passed,
                "stdout": "", "stderr": ""}


def score(root: Path, validation: FakeValidation | None = None):
    with mock.patch.object(collector, "run_validation", validation or FakeValidation()):
        facts = collector.collect_facts(root, "demo")
    card = collector.score_facts(facts)
    return facts, card, {m["metric"]: m for m in card["metrics"]}


class PrincipleRangeTests(unittest.TestCase):
    def test_v6_frameworks_use_eight_to_eleven(self):
        with tempfile.TemporaryDirectory() as td:
            _, _, metrics = score(make_root(td, V6_SKILL, zh=9))
        depth = metrics["Cognitive Distillation Depth"]
        self.assertTrue(any("in range" in e for e in depth["evidence"]), depth)
        with tempfile.TemporaryDirectory() as td:
            _, _, metrics = score(make_root(td, V6_SKILL, zh=7))
        self.assertTrue(any("8-11" in d for d in metrics["Cognitive Distillation Depth"]["deductions"]))

    def test_legacy_frameworks_keep_five_to_eight(self):
        with tempfile.TemporaryDirectory() as td:
            _, _, metrics = score(make_root(td, LEGACY_SKILL, zh=9, en=9, v6=False))
        self.assertTrue(any("5-8" in d for d in metrics["Cognitive Distillation Depth"]["deductions"]))


class CrossLingualTests(unittest.TestCase):
    def test_chinese_only_v6_package_is_not_penalised_for_missing_english(self):
        with tempfile.TemporaryDirectory() as td:
            facts, _, metrics = score(make_root(td, V6_SKILL))
        fit = metrics["Cross-Lingual & Cultural Fit"]
        self.assertTrue(facts["checks"]["is_v6_package"])
        self.assertEqual(fit["score"], fit["max_score"], fit)
        self.assertFalse([d for d in fit["deductions"] if "English" in d or "bilingual" in d], fit["deductions"])

    def test_requested_english_branch_must_exist(self):
        with tempfile.TemporaryDirectory() as td:
            _, _, metrics = score(make_root(td, V6_SKILL, en_flag=True))
        fit = metrics["Cross-Lingual & Cultural Fit"]
        self.assertLess(fit["score"], fit["max_score"])
        self.assertTrue(any("English branch" in d for d in fit["deductions"]), fit["deductions"])
        with tempfile.TemporaryDirectory() as td:
            _, _, metrics = score(make_root(td, V6_SKILL, en=9, en_flag=True, en_skill=True))
        fit = metrics["Cross-Lingual & Cultural Fit"]
        self.assertEqual(fit["score"], fit["max_score"], fit)

    def test_legacy_bilingual_scoring_is_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            _, _, metrics = score(make_root(td, "---\nname: x\ndescription: 中文\n---\n## 中文版\n", zh=6, v6=False))
        self.assertTrue(any("English section missing" in d for d in metrics["Cross-Lingual & Cultural Fit"]["deductions"]))


class PackageGateTests(unittest.TestCase):
    def test_v6_runs_the_package_gate_without_the_recording_command(self):
        validation = FakeValidation()
        with tempfile.TemporaryDirectory() as td:
            facts, _, _ = score(make_root(td, V6_SKILL), validation)
        self.assertIn("package", facts["validation"])
        self.assertNotIn("package", validation.stages, "`validate_output package` 会往 output/ 写闸门记录，评测只读")
        self.assertIn("skill", validation.stages)

    def test_a_failed_package_gate_is_a_critical_gate(self):
        with tempfile.TemporaryDirectory() as td:
            _, card, _ = score(make_root(td, V6_SKILL), FakeValidation(passed=False))
        self.assertIn("package_gate_failed", card["critical_gates"])
        self.assertLessEqual(card["total_score"], 69)

    def test_legacy_skill_has_no_package_gate(self):
        with tempfile.TemporaryDirectory() as td:
            facts, card, _ = score(make_root(td, LEGACY_SKILL, zh=6, en=6, v6=False), FakeValidation(passed=False))
        self.assertNotIn("package", facts["validation"])
        self.assertNotIn("package_gate_failed", card["critical_gates"])


class RunValidationTests(unittest.TestCase):
    def test_repo_validator_runs_in_a_data_root_outside_the_repo_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            root = make_root(td, V6_SKILL)
            before = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))
            result = collector.run_validation(root, "skill", "demo")
            after = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))
        self.assertFalse(result["skipped"], "数据根里没有 scripts/ 也要用仓库的校验器")
        self.assertFalse(result["passed"], result["stdout"])
        self.assertIn("MISSING", result["stdout"])
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
