# Skill Package v6 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把工厂产出从「单文件双语 SKILL.md」改造成「纯中文厚核心 + 三个按需附件 + 一份人读档案」，并新增确定性溯源闸门；英文版降级为按需生成的独立 skill。

**Architecture:** 新增 `scripts/verify_provenance.py`（纯函数溯源校验器）与 `validate_output.py` 的 `package` stage，二者构成六道规则式闸门。`SKILL.md` frontmatter 新增 `format_version: 6` 作为格式判别位——校验器见到它走 v6 纯中文路径，见不到就走今日的 legacy 双语路径，**存量 24 个 skill 的校验行为逐字节不变**。模板、代理、编排命令随之改写。

**Tech Stack:** Python 3.11+（stdlib 为主）、pytest 9.1.1 / unittest、Markdown 模板、Claude Code skill 加载器约定。可选依赖 `opencc-python-reimplemented`（繁简归一），缺失时降级为不折叠并发 WARNING。

**Spec:** `docs/superpowers/specs/2026-08-23-skill-package-v6-design.md`

## Global Constraints

以下是全局约束，每个任务的要求都隐含包含本节。数值逐字取自规格书。

- **只对新蒸馏生效。** 存量 24 个 skill 与 `gallery/` 不得被修改。任何改动若使 `python scripts/validate_output.py gallery <任一存量slug>` 的输出发生变化，即为回归。
- **格式判别位：** v6 包的 `SKILL.md` frontmatter 必须含 `format_version: 6`。无此字段一律按 legacy 双语格式校验。
- **`SKILL.md` 硬上限 500 行**，纯中文，不含 `## English` 区块，不含语言检测头。
- **原则数 9–11 条**（`min_principles: 8` / `max_principles: 11`），每条约 900 字。
- **description ≤300 字符**（沿用今日 `validate_output.py:607` 的既有闸门）。
- **附件目录固定为 `references/`**，只含 `cases.md`、`evidence.md`、`voice.md` 三个文件。
- **`人物档案.md` 不进安装目录**，只进 `output/{slug}/` 与 `gallery/{slug}/`。
- **逐字比对归一化 = 标点 + 空白 + 繁简三者均归一**（规格 §九）。
- **Windows/UTF-8 纪律：** 所有文件读写显式 `encoding="utf-8"`；脚本沿用 `validate_output.py:23-29` 的 Windows stdout 重配置模式。控制台 CJK 乱码是显示假象，判定一律以磁盘内容为准。
- **正则中的字面 `-` 必须转义或置于字符类末尾**，并用原始字符串 `r"..."`（原型阶段出现过 `SyntaxWarning: invalid escape sequence '\-'`）。
- **提交纪律：** 每个任务末尾提交一次，信息用 `feat:` / `test:` / `docs:` / `chore:` 前缀。

## 实测基线（供验收比对，勿重新猜测）

这些数字来自 2026-08-23 对 `zhang-juzheng` 与 21 个已安装 skill 的实测，是验收标准的比对基准：

| 指标 | 实测值 |
|---|---|
| 21 个 skill 平均恒载 | 19,682 tok（英文镜像占 48%） |
| `zhang-juzheng` 精选提取总量 | 152 条 / 17,029 字 |
| 出厂逐字引文 | 307 字 = **1.80%** |
| 出厂案例数 | **0** |
| **出厂 14 条引文的逐字校验结果** | **10 PASS / 4 FAIL**（Stage 5 的 LLM 评审报告为「7/7 EXACT」） |

**四条已确证的失败引文**（Task 9 的阳性对照，三种缺陷各不相同）：

| 出厂文本 | 语料实际文本 | 缺陷类型 | 最长逐字前缀 |
|---|---|---|---|
| 「如此则月有考，岁有稽，名必中实，事可责成」（principle1 与 quote2 同一句） | 「如此，月有考，岁有稽，**不惟使**声必中实，事可责成」 | 跨缺口缝合 | **3 / 17 字**（仅「如此则」，无锚点巧合命中） |
| 「…毋得彼此**推护**，徒**记空言**」（principle2） | 「…毋得彼此**推诿**，徒**托空言**」 | 字符讹误 | 21 / 26 字 |
| 「欲用一人，须慎之于始；既得其人，则信而任之」（quote4） | 「欲用一人须慎之于始**务求相应**既得其人则信而任之」 | 静默省略未加省略号 | 9 字 |

---

### Task 1: 溯源核心——归一化与逐字匹配

**Files:**
- Create: `scripts/verify_provenance.py`
- Create: `tests/test_provenance_core.py`
- Modify: `pyproject.toml:11-13`（新增 optional-dependencies）

**Interfaces:**
- Consumes: 无（本任务是基础层）
- Produces:
  - `normalize(text: str, fold_variants: bool = True) -> str`
  - `get_variant_folder() -> Callable[[str], str] | None`
  - `load_corpus(slug: str, root: Path) -> list[tuple[str, str]]` — 返回 `[(文件名, 归一化文本), ...]`
  - `find_verbatim(needle: str, corpus: list[tuple[str, str]]) -> str | None` — 命中返回文件名，否则 `None`
  - `longest_verbatim_prefix(needle: str, corpus: list[tuple[str, str]]) -> int`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_provenance_core.py`：

```python
from __future__ import annotations

import importlib.util
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


prov = load_module("verify_provenance", ROOT / "scripts" / "verify_provenance.py")


class NormalizeTests(unittest.TestCase):
    def test_strips_chinese_punctuation_and_whitespace(self) -> None:
        self.assertEqual(prov.normalize("如此，月有考，岁有稽。"), "如此月有考岁有稽")

    def test_strips_quote_marks_and_brackets(self) -> None:
        self.assertEqual(prov.normalize("「事可责成」——《陈六事疏》"), "事可责成陈六事疏")

    def test_strips_ascii_punctuation_and_newlines(self) -> None:
        self.assertEqual(prov.normalize("a, b.\n c;"), "abc")

    def test_is_idempotent(self) -> None:
        once = prov.normalize("如此，月有考。")
        self.assertEqual(prov.normalize(once), once)


class CorpusTests(unittest.TestCase):
    def test_load_corpus_reads_txt_files_and_normalizes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw = root / "sources" / "demo" / "raw"
            raw.mkdir(parents=True)
            (raw / "a.txt").write_text("如此，月有考，岁有稽。", encoding="utf-8")
            (raw / "ignore.pdf").write_bytes(b"%PDF-1.4 binary")
            corpus = prov.load_corpus("demo", root)
            self.assertEqual(len(corpus), 1)
            self.assertEqual(corpus[0][0], "a.txt")
            self.assertEqual(corpus[0][1], "如此月有考岁有稽")

    def test_find_verbatim_returns_filename_on_hit(self) -> None:
        corpus = [("a.txt", "如此月有考岁有稽不惟使声必中实事可责成")]
        self.assertEqual(prov.find_verbatim("月有考岁有稽", corpus), "a.txt")

    def test_find_verbatim_returns_none_on_stitched_quote(self) -> None:
        corpus = [("a.txt", "如此月有考岁有稽不惟使声必中实事可责成")]
        self.assertIsNone(prov.find_verbatim("如此则月有考岁有稽名必中实事可责成", corpus))

    def test_longest_verbatim_prefix_reports_divergence_point(self) -> None:
        corpus = [("a.txt", "毋得彼此推诿徒托空言")]
        self.assertEqual(prov.longest_verbatim_prefix("毋得彼此推护徒记空言", corpus), 5)

    def test_longest_verbatim_prefix_is_zero_when_nothing_matches(self) -> None:
        corpus = [("a.txt", "毋得彼此推诿")]
        self.assertEqual(prov.longest_verbatim_prefix("完全不相干的句子", corpus), 0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -X utf8 -m pytest tests/test_provenance_core.py -v
```

Expected: FAIL — 收集期报错，文件尚不存在（实际抛 `FileNotFoundError`；`load_module` 的 `RuntimeError` 只在 spec 为 None 时触发）

- [ ] **Step 3: 写最小实现**

创建 `scripts/verify_provenance.py`：

```python
#!/usr/bin/env python3
"""
Mind Distill Factory — 溯源校验器（确定性，不依赖 LLM 打分）

逐字比对出厂引文与语料，拦截缝合改写、字符讹误、静默省略三类缺陷。
规格：docs/superpowers/specs/2026-08-23-skill-package-v6-design.md §五
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Callable

# Windows 控制台 UTF-8（沿用 validate_output.py:23-29 的模式）
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

# 字面 '-' 置于字符类末尾，整体使用原始字符串
PUNCT_RE = re.compile(
    r"[\s，。、；：「」『』“”‘’（）()《》〈〉【】·,.;:!?…—　~～\"'’-]"
)

TEXT_SUFFIXES = (".txt", ".md")


def get_variant_folder() -> Callable[[str], str] | None:
    """返回繁→简转换函数；opencc 未安装时返回 None（降级为不折叠）。"""
    try:
        import opencc  # type: ignore
    except ImportError:
        return None
    converter = opencc.OpenCC("t2s")
    return converter.convert


_FOLDER = get_variant_folder()


def normalize(text: str, fold_variants: bool = True) -> str:
    """去标点、去空白，可选繁简归一。逐字比对前的唯一预处理。"""
    stripped = PUNCT_RE.sub("", text)
    if fold_variants and _FOLDER is not None:
        stripped = _FOLDER(stripped)
    return stripped


def load_corpus(slug: str, root: Path) -> list[tuple[str, str]]:
    """读取 sources/{slug}/raw/ 与 processed/ 下的文本文件，返回归一化后的语料。"""
    corpus: list[tuple[str, str]] = []
    for sub in ("raw", "processed"):
        base = root / "sources" / slug / sub
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            corpus.append((path.name, normalize(text)))
    return corpus


def find_verbatim(needle: str, corpus: list[tuple[str, str]]) -> str | None:
    """needle 逐字出现在某个语料文件中则返回该文件名，否则 None。"""
    probe = normalize(needle)
    if not probe:
        return None
    for filename, text in corpus:
        if probe in text:
            return filename
    return None


def longest_verbatim_prefix(needle: str, corpus: list[tuple[str, str]]) -> int:
    """返回 needle 归一化后能在语料中逐字命中的最长前缀长度，用于报告分歧位置。"""
    probe = normalize(needle)
    for length in range(len(probe), 0, -1):
        prefix = probe[:length]
        if any(prefix in text for _, text in corpus):
            return length
    return 0
```

- [ ] **Step 4: 运行测试确认通过**

```bash
python -X utf8 -m pytest tests/test_provenance_core.py -v
```

Expected: PASS — 9 passed（修复轮后为 11 条：另加 errors=replace 与 opencc 降级两条覆盖测试）

- [ ] **Step 5: 声明可选依赖**

修改 `pyproject.toml`，在 `dependencies = []`（第 11 行）之后插入：

```toml
[project.optional-dependencies]
provenance = ["opencc-python-reimplemented>=0.1.7"]
```

- [ ] **Step 6: 安装可选依赖并确认繁简折叠生效**

```bash
python -X utf8 -m pip install "opencc-python-reimplemented>=0.1.7"
```

再运行：

```bash
python -X utf8 -c "import sys; sys.path.insert(0,'scripts'); import verify_provenance as p; print(p.get_variant_folder() is not None); print(p.normalize('毋得彼此推諉'))"
```

Expected: `True` 然后 `毋得彼此推诿`（繁体输入被折叠为简体）

- [ ] **Step 7: 确认无 opencc 时降级不崩**

```bash
python -X utf8 -m pytest tests/test_provenance_core.py -v
```

Expected: PASS（测试全部使用简体，折叠与否结果相同——这正是降级安全的证明）

- [ ] **Step 8: 提交**

```bash
git add scripts/verify_provenance.py tests/test_provenance_core.py pyproject.toml && git commit -m "feat: add provenance normalizer and verbatim matcher"
```

---

### Task 2: 证据卡解析与 P1/P2 闸门

**Files:**
- Modify: `scripts/verify_provenance.py`（在 Task 1 的函数之后追加）
- Modify: `tests/test_provenance_core.py`（追加测试类）

**Interfaces:**
- Consumes: Task 1 的 `normalize`、`load_corpus`、`find_verbatim`、`longest_verbatim_prefix`
- Produces:
  - `parse_evidence_cards(text: str) -> list[dict]` — 每张卡 `{"title": str, "verbatim": str, "fields": dict[str, str]}`
  - `extract_skill_quotes(text: str) -> list[tuple[str, str]]` — `[(来源标签, 引文), ...]`
  - `check_p1_quote_closure(skill_md: Path, evidence_md: Path) -> list[str]`
  - `check_p2_corpus_closure(evidence_md: Path, slug: str, root: Path) -> list[str]`

**证据卡格式契约**（Task 5 的模板必须产出此形状）：

```markdown
### 原则 1：立限考成

> 如此，月有考，岁有稽，不惟使声必中实，事可责成

- 出处：《请稽查章奏随事考成以修实政疏》（万历元年）
- 语料位置：`sources/zhang-juzheng/raw/张居正全集.txt`
- confidence：high
- 现代转译：任何政令都要定期限、立台账、指定到期被追责的人
```

`textual_note：` 为可选字段；带该字段的卡片 P2 失败时降级为 WARNING 而非 error。

**SKILL.md 引文提取契约**（只从两处结构化位置取，避免把强调用的「」误判为引文）：
1. 以 `**原文出处：**` 开头的行 → 取其中第一对 `「」` 的内容
2. `## 标志性名言` 章节内的列表项或表格行 → 取每行第一对 `「」` 的内容

- [ ] **Step 1: 写失败测试**

在 `tests/test_provenance_core.py` 末尾（`if __name__` 之前）追加：

```python
class EvidenceParseTests(unittest.TestCase):
    CARD = (
        "# 证据卡\n\n"
        "### 原则 1：立限考成\n\n"
        "> 如此，月有考，岁有稽，不惟使声必中实，事可责成\n\n"
        "- 出处：《请稽查章奏随事考成以修实政疏》（万历元年）\n"
        "- confidence：high\n\n"
        "### 原则 2：尚实黜虚\n\n"
        "> 毋得彼此推诿，徒托空言\n\n"
        "- 出处：《陈六事疏·省议论》\n"
        "- confidence：high\n"
        "- textual_note：底本作「推护」，据全集本正为「推诿」\n"
    )

    def test_parses_two_cards(self) -> None:
        cards = prov.parse_evidence_cards(self.CARD)
        self.assertEqual(len(cards), 2)
        self.assertEqual(cards[0]["title"], "原则 1：立限考成")

    def test_captures_blockquote_as_verbatim(self) -> None:
        cards = prov.parse_evidence_cards(self.CARD)
        self.assertEqual(cards[0]["verbatim"], "如此，月有考，岁有稽，不惟使声必中实，事可责成")

    def test_captures_fields(self) -> None:
        cards = prov.parse_evidence_cards(self.CARD)
        self.assertEqual(cards[0]["fields"]["confidence"], "high")

    def test_detects_textual_note(self) -> None:
        cards = prov.parse_evidence_cards(self.CARD)
        self.assertNotIn("textual_note", cards[0]["fields"])
        self.assertIn("textual_note", cards[1]["fields"])


class SkillQuoteExtractionTests(unittest.TestCase):
    SKILL = (
        "## 核心原则\n\n"
        "#### 原则 1：立限考成\n\n"
        "**理念：** 我见章奏堆积如山，「空文」二字最误国。\n\n"
        "**原文出处：**「如此，月有考，岁有稽」——《请稽查章奏疏》\n\n"
        "## 标志性名言\n\n"
        "- 「毋得彼此推诿，徒托空言」——《陈六事疏》\n"
    )

    def test_extracts_principle_source_quote(self) -> None:
        quotes = prov.extract_skill_quotes(self.SKILL)
        self.assertIn("如此，月有考，岁有稽", [q for _, q in quotes])

    def test_extracts_signature_quote(self) -> None:
        quotes = prov.extract_skill_quotes(self.SKILL)
        self.assertIn("毋得彼此推诿，徒托空言", [q for _, q in quotes])

    def test_ignores_emphasis_brackets_in_prose(self) -> None:
        quotes = prov.extract_skill_quotes(self.SKILL)
        self.assertNotIn("空文", [q for _, q in quotes])


class GateTests(unittest.TestCase):
    def _write(self, root: Path, skill: str, evidence: str, corpus: str) -> None:
        out = root / "output" / "demo"
        out.mkdir(parents=True)
        (out / "SKILL.md").write_text(skill, encoding="utf-8")
        refs = out / "references"
        refs.mkdir()
        (refs / "evidence.md").write_text(evidence, encoding="utf-8")
        raw = root / "sources" / "demo" / "raw"
        raw.mkdir(parents=True)
        (raw / "corpus.txt").write_text(corpus, encoding="utf-8")

    def test_p1_passes_when_quote_is_in_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write(
                root,
                "**原文出处：**「如此，月有考，岁有稽」——《疏》\n",
                "### 原则 1：甲\n\n> 如此，月有考，岁有稽\n\n- confidence：high\n",
                "如此，月有考，岁有稽，不惟使声必中实。",
            )
            errors = prov.check_p1_quote_closure(
                root / "output" / "demo" / "SKILL.md",
                root / "output" / "demo" / "references" / "evidence.md",
            )
            self.assertEqual(errors, [])

    def test_p1_fails_when_quote_missing_from_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write(
                root,
                "**原文出处：**「如此则月有考，名必中实」——《疏》\n",
                "### 原则 1：甲\n\n> 如此，月有考，岁有稽\n\n- confidence：high\n",
                "如此，月有考，岁有稽。",
            )
            errors = prov.check_p1_quote_closure(
                root / "output" / "demo" / "SKILL.md",
                root / "output" / "demo" / "references" / "evidence.md",
            )
            self.assertEqual(len(errors), 1)
            self.assertTrue(errors[0].startswith("P1_QUOTE_NOT_IN_EVIDENCE"))

    def test_p2_fails_on_stitched_quote_and_reports_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write(
                root,
                "**原文出处：**「甲」——《疏》\n",
                "### 原则 1：甲\n\n> 如此则月有考，岁有稽，名必中实，事可责成\n\n- confidence：high\n",
                "如此，月有考，岁有稽，不惟使声必中实，事可责成。",
            )
            errors = prov.check_p2_corpus_closure(
                root / "output" / "demo" / "references" / "evidence.md", "demo", root
            )
            self.assertEqual(len(errors), 1)
            self.assertTrue(errors[0].startswith("P2_NOT_IN_CORPUS"))
            # 2 而非 0：longest_verbatim_prefix 无锚点，「如此」两字在语料开头巧合命中
            self.assertIn("最长逐字前缀=2", errors[0])

    def test_p2_downgrades_to_warning_when_textual_note_present(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write(
                root,
                "**原文出处：**「甲」——《疏》\n",
                "### 原则 1：甲\n\n> 如此则月有考\n\n"
                "- confidence：high\n- textual_note：底本讹字，据received text 正之\n",
                "如此，月有考。",
            )
            errors = prov.check_p2_corpus_closure(
                root / "output" / "demo" / "references" / "evidence.md", "demo", root
            )
            self.assertEqual(len(errors), 1)
            self.assertTrue(errors[0].startswith("WARNING:"))

    def test_p2_passes_when_verbatim(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write(
                root,
                "**原文出处：**「甲」——《疏》\n",
                "### 原则 1：甲\n\n> 月有考，岁有稽\n\n- confidence：high\n",
                "如此，月有考，岁有稽，不惟使声必中实。",
            )
            errors = prov.check_p2_corpus_closure(
                root / "output" / "demo" / "references" / "evidence.md", "demo", root
            )
            self.assertEqual(errors, [])
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -X utf8 -m pytest tests/test_provenance_core.py -v -k "EvidenceParse or SkillQuote or Gate"
```

Expected: FAIL — `AttributeError: module 'verify_provenance' has no attribute 'parse_evidence_cards'`

- [ ] **Step 3: 写最小实现**

在 `scripts/verify_provenance.py` 的 `longest_verbatim_prefix` 之后追加：

```python
# ── 证据卡解析 ──────────────────────────────────────────────────────

CARD_SPLIT_RE = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)
FIELD_RE = re.compile(r"^-\s*([A-Za-z_]+|出处|语料位置|现代转译)\s*[：:]\s*(.+?)\s*$", re.MULTILINE)
BLOCKQUOTE_RE = re.compile(r"^>\s?(.*?)\s*$", re.MULTILINE)


def parse_evidence_cards(text: str) -> list[dict]:
    """把 evidence.md 解析成卡片列表。每张卡的引文取其 blockquote 内容。"""
    cards: list[dict] = []
    matches = list(CARD_SPLIT_RE.finditer(text))
    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end]
        quote_lines = [m.group(1) for m in BLOCKQUOTE_RE.finditer(body) if m.group(1)]
        fields = {m.group(1): m.group(2) for m in FIELD_RE.finditer(body)}
        cards.append({
            "title": match.group(1),
            "verbatim": "\n".join(quote_lines).strip(),
            "fields": fields,
        })
    return cards


# ── SKILL.md 引文提取 ───────────────────────────────────────────────

BRACKET_QUOTE_RE = re.compile(r"「([^」]+)」")
SOURCE_LINE_RE = re.compile(r"^\*\*原文出处：\*\*(.*)$", re.MULTILINE)
QUOTES_SECTION_RE = re.compile(r"^##\s*标志性名言\s*$(.*?)(?=^##\s|\Z)", re.MULTILINE | re.DOTALL)


def extract_skill_quotes(text: str) -> list[tuple[str, str]]:
    """只从两处结构化位置提取引文：原文出处行、标志性名言章节。"""
    found: list[tuple[str, str]] = []
    for match in SOURCE_LINE_RE.finditer(text):
        inner = BRACKET_QUOTE_RE.search(match.group(1))
        if inner:
            found.append(("原文出处", inner.group(1)))
    section = QUOTES_SECTION_RE.search(text)
    if section:
        for line in section.group(1).splitlines():
            stripped = line.strip()
            if not stripped.startswith(("-", "*", "|")):
                continue
            inner = BRACKET_QUOTE_RE.search(stripped)
            if inner:
                found.append(("标志性名言", inner.group(1)))
    return found


# ── P1 / P2 闸门 ────────────────────────────────────────────────────

def check_p1_quote_closure(skill_md: Path, evidence_md: Path) -> list[str]:
    """P1：SKILL.md 中每条引文必须逐字出现在 evidence.md 的某张卡里。"""
    if not skill_md.exists():
        return [f"MISSING: {skill_md}"]
    if not evidence_md.exists():
        return [f"MISSING: {evidence_md}"]
    cards = parse_evidence_cards(evidence_md.read_text(encoding="utf-8"))
    haystack = [normalize(card["verbatim"]) for card in cards]
    errors: list[str] = []
    for label, quote in extract_skill_quotes(skill_md.read_text(encoding="utf-8")):
        probe = normalize(quote)
        if not probe:
            continue
        if not any(probe in card_text for card_text in haystack):
            errors.append(
                f"P1_QUOTE_NOT_IN_EVIDENCE: {skill_md} [{label}]: 「{quote}」"
                f" 未逐字出现在 {evidence_md.name}"
            )
    return errors


def check_p2_corpus_closure(evidence_md: Path, slug: str, root: Path) -> list[str]:
    """P2：evidence.md 中每条逐字原文必须逐字出现在语料中。"""
    if not evidence_md.exists():
        return [f"MISSING: {evidence_md}"]
    corpus = load_corpus(slug, root)
    if not corpus:
        return [f"EMPTY_CORPUS: sources/{slug}/ 下没有可读的 .txt/.md 语料"]
    errors: list[str] = []
    for card in parse_evidence_cards(evidence_md.read_text(encoding="utf-8")):
        verbatim = card["verbatim"]
        if not normalize(verbatim):
            continue
        if find_verbatim(verbatim, corpus):
            continue
        prefix = longest_verbatim_prefix(verbatim, corpus)
        message = (
            f"P2_NOT_IN_CORPUS: {evidence_md.name} [{card['title']}]: "
            f"「{verbatim[:32]}」未逐字出现在语料中（最长逐字前缀={prefix}字）"
        )
        if "textual_note" in card["fields"]:
            errors.append(f"WARNING: {message} — 已记 textual_note，人工裁决在案")
        else:
            errors.append(message)
    return errors
```

- [ ] **Step 4: 运行测试确认通过**

```bash
python -X utf8 -m pytest tests/test_provenance_core.py -v
```

Expected: PASS — 23 passed（Task 1 的 11 条 + 本任务新增 12 条）

- [ ] **Step 5: 提交**

```bash
git add scripts/verify_provenance.py tests/test_provenance_core.py && git commit -m "feat: add P1 quote-closure and P2 corpus-closure gates"
```

> **修复轮已应用（commit `02fe867`）——重跑本任务时请连同下列改动一并实现：**
> 1. `QUOTES_SECTION_RE` 改为容忍标题漂移：`r"^##(?!#)[^
]*标志性名言[^
]*$(.*?)(?=^##\s|\Z)"`
>    （`(?!#)` 排除 `###`；`[^
]*` 而非 `.*`，避免在 DOTALL 下越过行尾）。
> 2. `check_p1_quote_closure` 增加失败关闭守卫：统计 `**原文出处：**` 标记数，与
>    `extract_skill_quotes` 实际收获的 `原文出处` 类引文数比较，短缺者按
>    `P1_UNPARSEABLE_CITATION` 报错（附 ≤80 字定位片段）。**不得**改动两个函数的签名。
> 3. 新增 3 条测试：`test_p1_fails_on_citation_quote_that_wraps_to_next_line`、
>    `test_extract_skill_quotes_tolerates_heading_drift`、`test_p2_reports_empty_corpus_distinctly`。
>    本任务最终为 **26 passed**，非 23。
>
> 理由：原实现在引文跨行、或标题写成「标志性名言与佳句」时**静默返回空列表**，闸门报 PASS——
> 对溯源校验器而言只会制造**假通过**。已在真实产物上验证：该守卫正确拦下了一份用 ASCII 引号
> 而非 `「」` 的 SKILL.md 的 11 处引文。

---

### Task 3: 包结构闸门 P3–P6 与 `package` stage

**Files:**
- Modify: `scripts/validate_output.py:34-84`（新增 `PACKAGE_SCHEMA`）、`scripts/validate_output.py:665-672`（`STAGES`）、文件末尾新增 `validate_package`
- Modify: `scripts/validate_output.py:6-13`（docstring 的 Stages 列表）
- Modify: `config/defaults.json`
- Create: `tests/test_package_v6.py`

**Interfaces:**
- Consumes: Task 2 的 `check_p1_quote_closure`、`check_p2_corpus_closure`
- Produces:
  - `validate_package(slug: str) -> list[str]` — 注册进 `STAGES["package"]`
  - `PACKAGE_SCHEMA` 常量：`{"skill_max_lines": 500, "required_refs": [...], "min_cases_per_cluster": 2, "min_counter_cases": 1, "core_sections": [...]}`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_package_v6.py`：

```python
from __future__ import annotations

import importlib.util
import json
import os
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


validator = load_module("validate_output", ROOT / "scripts" / "validate_output.py")

CORE_SECTIONS = [
    "身份卡", "响应策略", "核心原则", "决策框架",
    "已知盲区", "表达风格 DNA", "价值取向与反模式", "溯源",
]


def build_skill_md(sections=None, extra="") -> str:
    sections = CORE_SECTIONS if sections is None else sections
    body = "\n\n".join(f"## {name}\n\n内容占位，非空。" for name in sections)
    return (
        "---\n"
        "name: demo-wisdom\n"
        "format_version: 6\n"
        "description: 运用示例人物的框架处理决策问题。触发：示例。\n"
        "---\n\n"
        "# 示例人物的思维框架\n\n"
        f"{body}\n\n{extra}\n"
    )


class PackageFixture:
    """在临时目录里搭一个最小 v6 包，供各闸门测试复用。"""

    def __init__(self, td: str):
        self.root = Path(td)
        self.out = self.root / "output" / "demo"
        self.refs = self.out / "references"
        self.refs.mkdir(parents=True)
        raw = self.root / "sources" / "demo" / "raw"
        raw.mkdir(parents=True)
        (raw / "corpus.txt").write_text("月有考，岁有稽，事可责成。", encoding="utf-8")
        self.write_skill(build_skill_md())
        self.write_ref("evidence.md", "### 原则 1：甲\n\n> 月有考，岁有稽\n\n- confidence：high\n")
        self.write_ref("voice.md", "### 样本 1（维度：句式）\n\n> 示例\n")
        self.write_cases(clusters=1, counter=True)

    def write_skill(self, text: str) -> None:
        (self.out / "SKILL.md").write_text(text, encoding="utf-8")

    def write_ref(self, name: str, text: str) -> None:
        (self.refs / name).write_text(text, encoding="utf-8")

    def write_cases(self, clusters: int, counter: bool) -> None:
        blocks = []
        for c in range(1, clusters + 1):
            for n in range(1, 3):
                blocks.append(
                    f"### 案例 {c}-{n}：示例（case_id: demo-c{c}-{n}，high）\n\n"
                    f"**对应原则簇：** cluster_{c:03d}\n\n**情境：** 略。\n"
                )
        if counter:
            blocks.append(
                "### 案例 X：反例（case_id: demo-counter-1，high）\n\n"
                "**对应原则簇：** cluster_001\n\n**反例：** 此处判断失误。\n"
            )
        self.write_ref("cases.md", "\n\n".join(blocks))


class P3PathResolutionTests(unittest.TestCase):
    def test_passes_when_all_backtick_paths_resolve(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = PackageFixture(td)
            fx.write_skill(build_skill_md(extra="详见 `references/cases.md`。"))
            errors = validator.check_p3_paths(fx.out / "SKILL.md")
            self.assertEqual(errors, [])

    def test_fails_on_dangling_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = PackageFixture(td)
            fx.write_skill(build_skill_md(extra="详见 `references/nope.md`。"))
            errors = validator.check_p3_paths(fx.out / "SKILL.md")
            self.assertEqual(len(errors), 1)
            self.assertTrue(errors[0].startswith("P3_DANGLING_PATH"))


class P4CaseCoverageTests(unittest.TestCase):
    def test_passes_with_two_cases_per_cluster_and_a_counter_case(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = PackageFixture(td)
            errors = validator.check_p4_cases(fx.refs / "cases.md", ["cluster_001"])
            self.assertEqual(errors, [])

    def test_fails_when_cluster_has_one_case(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = PackageFixture(td)
            # cluster_001 有 2 例（达标），cluster_002 只有 1 例（不达标）
            fx.write_ref(
                "cases.md",
                "### 案例 1：甲（case_id: demo-a-1，high）\n\n"
                "**对应原则簇：** cluster_001\n\n**情境：** 略。\n\n"
                "### 案例 2：乙（case_id: demo-b-1，high）\n\n"
                "**对应原则簇：** cluster_001\n\n**情境：** 略。\n\n"
                "### 案例 X：反例（case_id: demo-counter-1，high）\n\n"
                "**对应原则簇：** cluster_002\n\n**反例：** 略。\n",
            )
            errors = validator.check_p4_cases(
                fx.refs / "cases.md", ["cluster_001", "cluster_002"]
            )
            self.assertTrue(any(e.startswith("P4_TOO_FEW_CASES") for e in errors))
            self.assertTrue(any("cluster_002" in e for e in errors))
            self.assertFalse(any("cluster_001" in e for e in errors))

    def test_fails_when_no_counter_case(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = PackageFixture(td)
            fx.write_cases(clusters=1, counter=False)
            errors = validator.check_p4_cases(fx.refs / "cases.md", ["cluster_001"])
            self.assertTrue(any(e.startswith("P4_NO_COUNTER_CASE") for e in errors))


class P5IndexConsistencyTests(unittest.TestCase):
    def test_passes_when_index_matches_case_ids(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = PackageFixture(td)
            index = (
                "## 案例索引\n\n"
                "| 案例 | 触发情境 | case_id |\n|---|---|---|\n"
                "| 示例 | 情境甲 | demo-c1-1 |\n"
                "| 示例 | 情境乙 | demo-c1-2 |\n"
                "| 反例 | 情境丙 | demo-counter-1 |\n"
            )
            fx.write_skill(build_skill_md(extra=index))
            errors = validator.check_p5_index(fx.out / "SKILL.md", fx.refs / "cases.md")
            self.assertEqual(errors, [])

    def test_fails_when_index_references_unknown_case_id(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = PackageFixture(td)
            index = (
                "## 案例索引\n\n"
                "| 案例 | 触发情境 | case_id |\n|---|---|---|\n"
                "| 幽灵 | 情境甲 | demo-ghost-9 |\n"
            )
            fx.write_skill(build_skill_md(extra=index))
            errors = validator.check_p5_index(fx.out / "SKILL.md", fx.refs / "cases.md")
            self.assertTrue(any(e.startswith("P5_INDEX_ORPHAN") for e in errors))

    def test_fails_when_case_is_not_indexed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = PackageFixture(td)
            index = (
                "## 案例索引\n\n"
                "| 案例 | 触发情境 | case_id |\n|---|---|---|\n"
                "| 示例 | 情境甲 | demo-c1-1 |\n"
            )
            fx.write_skill(build_skill_md(extra=index))
            errors = validator.check_p5_index(fx.out / "SKILL.md", fx.refs / "cases.md")
            self.assertTrue(any(e.startswith("P5_CASE_NOT_INDEXED") for e in errors))


class P6CoreSelfSufficiencyTests(unittest.TestCase):
    def test_passes_with_all_eight_sections_under_line_cap(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = PackageFixture(td)
            errors = validator.check_p6_core(fx.out / "SKILL.md")
            self.assertEqual(errors, [])

    def test_fails_when_a_core_section_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = PackageFixture(td)
            fx.write_skill(build_skill_md(sections=CORE_SECTIONS[:-1]))
            errors = validator.check_p6_core(fx.out / "SKILL.md")
            self.assertTrue(any(e.startswith("P6_MISSING_SECTION") for e in errors))

    def test_fails_when_a_core_section_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = PackageFixture(td)
            body = "\n\n".join(
                f"## {name}\n" + ("" if name == "溯源" else "\n内容占位，非空。")
                for name in CORE_SECTIONS
            )
            fx.write_skill(
                "---\nname: demo-wisdom\nformat_version: 6\n"
                "description: 示例。触发：示例。\n---\n\n# 标题\n\n" + body + "\n"
            )
            errors = validator.check_p6_core(fx.out / "SKILL.md")
            self.assertTrue(any(e.startswith("P6_EMPTY_SECTION") for e in errors))

    def test_fails_over_line_cap(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = PackageFixture(td)
            fx.write_skill(build_skill_md(extra="填充行\n" * 600))
            errors = validator.check_p6_core(fx.out / "SKILL.md")
            self.assertTrue(any(e.startswith("P6_TOO_LONG") for e in errors))


class PackageStageTests(unittest.TestCase):
    def test_package_stage_is_registered(self) -> None:
        self.assertIn("package", validator.STAGES)

    def test_validate_package_reports_missing_reference_file(self) -> None:
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as td:
            try:
                fx = PackageFixture(td)
                (fx.refs / "voice.md").unlink()
                os.chdir(fx.root)
                errors = validator.validate_package("demo")
            finally:
                os.chdir(cwd)
            self.assertTrue(any("voice.md" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -X utf8 -m pytest tests/test_package_v6.py -v
```

Expected: FAIL — `AttributeError: module 'validate_output' has no attribute 'check_p3_paths'`

- [ ] **Step 3: 新增 PACKAGE_SCHEMA 常量**

在 `scripts/validate_output.py` 的 `FRAMEWORK_CORE_SCHEMA`（第 77-84 行）之后插入：

```python
> ⚠️ **同时必须让 `FRAMEWORK_SCHEMA` 的原则数上下界随格式变化。** 它今天硬编码
> `min_principles: 5, max_principles: 8`，而 v6 要求 9–11——若不改，一份合规的 v6 框架会被
> `frameworks` stage 以 `TOO_MANY_PRINCIPLES` 拒绝。**注意 `validate_output.py` 从不读
> `config/defaults.json`**，所以把 8/11 写进 defaults.json 不会产生任何效果（这正是本计划最初
> 犯的错）。做法：`frameworks.zh.json` 顶层带 `"format_version": 6` 时用 8–11，缺失时保持 5–8
> 原样，legacy 行为逐字节不变。上界取 11 是算出来的：12 条 × ~900 字会突破 P6 的 500 行硬闸门。

PACKAGE_SCHEMA = {
    "skill_max_lines": 500,
    "reference_dir": "references",
    "required_refs": ["cases.md", "evidence.md", "voice.md"],
    "min_cases_per_cluster": 2,
    "min_counter_cases": 1,
    "core_sections": ["身份卡", "响应策略", "核心原则", "决策框架",
                      "已知盲区", "表达风格 DNA", "价值取向与反模式", "溯源"],
    "format_version": 6,
}
```

- [ ] **Step 4: 实现 P3–P6 与 validate_package**

在 `scripts/validate_output.py` 的 `validate_gallery` 之后、`_validate_merged_skill` 之前插入：

```python
# ── v6 包闸门（P3–P6）────────────────────────────────────────────────

BACKTICK_PATH_RE = re.compile(r"`([A-Za-z0-9_./-]+\.(?:md|json|py|txt))`")
CASE_ID_RE = re.compile(r"case_id:\s*([A-Za-z0-9_-]+)")
CASE_CLUSTER_RE = re.compile(r"^\*\*对应原则簇：\*\*\s*(\S+)\s*$", re.MULTILINE)
CASE_HEADING_RE = re.compile(r"^###\s+.*$", re.MULTILINE)


def check_p3_paths(skill_md: Path) -> list[str]:
    """P3：SKILL.md 中每个反引号路径必须解析到实际文件。"""
    if not skill_md.exists():
        return [f"MISSING: {skill_md}"]
    base = skill_md.parent
    errors = []
    for match in BACKTICK_PATH_RE.finditer(skill_md.read_text(encoding="utf-8")):
        rel = match.group(1)
        if (base / rel).exists() or Path(rel).exists():
            continue
        errors.append(f"P3_DANGLING_PATH: {skill_md}: `{rel}` 无法解析到实际文件")
    return errors


def _parse_cases(cases_md: Path) -> list[dict]:
    text = cases_md.read_text(encoding="utf-8")
    headings = list(CASE_HEADING_RE.finditer(text))
    cases = []
    for i, match in enumerate(headings):
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        block = text[match.start():end]
        case_id = CASE_ID_RE.search(block)
        cluster = CASE_CLUSTER_RE.search(block)
        cases.append({
            "case_id": case_id.group(1) if case_id else None,
            "cluster": cluster.group(1) if cluster else None,
            "is_counter": "反例" in block,
        })
    return cases


def check_p4_cases(cases_md: Path, cluster_ids: list[str]) -> list[str]:
    """P4：每个 principle cluster ≥2 例；全库 ≥1 反例。"""
    if not cases_md.exists():
        return [f"MISSING: {cases_md}"]
    cases = _parse_cases(cases_md)
    errors = []
    for case in cases:
        if not case["case_id"]:
            errors.append(f"P4_MISSING_CASE_ID: {cases_md}: 存在无 case_id 的案例")
    for cluster_id in cluster_ids:
        count = sum(1 for c in cases if c["cluster"] == cluster_id)
        if count < PACKAGE_SCHEMA["min_cases_per_cluster"]:
            errors.append(
                f"P4_TOO_FEW_CASES: {cases_md}: cluster '{cluster_id}' 只有 {count} 例 "
                f"< {PACKAGE_SCHEMA['min_cases_per_cluster']}"
            )
    counters = sum(1 for c in cases if c["is_counter"])
    if counters < PACKAGE_SCHEMA["min_counter_cases"]:
        errors.append(f"P4_NO_COUNTER_CASE: {cases_md}: 全库反例数 {counters} < 1")
    return errors


def check_p5_index(skill_md: Path, cases_md: Path) -> list[str]:
    """P5：SKILL.md 案例索引与 cases.md 的 case_id 必须双向一一对应。"""
    if not skill_md.exists():
        return [f"MISSING: {skill_md}"]
    if not cases_md.exists():
        return [f"MISSING: {cases_md}"]
    indexed = set(CASE_ID_RE.findall(skill_md.read_text(encoding="utf-8")))
    section = re.search(
        r"^##\s*案例索引\s*$(.*?)(?=^##\s|\Z)",
        skill_md.read_text(encoding="utf-8"),
        re.MULTILINE | re.DOTALL,
    )
    if section:
        for line in section.group(1).splitlines():
            if line.strip().startswith("|"):
                for cell in line.split("|"):
                    token = cell.strip()
                    if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)+", token):
                        indexed.add(token)
    actual = {c["case_id"] for c in _parse_cases(cases_md) if c["case_id"]}
    errors = []
    for orphan in sorted(indexed - actual):
        errors.append(f"P5_INDEX_ORPHAN: {skill_md}: 索引引用了不存在的 case_id '{orphan}'")
    for missing in sorted(actual - indexed):
        errors.append(f"P5_CASE_NOT_INDEXED: {cases_md}: case_id '{missing}' 未出现在案例索引中")
    return errors


def check_p6_core(skill_md: Path) -> list[str]:
    """P6：核心自足——≤500 行，8 个必需章节齐备且非空（不检查指针，那是 P3 的事）。"""
    if not skill_md.exists():
        return [f"MISSING: {skill_md}"]
    content = skill_md.read_text(encoding="utf-8")
    errors = []
    line_count = len(content.splitlines())
    if line_count > PACKAGE_SCHEMA["skill_max_lines"]:
        errors.append(
            f"P6_TOO_LONG: {skill_md}: {line_count} 行 > "
            f"{PACKAGE_SCHEMA['skill_max_lines']} 行上限"
        )
    headings = list(re.finditer(r"^#{2,4}\s*(.+?)\s*$", content, re.MULTILINE))
    for name in PACKAGE_SCHEMA["core_sections"]:
        hit = None
        for i, match in enumerate(headings):
            if name in match.group(1):
                end = headings[i + 1].start() if i + 1 < len(headings) else len(content)
                hit = content[match.end():end].strip()
                break
        if hit is None:
            errors.append(f"P6_MISSING_SECTION: {skill_md}: 缺少必需章节 '{name}'")
        elif not hit:
            errors.append(f"P6_EMPTY_SECTION: {skill_md}: 章节 '{name}' 为空")
    return errors


def validate_package(slug: str) -> list[str]:
    """v6 包整体校验：结构 + P1–P6 六道闸门。"""
    root = Path(".")
    output_dir = root / "output" / slug
    skill_md = output_dir / "SKILL.md"
    refs_dir = output_dir / PACKAGE_SCHEMA["reference_dir"]
    errors: list[str] = []

    if not skill_md.exists():
        return [f"MISSING: {skill_md}"]

    content = skill_md.read_text(encoding="utf-8")
    if f"format_version: {PACKAGE_SCHEMA['format_version']}" not in content:
        errors.append(
            f"NOT_V6: {skill_md}: frontmatter 缺少 "
            f"'format_version: {PACKAGE_SCHEMA['format_version']}'"
        )
    if re.search(r"^##\s+English", content, re.MULTILINE):
        errors.append(f"V6_HAS_ENGLISH_BLOCK: {skill_md}: v6 包不得含 '## English' 区块")

    for name in PACKAGE_SCHEMA["required_refs"]:
        if not (refs_dir / name).exists():
            errors.append(f"MISSING: {refs_dir / name}")

    errors.extend(check_p3_paths(skill_md))
    errors.extend(check_p6_core(skill_md))

    cases_md = refs_dir / "cases.md"
    evidence_md = refs_dir / "evidence.md"

    cluster_ids: list[str] = []
    core_file = output_dir / "framework_core.json"
    if core_file.exists():
        try:
            core = read_json_file(core_file)
            cluster_ids = [
                c.get("cluster_id") for c in core.get("principle_clusters", [])
                if c.get("cluster_id")
            ]
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            errors.append(f"PARSE_ERROR: {core_file}: {e}")

    if cases_md.exists():
        errors.extend(check_p4_cases(cases_md, cluster_ids))
        errors.extend(check_p5_index(skill_md, cases_md))

    if evidence_md.exists():
        prov = _load_provenance()
        errors.extend(prov.check_p1_quote_closure(skill_md, evidence_md))
        errors.extend(prov.check_p2_corpus_closure(evidence_md, slug, root))

    return errors


def _load_provenance():
    """按路径加载同目录的 verify_provenance 模块（scripts/ 不是包）。"""
    import importlib.util
    path = Path(__file__).resolve().parent / "verify_provenance.py"
    spec = importlib.util.spec_from_file_location("verify_provenance", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
```

- [ ] **Step 5: 注册 stage 并更新 docstring**

把 `scripts/validate_output.py:665-672` 的 `STAGES` 改为：

```python
STAGES = {
    "sources": validate_sources,
    "principles": validate_principles,
    "frameworks": validate_frameworks,
    "skill": validate_skill,
    "package": validate_package,
    "gallery": validate_gallery,
}
```

并在文件 docstring（第 12 行 `skill — ...` 之后）插入一行：

```
  package   — validate the v6 package: output/{slug}/SKILL.md + references/ (gates P1-P6)
```

- [ ] **Step 6: 运行测试确认通过**

```bash
python -X utf8 -m pytest tests/test_package_v6.py -v
```

Expected: PASS — 14 passed

- [ ] **Step 7: 更新 config/defaults.json**

把 `config/defaults.json` 整体替换为：

```json
{
  "version": "2.0",
  "output": {
    "languages": ["zh"],
    "skill_install_path": "~/.claude/skills/{person-slug}-wisdom/",
    "gallery_path": "./gallery/{person-slug}/",
    "output_path": "./output/{person-slug}/",
    "english_on_demand": true,
    "english_install_path": "~/.claude/skills/{person-slug}-wisdom-en/"
  },
  "package_budget": {
    "format_version": 6,
    "skill_max_lines": 500,
    "reference_dir": "references",
    "required_refs": ["cases.md", "evidence.md", "voice.md"],
    "cases_max_tokens": 4000,
    "evidence_max_tokens": 3000,
    "voice_max_tokens": 2000,
    "dossier_in_install_dir": false
  },
  "distillation": {
    "min_principles": 8,
    "max_principles": 11,
    "principle_target_chars": 900,
    "min_reasoning_patterns": 3,
    "max_reasoning_patterns": 5,
    "min_blind_spots": 2,
    "min_quotes": 5,
    "max_quotes": 10,
    "min_cases_per_cluster": 2,
    "min_counter_cases": 1,
    "min_voice_samples": 20
  },
  "source_strategy": {
    "priority": "user-provided-first",
    "user_source_path": "./sources/{person-slug}/raw/",
    "processed_path": "./sources/{person-slug}/processed/",
    "supported_formats": ["pdf", "txt", "md", "epub"],
    "fallback": "web-search"
  },
  "quality": {
    "require_source_attribution": true,
    "require_blind_spots": true,
    "require_bilingual_review": false,
    "require_provenance_gates": true,
    "review_verdicts": ["PASS", "REVISE", "FAIL"]
  }
}
```

- [ ] **Step 8: 确认 defaults 与 PACKAGE_SCHEMA 一致**

```bash
python -X utf8 -c "
import json,sys,importlib.util
d=json.load(open('config/defaults.json',encoding='utf-8'))['package_budget']
spec=importlib.util.spec_from_file_location('v','scripts/validate_output.py')
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
s=m.PACKAGE_SCHEMA
for k in ('skill_max_lines','reference_dir','required_refs','format_version'):
    assert d[k]==s[k], (k,d[k],s[k])
print('defaults.json 与 PACKAGE_SCHEMA 一致')
"
```

Expected: `defaults.json 与 PACKAGE_SCHEMA 一致`

- [ ] **Step 9: 提交**

```bash
git add scripts/validate_output.py tests/test_package_v6.py config/defaults.json && git commit -m "feat: add package stage with P3-P6 structural gates"
```

---

### Task 4: 格式感知——保护存量 24 个 skill

**Files:**
- Modify: `scripts/validate_output.py:417-441`（`validate_skill`）
- Modify: `scripts/validate_output.py:275-280`、`:393-395`（`validate_frameworks` 的 en 条件化）
- Modify: `tests/test_package_v6.py`（追加回归测试类）

**Interfaces:**
- Consumes: Task 3 的 `PACKAGE_SCHEMA`、`validate_package`
- Produces: `validate_skill` 与 `validate_frameworks` 的格式判别行为——`format_version: 6` 走 v6 路径，否则逐字节保持今日 legacy 行为

- [ ] **Step 1: 先记录存量行为作为回归基线**

```bash
python -X utf8 scripts/validate_output.py gallery zhang-juzheng > /tmp/baseline_zhang.txt 2>&1; echo "exit=$?" >> /tmp/baseline_zhang.txt; cat /tmp/baseline_zhang.txt
```

Expected: 输出以 `✅ Stage 'gallery' passed for 'zhang-juzheng'` 结尾，`exit=0`。把这份输出留作 Step 6 的比对基线。

- [ ] **Step 2: 写失败测试**

在 `tests/test_package_v6.py` 的 `if __name__` 之前追加：

```python
class FormatDetectionTests(unittest.TestCase):
    LEGACY = (
        "---\nname: demo-wisdom\n"
        "description: Apply demo frameworks. 运用示例框架。\n---\n\n"
        "# Language Detection · 语言检测\n\n"
        "## English\n\n### Identity Card\n略\n\n"
        "## 中文版\n\n### 身份卡\n略\n"
    )

    def test_detects_v6_by_format_version(self) -> None:
        self.assertTrue(validator.is_v6_skill(build_skill_md()))

    def test_detects_legacy_when_format_version_absent(self) -> None:
        self.assertFalse(validator.is_v6_skill(self.LEGACY))

    def test_v6_skill_stage_does_not_demand_english_block(self) -> None:
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as td:
            try:
                fx = PackageFixture(td)
                os.chdir(fx.root)
                errors = validator.validate_skill("demo")
            finally:
                os.chdir(cwd)
            self.assertFalse(any("## English" in e for e in errors))
            self.assertFalse(any("MISSING_LANG_DETECTION" in e for e in errors))

    def test_legacy_skill_stage_still_demands_english_block(self) -> None:
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as td:
            try:
                out = Path(td) / "output" / "demo"
                out.mkdir(parents=True)
                (out / "SKILL.md").write_text(
                    self.LEGACY.replace("## English\n\n### Identity Card\n略\n\n", ""),
                    encoding="utf-8",
                )
                os.chdir(td)
                errors = validator.validate_skill("demo")
            finally:
                os.chdir(cwd)
            self.assertTrue(any("'## English'" in e for e in errors))


class FrameworksLanguageTests(unittest.TestCase):
    def _write_core(self, out: Path) -> None:
        (out / "framework_core.json").write_text(
            json.dumps({"person_slug": "demo", "principle_clusters": [{"cluster_id": "cluster_001"}]}),
            encoding="utf-8",
        )

    def test_missing_en_framework_is_not_an_error_when_zh_only(self) -> None:
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as td:
            try:
                out = Path(td) / "output" / "demo"
                out.mkdir(parents=True)
                self._write_core(out)
                (out / "frameworks.zh.json").write_text("{}", encoding="utf-8")
                os.chdir(td)
                errors = validator.validate_frameworks("demo")
            finally:
                os.chdir(cwd)
            self.assertFalse(
                any(e.startswith("MISSING:") and "frameworks.en.json" in e for e in errors)
            )

    def test_missing_en_framework_is_an_error_when_en_requested(self) -> None:
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as td:
            try:
                out = Path(td) / "output" / "demo"
                out.mkdir(parents=True)
                self._write_core(out)
                (out / "frameworks.zh.json").write_text("{}", encoding="utf-8")
                (out / "en_requested.flag").write_text("yes", encoding="utf-8")
                os.chdir(td)
                errors = validator.validate_frameworks("demo")
            finally:
                os.chdir(cwd)
            self.assertTrue(
                any(e.startswith("MISSING:") and "frameworks.en.json" in e for e in errors)
            )
```

- [ ] **Step 3: 运行测试确认失败**

```bash
python -X utf8 -m pytest tests/test_package_v6.py -v -k "FormatDetection or FrameworksLanguage"
```

Expected: FAIL — 6 条新测试全部为红。其中 2 条报 `AttributeError: module 'validate_output' has no attribute 'is_v6_skill'`；另 4 条为普通断言失败或（实现前）伪通过——判据是「红→绿」，不是错误文本一致

- [ ] **Step 4: 实现格式判别**

在 `scripts/validate_output.py` 的 `validate_skill`（第 417 行）之前插入：

```python
def is_v6_skill(content: str) -> bool:
    """v6 包由 frontmatter 的 format_version 判定；无此字段一律按 legacy 处理。"""
    return bool(re.search(
        rf"^format_version:\s*{PACKAGE_SCHEMA['format_version']}\s*$",
        content, re.MULTILINE,
    ))


def en_branch_requested(slug: str) -> bool:
    """英文分支是否已被用户选用（Stage 6.5 落 en_requested.flag）。"""
    return Path(f"output/{slug}/en_requested.flag").exists()
```

把 `validate_skill`（第 417-441 行）的函数体开头改为——在 `merged_file = output_dir / "SKILL.md"` 与 `if merged_file.exists():` 之间插入格式分流：

```python
    merged_file = output_dir / "SKILL.md"
    if merged_file.exists():
        if is_v6_skill(merged_file.read_text(encoding="utf-8")):
            return validate_package(slug)
        return _validate_merged_skill(merged_file, slug)
```

- [ ] **Step 5: 条件化 frameworks 的英文要求**

把 `scripts/validate_output.py:331` 的循环头：

```python
    for lang in ["zh", "en"]:
```

改为：

```python
    langs = ["zh", "en"] if en_branch_requested(slug) else ["zh"]
    for lang in langs:
```

并把第 392-394 行的双语交叉检查入口包进条件——用普通守卫，不要用抛异常的写法：

原文：

```python
    # Cross-check: blind spots must cover same themes
    try:
        zh_data = read_json_file(output_dir / "frameworks.zh.json")
```

改为：

```python
    # Cross-check: blind spots must cover same themes（仅在英文分支启用时）
    try:
        if not en_branch_requested(slug):
            return errors
        zh_data = read_json_file(output_dir / "frameworks.zh.json")
```

（`return errors` 直接跳过整个交叉检查块并返回已累积的错误——此块是函数体最后一段，
其后只有 `except Exception: pass` 与 `return errors`，提前返回不会漏掉任何检查。）

同时把第 328-330 行 `expected_outputs` 中的 `"framework_en"` 一项改为条件加入：

```python
            expected_outputs = {
                "framework_core": output_dir / "framework_core.json",
                "framework_zh": output_dir / "frameworks.zh.json",
                "alignment_review": output_dir / "framework_alignment_review.md",
            }
            if en_branch_requested(slug):
                expected_outputs["framework_en"] = output_dir / "frameworks.en.json"
```

- [ ] **Step 6: 运行全量测试并比对存量基线**

```bash
python -X utf8 -m pytest tests/ -v
```

Expected: PASS — `tests/` 共 **61 passed**（Task 1-3 后为 55：18 package + 26 provenance + 11 既有；本任务 +6）

```bash
python -X utf8 scripts/validate_output.py gallery zhang-juzheng > /tmp/after_zhang.txt 2>&1; echo "exit=$?" >> /tmp/after_zhang.txt; diff /tmp/baseline_zhang.txt /tmp/after_zhang.txt && echo "存量行为零变化"
```

Expected: `存量行为零变化`（diff 无输出）

- [ ] **Step 7: 对全部存量 slug 做回归扫描**

```bash
for s in $(python -X utf8 -c "
import json
print(' '.join(e['slug'] for e in json.load(open('gallery/index.json',encoding='utf-8'))['skills']))
"); do printf '%-22s ' "$s"; if python -X utf8 scripts/validate_output.py gallery "$s" >/dev/null 2>&1; then echo OK; else echo FAIL; fi; done > /tmp/gallery_now.txt; diff .superpowers/sdd/2026-08-23-skill-package-v6/gallery-baseline.txt /tmp/gallery_now.txt && echo "存量行为零变化"
```

Expected: `存量行为零变化`（diff 无输出）。

⚠️ **判据是与基线一致，不是全部 OK。** 基线为 **23 OK / 1 FAIL**：`charlie-munger` 恒 FAIL，
原因是 `output/charlie-munger/` 根本不存在（它是手写的 legacy 示例，从未经管线产出，而 `output/`
被 gitignore）。该失败在 Task 3 之前即已存在，与本改造无关。任何**偏离基线**的行才是回归。

- [ ] **Step 8: 提交**

```bash
git add scripts/validate_output.py tests/test_package_v6.py && git commit -m "feat: make skill and frameworks stages format-aware, preserving legacy behavior"
```

---

### Task 5: v6 模板（核心 + 四附件）与 Rule 4 改写

**Files:**
- Create: `templates/skill-template.v6.zh.md`
- Create: `templates/refs/cases.zh.md`
- Create: `templates/refs/evidence.zh.md`
- Create: `templates/refs/voice.zh.md`
- Create: `templates/refs/dossier.zh.md`
- Modify: `CLAUDE.md:25`（Critical Platform Constraint）、`CLAUDE.md:32`（Rule 4）
- Create: `tests/test_templates_v6.py`

**Interfaces:**
- Consumes: Task 3 的 `PACKAGE_SCHEMA["core_sections"]`；Task 2 的证据卡格式契约
- Produces: 五个模板文件，其占位符名与 `frameworks.zh.json` 字段一一对应；新增两个原则字段占位符 `{failure_boundary_zh}`、`{prerequisite_intel_zh}`

> 保留 `templates/skill-template.zh.md` 原文件不动——它仍是 legacy 格式的参考。v6 用新文件名，避免破坏存量文档引用。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_templates_v6.py`：

> ⚠️ **`assertRegex` 的第三个位置参数是 `msg`，不是 `flags`。** 写
> `self.assertRegex(text, pattern, re.MULTILINE)` 会**静默丢弃**多行模式，导致 `^`/`$`
> 只匹配整串首尾——对多行文件而言这些断言要么恒假、要么因错误的原因通过。
> 因此下面所有跨行断言一律用内联 `(?m)`，不要传 flags 参数。

```python
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE_SECTIONS = [
    "身份卡", "响应策略", "核心原则", "决策框架",
    "已知盲区", "表达风格 DNA", "价值取向与反模式", "溯源",
]


class V6CoreTemplateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.path = ROOT / "templates" / "skill-template.v6.zh.md"
        self.text = self.path.read_text(encoding="utf-8")

    def test_declares_format_version_6(self) -> None:
        self.assertRegex(self.text, r"(?m)^format_version:\s*6\s*$")

    def test_has_no_english_block(self) -> None:
        self.assertNotRegex(self.text, r"(?m)^##\s+English")

    def test_has_no_language_detection_header(self) -> None:
        self.assertNotIn("Language Detection", self.text)

    def test_contains_all_core_sections(self) -> None:
        for name in CORE_SECTIONS:
            with self.subTest(section=name):
                self.assertRegex(self.text, rf"(?m)^#{{2,4}}\s*.*{re.escape(name)}")

    def test_has_case_index_section(self) -> None:
        self.assertRegex(self.text, r"(?m)^##\s*案例索引\s*$")

    def test_principle_block_has_failure_boundary(self) -> None:
        self.assertIn("{failure_boundary_zh}", self.text)

    def test_principle_block_has_prerequisite_intel(self) -> None:
        self.assertIn("{prerequisite_intel_zh}", self.text)

    def test_declares_attachment_read_triggers(self) -> None:
        for ref in ("references/cases.md", "references/evidence.md", "references/voice.md"):
            with self.subTest(ref=ref):
                self.assertIn(ref, self.text)

    def test_principle_count_guidance_is_nine_to_eleven(self) -> None:
        self.assertIn("9-11", self.text)

    def test_is_under_line_cap(self) -> None:
        self.assertLessEqual(len(self.text.splitlines()), 500)


class AttachmentTemplateTests(unittest.TestCase):
    def test_all_four_attachment_templates_exist(self) -> None:
        for name in ("cases.zh.md", "evidence.zh.md", "voice.zh.md", "dossier.zh.md"):
            with self.subTest(name=name):
                self.assertTrue((ROOT / "templates" / "refs" / name).exists())

    def test_evidence_template_matches_parser_contract(self) -> None:
        text = (ROOT / "templates" / "refs" / "evidence.zh.md").read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^###\s+原则")
        self.assertRegex(text, r"(?m)^>\s")
        self.assertRegex(text, r"(?m)^-\s*confidence\s*[：:]")
        self.assertIn("textual_note", text)

    def test_cases_template_matches_parser_contract(self) -> None:
        text = (ROOT / "templates" / "refs" / "cases.zh.md").read_text(encoding="utf-8")
        self.assertIn("case_id:", text)
        self.assertRegex(text, r"(?m)^\*\*对应原则簇：\*\*")
        self.assertIn("反例", text)

    def test_voice_template_has_positive_and_negative_pair(self) -> None:
        text = (ROOT / "templates" / "refs" / "voice.zh.md").read_text(encoding="utf-8")
        self.assertIn("为什么像他", text)
        self.assertIn("误写成通用分析腔", text)

    def test_dossier_template_records_rejected_candidates(self) -> None:
        text = (ROOT / "templates" / "refs" / "dossier.zh.md").read_text(encoding="utf-8")
        self.assertIn("被舍弃", text)


class Rule4Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")

    def test_rule4_no_longer_mandates_bilingual_by_default(self) -> None:
        self.assertNotIn(
            "the final deliverable MUST be one `SKILL.md` containing both languages",
            self.text,
        )

    def test_rule4_declares_chinese_default(self) -> None:
        self.assertIn("Chinese-only by default", self.text)

    def test_rule4_declares_english_as_separate_skill(self) -> None:
        self.assertIn("{person-slug}-wisdom-en", self.text)

    def test_platform_constraint_still_states_skill_md_requirement(self) -> None:
        self.assertIn("requires exactly `SKILL.md`", self.text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -X utf8 -m pytest tests/test_templates_v6.py -v
```

Expected: FAIL — `FileNotFoundError: templates/skill-template.v6.zh.md`

- [ ] **Step 3: 创建核心模板**

创建 `templates/skill-template.v6.zh.md`。以现有 `templates/skill-template.zh.md` 为基础，做四处改动，其余章节逐字沿用：

改动一，frontmatter（替换第 1-14 行）：

```markdown
---
name: {person-slug}-wisdom
format_version: 6
description: >-
  运用{person_name_zh}的{primary_domain_zh}框架处理{category_description_zh}。
  触发：{person_name_zh}、{keyword_list_zh}
argument-hint: <描述你面临的决策场景或困境>
---

<!--
  v6 包格式。本文件是恒载核心，必须自足——删掉 references/ 后仍是一份完整框架。
  硬约束：≤500 行、纯中文、不得含英文语言区块、不含语言检测头。
  附件在 references/{cases,evidence,voice}.md，由下方「附件调用」表的触发条件驱动。
  英文版是独立 skill（{person-slug}-wisdom-en），不在本文件内。
-->
```

改动二，在「### 按输入类型适配」小节之后插入附件调用表：

```markdown
### 附件调用（触发条件确定，不由临场判断）

| 触发条件 | 必须执行 |
|---|---|
| 用户问出处、质疑真伪、问「他真说过这话吗」 | 读 `references/evidence.md`，只引用其中逐字条目；卡里没有的引文不得凭记忆补充 |
| 用户描述的处境命中下方「案例索引」某一行 | 读 `references/cases.md` 中对应 case_id 的条目再作答 |
| 同一对话中已连续 2 轮回答结构趋同 | 读 `references/voice.md` 取样重置语感 |

附件是深度补充，不是前置条件。未触发时直接用本文件作答——本文件已是完整框架。
```

改动三，「## 核心原则」的重复块（现第 90-108 行）替换为：

```markdown
## 核心原则

{repeat_block: 9-11 principles，每条约 900 字}

### 原则 {n}：{principle_name_zh}

**理念：** {principle_explanation_zh — 第一人称，3-4 句}

**原文出处：**「{original_quote_zh}」——《{source_title_zh}》{source_detail}

**决策规则：** 当{situation_pattern_zh}时，应当{recommended_action_zh}。

**应用示例：**
- **情境：** {modern_scenario_zh}
- **运用此原则：** {how_principle_applies_zh}
- **背后逻辑：** {why_it_works_zh}

**失效边界：** {failure_boundary_zh — 这条原则在什么条件下不适用，硬套会导致什么}

**情报前提：** {prerequisite_intel_zh — 应用前必须先查明什么}

{/repeat_block}
```

改动五（**P3 闸门强制要求**），清除仓库相对路径：

现有 zh 模板的反套公式指令第 1 条以反引号引用了 `config/post-review-tuning-guide.md`。
v6 的 P3 闸门只按 **SKILL.md 自身所在目录**解析反引号路径（CWD 回退已在 Task 3 修复轮中删除，
因为它会让悬空路径靠仓库根巧合通过）。已安装的 skill 位于 `~/.claude/skills/{slug}-wisdom/`，
那里不存在 `config/`——所以模板中**任何仓库相对的反引号路径都会被 P3 判为悬空**。

处理：把该引用改写为散文（如「替代工具箱见工厂的 post-review 调优指南」，不加反引号路径），
并检查模板全文，确保**仅有** `references/cases.md`、`references/evidence.md`、`references/voice.md`
三个反引号路径——它们相对包目录可解析。这是「出厂 skill 必须自足」的直接推论。

改动四，在「## 核心原则」之前插入案例索引章：

```markdown
## 案例索引

情境与下表某行相符时，按「附件调用」表读取 `references/cases.md` 中对应条目。

| 案例 | 触发情境 | 对应原则 | case_id |
|---|---|---|---|
| {case_title_1} | {case_trigger_1} | 原则 {n} | {case_id_1} |
| {case_title_2} | {case_trigger_2} | 原则 {n} | {case_id_2} |

{repeat: 每个原则簇至少 2 行，全表至少 1 个反例}
```

- [ ] **Step 4: 创建四个附件模板**

创建 `templates/refs/evidence.zh.md`：

```markdown
# {person_name_zh} · 证据卡

每条原则一张卡，承载**逐字**原文。此文件是 P1/P2 闸门的输入端——
卡内引文必须逐字出现在 `sources/{person-slug}/` 的语料中，否则 `package` 校验不通过。

若出厂文本与语料有分歧而作者判定出厂文本正确（如底本讹字），
追加 `- textual_note：` 说明分歧，闸门降级为 WARNING 并把分歧记录在案。

---

### 原则 1：{principle_name_zh}

> {逐字原文，一字不改}

- 出处：《{source_title_zh}》{source_detail}
- 语料位置：`sources/{person-slug}/raw/{filename}`
- confidence：high
- 现代转译：{核心层那句「决策规则」如何从这段原文推出}

### 原则 2：{principle_name_zh}

> {逐字原文}

- 出处：《{source_title_zh}》{source_detail}
- 语料位置：`sources/{person-slug}/raw/{filename}`
- confidence：medium
- 现代转译：{……}
- textual_note：{仅在与语料有分歧时填写；说明分歧与裁决依据}
```

创建 `templates/refs/cases.zh.md`：

```markdown
# {person_name_zh} · 案例库

每个原则簇至少 2 例，全库至少 1 个反例。每例必须有 case_id 与 confidence 分级。
反例是硬要求——只收成功案例会让案例库退化成颂扬集。

---

### 案例 1：{case_title}（case_id: {person-slug}-{key}-{year}，high）

**对应原则簇：** {cluster_id}

**情境：** {当时的客观处境，含约束条件}

**{person_name_zh}如何判断：** {第一人称重述推理路径，挂到具体原则}

**实际结局：** {发生了什么}

**若换一种做法：** {反事实推演，一句}

**出处：** 《{source_title_zh}》{source_detail}

### 案例 N：{case_title}（case_id: {person-slug}-{key}-{year}，medium）

**对应原则簇：** {cluster_id}

**反例：** {此人判断失误或原则被误用的案例——说明失效边界如何被触碰}

**情境：** {……}

**实际结局：** {……}

**出处：** 《{source_title_zh}》{source_detail}
```

创建 `templates/refs/voice.zh.md`：

```markdown
# {person_name_zh} · 语感样本库

至少 20 条带标注的原始语料。正例与反例对照——复盘把「通用 AI 分析腔」
列为头号运行期缺陷，单列正例不足以纠正。

---

### 样本 1（维度：{句式 / 修辞 / 语气 / 确定性 / 幽默 / 禁忌 / 段落节奏 / 对话标记}）

> {原文片段}

**为什么像他：** {一句标注}

**误写成通用分析腔会变成：** {把同一意思写成通用 AI 腔的反例改写}

### 样本 2（维度：{……}）

> {原文片段}

**为什么像他：** {……}

**误写成通用分析腔会变成：** {……}
```

创建 `templates/refs/dossier.zh.md`：

```markdown
# {person_name_zh} 蒸馏档案

> 本文件给人读，不进 `~/.claude/skills/`。它记录管线内部的判断过程。

## 一、语料规模与来源

| 文件 | 大小 | 类型 | OCR 质量 | 已知讹字 |
|---|---|---|---|---|
| {filename} | {size} | 一手 / 二手 | {good/fair/poor} | {notes} |

分片：{n} shards / {tokens} tok；采样：{sampled}/{total}

## 二、原则推导链

| cluster_id | 候选原则 | 是否出厂 | 理由 |
|---|---|---|---|
| {cluster_id} | {candidate_name} | ✅ 原则 {n} | {why} |
| {cluster_id} | {candidate_name} | ❌ 舍弃 | {why_rejected} |

**被舍弃的候选原则及理由**是本节的重点——它记录了蒸馏做过的取舍。

## 三、盲区与缓解

{每条盲区 + 缓解建议}

## 四、质量审查结论

- distill_confidence：{n}/5
- 逐字引文校验：{pass}/{total}
- 案例覆盖：{clusters_covered}/{clusters_total}，反例 {counter_count} 个

## 五、已知风险

- {误归属陷阱：如小说/影视/后世注评混入}
- {OCR 讹字与底本分歧}
- {语料时代局限}
```

- [ ] **Step 5: 改写 CLAUDE.md 的 Rule 4 与平台约束**

把 `CLAUDE.md:25` 整段替换为：

```markdown
**Claude Code skill discovery requires exactly `SKILL.md`** (case-sensitive) in each skill directory. Files like `SKILL.zh.md`, `SKILL.en.md`, or `README.md` are invisible to the skill loader. A skill directory MAY also contain sub-files (e.g. `references/*.md`); the model reads those on demand via relative paths written into `SKILL.md`. See Rule 4 and the v6 package format below.
```

把 `CLAUDE.md:32` 的 Rule 4 整条替换为：

```markdown
4. **Language: Chinese-only by default.** Each Skill produces `frameworks.zh.json` and a Chinese-only `SKILL.md` carrying `format_version: 6`. No `## English` block, no language-detection header. After the Chinese package is installed, the orchestrator asks whether to also generate an English version; only on a yes does it run the EN branch (reusing the language-neutral `framework_core.json`) and publish it as a **separate skill directory** `{person-slug}-wisdom-en`. Rule 4's original principle — the English version is an independent cognitive reconstruction, NOT a translation — still holds *within* the EN branch. It is now paid on demand instead of every run.
```

在 Rule 7 之后新增一节：

```markdown
## Skill Package Format (v6)

A distilled Skill ships as a **package**, not a single file:

```
{slug}-wisdom/
├── SKILL.md              # always-loaded, Chinese, self-sufficient, ≤500 lines
└── references/
    ├── cases.md          # on demand — worked cases, ≥2 per cluster, ≥1 counter-case
    ├── evidence.md       # on demand — verbatim source excerpts, machine-checked
    └── voice.md          # on demand — ≥20 annotated voice samples
```

`SKILL.md` is **never a dispatcher**. Deleting `references/` must leave a complete, working framework — gate P6 enforces this. The case *index* lives in the core so the model always knows what exists; only case *bodies* live in the attachment.

`人物档案.md` is a human-readable dossier. It goes to `output/` and `gallery/` but **never** into the install directory.

Gates P1–P6 (`python scripts/validate_output.py package {slug}`) are all rule-based — no LLM scoring — because an LLM reviewer graded 7/7 quotes "EXACT" on a set where 4 of 14 were not verbatim.
```

- [ ] **Step 6: 运行测试确认通过**

```bash
python -X utf8 -m pytest tests/test_templates_v6.py -v
```

Expected: PASS — 19 passed（+15 subtests）

- [ ] **Step 7: 确认核心模板能过 P6 闸门**

```bash
python -X utf8 -c "
import importlib.util, tempfile, shutil
from pathlib import Path
spec=importlib.util.spec_from_file_location('v','scripts/validate_output.py')
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
with tempfile.TemporaryDirectory() as td:
    p=Path(td)/'SKILL.md'
    shutil.copy('templates/skill-template.v6.zh.md', p)
    errs=[e for e in m.check_p6_core(p) if e.startswith('P6_TOO_LONG')]
    print('P6 行数闸门:', errs or 'PASS')
"
```

Expected: `P6 行数闸门: PASS`（模板本身在 500 行以内；章节非空检查会因占位符而报错，属预期——模板不是成品）

- [ ] **Step 8: 提交**

```bash
git add templates/skill-template.v6.zh.md templates/refs/ CLAUDE.md tests/test_templates_v6.py && git commit -m "feat: add v6 templates and rewrite Rule 4 for Chinese-first output"
```

---

### Task 6: 发布器目录同步与 gallery manifest 校验

**Files:**
- Modify: `scripts/publish_skill.py:66-140`（路径、复制、index 条目）
- Modify: `scripts/validate_output.py:453-492`（`validate_gallery`）
- Create: `tests/test_publish_v6.py`

**Interfaces:**
- Consumes: Task 3 的 `PACKAGE_SCHEMA`、Task 4 的 `is_v6_skill`
- Produces:
  - `publish_skill.copy_package(output_dir: Path, gallery_dir: Path, is_v6: bool) -> list[str]` — 返回已复制的相对路径列表
  - `publish_skill.write_manifest(gallery_dir: Path, copied: list[str]) -> Path` — 写 `manifest.json`，含每个文件的 sha256
  - `publish_skill.INSTALL_WHITELIST = ("SKILL.md", "references")`
  - `validate_output.validate_gallery` 对 v6 包改为逐文件哈希比对

- [ ] **Step 1: 写失败测试**

创建 `tests/test_publish_v6.py`：

```python
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


publisher = load_module("publish_skill", ROOT / "scripts" / "publish_skill.py")


def build_v6_output(root: Path) -> Path:
    out = root / "output" / "demo"
    refs = out / "references"
    refs.mkdir(parents=True)
    (out / "SKILL.md").write_text(
        "---\nname: demo-wisdom\nformat_version: 6\n---\n\n# 示例\n", encoding="utf-8"
    )
    for name in ("cases.md", "evidence.md", "voice.md"):
        (refs / name).write_text(f"# {name}\n", encoding="utf-8")
    (out / "人物档案.md").write_text("# 档案\n", encoding="utf-8")
    return out


class CopyPackageTests(unittest.TestCase):
    def test_copies_skill_and_all_references(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out = build_v6_output(root)
            gallery = root / "gallery" / "demo"
            copied = publisher.copy_package(out, gallery, is_v6=True)
            self.assertIn("SKILL.md", copied)
            self.assertIn("references/cases.md", copied)
            self.assertTrue((gallery / "references" / "voice.md").exists())

    def test_copies_dossier_into_gallery(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out = build_v6_output(root)
            gallery = root / "gallery" / "demo"
            publisher.copy_package(out, gallery, is_v6=True)
            self.assertTrue((gallery / "人物档案.md").exists())

    def test_legacy_copies_only_skill_md(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out = root / "output" / "demo"
            out.mkdir(parents=True)
            (out / "SKILL.md").write_text("---\nname: demo-wisdom\n---\n", encoding="utf-8")
            gallery = root / "gallery" / "demo"
            copied = publisher.copy_package(out, gallery, is_v6=False)
            self.assertEqual(copied, ["SKILL.md"])


class InstallWhitelistTests(unittest.TestCase):
    def test_dossier_is_not_in_install_whitelist(self) -> None:
        self.assertNotIn("人物档案.md", publisher.INSTALL_WHITELIST)

    def test_whitelist_contains_skill_and_references(self) -> None:
        self.assertIn("SKILL.md", publisher.INSTALL_WHITELIST)
        self.assertIn("references", publisher.INSTALL_WHITELIST)


class ManifestTests(unittest.TestCase):
    def test_manifest_lists_every_copied_file_with_hash(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out = build_v6_output(root)
            gallery = root / "gallery" / "demo"
            copied = publisher.copy_package(out, gallery, is_v6=True)
            manifest_path = publisher.write_manifest(gallery, copied)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(sorted(manifest["files"].keys()), sorted(copied))
            for digest in manifest["files"].values():
                self.assertEqual(len(digest), 64)

    def test_manifest_hash_changes_when_a_reference_changes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out = build_v6_output(root)
            gallery = root / "gallery" / "demo"
            copied = publisher.copy_package(out, gallery, is_v6=True)
            first = json.loads(publisher.write_manifest(gallery, copied).read_text(encoding="utf-8"))
            (gallery / "references" / "cases.md").write_text("# changed\n", encoding="utf-8")
            second = json.loads(publisher.write_manifest(gallery, copied).read_text(encoding="utf-8"))
            self.assertNotEqual(
                first["files"]["references/cases.md"], second["files"]["references/cases.md"]
            )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -X utf8 -m pytest tests/test_publish_v6.py -v
```

Expected: FAIL — `AttributeError: module 'publish_skill' has no attribute 'copy_package'`

- [ ] **Step 3: 实现包复制、白名单与 manifest**

在 `scripts/publish_skill.py` 的 `run_command`（第 34-44 行）之后插入：

```python
INSTALL_WHITELIST = ("SKILL.md", "references")
DOSSIER_NAME = "人物档案.md"
REFERENCE_DIR = "references"


def is_v6_package(skill_md: Path) -> bool:
    """v6 包由 SKILL.md frontmatter 的 format_version 判定。

    **委托给 validate_output.is_v6_skill，不得自建正则。** 格式判别位只能有一个实现：
    发布器与校验器若各判各的，就会出现「按 v6 发布、按 legacy 校验」的永久不一致，
    而发布器是会留下损坏的那一半。
    """
    import importlib.util
    path = Path(__file__).resolve().parent / "validate_output.py"
    spec = importlib.util.spec_from_file_location("validate_output", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.is_v6_skill(skill_md.read_text(encoding="utf-8"))


def copy_package(output_dir: Path, gallery_dir: Path, is_v6: bool) -> list[str]:
    """把 output/{slug}/ 的包内容同步到 gallery/{slug}/，返回已复制的相对路径。"""
    gallery_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []

    shutil.copy2(output_dir / "SKILL.md", gallery_dir / "SKILL.md")
    copied.append("SKILL.md")
    if not is_v6:
        return copied

    refs_src = output_dir / REFERENCE_DIR
    if refs_src.exists():
        refs_dst = gallery_dir / REFERENCE_DIR
        refs_dst.mkdir(exist_ok=True)
        for path in sorted(refs_src.glob("*.md")):
            shutil.copy2(path, refs_dst / path.name)
            copied.append(f"{REFERENCE_DIR}/{path.name}")

    dossier = output_dir / DOSSIER_NAME
    if dossier.exists():
        shutil.copy2(dossier, gallery_dir / DOSSIER_NAME)
        copied.append(DOSSIER_NAME)

    return copied


def file_sha256(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_manifest(gallery_dir: Path, copied: list[str]) -> Path:
    """写 gallery/{slug}/manifest.json，含每个文件的 sha256。"""
    manifest = {
        "format_version": 6,
        "files": {rel: file_sha256(gallery_dir / rel) for rel in sorted(copied)},
    }
    path = gallery_dir / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def install_paths(gallery_dir: Path) -> list[Path]:
    """只有白名单内的路径进 ~/.claude/skills/——档案留在 gallery。"""
    result = []
    for name in INSTALL_WHITELIST:
        candidate = gallery_dir / name
        if candidate.exists():
            result.append(candidate)
    return result
```

把 `scripts/publish_skill.py:127-133` 的复制块：

```python
    try:
        shutil.copy2(output_skill, gallery_skill)
        print(f"  Copied {output_skill.name} to {gallery_skill}")
    except Exception as e:
        print(f"ERROR copying files: {e}", file=sys.stderr)
        return 1
```

替换为：

```python
    try:
        v6 = is_v6_package(output_skill)
        copied = copy_package(output_dir, gallery_dir, is_v6=v6)
        manifest_path = write_manifest(gallery_dir, copied)
        print(f"  Copied {len(copied)} file(s) to {gallery_dir}: {', '.join(copied)}")
        print(f"  Wrote {manifest_path.name} (format_version={'6' if v6 else 'legacy'})")
    except Exception as e:
        print(f"ERROR copying files: {e}", file=sys.stderr)
        return 1
```

把第 92-97 行英文框架的硬性要求放宽（`frameworks.en.json` 本已是 optional，只需在新条目里记录语言）；在第 152-166 行的 `new_entry` 字典中追加三个字段：

```python
            "lang": "zh",
            "format_version": 6 if v6 else 1,
            "has_attachments": v6,
```

并在第 138-150 行的 `entry` 更新分支中同样追加这三行赋值。

- [ ] **Step 4: 运行测试确认通过**

```bash
python -X utf8 -m pytest tests/test_publish_v6.py -v
```

Expected: PASS — 7 passed

- [ ] **Step 5: 让 validate_gallery 对 v6 包逐文件比对**

把 `scripts/validate_output.py:453-470`（`validate_gallery` 开头到哈希比对）替换为：

```python
def validate_gallery(slug: str) -> list[str]:
    """Validate the published gallery artifact and ensure it is synced from output."""
    errors = []
    output_file = Path(f"output/{slug}/SKILL.md")
    gallery_file = Path(f"gallery/{slug}/SKILL.md")

    if not output_file.exists():
        return [f"MISSING: {output_file}"]
    if not gallery_file.exists():
        return [f"MISSING: {gallery_file}"]

    v6 = is_v6_skill(gallery_file.read_text(encoding="utf-8"))
    sync_targets = ["SKILL.md"]
    if v6:
        refs_src = Path(f"output/{slug}/references")
        if refs_src.exists():
            sync_targets += [f"references/{p.name}" for p in sorted(refs_src.glob("*.md"))]

    for rel in sync_targets:
        out_path = Path(f"output/{slug}/{rel}")
        gal_path = Path(f"gallery/{slug}/{rel}")
        if not gal_path.exists():
            errors.append(f"GALLERY_MISSING_FILE: {gal_path} (present in output/)")
            continue
        if _sha256(out_path) != _sha256(gal_path):
            errors.append(
                f"GALLERY_OUT_OF_SYNC: {gal_path} does not match {out_path} "
                f"(gallery={_sha256(gal_path)[:12]}, output={_sha256(out_path)[:12]})"
            )

    if v6:
        errors.extend(validate_package(slug))
    else:
        errors.extend(_validate_merged_skill(gallery_file, slug))
```

（其后的 `index_file` 检查块保持不变。）

- [ ] **Step 6: 运行全量测试并重跑存量回归**

```bash
python -X utf8 -m pytest tests/ -v
```

Expected: PASS — 全部通过

```bash
for s in $(python -X utf8 -c "
import json
print(' '.join(e['slug'] for e in json.load(open('gallery/index.json',encoding='utf-8'))['skills']))
"); do printf '%-24s ' "$s"; python -X utf8 scripts/validate_output.py gallery "$s" >/dev/null 2>&1 && echo OK || echo FAIL; done
```

Expected: 全部 `OK`

- [ ] **Step 7: 提交**

```bash
git add scripts/publish_skill.py scripts/validate_output.py tests/test_publish_v6.py && git commit -m "feat: publish v6 packages as directories with manifest hashing"
```

---

### Task 7: 代理改写（组装器、案例builder、证据卡builder、评审员）

**Files:**
- Modify: `agents/skill-assembler.md`
- Create: `agents/case-builder.md`
- Create: `agents/evidence-carder.md`
- Modify: `agents/quality-reviewer.md`
- Modify: `agents/framework-alignment-reviewer.md`
- Create: `tests/test_agent_contracts.py`

**Interfaces:**
- Consumes: Task 5 的模板路径与格式契约；Task 3 的闸门名称 P1–P6
- Produces: 四份代理定义。测试以「文档内引用的路径必须真实存在」为验证手段（借 mao 的 `check_skill_routes` 思路）

- [ ] **Step 1: 写失败测试**

创建 `tests/test_agent_contracts.py`：

```python
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKTICK_PATH_RE = re.compile(r"`([A-Za-z0-9_一-鿿./{}-]+\.(?:md|json|py))`")
PLACEHOLDER_RE = re.compile(r"\{[a-z_]+\}")

V6_DOCS = [
    ROOT / "agents" / "skill-assembler.md",
    ROOT / "agents" / "case-builder.md",
    ROOT / "agents" / "evidence-carder.md",
    ROOT / "agents" / "quality-reviewer.md",
    ROOT / "commands" / "distill.md",
]


def resolvable(rel: str) -> bool:
    """去掉 {slug} 之类占位符后判断路径是否存在（占位路径按目录前缀判断）。"""
    if PLACEHOLDER_RE.search(rel):
        prefix = rel.split("{")[0].rstrip("/")
        return bool(prefix) and (ROOT / prefix).exists()
    return (ROOT / rel).exists()


class AgentPathTests(unittest.TestCase):
    def test_every_backtick_path_in_v6_docs_resolves(self) -> None:
        for doc in V6_DOCS:
            if not doc.exists():
                self.fail(f"missing doc: {doc}")
            for match in BACKTICK_PATH_RE.finditer(doc.read_text(encoding="utf-8")):
                rel = match.group(1)
                if rel.startswith(("http", "~")):
                    continue
                with self.subTest(doc=doc.name, path=rel):
                    self.assertTrue(resolvable(rel), f"{doc.name} references missing `{rel}`")


class AssemblerContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = (ROOT / "agents" / "skill-assembler.md").read_text(encoding="utf-8")

    def test_targets_v6_template(self) -> None:
        self.assertIn("templates/skill-template.v6.zh.md", self.text)

    def test_no_longer_merges_bilingual_blocks(self) -> None:
        self.assertNotIn("## English", self.text)

    def test_emits_format_version(self) -> None:
        self.assertIn("format_version: 6", self.text)

    def test_states_line_cap(self) -> None:
        self.assertIn("500", self.text)


class CaseBuilderContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = (ROOT / "agents" / "case-builder.md").read_text(encoding="utf-8")

    def test_requires_proof_line(self) -> None:
        self.assertIn("首行为证", self.text)

    def test_requires_two_cases_per_cluster(self) -> None:
        self.assertIn("每个原则簇", self.text)
        self.assertIn("2", self.text)

    def test_requires_counter_case(self) -> None:
        self.assertIn("反例", self.text)


class EvidenceCarderContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = (ROOT / "agents" / "evidence-carder.md").read_text(encoding="utf-8")

    def test_forbids_stitching(self) -> None:
        self.assertIn("缝合", self.text)

    def test_mentions_textual_note_escape_hatch(self) -> None:
        self.assertIn("textual_note", self.text)

    def test_names_the_p2_gate(self) -> None:
        self.assertIn("P2", self.text)


class ReviewerContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = (ROOT / "agents" / "quality-reviewer.md").read_text(encoding="utf-8")

    def test_drops_bilingual_equivalence_from_default_path(self) -> None:
        self.assertIn("仅在英文分支", self.text)

    def test_adds_case_layer_dimension(self) -> None:
        self.assertIn("案例层", self.text)

    def test_defers_quote_verification_to_deterministic_gate(self) -> None:
        self.assertIn("verify_provenance", self.text)


class AlignmentReviewerContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = (ROOT / "agents" / "framework-alignment-reviewer.md").read_text(
            encoding="utf-8"
        )

    def test_has_a_chinese_self_check_mode(self) -> None:
        self.assertIn("中文自检", self.text)

    def test_self_check_covers_the_two_new_principle_fields(self) -> None:
        self.assertIn("失效边界", self.text)
        self.assertIn("情报前提", self.text)

    def test_bilingual_mode_is_conditional(self) -> None:
        self.assertIn("en_requested.flag", self.text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -X utf8 -m pytest tests/test_agent_contracts.py -v
```

Expected: FAIL — `FileNotFoundError: agents/case-builder.md`

- [ ] **Step 3: 改写 skill-assembler.md**

把 `agents/skill-assembler.md` 中所有关于「生成双语草稿 → 合并 SKILL.md」的表述替换为 v6 包组装。核心段落写作：

> ⚠️ **不要在这个文件里写出英文区块标记的字面量。** 本任务的测试
> `test_no_longer_merges_bilingual_blocks` 断言该字面量不出现在 `skill-assembler.md` 中——
> 写「不含 `## Eng`+`lish`」这类说明会让文件被自己的测试判失败。用「不得含英文语言区块」表述。

```markdown
## 产出物

组装 v6 包，共四个文件：

| 文件 | 模板 | 硬约束 |
|---|---|---|
| `output/{slug}/SKILL.md` | `templates/skill-template.v6.zh.md` | frontmatter 含 `format_version: 6`；纯中文；**≤500 行**；不得含英文语言区块；不含语言检测头 |
| `output/{slug}/references/cases.md` | `templates/refs/cases.zh.md` | 由 case-builder 产出，本代理只做收口 |
| `output/{slug}/references/evidence.md` | `templates/refs/evidence.zh.md` | 由 evidence-carder 产出，本代理只做收口 |
| `output/{slug}/references/voice.md` | `templates/refs/voice.zh.md` | ≥20 条样本，每条含正例标注与「误写成通用分析腔」反例 |

另产出 `output/{slug}/人物档案.md`（模板 `templates/refs/dossier.zh.md`）——给人读，**不进安装目录**。

## 不再做的事

- 不再生成英文草稿。英文版是独立 skill，由 Stage 6.5 按用户意愿单独触发。
- 不再合并语言区块，不再写语言检测头。

## 核心层加厚要求

- 原则 **9-11 条**，每条约 900 字，必须含 `失效边界` 与 `情报前提` 两个新字段。
- 必须写「案例索引」章：每个原则簇至少 2 行，全表至少 1 个反例行，每行带 `case_id`。
- 「响应策略」下必须含「附件调用」表，三条触发条件逐字照抄模板——**不得改写为「可酌情参考」之类的软表述**，触发条件是确定性的。

## 自检

组装完成后必须自行运行并通过：

```bash
python scripts/validate_output.py package {slug}
```

若 P6 报 `P6_TOO_LONG`，**减少原则条数**而非压缩每条深度——深度是 v6 的目标。
```

- [ ] **Step 4: 创建 case-builder.md**

创建 `agents/case-builder.md`：

```markdown
---
name: case-builder
description: 从语料与 framework_core.json 构建案例库 references/cases.md
model: haiku
---

# 案例构建器

从 `output/{slug}/framework_core.json` 的 principle_clusters 与 `sources/{slug}/` 的语料，
构建 `output/{slug}/references/cases.md`。模板见 `templates/refs/cases.zh.md`。

## 铁律

1. **每个原则簇至少 2 例。** 少于 2 例的簇必须回到语料补齐，不得以「材料不足」跳过——
   若确实无材料，报告该 cluster_id 并交回编排者裁决，不要编造。
2. **全库至少 1 个反例。** 反例＝此人判断失误、或原则被误用而触碰失效边界的案例。
   只收成功案例会让案例库退化成颂扬集。
3. **首行为证。** 每写一例，必须在工作记录里附上该案例所据语料段落的**首行原文**。
   无法附首行的案例一律不得写入——这是防编造的硬纪律。
4. **每例必须有 `case_id`**，格式 `{slug}-{key}-{year}`，全库唯一。
5. **每例必须标注 `**对应原则簇：** cluster_XXX`**，与 framework_core.json 的 cluster_id 逐字一致。
6. **出处须篇目级**，且案例中的任何直接引文都要能过 P2 逐字校验——
   拿不准就转述，不要加引号。
7. **confidence 分级：** 用户一手材料 = high；网络或转述 = medium。
8. **不写现代商业类比。** 案例是历史事实的记录；把它映射到现代情境是运行期的事，不是建造期的事。

## 自检

```bash
python scripts/validate_output.py package {slug}
```

关注 `P4_TOO_FEW_CASES`、`P4_NO_COUNTER_CASE`、`P4_MISSING_CASE_ID` 三类报错。
```

- [ ] **Step 5: 创建 evidence-carder.md**

创建 `agents/evidence-carder.md`：

```markdown
---
name: evidence-carder
description: 构建证据卡 references/evidence.md，承载逐字原文供 P1/P2 闸门校验
model: haiku
---

# 证据卡构建器

为每条出厂原则建一张证据卡，写入 `output/{slug}/references/evidence.md`。
模板见 `templates/refs/evidence.zh.md`。

## 铁律

1. **逐字，一字不改。** 卡内 blockquote 必须是从语料**连续复制**的原文。
2. **禁止缝合。** 不得把相隔的两段拼成一句。已确证的真实事故：
   出厂引文「如此则月有考，岁有稽，名必中实，事可责成」是三处邻近文本的缝合，
   在语料中最长逐字前缀仅 **3 / 17 字**（且属无锚点巧合命中），而 LLM 评审当时判定它「EXACT」。
3. **禁止静默省略。** 中间略去内容必须写省略号；已确证事故：
   「欲用一人，须慎之于始；既得其人，则信而任之」静默吞掉了原文的「务求相应」。
4. **不改字。** 已确证事故：「毋得彼此推护，徒记空言」——语料作「推诿」「托空言」。
5. **分歧走 `textual_note`，不走沉默。** 若你判定出厂文本正确而语料有讹（如 OCR 讹字），
   保留语料原文之外**追加** `- textual_note：` 说明分歧与裁决依据。
   P2 闸门会把这类条目降级为 WARNING 并记录在案；沉默改字则是 error。
6. **每张卡必须有 `- confidence：high|medium`** 与 `- 语料位置：`（指向实际文件）。

## 自检

```bash
python scripts/validate_output.py package {slug}
```

必须做到 `P2_NOT_IN_CORPUS` 零条（或全部带 `textual_note` 降级为 WARNING）。
报错中的「最长逐字前缀=N字」指出分歧位置：N 远小于全长即缝合（该函数无锚点，短前缀可能是巧合命中，故 N 很少恰为 0），N 接近全长是改字或省略。
```

- [ ] **Step 6: 改写 quality-reviewer.md**

在 `agents/quality-reviewer.md` 的评审维度表中做三处修改：

把「双语一致性」维度改为：

```markdown
| 双语一致性 | **仅在英文分支启用时评审**（存在 `output/{slug}/en_requested.flag`）。默认中文单语包不评此项，权重重新分配给「案例层」。 |
```

新增两个维度。**注意权重不再拼成 100 的字面和**：默认路径下「双语一致性」退出评审、
不计入分母，而新增两项权重之和（25）大于它腾出的 10，所以综合得分必须按
`Σ(得分 × 权重) / Σ(权重)` 的**加权平均**计算，不要试图把各权重硬凑回 100。

```markdown
| 案例层质量（权重 15） | 每个原则簇 ≥2 例？至少 1 个反例？案例是历史事实而非现代类比？case_id 与索引双向对应？（结构合规由 P4/P5 闸门保证，此处只评**内容质量**：案例是否真的展示了该原则的判断过程） |
| 附件可用性（权重 10） | 「附件调用」表的三条触发条件是否逐字保留、未被软化为「可酌情参考」？案例索引是否让模型能在不打开附件时就知道有什么？ |
```

在「引文准确性」维度下追加一行：

```markdown
> **引文逐字性不由本代理判定。** 它由 `scripts/verify_provenance.py` 的 P1/P2 闸门确定性校验。
> 已确证：本代理的前身曾对一组 14 条引文报告「7/7 EXACT」，而其中 4 条实际不是逐字引用。
> 本代理只评**引文选得好不好**（是否切题、是否有代表性），不评**引文对不对**。
```

- [ ] **Step 7: 改写 framework-alignment-reviewer.md 为双模式**

`agents/framework-alignment-reviewer.md` 现在只有双语对齐一种职责。改为双模式，
在文件开头「职责」一节之后插入：

```markdown
## 两种模式（按 `output/{slug}/en_requested.flag` 是否存在自动选择）

### 模式 A：中文自检（默认，无 flag 文件时）

单语路径下不存在「对齐」问题，本代理改做中文框架的结构自检：

1. **决策框架全过滤器化**：每一步是否都是 yes/no 闸门？有无开放式收尾步骤
   （「综合考虑上述因素」之类）？有则退回 Stage 3B 重写。
2. **盲区缓解齐备**：每条盲区是否都带可执行的缓解建议，而非只描述问题？
3. **新增字段齐备**：每条原则是否都有 `失效边界` 与 `情报前提`？
   缺任一字段即退回——这两项是 v6 加厚的核心，不是可选装饰。
4. **失效边界非空泛**：`失效边界` 是否给出了**具体条件**而非「凡事都有例外」式的套话？
5. **原则数在 9-11 之间**。

输出：`output/{slug}/framework_alignment_review.md`，判定 `[PASS]` / `[REVISE]`。

### 模式 B：双语对齐（仅当 `output/{slug}/en_requested.flag` 存在时）

英文分支启用后才执行。职责与改动前一致：检查中英两版是否共享证据底座、
盲区覆盖是否等价、是否滑向「各说各话」。允许原则数量、顺序、语言 framing 差异。
```

- [ ] **Step 8: 运行测试确认通过**

```bash
python -X utf8 -m pytest tests/test_agent_contracts.py -v
```

Expected: PASS — 16 passed（`AgentPathTests` 此时会连带检查 `commands/distill.md`，若该文件尚未改写而引用了不存在的路径，先记下，Task 8 修复）

- [ ] **Step 9: 提交**

```bash
git add agents/ tests/test_agent_contracts.py && git commit -m "feat: rewrite assembler and add case-builder, evidence-carder agents"
```

---

### Task 8: 编排命令与回归协议

**Files:**
- Modify: `commands/distill.md:272-360`（Stage 3）、`:367-440`（Stage 4）、`:441-467`（Stage 5）、`:468-546`（Stage 6）
- Modify: `evaluation/regression-protocol.md`
- Modify: `tests/test_agent_contracts.py`（追加编排契约测试）

**Interfaces:**
- Consumes: Task 3 的 `package` stage、Task 6 的 `publish_skill.py` 目录同步、Task 7 的三个代理
- Produces: 改写后的 `/distill` 编排；新增 Stage 4.5（附件生成）与 Stage 6.5（英文版询问）

- [ ] **Step 1: 写失败测试**

在 `tests/test_agent_contracts.py` 的 `if __name__` 之前追加：

```python
class OrchestratorContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = (ROOT / "commands" / "distill.md").read_text(encoding="utf-8")

    def test_has_attachment_stage(self) -> None:
        self.assertIn("Stage 4.5", self.text)

    def test_has_english_on_demand_stage(self) -> None:
        self.assertIn("Stage 6.5", self.text)

    def test_english_stage_writes_the_flag_file(self) -> None:
        self.assertIn("en_requested.flag", self.text)

    def test_english_installs_to_separate_directory(self) -> None:
        self.assertIn("{person-slug}-wisdom-en", self.text)

    def test_stage3_no_longer_runs_en_synthesizer_by_default(self) -> None:
        self.assertIn("默认只跑中文", self.text)

    def test_checkpoint_uses_package_stage(self) -> None:
        self.assertIn("validate_output.py package", self.text)

    def test_install_copies_references_directory(self) -> None:
        self.assertIn("references/", self.text)

    def test_dossier_excluded_from_install(self) -> None:
        self.assertIn("人物档案.md", self.text)
        install_section = self.text[self.text.index("### 6.3"):]
        self.assertIn("不进安装目录", install_section)


class RegressionProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = (ROOT / "evaluation" / "regression-protocol.md").read_text(encoding="utf-8")

    def test_adds_attachment_read_checkpoint(self) -> None:
        self.assertIn("附件是否被读取", self.text)

    def test_requires_two_successful_attachment_reads(self) -> None:
        self.assertIn("至少 2 次", self.text)

    def test_requires_core_only_turns_to_hold_quality(self) -> None:
        self.assertIn("未读附件", self.text)
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -X utf8 -m pytest tests/test_agent_contracts.py -v -k "Orchestrator or RegressionProtocol"
```

Expected: FAIL — `AssertionError: 'Stage 4.5' not found`

- [ ] **Step 3: 改写 Stage 3（默认单语）**

把 `commands/distill.md:309-335`（Stage 3B）替换为：

```markdown
### Stage 3B：中文框架生成（framework-synthesizer-zh，1 个）

**默认只跑中文。** 英文合成器不在默认路径上——它由 Stage 6.5 按用户意愿单独触发。

- 输入：`output/{slug}/framework_core.json`
- 输出：`output/{slug}/frameworks.zh.json`
- 原则数：**9-11 条**（`config/defaults.json` 的 min_principles/max_principles）
- 每条原则必须含新增的两个字段：`failure_boundary`（失效边界）与 `prerequisite_intel`（情报前提）

### Stage 3C：中文自检（framework-alignment-reviewer，1 个）

单语路径下，本阶段不做双语对齐，改做中文自检：

- 决策框架每一步是否都是过滤器型（yes/no 闸门），无开放式收尾步骤
- 每条盲区是否都带缓解建议
- 每条原则是否都有 `failure_boundary` 与 `prerequisite_intel`
- 输出：`output/{slug}/framework_alignment_review.md`
```

- [ ] **Step 4: 改写 Stage 4 并新增 Stage 4.5**

把 `commands/distill.md:367-440`（整个 Stage 4）替换为：

```markdown
## Stage 4：核心层组装

**执行者：skill-assembler 子代理（1 个）**

从 `output/{slug}/frameworks.zh.json` + `templates/skill-template.v6.zh.md` 生成
`output/{slug}/SKILL.md`。

**硬约束：**

- frontmatter 必须含 `format_version: 6`
- 纯中文；**不得含英文语言区块**；**不含**语言检测头
- **≤500 行**（超限时减少原则条数，不压缩每条深度）
- `description` ≤300 字符
- 必须含「案例索引」章与「附件调用」表

## Stage 4.5：附件生成

三个附件可并行生成：

| 子代理 | 产出 | 模板 |
|---|---|---|
| evidence-carder | `output/{slug}/references/evidence.md` | `templates/refs/evidence.zh.md` |
| case-builder | `output/{slug}/references/cases.md` | `templates/refs/cases.zh.md` |
| skill-assembler（续） | `output/{slug}/references/voice.md` | `templates/refs/voice.zh.md` |

另由 skill-assembler 产出 `output/{slug}/人物档案.md`（模板 `templates/refs/dossier.zh.md`）。

附件齐备后回写核心层的「案例索引」表——索引的 case_id 必须与 `cases.md` 双向一一对应（P5 闸门）。

### ✓ 检查点 4：包校验

```bash
python scripts/validate_output.py package {slug}
```

六道闸门全过方可进入 Stage 5。常见报错处置：

| 报错 | 处置 |
|---|---|
| `P2_NOT_IN_CORPUS` | 回 evidence-carder 改逐字引文；确属底本讹字则加 `textual_note` |
| `P4_TOO_FEW_CASES` | 回 case-builder 补该 cluster 的案例 |
| `P5_INDEX_ORPHAN` / `P5_CASE_NOT_INDEXED` | 同步核心层索引与 cases.md |
| `P6_TOO_LONG` | 减原则条数，不压深度 |
```

- [ ] **Step 5: 改写 Stage 6 安装块并新增 Stage 6.5**

把 `commands/distill.md:491-516`（6.3 执行安装）替换为：

```markdown
### 6.3 执行安装（如用户选择 [1]）

```bash
# 发布到 gallery 并写 manifest（脚本会自动识别 v6 包并同步 references/）
python scripts/publish_skill.py --slug {slug}

# 安装到 Claude Code。白名单：只有 SKILL.md 与 references/ 进安装目录
mkdir -p ~/.claude/skills/{person-slug}-wisdom/references/
cp gallery/{slug}/SKILL.md ~/.claude/skills/{person-slug}-wisdom/SKILL.md
cp gallery/{slug}/references/*.md ~/.claude/skills/{person-slug}-wisdom/references/
```

**`人物档案.md` 不进安装目录**——它只留在 `gallery/{slug}/` 供人阅读。
把一份第三人称档案放进 skill 目录会诱发人称漂移，违反第一人称沉浸铁律。

发布后必须立即校验：

```bash
python scripts/validate_output.py gallery {slug}
```

此检查会逐文件比对 output/ 与 gallery/ 的哈希（v6 包含全部 references）。
失败时不得宣称安装完成——先重新同步再重跑。

### 6.5 询问是否生成英文版

中文包安装完成后询问用户：

> 中文版已完成并安装。是否同时生成英文版？英文版会作为**独立 skill**
> （`{person-slug}-wisdom-en`）发布，是独立的认知重构而非翻译，需要额外一轮合成与审查。

**用户选择「否」→ 蒸馏结束。** 这是默认路径。

**用户选择「是」→ 执行英文分支：**

```bash
# 标记英文分支已启用，校验器据此要求 frameworks.en.json
echo "requested" > output/{slug}/en_requested.flag
```

英文分支复用语言中立的 `framework_core.json`，依次执行：

1. Stage 3B-en：framework-synthesizer-en → `output/{slug}/frameworks.en.json`
   （**独立重构，不看中文产物**——Rule 4 的独立成篇原则在分支内完整保留）
2. Stage 3C-en：framework-alignment-reviewer → 中英覆盖等价性审查
3. Stage 4-en：skill-assembler → `output/{slug}-en/SKILL.md` + `references/`
   （模板 `templates/skill-template.en.md`）
4. Stage 5-en：quality-reviewer（此时启用「双语一致性」维度）
5. 安装到 `~/.claude/skills/{person-slug}-wisdom-en/`，
   gallery 条目 `lang: "en"`、slug 为 `{slug}-en`
```

同时把 `commands/distill.md:517-533`（6.4 index.json 条目）的 JSON 追加三个字段：

```json
{
  "slug": "{slug}",
  "name_zh": "{人物中文名}",
  "name_en": "{Person English Name}",
  "lang": "zh",
  "format_version": 6,
  "has_attachments": true,
  "primary_category": "{category_id}",
  "secondary_categories": ["{cat2}", "{cat3}"],
  "distilled_on": "{YYYY-MM-DD}",
  "review_status": "PASS",
  "skill_dir": "gallery/{slug}/"
}
```

并把第 10 行的命令描述从「产出双语（中文 + 英文）的 Claude Code Skill 文件」改为
「产出中文 Claude Code Skill 包（英文版按需追加）」。

- [ ] **Step 6: 更新回归协议**

在 `evaluation/regression-protocol.md` 的「三、通过线」一节追加：

```markdown
### v6 包附加检查（≥8 轮压测）

v6 包多了一层按需附件，而**附件不被读＝附件层无效**。因此压测必须实测读取行为，
不能假设模型会读：

1. **附件是否被读取。** 压测题目须至少包含：2 道追问出处/质疑引文的题（应触发
   `references/evidence.md`）、2 道描述具体处境且命中案例索引的题（应触发
   `references/cases.md`）。记录模型是否真的打开了对应文件。
   **通过线：附件至少被正确触发读取 2 次。**
2. **未读附件的轮次质量不得下降。** 其余轮次模型只用核心层作答，
   其评分不得低于同一人物旧格式的基线分。这条检验 P6「核心自足」在运行期是否真的成立。
3. **附件读取不得挤占正文质量。** 读附件的轮次若出现「大段复述附件内容」而非融入回答，
   记为 P1 缺陷（对应 post-review-tuning-guide 的结构趋同类）。
```

- [ ] **Step 7: 给英文模板补 v6 结构**

Stage 6.5 的英文分支引用 `templates/skill-template.en.md`，但该文件仍是 legacy
双语时代的形状。**只做最小必要改动**（英文分支尚无回归测试集，深度改写属投机）：

在其 frontmatter 中加入 `format_version: 6`，并把文件顶部的开发注释替换为：

```markdown
<!--
  v6 EN package. Produced ONLY by the on-demand English branch (Stage 6.5),
  never on the default path. Installs to {person-slug}-wisdom-en/ as a SEPARATE skill.
  Same hard constraints as the zh core: format_version: 6, <=500 lines,
  no language-detection header, no ## 中文版 block.
  Attachments live in references/{cases,evidence,voice}.md, same contracts as zh.
  Rule 4 still applies WITHIN this branch: this is an independent cognitive
  reconstruction from framework_core.json, NOT a translation of the Chinese version.
-->
```

英文附件模板暂不新建——英文分支首次被真实触发时再按 zh 模板对译建立。
本步只保证：若有人今天就要英文版，产出的包结构与校验器一致，不会卡在 `NOT_V6`。

- [ ] **Step 8: 运行全量测试**

```bash
python -X utf8 -m pytest tests/ -v
```

Expected: PASS — 全部通过，含 `AgentPathTests` 对 `commands/distill.md` 的路径可解性检查

- [ ] **Step 9: 提交**

```bash
git add commands/distill.md templates/skill-template.en.md evaluation/regression-protocol.md tests/test_agent_contracts.py && git commit -m "feat: rewrite orchestrator for zh-first v6 packages with on-demand English"
```

---

### Task 9: 溯源闸门实弹校验（zhang-juzheng 阳性对照）

**Files:**
- Create: `scripts/audit_legacy_quotes.py`
- Create: `tests/test_zhang_provenance_audit.py`

> 注：本任务**不**产出 `output/zhang-juzheng/references/evidence.md`——证据卡属 Task 10 的样板包。
> Task 9 只做只读审计，不写任何 `output/` 产物。

**Interfaces:**
- Consumes: Task 1/2 的 `verify_provenance` 全部函数
- Produces: `audit_legacy_quotes.audit(slug: str, root: Path) -> dict` — 返回 `{"total": int, "passed": int, "failed": list[dict]}`

本任务在写任何 v6 内容之前，先用真实数据验证闸门有效。它有**已知的阳性对照**：
14 条引文中恰有 4 条应当失败，且三种缺陷类型各不相同。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_zhang_provenance_audit.py`：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -X utf8 -m pytest tests/test_zhang_provenance_audit.py -v
```

Expected: FAIL — `RuntimeError: Could not load module from .../scripts/audit_legacy_quotes.py`

- [ ] **Step 3: 实现审计脚本**

创建 `scripts/audit_legacy_quotes.py`：

```python
#!/usr/bin/env python3
"""
对既有 frameworks.{lang}.json 的出厂引文做逐字审计。

用于把存量产物的溯源缺陷显性化，也是 P2 闸门的实弹验证工具。
Run: python scripts/audit_legacy_quotes.py <slug>
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass


def _load_provenance(root: Path):
    path = root / "scripts" / "verify_provenance.py"
    spec = importlib.util.spec_from_file_location("verify_provenance", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def collect_quotes(framework: dict) -> list[tuple[str, str]]:
    """从 frameworks.zh.json 收集所有出厂引文：原则原文 + 标志性名言。"""
    quotes: list[tuple[str, str]] = []
    for principle in framework.get("core_principles", []):
        text = principle.get("original_quote", "")
        if text:
            quotes.append((f"principle{principle.get('order', '?')}", text))
    for i, quote in enumerate(framework.get("signature_quotes", []), 1):
        text = quote.get("text", "")
        if text:
            quotes.append((f"quote{i}", text))
    return quotes


def audit(slug: str, root: Path) -> dict:
    prov = _load_provenance(root)
    framework_path = root / "output" / slug / "frameworks.zh.json"
    framework = json.loads(framework_path.read_text(encoding="utf-8-sig"))
    corpus = prov.load_corpus(slug, root)
    passed = 0
    failed: list[dict] = []
    quotes = collect_quotes(framework)
    for tag, quote in quotes:
        hit = prov.find_verbatim(quote, corpus)
        if hit:
            passed += 1
            continue
        failed.append({
            "tag": tag,
            "quote": quote,
            "longest_prefix": prov.longest_verbatim_prefix(quote, corpus),
        })
    return {"total": len(quotes), "passed": passed, "failed": failed}


def main() -> int:
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <slug>")
        return 1
    slug = sys.argv[1]
    root = Path(__file__).resolve().parent.parent
    result = audit(slug, root)
    print(f"逐字审计 '{slug}': {result['passed']}/{result['total']} PASS")
    for item in result["failed"]:
        print(f"  FAIL {item['tag']:12s} 最长逐字前缀={item['longest_prefix']:2d}字  「{item['quote'][:32]}」")
    return 0 if not result["failed"] else 2


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 运行测试确认通过**

```bash
python -X utf8 -m pytest tests/test_zhang_provenance_audit.py -v
```

Expected: PASS — 6 passed

- [ ] **Step 5: 人工确认审计输出与实测基线一致**

```bash
python -X utf8 scripts/audit_legacy_quotes.py zhang-juzheng
```

Expected: 输出 `逐字审计 'zhang-juzheng': 10/14 PASS`，其后 4 行 FAIL，
最长逐字前缀分别为 3、3、21、9（两条 3 是同一句 principle1 与 quote2），退出码 2。

- [ ] **Step 6: 提交**

```bash
git add scripts/audit_legacy_quotes.py tests/test_zhang_provenance_audit.py && git commit -m "feat: add legacy quote audit with zhang-juzheng positive control"
```

---

### Task 10: 样板包（zhang-juzheng v6）与验收

**Files:**
- Create: `output/zhang-juzheng-v6/SKILL.md`
- Create: `output/zhang-juzheng-v6/references/{cases,evidence,voice}.md`
- Create: `output/zhang-juzheng-v6/人物档案.md`
- Create: `output/zhang-juzheng-v6/framework_core.json`（从 `output/zhang-juzheng/framework_core.json` 复制）
- Create: `scripts/measure_package.py`

**Interfaces:**
- Consumes: 前九个任务的全部产出
- Produces: `measure_package.measure(slug: str, root: Path) -> dict` — 返回验收指标 `{"lines", "evidence_survival_pct", "cases", "counter_cases", "clusters_covered"}`

> 用 `zhang-juzheng-v6` 作为独立 slug，**不覆盖** `output/zhang-juzheng/`——
> 存量产物是 Task 9 的阳性对照，必须原样保留。

- [ ] **Step 1: 准备样板目录**

```bash
mkdir -p output/zhang-juzheng-v6/references && cp output/zhang-juzheng/framework_core.json output/zhang-juzheng-v6/framework_core.json && ln -sfn "$(pwd)/sources/zhang-juzheng" sources/zhang-juzheng-v6 2>/dev/null || cp -r sources/zhang-juzheng sources/zhang-juzheng-v6
```

确认语料可达：

```bash
python -X utf8 -c "
import sys; sys.path.insert(0,'scripts')
import verify_provenance as p
from pathlib import Path
print('语料文件数:', len(p.load_corpus('zhang-juzheng-v6', Path('.'))))
"
```

Expected: `语料文件数: 12` 或更多

- [ ] **Step 2: 写验收度量脚本的失败测试**

创建 `tests/test_measure_package.py`：

```python
from __future__ import annotations

import importlib.util
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


measure_mod = load_module("measure_package", ROOT / "scripts" / "measure_package.py")


class MeasureTests(unittest.TestCase):
    def _build(self, root: Path) -> None:
        out = root / "output" / "demo"
        refs = out / "references"
        refs.mkdir(parents=True)
        (out / "SKILL.md").write_text(
            "---\nname: demo-wisdom\nformat_version: 6\n---\n\n# 标题\n\n正文一行\n",
            encoding="utf-8",
        )
        (refs / "evidence.md").write_text(
            "### 原则 1：甲\n\n> 月有考岁有稽\n\n- confidence：high\n", encoding="utf-8"
        )
        (refs / "cases.md").write_text(
            "### 案例 1：甲（case_id: demo-a-1，high）\n\n**对应原则簇：** cluster_001\n\n略\n\n"
            "### 案例 2：乙（case_id: demo-b-1，high）\n\n**对应原则簇：** cluster_001\n\n反例：略\n",
            encoding="utf-8",
        )
        (refs / "voice.md").write_text("### 样本 1\n\n> 略\n", encoding="utf-8")
        processed = root / "sources" / "demo" / "processed"
        processed.mkdir(parents=True)
        (processed / "user_sources.json").write_text(
            '{"extracts":[{"text":"月有考岁有稽，事可责成，凡二十字整。"}]}', encoding="utf-8"
        )

    def test_counts_lines(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._build(root)
            result = measure_mod.measure("demo", root)
            self.assertEqual(result["lines"], 7)

    def test_counts_cases_and_counter_cases(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._build(root)
            result = measure_mod.measure("demo", root)
            self.assertEqual(result["cases"], 2)
            self.assertEqual(result["counter_cases"], 1)

    def test_computes_evidence_survival_percentage(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._build(root)
            result = measure_mod.measure("demo", root)
            self.assertGreater(result["evidence_survival_pct"], 0)
            self.assertLessEqual(result["evidence_survival_pct"], 100)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: 运行测试确认失败**

```bash
python -X utf8 -m pytest tests/test_measure_package.py -v
```

Expected: FAIL — `RuntimeError: Could not load module from .../scripts/measure_package.py`

- [ ] **Step 4: 实现度量脚本**

创建 `scripts/measure_package.py`：

```python
#!/usr/bin/env python3
"""
v6 包验收度量。Run: python scripts/measure_package.py <slug>

对照规格 §八 的验收标准输出可比数字。
"""

from __future__ import annotations

import glob
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass


def _load_provenance(root: Path):
    path = root / "scripts" / "verify_provenance.py"
    spec = importlib.util.spec_from_file_location("verify_provenance", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def measure(slug: str, root: Path) -> dict:
    prov = _load_provenance(root)
    out = root / "output" / slug
    refs = out / "references"

    skill_text = (out / "SKILL.md").read_text(encoding="utf-8")
    lines = len(skill_text.splitlines())

    # 分母：processed/ 下所有 extracts[].text 的归一化字数
    denominator = 0
    for path in sorted((root / "sources" / slug / "processed").glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        for extract in data.get("extracts", []) if isinstance(data, dict) else []:
            denominator += len(prov.normalize(extract.get("text", "")))

    # 分子：核心层 + 证据卡的逐字引文，去重
    verbatim: set[str] = set()
    for _, quote in prov.extract_skill_quotes(skill_text):
        verbatim.add(prov.normalize(quote))
    evidence_path = refs / "evidence.md"
    if evidence_path.exists():
        for card in prov.parse_evidence_cards(evidence_path.read_text(encoding="utf-8")):
            verbatim.add(prov.normalize(card["verbatim"]))
    numerator = sum(len(v) for v in verbatim if v)

    cases = counter = 0
    clusters: set[str] = set()
    cases_path = refs / "cases.md"
    if cases_path.exists():
        text = cases_path.read_text(encoding="utf-8")
        blocks = re.split(r"^###\s+", text, flags=re.MULTILINE)[1:]
        cases = len(blocks)
        counter = sum(1 for b in blocks if "反例" in b)
        clusters = set(re.findall(r"^\*\*对应原则簇：\*\*\s*(\S+)\s*$", text, re.MULTILINE))

    return {
        "lines": lines,
        "evidence_chars": numerator,
        "corpus_chars": denominator,
        "evidence_survival_pct": round(100 * numerator / denominator, 2) if denominator else 0.0,
        "cases": cases,
        "counter_cases": counter,
        "clusters_covered": len(clusters),
    }


def main() -> int:
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <slug>")
        return 1
    root = Path(__file__).resolve().parent.parent
    result = measure(sys.argv[1], root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: 运行测试确认通过**

```bash
python -X utf8 -m pytest tests/test_measure_package.py -v
```

Expected: PASS — 3 passed

- [ ] **Step 6: 生成样板包内容**

按 Stage 4 / 4.5 的代理契约生成四个文件。内容生成规则（供执行者遵循）：

- `output/zhang-juzheng-v6/references/evidence.md`：为每条出厂原则建卡。
  **Task 9 已确证 4 条引文不是逐字引用**——这 4 条必须改为语料原文：
  - 「如此，月有考，岁有稽，不惟使声必中实，事可责成」（取代缝合版）
  - 「毋得彼此推诿，徒托空言」（取代「推护/记空言」）
  - 「欲用一人，须慎之于始，务求相应；既得其人，则信而任之」（补回被吞掉的「务求相应」）
  若判定出厂旧文本更接近传世本（如 `名` vs OCR 的 `声`），保留语料原文并加 `- textual_note：`。
- `output/zhang-juzheng-v6/references/cases.md`：9 个 cluster × ≥2 例 + ≥1 反例。
  夺情之争、考成法逼出冤案是天然的反例素材（已在旧 SKILL.md 的盲区章中有据）。
- `output/zhang-juzheng-v6/references/voice.md`：从
  `sources/zhang-juzheng/processed/expression_dna.json` 的 26 条提取中取 ≥20 条建样本。
- `output/zhang-juzheng-v6/SKILL.md`：9-11 条原则，每条约 900 字，含失效边界与情报前提；
  含案例索引表与附件调用表。

- [ ] **Step 7: 跑六道闸门**

```bash
python -X utf8 scripts/validate_output.py package zhang-juzheng-v6
```

Expected: `✅ Stage 'package' passed for 'zhang-juzheng-v6'`，退出码 0。
若 `P2_NOT_IN_CORPUS` 仍有非 WARNING 条目，回 Step 6 修引文——这正是闸门在起作用。

- [ ] **Step 8: 度量并对照验收标准**

```bash
python -X utf8 scripts/measure_package.py zhang-juzheng-v6
```

Expected（对照规格 §八）：
- `lines` ≤ 500
- `evidence_survival_pct` ≥ 15.0（基线 1.80）
- `cases` ≥ 18（9 个 cluster × 2）
- `counter_cases` ≥ 1
- `clusters_covered` == 9

- [ ] **Step 9: 确认存量零回归**

```bash
python -X utf8 -m pytest tests/ -v && for s in $(python -X utf8 -c "
import json
print(' '.join(e['slug'] for e in json.load(open('gallery/index.json',encoding='utf-8'))['skills']))
"); do printf '%-22s ' "$s"; if python -X utf8 scripts/validate_output.py gallery "$s" >/dev/null 2>&1; then echo OK; else echo FAIL; fi; done > /tmp/gallery_now.txt; diff .superpowers/sdd/2026-08-23-skill-package-v6/gallery-baseline.txt /tmp/gallery_now.txt && echo "存量行为零变化"
```

Expected: 测试全绿；`存量行为零变化`（基线 23 OK / 1 FAIL，charlie-munger 恒 FAIL 属既有状态）

- [ ] **Step 10: 提交**

```bash
git add output/zhang-juzheng-v6/ scripts/measure_package.py tests/test_measure_package.py && git commit -m "feat: build zhang-juzheng v6 pilot package and acceptance metrics"
```

---

## 剩余的运行期验收（不在本计划内）

规格 §八 第 6 条——**≥8 轮压测中附件至少被正确触发读取 2 次**——需要真人对话，
无法由本计划的自动化步骤完成。样板包安装后按
`evaluation/regression-protocol.md` 的「v6 包附加检查」执行。

这是整个设计**最大的未验证假设**：附件不被读＝附件层无效。
在这一条通过之前，不要把 v6 铺开到其他人物。
