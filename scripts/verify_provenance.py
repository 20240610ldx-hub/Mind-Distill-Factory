#!/usr/bin/env python3
"""
Mind Distill Factory — 溯源校验器（确定性，不依赖 LLM 打分）

逐字比对出厂引文与语料，拦截缝合改写、字符讹误、静默省略三类缺陷。
规格：docs/superpowers/specs/2026-08-23-skill-package-v6-design.md §五
"""

from __future__ import annotations

import functools
import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable, NamedTuple

# Windows 控制台 UTF-8（沿用 validate_output.py:23-29 的模式）
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

# 字面 '-' 置于字符类末尾，整体使用原始字符串。
# 第二段是整块的 Unicode 标点区：全角 ！？（OCR 常吐成半角 !?，同一句话就对不上）、
# 竖排专用标点 ﹁﹂︵︶︑︒（竖排书的扫描件与电子版混用）、小写变体、各种破折号与引号。
# 2026-10-18 OCR 竖排校准发现：只认半角 !? 时，「不亦說乎？」与 OCR 的「不亦說乎?」永远对不上。
PUNCT_RE = re.compile(
    r"[\s，。、；：「」『』“”‘’（）()《》〈〉【】·,.;:!?…—　~～\"'’"
    "‐-‧‰-⁞"            # 一般标点：破折号、引号、省略号、‰ 等
    "、-〃〈-】〔-〟〰"  # CJK 符号与标点（不含 々〆〇 等字）
    "︐-︙︰-﹏﹐-﹫"        # 竖排形式、CJK 兼容形式、小写变体
    "！-／：-＠［-｀｛-･"  # 全角 ASCII 标点
    "-]"
)
# 全角数字与拉丁字母折成半角：「１９１２年」与 OCR 的「1912年」是同一句话
_FULLWIDTH_ALNUM = {cp: cp - 0xFEE0 for cp in (*range(0xFF10, 0xFF1A), *range(0xFF21, 0xFF3B), *range(0xFF41, 0xFF5B))}

TEXT_SUFFIXES = (".txt", ".md")
PDF_SIDECAR_DIR = "extracted"


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
    """去标点、去空白、全角数字字母折半角，可选繁简归一。逐字比对前的唯一预处理。"""
    stripped = PUNCT_RE.sub("", text).translate(_FULLWIDTH_ALNUM)
    if fold_variants and _FOLDER is not None:
        stripped = _FOLDER(stripped)
    return stripped


@functools.lru_cache(maxsize=None)
def _text_decoding() -> Any:
    # 本模块常被按路径加载（不在 sys.modules 里），兄弟模块也按路径取。
    path = Path(__file__).resolve().parent / "text_decoding.py"
    spec = importlib.util.spec_from_file_location("_provenance_text_decoding", path)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def read_raw_text(path: Path) -> str:
    """与 index 同一解码顺序（UTF-8 → GB18030 → Big5），GBK 电子书不再整份溯源失败。"""
    return _text_decoding().decode_bytes(path.read_bytes()).text


def load_corpus(slug: str, root: Path) -> list[tuple[str, str]]:
    """Load raw text plus hash-bound PDF sidecars.

    Processed JSON and arbitrary processed text are deliberately excluded: a
    derived artifact cannot prove its own provenance. PDF sidecars are accepted
    only when their parent SHA-256 matches the registered raw source.
    """
    corpus: list[tuple[str, str]] = []
    source_root = root / "sources" / slug
    raw_base = source_root / "raw"
    for path in sorted(raw_base.rglob("*")) if raw_base.exists() else []:
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = read_raw_text(path)
        corpus.append((path.relative_to(raw_base).as_posix(), normalize(text)))

    registry_path = source_root / "processed" / "source_registry.json"
    sidecar_base = source_root / "processed" / PDF_SIDECAR_DIR
    if not registry_path.exists() or not sidecar_base.exists():
        return corpus
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return corpus
    for item in registry.get("sources", []):
        if not isinstance(item, dict) or item.get("extension", "").lower() != ".pdf":
            continue
        source_id = item.get("source_id")
        digest = item.get("sha256")
        if not source_id or not digest:
            continue
        sidecar_meta = sidecar_base / f"{source_id}.json"
        sidecar_text = sidecar_base / f"{source_id}.txt"
        if not sidecar_meta.exists() or not sidecar_text.exists():
            continue
        try:
            metadata = json.loads(sidecar_meta.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        if metadata.get("parent_sha256") != digest or metadata.get("source_id") != source_id:
            continue
        text = sidecar_text.read_text(encoding="utf-8", errors="replace")
        corpus.append((f"{item.get('relative_path', source_id)}#{source_id}", normalize(text)))
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
QUOTES_SECTION_RE = re.compile(
    r"^##(?!#)[^\n]*标志性名言[^\n]*$(.*?)(?=^##\s|\Z)", re.MULTILINE | re.DOTALL
)
FIRST_H2_RE = re.compile(r"^##(?!#)", re.MULTILINE)
BLOCKQUOTE_LINE_RE = re.compile(r"^>\s?(.*)$")


def extract_skill_quotes(text: str) -> list[tuple[str, str]]:
    """从三处结构化位置提取引文：顶部题记、原文出处行、标志性名言章节。

    顶部题记（epigraph）指首个 `##` 标题之前出现的 `> ` 引用行——v6 核心模板与
    样板包都只在这一位置放一句题记式签名引言，此前完全不在扫描范围内，是
    SKILL.md 里最显眼的一句引文却零覆盖。只扫描首个 `##` 之前的区域，不影响
    正文中出现在其他章节里的普通 blockquote。
    """
    found: list[tuple[str, str]] = []
    first_heading = FIRST_H2_RE.search(text)
    header_region = text[:first_heading.start()] if first_heading else text
    for line in header_region.splitlines():
        match = BLOCKQUOTE_LINE_RE.match(line.strip())
        if not match:
            continue
        inner = BRACKET_QUOTE_RE.search(match.group(1))
        if inner:
            found.append(("epigraph", inner.group(1)))
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
    skill_text = skill_md.read_text(encoding="utf-8")
    cards = parse_evidence_cards(evidence_md.read_text(encoding="utf-8"))
    haystack = [normalize(card["verbatim"]) for card in cards]
    errors: list[str] = []

    quotes = extract_skill_quotes(skill_text)
    source_markers = list(SOURCE_LINE_RE.finditer(skill_text))
    harvested_source_quotes = sum(1 for label, _ in quotes if label == "原文出处")
    if len(source_markers) > harvested_source_quotes:
        # 失败关闭：某条「原文出处：」行未能解析出可闭合的「」引文（例如引文跨行
        # 断裂），不能被静默跳过——看不见不等于合规，必须报错而非放行。
        for match in source_markers:
            if BRACKET_QUOTE_RE.search(match.group(1)) is not None:
                continue
            snippet = match.group(0).strip()
            if len(snippet) > 80:
                snippet = snippet[:80] + "…"
            errors.append(
                f"P1_UNPARSEABLE_CITATION: {skill_md} 原文出处行未能解析出可闭合的"
                f"「」引文: {snippet}"
            )

    for label, quote in quotes:
        probe = normalize(quote)
        if not probe:
            continue
        if not any(probe in card_text for card_text in haystack):
            errors.append(
                f"P1_QUOTE_NOT_IN_EVIDENCE: {skill_md} [{label}]: 「{quote}」"
                f" 未逐字出现在 {evidence_md.name}"
            )
    return errors


def check_p2_corpus_closure(
    evidence_md: Path,
    slug: str,
    root: Path,
    corpus: list[tuple[str, str]] | None = None,
) -> list[str]:
    """P2：evidence.md 中每条逐字原文必须逐字出现在语料中。

    传入 corpus 时直接用它，不再重读磁盘——发布证明需要对「P2 实际比对的那份
    语料」取指纹，两次分别读盘之间语料若被改动，指纹就会证明一份没被检查过的语料。
    """
    if not evidence_md.exists():
        return [f"MISSING: {evidence_md}"]
    if corpus is None:
        corpus = load_corpus(slug, root)
    if not corpus:
        return [f"EMPTY_CORPUS: sources/{slug}/ 下没有可读的 .txt/.md 语料"]
    return p2_scan(evidence_md, slug, corpus)[0]


class EvidenceCoverage(NamedTuple):
    """P2 的逐字覆盖：机器核对通过的卡 / 有引文的卡；adjudicated 是只靠 textual_note 人工放行的卡。

    闸门「通过」不等于每张卡都核对过（鲁迅验收发现 11：28 张只核对了 12 张）。覆盖率要从校验器一路带到
    状态表、manifest、发布行，文字格式与解析只在这里——别处用正则拆警告文本，改一处措辞另一处就读不出。

    用 NamedTuple 而不是 dataclass：本模块常被 spec_from_file_location 按路径加载而不登记进 sys.modules，
    dataclass 在 `from __future__ import annotations` 下会去 sys.modules 查模块而崩掉。
    """

    verified: int
    total: int
    adjudicated: int = 0

    CODE = "P2_COVERAGE"
    _PARSE_RE = re.compile(r"P2_COVERAGE: .*?逐字核对覆盖 (\d+)/(\d+) 张证据卡；(\d+) 张未逐字命中语料")

    def warning(self, evidence_name: str, slug: str) -> str:
        return (f"WARNING: {self.CODE}: {evidence_name}: 逐字核对覆盖 {self.verified}/{self.total} 张证据卡；"
                f"{self.adjudicated} 张未逐字命中语料，只靠 textual_note 人工裁决放行。"
                f"语料外的原文用 mdf acquire 采进 sources/{slug}/raw/ 才能机器核对")

    @classmethod
    def parse(cls, line: str) -> "EvidenceCoverage | None":
        match = cls._PARSE_RE.search(line)
        return cls(*(int(g) for g in match.groups())) if match else None

    def to_attestation(self) -> dict[str, int]:
        return {"cards_verified": self.verified, "cards_total": self.total, "cards_adjudicated": self.adjudicated}

    @classmethod
    def from_attestation(cls, data: Any) -> "EvidenceCoverage | None":
        if not isinstance(data, dict):
            return None
        verified, total = data.get("cards_verified"), data.get("cards_total")
        if not isinstance(verified, int) or not isinstance(total, int):
            return None  # 发现 11 之前的 manifest 没有覆盖率
        adjudicated = data.get("cards_adjudicated")
        return cls(verified, total, adjudicated if isinstance(adjudicated, int) else total - verified)

    def gap(self) -> str:
        """给状态表的一句话；没有人工放行的卡时为空。"""
        if not self.adjudicated:
            return ""
        return f"逐字核对只覆盖 {self.verified}/{self.total} 张证据卡，{self.adjudicated} 张靠 textual_note 放行"


def p2_scan(evidence_md: Path, slug: str, corpus: list[tuple[str, str]]) -> tuple[list[str], EvidenceCoverage]:
    """逐张核对证据卡：(错误与警告, 覆盖率)。

    语料外的卡写了 textual_note 只降级为 WARNING——但闸门「通过」不等于每张卡都核对过。2026-10-19 鲁迅验收里
    16 张维基文库转录卡都走了这条路，P2 的逐字保证实际只覆盖《熱風》（发现 11），所以另给一行覆盖率；
    这类卡按规则 6 最高 medium，标 high 直接报错。

    「语料外」看语料位置指向哪里，不看 textual_note 本身：底本讹字的卡原文就在 raw/ 里，textual_note
    记的是校勘，可以是 high；指向 processed/（维基文库转录之类）的卡才是规则 6 说的网络来源。
    """
    errors: list[str] = []
    verified = total = adjudicated = 0
    for card in parse_evidence_cards(evidence_md.read_text(encoding="utf-8")):
        verbatim = card["verbatim"]
        if not normalize(verbatim):
            continue
        total += 1
        if find_verbatim(verbatim, corpus):
            verified += 1
            continue
        prefix = longest_verbatim_prefix(verbatim, corpus)
        message = (
            f"P2_NOT_IN_CORPUS: {evidence_md.name} [{card['title']}]: "
            f"「{verbatim[:32]}」未逐字出现在语料中（最长逐字前缀={prefix}字）"
        )
        if "textual_note" not in card["fields"]:
            errors.append(message)
            continue
        adjudicated += 1
        errors.append(f"WARNING: {message} — 已记 textual_note，人工裁决在案")
        off_corpus = not _located_in_raw(card["fields"].get("语料位置", ""), slug)
        if off_corpus and card["fields"].get("confidence", "").strip().lower() == "high":
            errors.append(f"P2_UNVERIFIED_HIGH: {evidence_md.name} [{card['title']}]: "
                          "语料位置不在 raw/ 里、只靠 textual_note 放行的卡最高 medium（规则 6），却标了 high")
    coverage = EvidenceCoverage(verified, total, adjudicated)
    if adjudicated:
        errors.append(coverage.warning(evidence_md.name, slug))
    return errors, coverage


LOCATION_PATH_RE = re.compile(r"^`?([^`（(\s]+)")


def _located_in_raw(location: str, slug: str) -> bool:
    """语料位置的第一个路径是否在 sources/{slug}/raw/ 下。

    只看开头那个路径：鲁迅验收的维基文库卡写的是「processed/…json（…不在 `sources/lu-xun/raw/` 内）」，
    整串做子串匹配会把这句否定说明当成命中。
    """
    match = LOCATION_PATH_RE.match(location.strip())
    return bool(match) and match.group(1).replace("\\", "/").startswith(f"sources/{slug}/raw/")
