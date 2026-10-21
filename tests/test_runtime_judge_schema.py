"""运行时评测的 judge 输出要按 schema 严格校验（HANDOFF P2）。

原来的做法：`parse_json_object` 解析失败就用贪婪正则 `\\{.*\\}` 从整段文字里捞 JSON，`judge_records` 再用 setdefault
补 schema_version / metadata。模型回了半截、多段、字段错的 JSON 都会被当成有效裁决写进 runtime-judgment.json，
分数随后进入 collect_artifacts 的总分。现在：只认整段 JSON（允许一层 ```json 围栏）；字段、分数范围、严重度、
失败标记、P0/P1 计数逐项核对；不合格就带着错误清单让 judge 重答一次，仍不合格就失败，不补默认值。
"""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from sibling import load_module  # noqa: E402  按路径加载模块的唯一入口（先登记 sys.modules）


runtime = load_module(ROOT / "evaluation" / "runtime" / "run_dialogue_eval.py", "run_dialogue_eval_judge")
RUBRIC = json.loads((ROOT / "evaluation" / "runtime" / "judge_rubric.json").read_text(encoding="utf-8"))
METRICS = list(RUBRIC["per_case_metrics"])
CASES = ["case_01", "case_02"]


def valid_judgment() -> dict:
    return {
        "schema_version": "MindDistillRuntimeJudgment-v1",
        "case_judgments": [
            {"case_id": "case_01", "scores": {m: 4 for m in METRICS}, "failure_flags": [],
             "severity": "none", "notes": "稳"},
            {"case_id": "case_02", "scores": {m: 3 for m in METRICS}, "failure_flags": ["ordinal_formula"],
             "severity": "P1", "notes": "序数列举"},
        ],
        "aggregate": {"runtime_score_25": 18, "coverage": "standard", "p0_count": 0, "p1_count": 1,
                      "summary": "可用"},
    }


class ParseJsonObject(unittest.TestCase):
    def test_whole_object_and_one_fence_are_accepted(self):
        text = json.dumps(valid_judgment(), ensure_ascii=False)
        self.assertEqual(runtime.parse_json_object(text)["aggregate"]["p1_count"], 1)
        self.assertEqual(runtime.parse_json_object(f"```json\n{text}\n```")["aggregate"]["p1_count"], 1)

    def test_no_fishing_json_out_of_prose(self):
        text = json.dumps(valid_judgment())
        for bad in (f"这是评分：{text}", f"{text}\n以上。", '{"a": 1} 和 {"b": 2}'):
            with self.subTest(bad=bad[:20]), self.assertRaises(ValueError):
                runtime.parse_json_object(bad)

    def test_top_level_must_be_an_object(self):
        with self.assertRaises(ValueError):
            runtime.parse_json_object("[1, 2]")


class ValidateJudgment(unittest.TestCase):
    def errors(self, judgment):
        return runtime.validate_judgment(judgment, RUBRIC, CASES)

    def mutate(self, fn) -> list[str]:
        judgment = valid_judgment()
        fn(judgment)
        return self.errors(judgment)

    def test_valid_judgment_has_no_errors(self):
        self.assertEqual(self.errors(valid_judgment()), [])

    def test_every_record_is_judged_exactly_once(self):
        self.assertTrue(any("case_02" in e for e in self.mutate(lambda j: j["case_judgments"].pop())))
        self.assertTrue(any("case_09" in e for e in self.mutate(
            lambda j: j["case_judgments"].append({**j["case_judgments"][0], "case_id": "case_09"}))))
        self.assertTrue(any("重复" in e for e in self.mutate(
            lambda j: j["case_judgments"].append(copy.deepcopy(j["case_judgments"][0])))))

    def test_scores_follow_the_rubric(self):
        self.assertTrue(self.mutate(lambda j: j["case_judgments"][0]["scores"].pop(METRICS[0])))
        self.assertTrue(self.mutate(lambda j: j["case_judgments"][0]["scores"].update(extra=3)))
        self.assertTrue(self.mutate(lambda j: j["case_judgments"][0]["scores"].update({METRICS[0]: 6})))
        self.assertTrue(self.mutate(lambda j: j["case_judgments"][0]["scores"].update({METRICS[0]: "4"})))
        self.assertTrue(self.mutate(lambda j: j["case_judgments"][0]["scores"].update({METRICS[0]: True})))

    def test_severity_and_flags_come_from_the_rubric(self):
        self.assertTrue(self.mutate(lambda j: j["case_judgments"][0].update(severity="P3")))
        self.assertTrue(self.mutate(lambda j: j["case_judgments"][0].update(failure_flags=["made_up"])))
        self.assertTrue(self.mutate(lambda j: j["case_judgments"][0].update(failure_flags="ordinal_formula")))

    def test_aggregate_is_checked_against_the_cases(self):
        self.assertTrue(self.mutate(lambda j: j["aggregate"].update(runtime_score_25=26)))
        self.assertTrue(self.mutate(lambda j: j["aggregate"].update(coverage="most")))
        p1 = self.mutate(lambda j: j["aggregate"].update(p1_count=0))
        self.assertTrue(any("p1_count" in e for e in p1), "P1 计数必须等于严重度为 P1 的条数")
        self.assertTrue(self.mutate(lambda j: j.pop("aggregate")))

    def test_schema_version_is_not_filled_in(self):
        self.assertTrue(self.mutate(lambda j: j.pop("schema_version")))


class FakeChat:
    def __init__(self, *contents: str):
        self.contents = list(contents)
        self.calls: list[list[dict]] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs["messages"])
        return {"choices": [{"message": {"content": self.contents.pop(0)}}]}


class JudgeRecords(unittest.TestCase):
    records = [{"case_id": c, "question": "问", "answer": "答"} for c in CASES]

    def judge(self, chat):
        return runtime.judge_records(api_key="k", base_url="u", model="m", reasoning_effort="max",
                                     skill_text="# 技能", rubric=RUBRIC, records=self.records,
                                     standard_case_count=2, chat=chat)

    def test_valid_answer_gets_metadata_and_nothing_else_invented(self):
        result = self.judge(FakeChat(json.dumps(valid_judgment())))
        self.assertEqual(result["metadata"]["model"], "m")
        self.assertEqual(result["aggregate"]["runtime_score_25"], 18)

    def test_invalid_answer_is_sent_back_once_with_the_errors(self):
        broken = valid_judgment()
        broken["aggregate"]["p1_count"] = 0
        chat = FakeChat(json.dumps(broken), json.dumps(valid_judgment()))
        self.assertEqual(self.judge(chat)["aggregate"]["p1_count"], 1)
        self.assertEqual(len(chat.calls), 2)
        self.assertIn("p1_count", chat.calls[1][-1]["content"], "重答时要告诉 judge 哪里不合格")

    def test_still_invalid_after_retry_fails_closed(self):
        broken = json.dumps({**valid_judgment(), "case_judgments": []})
        with self.assertRaises(RuntimeError) as ctx:
            self.judge(FakeChat(broken, broken))
        self.assertIn("case_01", str(ctx.exception))

    def test_prose_wrapped_answer_is_not_rescued(self):
        wrapped = "评分如下：" + json.dumps(valid_judgment())
        with self.assertRaises(RuntimeError):
            self.judge(FakeChat(wrapped, wrapped))


if __name__ == "__main__":
    unittest.main()
