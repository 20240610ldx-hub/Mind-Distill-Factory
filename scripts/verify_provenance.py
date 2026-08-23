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
    """返回繁→简转换函数；opencc 未安装或初始化失败时返回 None（降级为不折叠）。"""
    try:
        import opencc  # type: ignore

        converter = opencc.OpenCC("t2s")
    except Exception:
        return None
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
            text = path.read_text(encoding="utf-8", errors="replace")
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
    """返回 needle 归一化后最长前缀的长度，使该前缀作为子串出现在语料某处。

    注意：匹配是不锚定的（unanchored）——只判断 needle[:L] 是否作为子串出现在
    语料的任意位置，不要求它出现在 needle 原本引用的上下文里。因此，当前缀较短
    （相对 needle 总长而言）时，命中很可能只是常见字词的巧合重叠，基本不代表
    存在逐字依据；只有当返回值接近 len(normalize(needle)) 时才说明大部分文本
    确有逐字来源。本函数返回的是诊断性提示，不是精确的分歧位置（divergence
    offset）。"""
    probe = normalize(needle)
    for length in range(len(probe), 0, -1):
        prefix = probe[:length]
        if any(prefix in text for _, text in corpus):
            return length
    return 0


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
