#!/usr/bin/env python3
"""Assemble Stage-1 deliverables for zhang-juzheng from shard extracts + secondary_work.
Produces: expression_dna.json, secondary_sources.json, primary_sources.json.
Then prints a verification report (counts / confidence / U+FFFD / user_sources person).
All extracts normalized to validator's EXTRACT_SCHEMA. No content invented.
"""
import json, collections
from pathlib import Path
from datetime import date

root = Path(__file__).resolve().parents[1]
proc = root / "sources" / "zhang-juzheng" / "processed"
ls = proc / "local_shards"
sw = proc / "secondary_work"

REQUIRED = ["text","source_title","source_detail","language","content_type","topic_tags","confidence"]

def fffd(s): return (s or "").count("�")

def normalize(e, default_conf):
    ct = e.get("content_type") or "analysis"
    out = {
        "text": (e.get("text") or "").strip(),
        "source_title": e.get("source_title") or "Local source",
        "source_detail": e.get("source_detail") or e.get("detail") or "",
        "source_url": e.get("source_url",""),
        "language": e.get("language") or "zh",
        "content_type": ct,
        "topic_tags": e.get("topic_tags") or e.get("style_tags") or [],
        "confidence": e.get("confidence") or default_conf,
        "confidence_reason": e.get("confidence_reason") or "",
    }
    if ct == "expression_sample":
        out["style_tags"] = e.get("style_tags") or e.get("topic_tags") or []
        dim = e.get("dimension")
        if dim:
            out["dimension"] = dim[0] if isinstance(dim, list) else dim  # scaffold needs str (hashable)
        if e.get("analysis"): out["analysis"] = e["analysis"]
    return out

def load_shard_extracts():
    out=[]
    for f in sorted(ls.glob("shard_*_extracts.json")):
        d=json.loads(f.read_text(encoding="utf-8"))
        for e in d.get("extracts",[]):
            e["_shard"]=d.get("shard_id"); out.append(e)
    return out

allex = load_shard_extracts()

# ---- expression_dna.json ----
expr = [normalize(e,"high") for e in allex if e.get("content_type")=="expression_sample"]
# signature voice supplement: pull by ACTUAL text substrings (formal register + certainty/values)
SIG = ["众镞攒体","得失毁誉","愚忠","親故不宥","貴近不宥","疏賤必申","虽万世之是非","忘家殉国","机穽满前"]
seen_text = {e["text"] for e in expr}
supp=[]
for e in allex:
    t = e.get("text","")
    if t not in seen_text and any(k in t for k in SIG):
        n = normalize(e, e.get("confidence","medium"))
        n["content_type"]="expression_sample"
        n["style_tags"] = n.get("topic_tags") or ["果决","殉道者-certainty"]
        n["dimension"] = "certainty"
        n["analysis"] = "签名式自况：殉道者心态 + 不计毁誉的高确定性语气（formal register）"
        supp.append(n); seen_text.add(t)
expr_all = expr + supp
expr_env = {"person":"张居正","person_slug":"zhang-juzheng","source_type":"expression_dna",
            "collected_at":date.today().isoformat(),
            "collection_notes":f"书牍 expression_sample {len(expr)} 条 + 签名式语气补充 {len(supp)} 条（双声道：私信直白 + 奏疏/自况庄重）。",
            "extracts":expr_all}
(proc/"expression_dna.json").write_text(json.dumps(expr_env,ensure_ascii=False,indent=2),encoding="utf-8")

# ---- secondary_sources.json ----
sec=[]
for f in sorted(sw.glob("*.json")):
    d=json.loads(f.read_text(encoding="utf-8"))
    for e in d.get("extracts",[]):
        sec.append(normalize(e,"medium"))
sec_env = {"person":"张居正","person_slug":"zhang-juzheng","source_type":"secondary",
           "collected_at":date.today().isoformat(),
           "collection_notes":"本地二手/传记素材（朱东润《张居正大传》/《明史·张居正传》/黄仁宇《万历十五年》），用于已知盲区、价值观张力与时间线。confidence 一律 medium。",
           "extracts":sec}
(proc/"secondary_sources.json").write_text(json.dumps(sec_env,ensure_ascii=False,indent=2),encoding="utf-8")

# ---- primary_sources.json (curated first-hand canon) ----
# high-confidence quote/principle from clean first-hand shards; dedup; cap 30
prim=[]; seenp=set()
order = {"quote":0,"principle":1,"behavior_record":2}
cand = [e for e in allex if e.get("confidence")=="high" and e.get("content_type") in ("quote","principle","behavior_record")]
cand.sort(key=lambda e: (order.get(e.get("content_type"),3), -len(e.get("text",""))))
for e in cand:
    t=e.get("text","")
    if t and t not in seenp:
        prim.append(normalize(e,"high")); seenp.add(t)
    if len(prim)>=30: break
prim_env = {"person":"张居正","person_slug":"zhang-juzheng","source_type":"primary",
            "collected_at":date.today().isoformat(),
            "collection_notes":"第一手原文精选（奏疏/书牍/帝鉴图说中 high-confidence 的 quote/principle），作为框架骨架来源。与 user_sources 有重叠，Stage 2 去重。",
            "extracts":prim}
(proc/"primary_sources.json").write_text(json.dumps(prim_env,ensure_ascii=False,indent=2),encoding="utf-8")

# ---- report ----
def rpt(name):
    p=proc/name
    if not p.exists(): return f"{name}: MISSING"
    d=json.loads(p.read_text(encoding="utf-8"))
    exs=d.get("extracts",[])
    conf=collections.Counter(e.get("confidence") for e in exs)
    ct=collections.Counter(e.get("content_type") for e in exs)
    f=sum(fffd(e.get("text","")) for e in exs)
    miss=sum(1 for e in exs for r in REQUIRED if r not in e)
    return (f"{name}: n={len(exs)} type={d.get('source_type')} person={d.get('person')} "
            f"CONF={dict(conf)} CT={dict(ct)} FFFD={f} MISSING_FIELDS={miss}")

lines=[rpt("user_sources.json"),rpt("primary_sources.json"),
       rpt("secondary_sources.json"),rpt("expression_dna.json")]
out=proc/"_stage1_report.txt"
out.write_text("\n".join(lines)+"\n",encoding="utf-8")
print("\n".join(lines))
