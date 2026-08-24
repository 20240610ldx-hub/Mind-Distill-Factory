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
    """真实数据的阳性对照：14 条引文中恰有 4 条不是逐字引用。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.result = audit_mod.audit("zhang-juzheng", ROOT)

    def test_audits_fourteen_quotes(self) -> None:
        self.assertEqual(self.result["total"], 14)

    def test_exactly_four_fail(self) -> None:
        self.assertEqual(len(self.result["failed"]), 4)

    def test_ten_pass(self) -> None:
        self.assertEqual(self.result["passed"], 10)

    def test_stitched_quote_has_negligible_prefix(self) -> None:
        # 归一化后 17 字的引文只有前 3 字（如此则）能在语料中找到——
        # 注意 longest_verbatim_prefix 是「无锚点」的：它问「这个前缀是否出现在语料任何位置」，
        # 短前缀因此可能是巧合命中。3/17 在语义上即「几乎全无逐字依据」。
        stitched = [f for f in self.result["failed"] if "名必中实" in f["quote"]]
        self.assertEqual(len(stitched), 2)  # principle1 与 quote2 是同一句
        for item in stitched:
            self.assertEqual(item["longest_prefix"], 3)

    def test_character_corruption_has_partial_prefix(self) -> None:
        corrupted = [f for f in self.result["failed"] if "推护" in f["quote"]]
        self.assertEqual(len(corrupted), 1)
        self.assertGreater(corrupted[0]["longest_prefix"], 15)
        self.assertLess(corrupted[0]["longest_prefix"], 26)

    def test_silent_elision_has_short_prefix(self) -> None:
        elided = [f for f in self.result["failed"] if "须慎之于始" in f["quote"]]
        self.assertEqual(len(elided), 1)
        self.assertEqual(elided[0]["longest_prefix"], 9)


if __name__ == "__main__":
    unittest.main()
