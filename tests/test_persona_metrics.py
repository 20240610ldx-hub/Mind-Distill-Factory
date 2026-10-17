"""人物包确定性度量（scripts/persona_metrics.py）：主张账本、来源集中度、文体指纹、对话层检测。"""

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


pm = load("_persona_metrics_ut", ROOT / "scripts" / "persona_metrics.py")
registry = load("_source_registry_pm", ROOT / "scripts" / "source_registry.py")

CORPUS_A = "月有考，岁有稽，事可责成。\n"
CORPUS_B = "天下之事，不难于立法，而难于法之必行。不难于听言，而难于言之必效。\n"

SKILL = """---
name: demo-wisdom
format_version: 6
---

# 张居正的思维框架

**張居正** · 1525–1582

> 「天下之事，不难于立法」

## 核心原则

### 原则 1：考成责实

**理念：** 我主张月有考、岁有稽，事事责成。

**原文出处：**「月有考，岁有稽」——《请稽查章奏随事考成以修实政疏》

**决策规则：** 当政令推行不力时，应当立限考成。

### 原则 2：法之必行

**理念：** 我看重的不是立法，而是法之必行。

**原文出处：**「不难于立法，而难于法之必行」——《陈六事疏》

**决策规则：** 当新法出台时，应当先定执行与追责。

## 决策框架

```text
这件事有明确期限吗？
↓
有人对结果负责吗？
↓
能按月核查吗？
```

## 已知盲区与局限

1. **专权集权**：权力过度集中。*缓解：* 设独立复核。
2. **考成苛酷**：指标压人。*缓解：* 留出申辩通道。

## 标志性名言

- 「事可责成」——《请稽查章奏随事考成以修实政疏》
"""

EVIDENCE = """# 证据卡

### 原则 1：考成责实

> 月有考，岁有稽

- 出处：《请稽查章奏随事考成以修实政疏》
- 语料位置：`sources/demo/raw/a.txt`
- confidence：high

### 原则 2：法之必行

> 天下之事，不难于立法，而难于法之必行

- 出处：《陈六事疏》
- 语料位置：`sources/demo/raw/b.txt`
- confidence：high

### 原则 2：法之必行（补）

> 不难于听言，而难于言之必效

- 出处：《陈六事疏》
- confidence：medium

### 标志性名言

> 月有考，岁有稽，事可责成

- 出处：同上
- confidence：high
"""

VOICE = """# 语感样本库

### 样本 1（维度：句式）

> 月有考，岁有稽。

**为什么像他：** 斩截作结。

**误写成通用分析腔会变成：** 我们需要建立定期复盘机制，以确保各项工作能够有效推进。

### 样本 2（维度：修辞）

> 不难于立法，而难于法之必行。

**为什么像他：** 对举。

**误写成通用分析腔会变成：** 因此，制度设计固然重要，但是执行层面的问题同样值得关注。

### 样本 3（维度：语气）

> 这是我自己编的一句话。

**为什么像他：** 无。

**误写成通用分析腔会变成：** 首先要明确目标，其次要落实责任，最后要加强监督。
"""


class Workspace:
    def __init__(self, td: str):
        self.root = Path(td)
        self.raw = self.root / "sources" / "demo" / "raw"
        self.raw.mkdir(parents=True)
        (self.raw / "a.txt").write_text(CORPUS_A, encoding="utf-8")
        (self.raw / "b.txt").write_text(CORPUS_B, encoding="utf-8")
        self.out = self.root / "output" / "demo"
        (self.out / "references").mkdir(parents=True)
        self.write(SKILL, EVIDENCE, VOICE)

    def write(self, skill=None, evidence=None, voice=None):
        if skill is not None:
            (self.out / "SKILL.md").write_text(skill, encoding="utf-8")
        if evidence is not None:
            (self.out / "references" / "evidence.md").write_text(evidence, encoding="utf-8")
        if voice is not None:
            (self.out / "references" / "voice.md").write_text(voice, encoding="utf-8")

    def register(self):
        reg = registry.build_registry(self.raw)
        registry.write_registry(self.root / "sources" / "demo" / "processed" / "source_registry.json", reg)

    def measure(self, **kw):
        return pm.measure("demo", self.root, **kw)


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.ws = Workspace(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def test_parsers(self):
        principles = pm.parse_principles(SKILL)
        self.assertEqual([p["number"] for p in principles], ["1", "2"])
        self.assertEqual(principles[0]["quote"], "月有考，岁有稽")
        self.assertEqual(pm.parse_gates(SKILL), ["这件事有明确期限吗？", "有人对结果负责吗？", "能按月核查吗？"])
        self.assertEqual(pm.parse_blind_spots(SKILL), ["专权集权", "考成苛酷"])
        self.assertEqual(pm.person_names(SKILL), ["张居正", "張居正"])
        legacy = "---\nname: abraham-lincoln-wisdom\n---\n# Language Detection · 语言检测\n"
        self.assertEqual(pm.person_names(legacy), ["Abraham Lincoln"])
        card = "**張居正 (Zhang Juzheng), courtesy name Shuda** · 1525–1582\n"
        self.assertEqual(pm.person_names(card), ["張居正", "Zhang Juzheng"])
        samples = pm.parse_voice_samples(VOICE)
        self.assertEqual(samples[1]["dimension"], "修辞")
        self.assertTrue(samples[0]["anti"].startswith("我们需要"))

    def test_claims_bind_to_cards_files_and_registry(self):
        self.ws.register()
        ledger = self.ws.measure()["ledger"]
        claims = {c["claim_id"]: c for c in ledger["claims"]}
        self.assertEqual(claims["principle-1"]["corpus_files"], ["a.txt"])
        self.assertEqual(claims["principle-2"]["evidence"], ["evidence-2", "evidence-3"])
        self.assertEqual(claims["principle-2"]["corpus_files"], ["b.txt"])
        quotes = [c for c in ledger["claims"] if c["kind"] == "quote"]
        self.assertEqual({q["location"] for q in quotes}, {"epigraph", "原文出处", "标志性名言"})
        self.assertTrue(all(q["corpus_files"] for q in quotes))
        self.assertEqual(claims["voice-3"]["corpus_files"], [], "编造的语感样本追不到语料")
        self.assertEqual(claims["gate-1"]["basis"], "synthesis")
        self.assertEqual(claims["blind-spot-2"]["text"], "考成苛酷")
        self.assertTrue(ledger["sources"]["a.txt"]["source_id"].startswith("src_"))
        self.assertEqual(ledger["sources"]["b.txt"]["evidence_cards"], 2)

    def test_metrics_and_flags(self):
        metrics = self.ws.measure()["metrics"]["package"]
        self.assertEqual(metrics["principles"]["traced"], 2)
        self.assertEqual(metrics["voice"], {"total": 3, "traced": 2, "untraced": ["voice-3"]})
        self.assertEqual(metrics["cards"]["confidence"], {"high": 3, "medium": 1})
        codes = {f["code"] for f in metrics["flags"]}
        self.assertIn("SOURCE_NOT_REGISTERED", codes)  # 没有 registry
        self.assertNotIn("PRINCIPLE_UNTRACED", codes)
        self.assertIn("立法", metrics["anchor_terms"]["principle-2"][0] + "".join(metrics["anchor_terms"]["principle-2"]))
        self.ws.register()
        codes = {f["code"] for f in self.ws.measure()["metrics"]["package"]["flags"]}
        self.assertNotIn("SOURCE_NOT_REGISTERED", codes)

    def test_untraced_principle(self):
        self.ws.write(evidence=EVIDENCE.replace("> 月有考，岁有稽\n", "> 语料里没有的话\n", 1))
        flags = self.ws.measure()["metrics"]["package"]["flags"]
        self.assertIn({"code": "PRINCIPLE_UNTRACED", "detail": "principle-1"}, flags)

    def test_single_source_concentration(self):
        concentrated = EVIDENCE.replace("天下之事，不难于立法，而难于法之必行", "事可责成").replace(
            "不难于听言，而难于言之必效", "岁有稽，事可责成")
        self.ws.write(evidence=concentrated)
        pkg = self.ws.measure()["metrics"]["package"]
        self.assertEqual(pkg["source_concentration"]["top_share"], 1.0)
        self.assertIn("SINGLE_SOURCE_CONCENTRATION", {f["code"] for f in pkg["flags"]})

    def test_coverage_matrix(self):
        (self.ws.out / "references" / "cases.md").write_text(
            "### 案例 1（case_id: demo-c1-1）\n\n**对应原则簇：** cluster_001\n\n"
            "### 案例 2（case_id: demo-counter-1）\n\n**对应原则簇：** cluster_001\n\n**反例：** 苛察致怨\n",
            encoding="utf-8")
        coverage = self.ws.measure()["metrics"]["coverage"]
        self.assertEqual(coverage["clusters"]["cluster_001"], {"cases": 2, "counter_cases": 1})
        self.assertEqual(coverage["principles"][1]["cards"], 2)
        self.assertEqual(coverage["principles"][1]["best_confidence"], "high")


class StylometryTests(unittest.TestCase):
    CLASSICAL = "天下之事，不难于立法。而难于法之必行也。月有考，岁有稽。事可责成矣。不难于听言，而难于言之必效也。"
    MODERN = ("因此，我们需要建立一套完善的考核机制。首先要明确目标，其次要落实责任。"
              "但是执行层面同样重要。总之，制度与执行缺一不可。")

    def test_features(self):
        classical, modern = pm.stylometry(self.CLASSICAL), pm.stylometry(self.MODERN)
        self.assertGreater(classical["classical_per_k"], modern["classical_per_k"])
        self.assertGreater(modern["connective_per_k"], classical["connective_per_k"])
        self.assertIsNone(pm.stylometry("太短。"))

    def test_distance(self):
        a = pm.stylometry(self.CLASSICAL)
        self.assertEqual(pm.profile_distance(a, a), 0.0)
        self.assertGreater(pm.profile_distance(a, pm.stylometry(self.MODERN)), 0.3)


GOOD = ("我做事，先问期限。没有期限的事，等于没有这件事！当年推行考成法，许多人说苛刻，"
        "我不辩解，只看三个月后的账目。\n\n你要的不是更多会议，而是一个敢签字的人。谁签字，谁负责？\n\n"
        "这道理不新。新的是肯不肯真做。")


class DialogueTests(unittest.TestCase):
    def test_clean_answer_has_no_flags(self):
        result = pm.dialogue_metrics([{"prompt": "", "response": GOOD}], ["张居正"])
        self.assertEqual(result["flags"], [], result)

    def test_drift_ordinal_lecture_and_closing(self):
        bad = ("张居正认为，改革需要坚持。第一，要明确目标。第二，要落实责任。第三，要加强监督。"
               "你应该从小事做起。\n\n总之，坚持就是胜利。")
        result = pm.dialogue_metrics([{"prompt": "", "response": bad}] * 2 + [{"prompt": "", "response": GOOD}], ["张居正"])
        codes = {f["code"] for f in result["flags"]}
        self.assertTrue({"THIRD_PERSON_DRIFT", "ORDINAL_ENUMERATION", "SECOND_PERSON_LECTURING",
                         "CLOSING_REPETITION"} <= codes, codes)

    def test_uniform_structure_and_length_mismatch(self):
        uniform = "\n\n".join(["这是一个整齐的句子而已。这是一个整齐的句子而已。这是一个整齐的句子而已。"] * 4)
        result = pm.dialogue_metrics([{"prompt": "", "response": uniform}], [])
        codes = {f["code"] for f in result["flags"]}
        self.assertIn("UNIFORM_PARAGRAPHS", codes)
        self.assertIn("UNIFORM_SENTENCE_LENGTH", codes)
        result = pm.dialogue_metrics([{"prompt": "好吗？", "response": GOOD + "长" * 1300}], [])
        self.assertIn("LENGTH_MISMATCH", {f["code"] for f in result["flags"]})

    def test_load_formats(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            (base / "a.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in [
                {"role": "user", "content": "问"}, {"role": "assistant", "content": "答一"},
                {"role": "assistant", "content": "答二"}]), encoding="utf-8")
            self.assertEqual(pm.load_responses(base / "a.jsonl"),
                             [{"prompt": "问", "response": "答一"}, {"prompt": "", "response": "答二"}])
            (base / "b.json").write_text(json.dumps(["甲", "乙"], ensure_ascii=False), encoding="utf-8")
            self.assertEqual(len(pm.load_responses(base / "b.json")), 2)
            (base / "c.md").write_text("回答一\n---\n回答二\n\n---\n回答三", encoding="utf-8")
            self.assertEqual([p["response"] for p in pm.load_responses(base / "c.md")], ["回答一", "回答二", "回答三"])


class CliTests(unittest.TestCase):
    def test_write_json_and_fail_on_flags(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Workspace(td)
            dialogue = Path(td) / "d.md"
            dialogue.write_text(GOOD, encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = pm.main(["demo", "--root", td, "--write", "--json", "--dialogue", str(dialogue)])
            self.assertEqual(code, 0)
            data = json.loads(out.getvalue())
            self.assertEqual(data["schema"], "persona-metrics-v1")
            self.assertEqual(data["dialogue"]["turns"], 1)
            ledger = json.loads((ws.out / "claim_ledger.json").read_text(encoding="utf-8"))
            self.assertEqual(ledger["schema"], "claim-ledger-v1")
            self.assertTrue((ws.out / "persona_metrics.json").exists())
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(pm.main(["demo", "--root", td, "--fail-on-flags"]), 1)  # 未登记来源

    def test_markdown_render(self):
        with tempfile.TemporaryDirectory() as td:
            Workspace(td)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                pm.main(["demo", "--root", td])
            self.assertIn("| 原则可溯源 | 2/2 |", out.getvalue())
            self.assertIn("证据来源未登记", out.getvalue())


if __name__ == "__main__":
    unittest.main()
