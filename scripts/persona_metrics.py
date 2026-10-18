#!/usr/bin/env python3
"""人物包的确定性度量：主张账本、覆盖矩阵、来源集中度、文体指纹，以及对话层的漂移检测。

这些数字是**代理指标**，不是质量裁决：它们回答「这句话能追到哪份语料」「证据是不是
集中在一本书上」「核心层的第一人称阐释更像本人还是更像通用分析腔」「对话里有没有
滑向第三人称、序数罗列、结尾口号」。真正的放行闸门仍是 validate_output 的 P1–P6
与隔离审查；方法论与阈值来由见 docs/methodology.md。

    python scripts/mdf.py metrics <slug>                       # 构建期包（output/）
    python scripts/mdf.py metrics <slug> --published           # 已发布包（gallery/）
    python scripts/mdf.py metrics <slug> --dialogue log.jsonl  # 加上对话层检测
    python scripts/mdf.py metrics <slug> --write               # 写 claim_ledger.json / persona_metrics.json

对话文件格式：.jsonl / .json（[{role, content}] 或字符串列表），或 .md/.txt（回答之间用单独一行 --- 分隔）。
"""

import argparse
import functools
import importlib.util
import json
import os
import re
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any
_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:  # 按路径加载本模块时也能找到同目录的 workspace
    sys.path.insert(0, _SCRIPTS_DIR)
from workspace import data_root  # noqa: E402  数据根解析规则只在 workspace.py 定义

CODE_ROOT = Path(__file__).resolve().parent.parent
LEDGER_SCHEMA = "claim-ledger-v1"
METRICS_SCHEMA = "persona-metrics-v1"

# 阈值集中在这里；改动请同步 docs/methodology.md。
LIMITS = {
    "top_source_share": 0.6,      # 单一来源占已溯源证据卡的比例上限
    "min_cards_for_share": 3,
    "sentence_cv_min": 0.30,      # CLAUDE.md：句长变化 >30%
    "ordinal_rate_max": 0.2,      # 含序数罗列的回答占比
    "lecturing_rate_max": 0.25,   # 含「你应该/你必须」的回答占比
    "closing_repeat_max": 1,      # 同一结尾句最多出现次数
    "short_prompt_chars": 30,
    "long_answer_chars": 1200,
}


@functools.lru_cache(maxsize=None)
def _sibling(name: str) -> Any:
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_persona_metrics_{name}", path)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[spec.name] = module  # type: ignore[union-attr]
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


# ── 解析包 ────────────────────────────────────────────────────────────

FIELD_LINE_RE = re.compile(r"^\*\*(理念|原文出处|决策规则)：\*\*\s*(.*)$", re.MULTILINE)
BRACKET_RE = re.compile(r"「([^」]+)」")
PRINCIPLE_TITLE_RE = re.compile(r"^原则\s*(\d+)\s*[：:]\s*(.*)$")
BLIND_ITEM_RE = re.compile(r"^\s*(?:\d+[.、]|[-*])\s*\*\*([^*]+)\*\*", re.MULTILINE)
VOICE_HEAD_RE = re.compile(r"^###\s*(样本[^\n]*)$", re.MULTILINE)
VOICE_DIM_RE = re.compile(r"维度[：:]\s*([^）)\s]+)")
ANTI_RE = re.compile(r"误写成通用分析腔会变成[：:]\*{0,2}\s*(.+)")
H1_RE = re.compile(r"^#(?!#)\s*(.+?)\s*$", re.MULTILINE)


def parse_principles(skill_text: str) -> list[dict[str, Any]]:
    v = _sibling("validate_output")
    core = v._h2_body(skill_text, "核心原则") or ""
    principles = []
    for title, body in v._h3_bodies(core):
        match = PRINCIPLE_TITLE_RE.match(title)
        if not match:
            continue
        fields = {k: val.strip() for k, val in FIELD_LINE_RE.findall(body)}
        quote = BRACKET_RE.search(fields.get("原文出处", ""))
        principles.append({
            "number": match.group(1), "name": match.group(2).strip(),
            "statement": fields.get("理念", ""), "rule": fields.get("决策规则", ""),
            "quote": quote.group(1) if quote else "",
        })
    return principles


def parse_gates(skill_text: str) -> list[str]:
    v = _sibling("validate_output")
    body = v._h2_body(skill_text, "决策框架") or ""
    fence = v.FENCE_RE.search(body)
    if not fence:
        return []
    return [ln.strip() for ln in fence.group(1).splitlines() if not v.DECISION_ARROW_LINE_RE.match(ln)]


def parse_blind_spots(skill_text: str) -> list[str]:
    body = _sibling("validate_output")._h2_body(skill_text, "已知盲区") or ""
    return [m.strip() for m in BLIND_ITEM_RE.findall(body)]


def parse_voice_samples(voice_text: str) -> list[dict[str, str]]:
    heads = list(VOICE_HEAD_RE.finditer(voice_text))
    samples = []
    for i, head in enumerate(heads):
        body = voice_text[head.end(): heads[i + 1].start() if i + 1 < len(heads) else len(voice_text)]
        quote = "\n".join(m.group(1) for m in re.finditer(r"^>\s?(.*)$", body, re.MULTILINE)).strip()
        dim = VOICE_DIM_RE.search(head.group(1))
        anti = ANTI_RE.search(body)
        samples.append({"title": head.group(1).strip(), "dimension": dim.group(1) if dim else "",
                        "text": quote, "anti": anti.group(1).strip() if anti else ""})
    return samples


def person_names(skill_text: str) -> list[str]:
    """人物的中外文名（用于检测第三人称漂移）。兼容 v6 与旧版双语包（H1 可能是「Language Detection」）。"""
    names: list[str] = []
    for heading in H1_RE.findall(skill_text):
        zh = re.match(r"(.+?)的思维框架", heading)
        en = re.match(r"(.+?)['’]s\s+(?:Thinking|Mental|Cognitive|Decision)", heading, re.IGNORECASE)
        if zh:
            names.append(zh.group(1))
        elif en:
            names.append(en.group(1))
    for line in re.findall(r"^\*\*([^*]+)\*\*\s*·", skill_text, re.MULTILINE):
        for part in re.split(r"\s*/\s*", line):
            inner = re.findall(r"[（(]([^）)]+)[）)]", part)
            names.append(re.sub(r"\s*[（(][^）)]*[）)]", "", part))
            names += [seg for chunk in inner for seg in re.split(r"[,，]\s*", chunk)]
    slug_name = re.search(r"^name:\s*([a-z0-9-]+?)(?:-wisdom)?(?:-en)?\s*$", skill_text, re.MULTILINE)
    if slug_name and not names:  # 兜底：abraham-lincoln-wisdom → Abraham Lincoln
        names.append(" ".join(w.capitalize() for w in slug_name.group(1).split("-")))
    cleaned = []
    for name in names:
        name = re.split(r",\s*(?:courtesy|sobriquet|also)", name.strip(), flags=re.IGNORECASE)[0].strip(" .")
        if len(name) >= 2 and not re.search(r"\d|Language|语言检测|BCE|CE\b", name):
            cleaned.append(name)
    return list(dict.fromkeys(cleaned))


# ── 主张账本 ──────────────────────────────────────────────────────────


def _registry(root: Path, slug: str) -> dict[str, dict[str, Any]]:
    path = root / "sources" / slug / "processed" / "source_registry.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return {str(item.get("relative_path")): item for item in data.get("sources", []) if isinstance(item, dict)}


def build_claim_ledger(slug: str, root: Path, package_dir: Path | None = None) -> dict[str, Any]:
    """把核心层与附件里的每条主张绑定到证据卡、语料文件与 source_id。"""
    prov = _sibling("verify_provenance")
    package_dir = package_dir or root / "output" / slug
    skill_text = (package_dir / "SKILL.md").read_text(encoding="utf-8")
    refs = package_dir / "references"
    evidence_text = (refs / "evidence.md").read_text(encoding="utf-8") if (refs / "evidence.md").exists() else ""
    voice_text = (refs / "voice.md").read_text(encoding="utf-8") if (refs / "voice.md").exists() else ""
    corpus = prov.load_corpus(slug, root)
    registry = _registry(root, slug)

    def locate(text: str) -> str | None:
        name = prov.find_verbatim(text, corpus) if text else None
        return name.split("#", 1)[0] if name else None

    cards = []
    for i, card in enumerate(prov.parse_evidence_cards(evidence_text), 1):
        principle = _sibling("validate_output").EVIDENCE_PRINCIPLE_RE.match(card["title"])
        confidence = (card["fields"].get("confidence") or "").split("（")[0].split("(")[0].strip().lower()
        cards.append({
            "card_id": f"evidence-{i}", "title": card["title"], "principle": principle.group(1) if principle else None,
            "verbatim": card["verbatim"], "confidence": confidence or None,
            "declared_location": card["fields"].get("语料位置"), "corpus_file": locate(card["verbatim"]),
        })

    claims: list[dict[str, Any]] = []
    for p in parse_principles(skill_text):
        linked = [c for c in cards if c["principle"] == p["number"]]
        claims.append({
            "claim_id": f"principle-{p['number']}", "kind": "principle", "basis": "evidence",
            "text": p["name"], "statement": p["statement"][:300],
            "evidence": [c["card_id"] for c in linked],
            "corpus_files": sorted({c["corpus_file"] for c in linked if c["corpus_file"]}),
        })
    normalized_cards = [(c, prov.normalize(c["verbatim"])) for c in cards]
    for k, (where, quote) in enumerate(prov.extract_skill_quotes(skill_text), 1):
        probe = prov.normalize(quote)
        linked = [c for c, norm in normalized_cards if probe and probe in norm]
        files = {c["corpus_file"] for c in linked if c["corpus_file"]} or ({locate(quote)} - {None})
        claims.append({
            "claim_id": f"quote-{k}", "kind": "quote", "basis": "evidence", "location": where, "text": quote,
            "evidence": [c["card_id"] for c in linked], "corpus_files": sorted(files),
        })
    for i, sample in enumerate(parse_voice_samples(voice_text), 1):
        found = locate(sample["text"])
        claims.append({
            "claim_id": f"voice-{i}", "kind": "voice", "basis": "evidence", "dimension": sample["dimension"],
            "text": sample["text"][:200], "evidence": [], "corpus_files": [found] if found else [],
        })
    # 决策闸门与盲区是综合判断，不假装能逐字溯源；单列出来，便于审查者知道哪些需要靠论证而非引文。
    claims += [{"claim_id": f"gate-{i}", "kind": "gate", "basis": "synthesis", "text": g}
               for i, g in enumerate(parse_gates(skill_text), 1)]
    claims += [{"claim_id": f"blind-spot-{i}", "kind": "blind_spot", "basis": "synthesis", "text": b}
               for i, b in enumerate(parse_blind_spots(skill_text), 1)]

    usage = Counter(c["corpus_file"] for c in cards if c["corpus_file"])
    sources = {}
    for rel, n in sorted(usage.items()):
        item = registry.get(rel, {})
        sources[rel] = {
            "source_id": item.get("source_id"), "sha256": item.get("sha256"),
            "rights_status": item.get("rights_status", "unregistered"), "origin": item.get("origin"),
            "canonical_url": item.get("canonical_url") or None, "evidence_cards": n,
        }
    return {"schema": LEDGER_SCHEMA, "slug": slug, "package_dir": package_dir.as_posix(),
            "cards": cards, "claims": claims, "sources": sources}


# ── 文体指纹 ──────────────────────────────────────────────────────────

SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?；;])|\n+")
FIRST_PERSON_RE = re.compile(r"我|吾|余(?=[之以所])|予(?=[之以所])|朕|\bI\b|\bmy\b|\bme\b", re.IGNORECASE)
CLASSICAL_RE = re.compile(r"[之乎者也矣焉哉耳夫盖]")
CONNECTIVE_RE = re.compile(
    r"因此|所以|但是|然而|首先|其次|最后|总之|综上|此外|另外|总而言之|\btherefore\b|\bhowever\b|\bmoreover\b"
    r"|\bfurthermore\b|\bin conclusion\b|\bfirstly\b", re.IGNORECASE)
FEATURES = ("sentence_len_mean", "sentence_len_cv", "question_rate", "exclaim_rate",
            "first_person_per_k", "classical_per_k", "connective_per_k", "commas_per_sentence")


def sentences(text: str) -> list[str]:
    return [s.strip() for s in SENTENCE_SPLIT_RE.split(text) if s and len(s.strip()) > 1]


def stylometry(text: str) -> dict[str, float] | None:
    sents = sentences(text)
    chars = sum(1 for ch in text if not ch.isspace())
    if len(sents) < 3 or chars < 40:
        return None
    lengths = [len(s) for s in sents]
    mean = statistics.mean(lengths)
    per_k = 1000 / chars
    return {
        "sentence_len_mean": round(mean, 2),
        "sentence_len_cv": round(statistics.pstdev(lengths) / mean, 3) if mean else 0.0,
        "question_rate": round(sum(s.endswith(("？", "?")) for s in sents) / len(sents), 3),
        "exclaim_rate": round(sum(s.endswith(("！", "!")) for s in sents) / len(sents), 3),
        "first_person_per_k": round(len(FIRST_PERSON_RE.findall(text)) * per_k, 2),
        "classical_per_k": round(len(CLASSICAL_RE.findall(text)) * per_k, 2),
        "connective_per_k": round(len(CONNECTIVE_RE.findall(text)) * per_k, 2),
        "commas_per_sentence": round(sum(text.count(c) for c in "，,、") / len(sents), 2),
    }


def profile_distance(a: dict[str, float], b: dict[str, float]) -> float:
    """逐特征相对差的均值，0=相同，1=完全不同。"""
    diffs = []
    for key in FEATURES:
        x, y = a[key], b[key]
        scale = max(abs(x), abs(y))
        diffs.append(abs(x - y) / scale if scale > 1e-9 else 0.0)
    return round(sum(diffs) / len(diffs), 3)


# ── 包层指标 ──────────────────────────────────────────────────────────

CJK_CHAR_RE = re.compile(r"[㐀-鿿]")


def _anchor_terms(a: str, b: str) -> list[str]:
    """两段文本共享的「内容片段」：CJK 双字组 + 4 字母以上英文词。"""
    def grams(text: str) -> set[str]:
        cjk = "".join(CJK_CHAR_RE.findall(text))
        out = {cjk[i:i + 2] for i in range(len(cjk) - 1)}
        out |= {w.lower() for w in re.findall(r"[A-Za-z]{4,}", text)}
        return out
    return sorted(grams(a) & grams(b))


def package_metrics(ledger: dict[str, Any], skill_text: str, voice_text: str) -> dict[str, Any]:
    claims = ledger["claims"]
    cards = ledger["cards"]
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for c in claims:
        by_kind.setdefault(c["kind"], []).append(c)

    def traced(kind: str) -> dict[str, Any]:
        items = by_kind.get(kind, [])
        ok = [c for c in items if c.get("corpus_files")]
        return {"total": len(items), "traced": len(ok), "untraced": [c["claim_id"] for c in items if not c.get("corpus_files")]}

    quotes = by_kind.get("quote", [])
    traced_cards = [c for c in cards if c["corpus_file"]]
    usage = Counter(c["corpus_file"] for c in traced_cards)
    total = sum(usage.values())
    concentration = {
        "distinct_sources": len(usage),
        "top_source": usage.most_common(1)[0][0] if usage else None,
        "top_share": round(usage.most_common(1)[0][1] / total, 3) if total else 0.0,
        "hhi": round(sum((n / total) ** 2 for n in usage.values()), 3) if total else 0.0,
    }

    card_by_id = {c["card_id"]: c for c in cards}
    principles = parse_principles(skill_text)
    anchors = {}
    for p in principles:
        evidence = " ".join(card_by_id[e]["verbatim"] for e in next(
            (c["evidence"] for c in claims if c["claim_id"] == f"principle-{p['number']}"), []))
        anchors[f"principle-{p['number']}"] = _anchor_terms(" ".join([p["name"], p["statement"], p["rule"]]), evidence)[:8]

    samples = parse_voice_samples(voice_text)
    corpus_style = stylometry("\n".join([c["verbatim"] for c in cards] + [s["text"] for s in samples]))
    skill_style = stylometry("\n".join(p["statement"] for p in principles))
    generic_style = stylometry("\n".join(s["anti"] for s in samples))
    style: dict[str, Any] = {"core_prose": skill_style, "corpus": corpus_style, "generic_baseline": generic_style}
    if skill_style and corpus_style and generic_style:
        style["distance_to_corpus"] = profile_distance(skill_style, corpus_style)
        style["distance_to_generic"] = profile_distance(skill_style, generic_style)
        style["closer_to"] = "corpus" if style["distance_to_corpus"] <= style["distance_to_generic"] else "generic"

    flags: list[dict[str, str]] = []
    principle_trace = traced("principle")
    if principle_trace["untraced"]:
        flags.append({"code": "PRINCIPLE_UNTRACED", "detail": "、".join(principle_trace["untraced"])})
    if total >= LIMITS["min_cards_for_share"] and concentration["top_share"] > LIMITS["top_source_share"]:
        flags.append({"code": "SINGLE_SOURCE_CONCENTRATION",
                      "detail": f"{concentration['top_share']:.0%} 的已溯源证据卡来自 {concentration['top_source']}"})
    zero_anchor = [k for k, v in anchors.items() if not v]
    if zero_anchor:
        flags.append({"code": "PRINCIPLE_NO_ANCHOR_OVERLAP", "detail": "、".join(zero_anchor)})
    if style.get("closer_to") == "generic":
        flags.append({"code": "CORE_PROSE_GENERIC_STYLE", "detail": "核心原则的第一人称阐释在文体指纹上更接近「通用分析腔」反例"})
    if any(not v.get("source_id") for v in ledger["sources"].values()):
        flags.append({"code": "SOURCE_NOT_REGISTERED", "detail": "有证据所在文件不在 source_registry.json（先重跑 mdf index）"})

    return {
        "principles": principle_trace,
        "quotes": {"total": len(quotes), "in_evidence": sum(1 for q in quotes if q["evidence"]),
                   "traced": sum(1 for q in quotes if q["corpus_files"])},
        "voice": traced("voice"),
        "cards": {"total": len(cards), "traced": len(traced_cards),
                  "confidence": dict(Counter(c["confidence"] or "missing" for c in cards))},
        "synthesis_claims": {"gates": len(by_kind.get("gate", [])), "blind_spots": len(by_kind.get("blind_spot", []))},
        "source_concentration": concentration,
        "anchor_terms": anchors,
        "stylometry": style,
        "flags": flags,
    }


def coverage_matrix(ledger: dict[str, Any], package_dir: Path) -> dict[str, Any]:
    """原则 × 证据，原则簇 × 案例（正例/反例）。"""
    rows = []
    for claim in (c for c in ledger["claims"] if c["kind"] == "principle"):
        cards = [c for c in ledger["cards"] if c["card_id"] in claim["evidence"]]
        rows.append({"claim_id": claim["claim_id"], "name": claim["text"], "cards": len(cards),
                     "traced_cards": sum(1 for c in cards if c["corpus_file"]),
                     "best_confidence": min((c["confidence"] or "z" for c in cards),
                                            key=lambda x: {"high": 0, "medium": 1, "low": 2}.get(x, 3), default=None)})
    clusters: dict[str, dict[str, int]] = {}
    cases_path = package_dir / "references" / "cases.md"
    if cases_path.exists():
        validator = _sibling("validate_output")
        text = cases_path.read_text(encoding="utf-8")
        for block in re.split(r"^###\s+", text, flags=re.MULTILINE)[1:]:
            cluster = re.search(r"^\*\*对应原则簇：\*\*\s*(\S+)\s*$", block, re.MULTILINE)
            key = cluster.group(1) if cluster else "（未标注）"
            slot = clusters.setdefault(key, {"cases": 0, "counter_cases": 0})
            slot["cases"] += 1
            slot["counter_cases"] += 1 if validator.CASE_COUNTER_FIELD_RE.search(block) else 0
    return {"principles": rows, "clusters": clusters}


# ── 对话层 ────────────────────────────────────────────────────────────

ORDINAL_PATTERNS = (
    re.compile(r"第一[，、：:,].{0,300}?第二[，、：:,]", re.DOTALL),
    re.compile(r"首先.{0,400}?其次", re.DOTALL),
    re.compile(r"一是.{0,300}?二是", re.DOTALL),
    re.compile(r"\bfirst(?:ly)?,.{0,400}?\bsecond(?:ly)?,", re.DOTALL | re.IGNORECASE),
)
LIST_LINE_RE = re.compile(r"^\s*(?:\d+[.、)）]|[-*•])\s+\S", re.MULTILINE)
LECTURE_RE = re.compile(r"你(?:应该|必须|需要|一定要)|you (?:should|must|need to)\b", re.IGNORECASE)
THIRD_PERSON_VERBS = r"(?:认为|说过?|主张|强调|指出|曾经?|的观点|的看法|believed|said|argued|wrote|thought)"


QA_PAIR_RE = re.compile(
    r"^\*\*Q[:：]\*\*\s*(.*?)\n\s*\*\*A[:：]\*\*\s*(.*?)(?=^\*\*Q[:：]\*\*|^#{1,3}\s|\Z)", re.MULTILINE | re.DOTALL
)


def load_responses(path: Path) -> list[dict[str, str]]:
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix in (".jsonl", ".json"):
        records = ([json.loads(line) for line in text.splitlines() if line.strip()] if suffix == ".jsonl"
                   else json.loads(text))
        pairs, prompt = [], ""
        for record in records:
            if isinstance(record, str):
                pairs.append({"prompt": "", "response": record})
            elif record.get("role") == "user":
                prompt = str(record.get("content", ""))
            elif record.get("role") == "assistant":
                pairs.append({"prompt": prompt, "response": str(record.get("content", ""))})
                prompt = ""
        return pairs
    qa = QA_PAIR_RE.findall(text)
    if qa:  # evaluation/reports/*/runtime-dialogue-test.md 的「**Q:** … **A:** …」格式
        return [{"prompt": q.strip(), "response": a.strip()} for q, a in qa]
    return [{"prompt": "", "response": chunk.strip()} for chunk in re.split(r"^\s*---\s*$", text, flags=re.MULTILINE)
            if chunk.strip()]


def _last_sentence(text: str) -> str:
    sents = sentences(text)
    return re.sub(r"[\W_]+", "", sents[-1]) if sents else ""


def dialogue_metrics(pairs: list[dict[str, str]], names: list[str]) -> dict[str, Any]:
    name_re = (re.compile(r"(?:" + "|".join(re.escape(n) for n in names) + r").{0,4}?" + THIRD_PERSON_VERBS)
               if names else None)
    rows = []
    for i, pair in enumerate(pairs, 1):
        response = pair["response"]
        paragraphs = [p for p in re.split(r"\n\s*\n", response) if p.strip()]
        lengths = [len(s) for s in sentences(response)]
        # 少于 5 句的短答，句长变化系数没有统计意义（真实报告里「150 字以内」的回答曾大量误报）。
        cv = round(statistics.pstdev(lengths) / statistics.mean(lengths), 3) if len(lengths) >= 5 else None
        rows.append({
            "turn": i,
            "chars": len(response),
            "first_person": len(FIRST_PERSON_RE.findall(response)),
            "third_person_self": len(name_re.findall(response)) if name_re else 0,
            "lecturing": len(LECTURE_RE.findall(response)),
            "ordinal": any(p.search(response) for p in ORDINAL_PATTERNS) or len(LIST_LINE_RE.findall(response)) >= 3,
            "sentence_cv": cv,
            "paragraph_sentences": [len(sentences(p)) for p in paragraphs],
            "length_mismatch": bool(pair["prompt"]) and len(pair["prompt"]) < LIMITS["short_prompt_chars"]
            and len(response) > LIMITS["long_answer_chars"],
            "closing": _last_sentence(response),
        })
    n = len(rows) or 1
    closings = Counter(r["closing"] for r in rows if r["closing"])
    repeated = {k: v for k, v in closings.items() if v > LIMITS["closing_repeat_max"]}
    low_cv = [r["turn"] for r in rows if r["sentence_cv"] is not None and r["sentence_cv"] < LIMITS["sentence_cv_min"]]
    uniform_paragraphs = [r["turn"] for r in rows if len(r["paragraph_sentences"]) >= 4
                          and len(set(r["paragraph_sentences"])) == 1]
    flags = []
    if any(r["third_person_self"] for r in rows):
        flags.append({"code": "THIRD_PERSON_DRIFT", "detail": "回合 " + "、".join(str(r["turn"]) for r in rows if r["third_person_self"])})
    ordinal_rate = sum(r["ordinal"] for r in rows) / n
    if ordinal_rate > LIMITS["ordinal_rate_max"]:
        flags.append({"code": "ORDINAL_ENUMERATION", "detail": f"{ordinal_rate:.0%} 的回答在序数罗列"})
    if repeated:
        flags.append({"code": "CLOSING_REPETITION", "detail": "；".join(f"「{k[:20]}」×{v}" for k, v in repeated.items())})
    if low_cv:
        flags.append({"code": "UNIFORM_SENTENCE_LENGTH", "detail": "回合 " + "、".join(map(str, low_cv))})
    if uniform_paragraphs:
        flags.append({"code": "UNIFORM_PARAGRAPHS", "detail": "回合 " + "、".join(map(str, uniform_paragraphs))})
    if any(r["length_mismatch"] for r in rows):
        flags.append({"code": "LENGTH_MISMATCH", "detail": "短问长答：回合 " + "、".join(str(r["turn"]) for r in rows if r["length_mismatch"])})
    # 「你需要……」在劝告里很常见，偶尔一次不算；成了习惯（≥1/4 的回答）或一段里连用才算说教。
    lecturing = [r["turn"] for r in rows if r["lecturing"]]
    if lecturing and (len(lecturing) / n >= LIMITS["lecturing_rate_max"] or any(r["lecturing"] >= 3 for r in rows)):
        flags.append({"code": "SECOND_PERSON_LECTURING", "detail": "回合 " + "、".join(map(str, lecturing))})
    return {"turns": len(rows), "ordinal_rate": round(ordinal_rate, 3), "repeated_closings": repeated,
            "rows": rows, "flags": flags}


# ── 渲染与 CLI ────────────────────────────────────────────────────────

FLAG_TEXT = {
    "PRINCIPLE_UNTRACED": "有原则找不到能逐字追到语料的证据卡",
    "SINGLE_SOURCE_CONCENTRATION": "证据集中于单一来源（主语料是全集/文集时属正常，核对关键原则是否另有独立来源佐证）",
    "PRINCIPLE_NO_ANCHOR_OVERLAP": "原则表述与其证据没有共享内容片段（去名测试的「证据锚点」不成立）",
    "CORE_PROSE_GENERIC_STYLE": "核心层文体更像通用分析腔",
    "SOURCE_NOT_REGISTERED": "证据来源未登记",
    "THIRD_PERSON_DRIFT": "回答滑向第三人称叙述本人",
    "ORDINAL_ENUMERATION": "序数罗列过多",
    "CLOSING_REPETITION": "结尾口号重复",
    "UNIFORM_SENTENCE_LENGTH": "句长变化不足 30%",
    "UNIFORM_PARAGRAPHS": "段落长度整齐划一",
    "LENGTH_MISMATCH": "短问长答",
    "SECOND_PERSON_LECTURING": "第二人称说教",
}


def render(slug: str, result: dict[str, Any]) -> str:
    pkg = result["package"]
    lines = [f"## 人物包度量：{slug}", "",
             "| 项目 | 数值 |", "|---|---|",
             f"| 原则可溯源 | {pkg['principles']['traced']}/{pkg['principles']['total']} |",
             f"| 引文 → 证据卡 → 语料 | {pkg['quotes']['total']} → {pkg['quotes']['in_evidence']} → {pkg['quotes']['traced']} |",
             f"| 语感样本逐字出自语料 | {pkg['voice']['traced']}/{pkg['voice']['total']} |",
             f"| 证据卡（已溯源/总数） | {pkg['cards']['traced']}/{pkg['cards']['total']}，confidence {pkg['cards']['confidence']} |",
             f"| 来源分布 | {pkg['source_concentration']['distinct_sources']} 个来源，最大占比 {pkg['source_concentration']['top_share']:.0%}，HHI {pkg['source_concentration']['hhi']} |",
             f"| 综合判断类主张 | 闸门 {pkg['synthesis_claims']['gates']}、盲区 {pkg['synthesis_claims']['blind_spots']}（不要求逐字溯源） |"]
    style = pkg["stylometry"]
    if "closer_to" in style:
        lines.append(f"| 核心层文体 | 距语料 {style['distance_to_corpus']} / 距通用腔 {style['distance_to_generic']} → 更像{'本人' if style['closer_to'] == 'corpus' else '通用分析腔'} |")
    flags = list(pkg["flags"])
    dialogue = result.get("dialogue")
    if dialogue:
        lines.append(f"| 对话 | {dialogue['turns']} 回合，序数罗列 {dialogue['ordinal_rate']:.0%} |")
        flags += dialogue["flags"]
    lines.append("")
    if flags:
        lines += ["**需要关注：**", ""] + [f"- {FLAG_TEXT.get(f['code'], f['code'])}：{f['detail']}" for f in flags]
    else:
        lines.append("没有触发任何关注项。")
    return "\n".join(lines) + "\n"


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def measure(slug: str, root: Path, *, published: bool = False, dialogue: Path | None = None) -> dict[str, Any]:
    package_dir = root / ("gallery" if published else "output") / slug
    skill_text = (package_dir / "SKILL.md").read_text(encoding="utf-8")
    voice_path = package_dir / "references" / "voice.md"
    voice_text = voice_path.read_text(encoding="utf-8") if voice_path.exists() else ""
    ledger = build_claim_ledger(slug, root, package_dir)
    result: dict[str, Any] = {
        "schema": METRICS_SCHEMA, "slug": slug, "limits": LIMITS,
        "package": package_metrics(ledger, skill_text, voice_text),
        "coverage": coverage_matrix(ledger, package_dir),
    }
    if dialogue is not None:
        result["dialogue"] = dialogue_metrics(load_responses(dialogue), person_names(skill_text))
    return {"ledger": ledger, "metrics": result}


def main(argv: list[str] | None = None) -> int:
    slug_arg = _sibling("slug_rules").slug_arg
    parser = argparse.ArgumentParser(description="人物包确定性度量（代理指标，不是放行闸门）")
    parser.add_argument("slug", type=slug_arg)
    parser.add_argument("--root", help="数据根目录（默认 MDF_DATA_ROOT，再默认仓库根）")
    parser.add_argument("--published", action="store_true", help="度量 gallery/ 里的发布包")
    parser.add_argument("--dialogue", type=Path, help="对话记录，做第一人称/序数/口号/结构检测")
    parser.add_argument("--write", action="store_true", help="写 output/{slug}/claim_ledger.json 与 persona_metrics.json")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--fail-on-flags", action="store_true", help="有关注项时返回 1（给 CI 用）")
    args = parser.parse_args(argv)

    root = data_root(args.root)
    package_dir = root / ("gallery" if args.published else "output") / args.slug
    if not (package_dir / "SKILL.md").exists():
        print(f"找不到 {package_dir / 'SKILL.md'}", file=sys.stderr)
        return 1
    out = measure(args.slug, root, published=args.published, dialogue=args.dialogue)
    if args.write:
        _write_json(root / "output" / args.slug / "claim_ledger.json", out["ledger"])
        _write_json(root / "output" / args.slug / "persona_metrics.json", out["metrics"])
    if args.json:
        print(json.dumps(out["metrics"], ensure_ascii=False, indent=2))
    else:
        print(render(args.slug, out["metrics"]), end="")
    flags = out["metrics"]["package"]["flags"] + (out["metrics"].get("dialogue") or {}).get("flags", [])
    return 1 if args.fail_on_flags and flags else 0


if __name__ == "__main__":
    if sys.platform.startswith("win"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except AttributeError:
            pass
    sys.exit(main())
