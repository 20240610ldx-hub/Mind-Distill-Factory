#!/usr/bin/env python3
"""Deterministic token, request, and optional cost estimates for Stage 1."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "cost-estimate-v1"


@dataclass(frozen=True)
class Pricing:
    input_per_million: float | None = None
    output_per_million: float | None = None
    ocr_per_page: float | None = None
    web_request: float | None = None

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> "Pricing":
        values = data or {}
        return cls(
            input_per_million=_number_or_none(values.get("input_per_million")),
            output_per_million=_number_or_none(values.get("output_per_million")),
            ocr_per_page=_number_or_none(values.get("ocr_per_page")),
            web_request=_number_or_none(values.get("web_request")),
        )


def _number_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _range_cost(lower: float, upper: float, rate: float | None) -> dict[str, Any]:
    if rate is None:
        return {"lower": None, "upper": None, "status": "cost_unknown"}
    return {
        "lower": round(lower * rate, 6),
        "upper": round(upper * rate, 6),
        "status": "estimated",
    }


def estimate_cost(
    *,
    selected_tokens: int,
    total_tokens: int,
    shard_count: int,
    worker_output_tokens_per_shard: tuple[int, int] = (800, 2_000),
    ocr_pages: int = 0,
    web_requests: int = 0,
    pricing: Pricing | None = None,
) -> dict[str, Any]:
    """Estimate lower/upper bounds without inventing prices when absent."""
    rates = pricing or Pricing()
    selected_tokens = max(0, int(selected_tokens))
    total_tokens = max(selected_tokens, int(total_tokens))
    shard_count = max(0, int(shard_count))
    ocr_pages = max(0, int(ocr_pages))
    web_requests = max(0, int(web_requests))
    output_low, output_high = worker_output_tokens_per_shard
    output_low = max(0, int(output_low))
    output_high = max(output_low, int(output_high))
    worker_output_low = shard_count * output_low
    worker_output_high = shard_count * output_high
    input_cost = _range_cost(selected_tokens / 1_000_000, selected_tokens / 1_000_000, rates.input_per_million)
    output_cost = _range_cost(worker_output_low / 1_000_000, worker_output_high / 1_000_000, rates.output_per_million)
    ocr_cost = _range_cost(ocr_pages, ocr_pages, rates.ocr_per_page)
    web_cost = _range_cost(web_requests, web_requests, rates.web_request)
    known_costs = [
        item for item in (input_cost, output_cost, ocr_cost, web_cost)
        if item["status"] == "estimated"
    ]
    total_lower = sum(float(item["lower"]) for item in known_costs)
    total_upper = sum(float(item["upper"]) for item in known_costs)
    unknown = any(item["status"] == "cost_unknown" for item in (input_cost, output_cost, ocr_cost, web_cost))
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "tokens": {
            "total_corpus": total_tokens,
            "selected_input": selected_tokens,
            "worker_output_lower": worker_output_low,
            "worker_output_upper": worker_output_high,
        },
        "requests": {
            "worker": shard_count,
            "reducer": 1 if shard_count else 0,
            "ocr_pages": ocr_pages,
            "web": web_requests,
        },
        "cost": {
            "input": input_cost,
            "worker_output": output_cost,
            "ocr": ocr_cost,
            "web": web_cost,
            "lower": None if unknown else round(total_lower, 6),
            "upper": None if unknown else round(total_upper, 6),
            "status": "cost_unknown" if unknown else "estimated",
        },
        "assumptions": {
            "worker_output_tokens_per_shard": [output_low, output_high],
            "pricing_snapshot": {
                "input_per_million": rates.input_per_million,
                "output_per_million": rates.output_per_million,
                "ocr_per_page": rates.ocr_per_page,
                "web_request": rates.web_request,
            },
        },
    }


def exceeds_budget(estimate: dict[str, Any], *, max_tokens: int | None = None, max_cost: float | None = None) -> bool:
    tokens = estimate.get("tokens", {})
    if max_tokens is not None and int(tokens.get("selected_input") or 0) > max_tokens:
        return True
    cost = estimate.get("cost", {})
    upper = cost.get("upper")
    return max_cost is not None and upper is not None and float(upper) > max_cost


def write_estimate(path: Path, estimate: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(estimate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
