#!/usr/bin/env python3
"""Convert Stage 1A shard JSON into Read-friendly plain-text files.

Shard JSON stores passage text as an escaped single-line string, which is
unreadable in chunks by an LLM worker (the Read tool caps at ~25k tokens and
line-based offset/limit cannot split one giant line). This helper writes each
shard's passages to local_shards/_read/{shard_id}.txt with REAL newlines, so a
local-source-worker can paginate through it with offset/limit.

Usage:
  python scripts/shard_to_read.py <person-slug>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python scripts/shard_to_read.py <person-slug>")
    slug = sys.argv[1]
    shard_dir = repo_root() / "sources" / slug / "processed" / "local_shards"
    if not shard_dir.exists():
        raise SystemExit(f"Missing shard dir: {shard_dir}. Run `index` first.")

    read_dir = shard_dir / "_read"
    read_dir.mkdir(parents=True, exist_ok=True)

    shard_files = sorted(
        p for p in shard_dir.glob("shard_*.json")
        if not p.stem.endswith("_extracts")
    )
    if not shard_files:
        raise SystemExit(f"No shard_*.json found in {shard_dir}")

    for shard_path in shard_files:
        shard = json.loads(shard_path.read_text(encoding="utf-8"))
        shard_id = shard["shard_id"]
        parts: list[str] = []
        for p in shard["passages"]:
            header = (
                f"=== passage {p['passage_id']} | {p['source_title']} | "
                f"{p['source_detail']} ==="
            )
            parts.append(f"{header}\n{p['text']}")
        body = "\n\n".join(parts)
        out_path = read_dir / f"{shard_id}.txt"
        out_path.write_text(body, encoding="utf-8")
        lines = body.count("\n") + 1
        print(f"[OK] {out_path.name}: {len(body):,} chars, {lines:,} lines")


if __name__ == "__main__":
    main()
