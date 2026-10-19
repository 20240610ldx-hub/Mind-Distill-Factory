#!/usr/bin/env python3
"""闸门通过记录：确定性闸门通过时记下产物指纹，`mdf status` 不加 --check 也能如实显示「已通过」。

`mdf status` 只读文件、毫秒级完成，所以不跑 P1–P6 这类较慢的闸门。以前「闸门通过」这件事不落盘：
2026-10-19 鲁迅 GUI 验收里，包闸门通过、阶段 5 审查也 PASS 了，不加 --check 的状态表仍停在
「P1–P6 未检查」，阶段卡指回阶段 4（发现 15）。

记录绑定产物指纹：闸门之后改过 SKILL.md 或 references/，记录就作废，状态回到「需要重新校验」。
记录放在 output/{slug}/.gates/ 下，发布只复制 SKILL.md、references/*.md 与人物档案，不会带走它。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

RECORD_DIR = ".gates"
PACKAGE_GATE = "package"
# 闸门通过后仍要一路带到状态表、阶段卡的警告：P2 的逐字覆盖率（鲁迅验收发现 11——28 张卡只核对了 12 张，
# 闸门却只说「通过」）。其余警告看校验器输出即可。
CARRIED_CODES = ("P2_COVERAGE",)  # = verify_provenance.EvidenceCoverage.CODE（有测试守着）


def carried_notes(warnings: list[str]) -> list[str]:
    return [w.removeprefix("WARNING: ") for w in warnings if any(code in w for code in CARRIED_CODES)]


def package_files(output_dir: Path) -> list[Path]:
    """包闸门检查的产物：核心层与三份附件。"""
    refs = output_dir / "references"
    return [output_dir / "SKILL.md", *sorted(refs.glob("*.md"))] if output_dir.exists() else []


def fingerprint(base: Path, files: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in files:
        content = path.read_bytes() if path.exists() else b""
        digest.update(f"{path.relative_to(base).as_posix()}\0{hashlib.sha256(content).hexdigest()}\n".encode())
    return digest.hexdigest()


def _record_path(output_dir: Path, gate: str) -> Path:
    return output_dir / RECORD_DIR / f"{gate}.json"


def record_package_gate(output_dir: Path, notes: list[str] | tuple[str, ...] = ()) -> Path:
    path = _record_path(output_dir, PACKAGE_GATE)
    path.parent.mkdir(parents=True, exist_ok=True)
    files = package_files(output_dir)
    path.write_text(json.dumps({
        "gate": PACKAGE_GATE,
        "fingerprint": fingerprint(output_dir, files),
        "files": len(files),
        "passed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "notes": list(notes),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return path


def _current_record(output_dir: Path) -> dict | None:
    try:
        data = json.loads(_record_path(output_dir, PACKAGE_GATE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("fingerprint") != fingerprint(output_dir, package_files(output_dir)):
        return None
    return data


def package_gate_current(output_dir: Path) -> bool | None:
    """None：没有通过记录；True：通过后产物没改过；False：通过后产物改过，要重新校验。"""
    if not _record_path(output_dir, PACKAGE_GATE).exists():
        return None
    return _current_record(output_dir) is not None


def package_gate_notes(output_dir: Path) -> list[str]:
    """通过记录带下来的附注；记录不存在或已作废时为空。"""
    record = _current_record(output_dir)
    notes = record.get("notes", []) if record else []
    return [n for n in notes if isinstance(n, str)]
