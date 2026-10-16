#!/usr/bin/env python3
"""Plan bounded, adaptive local-source worker dispatch.

The orchestrator owns actual dispatch. This module produces a deterministic
queue annotation so it can keep difficult shards from exhausting one context.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Iterable

SCHEMA_VERSION = "worker-dispatch-plan-v1"


def difficulty_for_unit(unit: dict[str, Any]) -> str:
    score = 0
    tokens = int(unit.get("token_estimate") or 0)
    if tokens >= 45_000:
        score += 3
    elif tokens >= 30_000:
        score += 2
    elif tokens >= 20_000:
        score += 1
    if unit.get("ocr_required") or unit.get("extraction_quality_band") in {"poor", "unreadable"}:
        score += 2
    if unit.get("language") == "other":
        score += 1
    if unit.get("substantive_image_count", 0):
        score += 1
    if score >= 5:
        return "high"
    if score >= 3:
        return "medium"
    return "low"


def build_dispatch_plan(
    units: Iterable[dict[str, Any]],
    *,
    context_window_tokens: int = 100_000,
    reserved_tokens: int = 12_000,
    max_concurrency: int | None = None,
) -> dict[str, Any]:
    """Annotate selected units for dynamic dispatch by the main agent."""
    available = max(20_000, context_window_tokens - reserved_tokens)
    annotated: list[dict[str, Any]] = []
    for unit in units:
        item = dict(unit)
        tokens = int(item.get("token_estimate") or 0)
        difficulty = difficulty_for_unit(item)
        multiplier = {"low": 1.0, "medium": 1.25, "high": 1.6}[difficulty]
        estimated_context = min(context_window_tokens, max(20_000, math.ceil(tokens * multiplier)))
        item["difficulty"] = difficulty
        item["estimated_context_tokens"] = estimated_context
        item["recommended_max_tool_uses"] = {"low": 30, "medium": 24, "high": 18}[difficulty]
        item["dispatch_priority"] = (
            0 if difficulty == "high" else 1 if difficulty == "medium" else 2,
            -int(item.get("token_estimate") or 0),
            str(item.get("unit_id") or item.get("shard_id") or ""),
        )
        item["dispatch_note"] = {
            "low": "可与同级任务并行；保持一个 shard 一个 worker。",
            "medium": "限制并发并优先安排；若上下文紧张，先拆分该 shard。",
            "high": "主 agent 动态单独派发；不得与其他高难度 shard 共用上下文。",
        }[difficulty]
        annotated.append(item)

    annotated.sort(key=lambda item: item["dispatch_priority"])
    if max_concurrency is None:
        max_concurrency = max(1, min(8, available // 35_000))
    high_count = sum(item["difficulty"] == "high" for item in annotated)
    if high_count:
        max_concurrency = min(max_concurrency, 2)

    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "context_window_tokens": context_window_tokens,
        "reserved_tokens": reserved_tokens,
        "available_tokens": available,
        "recommended_max_concurrency": max_concurrency,
        "units": annotated,
        "dispatch_policy": [
            "主 agent 每次只派发当前可容纳的 unit，不一次性提交整个队列。",
            "高难度 unit 单独派发；连续失败后先拆分或降低并发。",
            "每个 worker 只读取一个 unit，完成后才释放该上下文槽位。",
        ],
    }


def next_dispatch_units(
    plan: dict[str, Any],
    *,
    completed: set[str] | None = None,
    active: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Return the next bounded batch for the orchestrator."""
    done = completed or set()
    running = active or set()
    slots = int(plan.get("recommended_max_concurrency") or 1)
    result: list[dict[str, Any]] = []
    for unit in plan.get("units", []):
        unit_id = str(unit.get("unit_id") or unit.get("shard_id") or "")
        if not unit_id or unit_id in done or unit_id in running:
            continue
        result.append(unit)
        if len(result) >= slots:
            break
    return result
