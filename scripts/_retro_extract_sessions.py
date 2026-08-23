# -*- coding: utf-8 -*-
"""Retrospective helper: extract user-message timeline from all session transcripts.

Writes a markdown map of every main-session JSONL in the project transcript dir:
session id, start/end timestamps, and the first 300 chars of each real user message
(skipping tool results, system reminders, command stdout noise).
"""
import json
import re
from pathlib import Path

TRANSCRIPT_DIR = Path(r"C:\Users\xx\.claude\projects\D--mind-distill-factory")
OUT = Path(r"D:\mind distill factory\output\_retro_session_map.md")

NOISE_PATTERNS = (
    "<system-reminder>",
    "<local-command-stdout>",
    "Caveat: The messages below",
    "This session is being continued",
)


def user_text(msg_content):
    """Pull plain text from a user message's content field."""
    if isinstance(msg_content, str):
        return msg_content
    if isinstance(msg_content, list):
        parts = []
        for block in msg_content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "\n".join(parts)
    return ""


def is_noise(text):
    if not text.strip():
        return True
    for pat in NOISE_PATTERNS:
        if pat in text:
            return True
    # pure tool-result envelopes
    if text.strip().startswith("[{") or text.strip().startswith("{\""):
        return True
    return False


def main():
    lines_out = ["# Session map — D--mind-distill-factory transcripts\n"]
    files = sorted(
        (p for p in TRANSCRIPT_DIR.glob("*.jsonl")),
        key=lambda p: p.stat().st_mtime,
    )
    for path in files:
        session_id = path.stem
        first_ts, last_ts = None, None
        user_msgs = []
        try:
            with path.open(encoding="utf-8") as fh:
                for raw in fh:
                    try:
                        rec = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    ts = rec.get("timestamp")
                    if ts:
                        if first_ts is None:
                            first_ts = ts
                        last_ts = ts
                    if rec.get("type") != "user":
                        continue
                    msg = rec.get("message", {})
                    if not isinstance(msg, dict):
                        continue
                    text = user_text(msg.get("content"))
                    if is_noise(text):
                        continue
                    # collapse whitespace, trim
                    text = re.sub(r"\s+", " ", text).strip()
                    if text:
                        user_msgs.append(text[:300])
        except OSError as exc:
            lines_out.append(f"\n## {session_id}\n- READ ERROR: {exc}\n")
            continue
        size_mb = path.stat().st_size / 1048576
        lines_out.append(f"\n## {session_id}  ({size_mb:.2f} MB)")
        lines_out.append(f"- span: {first_ts} → {last_ts}")
        lines_out.append(f"- user messages: {len(user_msgs)}")
        for i, m in enumerate(user_msgs, 1):
            lines_out.append(f"  {i}. {m}")
    OUT.write_text("\n".join(lines_out), encoding="utf-8")
    print(f"WROTE {OUT} ({len(files)} sessions)")


if __name__ == "__main__":
    main()
