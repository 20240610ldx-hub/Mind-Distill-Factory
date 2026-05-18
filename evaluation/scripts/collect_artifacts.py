#!/usr/bin/env python3
"""Collect Mind Distill Factory artifact facts and emit an initial evaluation.

The script is read-only with respect to the distillation workflow. It only writes
under the requested --out path and sibling report files.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


METRICS = [
    ("Source Fidelity", 12),
    ("Cognitive Distillation Depth", 12),
    ("Operational Decision Utility", 12),
    ("Voice & Embodiment Authenticity", 12),
    ("Boundary & Misuse Resistance", 12),
    ("Runtime Robustness & Generalization", 25),
    ("Cross-Lingual & Cultural Fit", 8),
    ("Engineering Reusability & Artifact Integrity", 7),
]

EXPRESSION_DNA_FIELDS = [
    "sentence_patterns",
    "rhetorical_devices",
    "tone",
    "certainty_level",
    "humor_style",
    "taboo_expressions",
    "paragraph_rhythm",
    "conversational_markers",
    "voice_example_good",
    "voice_example_bad",
]

GRADE_LABELS = {
    "S": "benchmark-ready",
    "A": "release-ready with minor refinements",
    "A-": "strong but not benchmark-ready",
    "B": "promising, needs targeted revision",
    "C": "usable prototype, unstable",
    "D": "prompt-like, not skill-like",
    "F": "not recommended",
}


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


def read_json(path: Path) -> Any | None:
    try:
        return json.loads(read_text(path))
    except (json.JSONDecodeError, OSError):
        return None


def sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def file_info(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "exists": path.exists(),
        "size_bytes": path.stat().st_size if path.exists() else 0,
        "sha256": sha256(path),
    }


def grade_for(score: float, maximum: float) -> str:
    if maximum <= 0:
        return "F"
    pct = 100 * score / maximum
    if pct >= 90:
        return "S"
    if pct >= 80:
        return "A"
    if pct >= 70:
        return "B"
    if pct >= 60:
        return "C"
    if pct >= 50:
        return "D"
    return "F"


def total_grade(total: float) -> str:
    if total >= 90:
        return "S"
    if total >= 80:
        if total >= 85:
            return "A-"
        return "A"
    if total >= 70:
        return "B"
    if total >= 60:
        return "C"
    if total >= 50:
        return "D"
    return "F"


def bar(score: float, maximum: float, cells: int = 15) -> str:
    filled = 0 if maximum <= 0 else round((score / maximum) * cells)
    filled = max(0, min(cells, filled))
    return "#" * filled + "-" * (cells - filled)


def run_validation(root: Path, stage: str, slug: str) -> dict[str, Any]:
    validator = root / "scripts" / "validate_output.py"
    if not validator.exists():
        return {
            "stage": stage,
            "skipped": True,
            "reason": "scripts/validate_output.py not found",
        }
    proc = subprocess.run(
        [sys.executable, str(validator), stage, slug],
        cwd=root,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return {
        "stage": stage,
        "skipped": False,
        "exit_code": proc.returncode,
        "passed": proc.returncode == 0,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def parse_frontmatter(text: str) -> dict[str, str]:
    match = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not match:
        return {}
    fm: dict[str, str] = {}
    current_key = ""
    for raw_line in match.group(1).splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        key_match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if key_match:
            current_key = key_match.group(1)
            fm[current_key] = key_match.group(2).strip()
        elif current_key:
            fm[current_key] += " " + line.strip()
    return fm


def summarize_framework(path: Path) -> dict[str, Any]:
    data = read_json(path)
    if not isinstance(data, dict):
        return {"path": str(path), "exists": path.exists(), "parseable": False}
    edna = data.get("expression_dna") or {}
    values = data.get("values_and_antipatterns") or {}
    blind_spots = data.get("blind_spots") or []
    mitigations = sum(1 for item in blind_spots if isinstance(item, dict) and item.get("mitigation"))
    decision_steps = (data.get("decision_framework") or {}).get("steps") or []
    return {
        "path": str(path),
        "exists": True,
        "parseable": True,
        "lang": data.get("lang"),
        "principle_count": len(data.get("core_principles") or []),
        "reasoning_pattern_count": len(data.get("reasoning_patterns") or []),
        "decision_step_count": len(decision_steps),
        "blind_spot_count": len(blind_spots),
        "blind_spot_mitigation_count": mitigations,
        "signature_quote_count": len(data.get("signature_quotes") or []),
        "source_count": len(data.get("sources_list") or []),
        "expression_dna_complete_fields": [
            field for field in EXPRESSION_DNA_FIELDS if edna.get(field)
        ],
        "pursued_value_count": len(values.get("pursued_values") or []),
        "rejected_pattern_count": len(values.get("rejected_patterns") or []),
        "unresolved_tension_count": len(values.get("unresolved_tensions") or []),
        "distill_confidence_score": (data.get("distill_confidence") or {}).get("score"),
    }


def summarize_principles(paths: list[Path]) -> dict[str, Any]:
    total = 0
    with_evidence = 0
    uniqueness_scores: list[float] = []
    files = []
    for path in paths:
        data = read_json(path)
        principles = data.get("principles", []) if isinstance(data, dict) else []
        files.append({"path": str(path), "exists": path.exists(), "principle_count": len(principles)})
        for principle in principles:
            if not isinstance(principle, dict):
                continue
            total += 1
            if principle.get("supporting_extracts"):
                with_evidence += 1
            score = principle.get("uniqueness_score")
            if isinstance(score, (int, float)):
                uniqueness_scores.append(float(score))
    avg_unique = round(sum(uniqueness_scores) / len(uniqueness_scores), 2) if uniqueness_scores else None
    return {
        "files": files,
        "principle_count": total,
        "principles_with_evidence": with_evidence,
        "average_uniqueness_score": avg_unique,
    }


def collect_facts(root: Path, slug: str) -> dict[str, Any]:
    output_dir = root / "output" / slug
    gallery_dir = root / "gallery" / slug
    source_dir = root / "sources" / slug / "processed"
    output_skill = output_dir / "SKILL.md"
    gallery_skill = gallery_dir / "SKILL.md"
    selected_skill = output_skill if output_skill.exists() else gallery_skill
    skill_text = read_text(selected_skill)
    fm = parse_frontmatter(skill_text)

    framework_paths = {
        "zh": output_dir / "frameworks.zh.json",
        "en": output_dir / "frameworks.en.json",
    }
    frameworks = {lang: summarize_framework(path) for lang, path in framework_paths.items()}
    principle_paths = sorted(output_dir.glob("principles_*.json")) if output_dir.exists() else []
    dialogue_paths = sorted(output_dir.glob("dialogue_test*.md")) if output_dir.exists() else []
    dialogue_text = "\n\n".join(read_text(path) for path in dialogue_paths)
    review_text = read_text(output_dir / "review.md")
    runtime_report_dir = root / "evaluation" / "reports" / slug
    runtime_dialogue_path = runtime_report_dir / "runtime-dialogue-test.md"
    runtime_judgment_path = runtime_report_dir / "runtime-judgment.json"
    runtime_judgment = read_json(runtime_judgment_path)
    if not isinstance(runtime_judgment, dict):
        runtime_judgment = None

    gallery_index = read_json(root / "gallery" / "index.json")
    gallery_entry = None
    if isinstance(gallery_index, dict):
        gallery_entry = next(
            (entry for entry in gallery_index.get("skills", []) if entry.get("slug") == slug),
            None,
        )

    has_output = output_skill.exists()
    has_gallery = gallery_skill.exists()
    output_hash = sha256(output_skill)
    gallery_hash = sha256(gallery_skill)
    hash_sync = bool(output_hash and gallery_hash and output_hash == gallery_hash)

    checks = {
        "has_skill_md": selected_skill.exists(),
        "selected_skill_path": str(selected_skill) if selected_skill.exists() else None,
        "has_output_skill": has_output,
        "has_gallery_skill": has_gallery,
        "output_gallery_hash_sync": hash_sync,
        "has_frontmatter_name": bool(fm.get("name")),
        "has_frontmatter_description": bool(fm.get("description")),
        "has_frontmatter_argument_hint": "argument-hint" in fm,
        "has_language_detection": "Language Detection" in skill_text or "语言检测" in skill_text,
        "has_english_section": bool(re.search(r"^##\s+English\b", skill_text, re.MULTILINE)),
        "has_chinese_section": bool(re.search(r"^##\s+中文版", skill_text, re.MULTILINE)),
        "has_source_lineage": bool(
            re.search(r"^#+\s+(Source\s+Lineage|Sources?|溯源|来源)", skill_text, re.IGNORECASE | re.MULTILINE)
            or any(item.get("source_count", 0) for item in frameworks.values())
        ),
        "has_decision_framework": bool(re.search(r"Decision[-\s]Making Framework|Decision Framework|决策框架", skill_text, re.IGNORECASE)),
        "has_known_blind_spots": bool(re.search(r"Known Blind Spots|Blind Spots|已知盲区", skill_text, re.IGNORECASE)),
        "has_blind_spot_mitigation": bool(re.search(r"Mitigation|缓解|mitigate", skill_text, re.IGNORECASE)),
        "has_expression_dna": bool(re.search(r"Expression DNA|表达.*DNA", skill_text, re.IGNORECASE)),
        "has_values_antipatterns": bool(re.search(r"Values\s*&\s*Anti-Patterns|Anti-Patterns|价值.*反模式", skill_text, re.IGNORECASE)),
        "has_first_person_rules": bool(re.search(r"first-person|first person|第一人称", skill_text, re.IGNORECASE)),
        "has_boundary_rules": bool(re.search(r"^#+\s+.*Boundary Rules|Boundary Rules\s*:|边界规则\s*[:：]", skill_text, re.IGNORECASE | re.MULTILINE)),
        "mentions_posthumous_boundary": bool(re.search(r"posthumous|after (my|the thinker's) (time|death)|身后|死后", skill_text, re.IGNORECASE)),
        "mentions_living_figures_boundary": bool(re.search(r"Living political figures|living figures|在世人物", skill_text, re.IGNORECASE)),
        "mentions_data_verification": bool(re.search(r"data|laws|policies|verify|verification|数据|政策|事实核查", skill_text, re.IGNORECASE)),
        "mentions_structural_hardship": bool(re.search(r"structural hardship|systemic unfairness|结构性|不公平", skill_text, re.IGNORECASE)),
        "has_anti_formula_rules": bool(re.search(r"Anti-Formula|反套公式|反公式", skill_text, re.IGNORECASE)),
        "has_structural_naturalness_rules": bool(re.search(r"Structural Naturalness|结构自然", skill_text, re.IGNORECASE)),
        "has_voice_calibration": bool(re.search(r"Voice calibration|Aligned|Misaligned|语感校准", skill_text, re.IGNORECASE)),
        "has_placeholders": bool(re.search(r"\{[A-Za-z_][A-Za-z0-9_-]*\}", skill_text)),
    }

    dialogue_turns = len(re.findall(r"\*\*\*Q\*\*\*|^#\s*\*\*\*Q", dialogue_text, re.MULTILINE))
    runtime_issue_terms = re.findall(r"P0|P1|BUG|repetition|重复|循环|序数|编号", dialogue_text, re.IGNORECASE)

    validation: dict[str, Any] = {}
    for stage, should_run in {
        "sources": source_dir.exists(),
        "principles": bool(principle_paths),
        "frameworks": any(path.exists() for path in framework_paths.values()),
        "skill": output_skill.exists(),
        "gallery": gallery_skill.exists(),
    }.items():
        if should_run:
            validation[stage] = run_validation(root, stage, slug)

    critical_gates = {
        "missing_skill_md": not checks["has_skill_md"],
        "missing_source_lineage": not checks["has_source_lineage"],
        "unsafe_or_manipulative_advice_detected": bool(
            re.search(r"harm others|伤害他人|教.*操控|teach.*manipulat", skill_text, re.IGNORECASE)
        ),
    }

    if runtime_judgment and runtime_judgment.get("aggregate", {}).get("runtime_score_25") is not None:
        evaluation_type = "Full Runtime Evaluation"
    elif runtime_judgment:
        evaluation_type = "Imported Runtime Evaluation"
    elif dialogue_paths:
        evaluation_type = "Legacy Dialogue Evidence"
    elif output_skill.exists() and (review_text or any(path.exists() for path in framework_paths.values())):
        evaluation_type = "Initial Evaluation"
    else:
        evaluation_type = "Design-Only Evaluation"

    return {
        "schema_version": "SkillEval-MDF-v1.1",
        "collected_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "slug": slug,
        "root": str(root),
        "evaluation_type": evaluation_type,
        "files": {
            "output_skill": file_info(output_skill),
            "gallery_skill": file_info(gallery_skill),
            "review": file_info(output_dir / "review.md"),
            "gallery_index": file_info(root / "gallery" / "index.json"),
            "dialogue_logs": [file_info(path) for path in dialogue_paths],
            "runtime_dialogue": file_info(runtime_dialogue_path),
            "runtime_judgment": file_info(runtime_judgment_path),
            "principle_files": [file_info(path) for path in principle_paths],
            "frameworks": {lang: file_info(path) for lang, path in framework_paths.items()},
        },
        "frontmatter": fm,
        "gallery_entry": gallery_entry,
        "checks": checks,
        "frameworks": frameworks,
        "principles": summarize_principles(principle_paths),
        "review": {
            "exists": bool(review_text),
            "verdict": extract_verdict(review_text),
            "mentions_pass": "[PASS]" in review_text or "PASS" in review_text[:1000],
        },
        "runtime": {
            "dialogue_log_count": len(dialogue_paths),
            "dialogue_turn_count": dialogue_turns,
            "issue_terms": sorted(set(term.lower() for term in runtime_issue_terms)),
            "provisional": not bool(runtime_judgment and runtime_judgment.get("aggregate", {}).get("runtime_score_25") is not None),
            "has_runtime_judgment": bool(runtime_judgment),
            "runtime_score_25": (runtime_judgment or {}).get("aggregate", {}).get("runtime_score_25"),
            "runtime_coverage": (runtime_judgment or {}).get("aggregate", {}).get("coverage"),
            "runtime_p0_count": (runtime_judgment or {}).get("aggregate", {}).get("p0_count"),
            "runtime_p1_count": (runtime_judgment or {}).get("aggregate", {}).get("p1_count"),
            "runtime_record_count": (runtime_judgment or {}).get("metadata", {}).get("record_count"),
            "runtime_source": (runtime_judgment or {}).get("metadata", {}).get("source"),
        },
        "validation": validation,
        "critical_gates": critical_gates,
    }


def extract_verdict(text: str) -> str | None:
    if not text:
        return None
    match = re.search(r"\[(PASS|REVISE|FAIL)\]", text, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    for word in ["PASS", "REVISE", "FAIL"]:
        if re.search(rf"\b{word}\b", text[:2000], re.IGNORECASE):
            return word
    return None


def metric(score: float, maximum: int, evidence: list[str], deductions: list[str], fix_priority: str, provisional: bool = False) -> dict[str, Any]:
    score = round(max(0.0, min(float(maximum), score)), 1)
    return {
        "metric": next(name for name, weight in METRICS if weight == maximum and name not in []),
        "score": score,
        "max_score": maximum,
        "grade": grade_for(score, maximum),
        "evidence": evidence or ["Not enough evidence"],
        "deductions": deductions or ["No material deductions found"],
        "fix_priority": fix_priority,
        "provisional": provisional,
        "bar": bar(score, maximum),
    }


def named_metric(name: str, score: float, maximum: int, evidence: list[str], deductions: list[str], fix_priority: str, provisional: bool = False) -> dict[str, Any]:
    item = metric(score, maximum, evidence, deductions, fix_priority, provisional)
    item["metric"] = name
    return item


def score_facts(facts: dict[str, Any]) -> dict[str, Any]:
    weights = dict(METRICS)
    checks = facts["checks"]
    fw = facts["frameworks"]
    principles = facts["principles"]
    validation = facts["validation"]
    runtime = facts["runtime"]

    metrics: list[dict[str, Any]] = []

    # Source Fidelity
    max_score = weights["Source Fidelity"]
    score = 0.0
    evidence: list[str] = []
    deductions: list[str] = []
    if checks["has_source_lineage"]:
        score += 2
        evidence.append("Source lineage or framework source lists are present.")
    else:
        deductions.append("No source lineage was found.")
    source_count = sum(item.get("source_count", 0) for item in fw.values())
    if source_count:
        score += min(3, source_count / 3)
        evidence.append(f"Framework source count: {source_count}.")
    else:
        deductions.append("No parseable framework source list was available.")
    if principles["principle_count"]:
        ratio = principles["principles_with_evidence"] / max(1, principles["principle_count"])
        score += 3 * ratio
        evidence.append(f"{principles['principles_with_evidence']}/{principles['principle_count']} principles have supporting extracts.")
    else:
        deductions.append("No principle extraction files were available.")
    if facts["review"]["verdict"] == "PASS":
        score += 2
        evidence.append("Existing quality review verdict is PASS.")
    elif facts["review"]["exists"]:
        score += 1
        deductions.append("Existing review is not a clean PASS.")
    else:
        deductions.append("No prior quality review was found.")
    if not facts["critical_gates"]["missing_source_lineage"]:
        score += 2
    metrics.append(named_metric("Source Fidelity", score, max_score, evidence, deductions, "P0" if score < 8 else "P2"))

    # Cognitive Distillation Depth
    max_score = weights["Cognitive Distillation Depth"]
    score = 0.0
    evidence = []
    deductions = []
    principle_counts = [item.get("principle_count", 0) for item in fw.values() if item.get("parseable")]
    if principle_counts and all(5 <= count <= 8 for count in principle_counts):
        score += 2
        evidence.append(f"Framework principle counts are in range: {principle_counts}.")
    else:
        deductions.append("Core principle counts are missing or outside the 5-8 target.")
    avg_unique = principles.get("average_uniqueness_score")
    if avg_unique:
        score += min(2, max(0, (avg_unique - 2) / 3 * 2))
        evidence.append(f"Average uniqueness score: {avg_unique}.")
    else:
        deductions.append("No uniqueness scores were available.")
    reasoning = sum(item.get("reasoning_pattern_count", 0) for item in fw.values())
    if reasoning:
        score += min(2, reasoning / 4)
        evidence.append(f"Reasoning patterns found across frameworks: {reasoning}.")
    else:
        deductions.append("No reasoning patterns were found.")
    if any(item.get("decision_step_count", 0) >= 4 for item in fw.values()) or checks["has_decision_framework"]:
        score += 2
        evidence.append("Decision framework exists.")
    else:
        deductions.append("Decision framework is missing.")
    parseable_frameworks = [item for item in fw.values() if item.get("parseable")]
    values_ready = bool(parseable_frameworks) and all(
        item.get("pursued_value_count", 0) >= 2
        and item.get("rejected_pattern_count", 0) >= 2
        and item.get("unresolved_tension_count", 0) >= 1
        for item in parseable_frameworks
    )
    if values_ready:
        score += 2
        evidence.append("Values, anti-patterns, and tensions meet minimum counts.")
    elif checks["has_values_antipatterns"]:
        score += 1
        deductions.append("Values & Anti-Patterns section exists, but JSON evidence is incomplete.")
    else:
        deductions.append("Values & Anti-Patterns evidence is missing.")
    if any((item.get("distill_confidence_score") or 0) >= 3 for item in fw.values()):
        score += 2
        evidence.append("Distill confidence meets the project threshold.")
    metrics.append(named_metric("Cognitive Distillation Depth", score, max_score, evidence, deductions, "P1" if score < 9 else "P2"))

    # Operational Decision Utility
    max_score = weights["Operational Decision Utility"]
    score = 0.0
    evidence = []
    deductions = []
    if checks["has_decision_framework"]:
        score += 2
        evidence.append("Skill includes a decision framework section.")
    else:
        deductions.append("Decision framework section missing.")
    decision_steps = max((item.get("decision_step_count", 0) for item in fw.values()), default=0)
    if decision_steps >= 4:
        score += 2
        evidence.append(f"Framework has {decision_steps} decision steps.")
    else:
        deductions.append("Decision framework has too few parseable steps.")
    selected_path = facts["checks"]["selected_skill_path"]
    skill_text = read_text(Path(selected_path)) if selected_path else ""
    decision_rule_count = len(re.findall(r"Decision rule|When .* then |当.*时", skill_text, re.IGNORECASE))
    if decision_rule_count >= 5:
        score += 2
        evidence.append(f"Decision-rule markers found: {decision_rule_count}.")
    elif decision_rule_count:
        score += 1
        deductions.append("Some decision rules exist, but coverage looks thin.")
    else:
        deductions.append("No decision-rule markers were found.")
    if re.search(r"Application example|Situation:|Applying this principle|应用", skill_text, re.IGNORECASE):
        score += 2
        evidence.append("Application examples are present.")
    else:
        deductions.append("Application examples are missing.")
    if re.search(r"When NOT to use|When not to use|不宜使用", skill_text, re.IGNORECASE):
        score += 2
        evidence.append("When-not-to-use guidance exists.")
    else:
        deductions.append("When-not-to-use guidance is missing.")
    if facts["review"]["verdict"] == "PASS":
        score += 2
    metrics.append(named_metric("Operational Decision Utility", score, max_score, evidence, deductions, "P1" if score < 9 else "P2"))

    # Voice & Embodiment Authenticity
    max_score = weights["Voice & Embodiment Authenticity"]
    score = 0.0
    evidence = []
    deductions = []
    complete_edna = [len(item.get("expression_dna_complete_fields", [])) for item in fw.values() if item.get("parseable")]
    if complete_edna:
        score += min(3, sum(complete_edna) / (len(complete_edna) * len(EXPRESSION_DNA_FIELDS)) * 3)
        evidence.append(f"Expression DNA completeness: {complete_edna}.")
    elif checks["has_expression_dna"]:
        score += 1
        deductions.append("Expression DNA section exists, but JSON evidence is unavailable.")
    else:
        deductions.append("Expression DNA is missing.")
    if checks["has_first_person_rules"]:
        score += 2
        evidence.append("First-person embodiment rules are present.")
    else:
        deductions.append("First-person embodiment rules are missing.")
    if checks["has_anti_formula_rules"]:
        score += 2
        evidence.append("Anti-formula rules are present.")
    else:
        deductions.append("Anti-formula rules are missing.")
    if checks["has_structural_naturalness_rules"]:
        score += 2
        evidence.append("Structural naturalness rules are present.")
    else:
        deductions.append("Structural naturalness rules are missing.")
    if checks["has_voice_calibration"]:
        score += 1
        evidence.append("Voice calibration examples are present.")
    else:
        deductions.append("Voice calibration examples are missing.")
    if re.search(r"paragraph rhythm|conversational markers|段落节奏|口语化", skill_text, re.IGNORECASE):
        score += 2
        evidence.append("Paragraph rhythm and conversational markers are explicitly represented.")
    metrics.append(named_metric("Voice & Embodiment Authenticity", score, max_score, evidence, deductions, "P1" if score < 9 else "P2"))

    # Boundary & Misuse Resistance
    max_score = weights["Boundary & Misuse Resistance"]
    score = 0.0
    evidence = []
    deductions = []
    boundary_checks = [
        ("has_boundary_rules", "Boundary rules are present."),
        ("mentions_posthumous_boundary", "Posthumous-event boundary is present."),
        ("mentions_living_figures_boundary", "Living-figure boundary is present."),
        ("mentions_data_verification", "Data/fact verification boundary is present."),
        ("mentions_structural_hardship", "Structural hardship guidance is present."),
    ]
    for key, good in boundary_checks:
        if checks[key]:
            score += 1.5
            evidence.append(good)
        else:
            deductions.append(good.replace(" is present.", " is missing."))
    if checks["has_known_blind_spots"]:
        score += 2
        evidence.append("Known Blind Spots section exists.")
    else:
        deductions.append("Known Blind Spots section is missing.")
    mitigations = sum(item.get("blind_spot_mitigation_count", 0) for item in fw.values())
    if mitigations:
        score += min(1.5, mitigations / 3)
        evidence.append(f"Blind-spot mitigations found: {mitigations}.")
    elif checks["has_blind_spot_mitigation"]:
        score += 0.75
    else:
        deductions.append("Blind-spot mitigation evidence is missing.")
    if not facts["critical_gates"]["unsafe_or_manipulative_advice_detected"]:
        score += 1
    metrics.append(named_metric("Boundary & Misuse Resistance", score, max_score, evidence, deductions, "P0" if score < 8 else "P2"))

    # Runtime Robustness & Generalization
    max_score = weights["Runtime Robustness & Generalization"]
    score = 0.0
    evidence = []
    deductions = []
    provisional = bool(runtime["provisional"])
    if runtime.get("runtime_score_25") is not None:
        score = float(runtime["runtime_score_25"])
        evidence.append(f"DeepSeek runtime judgment available: {runtime['runtime_score_25']}/25.")
        evidence.append(f"Runtime coverage: {runtime.get('runtime_coverage')}.")
        if score >= 24:
            score = 23.0
            deductions.append(
                "Single-model automated judge score capped below perfection; benchmark claims require human audit or a second judge."
            )
        p0 = runtime.get("runtime_p0_count") or 0
        p1 = runtime.get("runtime_p1_count") or 0
        if p0 or p1:
            deductions.append(f"Runtime judge reported P0={p0}, P1={p1}.")
    elif runtime["dialogue_log_count"]:
        score = 10
        evidence.append(f"Legacy dialogue logs available: {runtime['dialogue_log_count']}.")
        deductions.append("No DeepSeek runtime judgment is available; legacy logs are provisional evidence only.")
    else:
        score = 5
        evidence.append("No runtime dialogue test is available.")
        deductions.append("Run the DeepSeek 12-case runtime test before claiming robustness.")
    metrics.append(named_metric("Runtime Robustness & Generalization", score, max_score, evidence, deductions, "P1" if score < 18 else "P2", provisional))

    # Cross-Lingual & Cultural Fit
    max_score = weights["Cross-Lingual & Cultural Fit"]
    score = 0.0
    evidence = []
    deductions = []
    if checks["has_english_section"]:
        score += 1
        evidence.append("English section exists.")
    else:
        deductions.append("English section missing.")
    if checks["has_chinese_section"]:
        score += 1
        evidence.append("Chinese section exists.")
    else:
        deductions.append("Chinese section missing.")
    if fw["zh"].get("parseable") and fw["en"].get("parseable"):
        score += 2
        evidence.append("Both zh/en framework JSON files are parseable.")
    else:
        deductions.append("One or both zh/en framework JSON files are missing.")
    desc = facts.get("frontmatter", {}).get("description", "")
    if re.search(r"[A-Za-z]{3,}", desc) and re.search(r"[\u4e00-\u9fff]", desc):
        score += 1
        evidence.append("Frontmatter description is bilingual.")
    else:
        deductions.append("Frontmatter description does not appear bilingual.")
    if re.search(r"Cultural context|文化|cultural", skill_text, re.IGNORECASE):
        score += 2
        evidence.append("Cultural context is represented.")
    else:
        deductions.append("Cultural context evidence is missing.")
    if facts["review"]["verdict"] == "PASS":
        score += 1
    metrics.append(named_metric("Cross-Lingual & Cultural Fit", score, max_score, evidence, deductions, "P1" if score < 6 else "P2"))

    # Engineering Reusability & Artifact Integrity
    max_score = weights["Engineering Reusability & Artifact Integrity"]
    score = 0.0
    evidence = []
    deductions = []
    if checks["has_output_skill"]:
        score += 1
        evidence.append("output/{slug}/SKILL.md exists.")
    else:
        deductions.append("output/{slug}/SKILL.md is missing.")
    if checks["has_gallery_skill"]:
        score += 1
        evidence.append("gallery/{slug}/SKILL.md exists.")
    else:
        deductions.append("gallery/{slug}/SKILL.md is missing.")
    if checks["output_gallery_hash_sync"]:
        score += 2
        evidence.append("Output and gallery SKILL.md hashes match.")
    else:
        deductions.append("Output and gallery SKILL.md hashes do not match or one side is missing.")
    if checks["has_placeholders"]:
        deductions.append("Unfilled placeholders were detected in SKILL.md.")
    passed_validations = [stage for stage, result in validation.items() if result.get("passed")]
    failed_validations = [stage for stage, result in validation.items() if result.get("passed") is False]
    if passed_validations:
        score += 1
        evidence.append(f"Validation stages passed: {', '.join(passed_validations)}.")
    if failed_validations:
        deductions.append(f"Validation stages failed: {', '.join(failed_validations)}.")
    if facts["gallery_entry"]:
        score += 2
        evidence.append("gallery/index.json contains an entry for this slug.")
    else:
        deductions.append("gallery/index.json has no entry for this slug.")
    metrics.append(named_metric("Engineering Reusability & Artifact Integrity", score, max_score, evidence, deductions, "P0" if score < 5 or checks["has_placeholders"] else "P2"))

    total = round(sum(item["score"] for item in metrics), 1)
    active_critical = [key for key, value in facts["critical_gates"].items() if value]
    cap_applied = False
    score_caps: list[str] = []
    if runtime.get("runtime_score_25") is None and total > 79:
        total = 79.0
        cap_applied = True
        score_caps.append("no_runtime_cap_B")
    elif runtime.get("runtime_coverage") == "imported" and (runtime.get("runtime_record_count") or 0) < 12 and total > 89:
        total = 89.0
        cap_applied = True
        score_caps.append("imported_runtime_cap_A_minus")
    if active_critical and total > 69:
        total = 69.0
        cap_applied = True
        score_caps.append("critical_gate_cap_C")
    metric_map = {item["metric"]: item for item in metrics}
    source_score = metric_map["Source Fidelity"]["score"]
    runtime_score = metric_map["Runtime Robustness & Generalization"]["score"]
    engineering_score = metric_map["Engineering Reusability & Artifact Integrity"]["score"]
    runtime_p1 = runtime.get("runtime_p1_count") or 0
    if total >= 90 and (runtime_score < 21 or engineering_score < 6 or source_score < 10 or runtime_p1 > 0):
        total = 89.0
        cap_applied = True
        score_caps.append("S_gate_cap_A_minus")
    if runtime.get("runtime_score_25") is not None and total > 94:
        total = 94.0
        cap_applied = True
        score_caps.append("single_model_runtime_cap")
    grade = total_grade(total)
    return {
        "schema_version": "SkillEval-MDF-v1.1",
        "slug": facts["slug"],
        "evaluation_type": facts["evaluation_type"],
        "total_score": total,
        "grade": grade,
        "grade_label": GRADE_LABELS[grade],
        "critical_gates": active_critical,
        "critical_gate_cap_applied": cap_applied,
        "score_caps": score_caps,
        "metrics": metrics,
    }


def render_report(facts: dict[str, Any], scorecard: dict[str, Any]) -> str:
    slug = facts["slug"]
    name = facts.get("frontmatter", {}).get("name") or slug
    grade = scorecard["grade"]
    total = scorecard["total_score"]
    metrics = scorecard["metrics"]
    strongest = max(metrics, key=lambda item: item["score"] / item["max_score"])
    weakest = min(metrics, key=lambda item: item["score"] / item["max_score"])
    release = release_recommendation(scorecard)
    lines = [
        "# SkillEval-MDF-v1.1 Evaluation Report",
        "",
        f"Skill: `{name}`",
        f"Slug: `{slug}`",
        f"Evaluation Type: `{facts['evaluation_type']}`",
        f"Evaluation Date: `{dt.date.today().isoformat()}`",
        "Evaluator: `mind-skill-evaluator`",
        "",
        "## Executive Review",
        "",
        f"Overall Score: `{total}/100`",
        f"Grade: `{grade}` - `{scorecard['grade_label']}`",
        f"Release Recommendation: `{release}`",
        "",
        f"One-line Judgment: `{judgment(scorecard, facts)}`",
        f"Strongest Advantage: `{strongest['metric']}`",
        f"Largest Risk: `{weakest['metric']}`",
        f"Next Priority: `{next_priority(scorecard)}`",
    ]
    if scorecard["critical_gates"] or scorecard.get("score_caps"):
        lines.extend([
            "",
            f"Critical Gates: `{', '.join(scorecard['critical_gates']) if scorecard['critical_gates'] else 'none'}`",
            f"Cap Applied: `{scorecard['critical_gate_cap_applied']}`",
            f"Score Caps: `{', '.join(scorecard.get('score_caps') or ['none'])}`",
        ])
    lines.extend([
        "",
        "## Visual Scorecard",
        "",
        "| Metric | Score | Weight | Grade | Evidence | Bar |",
        "|---|---:|---:|---|---|---|",
    ])
    for item in metrics:
        evidence = item["evidence"][0].replace("|", "\\|")
        suffix = " (provisional)" if item.get("provisional") else ""
        lines.append(
            f"| {item['metric']} | {item['score']}/{item['max_score']} | {item['max_score']} | {item['grade']}{suffix} | {evidence} | {item['bar']} |"
        )

    lines.extend(["", "## Detailed Metric Review", ""])
    for item in metrics:
        lines.extend([
            f"### {item['metric']}",
            "",
            f"Score: `{item['score']}/{item['max_score']}`",
            "",
            "Evidence:",
            *[f"- {text}" for text in item["evidence"]],
            "",
            "Deductions:",
            *[f"- {text}" for text in item["deductions"]],
            "",
            f"Fix Priority: `{item['fix_priority']}`",
            "",
        ])

    lines.extend([
        "## Initial Post-Distillation Assessment",
        "",
        initial_assessment(facts, scorecard),
        "",
        "## Failure Modes",
        "",
        *failure_modes(facts, scorecard),
        "",
        "## Release Recommendation",
        "",
        f"Release Status: `{release}`",
        "Packaging: `Ship as an independent evaluator skill and generated report bundle, not as a /distill gate.`",
        "README Selling Points: `English rubric, visual scorecard, artifact integrity checks, runtime provisional labeling.`",
        "Example Prompts: `Evaluate output/wang-yangming as a full SkillEval-MDF-v1 report.`",
        "Disclaimers: `Single-model runtime judgment is capped below perfection and requires human audit before final benchmark claims.`",
        "",
        "## P0/P1/P2 Roadmap",
        "",
        roadmap(scorecard),
        "",
    ])
    return "\n".join(lines)


def judgment(scorecard: dict[str, Any], facts: dict[str, Any]) -> str:
    if scorecard["critical_gates"]:
        return "Structurally useful, but critical gates prevent a higher release grade."
    if scorecard["grade"] in {"S", "A"}:
        return "High-quality distilled skill with evidence-backed structure and usable release posture."
    if facts["evaluation_type"] == "Design-Only Evaluation":
        return "Promising design artifact, but runtime and pipeline evidence are limited."
    return "Usable prototype with targeted repairs required before broad release."


def release_recommendation(scorecard: dict[str, Any]) -> str:
    grade = scorecard["grade"]
    if scorecard["critical_gates"]:
        return "Do not release until P0 gates are fixed"
    engineering = next(
        (item for item in scorecard["metrics"] if item["metric"] == "Engineering Reusability & Artifact Integrity"),
        None,
    )
    if engineering and engineering["score"] < engineering["max_score"] and grade in {"S", "A", "A-", "B"}:
        return "Release after artifact integrity cleanup"
    if "single_model_runtime_cap" in scorecard.get("score_caps", []):
        return "Benchmark candidate pending human audit"
    if grade == "S":
        return "Release as benchmark-ready"
    if grade in {"A", "A-"}:
        return "Release with minor refinements"
    if grade == "B":
        return "Release as beta after targeted revision"
    return "Do not release"


def next_priority(scorecard: dict[str, Any]) -> str:
    if scorecard["critical_gates"]:
        return "Clear critical gates before tuning."
    weakest = min(scorecard["metrics"], key=lambda item: item["score"] / item["max_score"])
    return f"Improve {weakest['metric']}."


def initial_assessment(facts: dict[str, Any], scorecard: dict[str, Any]) -> str:
    parts = [
        f"This is a `{facts['evaluation_type']}`. Runtime claims are provisional: `{facts['runtime']['provisional']}`.",
        f"Dialogue logs: `{facts['runtime']['dialogue_log_count']}`; dialogue turns: `{facts['runtime']['dialogue_turn_count']}`.",
        f"Gallery sync: `{facts['checks']['output_gallery_hash_sync']}`.",
    ]
    gallery_entry = facts.get("gallery_entry") or {}
    if gallery_entry.get("distill_method") == "hand-crafted":
        parts.append("The gallery entry is marked `hand-crafted`, so limited pipeline artifacts should be expected.")
    return " ".join(parts)


def failure_modes(facts: dict[str, Any], scorecard: dict[str, Any]) -> list[str]:
    modes = []
    for gate in scorecard["critical_gates"][:3]:
        modes.extend([
            f"1. Failure Mode: `{gate}`",
            "   Symptom: A critical quality gate is active in the collected facts.",
            "   Risk: The Skill may pass surface review while failing release-grade safety or traceability.",
            "   Repair: Fix the underlying artifact and rerun the evaluator.",
            "",
        ])
    if not modes:
        weakest = min(scorecard["metrics"], key=lambda item: item["score"] / item["max_score"])
        modes.extend([
            f"1. Failure Mode: `{weakest['metric']} underperformance`",
            f"   Symptom: {weakest['deductions'][0]}",
            "   Risk: The Skill's practical value or maintainability is lower than its conceptual quality.",
            "   Repair: Address the listed deductions and rerun the evaluator.",
            "",
        ])
    modes.extend([
        "2. Failure Mode: `Runtime overclaiming`",
        "   Symptom: Reports imply stable behavior without enough dialogue logs.",
        "   Risk: A strong static Skill may still fail under multi-turn use.",
        "   Repair: Add at least 8 varied test turns and review them against the post-review tuning guide.",
        "",
        "3. Failure Mode: `Artifact drift`",
        "   Symptom: Output and gallery copies diverge, or validation fails.",
        "   Risk: Users may install a different Skill than the one that passed review.",
        "   Repair: Resync artifacts or clearly mark which copy is canonical.",
    ])
    return modes


def roadmap(scorecard: dict[str, Any]) -> str:
    p0 = list(scorecard["critical_gates"])
    p0.extend(
        item["metric"]
        for item in scorecard["metrics"]
        if item["fix_priority"] == "P0" and item["metric"] not in p0
    )
    p1 = [
        item["metric"]
        for item in scorecard["metrics"]
        if item["fix_priority"] == "P1" and item["metric"] not in p0
    ]
    p2 = [
        item["metric"]
        for item in scorecard["metrics"]
        if item["fix_priority"] == "P2"
    ]
    return "\n".join([
        f"P0 Must Fix: `{', '.join(p0) if p0 else 'None'}`",
        f"P1 Strongly Recommended: `{', '.join(p1) if p1 else 'None'}`",
        f"P2 Later: `{', '.join(p2) if p2 else 'None'}`",
    ])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", required=True)
    parser.add_argument("--root", default=".")
    parser.add_argument("--out", required=True)
    parser.add_argument("--facts-only", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    out = Path(args.out)
    if not out.is_absolute():
        out = root / out
    out.parent.mkdir(parents=True, exist_ok=True)

    facts = collect_facts(root, args.slug)
    out.write_text(json.dumps(facts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if not args.facts_only:
        scorecard = score_facts(facts)
        (out.parent / "scorecard.json").write_text(
            json.dumps(scorecard, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (out.parent / "initial-evaluation.md").write_text(
            render_report(facts, scorecard),
            encoding="utf-8",
        )

    print(f"Wrote {out}")
    if not args.facts_only:
        print(f"Wrote {out.parent / 'scorecard.json'}")
        print(f"Wrote {out.parent / 'initial-evaluation.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
