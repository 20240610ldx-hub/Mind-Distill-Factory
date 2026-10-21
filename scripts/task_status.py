#!/usr/bin/env python3
"""Checkpoint/resume status helper for long-running distillation stages.

Usage:
  python scripts/task_status.py init stage1a <slug>
  python scripts/task_status.py init stage3 <slug>
  python scripts/task_status.py mark-completed <status-path> <unit-id> [--output PATH]
  python scripts/task_status.py mark-failed <status-path> <unit-id> --error TEXT
  python scripts/task_status.py next <status-path>
  python scripts/task_status.py summary <status-path>
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:  # 按路径加载本模块时也能找到同目录的 workspace
    sys.path.insert(0, _SCRIPTS_DIR)
from workspace import Workspace  # noqa: E402  数据根解析规则只在 workspace.py 定义

try:
    from slug_rules import slug_arg
except ImportError:  # pragma: no cover - supports package-style imports
    from scripts.slug_rules import slug_arg  # type: ignore

STATUS_SCHEMA_VERSION = "task-status-v2"


BLOCK_AFTER_FAILURES = 3


if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic replacement prevents concurrent worker updates from leaving a
    # truncated status file. The orchestrator remains the owner of merge order.
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def workspace_of(status_path: Path | None = None, root: Path | None = None) -> Workspace:
    """状态文件属于哪个数据根：显式给的 > 状态文件所在的 `<根>/sources|output/…` > 环境（规则见 workspace.py）。
    状态里的路径一律相对这个根解析，数据根被复制或挪走后进度跟着走，不会读到旧位置的产物。"""
    if root is not None:
        return Workspace.resolve(root)
    return (Workspace.containing(status_path) if status_path is not None else None) or Workspace.resolve()


def stage1a_status_path(slug: str, root: Path | None = None) -> Path:
    return workspace_of(root=root).data_root / "sources" / slug / "processed" / "local_shards" / "task_status.json"


def stage3_status_path(slug: str, root: Path | None = None) -> Path:
    return workspace_of(root=root).data_root / "output" / slug / "stage3_status.json"


def base_status(task_id: str, stage: str, agent_role: str, input_units: list[dict[str, Any]]) -> dict[str, Any]:
    unit_ids = [unit["unit_id"] for unit in input_units]
    return {
        "schema_version": STATUS_SCHEMA_VERSION,
        "task_id": task_id,
        "stage": stage,
        "agent_role": agent_role,
        "status": "pending" if unit_ids else "completed",
        "input_units": input_units,
        "completed_units": [],
        "pending_units": unit_ids,
        "failed_units": [],
        "blocked_units": [],
        "failure_counts": {},
        "output_paths": {},
        "last_error": "",
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }


def refresh_status(status: dict[str, Any]) -> dict[str, Any]:
    all_ids = [unit["unit_id"] for unit in status.get("input_units", [])]
    completed = list(dict.fromkeys(status.get("completed_units", [])))
    failed_items = status.get("failed_units", [])
    failed_ids = []
    for item in failed_items:
        if isinstance(item, dict):
            failed_ids.append(item.get("unit_id"))
        else:
            failed_ids.append(item)
    blocked = set(status.get("blocked_units", []))
    completed_set = set(completed)
    failed_set = {unit_id for unit_id in failed_ids if unit_id}
    pending = [
        unit_id for unit_id in all_ids
        if unit_id not in completed_set and unit_id not in failed_set and unit_id not in blocked
    ]
    status["completed_units"] = completed
    status["pending_units"] = pending
    status["blocked_units"] = sorted(blocked)

    if blocked:
        status["status"] = "blocked"
    elif len(completed_set) == len(all_ids):
        status["status"] = "completed"
    elif completed_set:
        status["status"] = "in_progress"
    else:
        status["status"] = "pending"
    status["updated_at"] = now_iso()
    return status


def init_stage1a(slug: str, root: Path | None = None) -> Path:
    ws = workspace_of(root=root)
    shard_dir = f"sources/{slug}/processed/local_shards"
    manifest_path = ws.locate(f"{shard_dir}/manifest.json")
    if not manifest_path.exists():
        raise SystemExit(f"Missing Stage 1A manifest: {manifest_path}")
    manifest = read_json(manifest_path)
    input_units = []
    for shard in manifest.get("shards", []):
        shard_id = shard.get("shard_id")
        if not shard_id:
            continue
        input_units.append(
            {
                "unit_id": shard_id,
                "unit_type": "local_source_shard",
                "input_path": ws.portable(f"sources/{slug}/processed/{shard.get('path', '')}"),
                "expected_output": f"{shard_dir}/{shard_id}_extracts.json",
                "token_estimate": shard.get("token_estimate", 0),
                "input_fingerprint": manifest.get("input_fingerprint"),
                "shard_fingerprint": shard.get("shard_fingerprint"),
                "agent_role": "local-source-worker",
            }
        )
    status = base_status(f"{slug}:stage1a", "stage1a", "local-source-worker", input_units)
    status["manifest_path"] = f"{shard_dir}/manifest.json"
    status = sync_outputs(status, ws)
    path = stage1a_status_path(slug, ws.data_root)
    write_json(path, status)
    return path


def init_stage3(slug: str, root: Path | None = None) -> Path:
    ws = workspace_of(root=root)
    output_dir = f"output/{slug}"  # 相对数据根：状态文件不记绝对路径
    english_requested = ws.locate(f"{output_dir}/en_requested.flag").exists()
    units = [
        {
            "unit_id": "framework_core",
            "unit_type": "framework_core",
            "input_path": output_dir,
            "expected_output": f"{output_dir}/framework_core.json",
            "agent_role": "framework-core-synthesizer",
        },
        {
            "unit_id": "framework_zh",
            "unit_type": "language_framework",
            "input_path": f"{output_dir}/framework_core.json",
            "expected_output": f"{output_dir}/frameworks.zh.json",
            "agent_role": "framework-synthesizer-zh",
            "depends_on": ["framework_core"],
        },
        *([{
            "unit_id": "framework_en",
            "unit_type": "language_framework",
            "input_path": f"{output_dir}/framework_core.json",
            "expected_output": f"{output_dir}/frameworks.en.json",
            "agent_role": "framework-synthesizer-en",
            "depends_on": ["framework_core"],
        }] if english_requested else []),
        {
            "unit_id": "alignment_review",
            "unit_type": "alignment_review" if english_requested else "zh_self_check",
            "input_path": output_dir,
            "expected_output": f"{output_dir}/framework_alignment_review.md",
            "agent_role": "framework-alignment-reviewer",
            "depends_on": ["framework_zh", "framework_en"] if english_requested else ["framework_zh"],
        },
    ]
    status = base_status(f"{slug}:stage3", "stage3", "framework-stage", units)
    status = sync_outputs(status, ws)
    path = stage3_status_path(slug, ws.data_root)
    write_json(path, status)
    return path


PATH_FIELDS = ("input_path", "expected_output")


def portable_status(status: dict[str, Any], ws: Workspace) -> dict[str, Any]:
    """旧版状态文件存的是写入时的绝对路径：读进来就改成相对数据根的形式，下次保存即完成迁移。"""
    for unit in status.get("input_units", []):
        for field in PATH_FIELDS:
            if unit.get(field):
                unit[field] = ws.portable(unit[field])
    if status.get("manifest_path"):
        status["manifest_path"] = ws.portable(status["manifest_path"])
    status["output_paths"] = {unit_id: ws.portable(path) for unit_id, path in status.get("output_paths", {}).items()}
    return status


def display_unit(unit: dict[str, Any], ws: Workspace) -> dict[str, Any]:
    """给 `next` 的读者（编排者、worker）看的单元：路径换成当前数据根下的真实位置，不改状态文件。"""
    return {**unit, **{f: str(ws.locate(unit[f])) for f in PATH_FIELDS if unit.get(f)}}


def _output_matches_unit(unit: dict[str, Any], ws: Workspace) -> bool:
    expected = unit.get("expected_output")
    output_path = ws.locate(expected) if expected else None
    if output_path is None or not output_path.is_file():
        return False
    unit_type = unit.get("unit_type")
    if unit_type != "local_source_shard":
        if output_path.suffix.lower() == ".json":
            try:
                output = read_json(output_path)
            except (OSError, json.JSONDecodeError):
                return False
            if not isinstance(output, dict):
                return False
            person_slug = output.get("person_slug")
            if person_slug:
                parts = ws.portable(unit.get("input_path", "")).split("/")
                expected_slug = parts[1] if parts[0] == "output" and len(parts) > 1 else ""
                if expected_slug and person_slug != expected_slug:
                    return False
        else:
            try:
                return bool(output_path.read_text(encoding="utf-8").strip())
            except OSError:
                return False
        return True

    if output_path.suffix.lower() != ".json":
        return False
    try:
        output = read_json(output_path)
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(output, dict):
        return False
    expected_fingerprint = unit.get("input_fingerprint")
    if expected_fingerprint and output.get("input_fingerprint") != expected_fingerprint:
        return False
    if output.get("shard_id") != unit.get("unit_id"):
        return False
    return True


def sync_outputs(status: dict[str, Any], ws: Workspace | None = None) -> dict[str, Any]:
    ws = ws or workspace_of()
    for unit in status.get("input_units", []):
        unit_id = unit["unit_id"]
        if _output_matches_unit(unit, ws) and unit_id not in status.get("completed_units", []):
            status.setdefault("completed_units", []).append(unit_id)
            status.setdefault("output_paths", {})[unit_id] = ws.portable(unit["expected_output"])
    return refresh_status(status)


def load_status(path: Path) -> dict[str, Any]:
    ws = workspace_of(path)
    return sync_outputs(portable_status(read_json(path), ws), ws)


def save_status(path: Path, status: dict[str, Any]) -> None:
    write_json(path, refresh_status(status))


def mark_completed(path: Path, unit_id: str, output: str | None) -> None:
    status = load_status(path)
    if unit_id not in [unit["unit_id"] for unit in status.get("input_units", [])]:
        raise SystemExit(f"Unknown unit_id '{unit_id}' in {path}")
    if unit_id not in status.get("completed_units", []):
        status.setdefault("completed_units", []).append(unit_id)
    status["failed_units"] = [
        item for item in status.get("failed_units", [])
        if not ((item.get("unit_id") if isinstance(item, dict) else item) == unit_id)
    ]
    if unit_id in status.get("blocked_units", []):
        status["blocked_units"] = [u for u in status["blocked_units"] if u != unit_id]
    if output:
        status.setdefault("output_paths", {})[unit_id] = workspace_of(path).portable(output)
    status["last_error"] = ""
    save_status(path, status)


def mark_failed(path: Path, unit_id: str, error: str) -> None:
    status = load_status(path)
    if unit_id not in [unit["unit_id"] for unit in status.get("input_units", [])]:
        raise SystemExit(f"Unknown unit_id '{unit_id}' in {path}")
    counts = status.setdefault("failure_counts", {})
    counts[unit_id] = int(counts.get(unit_id, 0)) + 1
    status["failed_units"] = [
        item for item in status.get("failed_units", [])
        if not ((item.get("unit_id") if isinstance(item, dict) else item) == unit_id)
    ]
    status.setdefault("failed_units", []).append(
        {
            "unit_id": unit_id,
            "error": error,
            "failure_count": counts[unit_id],
            "failed_at": now_iso(),
        }
    )
    if counts[unit_id] >= BLOCK_AFTER_FAILURES and unit_id not in status.get("blocked_units", []):
        status.setdefault("blocked_units", []).append(unit_id)
    status["last_error"] = f"{unit_id}: {error}"
    save_status(path, status)


def runnable_units(status: dict[str, Any]) -> list[dict[str, Any]]:
    completed = set(status.get("completed_units", []))
    blocked = set(status.get("blocked_units", []))
    failed_ids = [
        item.get("unit_id") if isinstance(item, dict) else item
        for item in status.get("failed_units", [])
    ]
    candidates = list(dict.fromkeys([*failed_ids, *status.get("pending_units", [])]))
    units_by_id = {unit["unit_id"]: unit for unit in status.get("input_units", [])}
    runnable = []
    for unit_id in candidates:
        if not unit_id or unit_id in completed or unit_id in blocked:
            continue
        unit = units_by_id.get(unit_id)
        if not unit:
            continue
        depends_on = unit.get("depends_on", [])
        if all(dep in completed for dep in depends_on):
            runnable.append(unit)
    return runnable


def cmd_next(path: Path) -> None:
    status = load_status(path)
    ws = workspace_of(path)
    print(json.dumps([display_unit(u, ws) for u in runnable_units(status)], ensure_ascii=False, indent=2))


def cmd_summary(path: Path) -> None:
    status = load_status(path)
    print(f"task_id: {status.get('task_id')}")
    print(f"stage: {status.get('stage')}")
    print(f"status: {status.get('status')}")
    print(f"input_units: {len(status.get('input_units', []))}")
    print(f"completed: {len(status.get('completed_units', []))}")
    print(f"pending: {len(status.get('pending_units', []))}")
    print(f"failed: {len(status.get('failed_units', []))}")
    print(f"blocked: {len(status.get('blocked_units', []))}")
    if status.get("last_error"):
        print(f"last_error: {status['last_error']}")
    runnable = runnable_units(status)
    if runnable:
        print("next_units:")
        for unit in runnable:
            print(f"  - {unit['unit_id']} ({unit.get('agent_role', 'agent')})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init")
    init.add_argument("stage", choices=["stage1a", "stage3"])
    init.add_argument("slug", type=slug_arg)

    completed = sub.add_parser("mark-completed")
    completed.add_argument("status_path")
    completed.add_argument("unit_id")
    completed.add_argument("--output", default=None)

    failed = sub.add_parser("mark-failed")
    failed.add_argument("status_path")
    failed.add_argument("unit_id")
    failed.add_argument("--error", required=True)

    next_parser = sub.add_parser("next")
    next_parser.add_argument("status_path")

    summary = sub.add_parser("summary")
    summary.add_argument("status_path")
    summary.add_argument("--strict", action="store_true",
                         help="还有 pending / failed / blocked 单元时退出码为 1（当检查点用）")

    args = parser.parse_args()
    if args.command == "init":
        path = init_stage1a(args.slug) if args.stage == "stage1a" else init_stage3(args.slug)
        print(f"[OK] wrote {path}")
        cmd_summary(path)
    elif args.command == "mark-completed":
        mark_completed(Path(args.status_path), args.unit_id, args.output)
        cmd_summary(Path(args.status_path))
    elif args.command == "mark-failed":
        mark_failed(Path(args.status_path), args.unit_id, args.error)
        cmd_summary(Path(args.status_path))
    elif args.command == "next":
        cmd_next(Path(args.status_path))
    elif args.command == "summary":
        cmd_summary(Path(args.status_path))
        if args.strict:
            status = load_status(Path(args.status_path))
            open_units = [k for k in ("pending_units", "failed_units", "blocked_units") if status.get(k)]
            if open_units:
                print("[FAIL] 仍有未完成的单元：" + "、".join(open_units))
                raise SystemExit(1)


if __name__ == "__main__":
    main()
