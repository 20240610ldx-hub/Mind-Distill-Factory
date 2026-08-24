#!/usr/bin/env python3
"""
Mind Distill Factory — JSON Schema Validation Layer

Validates intermediate outputs at each pipeline stage before proceeding.
Run: python scripts/validate_output.py <stage> <person-slug>

Stages:
  sources   — validate sources/{slug}/processed/*.json
  principles — validate output/{slug}/principles_*.json
  frameworks — validate output/{slug}/frameworks.{zh,en}.json
  skill     — validate output/{slug}/SKILL.md frontmatter and bilingual structure
  package   — validate the v6 package: output/{slug}/SKILL.md + references/ (gates P1-P6)
  gallery   — validate gallery/{slug}/SKILL.md and ensure it matches output/{slug}/SKILL.md
"""

import json
import sys
import re
import os
import hashlib
from pathlib import Path

# Fix Windows console encoding for Unicode output
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

# ── Schema definitions ──────────────────────────────────────────────

EXTRACT_SCHEMA = {
    "required_fields": ["text", "source_title", "source_detail", "language",
                        "content_type", "topic_tags", "confidence"],
    "confidence_values": ["high", "medium", "low"],
    "content_type_values": ["quote", "principle", "behavior_record", "analysis", "expression_sample"],
}

SOURCE_FILE_SCHEMA = {
    "required_fields": ["person", "person_slug", "source_type", "collected_at", "extracts"],
    "source_type_values": ["primary", "secondary", "user_provided", "expression_dna"],
}

PRINCIPLE_SCHEMA = {
    "required_fields": ["id", "name_zh", "name_en", "uniqueness_score",
                        "explanation_zh", "explanation_en",
                        "decision_rule_zh", "decision_rule_en",
                        "supporting_extracts", "topic_tags"],
    "uniqueness_score_range": (1, 5),
}

FRAMEWORK_SCHEMA = {
    "required_fields": ["lang", "person_slug", "person_name", "person_name_original",
                        "era", "primary_category", "secondary_categories",
                        "core_tension", "one_line_philosophy", "signature_quote",
                        "synthesized_at", "core_principles", "decision_framework",
                        "reasoning_patterns", "blind_spots", "cultural_context",
                        "when_not_to_use", "signature_quotes", "sources_list",
                        "distill_confidence", "expression_dna",
                        "values_and_antipatterns"],
    "lang_values": ["zh", "en"],
    "min_principles": 5,
    "max_principles": 8,
    "min_blind_spots": 2,
    "min_quotes": 5,
    "expression_dna_fields": ["sentence_patterns", "rhetorical_devices", "tone",
                              "certainty_level", "humor_style", "taboo_expressions",
                              "paragraph_rhythm", "conversational_markers",
                              "voice_example_good", "voice_example_bad"],
    "min_pursued_values": 2,
    "min_rejected_patterns": 2,
    "min_tensions": 1,
}

# v6 frameworks（frameworks.{lang}.json 顶层带 "format_version": 6）用加厚后的原则数区间
# 替换上面 FRAMEWORK_SCHEMA 的 5-8——不读 config/defaults.json，仍是模块级常量，
# 与本文件其余 schema 的风格一致。没有 format_version 字段的 legacy 框架不受影响，
# 继续用 FRAMEWORK_SCHEMA 的 min_principles/max_principles。
FRAMEWORK_SCHEMA_V6_PRINCIPLES = {
    "min_principles": 8,
    "max_principles": 11,
}

FRAMEWORK_CORE_SCHEMA = {
    "required_fields": ["person_slug", "core_version", "synthesized_at",
                        "principle_clusters", "shared_blind_spot_themes",
                        "reasoning_pattern_candidates", "source_ledger",
                        "confidence_factors", "expression_dna_raw_summary",
                        "alignment_contract"],
    "min_clusters": 1,
}

PACKAGE_SCHEMA = {
    "skill_max_lines": 500,
    "reference_dir": "references",
    "required_refs": ["cases.md", "evidence.md", "voice.md"],
    "min_cases_per_cluster": 2,
    "min_counter_cases": 1,
    "core_sections": ["身份卡", "响应策略", "核心原则", "决策框架",
                      "已知盲区", "表达风格 DNA", "价值取向与反模式", "溯源"],
    "format_version": 6,
}

SKILL_FRONTMATTER_PATTERN = re.compile(
    r"^---\s*\n(.*?)\n---", re.DOTALL
)

# ── Validation functions ────────────────────────────────────────────

def read_json_file(filepath: Path):
    """Read JSON with UTF-8 BOM tolerance for Windows-generated files."""
    return json.loads(filepath.read_text(encoding="utf-8-sig"))


def status_failed_unit_ids(status: dict) -> list[str]:
    result = []
    for item in status.get("failed_units", []):
        if isinstance(item, dict):
            if item.get("unit_id"):
                result.append(item["unit_id"])
        elif item:
            result.append(item)
    return result

def validate_json_file(filepath: Path, required_fields: list[str]) -> list[str]:
    """Validate a JSON file exists, parses, and has required fields."""
    errors = []
    if not filepath.exists():
        return [f"MISSING: {filepath}"]
    try:
        data = read_json_file(filepath)
    except json.JSONDecodeError as e:
        return [f"JSON_PARSE_ERROR: {filepath}: {e}"]
    except UnicodeDecodeError as e:
        return [f"ENCODING_ERROR: {filepath}: {e}"]

    for field in required_fields:
        if field not in data:
            errors.append(f"MISSING_FIELD: {filepath}: '{field}'")
    return errors


def validate_sources(slug: str) -> list[str]:
    """Validate all files in sources/{slug}/processed/."""
    errors = []
    processed_dir = Path(f"sources/{slug}/processed")
    raw_dir = Path(f"sources/{slug}/raw")
    if not processed_dir.exists():
        return [f"MISSING_DIR: {processed_dir}"]

    json_files = list(processed_dir.glob("*.json"))
    if not json_files:
        return [f"EMPTY_DIR: {processed_dir} (no .json files)"]

    # ── Completeness check: required source files ──
    required_sources = {
        "expression_dna.json": "CRITICAL",  # Never skip — drives anti-formula quality
        "primary_sources.json": "REQUIRED",
        "secondary_sources.json": "REQUIRED",
    }
    for filename, severity in required_sources.items():
        fpath = processed_dir / filename
        if not fpath.exists():
            if severity == "CRITICAL":
                errors.append(f"MISSING_CRITICAL: {fpath} — expression DNA collection was skipped; SKILL quality will degrade")
            else:
                errors.append(f"WARNING: {fpath} not found (search may have failed)")
        else:
            # Check non-empty
            try:
                data = read_json_file(fpath)
                extracts = data.get("extracts", [])
                if not extracts:
                    label = "EMPTY_CRITICAL" if severity == "CRITICAL" else "WARNING"
                    errors.append(f"{label}: {fpath} has 0 extracts")
                elif filename == "expression_dna.json":
                    # Expression DNA should have content_type = expression_sample
                    expr_count = sum(1 for e in extracts if e.get("content_type") == "expression_sample")
                    if expr_count == 0:
                        errors.append(f"WARNING: {fpath}: {len(extracts)} extracts but none with content_type='expression_sample'")
            except Exception:
                pass

    # ── Stage 1A local sharding checks ──
    raw_files = list(raw_dir.glob("*")) if raw_dir.exists() else []
    raw_files = [p for p in raw_files if p.is_file()]
    if raw_files:
        manifest_path = processed_dir / "local_shards" / "manifest.json"
        if not manifest_path.exists():
            errors.append(
                f"WARNING: {manifest_path} not found; Stage 1A should use local-source-indexer/worker/reducer for raw materials"
            )
        else:
            try:
                manifest = read_json_file(manifest_path)
                hard_limit = manifest.get("hard_limit_tokens", 60000)
                for shard in manifest.get("shards", []):
                    token_estimate = shard.get("token_estimate", 0)
                    if token_estimate > hard_limit:
                        errors.append(
                            f"OVERSIZE_SHARD: {manifest_path}: {shard.get('shard_id')} token_estimate={token_estimate} > {hard_limit}"
                        )
                over_limit = manifest.get("over_limit_shards", [])
                if over_limit:
                    errors.append(f"OVERSIZE_SHARDS: {manifest_path}: {over_limit}")
                # Resume status consistency is advisory unless there are unresolved failures.
                status_path = processed_dir / "local_shards" / "task_status.json"
                if not status_path.exists():
                    errors.append(f"WARNING: {status_path} not found; interrupted Stage 1A cannot resume precisely")
                else:
                    status = read_json_file(status_path)
                    shard_ids = {s.get("shard_id") for s in manifest.get("shards", []) if s.get("shard_id")}
                    status_ids = {u.get("unit_id") for u in status.get("input_units", []) if u.get("unit_id")}
                    if shard_ids != status_ids:
                        errors.append(f"STAGE1A_STATUS_MISMATCH: {status_path}: input_units do not match manifest shards")
                    failed_ids = status_failed_unit_ids(status)
                    blocked_ids = status.get("blocked_units", [])
                    pending_ids = status.get("pending_units", [])
                    if pending_ids:
                        errors.append(f"WARNING: {status_path}: pending Stage 1A units remain: {pending_ids[:8]}{'...' if len(pending_ids) > 8 else ''}")
                    if failed_ids or blocked_ids:
                        errors.append(f"STAGE1A_UNRESOLVED_UNITS: {status_path}: failed={failed_ids} blocked={blocked_ids}")
                    for shard_id in status.get("completed_units", []):
                        expected = processed_dir / "local_shards" / f"{shard_id}_extracts.json"
                        if not expected.exists():
                            errors.append(f"STAGE1A_STATUS_MISMATCH: {status_path}: completed unit missing output {expected}")
            except Exception as e:
                errors.append(f"MANIFEST_PARSE_ERROR: {manifest_path}: {e}")

    # ── Per-file format validation ──
    for jf in json_files:
        errors.extend(validate_json_file(jf, SOURCE_FILE_SCHEMA["required_fields"]))
        try:
            data = read_json_file(jf)
            # Validate source_type
            if data.get("source_type") not in SOURCE_FILE_SCHEMA["source_type_values"]:
                errors.append(f"INVALID_VALUE: {jf}: source_type='{data.get('source_type')}'")
            # Validate each extract
            for i, ext in enumerate(data.get("extracts", [])):
                for field in EXTRACT_SCHEMA["required_fields"]:
                    # topic_tags is optional for expression_sample — style_tags accepted as alternative
                    if field == "topic_tags" and ext.get("content_type") == "expression_sample":
                        if "topic_tags" not in ext and "style_tags" not in ext:
                            errors.append(f"MISSING_FIELD: {jf}: extracts[{i}] needs 'topic_tags' or 'style_tags'")
                        continue
                    if field not in ext:
                        errors.append(f"MISSING_FIELD: {jf}: extracts[{i}].'{field}'")
                if ext.get("confidence") not in EXTRACT_SCHEMA["confidence_values"]:
                    errors.append(f"INVALID_VALUE: {jf}: extracts[{i}].confidence='{ext.get('confidence')}'")

            # Check high-confidence ratio
            extracts = data.get("extracts", [])
            if extracts:
                high_count = sum(1 for e in extracts if e.get("confidence") == "high")
                ratio = high_count / len(extracts)
                if ratio < 0.2:
                    errors.append(f"WARNING: {jf}: high-confidence ratio={ratio:.0%} (<20%), consider requesting user sources")
        except Exception:
            pass  # Parse errors already caught above
    return errors


def validate_principles(slug: str) -> list[str]:
    """Validate all principles_*.json files."""
    errors = []
    output_dir = Path(f"output/{slug}")
    if not output_dir.exists():
        return [f"MISSING_DIR: {output_dir}"]

    principle_files = list(output_dir.glob("principles_*.json"))
    if not principle_files:
        return [f"NO_PRINCIPLES: {output_dir} (no principles_*.json)"]

    for pf in principle_files:
        try:
            data = read_json_file(pf)
            for i, p in enumerate(data.get("principles", [])):
                for field in PRINCIPLE_SCHEMA["required_fields"]:
                    if field not in p:
                        errors.append(f"MISSING_FIELD: {pf}: principles[{i}].'{field}'")
                score = p.get("uniqueness_score", 0)
                lo, hi = PRINCIPLE_SCHEMA["uniqueness_score_range"]
                if not (lo <= score <= hi):
                    errors.append(f"INVALID_VALUE: {pf}: principles[{i}].uniqueness_score={score} (must be {lo}-{hi})")
                # Check supporting_extracts exist
                if not p.get("supporting_extracts"):
                    errors.append(f"EMPTY_EVIDENCE: {pf}: principles[{i}] has no supporting_extracts")
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            errors.append(f"PARSE_ERROR: {pf}: {e}")
    return errors


def validate_frameworks(slug: str) -> list[str]:
    """Validate frameworks.zh.json and frameworks.en.json."""
    errors = []
    output_dir = Path(f"output/{slug}")

    # ── Stage 3A shared framework core check ──
    core_file = output_dir / "framework_core.json"
    errors.extend(validate_json_file(core_file, FRAMEWORK_CORE_SCHEMA["required_fields"]))
    if core_file.exists():
        try:
            core = read_json_file(core_file)
            if core.get("person_slug") != slug:
                errors.append(f"SLUG_MISMATCH: {core_file}: person_slug='{core.get('person_slug')}' expected '{slug}'")
            clusters = core.get("principle_clusters", [])
            if len(clusters) < FRAMEWORK_CORE_SCHEMA["min_clusters"]:
                errors.append(f"EMPTY_CORE: {core_file}: principle_clusters is empty")
            for i, cluster in enumerate(clusters):
                if not cluster.get("cluster_id"):
                    errors.append(f"MISSING_FIELD: {core_file}: principle_clusters[{i}].cluster_id")
                if not cluster.get("selected_evidence"):
                    errors.append(f"EMPTY_EVIDENCE: {core_file}: principle_clusters[{i}] has no selected_evidence")
            contract = core.get("alignment_contract", {})
            for field in ["shared_fields", "equivalent_coverage_fields", "independent_language_fields"]:
                if not contract.get(field):
                    errors.append(f"MISSING_FIELD: {core_file}: alignment_contract.{field}")
        except Exception as e:
            errors.append(f"PARSE_ERROR: {core_file}: {e}")

    # ── Stage 3 resume status check ──
    stage3_status_path = output_dir / "stage3_status.json"
    if not stage3_status_path.exists():
        errors.append(f"WARNING: {stage3_status_path} not found; interrupted Stage 3 cannot resume precisely")
    else:
        try:
            status = read_json_file(stage3_status_path)
            failed_ids = status_failed_unit_ids(status)
            blocked_ids = status.get("blocked_units", [])
            pending_ids = status.get("pending_units", [])
            if pending_ids:
                errors.append(f"WARNING: {stage3_status_path}: pending Stage 3 units remain: {pending_ids}")
            if failed_ids or blocked_ids:
                errors.append(f"STAGE3_UNRESOLVED_UNITS: {stage3_status_path}: failed={failed_ids} blocked={blocked_ids}")
            expected_outputs = {
                "framework_core": output_dir / "framework_core.json",
                "framework_zh": output_dir / "frameworks.zh.json",
                "alignment_review": output_dir / "framework_alignment_review.md",
            }
            if en_branch_requested(slug):
                expected_outputs["framework_en"] = output_dir / "frameworks.en.json"
            for unit_id in status.get("completed_units", []):
                expected = expected_outputs.get(unit_id)
                if expected and not expected.exists():
                    errors.append(f"STAGE3_STATUS_MISMATCH: {stage3_status_path}: completed unit missing output {expected}")
        except Exception as e:
            errors.append(f"STAGE3_STATUS_PARSE_ERROR: {stage3_status_path}: {e}")

    langs = ["zh", "en"] if en_branch_requested(slug) else ["zh"]
    for lang in langs:
        fw_file = output_dir / f"frameworks.{lang}.json"
        errors.extend(validate_json_file(fw_file, FRAMEWORK_SCHEMA["required_fields"]))
        if fw_file.exists():
            try:
                data = read_json_file(fw_file)
                # Check lang field
                if data.get("lang") != lang:
                    errors.append(f"LANG_MISMATCH: {fw_file}: lang='{data.get('lang')}' expected '{lang}'")
                # Check principle count — bounds depend on format_version (v6 widens 5-8 to 8-11)
                is_v6_framework = data.get("format_version") == PACKAGE_SCHEMA["format_version"]
                principle_bounds = FRAMEWORK_SCHEMA_V6_PRINCIPLES if is_v6_framework else FRAMEWORK_SCHEMA
                min_principles = principle_bounds["min_principles"]
                max_principles = principle_bounds["max_principles"]
                n_principles = len(data.get("core_principles", []))
                if n_principles < min_principles:
                    errors.append(f"TOO_FEW_PRINCIPLES: {fw_file}: {n_principles} < {min_principles}")
                if n_principles > max_principles:
                    errors.append(f"TOO_MANY_PRINCIPLES: {fw_file}: {n_principles} > {max_principles}")
                # Check blind spots
                n_blindspots = len(data.get("blind_spots", []))
                if n_blindspots < FRAMEWORK_SCHEMA["min_blind_spots"]:
                    errors.append(f"TOO_FEW_BLIND_SPOTS: {fw_file}: {n_blindspots} < {FRAMEWORK_SCHEMA['min_blind_spots']}")
                # Check blind spot mitigation
                for i, bs in enumerate(data.get("blind_spots", [])):
                    if "mitigation" not in bs:
                        errors.append(f"MISSING_MITIGATION: {fw_file}: blind_spots[{i}] has no mitigation field")
                # Check quotes
                n_quotes = len(data.get("signature_quotes", []))
                if n_quotes < FRAMEWORK_SCHEMA["min_quotes"]:
                    errors.append(f"TOO_FEW_QUOTES: {fw_file}: {n_quotes} < {FRAMEWORK_SCHEMA['min_quotes']}")
                # Check distill_confidence
                dc = data.get("distill_confidence", {})
                if "score" not in dc:
                    errors.append(f"MISSING_FIELD: {fw_file}: distill_confidence.score")
                # Check decision framework steps are filters not open questions
                steps = data.get("decision_framework", {}).get("steps", [])
                for i, step in enumerate(steps):
                    if "?" in step and not any(kw in step for kw in ["是否", "能否", "有没有", "Is", "Does", "Can", "Are", "Have", "Has"]):
                        errors.append(f"WARNING: {fw_file}: decision_framework.steps[{i}] may be open-ended (should be filter)")
                # Check expression_dna completeness
                edna = data.get("expression_dna", {})
                if not edna:
                    errors.append(f"MISSING_FIELD: {fw_file}: expression_dna is empty or missing")
                else:
                    for field in FRAMEWORK_SCHEMA["expression_dna_fields"]:
                        if not edna.get(field):
                            errors.append(f"MISSING_FIELD: {fw_file}: expression_dna.'{field}'")
                # Check values_and_antipatterns
                vap = data.get("values_and_antipatterns", {})
                if not vap:
                    errors.append(f"MISSING_FIELD: {fw_file}: values_and_antipatterns is empty or missing")
                else:
                    n_pursued = len(vap.get("pursued_values", []))
                    if n_pursued < FRAMEWORK_SCHEMA["min_pursued_values"]:
                        errors.append(f"TOO_FEW_VALUES: {fw_file}: pursued_values={n_pursued} < {FRAMEWORK_SCHEMA['min_pursued_values']}")
                    n_rejected = len(vap.get("rejected_patterns", []))
                    if n_rejected < FRAMEWORK_SCHEMA["min_rejected_patterns"]:
                        errors.append(f"TOO_FEW_ANTIPATTERNS: {fw_file}: rejected_patterns={n_rejected} < {FRAMEWORK_SCHEMA['min_rejected_patterns']}")
                    n_tensions = len(vap.get("unresolved_tensions", []))
                    if n_tensions < FRAMEWORK_SCHEMA["min_tensions"]:
                        errors.append(f"TOO_FEW_TENSIONS: {fw_file}: unresolved_tensions={n_tensions} < {FRAMEWORK_SCHEMA['min_tensions']}")
            except Exception as e:
                errors.append(f"PARSE_ERROR: {fw_file}: {e}")

    # Cross-check: blind spots must cover same themes（仅在英文分支启用时）
    try:
        if not en_branch_requested(slug):
            return errors
        zh_data = read_json_file(output_dir / "frameworks.zh.json")
        en_data = read_json_file(output_dir / "frameworks.en.json")
        zh_bs = len(zh_data.get("blind_spots", []))
        en_bs = len(en_data.get("blind_spots", []))
        if abs(zh_bs - en_bs) > 1:
            errors.append(f"BILINGUAL_MISMATCH: blind_spots count differs significantly: zh={zh_bs} en={en_bs}")
        # Categories must match
        if zh_data.get("primary_category") != en_data.get("primary_category"):
            errors.append(f"BILINGUAL_MISMATCH: primary_category differs")
        if sorted(zh_data.get("secondary_categories", [])) != sorted(en_data.get("secondary_categories", [])):
            errors.append(f"BILINGUAL_MISMATCH: secondary_categories differs")
        zh_sources = {s.get("title", "") for s in zh_data.get("sources_list", []) if s.get("title")}
        en_sources = {s.get("title", "") for s in en_data.get("sources_list", []) if s.get("title")}
        if zh_sources and en_sources:
            overlap = len(zh_sources & en_sources)
            coverage = overlap / max(len(zh_sources), len(en_sources))
            if coverage < 0.6:
                errors.append(f"WARNING: sources_list title overlap is low ({coverage:.0%}); framework-alignment-reviewer should confirm equivalent coverage")
    except Exception:
        pass  # Files may not exist yet

    return errors


def is_v6_skill(content: str) -> bool:
    """v6 包由 frontmatter 的 format_version 判定；无此字段一律按 legacy 处理。

    只在解析出的 frontmatter 块内匹配，避免正文中示例代码块（如文档自身讲解
    v6 格式时贴出的 ```yaml 片段）触发误判。
    """
    match = SKILL_FRONTMATTER_PATTERN.search(content)
    if not match:
        return False
    frontmatter = match.group(1)
    return bool(re.search(
        rf"^[ \t]*format_version[ \t]*:[ \t]*{PACKAGE_SCHEMA['format_version']}[ \t]*$",
        frontmatter, re.MULTILINE,
    ))


def en_branch_requested(slug: str) -> bool:
    """英文分支是否已被用户选用（Stage 6.5 落 en_requested.flag）。"""
    return Path(f"output/{slug}/en_requested.flag").exists()


def validate_skill(slug: str) -> list[str]:
    """Validate the merged SKILL.md file (bilingual single-file format).

    Supports both the new merged format (single SKILL.md with ## English / ## 中文版)
    and legacy separate files (SKILL.zh.md + SKILL.en.md) as fallback.
    """
    errors = []
    output_dir = Path(f"output/{slug}")

    # ── Try merged SKILL.md first (preferred format) ──
    merged_file = output_dir / "SKILL.md"
    if merged_file.exists():
        if is_v6_skill(merged_file.read_text(encoding="utf-8")):
            return validate_package(slug)
        return _validate_merged_skill(merged_file, slug)

    # ── Fallback: separate SKILL.{lang}.md files ──
    for lang in ["zh", "en"]:
        skill_file = output_dir / f"SKILL.{lang}.md"
        if not skill_file.exists():
            errors.append(f"MISSING: {skill_file}")
            continue
        errors.extend(_validate_single_lang_skill(skill_file, slug, lang))

    if not errors:
        errors.append(f"WARNING: {output_dir}: using legacy separate files; consider merging into SKILL.md")
    return errors


def _sha256(filepath: Path) -> str:
    """Return the SHA-256 digest for a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_gallery(slug: str) -> list[str]:
    """Validate the published gallery artifact and ensure it is synced from output."""
    errors = []
    output_file = Path(f"output/{slug}/SKILL.md")
    gallery_file = Path(f"gallery/{slug}/SKILL.md")

    if not output_file.exists():
        return [f"MISSING: {output_file}"]
    if not gallery_file.exists():
        return [f"MISSING: {gallery_file}"]

    v6 = is_v6_skill(gallery_file.read_text(encoding="utf-8"))
    sync_targets = ["SKILL.md"]
    if v6:
        refs_src = Path(f"output/{slug}/references")
        if refs_src.exists():
            sync_targets += [f"references/{p.name}" for p in sorted(refs_src.glob("*.md"))]

    for rel in sync_targets:
        out_path = Path(f"output/{slug}/{rel}")
        gal_path = Path(f"gallery/{slug}/{rel}")
        if not gal_path.exists():
            errors.append(f"GALLERY_MISSING_FILE: {gal_path} (present in output/)")
            continue
        if _sha256(out_path) != _sha256(gal_path):
            errors.append(
                f"GALLERY_OUT_OF_SYNC: {gal_path} does not match {out_path} "
                f"(gallery={_sha256(gal_path)[:12]}, output={_sha256(out_path)[:12]})"
            )

    if v6:
        errors.extend(validate_package(slug))
    else:
        errors.extend(_validate_merged_skill(gallery_file, slug))

    index_file = Path("gallery/index.json")
    if not index_file.exists():
        errors.append(f"MISSING: {index_file}")
    else:
        try:
            index = read_json_file(index_file)
            entries = index.get("skills", [])
            entry = next((e for e in entries if e.get("slug") == slug), None)
            if not entry:
                errors.append(f"MISSING_GALLERY_INDEX_ENTRY: {index_file}: slug='{slug}'")
            elif entry.get("skill_dir") != f"gallery/{slug}/":
                errors.append(
                    f"INVALID_GALLERY_INDEX_ENTRY: {index_file}: skill_dir='{entry.get('skill_dir')}'"
                )
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            errors.append(f"PARSE_ERROR: {index_file}: {e}")

    return errors


# ── v6 包闸门（P3–P6）────────────────────────────────────────────────

BACKTICK_PATH_RE = re.compile(r"`([A-Za-z0-9_./-]+\.(?:md|json|py|txt))`")
CASE_ID_RE = re.compile(r"case_id:\s*([A-Za-z0-9_-]+)")
CASE_CLUSTER_RE = re.compile(r"^\*\*对应原则簇：\*\*\s*(\S+)\s*$", re.MULTILINE)
CASE_HEADING_RE = re.compile(r"^###\s+.*$", re.MULTILINE)
CASE_COUNTER_FIELD_RE = re.compile(r"^\*\*反例[:：]\*\*", re.MULTILINE)


def check_p3_paths(skill_md: Path) -> list[str]:
    """P3：SKILL.md 中每个反引号路径必须解析到实际文件。"""
    if not skill_md.exists():
        return [f"MISSING: {skill_md}"]
    base = skill_md.parent
    errors = []
    for match in BACKTICK_PATH_RE.finditer(skill_md.read_text(encoding="utf-8")):
        rel = match.group(1)
        if (base / rel).exists():
            continue
        errors.append(f"P3_DANGLING_PATH: {skill_md}: `{rel}` 无法解析到实际文件")
    return errors


def _parse_cases(cases_md: Path) -> list[dict]:
    text = cases_md.read_text(encoding="utf-8")
    headings = list(CASE_HEADING_RE.finditer(text))
    cases = []
    for i, match in enumerate(headings):
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        block = text[match.start():end]
        case_id = CASE_ID_RE.search(block)
        cluster = CASE_CLUSTER_RE.search(block)
        cases.append({
            "case_id": case_id.group(1) if case_id else None,
            "cluster": cluster.group(1) if cluster else None,
            "is_counter": bool(CASE_COUNTER_FIELD_RE.search(block)),
        })
    return cases


def check_p4_cases(cases_md: Path, cluster_ids: list[str]) -> list[str]:
    """P4：每个 principle cluster ≥2 例；全库 ≥1 反例。"""
    if not cases_md.exists():
        return [f"MISSING: {cases_md}"]
    cases = _parse_cases(cases_md)
    errors = []
    for case in cases:
        if not case["case_id"]:
            errors.append(f"P4_MISSING_CASE_ID: {cases_md}: 存在无 case_id 的案例")
    for cluster_id in cluster_ids:
        count = sum(1 for c in cases if c["cluster"] == cluster_id)
        if count < PACKAGE_SCHEMA["min_cases_per_cluster"]:
            errors.append(
                f"P4_TOO_FEW_CASES: {cases_md}: cluster '{cluster_id}' 只有 {count} 例 "
                f"< {PACKAGE_SCHEMA['min_cases_per_cluster']}"
            )
    counters = sum(1 for c in cases if c["is_counter"])
    if counters < PACKAGE_SCHEMA["min_counter_cases"]:
        errors.append(f"P4_NO_COUNTER_CASE: {cases_md}: 全库反例数 {counters} < 1")
    return errors


def check_p5_index(skill_md: Path, cases_md: Path) -> list[str]:
    """P5：SKILL.md 案例索引与 cases.md 的 case_id 必须双向一一对应。"""
    if not skill_md.exists():
        return [f"MISSING: {skill_md}"]
    if not cases_md.exists():
        return [f"MISSING: {cases_md}"]
    content = skill_md.read_text(encoding="utf-8")
    section = re.search(
        r"^##\s*案例索引\s*$(.*?)(?=^##\s|\Z)",
        content,
        re.MULTILINE | re.DOTALL,
    )
    indexed = set()
    if section:
        index_text = section.group(1)
        indexed.update(CASE_ID_RE.findall(index_text))
        for line in index_text.splitlines():
            if line.strip().startswith("|"):
                for cell in line.split("|"):
                    token = cell.strip()
                    if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)+", token):
                        indexed.add(token)
    actual = {c["case_id"] for c in _parse_cases(cases_md) if c["case_id"]}
    errors = []
    for orphan in sorted(indexed - actual):
        errors.append(f"P5_INDEX_ORPHAN: {skill_md}: 索引引用了不存在的 case_id '{orphan}'")
    for missing in sorted(actual - indexed):
        errors.append(f"P5_CASE_NOT_INDEXED: {cases_md}: case_id '{missing}' 未出现在案例索引中")
    return errors


def check_p6_core(skill_md: Path) -> list[str]:
    """P6：核心自足——≤500 行，8 个必需章节齐备且非空（不检查指针，那是 P3 的事）。"""
    if not skill_md.exists():
        return [f"MISSING: {skill_md}"]
    content = skill_md.read_text(encoding="utf-8")
    errors = []
    line_count = len(content.splitlines())
    if line_count > PACKAGE_SCHEMA["skill_max_lines"]:
        errors.append(
            f"P6_TOO_LONG: {skill_md}: {line_count} 行 > "
            f"{PACKAGE_SCHEMA['skill_max_lines']} 行上限"
        )
    headings = list(re.finditer(r"^(#{2,4})\s*(.+?)\s*$", content, re.MULTILINE))
    for name in PACKAGE_SCHEMA["core_sections"]:
        hit = None
        for i, match in enumerate(headings):
            if match.group(1) == "##" and match.group(2).startswith(name):
                # 章节体一直延伸到下一个 H2（不是任意级别的下一个标题）——
                # 这样内容全部挂在 ### 子标题下的章节不会被误判为空。
                # 标题匹配规则本身不变：仍只认 H2、仍要求 startswith(name)。
                end = len(content)
                for later in headings[i + 1:]:
                    if later.group(1) == "##":
                        end = later.start()
                        break
                hit = content[match.end():end].strip()
                break
        if hit is None:
            errors.append(f"P6_MISSING_SECTION: {skill_md}: 缺少必需章节 '{name}'")
        elif not hit:
            errors.append(f"P6_EMPTY_SECTION: {skill_md}: 章节 '{name}' 为空")
    return errors


def validate_package(slug: str) -> list[str]:
    """v6 包整体校验：结构 + P1–P6 六道闸门。"""
    root = Path(".")
    output_dir = root / "output" / slug
    skill_md = output_dir / "SKILL.md"
    refs_dir = output_dir / PACKAGE_SCHEMA["reference_dir"]
    errors: list[str] = []

    if not skill_md.exists():
        return [f"MISSING: {skill_md}"]

    content = skill_md.read_text(encoding="utf-8")
    if not is_v6_skill(content):
        errors.append(
            f"NOT_V6: {skill_md}: frontmatter 缺少 "
            f"'format_version: {PACKAGE_SCHEMA['format_version']}'"
        )
    if re.search(r"^##\s+English", content, re.MULTILINE):
        errors.append(f"V6_HAS_ENGLISH_BLOCK: {skill_md}: v6 包不得含 '## English' 区块")

    for name in PACKAGE_SCHEMA["required_refs"]:
        if not (refs_dir / name).exists():
            errors.append(f"MISSING: {refs_dir / name}")

    errors.extend(check_p3_paths(skill_md))
    errors.extend(check_p6_core(skill_md))

    cases_md = refs_dir / "cases.md"
    evidence_md = refs_dir / "evidence.md"

    cluster_ids: list[str] = []
    core_file = output_dir / "framework_core.json"
    if core_file.exists():
        try:
            core = read_json_file(core_file)
            cluster_ids = [
                c.get("cluster_id") for c in core.get("principle_clusters", [])
                if c.get("cluster_id")
            ]
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            errors.append(f"PARSE_ERROR: {core_file}: {e}")

    if cases_md.exists():
        errors.extend(check_p4_cases(cases_md, cluster_ids))
        errors.extend(check_p5_index(skill_md, cases_md))

    if evidence_md.exists():
        prov = _load_provenance()
        errors.extend(prov.check_p1_quote_closure(skill_md, evidence_md))
        errors.extend(prov.check_p2_corpus_closure(evidence_md, slug, root))

    return errors


def _load_provenance():
    """按路径加载同目录的 verify_provenance 模块（scripts/ 不是包）。"""
    import importlib.util
    path = Path(__file__).resolve().parent / "verify_provenance.py"
    spec = importlib.util.spec_from_file_location("verify_provenance", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _validate_merged_skill(filepath: Path, slug: str) -> list[str]:
    """Validate a merged bilingual SKILL.md file."""
    errors = []
    content = filepath.read_text(encoding="utf-8")

    # ── Frontmatter checks ──
    match = SKILL_FRONTMATTER_PATTERN.match(content)
    if not match:
        errors.append(f"NO_FRONTMATTER: {filepath}")
        return errors
    fm = match.group(1)
    if "name:" not in fm:
        errors.append(f"MISSING_FIELD: {filepath}: frontmatter 'name'")
    if "description:" not in fm:
        errors.append(f"MISSING_FIELD: {filepath}: frontmatter 'description'")
    if f"{slug}-wisdom" not in fm:
        errors.append(f"WRONG_NAME: {filepath}: frontmatter name should contain '{slug}-wisdom'")

    # ── Language detection header ──
    if "Language Detection" not in content and "语言检测" not in content:
        errors.append(f"MISSING_LANG_DETECTION: {filepath}: language detection header not found")

    # ── Bilingual section markers ──
    has_en_section = bool(re.search(r"^##\s+English", content, re.MULTILINE))
    has_zh_section = bool(re.search(r"^##\s+中文版", content, re.MULTILINE))
    if not has_en_section:
        errors.append(f"MISSING_SECTION: {filepath}: '## English' language block not found")
    if not has_zh_section:
        errors.append(f"MISSING_SECTION: {filepath}: '## 中文版' language block not found")

    # ── Split content into EN and ZH blocks for section checks ──
    en_block = ""
    zh_block = ""
    en_match = re.search(r"^##\s+English\s*\n(.*?)(?=^##\s+中文版|\Z)", content, re.MULTILINE | re.DOTALL)
    zh_match = re.search(r"^##\s+中文版\s*\n(.*)", content, re.MULTILINE | re.DOTALL)
    if en_match:
        en_block = en_match.group(1)
    if zh_match:
        zh_block = zh_match.group(1)

    # ── Check required sections in each language block ──
    # Use flexible matching: check for any of several acceptable variants
    en_section_checks = {
        "Identity Card": [r"Identity\s+Card"],
        "Response Strategy": [r"Response\s+Strategy", r"How\s+to\s+Use"],
        "Core Principles": [r"Core\s+Principles"],
        "Decision-Making Framework": [r"Decision[\s-]*Making\s+Framework", r"Decision\s+Framework"],
        "Known Blind Spots": [r"Known\s+Blind\s+Spots"],
        "Expression DNA": [r"Expression\s+DNA"],
        "Values & Anti-Patterns": [r"Values\s*[&和与]\s*Anti[\s-]*Patterns?"],
        "Source Lineage": [r"Source\s+Lineage", r"Sources?"],
    }
    zh_section_checks = {
        "身份卡": [r"身份卡"],
        "响应策略": [r"响应策略", r"使用方式"],
        "核心原则": [r"核心原则"],
        "决策框架": [r"决策框架"],
        "已知盲区": [r"已知盲区"],
        "表达风格 DNA": [r"表达风格\s*DNA", r"表达\s*DNA"],
        "价值取向与反模式": [r"价值取向", r"核心价值.*反模式"],
        "溯源": [r"溯源"],
    }

    for canonical, patterns in en_section_checks.items():
        found = any(re.search(p, en_block, re.IGNORECASE) for p in patterns)
        if not found:
            errors.append(f"MISSING_SECTION: {filepath} [English]: '{canonical}'")
        # Warn if non-canonical name used
        elif canonical == "Response Strategy" and not re.search(r"Response\s+Strategy", en_block):
            errors.append(f"WARNING: {filepath} [English]: section uses non-canonical name (expected 'Response Strategy')")
        elif canonical == "Values & Anti-Patterns" and not re.search(r"Values\s*&\s*Anti-Patterns", en_block):
            errors.append(f"WARNING: {filepath} [English]: section uses non-canonical name (expected 'Values & Anti-Patterns')")

    for canonical, patterns in zh_section_checks.items():
        found = any(re.search(p, zh_block) for p in patterns)
        if not found:
            errors.append(f"MISSING_SECTION: {filepath} [中文]: '{canonical}'")
        # Warn if non-canonical name used
        elif canonical == "响应策略" and "响应策略" not in zh_block:
            errors.append(f"WARNING: {filepath} [中文]: section uses non-canonical name (expected '响应策略', found '使用方式')")
        elif canonical == "表达风格 DNA" and not re.search(r"表达风格\s*DNA", zh_block):
            errors.append(f"WARNING: {filepath} [中文]: section uses non-canonical name (expected '表达风格 DNA')")
        elif canonical == "价值取向与反模式" and "价值取向" not in zh_block:
            errors.append(f"WARNING: {filepath} [中文]: section uses non-canonical name (expected '价值取向与反模式')")

    # ── Anti-formula checks ──
    if not re.search(r"Anti[\s-]*Formula", en_block, re.IGNORECASE):
        errors.append(f"MISSING_ANTI_FORMULA: {filepath} [English]: anti-formula instructions not found")
    if not re.search(r"反套公式|反公式化", zh_block):
        errors.append(f"MISSING_ANTI_FORMULA: {filepath} [中文]: anti-formula instructions not found")
    elif "反套公式" not in zh_block and "反公式化" in zh_block:
        errors.append(f"WARNING: {filepath} [中文]: uses '反公式化' instead of canonical '反套公式'")

    # ── Bilingual description check ──
    desc_block = fm[fm.find("description:"):] if "description:" in fm else ""
    # Check that description has both Chinese and ASCII content
    has_chinese = bool(re.search(r"[一-鿿]", desc_block))
    has_english = bool(re.search(r"[a-zA-Z]{3,}", desc_block))
    if not has_chinese:
        errors.append(f"MISSING_BILINGUAL_DESC: {filepath}: description lacks Chinese content")
    if not has_english:
        errors.append(f"MISSING_BILINGUAL_DESC: {filepath}: description lacks English content")

    # ── Description length check ──
    # Extract only the description value (stop before next YAML field at column 0)
    desc_value = desc_block
    # Next YAML key appears after \n at column 0; description continuation lines are indented
    next_key = re.search(r"\n[a-z][a-z_-]+:", desc_value)
    if next_key:
        desc_value = desc_value[:next_key.start()]
    desc_text = desc_value.replace("description:", "", 1).strip()
    desc_text = re.sub(r"^>\s*-?\s*", "", desc_text).strip()
    total_len = len(desc_text)
    if total_len > 300:
        errors.append(
            f"DESCRIPTION_TOO_LONG: {filepath}: "
            f"{total_len} chars (max 300). Shorten to 1-2 sentences per language."
        )

    # ── Unfilled placeholders ──
    placeholders = re.findall(r"\{[a-z_]+\}", content)
    # Filter out legitimate code/template references
    real_placeholders = [p for p in placeholders if p not in ["{slug}", "{person_slug}"]]
    if real_placeholders:
        errors.append(f"UNFILLED_PLACEHOLDERS: {filepath}: {real_placeholders[:5]}")

    return errors


def _validate_single_lang_skill(filepath: Path, slug: str, lang: str) -> list[str]:
    """Validate a single-language SKILL.{lang}.md file (legacy format)."""
    errors = []
    content = filepath.read_text(encoding="utf-8")

    match = SKILL_FRONTMATTER_PATTERN.match(content)
    if not match:
        errors.append(f"NO_FRONTMATTER: {filepath}")
        return errors
    fm = match.group(1)
    if "name:" not in fm:
        errors.append(f"MISSING_FIELD: {filepath}: frontmatter 'name'")
    if "description:" not in fm:
        errors.append(f"MISSING_FIELD: {filepath}: frontmatter 'description'")
    if f"{slug}-wisdom" not in fm:
        errors.append(f"WRONG_NAME: {filepath}: frontmatter name should contain '{slug}-wisdom'")

    placeholders = re.findall(r"\{[a-z_]+\}", content)
    if placeholders:
        errors.append(f"UNFILLED_PLACEHOLDERS: {filepath}: {placeholders[:5]}")

    required_sections = ["身份卡" if lang == "zh" else "Identity Card",
                       "响应策略" if lang == "zh" else "Response Strategy",
                       "核心原则" if lang == "zh" else "Core Principles",
                       "决策框架" if lang == "zh" else "Decision-Making Framework",
                       "已知盲区" if lang == "zh" else "Known Blind Spots",
                       "表达风格 DNA" if lang == "zh" else "Expression DNA",
                       "价值取向" if lang == "zh" else "Values",
                       "溯源" if lang == "zh" else "Source Lineage"]
    for section in required_sections:
        if section not in content:
            errors.append(f"MISSING_SECTION: {filepath}: '{section}'")

    anti_marker = "反套公式" if lang == "zh" else "Anti-Formula"
    if anti_marker not in content:
        errors.append(f"MISSING_ANTI_FORMULA: {filepath}: anti-formula instructions not found")

    return errors


# ── Main ────────────────────────────────────────────────────────────

STAGES = {
    "sources": validate_sources,
    "principles": validate_principles,
    "frameworks": validate_frameworks,
    "skill": validate_skill,
    "package": validate_package,
    "gallery": validate_gallery,
}

def main():
    if len(sys.argv) < 3:
        print(f"Usage: python {sys.argv[0]} <stage> <person-slug>")
        print(f"Stages: {', '.join(STAGES.keys())}")
        sys.exit(1)

    stage = sys.argv[1]
    slug = sys.argv[2]

    if stage not in STAGES:
        print(f"Unknown stage: {stage}. Available: {', '.join(STAGES.keys())}")
        sys.exit(1)

    print(f"Validating stage '{stage}' for '{slug}'...")
    errors = STAGES[stage](slug)

    warnings = [e for e in errors if e.startswith("WARNING:")]
    hard_errors = [e for e in errors if not e.startswith("WARNING:")]

    if warnings:
        print(f"\n⚠️  {len(warnings)} warning(s):")
        for w in warnings:
            print(f"  {w}")

    if hard_errors:
        print(f"\n❌ {len(hard_errors)} error(s):")
        for e in hard_errors:
            print(f"  {e}")
        sys.exit(1)
    else:
        print(f"\n✅ Stage '{stage}' passed for '{slug}'")
        if warnings:
            print(f"   ({len(warnings)} warning(s) — review recommended)")
        sys.exit(0)


if __name__ == "__main__":
    main()
