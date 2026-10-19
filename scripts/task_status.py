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
from workspace import data_root  # noqa: E402  数据根解析规则只在 workspace.py 定义

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


def repo_root() -> Path:
    """数据根目录：MDF_DATA_ROOT 优先（mdf 的 --root 与测试用），否则仓库根（规则见 workspace.py）。"""
    return data_root()


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


def stage1a_status_path(slug: str) -> Path:
    return repo_root() / "sources" / slug / "processed" / "local_shards" / "task_status.json"


def stage3_status_path(slug: str) -> Path:
    return repo_root() / "output" / slug / "stage3_status.json"


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


def init_stage1a(slug: str) -> Path:
    manifest_path = repo_root() / "sources" / slug / "processed" / "local_shards" / "manifest.json"
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
                "input_path": str(repo_root() / "sources" / slug / "processed" / shard.get("path", "")),
                "expected_output": str(repo_root() / "sources" / slug / "processed" / "local_shards" / f"{shard_id}_extracts.json"),
                "token_estimate": shard.get("token_estimate", 0),
                "input_fingerprint": manifest.get("input_fingerprint"),
                "shard_fingerprint": shard.get("shard_fingerprint"),
                "agent_role": "local-source-worker",
            }
        )
    status = base_status(f"{slug}:stage1a", "stage1a", "local-source-worker", input_units)
    status["manifest_path"] = str(manifest_path)
    status = sync_outputs(status)
    path = stage1a_status_path(slug)
    write_json(path, status)
    return path


def init_stage3(slug: str) -> Path:
    root = repo_root()
    output_dir = root / "output" / slug
    english_requested = (output_dir / "en_requested.flag").exists()
    units = [
        {
            "unit_id": "framework_core",
            "unit_type": "framework_core",
            "input_path": str(output_dir),
            "expected_output": str(output_dir / "framework_core.json"),
            "agent_role": "framework-core-synthesizer",
        },
        {
            "unit_id": "framework_zh",
            "unit_type": "language_framework",
            "input_path": str(output_dir / "framework_core.json"),
            "expected_output": str(output_dir / "frameworks.zh.json"),
            "agent_role": "framework-synthesizer-zh",
            "depends_on": ["framework_core"],
        },
        *([{
            "unit_id": "framework_en",
            "unit_type": "language_framework",
            "input_path": str(output_dir / "framework_core.json"),
            "expected_output": str(output_dir / "frameworks.en.json"),
            "agent_role": "framework-synthesizer-en",
            "depends_on": ["framework_core"],
        }] if english_requested else []),
        {
            "unit_id": "alignment_review",
            "unit_type": "alignment_review" if english_requested else "zh_self_check",
            "input_path": str(output_dir),
            "expected_output": str(output_dir / "framework_alignment_review.md"),
            "agent_role": "framework-alignment-reviewer",
            "depends_on": ["framework_zh", "framework_en"] if english_requested else ["framework_zh"],
        },
    ]
    status = base_status(f"{slug}:stage3", "stage3", "framework-stage", units)
    status = sync_outputs(status)
    path = stage3_status_path(slug)
    write_json(path, status)
    return path


def _output_matches_unit(unit: dict[str, Any]) -> bool:
    expected = unit.get("expected_output")
    if not expected or not Path(expected).is_file():
        return False
    output_path = Path(expected)
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
                expected_slug = unit.get("input_path", "").split("output/")[-1].split("/")[0]
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


def sync_outputs(status: dict[str, Any]) -> dict[str, Any]:
    for unit in status.get("input_units", []):
        unit_id = unit["unit_id"]
        expected = unit.get("expected_output")
        if _output_matches_unit(unit) and unit_id not in status.get("completed_units", []):
            status.setdefault("completed_units", []).append(unit_id)
            status.setdefault("output_paths", {})[unit_id] = expected
    return refresh_status(status)


def load_status(path: Path) -> dict[str, Any]:
    status = read_json(path)
    return sync_outputs(status)


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
        status.setdefault("output_paths", {})[unit_id] = output
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
    print(json.dumps(runnable_units(status), ensure_ascii=False, indent=2))


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
