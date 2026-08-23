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
