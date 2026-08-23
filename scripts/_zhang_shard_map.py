#!/usr/bin/env python3
"""Temp helper: summarize zhang-juzheng shards -> source label + keyword hits.
Writes UTF-8 report to processed/local_shards/_shard_map.txt (read it back to avoid console mojibake).
"""
import json, re
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sd = root / "sources" / "zhang-juzheng" / "processed" / "local_shards"

# short labels for the long OCR filenames
def label(fn: str) -> str:
    if "全集" in fn: return "P1?全集(白话直解/商业包装)"
    if "奏疏集 上" in fn or "奏疏集 上" in fn: return "P1 奏疏集上"
    if "奏疏集 下" in fn: return "P1 奏疏集下"
    if "帝鉴图说" in fn: return "P1 帝鉴图说"
    if "shudu_vol14-28_full" in fn: return "P1 书牍full"
    if "shudu_vol14-28_index" in fn: return "书牍index(目录)"
    if "shudu_focus_qi_liaodong" in fn: return "书牍focus戚/辽东(目录)"
    if "四書経筵直解" in fn or "四書経筵直解" in fn: return "P1 四书经筵直解(残)"
    if "大传" in fn: return "P3 朱东润大传"
    if "韦庆远" in fn: return "P3 韦庆远政局(残)"
    if "万历十五年" in fn: return "P3 万历十五年"
    if "明史" in fn: return "P3 明史传"
    return fn[:24]

KW = ["陈六事","六事疏","考成","一条鞭","清丈","夺情","戚继光","李成梁","俺答","冯保",
      "太后","抄家","削籍","当国","柄政","虽万箭","得失毁誉","非常之事","利不百"]

man = json.loads((sd / "manifest.json").read_text(encoding="utf-8"))
lines = []
for s in man["shards"]:
    sid = s["shard_id"]
    p = sd / f"{sid}.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        lines.append(f"{sid}\tERR {e}"); continue
    # collect text from passages
    txt = ""
    passages = data.get("passages") or data.get("chunks") or []
    if isinstance(passages, list):
        for ps in passages:
            if isinstance(ps, dict):
                txt += ps.get("text","")
    srcs = s.get("source_files", [])
    labs = "|".join(sorted({label(x) for x in srcs}))
    hits = [k for k in KW if k in txt]
    repl = txt.count("�")
    lines.append(f"{sid}\t{s['token_estimate']:>6}tok\t{labs}\tKW:{','.join(hits) if hits else '-'}\tU+FFFD:{repl}")

out = sd / "_shard_map.txt"
out.write_text("\n".join(lines), encoding="utf-8")
print(f"wrote {out} ({len(lines)} shards)")
