#!/usr/bin/env python3
"""采集的本地设置：User-Agent 联系方式与法域。问过用户后存在数据根里复用，不写进入库的采集策略。

用户 2026-10-24 决定：联系方式与法域「询问用户后存入项目记忆复用」。所以：
- 存在 `{数据根}/.mdf/acquisition.json`（.gitignore 忽略），整体复制数据根时一起带走；
- `config/acquisition_policy.json` 里的 contact / jurisdiction 保持为空，入库的值仍优先（见 acquire.resolve_contact）；
- 法域可以显式记为「暂不设定」（jurisdiction_decided=true），编排者据此不再反复问；未设定时公有领域一律待复核。

    python scripts/mdf.py acquire-settings                       # 查看
    python scripts/mdf.py acquire-settings --contact <项目主页 URL>
    python scripts/mdf.py acquire-settings --jurisdiction SG     # 或 --no-jurisdiction
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:  # 按路径加载本模块时也能找到同目录的 workspace
    sys.path.insert(0, _SCRIPTS_DIR)
from workspace import data_root  # noqa: E402  数据根解析规则只在 workspace.py 定义

SCHEMA = "mdf-acquisition-settings-v1"
RELATIVE_PATH = Path(".mdf") / "acquisition.json"
EMPTY: dict[str, Any] = {"contact": None, "jurisdiction": None, "jurisdiction_decided": False}
_UNSET = object()
_JURISDICTION_RE = re.compile(r"[A-Za-z]{2}")


def path_for(root: Path) -> Path:
    return Path(root) / RELATIVE_PATH


def load(root: Path) -> dict[str, Any]:
    """读本地设置；文件不存在或坏了都当作没设（坏文件不该让采集带着错的联系方式发请求）。"""
    try:
        data = json.loads(path_for(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return dict(EMPTY)
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        return dict(EMPTY)
    return {key: data.get(key, default) for key, default in EMPTY.items()}


def save(root: Path, *, contact: Any = _UNSET, jurisdiction: Any = _UNSET, now: str | None = None) -> dict[str, Any]:
    """只改给出的字段。contact 不能为空或含空白；jurisdiction 是两位国家码，None 表示「用户选择暂不设定」。"""
    current = load(root)
    if contact is not _UNSET:
        value = str(contact or "").strip()
        if not value or any(ch.isspace() for ch in value):
            raise ValueError(f"联系方式不能为空或含空白：{contact!r}（建议填项目主页 URL）")
        current["contact"] = value
    if jurisdiction is not _UNSET:
        if jurisdiction is None:
            current["jurisdiction"] = None
        elif isinstance(jurisdiction, str) and _JURISDICTION_RE.fullmatch(jurisdiction.strip()):
            current["jurisdiction"] = jurisdiction.strip().upper()
        else:
            raise ValueError(f"法域应为两位 ISO 国家码（如 SG、US），不能是 {jurisdiction!r}")
        current["jurisdiction_decided"] = True
    record = {"schema": SCHEMA, **current, "updated_at": now or datetime.now(timezone.utc).replace(microsecond=0).isoformat()}
    path = path_for(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return current


def describe(data: dict[str, Any]) -> list[str]:
    jurisdiction = data.get("jurisdiction")
    if jurisdiction:
        law = f"法域：{jurisdiction}"
    elif data.get("jurisdiction_decided"):
        law = "法域：用户选择暂不设定（公有领域判定一律待复核）"
    else:
        law = "法域：还没问过用户（公有领域判定一律待复核）"
    return [f"联系方式：{data.get('contact') or '未设置（联网采集会被拒绝）'}", law]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="采集的本地设置（联系方式、法域），存在数据根的 .mdf/ 下")
    parser.add_argument("--contact", help="User-Agent 里的联系方式，建议填项目主页 URL")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--jurisdiction", help="两位 ISO 国家码，如 SG、US")
    group.add_argument("--no-jurisdiction", action="store_true", help="记下用户选择暂不设定法域")
    parser.add_argument("--root", help="数据根目录（默认 MDF_DATA_ROOT，再默认仓库根）")
    args = parser.parse_args(argv)
    root = data_root(args.root)
    changes: dict[str, Any] = {}
    if args.contact is not None:
        changes["contact"] = args.contact
    if args.jurisdiction is not None:
        changes["jurisdiction"] = args.jurisdiction
    elif args.no_jurisdiction:
        changes["jurisdiction"] = None
    try:
        data = save(root, **changes) if changes else load(root)
    except ValueError as exc:
        parser.error(str(exc))
    print(f"采集设置（{path_for(root).as_posix()}）")
    for line in describe(data):
        print(f"- {line}")
    return 0


if __name__ == "__main__":
    if sys.platform.startswith("win"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except AttributeError:
            pass
    sys.exit(main())
