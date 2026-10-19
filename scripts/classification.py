#!/usr/bin/env python3
"""类目决策：阶段 0.3 由用户确认，落盘到 sources/{slug}/classification.json，下游只读不选。

墨子试跑的教训：编排者在对话里定了 governance 主类，但这个决定没有任何通道传给新进程，
principle-extractor / framework-synthesizer 各自翻 taxonomy.json 自选，最终包里成了 philosophy 主类。

流程：编排者推荐分类 → 用 AskUserQuestion（或 harness 的同类提问工具）让用户确认 →
`mdf classify <slug> --primary X --secondary a,b` 写盘 → `mdf brief` 把它写进简报「上下文」，
需要类目的步骤缺这份文件时拒绝生成简报 → validate frameworks / package 核对产物与之一致。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

SCHEMA = "classification-v1"
FILENAME = "classification.json"
MAX_SECONDARY = 2
CODE_ROOT = Path(__file__).resolve().parent.parent


def path_for(root: Path, slug: str) -> Path:
    return root / "sources" / slug / FILENAME


def load_taxonomy(code_root: Path = CODE_ROOT) -> dict[str, dict[str, Any]]:
    data = json.loads((code_root / "config" / "taxonomy.json").read_text(encoding="utf-8"))
    return {c["id"]: c for c in data.get("categories", []) if isinstance(c, dict) and c.get("id")}


def problems(primary: str | None, secondary: list[str], taxonomy: dict[str, Any]) -> list[str]:
    """CLAUDE.md 规则 5：1 主 + 至多 2 副，且都在 taxonomy 里、互不重复。"""
    found: list[str] = []
    if not primary:
        found.append("缺少主类")
    elif primary not in taxonomy:
        found.append(f"主类 {primary!r} 不在 config/taxonomy.json 中")
    if len(secondary) > MAX_SECONDARY:
        found.append(f"副类最多 {MAX_SECONDARY} 个，给了 {len(secondary)} 个")
    for cat in secondary:
        if cat not in taxonomy:
            found.append(f"副类 {cat!r} 不在 config/taxonomy.json 中")
    if primary and primary in secondary:
        found.append(f"{primary!r} 同时是主类和副类")
    if len(set(secondary)) != len(secondary):
        found.append("副类有重复")
    return found


def load(root: Path, slug: str) -> dict[str, Any] | None:
    """读已确认的类目；文件不存在返回 None，文件损坏或内容不合规抛 ValueError（不静默回落）。"""
    path = path_for(root, slug)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except ValueError as exc:
        raise ValueError(f"{path.as_posix()} 不是合法 JSON：{exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path.as_posix()} 顶层必须是对象")
    found = problems(data.get("primary"), list(data.get("secondary") or []), load_taxonomy())
    if found:
        raise ValueError(f"{path.as_posix()}：" + "；".join(found))
    return data


def write(root: Path, slug: str, primary: str, secondary: list[str], person_name: str | None = None,
          now: datetime | None = None) -> Path:
    found = problems(primary, secondary, load_taxonomy())
    if found:
        raise ValueError("；".join(found))
    path = path_for(root, slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "schema": SCHEMA,
        "slug": slug,
        "person_name": person_name or None,
        "primary": primary,
        "secondary": secondary,
        "confirmed_by": "user",
        "confirmed_at": f"{(now or datetime.now()):%Y-%m-%d %H:%M:%S}",
    }
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return path


def describe(data: dict[str, Any], taxonomy: dict[str, Any] | None = None) -> str:
    """`governance（治理）；副类 philosophy（哲理）、conduct（行事）`"""
    taxonomy = taxonomy if taxonomy is not None else load_taxonomy()

    def name(cat: str) -> str:
        zh = (taxonomy.get(cat) or {}).get("name_zh")
        return f"{cat}（{zh}）" if zh else cat

    secondary = data.get("secondary") or []
    return f"主类 {name(data['primary'])}；副类 " + ("、".join(name(c) for c in secondary) if secondary else "无")


def mismatch(data: dict[str, Any], primary: str | None, secondary: list[str] | None) -> list[str]:
    """产物里的类目与用户确认的不一致时，返回差异说明。"""
    found = []
    if primary != data["primary"]:
        found.append(f"主类是 {primary!r}，用户确认的是 {data['primary']!r}")
    if sorted(secondary or []) != sorted(data.get("secondary") or []):
        found.append(f"副类是 {sorted(secondary or [])}，用户确认的是 {sorted(data.get('secondary') or [])}")
    return found
