# -*- coding: utf-8 -*-
"""Extract agent topology + key events from the Mao distillation session (4f3635e9)."""
import json
import re
from pathlib import Path

SESSION = Path(r"C:\Users\xx\.claude\projects\D--mind-distill-factory\4f3635e9-8bc5-435b-8093-7cffc6cd4a72.jsonl")
OUT = Path(r"D:\mind distill factory\output\_retro_mao_topology.md")

lines_out = ["# Mao session (4f3635e9) — agent topology & key events\n"]
task_calls = []
bash_calls = []
assistant_texts = []

with SESSION.open(encoding="utf-8") as fh:
    for raw in fh:
        try:
            rec = json.loads(raw)
        except json.JSONDecodeError:
            continue
        ts = rec.get("timestamp", "")
        if rec.get("type") != "assistant":
            continue
        msg = rec.get("message", {})
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "tool_use":
                name = block.get("name", "")
                inp = block.get("input", {})
                if name == "Task":
                    task_calls.append({
                        "ts": ts,
                        "type": inp.get("subagent_type", "?"),
                        "model": inp.get("model", "-"),
                        "desc": inp.get("description", ""),
                        "prompt_head": re.sub(r"\s+", " ", str(inp.get("prompt", "")))[:240],
                    })
                elif name == "Bash":
                    cmd = str(inp.get("command", ""))
                    if "validate" in cmd or "task_status" in cmd or "pipeline" in cmd:
                        bash_calls.append({"ts": ts, "cmd": cmd[:200]})
            elif btype == "text":
                t = block.get("text", "")
                if t.strip():
                    assistant_texts.append({"ts": ts, "text": re.sub(r"\s+", " ", t)[:300]})

lines_out.append(f"\n## Task spawns ({len(task_calls)})\n")
for i, t in enumerate(task_calls, 1):
    lines_out.append(f"{i}. [{t['ts']}] type={t['type']} model={t['model']}")
    lines_out.append(f"   desc: {t['desc']}")
    lines_out.append(f"   prompt: {t['prompt_head']}\n")

lines_out.append(f"\n## Pipeline bash calls ({len(bash_calls)})\n")
for b in bash_calls:
    lines_out.append(f"- [{b['ts']}] {b['cmd']}")

lines_out.append(f"\n## Assistant narration timeline ({len(assistant_texts)} texts, sampled every 5th)\n")
for i, a in enumerate(assistant_texts):
    if i % 5 == 0:
        lines_out.append(f"- [{a['ts']}] {a['text']}")

OUT.write_text("\n".join(lines_out), encoding="utf-8")
print(f"WROTE {OUT}: {len(task_calls)} tasks, {len(bash_calls)} pipeline calls, {len(assistant_texts)} texts")
