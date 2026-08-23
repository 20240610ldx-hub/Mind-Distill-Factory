#!/usr/bin/env python3
"""Fix JSON files with unescaped double quotes inside string values.
Generic fix: replace all "Chinese text" patterns with corner brackets."""
import json, sys, re
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
shard_dir = Path("sources/lu-xun/processed/local_shards")

# Generic pattern: replace "Chinese chars" with 「Chinese chars」
# Only matches quotes containing CJK characters
cjk_quote_re = re.compile(r'"([一-鿿＀-￯　-〿，。、；：！？（）]{1,30})"')

for f in sorted(shard_dir.glob("*_extracts.json")):
    text = f.read_text(encoding="utf-8-sig")
    try:
        json.loads(text)
        continue
    except json.JSONDecodeError:
        pass

    print(f"  FIX {f.name}...", end=" ")

    # Replace CJK text between quotes with corner brackets
    result = cjk_quote_re.sub(r"「\1」", text)

    try:
        obj = json.loads(result)
        f.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        count = len(obj.get("extracts", []))
        print(f"FIXED ({count} extracts)")
    except json.JSONDecodeError as e:
        print(f"FAILED: {e}")
        # Last resort: array-level recovery
        try:
            m = re.search(r'"person_slug"\s*:\s*"([^"]+)"', result)
            slug = m.group(1) if m else "lu-xun"
            m = re.search(r'"shard_id"\s*:\s*"([^"]+)"', result)
            sid = m.group(1) if m else "unknown"
            start = result.find('"extracts"')
            if start >= 0:
                arr_start = result.find("[", start)
                if arr_start >= 0:
                    depth = 0
                    arr_end = -1
                    for i in range(arr_start, len(result)):
                        if result[i] == "[": depth += 1
                        elif result[i] == "]": depth -= 1
                        if depth == 0: arr_end = i + 1; break
                    if arr_end > 0:
                        arr_text = result[arr_start:arr_end]
                        # One more try with sanitize
                        arr_text = cjk_quote_re.sub(r"「\1」", arr_text)
                        arr = json.loads(arr_text)
                        obj = {"person_slug": slug, "shard_id": sid, "extracts": arr, "worker_notes": ""}
                        f.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
                        print(f"  RECOVERED ({len(arr)} extracts)")
        except Exception as e2:
            print(f"  FATAL: {e2}")
