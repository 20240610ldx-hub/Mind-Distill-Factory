from __future__ import annotations

import importlib.util
import json
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


runtime = load_module("run_dialogue_eval", ROOT / "evaluation" / "runtime" / "run_dialogue_eval.py")
collector = load_module("collect_artifacts", ROOT / "evaluation" / "scripts" / "collect_artifacts.py")


class EvaluationRuntimeTests(unittest.TestCase):
    def test_extract_qa_pairs_does_not_absorb_case_headings(self) -> None:
        markdown = (
            "# Dialogue Test Set - demo\n\n"
            "## Case 01 - First\n\n"
            "**Q:** first question?\n\n"
            "**A:** first answer.\n\n"
            "## Case 02 - Second\n\n"
            "## Case 02 - Second\n\n"
            "**Q:** second question?\n\n"
            "**A:** second answer.\n"
        )

        pairs = runtime.extract_qa_pairs(markdown)

        self.assertEqual(pairs, [
            ("first question?", "first answer."),
            ("second question?", "second answer."),
        ])

    def test_soul_question_auto_trigger_rules(self) -> None:
        def should_run(**overrides) -> bool:
            params = {
                "ten_questions": "auto",
                "source": "generated",
                "smoke": False,
                "limit": None,
                "import_existing": False,
                "judge_existing_runtime": False,
                "record_count": 12,
                "standard_case_count": 12,
            }
            params.update(overrides)
            return runtime.should_run_soul_questions(**params)

        self.assertTrue(should_run())
        self.assertFalse(should_run(smoke=True))
        self.assertFalse(should_run(limit=12))
        self.assertFalse(should_run(source="imported", import_existing=True))
        self.assertFalse(should_run(judge_existing_runtime=True))
        self.assertFalse(should_run(record_count=11))
        self.assertTrue(should_run(ten_questions="on", smoke=True, source="imported", import_existing=True))
        self.assertFalse(should_run(ten_questions="off"))

    def test_soul_question_json_and_markdown_contract_preserve_utf8(self) -> None:
        raw = {
            "questions": [
                {
                    "question": f"第{i:02d}问：您如何看待这件事？",
                    "why_this_question": "用于观察人格智慧，而不是评分。",
                    "principle_or_source_anchor": "原则锚点",
                }
                for i in range(1, 11)
            ]
        }
        questions = runtime.normalize_soul_questions(raw)
        self.assertEqual(len(questions), 10)
        self.assertEqual(len({item["id"] for item in questions}), 10)
        for item in questions:
            self.assertTrue(item["archetype"])
            self.assertTrue(item["principle_or_source_anchor"])

        records = []
        for question in questions:
            record = dict(question)
            record["answer"] = "这是中文回答。"
            record["model_metadata"] = {
                "question_model": "fake-model",
                "answer_model": "fake-model",
                "reasoning_effort": "test",
            }
            records.append(record)

        with tempfile.TemporaryDirectory() as tmp:
            json_path = Path(tmp) / "ten-question-qa.json"
            payload = {
                "schema_version": runtime.SOUL_QUESTION_SCHEMA_VERSION,
                "benchmark_included": False,
                "questions": records,
            }
            runtime.write_json(json_path, payload)
            loaded = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["questions"][0]["question"], "第01问：您如何看待这件事？")

        markdown = runtime.render_soul_markdown(
            slug="demo",
            model="fake-model",
            reasoning_effort="test",
            generated_at="2026-05-21T00:00:00+00:00",
            records=records,
        )
        self.assertIn(runtime.SOUL_APPENDIX_NOTICE, markdown)
        self.assertIn("Benchmark Included: `false`", markdown)
        self.assertIn("这是中文回答。", markdown)

        summary = runtime.render_soul_summary_markdown(slug="demo", summary=runtime.default_soul_summary())
        for heading in runtime.SOUL_SUMMARY_HEADINGS:
            self.assertIn(f"## {heading}", summary)
        self.assertNotIn("runtime_score_25", summary)
        self.assertNotIn("Total Score", summary)

    def test_soul_question_artifacts_do_not_change_scorecard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "output" / "demo"
            gallery_dir = root / "gallery" / "demo"
            report_dir = root / "evaluation" / "reports" / "demo"
            output_dir.mkdir(parents=True)
            gallery_dir.mkdir(parents=True)
            report_dir.mkdir(parents=True)

            skill_text = (
                "---\n"
                "name: demo-wisdom\n"
                "description: Demo skill.\n"
                "---\n"
                "# Demo Skill\n\n"
                "## English\n\n"
                "Source Lineage: documented source.\n"
                "Decision Framework: yes/no gate.\n"
                "Known Blind Spots: includes mitigation.\n"
                "Boundary Rules: verify data and do not assess living figures.\n"
                "Use first-person rules and Anti-Formula guidance.\n\n"
                "## 中文版\n\n"
                "Source Lineage: documented source.\n"
            )
            (output_dir / "SKILL.md").write_text(skill_text, encoding="utf-8")
            (gallery_dir / "SKILL.md").write_text(skill_text, encoding="utf-8")
            (report_dir / "runtime-judgment.json").write_text(
                json.dumps(
                    {
                        "schema_version": "MindDistillRuntimeJudgment-v1",
                        "aggregate": {
                            "runtime_score_25": 20,
                            "coverage": "standard",
                            "p0_count": 0,
                            "p1_count": 0,
                            "summary": "Stable enough for this regression.",
                        },
                        "metadata": {
                            "record_count": 12,
                            "source": "generated",
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            facts_before = collector.collect_facts(root, "demo")
            score_before = collector.score_facts(facts_before)

            questions = []
            for idx, archetype in enumerate(runtime.SOUL_QUESTION_ARCHETYPES, start=1):
                questions.append(
                    {
                        "id": f"Q{idx:02d}",
                        "archetype": archetype["id"],
                        "question": f"第{idx:02d}问",
                        "why_this_question": "非评分观察。",
                        "principle_or_source_anchor": "source anchor",
                        "answer": "回答。",
                        "model_metadata": {
                            "question_model": "fake-model",
                            "answer_model": "fake-model",
                            "reasoning_effort": "test",
                        },
                    }
                )
            (report_dir / "ten-question-qa.json").write_text(
                json.dumps(
                    {
                        "schema_version": runtime.SOUL_QUESTION_SCHEMA_VERSION,
                        "benchmark_included": False,
                        "questions": questions,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            (report_dir / "ten-question-qa.md").write_text(runtime.SOUL_APPENDIX_NOTICE, encoding="utf-8")
            (report_dir / "ten-question-summary.md").write_text(runtime.default_soul_summary(), encoding="utf-8")

            facts_after = collector.collect_facts(root, "demo")
            score_after = collector.score_facts(facts_after)

            self.assertTrue(facts_after["soul_ten_questions"]["valid_non_benchmark_appendix"])
            self.assertEqual(facts_before["runtime"], facts_after["runtime"])
            self.assertEqual(score_before["total_score"], score_after["total_score"])
            self.assertEqual(score_before["grade_label"], score_after["grade_label"])
            self.assertEqual(score_before["score_caps"], score_after["score_caps"])
            before_runtime = next(
                item for item in score_before["metrics"] if item["metric"] == "Runtime Robustness & Generalization"
            )
            after_runtime = next(
                item for item in score_after["metrics"] if item["metric"] == "Runtime Robustness & Generalization"
            )
            self.assertEqual(before_runtime["score"], after_runtime["score"])


if __name__ == "__main__":
    unittest.main()
