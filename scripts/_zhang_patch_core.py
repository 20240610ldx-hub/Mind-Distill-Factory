#!/usr/bin/env python3
"""Patch framework_core.json: backfill shared_blind_spot_themes + reasoning_pattern_candidates
+ quote_candidates from the authored principles files; demote bs-* clusters out of principle_clusters.
Deterministic; sources are the orchestrator-authored principles_*.json.
"""
import json
from pathlib import Path

out = Path(__file__).resolve().parents[1] / "output" / "zhang-juzheng"
core = json.loads((out / "framework_core.json").read_text(encoding="utf-8"))
usr = json.loads((out / "principles_user_sources.json").read_text(encoding="utf-8"))
sec = json.loads((out / "principles_secondary_sources.json").read_text(encoding="utf-8"))

# 1. demote blind-spot clusters: keep clusters that are NOT purely bs-*
def is_bs(cl):
    ids = cl.get("candidate_principle_ids", [])
    return bool(ids) and all(str(i).startswith("zjz-bs-") for i in ids)
core["principle_clusters"] = [c for c in core["principle_clusters"] if not is_bs(c)]

# 2. shared_blind_spot_themes from secondary seeds
themes = []
for p in sec["principles"]:
    themes.append({
        "theme_id": p["id"],
        "name_zh": p["name_zh"],
        "name_en": p["name_en"],
        "risk_zh": p["explanation_zh"],
        "risk_en": p["explanation_en"],
        "mitigation_zh": p["decision_rule_zh"],
        "mitigation_en": p["decision_rule_en"],
        "shadows_principle": p.get("shadows_principle", ""),
        "supporting_evidence": p.get("supporting_extracts", []),
    })
core["shared_blind_spot_themes"] = themes

# 3. reasoning_pattern_candidates from user principles
core["reasoning_pattern_candidates"] = usr.get("reasoning_patterns", [])

# 4. quote_candidates from notable_quotes (if empty)
if not core.get("quote_candidates"):
    core["quote_candidates"] = usr.get("notable_quotes", [])

core["core_notes"] = (core.get("core_notes") or "") + \
    " | ORCHESTRATOR-REFINED: demoted 6 bs-* clusters to shared_blind_spot_themes; " \
    "backfilled reasoning_pattern_candidates(5) + quote_candidates(10) from authored principles."

(out / "framework_core.json").write_text(json.dumps(core, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"clusters(positive)={len(core['principle_clusters'])} blind_themes={len(core['shared_blind_spot_themes'])} "
      f"reasoning={len(core['reasoning_pattern_candidates'])} quotes={len(core['quote_candidates'])} ledger={len(core['source_ledger'])}")
print("cluster names:", [c.get("canonical_name_zh","?") for c in core["principle_clusters"]])
