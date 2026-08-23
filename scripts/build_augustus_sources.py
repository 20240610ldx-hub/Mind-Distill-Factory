#!/usr/bin/env python3
"""Build curated Stage 1 source artifacts for Augustus.

This is intentionally narrow: it turns the local raw/sharded Augustus corpus
into validator-compatible source JSON. It does not synthesize principles,
frameworks, or a Skill.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any


SLUG = "augustus"
PERSON = "Augustus"
ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "sources" / SLUG / "processed"
SHARDS = PROCESSED / "local_shards"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_ws(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def load_passages() -> list[dict[str, Any]]:
    passages: list[dict[str, Any]] = []
    for shard_path in sorted(SHARDS.glob("shard_*.json")):
        if shard_path.name.endswith("_extracts.json"):
            continue
        data = read_json(shard_path)
        shard_id = data.get("shard_id") or shard_path.stem
        for idx, passage in enumerate(data.get("passages", []), 1):
            passages.append(
                {
                    "shard_id": shard_id,
                    "passage_id": passage.get("passage_id") or f"{shard_id}:p{idx}",
                    "source_file": passage.get("source_file", ""),
                    "source_title": passage.get("source_title", passage.get("source_file", "")),
                    "source_detail": passage.get("source_detail", ""),
                    "language": passage.get("language", "en"),
                    "text": passage.get("text", ""),
                }
            )
    return passages


PASSAGES = load_passages()


def find_context(
    keyword: str,
    *,
    source_contains: str | None = None,
    before: int = 260,
    after: int = 520,
) -> tuple[str, dict[str, Any]]:
    pattern_text = r"\s+".join(re.escape(part) for part in keyword.split())
    pattern = re.compile(pattern_text, re.IGNORECASE)
    for passage in PASSAGES:
        if source_contains and source_contains.lower() not in passage["source_file"].lower():
            continue
        match = pattern.search(passage["text"])
        if not match:
            continue
        start = max(0, match.start() - before)
        end = min(len(passage["text"]), match.end() + after)
        return normalize_ws(passage["text"][start:end]), passage
    raise RuntimeError(f"Could not find keyword: {keyword!r}")


def extract(spec: dict[str, Any]) -> dict[str, Any]:
    text, passage = find_context(
        spec["keyword"],
        source_contains=spec.get("source_contains"),
        before=spec.get("before", 260),
        after=spec.get("after", 520),
    )
    detail_bits = [spec["source_detail"], passage["shard_id"], passage["passage_id"]]
    out = {
        "text": text,
        "source_title": spec["source_title"],
        "source_detail": " | ".join(bit for bit in detail_bits if bit),
        "source_url": spec.get("source_url", ""),
        "language": spec.get("language", passage.get("language", "en")),
        "content_type": spec["content_type"],
        "topic_tags": spec.get("topic_tags", []),
        "confidence": spec.get("confidence", "high"),
        "confidence_reason": spec.get(
            "confidence_reason",
            "User-provided local source material; passage is traceable to indexed raw corpus.",
        ),
    }
    if spec.get("style_tags"):
        out["style_tags"] = spec["style_tags"]
    if spec.get("dimension"):
        out["dimension"] = spec["dimension"]
    if spec.get("analysis"):
        out["analysis"] = spec["analysis"]
    out["_bucket"] = spec["bucket"]
    out["_shard_id"] = passage["shard_id"]
    return out


SPECS = [
    {
        "bucket": "primary",
        "keyword": "At the age of nineteen",
        "source_contains": "Res Gestae",
        "source_title": "Res Gestae Divi Augusti",
        "source_detail": "ch. 1, Brunt/Moore translation in local OCR packet",
        "content_type": "quote",
        "topic_tags": ["legitimacy", "crisis-entry", "private-resources", "republic"],
    },
    {
        "bucket": "primary",
        "keyword": "The dictatorship was offered",
        "source_contains": "Res Gestae",
        "source_title": "Res Gestae Divi Augusti",
        "source_detail": "ch. 5, refusal of dictatorship and permanent consulship",
        "content_type": "principle",
        "topic_tags": ["constitutional-form", "power-restraint", "legitimacy"],
    },
    {
        "bucket": "primary",
        "keyword": "supervisor of laws and morals",
        "source_contains": "Res Gestae",
        "source_title": "Res Gestae Divi Augusti",
        "source_detail": "ch. 6, moral legislation through accepted powers",
        "content_type": "principle",
        "topic_tags": ["institutional-design", "morals", "ancestral-custom"],
    },
    {
        "bucket": "primary",
        "keyword": "By new laws passed on my proposal",
        "source_contains": "Res Gestae",
        "source_title": "Res Gestae Divi Augusti",
        "source_detail": "ch. 8, restoration of ancestral practices",
        "content_type": "principle",
        "topic_tags": ["tradition", "law", "exemplarity", "posterity"],
    },
    {
        "bucket": "primary",
        "keyword": "gateway of Janus Quirinus",
        "source_contains": "Res Gestae",
        "source_title": "Res Gestae Divi Augusti",
        "source_detail": "ch. 13, peace framed as ancestral omen",
        "content_type": "quote",
        "topic_tags": ["peace", "symbolic-politics", "victory"],
    },
    {
        "bucket": "primary",
        "keyword": "I restored the Capitol and the theatre of Pompey",
        "source_contains": "Res Gestae",
        "source_title": "Res Gestae Divi Augusti",
        "source_detail": "ch. 20, public works without name inscription",
        "content_type": "behavior_record",
        "topic_tags": ["public-works", "restoration", "self-presentation"],
    },
    {
        "bucket": "primary",
        "keyword": "whole of Italy of its own free will",
        "source_contains": "Res Gestae",
        "source_title": "Res Gestae Divi Augusti",
        "source_detail": "ch. 25, Actium oath and leadership claim",
        "content_type": "quote",
        "topic_tags": ["coalition", "actium", "consent", "war-leadership"],
    },
    {
        "bucket": "primary",
        "keyword": "Parthians to restore",
        "source_contains": "Res Gestae",
        "source_title": "Res Gestae Divi Augusti",
        "source_detail": "ch. 29, diplomatic recovery of standards",
        "content_type": "behavior_record",
        "topic_tags": ["diplomacy", "prestige", "deterrence", "symbolic-victory"],
    },
    {
        "bucket": "primary",
        "keyword": "excelled all in influence",
        "source_contains": "Res Gestae",
        "source_title": "Res Gestae Divi Augusti",
        "source_detail": "ch. 34, auctoritas versus potestas",
        "content_type": "quote",
        "topic_tags": ["auctoritas", "constitutional-form", "power"],
    },
    {
        "bucket": "primary",
        "keyword": "Father of my Country",
        "source_contains": "Res Gestae",
        "source_title": "Res Gestae Divi Augusti",
        "source_detail": "ch. 35, title and public inscription",
        "content_type": "quote",
        "topic_tags": ["legitimacy", "honor", "public-consensus"],
    },
    {
        "bucket": "secondary",
        "keyword": "coming as a private citizen with only a few attendants",
        "source_contains": "cassius_dio",
        "source_title": "Cassius Dio, Roman History",
        "source_detail": "Book 45, ch. 5, Octavian enters politics without display",
        "content_type": "behavior_record",
        "topic_tags": ["low-profile-entry", "patience", "political-theater"],
    },
    {
        "bucket": "secondary",
        "keyword": "appearance of liberty",
        "source_contains": "cassius_dio",
        "source_title": "Cassius Dio, Roman History",
        "source_detail": "Book 45, ch. 11, liberty appearance versus monarchical deeds",
        "content_type": "analysis",
        "topic_tags": ["blind-spot", "monarchy", "republican-forms"],
    },
    {
        "bucket": "secondary",
        "keyword": "art and patience rather than open boldness",
        "source_contains": "appian",
        "source_title": "Appian, Civil Wars",
        "source_detail": "Book 3, ch. 14, Atia's advice and Octavian's acceptance",
        "content_type": "behavior_record",
        "topic_tags": ["patience", "indirect-action", "timing", "risk-control"],
    },
    {
        "bucket": "secondary",
        "keyword": "he would call on Antony, as the younger man on the older",
        "source_contains": "appian",
        "source_title": "Appian, Civil Wars",
        "source_detail": "Book 3, ch. 13, public deference while preserving claim",
        "content_type": "behavior_record",
        "topic_tags": ["deference", "status-management", "legitimacy"],
    },
    {
        "bucket": "secondary",
        "keyword": "never to ask a favour at an inopportune time",
        "source_contains": "nicolaus",
        "source_title": "Nicolaus of Damascus, Life of Augustus",
        "source_detail": "Fragment 127, early patronage under Caesar",
        "content_type": "behavior_record",
        "topic_tags": ["timing", "intercession", "restraint", "patronage"],
    },
    {
        "bucket": "secondary",
        "keyword": "concise in his replies",
        "source_contains": "nicolaus",
        "source_title": "Nicolaus of Damascus, Life of Augustus",
        "source_detail": "Fragment 127, Caesar tests Octavian's judgment",
        "content_type": "behavior_record",
        "topic_tags": ["communication", "judgment", "brevity"],
    },
    {
        "bucket": "secondary",
        "keyword": "By making himself known through kindness he persuaded them to obey him",
        "source_contains": "nicolaus",
        "source_title": "Nicolaus of Damascus, Life of Augustus",
        "source_detail": "Fragment 125, eulogistic summary of rule",
        "content_type": "analysis",
        "topic_tags": ["soft-power", "pacification", "benevolence"],
    },
    {
        "bucket": "secondary",
        "keyword": "step by step began to make his ascent",
        "source_contains": "tacitus",
        "source_title": "Tacitus, Annals",
        "source_detail": "Book 1, ch. 2, critical account of concentration of offices",
        "content_type": "analysis",
        "topic_tags": ["blind-spot", "gradualism", "institutional-capture"],
    },
    {
        "bucket": "secondary",
        "keyword": "cheerful acceptance of slavery",
        "source_contains": "tacitus",
        "source_title": "Tacitus, Annals",
        "source_detail": "Book 1, ch. 2, critique of elite accommodation",
        "content_type": "analysis",
        "topic_tags": ["blind-spot", "elite-incentives", "liberty"],
    },
    {
        "bucket": "secondary",
        "keyword": "administration by the Senate and People had been discredited",
        "source_contains": "tacitus",
        "source_title": "Tacitus, Annals",
        "source_detail": "Book 1, ch. 2, provincial preference for order",
        "content_type": "analysis",
        "topic_tags": ["provincial-order", "governance", "tradeoff"],
    },
    {
        "bucket": "secondary",
        "keyword": "the government of the triumvirate was odious to the Romans",
        "source_contains": "plutarch",
        "source_title": "Plutarch, Life of Antony",
        "source_detail": "ch. 21, triumviral violence and reputation",
        "content_type": "analysis",
        "topic_tags": ["blind-spot", "proscription", "civil-war", "coercion"],
    },
    {
        "bucket": "secondary",
        "keyword": "all other matters were easily agreed upon",
        "source_contains": "plutarch",
        "source_title": "Plutarch, Life of Antony",
        "source_detail": "ch. 19, triumvirs divide power and negotiate proscriptions",
        "content_type": "behavior_record",
        "topic_tags": ["coalition", "hard-bargain", "moral-cost"],
    },
    {
        "bucket": "expression",
        "keyword": "The achievements of the Divine Augustus",
        "source_contains": "Res Gestae",
        "source_title": "Res Gestae Divi Augusti",
        "source_detail": "heading and public autobiographical framing",
        "content_type": "expression_sample",
        "topic_tags": ["public-record", "self-framing"],
        "style_tags": ["ledger-like-title", "public-achievement-frame"],
        "dimension": "tone",
        "analysis": "Frames a personal career as a public ledger of achievements, expenses, and service.",
    },
    {
        "bucket": "expression",
        "keyword": "I successfully championed the liberty of the republic",
        "source_contains": "Res Gestae",
        "source_title": "Res Gestae Divi Augusti",
        "source_detail": "ch. 1, first-person legitimating claim",
        "content_type": "expression_sample",
        "topic_tags": ["republican-language", "self-legitimation"],
        "style_tags": ["first-person-action", "legal-public-register"],
        "dimension": "rhetoric",
        "analysis": "Uses first-person action but embeds it inside republican and senatorial validation.",
    },
    {
        "bucket": "expression",
        "keyword": "but I refused it",
        "source_contains": "Res Gestae",
        "source_title": "Res Gestae Divi Augusti",
        "source_detail": "ch. 5, repeated refusal formula",
        "content_type": "expression_sample",
        "topic_tags": ["restraint", "office-refusal"],
        "style_tags": ["plain-refusal", "repeated-formula"],
        "dimension": "sentence-pattern",
        "analysis": "Short refusal clauses punctuate long lists of honors, creating an image of restraint.",
    },
    {
        "bucket": "expression",
        "keyword": "I excelled all in influence",
        "source_contains": "Res Gestae",
        "source_title": "Res Gestae Divi Augusti",
        "source_detail": "ch. 34, auctoritas/potestas distinction",
        "content_type": "expression_sample",
        "topic_tags": ["auctoritas", "constitutional-language"],
        "style_tags": ["technical-distinction", "measured-claim"],
        "dimension": "certainty",
        "analysis": "Draws a precise legal-political distinction instead of simply claiming monarchy.",
    },
    {
        "bucket": "expression",
        "keyword": "He cultivated a style of speaking",
        "source_contains": "Suetonius",
        "source_title": "Suetonius, Life of Augustus",
        "source_detail": "ch. 86, style of speech",
        "content_type": "expression_sample",
        "topic_tags": ["clarity", "plain-style"],
        "style_tags": ["chaste-elegant", "anti-obscurity", "plain-clarity"],
        "dimension": "tone",
        "analysis": "Suetonius explicitly describes a clear, elegant, non-flashy speaking style.",
    },
    {
        "bucket": "expression",
        "keyword": "prepositions with names of cities",
        "source_contains": "Suetonius",
        "source_title": "Suetonius, Life of Augustus",
        "source_detail": "ch. 86, grammatical clarity over elegance",
        "content_type": "expression_sample",
        "topic_tags": ["clarity", "syntax"],
        "style_tags": ["reader-first", "syntactic-explicitness"],
        "dimension": "sentence-pattern",
        "analysis": "Shows a willingness to sacrifice stylistic grace for unambiguous comprehension.",
    },
    {
        "bucket": "expression",
        "keyword": "as for Mark Antony",
        "source_contains": "Suetonius",
        "source_title": "Suetonius, Life of Augustus",
        "source_detail": "ch. 86, polemic against inflated style",
        "content_type": "expression_sample",
        "topic_tags": ["taboo", "anti-grandiosity"],
        "style_tags": ["anti-bombast", "mockery-of-excess"],
        "dimension": "taboo",
        "analysis": "Marks inflated, archaizing, or eccentric language as a style to reject.",
    },
    {
        "bucket": "expression",
        "keyword": "concise in his replies",
        "source_contains": "nicolaus",
        "source_title": "Nicolaus of Damascus, Life of Augustus",
        "source_detail": "Fragment 127, conversational brevity",
        "content_type": "expression_sample",
        "topic_tags": ["brevity", "conversation"],
        "style_tags": ["concise-answer", "to-the-point"],
        "dimension": "conversational_markers",
        "analysis": "Portrays effective conversation as brevity, relevance, and judgment under examination.",
    },
]


def public_extract(ext: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in ext.items() if not k.startswith("_")}


def build() -> None:
    extracted = [extract(spec) for spec in SPECS]
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in extracted:
        buckets[item["_bucket"]].append(public_extract(item))

    today = date.today().isoformat()
    common = {
        "person": PERSON,
        "person_slug": SLUG,
        "collected_at": today,
    }

    write_json(
        PROCESSED / "primary_sources.json",
        {
            **common,
            "source_type": "primary",
            "extracts": buckets["primary"],
            "collection_notes": (
                "Curated first-person or quoted primary-adjacent extracts from the local Augustus corpus. "
                "Res Gestae passages are direct first-person political self-presentation and are prioritized."
            ),
        },
    )
    write_json(
        PROCESSED / "secondary_sources.json",
        {
            **common,
            "source_type": "secondary",
            "extracts": buckets["secondary"],
            "collection_notes": (
                "Curated near-primary and secondary ancient narrative extracts from local Appian, Dio, Nicolaus, "
                "Tacitus, and Plutarch source packs. These are used for context, behavior records, and blind spots."
            ),
        },
    )
    write_json(
        PROCESSED / "expression_dna.json",
        {
            **common,
            "source_type": "expression_dna",
            "extracts": buckets["expression"],
            "collection_notes": (
                "Expression samples are drawn from Res Gestae first-person prose plus Suetonius/Nicolaus testimony "
                "about Augustus's clarity, concision, and anti-bombast style."
            ),
        },
    )
    write_json(
        PROCESSED / "user_sources.json",
        {
            **common,
            "source_type": "user_provided",
            "extracts": [public_extract(item) for item in extracted],
            "collection_notes": (
                "Combined local-source Stage 1 artifact generated from user-provided Augustus raw materials. "
                f"Total curated extracts: {len(extracted)}."
            ),
        },
    )

    worker_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in extracted:
        worker_groups[item["_shard_id"]].append(public_extract(item))
    for shard_id, items in worker_groups.items():
        write_json(
            SHARDS / f"{shard_id}_extracts.json",
            {
                "person_slug": SLUG,
                "shard_id": shard_id,
                "extracts": items,
                "worker_notes": "Curated keyword-based local extraction for Augustus Stage 1.",
            },
        )

    print(f"[OK] Wrote Augustus Stage 1 source artifacts with {len(extracted)} extracts")
    for bucket in ("primary", "secondary", "expression"):
        print(f"  {bucket}: {len(buckets[bucket])}")
    print(f"  worker shard outputs: {len(worker_groups)}")


if __name__ == "__main__":
    build()
