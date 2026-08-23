from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validator = load_module("validate_output", ROOT / "scripts" / "validate_output.py")

CORE_SECTIONS = [
    "身份卡", "响应策略", "核心原则", "决策框架",
    "已知盲区", "表达风格 DNA", "价值取向与反模式", "溯源",
]


def build_skill_md(sections=None, extra="") -> str:
    sections = CORE_SECTIONS if sections is None else sections
    body = "\n\n".join(f"## {name}\n\n内容占位，非空。" for name in sections)
    return (
        "---\n"
        "name: demo-wisdom\n"
        "format_version: 6\n"
        "description: 运用示例人物的框架处理决策问题。触发：示例。\n"
        "---\n\n"
        "# 示例人物的思维框架\n\n"
        f"{body}\n\n{extra}\n"
    )


class PackageFixture:
    """在临时目录里搭一个最小 v6 包，供各闸门测试复用。"""

    def __init__(self, td: str):
        self.root = Path(td)
        self.out = self.root / "output" / "demo"
        self.refs = self.out / "references"
        self.refs.mkdir(parents=True)
        raw = self.root / "sources" / "demo" / "raw"
        raw.mkdir(parents=True)
        (raw / "corpus.txt").write_text("月有考，岁有稽，事可责成。", encoding="utf-8")
        self.write_skill(build_skill_md())
        self.write_ref("evidence.md", "### 原则 1：甲\n\n> 月有考，岁有稽\n\n- confidence：high\n")
        self.write_ref("voice.md", "### 样本 1（维度：句式）\n\n> 示例\n")
        self.write_cases(clusters=1, counter=True)

    def write_skill(self, text: str) -> None:
        (self.out / "SKILL.md").write_text(text, encoding="utf-8")

    def write_ref(self, name: str, text: str) -> None:
        (self.refs / name).write_text(text, encoding="utf-8")

    def write_cases(self, clusters: int, counter: bool) -> None:
        blocks = []
        for c in range(1, clusters + 1):
            for n in range(1, 3):
                blocks.append(
                    f"### 案例 {c}-{n}：示例（case_id: demo-c{c}-{n}，high）\n\n"
                    f"**对应原则簇：** cluster_{c:03d}\n\n**情境：** 略。\n"
                )
        if counter:
            blocks.append(
                "### 案例 X：反例（case_id: demo-counter-1，high）\n\n"
                "**对应原则簇：** cluster_001\n\n**反例：** 此处判断失误。\n"
            )
        self.write_ref("cases.md", "\n\n".join(blocks))


class P3PathResolutionTests(unittest.TestCase):
    def test_passes_when_all_backtick_paths_resolve(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = PackageFixture(td)
            fx.write_skill(build_skill_md(extra="详见 `references/cases.md`。"))
            errors = validator.check_p3_paths(fx.out / "SKILL.md")
            self.assertEqual(errors, [])

    def test_fails_on_dangling_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = PackageFixture(td)
            fx.write_skill(build_skill_md(extra="详见 `references/nope.md`。"))
            errors = validator.check_p3_paths(fx.out / "SKILL.md")
            self.assertEqual(len(errors), 1)
            self.assertTrue(errors[0].startswith("P3_DANGLING_PATH"))

    def test_p3_fails_on_path_that_only_resolves_from_repo_root(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = PackageFixture(td)
            fx.write_skill(build_skill_md(extra="详见 `config/defaults.json`。"))
            errors = validator.check_p3_paths(fx.out / "SKILL.md")
            self.assertTrue(any(e.startswith("P3_DANGLING_PATH") for e in errors))


class P4CaseCoverageTests(unittest.TestCase):
    def test_passes_with_two_cases_per_cluster_and_a_counter_case(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = PackageFixture(td)
            errors = validator.check_p4_cases(fx.refs / "cases.md", ["cluster_001"])
            self.assertEqual(errors, [])

    def test_fails_when_cluster_has_one_case(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = PackageFixture(td)
            # cluster_001 有 2 例（达标），cluster_002 只有 1 例（不达标）
            fx.write_ref(
                "cases.md",
                "### 案例 1：甲（case_id: demo-a-1，high）\n\n"
                "**对应原则簇：** cluster_001\n\n**情境：** 略。\n\n"
                "### 案例 2：乙（case_id: demo-b-1，high）\n\n"
                "**对应原则簇：** cluster_001\n\n**情境：** 略。\n\n"
                "### 案例 X：反例（case_id: demo-counter-1，high）\n\n"
                "**对应原则簇：** cluster_002\n\n**反例：** 略。\n",
            )
            errors = validator.check_p4_cases(
                fx.refs / "cases.md", ["cluster_001", "cluster_002"]
            )
            self.assertTrue(any(e.startswith("P4_TOO_FEW_CASES") for e in errors))
            self.assertTrue(any("cluster_002" in e for e in errors))
            self.assertFalse(any("cluster_001" in e for e in errors))

    def test_fails_when_no_counter_case(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = PackageFixture(td)
            fx.write_cases(clusters=1, counter=False)
            errors = validator.check_p4_cases(fx.refs / "cases.md", ["cluster_001"])
            self.assertTrue(any(e.startswith("P4_NO_COUNTER_CASE") for e in errors))

    def test_p4_ignores_prose_mention_of_counter_example(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = PackageFixture(td)
            fx.write_ref(
                "cases.md",
                "### 案例 1：甲（case_id: demo-a-1，high）\n\n"
                "**对应原则簇：** cluster_001\n\n"
                "**情境：** 对方提出了一个反例，但我坚持原判。\n\n"
                "### 案例 2：乙（case_id: demo-b-1，high）\n\n"
                "**对应原则簇：** cluster_001\n\n**情境：** 略。\n",
            )
            errors = validator.check_p4_cases(fx.refs / "cases.md", ["cluster_001"])
            self.assertTrue(any(e.startswith("P4_NO_COUNTER_CASE") for e in errors))


class P5IndexConsistencyTests(unittest.TestCase):
    def test_passes_when_index_matches_case_ids(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = PackageFixture(td)
            index = (
                "## 案例索引\n\n"
                "| 案例 | 触发情境 | case_id |\n|---|---|---|\n"
                "| 示例 | 情境甲 | demo-c1-1 |\n"
                "| 示例 | 情境乙 | demo-c1-2 |\n"
                "| 反例 | 情境丙 | demo-counter-1 |\n"
            )
            fx.write_skill(build_skill_md(extra=index))
            errors = validator.check_p5_index(fx.out / "SKILL.md", fx.refs / "cases.md")
            self.assertEqual(errors, [])

    def test_fails_when_index_references_unknown_case_id(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = PackageFixture(td)
            index = (
                "## 案例索引\n\n"
                "| 案例 | 触发情境 | case_id |\n|---|---|---|\n"
                "| 幽灵 | 情境甲 | demo-ghost-9 |\n"
            )
            fx.write_skill(build_skill_md(extra=index))
            errors = validator.check_p5_index(fx.out / "SKILL.md", fx.refs / "cases.md")
            self.assertTrue(any(e.startswith("P5_INDEX_ORPHAN") for e in errors))

    def test_fails_when_case_is_not_indexed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = PackageFixture(td)
            index = (
                "## 案例索引\n\n"
                "| 案例 | 触发情境 | case_id |\n|---|---|---|\n"
                "| 示例 | 情境甲 | demo-c1-1 |\n"
            )
            fx.write_skill(build_skill_md(extra=index))
            errors = validator.check_p5_index(fx.out / "SKILL.md", fx.refs / "cases.md")
            self.assertTrue(any(e.startswith("P5_CASE_NOT_INDEXED") for e in errors))

    def test_p5_ignores_case_id_mentioned_outside_index_section(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = PackageFixture(td)
            fx.write_cases(clusters=1, counter=False)
            extra = (
                "## 案例索引\n\n"
                "| 案例 | 触发情境 | case_id |\n|---|---|---|\n"
                "| 示例 | 情境甲 | demo-c1-1 |\n\n"
                "## 附录\n\n"
                "另可参见 case_id: demo-c1-2 的教训。\n"
            )
            fx.write_skill(build_skill_md(extra=extra))
            errors = validator.check_p5_index(fx.out / "SKILL.md", fx.refs / "cases.md")
            self.assertTrue(
                any(e.startswith("P5_CASE_NOT_INDEXED") and "demo-c1-2" in e for e in errors)
            )


class P6CoreSelfSufficiencyTests(unittest.TestCase):
    def test_passes_with_all_eight_sections_under_line_cap(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = PackageFixture(td)
            errors = validator.check_p6_core(fx.out / "SKILL.md")
            self.assertEqual(errors, [])

    def test_fails_when_a_core_section_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = PackageFixture(td)
            fx.write_skill(build_skill_md(sections=CORE_SECTIONS[:-1]))
            errors = validator.check_p6_core(fx.out / "SKILL.md")
            self.assertTrue(any(e.startswith("P6_MISSING_SECTION") for e in errors))

    def test_fails_when_a_core_section_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = PackageFixture(td)
            body = "\n\n".join(
                f"## {name}\n" + ("" if name == "溯源" else "\n内容占位，非空。")
                for name in CORE_SECTIONS
            )
            fx.write_skill(
                "---\nname: demo-wisdom\nformat_version: 6\n"
                "description: 示例。触发：示例。\n---\n\n# 标题\n\n" + body + "\n"
            )
            errors = validator.check_p6_core(fx.out / "SKILL.md")
            self.assertTrue(any(e.startswith("P6_EMPTY_SECTION") for e in errors))

    def test_fails_over_line_cap(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = PackageFixture(td)
            fx.write_skill(build_skill_md(extra="填充行\n" * 600))
            errors = validator.check_p6_core(fx.out / "SKILL.md")
            self.assertTrue(any(e.startswith("P6_TOO_LONG") for e in errors))

    def test_p6_fails_when_section_exists_only_as_nested_subheading(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = PackageFixture(td)
            sections = [s for s in CORE_SECTIONS if s != "决策框架"]
            extra = (
                "## 案例索引\n\n"
                "#### 决策框架应用示例\n\n"
                "此处内容非空，用于验证嵌套子标题不应被误判为核心章节。\n"
            )
            fx.write_skill(build_skill_md(sections=sections, extra=extra))
            errors = validator.check_p6_core(fx.out / "SKILL.md")
            self.assertTrue(
                any(e.startswith("P6_MISSING_SECTION") and "决策框架" in e for e in errors)
            )


class PackageStageTests(unittest.TestCase):
    def test_package_stage_is_registered(self) -> None:
        self.assertIn("package", validator.STAGES)

    def test_validate_package_reports_missing_reference_file(self) -> None:
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as td:
            try:
                fx = PackageFixture(td)
                (fx.refs / "voice.md").unlink()
                os.chdir(fx.root)
                errors = validator.validate_package("demo")
            finally:
                os.chdir(cwd)
            self.assertTrue(any("voice.md" in e for e in errors))


class FormatDetectionTests(unittest.TestCase):
    LEGACY = (
        "---\nname: demo-wisdom\n"
        "description: Apply demo frameworks. 运用示例框架。\n---\n\n"
        "# Language Detection · 语言检测\n\n"
        "## English\n\n### Identity Card\n略\n\n"
        "## 中文版\n\n### 身份卡\n略\n"
    )

    def test_detects_v6_by_format_version(self) -> None:
        self.assertTrue(validator.is_v6_skill(build_skill_md()))

    def test_detects_legacy_when_format_version_absent(self) -> None:
        self.assertFalse(validator.is_v6_skill(self.LEGACY))

    def test_v6_skill_stage_does_not_demand_english_block(self) -> None:
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as td:
            try:
                fx = PackageFixture(td)
                os.chdir(fx.root)
                errors = validator.validate_skill("demo")
            finally:
                os.chdir(cwd)
            self.assertFalse(any("## English" in e for e in errors))
            self.assertFalse(any("MISSING_LANG_DETECTION" in e for e in errors))

    def test_legacy_skill_stage_still_demands_english_block(self) -> None:
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as td:
            try:
                out = Path(td) / "output" / "demo"
                out.mkdir(parents=True)
                (out / "SKILL.md").write_text(
                    self.LEGACY.replace("## English\n\n### Identity Card\n略\n\n", ""),
                    encoding="utf-8",
                )
                os.chdir(td)
                errors = validator.validate_skill("demo")
            finally:
                os.chdir(cwd)
            self.assertTrue(any("'## English'" in e for e in errors))


class FrameworksLanguageTests(unittest.TestCase):
    def _write_core(self, out: Path) -> None:
        (out / "framework_core.json").write_text(
            json.dumps({"person_slug": "demo", "principle_clusters": [{"cluster_id": "cluster_001"}]}),
            encoding="utf-8",
        )

    def test_missing_en_framework_is_not_an_error_when_zh_only(self) -> None:
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as td:
            try:
                out = Path(td) / "output" / "demo"
                out.mkdir(parents=True)
                self._write_core(out)
                (out / "frameworks.zh.json").write_text("{}", encoding="utf-8")
                os.chdir(td)
                errors = validator.validate_frameworks("demo")
            finally:
                os.chdir(cwd)
            self.assertFalse(
                any(e.startswith("MISSING:") and "frameworks.en.json" in e for e in errors)
            )

    def test_missing_en_framework_is_an_error_when_en_requested(self) -> None:
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as td:
            try:
                out = Path(td) / "output" / "demo"
                out.mkdir(parents=True)
                self._write_core(out)
                (out / "frameworks.zh.json").write_text("{}", encoding="utf-8")
                (out / "en_requested.flag").write_text("yes", encoding="utf-8")
                os.chdir(td)
                errors = validator.validate_frameworks("demo")
            finally:
                os.chdir(cwd)
            self.assertTrue(
                any(e.startswith("MISSING:") and "frameworks.en.json" in e for e in errors)
            )


if __name__ == "__main__":
    unittest.main()
