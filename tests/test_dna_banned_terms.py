"""表达 DNA 声称「不用某词」，语料里却大量出现——这种自相矛盾要由闸门拦下，不能靠审查员碰巧发现。

2026-10-20 鲁迅：SKILL.md「句式偏好 / 禁忌表达」与 voice.md 样本 1 的注释都写他「不用应当/必须」，
但《熱風》OCR 里「應該」16 处、「應當」2 处、「必須」4 处。GUI 验收（发现 14）与隔离审查各独立抓到一次，
两次都只靠 LLM 审查员。这里的检查是确定性的：抽出被禁的词，用 verify_provenance 的 normalize
（含繁简折叠）去语料里数，≥3 次报 WARNING。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
# 夹具一律用简体：繁简折叠依赖可选依赖 opencc，CI 不装它（见 pyproject 的 provenance extra），
# 折叠只在专门的、带 skipIf 的用例里测。

import validate_output as v  # noqa: E402

DNA_HEAD = "## 表达风格 DNA\n\n| 维度 | 特征 |\n|---|---|\n"


def skill_with_dna(rows: dict[str, str], tail: str = "") -> str:
    body = "".join(f"| {dim} | {text} |\n" for dim, text in rows.items())
    return f"---\nname: demo-wisdom\nformat_version: 6\n---\n\n{DNA_HEAD}{body}\n{tail}\n---\n\n## 价值取向与反模式\n"


class ExtractBannedTerms(unittest.TestCase):
    def terms(self, rows: dict[str, str], tail: str = "") -> dict[str, list[str]]:
        found: dict[str, list[str]] = {}
        for dim, term in v.banned_terms_from_dna(skill_with_dna(rows, tail)):
            found.setdefault(term, []).append(dim)
        return found

    def test_lu_xun_wording_yields_both_terms_from_both_dimensions(self):
        found = self.terms({
            "句式偏好": "语气平实，不用“应当”“必须”之类说教词；以「有點」轻描淡写。",
            "禁忌表达": "不把讽刺画成人身攻击的器具；不用“应当”“必须”之类说教词把判断说成训示。",
        })
        self.assertEqual(set(found), {"应当", "必须"})
        self.assertEqual(set(found["应当"]), {"句式偏好", "禁忌表达"})

    def test_explicit_never_say_sentences_in_any_row(self):
        found = self.terms({
            "语气基调": "从不说「毋庸置疑」，也绝不用『显而易见』；避免使用“众所周知”。",
            "口语化标记": "忌用「顺便一提」。",
        })
        self.assertEqual(set(found), {"毋庸置疑", "显而易见", "众所周知", "顺便一提"})

    def test_quoted_words_that_are_not_banned_are_ignored(self):
        found = self.terms({
            "口语化标记": "「我以爲」「我想」「據我的經驗」是高频起句。",
            "禁忌表达": "不先给廉价的安慰，不拿空洞的口号打发结构性困境。",
        })
        self.assertEqual(found, {})

    def test_calibration_examples_below_the_table_are_not_scanned(self):
        found = self.terms({"句式偏好": "平实。"},
                           tail="**语感校准：**\n- ❌ 偏离：「我们应当首先正视问题，必须行动」")
        self.assertEqual(found, {})

    def test_single_character_terms_are_too_noisy_to_check(self):
        found = self.terms({"禁忌表达": "不用「的」，不用「应当」。"})
        self.assertEqual(set(found), {"应当"})

    def test_no_dna_section_means_no_terms(self):
        self.assertEqual(v.banned_terms_from_dna("---\nname: x\n---\n\n## 身份卡\n不用「应当」\n"), [])


class CorpusInDataRoot(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self.out = self.root / "output" / "demo"
        (self.out / "references").mkdir(parents=True)
        self.raw = self.root / "sources" / "demo" / "raw"
        self.raw.mkdir(parents=True)

    def tearDown(self):
        self._td.cleanup()

    def write_skill(self, rows: dict[str, str]):
        (self.out / "SKILL.md").write_text(skill_with_dna(rows), encoding="utf-8", newline="\n")

    def write_corpus(self, name: str, text: str):
        (self.raw / name).write_text(text, encoding="utf-8", newline="\n")

    def warnings(self) -> list[str]:
        return v.check_dna_banned_terms(self.out / "SKILL.md", "demo", self.root)


class BannedTermAgainstCorpus(CorpusInDataRoot):
    ROWS = {"禁忌表达": "不用“应当”“必须”之类说教词。"}

    def test_simplified_corpus_hits_are_counted(self):
        self.write_corpus("热风.txt", "我们应当努力" + "凡事应当三思" + "此事应当如此" + "其余无关")
        self.write_skill(self.ROWS)
        out = self.warnings()
        self.assertEqual(len(out), 1, out)
        self.assertTrue(out[0].startswith("WARNING:"), "先做提醒，不挡路")
        self.assertIn("PKG_DNA_BANNED_TERM", out[0])
        self.assertIn("应当", out[0])
        self.assertIn("3", out[0])
        self.assertIn("热风.txt", out[0], "说出在哪份语料里数到的，方便核对")
        self.assertIn("描述", out[0], "给出处置方向：改成描述语气")

    @unittest.skipIf(v._load_provenance()._FOLDER is None, "繁简折叠需要可选依赖 opencc（pyproject 的 provenance extra）")
    def test_traditional_corpus_folds_to_the_simplified_term(self):
        # 語料是繁体、OCR 无标点；DNA 写简体。
        self.write_corpus("熱風.txt", "我們應當努力凡事應當三思此事應當如此其餘無關")
        self.write_skill(self.ROWS)
        out = self.warnings()
        self.assertEqual(len(out), 1, out)
        self.assertIn("应当 3", out[0])

    def test_counts_add_up_across_corpus_files(self):
        self.write_corpus("a.txt", "你必须去，他必须来。")
        self.write_corpus("b.txt", "必须如此。")
        self.write_skill(self.ROWS)
        out = self.warnings()
        self.assertEqual(len(out), 1, out)
        self.assertIn("必须", out[0])
        self.assertIn("3", out[0])

    def test_below_threshold_is_silent(self):
        self.write_corpus("a.txt", "你应当去，他应当来。")  # 2 次
        self.write_skill(self.ROWS)
        self.assertEqual(self.warnings(), [])

    def test_threshold_is_three(self):
        self.assertEqual(v.DNA_BANNED_TERM_THRESHOLD, 3)

    def test_terms_banned_together_count_as_one_class(self):
        # 鲁迅：「应当」2 处、「必须」4 处——单看「应当」不到阈值，但他把二者并称「说教词」，按一类数。
        self.write_corpus("a.txt", "此事应当如此，彼事应当如彼，你必须去。")
        self.write_skill(self.ROWS)
        out = self.warnings()
        self.assertEqual(len(out), 1, out)
        self.assertIn("应当 2", out[0])
        self.assertIn("必须 1", out[0])

    def test_the_same_class_named_in_two_dimensions_warns_once(self):
        self.write_corpus("a.txt", "应当应当应当")
        self.write_skill({"句式偏好": "不用“应当”“必须”。", "禁忌表达": "不用“应当”“必须”之类说教词。"})
        out = self.warnings()
        self.assertEqual(len(out), 1, out)
        self.assertIn("句式偏好/禁忌表达", out[0])

    def test_separately_banned_terms_each_get_their_own_warning(self):
        self.write_corpus("a.txt", "应当应当应当，必须必须必须。")
        self.write_skill({"句式偏好": "不用“应当”。", "禁忌表达": "从不说“必须”。"})
        self.assertEqual(len(self.warnings()), 2)

    def test_no_corpus_means_nothing_to_verify(self):
        self.write_skill(self.ROWS)
        self.assertEqual(self.warnings(), [])

    def test_missing_skill_md_is_not_this_checks_business(self):
        self.assertEqual(self.warnings(), [])


class WiredIntoPackageGate(CorpusInDataRoot):
    def test_validate_package_reports_it_as_a_warning_only(self):
        self.write_corpus("热风.txt", "应当应当应当")
        self.write_skill({"禁忌表達": "不用“应当”之类说教词。"})
        cwd = os.getcwd()
        os.chdir(self.root)
        try:
            errors = v.validate_package("demo")
        finally:
            os.chdir(cwd)
        hits = [e for e in errors if "PKG_DNA_BANNED_TERM" in e]
        self.assertEqual(len(hits), 1, errors)
        self.assertTrue(hits[0].startswith("WARNING:"))


class PipelineWiring(unittest.TestCase):
    """处置办法要落到管线每个入口：Claude Code 编排者读 distill.md，`mdf run` / Codex / pi 只读角色定义与阶段树简报。"""

    def setUp(self):
        self.orchestrator = (ROOT / "commands" / "distill.md").read_text(encoding="utf-8")
        self.assembler = (ROOT / "agents" / "skill-assembler.md").read_text(encoding="utf-8")
        tree = json.loads((ROOT / "config" / "pipeline_stages.json").read_text(encoding="utf-8"))
        self.steps = {s["id"]: s for phase in tree["phases"] for s in phase["steps"]}

    def test_checkpoint_4_table_has_a_disposition(self):
        import re
        section = re.search(r"^### ✓ 检查点 4.*?(?=^## )", self.orchestrator, re.M | re.S).group(0)
        row = next((ln for ln in section.splitlines() if "PKG_DNA_BANNED_TERM" in ln), "")
        self.assertTrue(row.startswith("|"), "检查点 4 的处置表里要有这一行")
        self.assertIn("描述", row)
        self.assertIn("voice.md", row, "禁忌词声明同时出现在 voice.md 注释里，要一起改")

    def test_skill_assembler_knows_not_to_ban_words(self):
        self.assertIn("PKG_DNA_BANNED_TERM", self.assembler)
        self.assertIn("描述", self.assembler)

    def test_briefs_for_assembly_steps_carry_it(self):
        for step in ("assemble", "attachments"):
            with self.subTest(step=step):
                self.assertIn("PKG_DNA_BANNED_TERM", self.steps[step].get("checkpoint_note", ""))


if __name__ == "__main__":
    unittest.main()
