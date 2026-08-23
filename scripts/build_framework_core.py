#!/usr/bin/env python3
"""Build a mechanical framework_core.json scaffold from principle outputs.

This script is a deterministic helper for Stage 3A validation and migration.
The framework-core-synthesizer agent may replace or refine this output, but the
shape stays stable for downstream zh/en framework synthesizers.

Usage:
  python scripts/build_framework_core.py <person-slug>
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any


if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def normalize_key(text: str) -> str:
    text = re.sub(r"\s+", "", text).lower()
    text = re.sub(r"[^\w\u4e00-\u9fff-]", "", text)
    return text[:80]


def principle_cluster_key(principle: dict[str, Any]) -> str:
    tags = principle.get("topic_tags") or []
    first_tag = tags[0] if tags else "untagged"
    name = principle.get("name_en") or principle.get("name_zh") or principle.get("id") or ""
    return f"{first_tag}:{normalize_key(name)}"


def confidence_score(confidence: str) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get(confidence, 0)


def collect_principles(slug: str) -> tuple[list[dict[str, Any]], Counter]:
    output_dir = repo_root() / "output" / slug
    principles: list[dict[str, Any]] = []
    source_type_counts: Counter = Counter()
    for path in sorted(output_dir.glob("principles_*.json")):
        data = read_json(path)
        source_type = data.get("source_type") or path.stem.replace("principles_", "")
        for item in data.get("principles", []):
            item = dict(item)
            item["_source_file"] = path.name
            item["_source_type"] = source_type
            principles.append(item)
            source_type_counts[source_type] += 1
    return principles, source_type_counts


def build_clusters(principles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for principle in principles:
        grouped[principle_cluster_key(principle)].append(principle)

    clusters: list[dict[str, Any]] = []
    for idx, (_key, items) in enumerate(grouped.items(), start=1):
        items.sort(
            key=lambda p: (
                -(p.get("uniqueness_score") or 0),
                -sum(confidence_score(e.get("confidence", "")) for e in p.get("supporting_extracts", [])),
            )
        )
        lead = items[0]
        all_tags: list[str] = []
        source_types: set[str] = set()
        selected_evidence: list[dict[str, Any]] = []
        high_confidence = 0
        total_evidence = 0
        for item in items:
            all_tags.extend(item.get("topic_tags") or [])
            source_types.add(item.get("_source_type", "unknown"))
            for evidence in item.get("supporting_extracts", []):
                total_evidence += 1
                if evidence.get("confidence") == "high":
                    high_confidence += 1
                if len(selected_evidence) < 4:
                    selected_evidence.append(
                        {
                            "text": evidence.get("text", ""),
                            "source_title": evidence.get("source_title", ""),
                            "source_detail": evidence.get("source_detail", ""),
                            "confidence": evidence.get("confidence", "low"),
                            "from_principle_id": item.get("id", ""),
                        }
                    )
        clusters.append(
            {
                "cluster_id": f"cluster_{idx:03d}",
                "canonical_name_zh": lead.get("name_zh", ""),
                "canonical_name_en": lead.get("name_en", ""),
                "topic_tags": [tag for tag, _ in Counter(all_tags).most_common(6)],
                "candidate_principle_ids": [item.get("id", "") for item in items],
                "source_types": sorted(source_types),
                "max_uniqueness_score": max((item.get("uniqueness_score") or 0) for item in items),
                "evidence_count": total_evidence,
                "high_confidence_evidence_count": high_confidence,
                "zh_summary_seed": lead.get("explanation_zh", ""),
                "en_summary_seed": lead.get("explanation_en", ""),
                "zh_decision_rule_seed": lead.get("decision_rule_zh", ""),
                "en_decision_rule_seed": lead.get("decision_rule_en", ""),
                "selected_evidence": selected_evidence,
            }
        )

    clusters.sort(
        key=lambda c: (
            -c["max_uniqueness_score"],
            -c["high_confidence_evidence_count"],
            -c["evidence_count"],
        )
    )
    for idx, cluster in enumerate(clusters, start=1):
        cluster["rank"] = idx
    return clusters


def collect_reasoning_patterns(principles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    patterns: list[dict[str, Any]] = []
    for principle in principles:
        for pattern in principle.get("reasoning_patterns", []):
            key = normalize_key(pattern.get("name_en") or pattern.get("name_zh") or pattern.get("id") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            patterns.append(
                {
                    "name_zh": pattern.get("name_zh", ""),
                    "name_en": pattern.get("name_en", ""),
                    "description_zh": pattern.get("description_zh", ""),
                    "description_en": pattern.get("description_en", ""),
                    "trigger_zh": pattern.get("trigger_zh", ""),
                    "trigger_en": pattern.get("trigger_en", ""),
                    "supporting_evidence": pattern.get("supporting_evidence", ""),
                }
            )
    return patterns[:12]


def collect_quotes(principles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    quotes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for principle in principles:
        for quote in principle.get("notable_quotes", []):
            text = quote.get("text_zh") or quote.get("text_en") or ""
            key = normalize_key(text)
            if not key or key in seen:
                continue
            seen.add(key)
            quotes.append(quote)
    quotes.sort(key=lambda q: -confidence_score(q.get("confidence", "")))
    return quotes[:20]


def collect_blind_spots(slug: str) -> list[dict[str, Any]]:
    output_dir = repo_root() / "output" / slug
    themes: dict[str, dict[str, Any]] = {}
    for lang in ("zh", "en"):
        path = output_dir / f"frameworks.{lang}.json"
        if not path.exists():
            continue
        data = read_json(path)
        for item in data.get("blind_spots", []):
            name = item.get("name", "")
            key = normalize_key(name)
            if not key:
                continue
            theme = themes.setdefault(
                key,
                {
                    "theme_id": f"blind_spot_{len(themes) + 1:03d}",
                    "name_zh": "",
                    "name_en": "",
                    "description_seed_zh": "",
                    "description_seed_en": "",
                    "mitigation_seed_zh": "",
                    "mitigation_seed_en": "",
                },
            )
            theme[f"name_{lang}"] = name
            theme[f"description_seed_{lang}"] = item.get("description", "")
            theme[f"mitigation_seed_{lang}"] = item.get("mitigation", "")
    return list(themes.values())


def collect_source_ledger(principles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ledger: dict[str, dict[str, Any]] = {}
    for principle in principles:
        source_type = principle.get("_source_type", "unknown")
        for evidence in principle.get("supporting_extracts", []):
            title = evidence.get("source_title", "")
            if not title:
                continue
            key = normalize_key(f"{title}:{evidence.get('source_detail', '')}")
            item = ledger.setdefault(
                key,
                {
                    "title": title,
                    "detail": evidence.get("source_detail", ""),
                    "role": source_type,
                    "confidence_counts": Counter(),
                    "used_by_principle_ids": set(),
                },
            )
            item["confidence_counts"][evidence.get("confidence", "low")] += 1
            item["used_by_principle_ids"].add(principle.get("id", ""))

    result: list[dict[str, Any]] = []
    for item in ledger.values():
        result.append(
            {
                "title": item["title"],
                "detail": item["detail"],
                "role": item["role"],
                "confidence_counts": dict(item["confidence_counts"]),
                "used_by_principle_ids": sorted(item["used_by_principle_ids"]),
            }
        )
    return result


def collect_expression_summary(slug: str) -> dict[str, Any]:
    path = repo_root() / "sources" / slug / "processed" / "expression_dna.json"
    if not path.exists():
        return {"available": False, "extract_count": 0}
    data = read_json(path)
    extracts = data.get("extracts", [])
    dimensions = Counter()
    style_tags = Counter()
    samples = []
    for item in extracts:
        if item.get("dimension"):
            dimensions[item["dimension"]] += 1
        for tag in item.get("style_tags") or item.get("topic_tags") or []:
            style_tags[tag] += 1
        if len(samples) < 6:
            samples.append(
                {
                    "text": item.get("text", "")[:500],
                    "dimension": item.get("dimension", ""),
                    "analysis": item.get("analysis", ""),
                    "source_title": item.get("source_title", ""),
                }
            )
    return {
        "available": True,
        "extract_count": len(extracts),
        "dimension_counts": dict(dimensions),
        "top_style_tags": [tag for tag, _ in style_tags.most_common(12)],
        "sample_seeds": samples,
    }


def confidence_factors(principles: list[dict[str, Any]], source_type_counts: Counter) -> dict[str, Any]:
    evidence = []
    for principle in principles:
        evidence.extend(principle.get("supporting_extracts", []))
    total = max(1, len(evidence))
    high = sum(1 for item in evidence if item.get("confidence") == "high")
    medium = sum(1 for item in evidence if item.get("confidence") == "medium")
    low = sum(1 for item in evidence if item.get("confidence") == "low")
    source_total = max(1, sum(source_type_counts.values()))
    return {
        "principle_count": len(principles),
        "evidence_count": len(evidence),
        "high_confidence_evidence_ratio": round(high / total, 3),
        "medium_confidence_evidence_ratio": round(medium / total, 3),
        "low_confidence_evidence_ratio": round(low / total, 3),
        "source_type_ratios": {
            key: round(value / source_total, 3)
            for key, value in sorted(source_type_counts.items())
        },
    }


def build_core(slug: str) -> dict[str, Any]:
    principles, source_type_counts = collect_principles(slug)
    if not principles:
        raise SystemExit(f"No principles_*.json files with principles found for {slug}")
    return {
        "person_slug": slug,
        "core_version": "1.0",
        "synthesized_at": date.today().isoformat(),
        "synthesis_mode": "mechanical_scaffold",
        "principle_clusters": build_clusters(principles),
        "shared_blind_spot_themes": collect_blind_spots(slug),
        "reasoning_pattern_candidates": collect_reasoning_patterns(principles),
        "quote_candidates": collect_quotes(principles),
        "source_ledger": collect_source_ledger(principles),
        "confidence_factors": confidence_factors(principles, source_type_counts),
        "expression_dna_raw_summary": collect_expression_summary(slug),
        "alignment_contract": {
            "shared_fields": ["primary_category", "secondary_categories", "sources_list", "distill_confidence"],
            "equivalent_coverage_fields": ["blind_spots"],
            "independent_language_fields": ["core_principles", "decision_framework", "reasoning_patterns", "signature_quotes"],
        },
        "core_notes": (
            "Mechanical scaffold generated from principles. The framework-core-synthesizer "
            "agent should refine clusters, blind spot themes, and evidence selection before "
            "language-specific framework generation."
        ),
    }


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: python {Path(sys.argv[0]).name} <person-slug>")
        sys.exit(1)
    slug = sys.argv[1]
    output_dir = repo_root() / "output" / slug
    output_dir.mkdir(parents=True, exist_ok=True)
    core = build_core(slug)
    out_path = output_dir / "framework_core.json"
    out_path.write_text(json.dumps(core, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] Wrote {out_path}")
    print(f"  principle clusters: {len(core['principle_clusters'])}")
    print(f"  blind spot themes: {len(core['shared_blind_spot_themes'])}")
    print(f"  source ledger entries: {len(core['source_ledger'])}")


if __name__ == "__main__":
    main()
