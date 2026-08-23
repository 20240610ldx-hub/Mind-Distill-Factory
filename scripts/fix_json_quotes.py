#!/usr/bin/env python3
"""Surgically fix embedded ASCII double-quotes inside JSON string values.
Uses a state machine to distinguish structural quotes from embedded text quotes."""
import json, sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
base = Path("sources/lu-xun/processed/local_shards")

names = ["shard_004", "shard_008", "shard_010", "shard_030"]

for name in names:
    path = base / f"{name}_extracts.json"
    text = path.read_text(encoding="utf-8-sig")

    # Quick check if already valid
    try:
        json.loads(text)
        print(f"  OK  {name}")
        continue
    except json.JSONDecodeError:
        pass

    # State-machine repair
    result = []
    in_string = False
    i = 0
    while i < len(text):
        ch = text[i]

        # Handle backslash escapes
        if ch == '\\' and in_string:
            result.append(ch)
            i += 1
            if i < len(text):
                result.append(text[i])
                i += 1
            continue

        if ch == '"':
            if not in_string:
                in_string = True
                result.append(ch)
            else:
                # Check if this is a structural close-quote
                # Look ahead for structural characters
                found_structural = False
                for j in range(i+1, len(text)):
                    nch = text[j]
                    if nch in ',]}:\n':
                        found_structural = True
                        break
                    if nch == '"':
                        # Another quote could be the actual delimiter or also embedded
                        # This is ambiguous - check if previous char is CJK
                        break
                    if nch not in ' \t\r':
                        break

                prev_char = text[i-1] if i > 0 else ''
                next_char = text[i+1] if i+1 < len(text) else ''

                # A structural close-quote is followed by whitespace then ,]}:
                # An embedded quote is between CJK characters or followed by CJK
                prev_is_cjk = '一' <= prev_char <= '鿿'
                next_is_cjk = '一' <= next_char <= '鿿'

                if found_structural and not next_is_cjk:
                    # This is a structural close-quote
                    in_string = False
                    result.append(ch)
                elif prev_is_cjk and not found_structural:
                    # Embedded quote after CJK text -> close with corner bracket
                    result.append('」')  # Japanese/Chinese close bracket
                elif next_is_cjk:
                    # Embedded quote before CJK text -> open with corner bracket
                    result.append('「')  # Japanese/Chinese open bracket
                else:
                    # Ambiguous - keep as is but it might fail
                    # Check if next real char suggests continuation
                    nxt = ''
                    for j in range(i+1, min(i+5, len(text))):
                        if text[j] not in ' \t\r\n':
                            nxt = text[j]
                            break
                    if nxt in ',]}':
                        in_string = False
                        result.append(ch)
                    else:
                        result.append('「')
        else:
            result.append(ch)

        i += 1

    fixed = ''.join(result)

    try:
        obj = json.loads(fixed)
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        count = len(obj.get("extracts", []))
        print(f"  FIXED {name} ({count} extracts)")
    except json.JSONDecodeError as e:
        print(f"  FAILED {name}: {e}")
        # Show context around error
        lines = fixed.split('\n')
        err = str(e)
        if 'line ' in err:
            try:
                lineno = int(err.split('line ')[1].split(' ')[0])
                for li in range(max(0, lineno-2), min(len(lines), lineno+2)):
                    print(f"    L{li+1}: {lines[li][:200]}")
            except:
                pass
