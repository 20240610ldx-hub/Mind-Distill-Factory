#!/usr/bin/env python3
"""语料清洗与质量闸门（由 `mdf index` 调用；`mdf clean` 查看报告）。

设计约束：**只删不改**。P2 溯源拿引文去 raw 里逐字比对，所以清洗只能整行/整段/整页
地删除噪声（版权页、网站广告、页码、页眉页脚、索引与目录），绝不改写保留下来的字符
（不做繁简转换、不改标点、不拼接断词）。删掉了什么都写进报告，人可以复核。

每个来源得到一个结论：
    accepted   可以进入分片
    flagged    可以进入分片，但需要人工复核（报告里写明原因）
    rejected   不进入分片：乱码、空文本、私用区字形、OCR 缺失过多……
    duplicate  与另一来源完全相同或高度重合，不重复抽取

报告写在 sources/{slug}/processed/cleaning_report.json（不含时间戳，同输入同输出）。
"""

import argparse
import json
import os
import re
import sys
import zlib
from pathlib import Path
from typing import Any, Iterable
_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:  # 按路径加载本模块时也能找到同目录的 workspace
    sys.path.insert(0, _SCRIPTS_DIR)
from workspace import data_root  # noqa: E402  数据根解析规则只在 workspace.py 定义

SCHEMA = "cleaning-report-v1"
CODE_ROOT = Path(__file__).resolve().parent.parent

# ── 阈值（集中在一处，改动请同步 docs/methodology.md）──────────────────
THRESHOLDS = {
    "fffd_flag": 0.0005,          # U+FFFD 占非空白字符比例
    "fffd_reject": 0.005,
    "pua_flag": 0.001,            # 私用区字形（PDF 字体映射失败的典型症状）
    "pua_reject": 0.05,           # 真实样本：OCR 把数字识别成私用区字形约 1.4%，正文仍可用 → 只标记
    "control_flag": 0.001,
    "mojibake_min_hits": 20,      # 乱码标记的最少出现次数
    "latin_mojibake_ratio": 0.002,
    "gbk_mojibake_ratio": 0.005,  # 相对 CJK 字符数
    "very_short_chars": 200,
    "running_head_min": 8,        # 文本文件里重复短行：至少出现次数
    "running_head_share": 0.02,   # ……且占非空行比例
    "pdf_head_share": 0.3,        # PDF 页眉页脚：至少出现在 30% 的有字页
    "pdf_head_min_pages": 3,
    "index_run_min": 12,          # 连续索引/目录行
    "index_page_share": 0.6,
    "index_page_min_lines": 10,
    "annotation_min_hits": 3,
    "ocr_missing_reject": 0.5,    # 需要 OCR 却没拿到文字的页占比
    # OCR 阈值来自 `mdf ocr calibrate` 实测（docs/methodology.md「OCR 校准」，64 次运行）：平均置信度
    # <0.9 的各次运行逐字存活率都 ≤58%；<0.6 的 CER 都在 71% 以上、逐字存活为 0，已是乱码。
    "ocr_low_confidence": 0.9,
    "ocr_garbled_reject": 0.6,
    "near_duplicate_jaccard": 0.85,
    "contained_share": 0.9,
}

CJK_RE = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
PUA_RE = re.compile(r"[\ue000-\uf8ff]")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0e-\x1f\x7f]")
# UTF-8 被当成 cp1252/latin-1 读出的典型片段：Ã© â€™ Â
LATIN_MOJIBAKE_RE = re.compile(r"Ã[\u0080-¿]|â€[\u0080-¿‐-›™]|Â[\u00a0-¿]")
# UTF-8 中文被当成 GBK 读出的典型字：，→锛 。→銆 “→鈥 的→鐨 是→鏄
GBK_MOJIBAKE_CHARS = "锛銆鈥鐨鏄"

GUTENBERG_START_RE = re.compile(r"^\*{3}\s*START OF (?:THE |THIS )?PROJECT GUTENBERG E-?BOOK.*$", re.I | re.M)
GUTENBERG_END_RE = re.compile(r"^\*{3}\s*END OF (?:THE |THIS )?PROJECT GUTENBERG E-?BOOK.*$", re.I | re.M)
# Google 扫描书卷首的使用须知：至少命中两条才认定（研究笔记里单独提到 Google Books 不算）。
GOOGLE_DISCLAIMER_MARKERS = (
    "digital copy of a book that was preserved", "Google Book Search", "non-commercial use of the files",
    "Maintain attribution", "Keep it legal", "automated querying",
)

# 显式页码标记是引用定位的依据（「语料位置」），任何规则都不得删除。
PAGE_MARKER_RE = re.compile(
    r"^\s*(?:≦\s*\d+\s*≧|=+\s*(?:PDF_)?PAGE\s*\d+\s*=+|-{2,}\s*Page\s+\d+(?:\s*\(OCR[^)]*\))?\s*-{2,})\s*$", re.I
)
PAGE_NUMBER_RE = re.compile(
    r"^\s*(?:[-–—]\s*\d{1,4}\s*[-–—]|\d{1,4}(?:\s+\d{1,4})?|第\s*\d{1,4}\s*页|page\s+\d{1,4}|\d{1,4}\s*/\s*\d{1,4})\s*$",
    re.I,
)
# 网站/电子书广告：必须同时有强线索词与广告动词。单字「网」「站」会误伤正文
# （真实语料里「神经网络……提供」「海外营业网点」都曾被误删）。
AD_CUE_RE = re.compile(
    r"电子书|二维码|公众号|粉丝群|书友群|读者群|z-?library|1lib|www\.|\.com\b|\.cn\b|\.net\b|txt下载|TXT下载", re.I
)
AD_VERB_RE = re.compile(r"提供|整理|收集|下载|访问|关注|扫码|加入|免费|更多|尽在|转载")
HEAVY_REMOVAL_SHARE = 0.10  # 行规则删掉超过 10% 的字符 → 需要人工复核
INDEX_LINE_RE = re.compile(r"[,，、]\s*\d{1,4}(?:\s*[-–—]\s*\d{1,4})?\s*$")
TOC_LINE_RE = re.compile(r"(?:\.{3,}|…{2,}|·{3,}|\s{4,})\s*\d{1,4}\s*$")
ANNOTATION_MARKERS = (
    "【注释】", "【译文】", "【注】", "【译】", "【评析】", "【解读】", "【今译】", "【题解】", "【赏析】",
    "注释：", "译文：", "今译：", "白话译文", "译者注", "编者注", "校注：",
    "Translator's Note", "Editor's Note", "Translator’s Note", "Editor’s Note",
)
MAX_SAMPLES = 5


def _non_space(text: str) -> int:
    return sum(1 for ch in text if not ch.isspace())


def _norm_line(line: str) -> str:
    return re.sub(r"\d+", "#", line.strip())


# OCR 常把页码两边的短横认成「一」或认丢一边（《熱風》：「-28一」「13-」「一81一」），
# 逐字比较时这些变体各自凑不够页数。页边行只有数字和横线时，一律按「页码」计数。
PDF_PAGE_NO_RE = re.compile(r"^[\s\-–—一_.·]*\d{1,4}[\s\-–—一_.·]*$")


def _head_key(line: str) -> str:
    return "#页码" if PDF_PAGE_NO_RE.match(line) else _norm_line(line)


def text_metrics(text: str) -> dict[str, Any]:
    chars = _non_space(text)
    cjk = len(CJK_RE.findall(text))
    gbk_hits = sum(text.count(ch) for ch in GBK_MOJIBAKE_CHARS)
    return {
        "chars": chars,
        "cjk_chars": cjk,
        "fffd": text.count("\ufffd"),
        "pua": len(PUA_RE.findall(text)),
        "control": len(CONTROL_RE.findall(text)),
        "latin_mojibake": len(LATIN_MOJIBAKE_RE.findall(text)),
        "gbk_mojibake": gbk_hits,
    }


def assess(metrics: dict[str, Any], t: dict[str, float] = THRESHOLDS) -> tuple[list[str], list[str]]:
    """按指标给出（拒绝原因, 复核标记）。"""
    reasons: list[str] = []
    flags: list[str] = []
    chars = max(1, metrics["chars"])
    if metrics["chars"] == 0:
        return ["empty_after_cleaning"], flags
    for key, flag_at, reject_at, label in (
        ("fffd", t["fffd_flag"], t["fffd_reject"], "replacement_chars"),
        ("pua", t["pua_flag"], t["pua_reject"], "private_use_glyphs"),
    ):
        ratio = metrics[key] / chars
        if ratio > reject_at:
            reasons.append(label)
        elif ratio > flag_at:
            flags.append(label)
    if metrics["latin_mojibake"] >= t["mojibake_min_hits"] and metrics["latin_mojibake"] / chars > t["latin_mojibake_ratio"]:
        reasons.append("mojibake_utf8_as_latin")
    cjk = max(1, metrics["cjk_chars"])
    if metrics["gbk_mojibake"] >= t["mojibake_min_hits"] and metrics["gbk_mojibake"] / cjk > t["gbk_mojibake_ratio"]:
        reasons.append("mojibake_utf8_as_gbk")
    if metrics["control"] / chars > t["control_flag"]:
        flags.append("control_chars")
    if metrics["chars"] < t["very_short_chars"]:
        flags.append("very_short")
    return reasons, flags


class Cleaner:
    """累积一份来源的删除动作与样例。"""

    BOILERPLATE_ACTIONS = {"gutenberg_boilerplate_chars", "scan_disclaimer_paragraphs"}

    def __init__(self) -> None:
        self.actions: dict[str, int] = {}
        self.samples: dict[str, list[str]] = {}
        self.line_rule_chars = 0  # 行/页规则删掉的非空白字符数（不含整段版权声明）

    def record(self, action: str, removed: Iterable[str] = (), count: int | None = None) -> None:
        removed = list(removed)
        n = len(removed) if count is None else count
        if not n:
            return
        self.actions[action] = self.actions.get(action, 0) + n
        if action not in self.BOILERPLATE_ACTIONS:
            self.line_rule_chars += sum(_non_space(line) for line in removed)
        bucket = self.samples.setdefault(action, [])
        for line in removed:
            line = line.strip()[:80]
            if line and line not in bucket and len(bucket) < MAX_SAMPLES:
                bucket.append(line)

    # ── 整段规则 ──────────────────────────────────────────────────────

    def strip_gutenberg(self, text: str) -> str:
        start, end = GUTENBERG_START_RE.search(text), GUTENBERG_END_RE.search(text)
        if not start:
            return text
        body = text[start.end(): end.start() if end and end.start() > start.end() else len(text)]
        self.record("gutenberg_boilerplate_chars", count=len(text) - len(body))
        return body

    def strip_google_disclaimer(self, text: str, window: int = 6000) -> str:
        head, tail = text[:window], text[window:]
        lowered = head.lower()
        if sum(1 for m in GOOGLE_DISCLAIMER_MARKERS if m.lower() in lowered) < 2:
            return text
        paragraphs = re.split(r"(\n\s*\n)", head)
        kept, removed = [], []
        for part in paragraphs:
            hit = any(m.lower() in part.lower() for m in GOOGLE_DISCLAIMER_MARKERS)
            (removed if hit else kept).append(part)
        if removed:
            self.record("scan_disclaimer_paragraphs", removed)
        return "".join(kept) + tail

    # ── 行规则 ────────────────────────────────────────────────────────

    def strip_noise_lines(self, lines: list[str]) -> list[str]:
        page_numbers = [ln for ln in lines if PAGE_NUMBER_RE.match(ln)]
        drop_page_numbers = len(page_numbers) >= 3  # 零星的单独数字可能是正文（章节号等）
        kept = []
        for line in lines:
            stripped = line.strip()
            if PAGE_MARKER_RE.match(line):
                kept.append(line)
            elif drop_page_numbers and PAGE_NUMBER_RE.match(line):
                self.record("page_number_lines", [line])
            elif len(stripped) <= 80 and AD_CUE_RE.search(stripped) and AD_VERB_RE.search(stripped):
                self.record("site_ad_lines", [line])
            else:
                kept.append(line)
        return kept

    def strip_repeated_lines(self, lines: list[str], t: dict[str, float] = THRESHOLDS) -> list[str]:
        """删除文本文件里的页眉页脚：重复出现、且大多紧挨分页处（页码或页标记旁）的短行。

        真实语料校准后的三条限制：
        - 带数字的行不删（「FEDERALIST 2」是篇目、「Page 3 of 128」是页码，都是引用定位依据）；
        - 说话人标签不删（「问：」「Q」），删了会丢失「谁说的」；
        - 没有分页迹象的文本不删（《林肯全集》里重复 164 次的「To Edwin M. Stanton」是信件抬头）。
        """
        nonblank = [ln.strip() for ln in lines if ln.strip()]
        boundaries = [i for i, ln in enumerate(nonblank) if PAGE_MARKER_RE.match(ln) or PAGE_NUMBER_RE.match(ln)]
        if not boundaries:
            return lines
        near: set[int] = set()
        for b in boundaries:
            near.update(range(b - 2, b + 3))
        counts: dict[str, int] = {}
        near_counts: dict[str, int] = {}
        for i, line in enumerate(nonblank):
            if (PAGE_MARKER_RE.match(line) or re.search(r"\d", line) or _non_space(line) < 4 or len(line) > 40
                    or line.endswith((":", "：")) or not re.search(r"[^\W\d_]", line)):
                continue
            counts[line] = counts.get(line, 0) + 1
            near_counts[line] = near_counts.get(line, 0) + (i in near)
        floor = max(t["running_head_min"], t["running_head_share"] * len(nonblank))
        heads = {k for k, n in counts.items() if n >= floor and near_counts[k] >= 0.6 * n}
        if not heads:
            return lines
        kept = []
        for line in lines:
            if line.strip() in heads:
                self.record("running_head_lines", [line])
            else:
                kept.append(line)
        return kept

    def strip_index_runs(self, lines: list[str], t: dict[str, float] = THRESHOLDS) -> list[str]:
        """删除连续的索引/目录块（允许夹 1 行不匹配，如字母分节标题）。"""
        marks = [bool(INDEX_LINE_RE.search(ln) or TOC_LINE_RE.search(ln)) if ln.strip() else None for ln in lines]
        drop = [False] * len(lines)
        i = 0
        while i < len(lines):
            if not marks[i]:
                i += 1
                continue
            j, hits, misses, last_hit = i, 0, 0, i
            while j < len(lines):
                if marks[j] is None:
                    j += 1
                    continue
                if marks[j]:
                    hits, misses, last_hit = hits + 1, 0, j
                else:
                    misses += 1
                    if misses > 1:
                        break
                j += 1
            if hits >= t["index_run_min"]:
                for k in range(i, last_hit + 1):
                    drop[k] = True
            i = last_hit + 1
        removed = [ln for ln, d in zip(lines, drop) if d and ln.strip()]
        if removed:
            self.record("index_toc_lines", removed)
        return [ln for ln, d in zip(lines, drop) if not d]


def annotation_markers(text: str) -> dict[str, int]:
    return {m: text.count(m) for m in ANNOTATION_MARKERS if m in text}


def _finish(cleaner: Cleaner, text: str, kind: str, extra_reasons: list[str], extra_flags: list[str],
            meta: dict[str, Any]) -> dict[str, Any]:
    metrics = text_metrics(text)
    reasons, flags = assess(metrics)
    reasons += extra_reasons
    flags += extra_flags
    markers = annotation_markers(text)
    if sum(markers.values()) >= THRESHOLDS["annotation_min_hits"]:
        flags.append("modern_annotation")
    # 例行删除（页眉页脚、页码、索引）不打扰人；删得太多才要求复核。
    if cleaner.line_rule_chars > HEAVY_REMOVAL_SHARE * max(1, int(meta.get("chars_before") or 0)):
        flags.append("heavy_removal")
    verdict = "rejected" if reasons else ("flagged" if flags else "accepted")
    return {
        "kind": kind,
        "verdict": verdict,
        "reasons": sorted(set(reasons)),
        "flags": sorted(set(flags)),
        "actions": dict(sorted(cleaner.actions.items())),
        "samples": {k: v for k, v in sorted(cleaner.samples.items())},
        "annotation_markers": markers,
        "metrics": metrics,
        **meta,
    }


def clean_text(text: str, *, encoding: str = "utf-8", replacements: int = 0) -> tuple[str, dict[str, Any]]:
    """清洗一份文本来源，返回（保留的文本, 报告条目）。"""
    cleaner = Cleaner()
    before = _non_space(text)
    body = text.replace("\r\n", "\n").replace("\r", "\n")
    body = cleaner.strip_gutenberg(body)
    body = cleaner.strip_google_disclaimer(body)
    lines = body.split("\n")
    lines = cleaner.strip_index_runs(lines)
    lines = cleaner.strip_repeated_lines(lines)  # 先于页码删除：要靠页码行判断哪里是分页处
    lines = cleaner.strip_noise_lines(lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() + "\n"
    report = _finish(cleaner, cleaned, "text", [], [], {
        "encoding": encoding, "decode_replacements": replacements,
        "chars_before": before, "chars_after": _non_space(cleaned),
    })
    return cleaned, report


def clean_pdf_pages(pages: list[str], ocr: dict[str, Any] | None = None) -> tuple[list[str], dict[str, Any]]:
    """清洗 PDF 的逐页文本（页数不变，被删的页变成空串），返回（各页文本, 报告条目）。

    ocr: {"pages_total", "ocr_required", "ocr_ok", "mean_confidence"}，来自 index 的页级诊断。
    """
    t = THRESHOLDS
    cleaner = Cleaner()
    before = sum(_non_space(p) for p in pages)
    page_lines = [p.replace("\r\n", "\n").replace("\r", "\n").split("\n") for p in pages]

    # 1. 索引/目录页：整页删除
    for idx, lines in enumerate(page_lines):
        nonblank = [ln for ln in lines if ln.strip()]
        if len(nonblank) >= t["index_page_min_lines"]:
            hits = sum(1 for ln in nonblank if INDEX_LINE_RE.search(ln) or TOC_LINE_RE.search(ln))
            if hits / len(nonblank) >= t["index_page_share"]:
                cleaner.record("index_toc_pages", [nonblank[0]], count=1)
                page_lines[idx] = []

    # 2. 页眉页脚：每页前两行/后两行里，在足够多页上重复出现的（数字归一后比较）
    def edges(lines: list[str]) -> list[str]:
        nonblank = [ln for ln in lines if ln.strip()]
        return nonblank[:2] + nonblank[-2:] if len(nonblank) > 4 else nonblank

    with_text = [lines for lines in page_lines if any(ln.strip() for ln in lines)]
    counts: dict[str, int] = {}
    for lines in with_text:
        for key in {_head_key(ln) for ln in edges(lines) if len(_norm_line(ln)) <= 60}:
            counts[key] = counts.get(key, 0) + 1
    floor = max(t["pdf_head_min_pages"], t["pdf_head_share"] * len(with_text))
    heads = {k for k, n in counts.items() if n >= floor}
    if heads:
        for idx, lines in enumerate(page_lines):
            edge_set = set(edges(lines))
            kept = []
            for ln in lines:
                if ln in edge_set and _head_key(ln) in heads:
                    cleaner.record("pdf_running_head_lines", [ln])
                else:
                    kept.append(ln)
            page_lines[idx] = kept

    # 3. 首三页的扫描版免责声明；逐页行级噪声
    cleaned_pages = []
    for idx, lines in enumerate(page_lines):
        text = "\n".join(lines)
        if idx < 3:
            text = cleaner.strip_google_disclaimer(text)
        lines = cleaner.strip_noise_lines(text.split("\n"))
        cleaned_pages.append(re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip())

    reasons: list[str] = []
    flags: list[str] = []
    ocr = ocr or {}
    total = int(ocr.get("pages_total") or len(pages) or 0)
    required, ok = int(ocr.get("ocr_required") or 0), int(ocr.get("ocr_ok") or 0)
    if required > ok:
        missing = required - ok
        if total and missing / total >= t["ocr_missing_reject"] and not any(cleaned_pages):
            reasons.append("ocr_unavailable")
        elif total and missing / total >= t["ocr_missing_reject"]:
            flags.append("ocr_mostly_missing")
        else:
            flags.append("ocr_incomplete")
    confidence = ocr.get("mean_confidence")
    if ok:
        # 闸门 P2 拿引文去比对的正是这份 OCR 文字，认错的字它查不出来——所以只要用了 OCR 就要标出来
        flags.append("ocr_text")
    if ok and int(ocr.get("suspect_lines") or 0):
        # 检测到文字行却没认出来（印章、透墨、污渍、手写）：缺的行不在语料里，缺口两侧在原书中并不相连
        flags.append("ocr_lines_dropped")
    if ok and confidence is not None and float(confidence) < t["ocr_low_confidence"]:
        if float(confidence) < t["ocr_garbled_reject"] and total and ok * 2 > total:
            reasons.append("ocr_garbled")
        else:
            flags.append("low_ocr_confidence")
    joined = "\n\n".join(p for p in cleaned_pages if p)
    report = _finish(cleaner, joined, "pdf", reasons, flags, {
        "chars_before": before, "chars_after": _non_space(joined),
        "pages": len(pages), "pages_with_text": sum(1 for p in cleaned_pages if p), "ocr": ocr,
    })
    return cleaned_pages, report


# ── 近重复 ────────────────────────────────────────────────────────────

_DEDUP_STRIP_RE = re.compile(r"[\s\W_]+", re.UNICODE)


def fingerprint(text: str, n: int = 8, keep_mod: int = 8) -> set[int]:
    """内容定义的抽样指纹：去空白标点后的 n-gram 取 crc32，只留 hash % keep_mod == 0 的。

    抽样由内容决定（而非位置），两份文本的相同片段总会被同样抽中，所以集合的 Jaccard
    近似原文的 n-gram Jaccard，内存只要 1/keep_mod。
    """
    s = _DEDUP_STRIP_RE.sub("", text)
    out = set()
    for i in range(max(0, len(s) - n + 1)):
        h = zlib.crc32(s[i:i + n].encode("utf-8"))
        if h % keep_mod == 0:
            out.add(h)
    return out


def find_near_duplicates(sources: list[tuple[str, int, str]]) -> dict[str, dict[str, Any]]:
    """sources: [(文件, 优先级, 清洗后文本)]，按给定顺序视为「先到先得」。

    返回 {被判重复的文件: {"duplicate_of": 文件, "relation": "near_duplicate"|"contained", "score": x}}。
    优先级数字小的保留；同优先级保留先出现的。被包含方的优先级更高时两者都保留（只是重合）。
    """
    t = THRESHOLDS
    prints = [(name, prio, fingerprint(text)) for name, prio, text in sources]
    result: dict[str, dict[str, Any]] = {}
    for i, (a, pa, fa) in enumerate(prints):
        if a in result or not fa:
            continue
        for b, pb, fb in prints[i + 1:]:
            if b in result or not fb:
                continue
            inter = len(fa & fb)
            if not inter:
                continue
            jaccard = inter / len(fa | fb)
            keep, drop = (a, b) if pa <= pb else (b, a)
            if jaccard >= t["near_duplicate_jaccard"]:
                result[drop] = {"duplicate_of": keep, "relation": "near_duplicate", "score": round(jaccard, 3)}
            else:
                small, big = (a, b) if len(fa) <= len(fb) else (b, a)
                share = inter / len(fa if small == a else fb)
                p_small, p_big = (pa, pb) if small == a else (pb, pa)
                if share >= t["contained_share"] and p_small >= p_big:
                    result[small] = {"duplicate_of": big, "relation": "contained", "score": round(share, 3)}
            if a in result:
                break
    return result


# ── 报告 ──────────────────────────────────────────────────────────────


def build_report(entries: dict[str, dict[str, Any]]) -> dict[str, Any]:
    files = dict(sorted(entries.items()))
    by = {v: [f for f, e in files.items() if e["verdict"] == v] for v in ("accepted", "flagged", "rejected", "duplicate")}
    return {
        "schema": SCHEMA,
        "source_count": len(files),
        "accepted_sources": by["accepted"],
        "flagged_sources": [{"file": f, "flags": files[f]["flags"]} for f in by["flagged"]],
        "rejected_sources": [{"file": f, "reasons": files[f]["reasons"]} for f in by["rejected"]],
        "duplicate_sources": [{"file": f, **files[f].get("duplicate", {})} for f in by["duplicate"]],
        "thresholds": THRESHOLDS,
        "sources": files,
    }


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


REASON_HINTS = {
    "empty_after_cleaning": "清洗后没有正文（可能整份都是目录/广告，或扫描件没有文字层）",
    "replacement_chars": "大量 U+FFFD：编码损坏，换一个版本或重新导出为 UTF-8",
    "private_use_glyphs": "大量私用区字形：PDF 字体没有 Unicode 映射，需走 OCR",
    "mojibake_utf8_as_latin": "UTF-8 被当成 Latin-1 保存过（Ã©/â€™），找原始文件",
    "mojibake_utf8_as_gbk": "UTF-8 被当成 GBK 保存过（锛/銆），找原始文件",
    "ocr_unavailable": "扫描件且 OCR 不可用：pip install -e .[ocr] 后重跑 index，或提供文字版",
    "ocr_garbled": "过半页靠 OCR 且平均置信度 <0.6（校准实测此档已是乱码）：换更清晰的扫描、换引擎（mdf ocr calibrate --backend all 比较），或提供文字版",
}
FLAG_HINTS = {
    "modern_annotation": "含现代注释/译文标记：抽取时区分原文与注释者的话（张居正《帝鉴图说》教训）",
    "heavy_removal": "行规则删掉了超过 10% 的字符，抽样核对报告里的 samples",
    "ocr_incomplete": "部分页需要 OCR 但未取得文字",
    "ocr_mostly_missing": "过半页需要 OCR 但未取得文字，覆盖面不完整",
    "low_ocr_confidence": "OCR 平均置信度 <0.9（校准实测此档逐字存活率 ≤58%），引文必须对照原图",
    "ocr_text": "含 OCR 识别文字：最好的引擎在无退化样张上仍约 5% 的句子不能逐字还原，引文对照原图后才能标 high",
    "ocr_lines_dropped": "OCR 有没认全的行（印章、透墨、污渍、手写；竖排页还按列距推算漏检列）：这些行不在语料里，缺口两侧在原书中并不相连，跨行引文必须对照原图（页码标记写明每页漏几行）",
    "very_short": "文本很短",
    "replacement_chars": "少量 U+FFFD",
    "private_use_glyphs": "少量私用区字形",
    "control_chars": "含控制字符",
}


def flag_label(flag: str, ocr: dict[str, Any] | None = None) -> str:
    """表格单元格里的短标签，带上这份来源自己的数字；长说明（FLAG_HINTS）放在表格下方，每种只写一次。"""
    ocr = ocr or {}
    missing = int(ocr.get("ocr_required") or 0) - int(ocr.get("ocr_ok") or 0)
    labels = {
        "ocr_incomplete": f"{missing} 页没取得 OCR 文字" if missing > 0 else "部分页没取得 OCR 文字",
        "ocr_mostly_missing": f"过半页没取得 OCR 文字（{missing}/{ocr.get('ocr_required')}）" if missing > 0
        else "过半页没取得 OCR 文字",
        "low_ocr_confidence": f"OCR 平均置信度 {float(ocr['mean_confidence']):.2f}" if ocr.get("mean_confidence")
        else "OCR 置信度低",
        "ocr_text": "含 OCR 文字（引文封顶 medium）",
        "ocr_lines_dropped": f"{ocr['suspect_lines']} 行 OCR 没认全" if ocr.get("suspect_lines") else "OCR 有没认全的行",
        "modern_annotation": "含现代注释",
        "heavy_removal": "删除超过 10%",
        "very_short": "文本很短",
        "replacement_chars": "少量 U+FFFD",
        "private_use_glyphs": "少量私用区字形",
        "control_chars": "含控制字符",
    }
    return labels.get(flag, flag)


def render_report(slug: str, report: dict[str, Any]) -> str:
    lines = [f"## 清洗报告：{slug}", "", f"共 {report['source_count']} 个来源："
             f"✅ {len(report['accepted_sources'])} 通过 · ⚠️ {len(report['flagged_sources'])} 待复核 · "
             f"❌ {len(report['rejected_sources'])} 被拒 · ➖ {len(report.get('duplicate_sources', []))} 重复", ""]
    if report["rejected_sources"] or report["flagged_sources"] or report.get("duplicate_sources"):
        lines += ["| 来源 | 结论 | 原因 / 建议 |", "|---|---|---|"]
        for item in report["rejected_sources"]:
            hint = "；".join(REASON_HINTS.get(r, r) for r in item["reasons"])
            lines.append(f"| {item['file']} | ❌ 被拒 | {hint} |")
        for item in report["flagged_sources"]:
            ocr = (report.get("sources", {}).get(item["file"]) or {}).get("ocr")
            hint = " · ".join(flag_label(f, ocr) for f in item["flags"])
            lines.append(f"| {item['file']} | ⚠️ 待复核 | {hint} |")
        for item in report.get("duplicate_sources", []):
            lines.append(f"| {item['file']} | ➖ 重复 | 与 {item.get('duplicate_of')} {item.get('relation', '')} {item.get('score', '')} |")
        lines.append("")
        flags = list(dict.fromkeys(f for item in report["flagged_sources"] for f in item["flags"] if f in FLAG_HINTS))
        if flags:
            lines += ["**标记说明**", "", *[f"- `{f}`：{FLAG_HINTS[f]}" for f in flags], ""]
    removed: dict[str, int] = {}
    for entry in report["sources"].values():
        for action, n in entry.get("actions", {}).items():
            removed[action] = removed.get(action, 0) + n
    if removed:
        lines.append("删除动作合计：" + "，".join(f"{k} {v}" for k, v in sorted(removed.items())))
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from slug_rules import slug_arg  # noqa: E402
    from text_decoding import decode_bytes  # noqa: E402

    parser = argparse.ArgumentParser(description="语料清洗报告与单文件预检")
    sub = parser.add_subparsers(dest="command")
    report_p = sub.add_parser("report", help="查看 index 生成的清洗报告（默认）")
    report_p.add_argument("slug", type=slug_arg)
    report_p.add_argument("--json", action="store_true")
    report_p.add_argument("--root")
    check_p = sub.add_parser("check", help="放进 raw 之前预检单个 txt/md 文件")
    check_p.add_argument("path", type=Path)
    check_p.add_argument("--json", action="store_true")
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] not in ("report", "check", "-h", "--help"):
        argv = ["report", *argv]  # `mdf clean <slug>` 等同 `report <slug>`
    args = parser.parse_args(argv)

    if args.command == "check":
        decoded = decode_bytes(args.path.read_bytes())
        _, entry = clean_text(decoded.text, encoding=decoded.encoding, replacements=decoded.replacements)
        print(json.dumps(entry, ensure_ascii=False, indent=2) if args.json else
              f"{args.path.name}: {entry['verdict']} {entry['reasons'] or entry['flags'] or ''} 编码 {entry['encoding']}")
        return 1 if entry["verdict"] == "rejected" else 0

    root = data_root(args.root)
    path = root / "sources" / args.slug / "processed" / "cleaning_report.json"
    if not path.exists():
        print(f"还没有清洗报告：先运行 python scripts/mdf.py index {args.slug}", file=sys.stderr)
        return 1
    report = json.loads(path.read_text(encoding="utf-8"))
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else render_report(args.slug, report), end="" if not args.json else "\n")
    return 1 if report.get("rejected_sources") else 0


if __name__ == "__main__":
    if sys.platform.startswith("win"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except AttributeError:
            pass
    sys.exit(main())
