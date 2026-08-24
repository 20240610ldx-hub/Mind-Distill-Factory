from __future__ import annotations

import importlib.util
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


audit_mod = load_module("audit_legacy_quotes", ROOT / "scripts" / "audit_legacy_quotes.py")


@unittest.skipUnless(
    (ROOT / "sources" / "zhang-juzheng" / "raw").exists(),
    "zhang-juzheng corpus not present",
)
class ZhangAuditTests(unittest.TestCase):
    """真实数据的阳性对照：json 视图 15 条引文中恰有 4 条不是逐字引用；

    skill_md 视图审计的是组装后的 output/zhang-juzheng/SKILL.md，字段更少
    （extract_skill_quotes 只认「原文出处」行与二级标题「标志性名言」章节，
    而该文件的「标志性名言」实际渲染成三级标题，因此匹配不到，只剩 7 条
    「原文出处」行），但恰恰是这个更窄的视图，暴露了 json 视图看不见的
    装配期缺陷：principle4 在 JSON 里因为完整保留「务求相应」而逐字通过，
    渲染到 SKILL.md 时丢了这四个字，逐字校验从 PASS 变成 FAIL。
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.result = audit_mod.audit("zhang-juzheng", ROOT)

    # ── json 视图：frameworks.zh.json ──────────────────────────────

    def test_json_audits_fifteen_quotes(self) -> None:
        # 14 条（7 principle + 7 signature_quotes）+ 1 顶层 signature_quote_header
        self.assertEqual(self.result["json"]["total"], 15)

    def test_json_exactly_four_fail(self) -> None:
        self.assertEqual(len(self.result["json"]["failed"]), 4)

    def test_json_eleven_pass(self) -> None:
        # 顶层 signature_quote_header 与 zhang-juzheng 的 signature_quotes[0]
        # 是同一句、逐字通过，因此 total 15 - failed 4 = passed 11
        self.assertEqual(self.result["json"]["passed"], 11)

    def test_json_signature_quote_header_is_audited(self) -> None:
        header = [
            d for d in self.result["json"]["passed_detail"]
            if d["tag"] == "signature_quote_header"
        ]
        self.assertEqual(len(header), 1)

    def test_json_stitched_quote_has_negligible_prefix(self) -> None:
        # 归一化后 17 字的引文只有前 3 字（如此则）能在语料中找到——
        # 注意 longest_verbatim_prefix 是「无锚点」的：它问「这个前缀是否出现在语料任何位置」，
        # 短前缀因此可能是巧合命中。3/17 在语义上即「几乎全无逐字依据」。
        stitched = [f for f in self.result["json"]["failed"] if "名必中实" in f["quote"]]
        self.assertEqual(len(stitched), 2)  # principle1 与 quote2 是同一句
        for item in stitched:
            self.assertEqual(item["longest_prefix"], 3)

    def test_json_character_corruption_has_partial_prefix(self) -> None:
        corrupted = [f for f in self.result["json"]["failed"] if "推护" in f["quote"]]
        self.assertEqual(len(corrupted), 1)
        self.assertGreater(corrupted[0]["longest_prefix"], 15)
        self.assertLess(corrupted[0]["longest_prefix"], 26)

    def test_json_silent_elision_has_short_prefix(self) -> None:
        elided = [f for f in self.result["json"]["failed"] if "须慎之于始" in f["quote"]]
        self.assertEqual(len(elided), 1)
        self.assertEqual(elided[0]["longest_prefix"], 9)

    # ── skill_md 视图：组装后的 output/zhang-juzheng/SKILL.md ──────

    def test_skill_md_view_counts(self) -> None:
        skill_md = self.result["skill_md"]
        self.assertEqual(skill_md["total"], 7)
        self.assertEqual(skill_md["passed"], 4)
        self.assertEqual(len(skill_md["failed"]), 3)

    def test_skill_md_failed_prefixes_match_same_three_defects(self) -> None:
        prefixes = sorted(item["longest_prefix"] for item in self.result["skill_md"]["failed"])
        self.assertEqual(prefixes, [3, 9, 21])

    # ── json vs skill_md 分歧 ────────────────────────────────────────

    def test_principle4_diverges_between_json_and_skill_md(self) -> None:
        # frameworks.zh.json 的 principle4 完整保留「务求相应」，逐字通过；
        # 组装到 SKILL.md 时丢字，逐字校验失败——这正是本工具存在的理由：
        # 只审计 JSON 会漏掉用户实际安装的产物里的缺陷。
        divergences = self.result["divergences"]
        self.assertEqual(len(divergences), 1)
        d = divergences[0]
        self.assertEqual(d["json_tag"], "principle4")
        self.assertEqual(d["json_status"], "pass")
        self.assertEqual(d["skill_md_status"], "fail")
        self.assertIn("须慎之于始", d["json_quote"])

    # ── raw/ vs processed/ 语料来源 ──────────────────────────────────

    def test_all_passes_backed_by_raw_corpus(self) -> None:
        # 当前 zhang-juzheng 的全部通过项都命中 raw/ 一手语料，没有任何一条
        # 只靠 processed/ 流水线派生文件（可能是引文抽取样本本身）撑过。
        processed_only = [
            item
            for view in (self.result["json"], self.result["skill_md"])
            for item in view["passed_detail"]
            if item["matched_dir"] == "processed"
        ]
        self.assertEqual(processed_only, [])


if __name__ == "__main__":
    unittest.main()
