"""预算闸门：超预算的分片抽取，要有用户批准过不小于当前规模的预算才派 worker。

2026-10-19 鲁迅 GUI 验收发现 5：cost_estimate 没配单价时 cost 全是 cost_unknown，上界是 None；
协议写的「上界超过配置预算就先问用户」既没有配置预算、也没有地方调用 exceeds_budget，闸门永远不响。
token 数总是算得出，所以按 token 判断。
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import cost_estimator as ce  # noqa: E402
import mdf  # noqa: E402
import pipeline_status as ps  # noqa: E402


def estimate(selected: int, shards: int = 3, pricing: ce.Pricing | None = None) -> dict:
    return ce.estimate_cost(selected_tokens=selected, total_tokens=selected * 2, shard_count=shards, pricing=pricing)


class Verdict(unittest.TestCase):
    def test_default_budget_matches_the_sampling_cap(self):
        self.assertEqual(ce.load_budget(ROOT).max_selected_input_tokens, 500_000)

    def test_tokens_decide_even_when_prices_are_unknown(self):
        budget = ce.Budget(max_selected_input_tokens=500_000)
        over = estimate(600_000)
        self.assertEqual(over["cost"]["status"], "cost_unknown")
        reason = budget.verdict(over)
        self.assertIn("600,000", reason)
        self.assertIn("500,000", reason)
        self.assertIsNone(budget.verdict(estimate(400_000)))

    def test_cost_counts_only_when_priced(self):
        budget = ce.Budget(max_selected_input_tokens=10_000_000, max_cost_usd=1.0)
        priced = estimate(600_000, pricing=ce.Pricing(input_per_million=3.0, output_per_million=15.0))
        self.assertIn("$", budget.verdict(priced))
        self.assertIsNone(budget.verdict(estimate(600_000)), "单价未知时不拿费用判断")

    def test_approval_covers_this_size_and_smaller_only(self):
        approval = {"approved_selected_input_tokens": 600_000}
        self.assertTrue(ce.Budget.covers(approval, estimate(600_000)))
        self.assertTrue(ce.Budget.covers(approval, estimate(550_000)))
        self.assertFalse(ce.Budget.covers(approval, estimate(700_000)), "重新分片变大了要再问")
        self.assertFalse(ce.Budget.covers(None, estimate(1)))


class ExtractStepGate(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        (self.root / "sources" / "demo" / "raw").mkdir(parents=True)
        (self.root / "sources" / "demo" / "raw" / "a.txt").write_text("正文", encoding="utf-8")
        self.shards = self.root / "sources" / "demo" / "processed" / "local_shards"
        self.shards.mkdir(parents=True)
        units = [{"unit_id": f"shard_{i:03d}"} for i in (1, 2, 3)]
        (self.shards / "task_status.json").write_text(json.dumps(
            {"input_units": units, "completed_units": [], "pending_units": [u["unit_id"] for u in units]}),
            encoding="utf-8")

    def tearDown(self):
        self._td.cleanup()

    def extract(self):
        return next(s for s in ps.collect_status("demo", self.root) if s.key == "extract")

    def write_estimate(self, selected: int):
        ce.write_estimate(self.shards / "cost_estimate.json", estimate(selected))

    def mdf(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = mdf.main([*argv, "--root", str(self.root)])
        return code, out.getvalue()

    def test_estimate_is_visible_on_the_step(self):
        self.write_estimate(28_347)
        step = self.extract()
        self.assertEqual(step.state, "pending")
        self.assertIn("预计输入 28,347 token", step.detail)

    def test_over_budget_blocks_dispatch_until_the_user_approves(self):
        self.write_estimate(600_000)
        step = self.extract()
        self.assertEqual(step.state, "blocked")
        self.assertIn("AskUserQuestion", step.next_action)
        self.assertIn("mdf.py budget demo --approve", step.next_action)

        code, out = self.mdf("budget", "demo", "--approve")
        self.assertEqual(code, 0, out)
        step = self.extract()
        self.assertEqual(step.state, "pending")
        self.assertIn("用户已批准", step.detail)
        self.assertIn("shard_001", step.next_action)

        self.write_estimate(900_000)  # 重新分片后更大：批准不再覆盖
        self.assertEqual(self.extract().state, "blocked")

    def test_budget_command_without_overrun_writes_nothing(self):
        self.write_estimate(28_347)
        code, out = self.mdf("budget", "demo", "--approve")
        self.assertEqual(code, 0)
        self.assertIn("未超预算", out)
        self.assertFalse((self.shards / ce.APPROVAL_FILE).exists())


if __name__ == "__main__":
    unittest.main()
