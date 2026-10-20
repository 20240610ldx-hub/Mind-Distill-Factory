"""P2 覆盖率要看得见，语料外的证据卡不得标 high。

2026-10-19 鲁迅 GUI 验收发现 11：evidence.md 里 16 张卡取自维基文库转录，原文不在 sources/lu-xun/raw/，
P2 无从逐字核对，只能逐张降级为 WARNING。闸门照样「通过」，读的人看不出「逐字证据」的保证
只覆盖了《熱風》那几张卡。规则 6：只有网络来源的引文最高 medium——语料外的卡标 high 就是越权。
"""

from __future__ import annotations

import dataclasses
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import package_manifest as pm  # noqa: E402
import verify_provenance as prov  # noqa: E402
from sibling import load_module  # noqa: E402


WIKI = "`sources/demo/processed/primary_sources.json`（维基文库转录；不在 `sources/demo/raw/` 内）"


def card(title: str, quote: str, confidence: str, note: bool, location: str = WIKI) -> str:
    lines = [f"### {title}", "", f"> {quote}", "", "- 出处：测试", f"- 语料位置：{location}",
             f"- confidence：{confidence}"]
    if note:
        lines.append("- textual_note：取自网络转录，不在 raw/ 里")
    return "\n".join(lines) + "\n\n"


class Coverage(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        raw = self.root / "sources" / "demo" / "raw"
        raw.mkdir(parents=True)
        (raw / "熱風.txt").write_text("真的猛士敢於直面慘淡的人生敢於正視淋漓的鮮血", encoding="utf-8")
        self.evidence = self.root / "evidence.md"

    def tearDown(self):
        self._td.cleanup()

    def check(self, *cards: str) -> list[str]:
        self.evidence.write_text("# 证据\n\n" + "".join(cards), encoding="utf-8")
        return prov.check_p2_corpus_closure(self.evidence, "demo", self.root)

    def test_coverage_line_names_how_many_cards_were_machine_checked(self):
        errors = self.check(card("甲", "真的猛士，敢於直面慘淡的人生", "medium", False),
                            card("乙", "天才並不是自生自長在深林荒野裏的怪物", "medium", True))
        self.assertFalse([e for e in errors if not e.startswith("WARNING")], errors)
        coverage = [e for e in errors if "P2_COVERAGE" in e]
        self.assertEqual(len(coverage), 1, errors)
        self.assertIn("1/2", coverage[0])
        self.assertIn("mdf acquire", coverage[0])

    def test_all_cards_in_corpus_needs_no_coverage_line(self):
        errors = self.check(card("甲", "真的猛士，敢於直面慘淡的人生", "high", False))
        self.assertEqual(errors, [])

    def test_off_corpus_card_cannot_claim_high(self):
        errors = self.check(card("乙", "天才並不是自生自長在深林荒野裏的怪物", "high", True))
        hard = [e for e in errors if not e.startswith("WARNING")]
        self.assertTrue(any(e.startswith("P2_UNVERIFIED_HIGH") and "乙" in e for e in hard), errors)

    def test_variant_reading_of_a_raw_passage_may_stay_high(self):
        # 底本讹字：原文就在 raw/ 里，textual_note 记的是校勘，不是「语料外」——规则 6 管不着
        errors = self.check(card("丙", "真的勇士敢於直面慘淡的人生", "high", True,
                                 location="`sources/demo/raw/熱風.txt`（底本「勇」誤作「猛」）"))
        self.assertTrue(any("P2_NOT_IN_CORPUS" in e for e in errors), errors)  # 确实走到了语料外分支
        self.assertFalse([e for e in errors if not e.startswith("WARNING")], errors)

    def test_hard_failures_are_not_counted_as_adjudicated(self):
        # 没写 textual_note 的卡已经是硬错误，覆盖率行只数「靠人工裁决放行」的卡
        errors = self.check(card("甲", "真的猛士，敢於直面慘淡的人生", "medium", False),
                            card("丁", "語料裏沒有這句話", "medium", False))
        self.assertFalse([e for e in errors if "P2_COVERAGE" in e], errors)

    def test_attestation_records_coverage(self):
        self.evidence.write_text("# 证据\n\n" + card("甲", "真的猛士，敢於直面慘淡的人生", "medium", False)
                                 + card("乙", "天才並不是自生自長在深林荒野裏的怪物", "medium", True), encoding="utf-8")
        attestation = pm.attest_p2(self.evidence, "demo", self.root, prov)
        self.assertEqual((attestation["cards_verified"], attestation["cards_total"]), (1, 2))


class CoverageValueObject(unittest.TestCase):
    """覆盖率是领域概念，不是一行警告文本：格式与解析只在 EvidenceCoverage 一处。

    之前状态表用正则把警告文本拆回数字，manifest 另记一套整数，三处各自知道格式——改一处措辞，
    另一处就静悄悄地读不出覆盖率。
    """

    def test_warning_text_round_trips(self):
        coverage = prov.EvidenceCoverage(verified=12, total=28, adjudicated=16)
        line = coverage.warning("evidence.md", "lu-xun")
        self.assertTrue(line.startswith("WARNING: P2_COVERAGE"))
        self.assertEqual(prov.EvidenceCoverage.parse(line), coverage)
        self.assertIsNone(prov.EvidenceCoverage.parse("WARNING: 别的警告"))

    def test_attestation_round_trips(self):
        coverage = prov.EvidenceCoverage(verified=5, total=7, adjudicated=2)
        self.assertEqual(prov.EvidenceCoverage.from_attestation(coverage.to_attestation()), coverage)
        self.assertIsNone(prov.EvidenceCoverage.from_attestation({"status": "pass"}), "旧 manifest 没有覆盖率")

    def test_is_a_frozen_dataclass_like_the_other_value_objects(self):
        coverage = prov.EvidenceCoverage(verified=1, total=2)
        self.assertTrue(dataclasses.is_dataclass(coverage))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            coverage.verified = 2  # type: ignore[misc]

    def test_survives_a_by_path_load_under_future_annotations(self):
        """按路径加载本模块（测试与 mdf 都这么做）时 dataclass 不能崩——靠 sibling.load_module 先登记。"""
        module = load_module(ROOT / "scripts" / "verify_provenance.py", "_p2_cov_by_path")
        self.addCleanup(sys.modules.pop, "_p2_cov_by_path", None)
        self.assertEqual(module.EvidenceCoverage(1, 2).total, 2)

    def test_gap_is_only_reported_when_cards_were_waved_through(self):
        self.assertEqual(prov.EvidenceCoverage(verified=3, total=3).gap(), "")
        gap = prov.EvidenceCoverage(verified=12, total=28, adjudicated=16).gap()
        self.assertIn("12/28", gap)
        self.assertIn("16", gap)

    def test_scan_returns_the_value_object(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw = root / "sources" / "demo" / "raw"
            raw.mkdir(parents=True)
            (raw / "a.txt").write_text("真的猛士敢於直面慘淡的人生", encoding="utf-8")
            evidence = root / "evidence.md"
            evidence.write_text("# 证据\n\n" + card("甲", "真的猛士，敢於直面慘淡的人生", "medium", False)
                                + card("乙", "天才並不是自生自長的怪物", "medium", True), encoding="utf-8")
            errors, coverage = prov.p2_scan(evidence, "demo", prov.load_corpus("demo", root))
        self.assertEqual(coverage, prov.EvidenceCoverage(verified=1, total=2, adjudicated=1))
        self.assertIn(coverage.warning("evidence.md", "demo"), errors)


if __name__ == "__main__":
    unittest.main()
