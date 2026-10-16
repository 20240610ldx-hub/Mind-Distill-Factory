#!/usr/bin/env python3
"""Deterministic stratified sampling and worker dispatch planning."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = "sampling-plan-v1"


@dataclass(frozen=True)
class SamplingConfig:
    mode: str = "auto"
    seed: int = 20261014
    pilot_max_tokens: int = 150_000
    representative_max_tokens: int = 500_000
    broad_fraction: float = 0.45
    minimum_units_per_stratum: int = 1


def stable_rank(value: str, seed: int) -> int:
    digest = hashlib.sha256(f"{seed}:{value}".encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def choose_mode(total_tokens: int, config: SamplingConfig) -> str:
    if config.mode in {"exhaustive", "stratified"}:
        return config.mode
    return "exhaustive" if total_tokens <= config.pilot_max_tokens else "stratified"


def _stratum_key(item: dict[str, Any]) -> str:
    source = item.get("source_id") or item.get("source_file") or "unknown"
    language = item.get("language") or "other"
    quality = item.get("extraction_quality_band") or item.get("quality_band") or "unknown"
    priority = item.get("source_priority", 5)
    return f"priority={priority}|language={language}|quality={quality}|source={source}"


def build_sampling_plan(
    units: Iterable[dict[str, Any]],
    *,
    config: SamplingConfig | None = None,
) -> dict[str, Any]:
    cfg = config or SamplingConfig()
    normalized = [dict(unit) for unit in units]
    total_tokens = sum(int(unit.get("token_estimate") or 0) for unit in normalized)
    mode = choose_mode(total_tokens, cfg)
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for unit in normalized:
        unit["stratum_key"] = unit.get("stratum_key") or _stratum_key(unit)
        groups[unit["stratum_key"]].append(unit)

    selected: list[dict[str, Any]] = []
    strata_report: list[dict[str, Any]] = []
    for key, members in sorted(groups.items()):
        members.sort(key=lambda item: stable_rank(str(item.get("unit_id", "")), cfg.seed))
        group_tokens = sum(int(item.get("token_estimate") or 0) for item in members)
        if mode == "exhaustive":
            take = len(members)
        else:
            target = max(cfg.minimum_units_per_stratum, math.ceil(len(members) * cfg.broad_fraction))
            take = min(len(members), target)
        chosen = members[:take]
        for item in members:
            item["selected"] = item in chosen
            item["inclusion_probability"] = round(take / len(members), 6) if members else 0.0
            if item["selected"]:
                selected.append(item)
        selected_tokens = sum(int(item.get("token_estimate") or 0) for item in chosen)
        strata_report.append({
            "stratum_key": key,
            "unit_count": len(members),
            "selected_count": take,
            "token_estimate": group_tokens,
            "selected_token_estimate": selected_tokens,
            "coverage_fraction": round(take / len(members), 6) if members else 0.0,
        })

    selected.sort(key=lambda item: str(item.get("unit_id", "")))
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": mode,
        "seed": cfg.seed,
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "total_unit_count": len(normalized),
        "selected_unit_count": len(selected),
        "total_token_estimate": total_tokens,
        "selected_token_estimate": sum(int(item.get("token_estimate") or 0) for item in selected),
        "strata": strata_report,
        "units": normalized,
        "selected_units": selected,
        "coverage_report": {
            "strata_count": len(strata_report),
            "uncovered_strata": [
                item["stratum_key"] for item in strata_report if item["selected_count"] == 0
            ],
        },
    }


def write_plan(path: Path, plan: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
