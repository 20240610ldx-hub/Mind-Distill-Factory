"""distill_confidence 闸门：CLAUDE.md 质量门「score ≥ 3 才能进 gallery」此前没有任何确定性检查。

2026-10-19 鲁迅 GUI 验收发现 10：frameworks.zh.json 的 distill_confidence.score 如实为 2，
validate frameworks 通过、publish --dry-run 也通过，门槛只靠子代理在 note 里提醒。
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from sibling import load_module  # noqa: E402  按路径加载模块的唯一入口（先登记 sys.modules）


publisher = load_module(ROOT / "scripts" / "publish_skill.py", "_publish_for_confidence")
validator = load_module(ROOT / "scripts" / "validate_output.py", "_validate_for_confidence")


class ConfidenceGatePolicy(unittest.TestCase):
    # (score, force, 审查关卡给的 review_status) → (允许发布, 最终 review_status)
    TABLE = {
        (3, False, "PASS"): (True, "PASS"),
        (5, False, "PASS"): (True, "PASS"),
        (2, False, "PASS"): (False, "BLOCKED_LOW_CONFIDENCE"),
        (2, True, "PASS"): (True, "FORCED_LOW_CONFIDENCE"),
        (2, True, "FORCED_REVISE"): (True, "FORCED_REVISE"),
        (None, False, "PASS"): (False, "BLOCKED_LOW_CONFIDENCE"),
        (None, True, "PASS"): (True, "FORCED_LOW_CONFIDENCE"),
    }

    def test_policy_table(self):
        for (score, force, status), expected in self.TABLE.items():
            with self.subTest(score=score, force=force, status=status):
                self.assertEqual(publisher.confidence_gate(score, force, status), expected)

    def test_threshold_is_the_validators(self):
        self.assertEqual(validator.FRAMEWORK_SCHEMA["min_distill_confidence"], 3)

    def test_forced_low_confidence_is_never_plain_pass(self):
        # validate published --strict 靠 review_status == "PASS" 判断是否真过了质量门
        for (score, force, status), (allowed, final) in self.TABLE.items():
            if allowed and not (isinstance(score, int) and score >= 3):
                self.assertNotEqual(final, "PASS")


class ReadsTheFrameworkScore(unittest.TestCase):
    def test_reads_score_from_frameworks_zh(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            (out / "frameworks.zh.json").write_text(json.dumps({"distill_confidence": {"score": 2}}), encoding="utf-8")
            self.assertEqual(publisher.read_distill_confidence(out), 2)
            (out / "frameworks.zh.json").write_text("{}", encoding="utf-8")
            self.assertIsNone(publisher.read_distill_confidence(out))
            self.assertIsNone(publisher.read_distill_confidence(out / "missing"))


class Stage3Warns(unittest.TestCase):
    def test_low_score_is_flagged_at_the_frameworks_gate(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "output" / "demo"
            out.mkdir(parents=True)
            (out / "frameworks.zh.json").write_text(json.dumps({"distill_confidence": {"score": 2}}),
                                                    encoding="utf-8")
            cwd = os.getcwd()
            os.chdir(td)
            try:
                errors = validator.validate_frameworks("demo")
            finally:
                os.chdir(cwd)
        flagged = [e for e in errors if "LOW_CONFIDENCE" in e]
        self.assertTrue(flagged, errors)
        self.assertTrue(all(e.startswith("WARNING") for e in flagged), "阶段 3 只提醒；拦在发布")


if __name__ == "__main__":
    unittest.main()
