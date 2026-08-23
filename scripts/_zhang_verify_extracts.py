#!/usr/bin/env python3
"""Temp deterministic verifier for zhang-juzheng worker extracts.
Reports per file: count, content_type hist, confidence hist, U+FFFD count,
empty-field count, and a sample. Writes UTF-8 to _extracts_check.txt (Read it back).
"""
import json, collections
from pathlib import Path

sd = Path(__file__).resolve().parents[1] / "sources" / "zhang-juzheng" / "processed" / "local_shards"
files = sorted(sd.glob("shard_*_extracts.json"))
lines = []
total = 0
for f in files:
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except Exception as e:
        lines.append(f"{f.name}\tJSON_ERROR: {e}")
        continue
    exs = data.get("extracts", [])
    total += len(exs)
    ct = collections.Counter(e.get("content_type") for e in exs)
    cf = collections.Counter(e.get("confidence") for e in exs)
    fffd = sum(e.get("text", "").count("�") for e in exs)
    empty = sum(1 for e in exs if not (e.get("text") or "").strip()
                or not (e.get("source_detail") or "").strip())
    sample = (exs[0].get("text", "")[:48] if exs else "<none>")
    lines.append(
        f"{f.name}\tn={len(exs)}\tCT={dict(ct)}\tCONF={dict(cf)}\t"
        f"FFFD={fffd}\tEMPTY={empty}\tsample={sample}"
    )
out = sd / "_extracts_check.txt"
out.write_text("\n".join(lines) + f"\n--- {len(files)} files, {total} extracts ---\n", encoding="utf-8")
print(f"checked {len(files)} files, {total} extracts -> {out}")
