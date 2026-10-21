"""运行时评测里的附件读取（HANDOFF P2）。

v6 技能包 = SKILL.md + references/{cases,evidence,voice}.md。真实运行时，模型照 SKILL.md 里写的相对路径按需读附件；
原来的评测只把 SKILL.md 塞进 system prompt，附件从来没被读到，也就测不出「该读证据时读没读」。

现在：生成回答时给模型一个 read_reference 工具，只放行这三个附件（拒绝绝对路径、`..`、包里其他文件、指出包外的链接），
每次调用记一行轨迹（runtime-trace.jsonl），每条记录带上它读了哪些附件，judge 能看到。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from sibling import load_module  # noqa: E402  按路径加载模块的唯一入口（先登记 sys.modules）


runtime = load_module(ROOT / "evaluation" / "runtime" / "run_dialogue_eval.py", "run_dialogue_eval_refs")

CASES_MD = "# 案例\n\n## 案例 1 守城\n正文"


def make_package(root: Path, *, references: bool = True) -> Path:
    skill_dir = root / "output" / "demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# 技能\n读 references/cases.md 看案例。", encoding="utf-8")
    (skill_dir / "人物档案.md").write_text("档案，不进安装目录", encoding="utf-8")
    if references:
        (skill_dir / "references").mkdir()
        (skill_dir / "references" / "cases.md").write_text(CASES_MD, encoding="utf-8")
        (skill_dir / "references" / "voice.md").write_text("# 语感", encoding="utf-8")
    return skill_dir


def tool_call(path, *, name="read_reference", call_id="call_1", raw=None):
    arguments = raw if raw is not None else json.dumps({"path": path})
    return {"choices": [{"message": {"content": "", "reasoning_content": "想一想",
                                     "tool_calls": [{"id": call_id, "type": "function",
                                                     "function": {"name": name, "arguments": arguments}}]}}]}


def answer(text):
    return {"choices": [{"message": {"content": text}}]}


class FakeChat:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def __call__(self, **kwargs):
        self.calls.append({**kwargs, "messages": [dict(m) for m in kwargs["messages"]]})
        return self.responses.pop(0)


class ReadReferenceTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.skill_dir = make_package(Path(self._td.name))

    def tearDown(self):
        self._td.cleanup()

    def test_the_three_attachments_are_readable(self):
        self.assertEqual(runtime.read_reference(self.skill_dir, "references/cases.md"), CASES_MD)
        self.assertEqual(runtime.read_reference(self.skill_dir, "./references/voice.md"), "# 语感")

    def test_absolute_paths_and_parent_steps_are_refused(self):
        for bad in ("/etc/passwd", "C:/Windows/win.ini", "C:\\Windows\\win.ini", "\\\\server\\share\\x.md",
                    "references/../SKILL.md", "../demo/references/cases.md", "references\\..\\SKILL.md"):
            with self.subTest(path=bad), self.assertRaises(ValueError):
                runtime.read_reference(self.skill_dir, bad)

    def test_other_files_in_the_package_are_refused(self):
        for bad in ("SKILL.md", "人物档案.md", "references/other.md", "references", ""):
            with self.subTest(path=bad), self.assertRaises(ValueError):
                runtime.read_reference(self.skill_dir, bad)
        with self.assertRaises(ValueError):
            runtime.read_reference(self.skill_dir, None)

    def test_an_allowed_but_absent_attachment_is_missing_not_refused(self):
        with self.assertRaises(FileNotFoundError):
            runtime.read_reference(self.skill_dir, "references/evidence.md")

    def test_a_link_out_of_the_package_is_refused(self):
        outside = Path(self._td.name) / "secret.md"
        outside.write_text("包外", encoding="utf-8")
        link = self.skill_dir / "references" / "evidence.md"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("这台机器不允许建符号链接")
        with self.assertRaises(ValueError):
            runtime.read_reference(self.skill_dir, "references/evidence.md")

    def test_available_references_lists_only_present_attachments(self):
        self.assertEqual(runtime.available_references(self.skill_dir),
                         ["references/cases.md", "references/voice.md"])
        self.assertEqual(runtime.available_references(None), [])


class SystemPromptTests(unittest.TestCase):
    def test_prompt_names_the_tool_and_the_attachments_only_when_there_are_some(self):
        with_refs = runtime.build_system_prompt("# 技能", references=["references/cases.md"])
        self.assertIn("read_reference", with_refs)
        self.assertIn("references/cases.md", with_refs)
        self.assertNotIn("read_reference", runtime.build_system_prompt("# 技能"))


class GenerationWithReferencesTests(unittest.TestCase):
    cases = [{"id": "case_01", "title": "守城", "category": "practical", "prompt": "城要不要守？"}]

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def generate(self, chat, *, references=True, cases=None):
        skill_dir = make_package(self.root, references=references)
        trace: list[dict] = []
        records = runtime.run_generation(api_key="k", base_url="u", model="m", reasoning_effort="high",
                                         skill_text="# 技能", cases=cases or self.cases, skill_dir=skill_dir,
                                         trace=trace, chat=chat)
        return records, trace

    def test_a_read_is_answered_traced_and_recorded(self):
        chat = FakeChat(tool_call("references/cases.md"), answer("我守过城。"))
        records, trace = self.generate(chat)
        self.assertEqual(records[0]["answer"], "我守过城。")
        self.assertEqual(records[0]["references_read"], ["references/cases.md"])
        tool_reply = chat.calls[1]["messages"][-1]
        self.assertEqual((tool_reply["role"], tool_reply["tool_call_id"], tool_reply["content"]),
                         ("tool", "call_1", CASES_MD))
        self.assertEqual(chat.calls[1]["messages"][-2]["reasoning_content"], "想一想",
                         "同一轮里的工具调用要把思考内容原样带回去")
        self.assertEqual(len(trace), 1)
        self.assertEqual({k: trace[0][k] for k in ("case_id", "tool", "path", "status", "chars")},
                         {"case_id": "case_01", "tool": "read_reference", "path": "references/cases.md",
                          "status": "ok", "chars": len(CASES_MD)})

    def test_a_refused_read_tells_the_model_and_leaks_nothing(self):
        chat = FakeChat(tool_call("../demo/人物档案.md"), answer("那就不看了。"))
        records, trace = self.generate(chat)
        reply = chat.calls[1]["messages"][-1]["content"]
        self.assertTrue(reply.startswith("ERROR"))
        self.assertNotIn("不进安装目录", reply)
        self.assertEqual(trace[0]["status"], "denied")
        self.assertEqual(records[0]["references_read"], [])

    def test_missing_attachment_unknown_tool_and_bad_arguments_are_traced(self):
        chat = FakeChat(tool_call("references/evidence.md"), tool_call(None, name="run_shell", call_id="c2"),
                        tool_call(None, raw="{不是 json", call_id="c3"), answer("好。"))
        _, trace = self.generate(chat)
        self.assertEqual([e["status"] for e in trace], ["missing", "denied", "denied"])

    def test_a_package_without_attachments_gets_no_tool(self):
        chat = FakeChat(answer("直接答。"))
        records, trace = self.generate(chat, references=False)
        self.assertIsNone(chat.calls[0].get("tools"))
        self.assertEqual((records[0]["answer"], records[0]["references_read"], trace), ("直接答。", [], []))

    def test_tool_rounds_are_bounded(self):
        rounds = runtime.MAX_TOOL_ROUNDS
        chat = FakeChat(*[tool_call("references/cases.md", call_id=f"c{i}") for i in range(rounds)], answer("够了。"))
        records, _ = self.generate(chat)
        self.assertEqual(records[0]["answer"], "够了。")
        self.assertEqual(chat.calls[-1].get("tool_choice"), "none", "最后一轮不许再调工具，逼它作答")
        stubborn = FakeChat(*[tool_call("references/cases.md", call_id=f"c{i}") for i in range(rounds + 1)])
        self.tearDown(), self.setUp()
        with self.assertRaises(RuntimeError):
            self.generate(stubborn)

    def test_the_conversation_carries_the_previous_turn_forward(self):
        cases = self.cases + [{"id": "case_02", "title": "追问", "category": "sparring", "prompt": "再说说？"}]
        chat = FakeChat(tool_call("references/cases.md"), answer("我守过城。"), answer("还是守。"))
        records, _ = self.generate(chat, cases=cases)
        history = chat.calls[2]["messages"]
        self.assertEqual(history[-2], {"role": "assistant", "content": "我守过城。"})
        self.assertEqual(history[-1], {"role": "user", "content": "再说说？"})
        self.assertIn(CASES_MD, [m.get("content") for m in history], "读过的附件留在上下文里，和真实运行时一样")
        self.assertEqual(records[1]["references_read"], [])


class MainWritesTraceTests(unittest.TestCase):
    def test_generated_run_writes_runtime_trace_jsonl(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            make_package(root)
            test_set = root / "set.json"
            test_set.write_text(json.dumps({"language": "zh", "cases": GenerationWithReferencesTests.cases},
                                           ensure_ascii=False), encoding="utf-8")
            chat = FakeChat(tool_call("references/cases.md"), answer("我守过城。"))
            env = {"MIND_DISTILL_EVAL_API_KEY": "k", "MIND_DISTILL_EVAL_LLM": "deepseek"}
            with mock.patch.dict(os.environ, env), mock.patch.object(runtime, "deepseek_chat", chat):
                code = runtime.main(["--slug", "demo", "--root", td, "--no-env-file", "--no-judge",
                                     "--ten-questions", "off", "--test-set", str(test_set),
                                     "--judge-rubric", str(ROOT / "evaluation/runtime/judge_rubric.json")])
            self.assertEqual(code, 0)
            lines = (root / "evaluation/reports/demo/runtime-trace.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual([json.loads(ln)["status"] for ln in lines], ["ok"])


if __name__ == "__main__":
    unittest.main()
