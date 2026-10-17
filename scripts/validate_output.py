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
  published — validate gallery/{slug}/ standalone: manifest v2 hashes + attested P2,
              v6 gates P1/P3-P6 rerun in place; never reads output/ or sources/
  gallery   — alias of published
"""

import functools
import json
import sys
import re
import os
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
    # P6 深度下限：真实样板包（zhang-juzheng-v6）最薄的必需章节（身份卡）有
    # 322 字符；用一行指针把整章替换成「详见 references/xxx.md」只有约 15-25
    # 字符。150 介于二者之间、离真实内容有约 2 倍余量，足以拦住「指针替身」而
    # 不会误伤真实的薄章节。
    "min_section_chars": 150,
    # ── M4 加固 ──
    "min_voice_samples": 20,
    "decision_steps": (3, 8),
    "dna_dimensions": ["句式偏好", "标志性修辞", "语气基调", "确定性表达",
                       "幽默风格", "禁忌表达", "段落节奏", "口语化标记"],
    # 「价值取向与反模式」各子节最少条目数（CLAUDE.md 质量门：≥2 追求、≥2 反对、≥1 张力）
    "values_min_items": {"坚定追求": 2, "坚决反对": 2, "内在张力": 1},
    "min_blind_spots": 2,
    # 「响应策略」各子节最少规则数，按子标题关键词匹配
    "response_min_rules": {"反套公式": 6, "结构自然性": 5, "边界规则": 5, "输入类型": 6},
    # 核心原则数下限，与 FRAMEWORK_SCHEMA_V6_PRINCIPLES["min_principles"] 保持
    # 同一个 v6 底线（8）；样板包实际有 9 条。
    "min_principles": 8,
    # ── 伦理与法律（docs/ethics-and-legal.md）──
    # 引文保持「引用」量级而非「复制」量级，按非空白字符计。样板包实测：核心层引文最长 58、
    # 证据卡最长 291（中位 80.5）、语感样本最长 50、证据原文合计 3186；legacy 包核心层最长 216。
    "quote_max_chars": {"core": 240, "evidence": 400, "voice": 200},
    "evidence_total_max_chars": 15000,
    # 在世人物的包必须带这一行声明（写法见 templates/skill-template.v6.zh.md）。
    "living_notice_label": "在世人物声明",
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

    # Registry, manifest, sidecar, and cost metadata are contracts, not
    # source extract files. Only the four extract payloads enter the legacy
    # SOURCE_FILE_SCHEMA loop below.
    metadata_names = {
        "source_registry.json",
        "provenance_manifest.json",
        "corpus_inventory.json",
        "sampling_plan.json",
        "cost_estimate.json",
    }
    json_files = [p for p in processed_dir.glob("*.json") if p.name not in metadata_names]
    if not json_files:
        return [f"EMPTY_DIR: {processed_dir} (no source extract .json files)"]

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


# ── v6 包闸门（P3–P6）────────────────────────────────────────────────

BACKTICK_PATH_RE = re.compile(r"`([A-Za-z0-9_./-]+\.(?:md|json|py|txt))`")
CASE_ID_RE = re.compile(r"case_id:\s*([A-Za-z0-9_-]+)")
# P5 解析索引表格时只认这种形状；case_id 本身也必须是这种形状，否则写进表格也会被判「未索引」。
CASE_ID_FORMAT_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)+")
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
    """P4：每个 principle cluster ≥2 例；全库 ≥1 反例；case_id 唯一且形状合规；
    每个案例的原则簇必须存在于簇列表。"""
    if not cases_md.exists():
        return [f"MISSING: {cases_md}"]
    cases = _parse_cases(cases_md)
    errors = []
    known = set(cluster_ids)
    seen: set[str] = set()
    for case in cases:
        case_id = case["case_id"]
        if not case_id:
            errors.append(f"P4_MISSING_CASE_ID: {cases_md}: 存在无 case_id 的案例")
            continue
        if case_id in seen:
            errors.append(f"P4_DUPLICATE_CASE_ID: {cases_md}: case_id '{case_id}' 重复出现")
        seen.add(case_id)
        if not CASE_ID_FORMAT_RE.fullmatch(case_id):
            errors.append(
                f"P4_BAD_CASE_ID: {cases_md}: case_id '{case_id}' 须为小写-连字符形式"
                f"（如 demo-c1-1），否则 P5 的索引表格认不出它"
            )
        if not case["cluster"]:
            errors.append(f"P4_MISSING_CLUSTER: {cases_md}: 案例 '{case_id}' 缺少「对应原则簇」")
        elif known and case["cluster"] not in known:
            # 簇列表为空时由 P4_EMPTY_CLUSTERS / MANIFEST_NO_CLUSTERS 报，这里不重复刷屏。
            errors.append(
                f"P4_UNKNOWN_CLUSTER: {cases_md}: 案例 '{case_id}' 指向不存在的原则簇 '{case['cluster']}'"
            )
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
                    if CASE_ID_FORMAT_RE.fullmatch(token):
                        indexed.add(token)
    actual = {c["case_id"] for c in _parse_cases(cases_md) if c["case_id"]}
    errors = []
    for orphan in sorted(indexed - actual):
        errors.append(f"P5_INDEX_ORPHAN: {skill_md}: 索引引用了不存在的 case_id '{orphan}'")
    for missing in sorted(actual - indexed):
        errors.append(f"P5_CASE_NOT_INDEXED: {cases_md}: case_id '{missing}' 未出现在案例索引中")
    return errors


PRINCIPLE_SUBHEADING_RE = re.compile(r"^###\s*原则", re.MULTILINE)


def check_p6_core(skill_md: Path) -> list[str]:
    """P6：核心自足——≤500 行，8 个必需章节齐备、非空、有实质深度，核心原则数
    达标（不检查指针，那是 P3 的事）。"""
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
        else:
            if len(hit) < PACKAGE_SCHEMA["min_section_chars"]:
                errors.append(
                    f"P6_SECTION_TOO_THIN: {skill_md}: 章节 '{name}' 正文（去空白）仅 "
                    f"{len(hit)} 字符 < {PACKAGE_SCHEMA['min_section_chars']} 字符下限"
                    f"——疑似被替换成指向 references/ 的一行指针，核心层未能自足"
                )
            if name == "核心原则":
                n_principles = len(PRINCIPLE_SUBHEADING_RE.findall(hit))
                if n_principles < PACKAGE_SCHEMA["min_principles"]:
                    errors.append(
                        f"P6_TOO_FEW_PRINCIPLES: {skill_md}: 核心原则章节仅含 "
                        f"{n_principles} 条「### 原则」子标题 < "
                        f"{PACKAGE_SCHEMA['min_principles']} 条下限"
                    )
    return errors


# ── M4 加固：附件内容、核心结构、模板残留、strict ─────────────────────

H2_RE = re.compile(r"^##(?!#)\s*(.+?)\s*$", re.MULTILINE)
H3_RE = re.compile(r"^###(?!#)\s*(.+?)\s*$", re.MULTILINE)
LIST_ITEM_RE = re.compile(r"^(?:\d+\.|[-*])\s+\S", re.MULTILINE)
CONFIDENCE_VALUE_RE = re.compile(r"(high|medium|low)(?![A-Za-z])")
EVIDENCE_PRINCIPLE_RE = re.compile(r"^原则\s*(\d+)(?!\d)")
SKILL_PRINCIPLE_RE = re.compile(r"^###(?!#)\s*原则\s*(\d+)(?!\d)", re.MULTILINE)
VOICE_SPLIT_RE = re.compile(r"^###\s*样本", re.MULTILINE)
VOICE_QUOTE_RE = re.compile(r"^>\s?\S", re.MULTILINE)
# 性别中立：女性思想家的样本写「为什么像她」。
VOICE_WHY_RE = re.compile(r"为什么像[他她]")
VOICE_ANTI_MARKER = "误写成通用分析腔"
UNRESOLVED_NOTE_RE = re.compile(
    r"^(?:待定|待裁决|待核实?|未定|TODO|TBD|N/?A|无|[?？]+|[.。…]+)$", re.IGNORECASE
)
TEMPLATE_RESIDUE_RE = re.compile(r"\{/?repeat_block[^}\n]*\}|\{[^{}\n]{1,60}\}")
FENCE_RE = re.compile(r"^```[^\n]*\n(.*?)^```", re.MULTILINE | re.DOTALL)
DECISION_ARROW_LINE_RE = re.compile(r"^[\s↓⬇↘→|vV]*$")


def _h2_body(content: str, name: str) -> str | None:
    """标题以 name 开头的 H2 章节正文（到下一个 H2 为止）；不存在返回 None。"""
    headings = list(H2_RE.finditer(content))
    for i, match in enumerate(headings):
        if match.group(1).startswith(name):
            end = headings[i + 1].start() if i + 1 < len(headings) else len(content)
            return content[match.end():end]
    return None


def _h3_bodies(body: str) -> list[tuple[str, str]]:
    headings = list(H3_RE.finditer(body))
    return [
        (m.group(1), body[m.end():headings[i + 1].start() if i + 1 < len(headings) else len(body)])
        for i, m in enumerate(headings)
    ]


def check_evidence_cards(evidence_md: Path, skill_md: Path) -> list[str]:
    """证据卡结构（规则 1–4、11）：非空、字段齐全、覆盖每条原则、high 有语料位置、裁决不是空话。"""
    if not evidence_md.exists():
        return [f"MISSING: {evidence_md}"]
    cards = _load_provenance().parse_evidence_cards(evidence_md.read_text(encoding="utf-8"))
    if not cards:
        return [f"EVIDENCE_EMPTY: {evidence_md}: 没有任何证据卡（### 标题 + > 逐字原文）"]

    errors: list[str] = []
    covered: set[str] = set()
    for card in cards:
        where = f"{evidence_md} [{card['title']}]"
        fields = card["fields"]
        if not card["verbatim"]:
            errors.append(f"EVIDENCE_NO_QUOTE: {where}: 卡内没有 > 逐字原文")
        if not fields.get("出处"):
            errors.append(f"EVIDENCE_MISSING_FIELD: {where}: 缺少「- 出处：」")
        confidence = fields.get("confidence")
        level = CONFIDENCE_VALUE_RE.match(confidence) if confidence else None
        if confidence is None:
            errors.append(f"EVIDENCE_MISSING_FIELD: {where}: 缺少「- confidence：」")
        elif level is None:
            errors.append(f"EVIDENCE_BAD_CONFIDENCE: {where}: confidence={confidence!r}，须为 high/medium/low")
        elif level.group(1) == "high" and not fields.get("语料位置"):
            # Rule 6：只有一手来源可标 high。语料是否真的在本地由 P2 逐字比对证明，
            # 这里只要求 high 卡写明出自语料哪里。
            errors.append(f"EVIDENCE_HIGH_WITHOUT_CORPUS: {where}: confidence 为 high 却没有「- 语料位置：」")
        note = fields.get("textual_note")
        if note is not None and UNRESOLVED_NOTE_RE.match(note.strip()):
            errors.append(
                f"EVIDENCE_UNRESOLVED_ADJUDICATION: {where}: textual_note={note!r} 是占位而非裁决依据"
                f"——P2 会因这个字段把逐字不符降级为 WARNING"
            )
        principle = EVIDENCE_PRINCIPLE_RE.match(card["title"])
        if principle:
            covered.add(principle.group(1))

    if skill_md.exists():
        core = _h2_body(skill_md.read_text(encoding="utf-8"), "核心原则") or ""
        for number in SKILL_PRINCIPLE_RE.findall(core):
            if number not in covered:
                errors.append(
                    f"EVIDENCE_PRINCIPLE_UNCOVERED: {evidence_md}: 核心原则 {number} 没有对应的证据卡"
                    f"（标题以「原则 {number}」开头）"
                )
    return errors


def check_voice_samples(voice_md: Path) -> list[str]:
    """语感样本（规则 5–6）：≥20 条，每条有原文、正向标注、反例改写。"""
    if not voice_md.exists():
        return [f"MISSING: {voice_md}"]
    blocks = VOICE_SPLIT_RE.split(voice_md.read_text(encoding="utf-8"))[1:]
    errors: list[str] = []
    minimum = PACKAGE_SCHEMA["min_voice_samples"]
    if len(blocks) < minimum:
        errors.append(f"VOICE_TOO_FEW: {voice_md}: 仅 {len(blocks)} 条样本 < {minimum}")
    for i, block in enumerate(blocks, 1):
        missing = []
        if not VOICE_QUOTE_RE.search(block):
            missing.append("> 原文片段")
        if not VOICE_WHY_RE.search(block):
            missing.append("「为什么像他/她」")
        if VOICE_ANTI_MARKER not in block:
            missing.append(f"「{VOICE_ANTI_MARKER}」反例")
        if missing:
            errors.append(f"VOICE_SAMPLE_INCOMPLETE: {voice_md}: 第 {i} 条样本缺少 {'、'.join(missing)}")
    return errors


def check_p6_structure(skill_md: Path) -> list[str]:
    """核心层结构（规则 7、12、14–16）：表达 DNA 八维、决策框架是非题、价值取向、
    盲区缓解、响应策略规则数。章节缺失本身由 check_p6_core 报，这里不重复。"""
    if not skill_md.exists():
        return [f"MISSING: {skill_md}"]
    content = skill_md.read_text(encoding="utf-8")
    errors: list[str] = []

    dna = _h2_body(content, "表达风格 DNA")
    if dna is not None:
        rows = {k.strip(): v.strip() for k, v in re.findall(r"^\|\s*([^|\n]+?)\s*\|\s*([^|\n]*?)\s*\|", dna, re.M)}
        for dim in PACKAGE_SCHEMA["dna_dimensions"]:
            if dim not in rows:
                errors.append(f"P6_DNA_MISSING_DIMENSION: {skill_md}: 表达风格 DNA 缺少维度「{dim}」")
            elif not rows[dim] or TEMPLATE_RESIDUE_RE.search(rows[dim]):
                errors.append(f"P6_DNA_EMPTY_DIMENSION: {skill_md}: 表达风格 DNA 维度「{dim}」为空或仍是占位")
        if not re.search(r"✅.*「[^」]+」", dna) or not re.search(r"❌.*「[^」]+」", dna):
            errors.append(f"P6_DNA_NO_CALIBRATION: {skill_md}: 语感校准须各有一条 ✅ 与 ❌ 示例")

    decision = _h2_body(content, "决策框架")
    if decision is not None:
        fence = FENCE_RE.search(decision)
        if fence is None:
            errors.append(f"P6_DF_NO_CODE_BLOCK: {skill_md}: 决策框架缺少 ``` 代码块形式的过滤链")
        else:
            steps = [ln.strip() for ln in fence.group(1).splitlines() if not DECISION_ARROW_LINE_RE.match(ln)]
            low, high = PACKAGE_SCHEMA["decision_steps"]
            if not low <= len(steps) <= high:
                errors.append(f"P6_DF_STEP_COUNT: {skill_md}: 决策框架 {len(steps)} 步，须在 {low}–{high} 步之间")
            for step in steps:
                if not step.endswith(("？", "?")):
                    errors.append(
                        f"P6_DF_NOT_A_QUESTION: {skill_md}: 决策框架步骤须是以「？」结尾的是/否闸门：{step[:40]}"
                    )

    values = _h2_body(content, "价值取向")
    if values is not None:
        subsections = _h3_bodies(values)
        for keyword, minimum in PACKAGE_SCHEMA["values_min_items"].items():
            body = next((b for title, b in subsections if keyword in title), "")
            count = len(LIST_ITEM_RE.findall(body))
            if count < minimum:
                errors.append(f"P6_VALUES_TOO_FEW: {skill_md}: 价值取向「{keyword}」仅 {count} 条 < {minimum}")

    blind = _h2_body(content, "已知盲区")
    if blind is not None:
        items = list(re.finditer(r"^\d+\.\s", blind, re.MULTILINE))
        minimum = PACKAGE_SCHEMA["min_blind_spots"]
        if len(items) < minimum:
            errors.append(f"P6_BLIND_SPOTS_TOO_FEW: {skill_md}: 已知盲区仅 {len(items)} 条 < {minimum}")
        for i, item in enumerate(items):
            end = items[i + 1].start() if i + 1 < len(items) else len(blind)
            block = blind[item.start():end]
            # 最后一条的条目体止于章末的「**文化语境：**」「**不宜使用…**」，避免把后文字眼算进来。
            trailer = re.search(r"^\*\*(?:文化语境|不宜使用)", block, re.MULTILINE)
            if trailer:
                block = block[: trailer.start()]
            if not re.search(r"缓解|应对", block):
                errors.append(f"P6_BLIND_SPOT_NO_MITIGATION: {skill_md}: 第 {i + 1} 条盲区缺少缓解/应对建议")

    strategy = _h2_body(content, "响应策略")
    if strategy is not None:
        subsections = _h3_bodies(strategy)
        for keyword, minimum in PACKAGE_SCHEMA["response_min_rules"].items():
            body = next((b for title, b in subsections if keyword in title), None)
            count = len(LIST_ITEM_RE.findall(body)) if body is not None else 0
            if count < minimum:
                errors.append(
                    f"P6_RESPONSE_RULES_TOO_FEW: {skill_md}: 响应策略「{keyword}」仅 {count} 条 < {minimum}"
                )
    return errors


def check_template_residue(paths: list[Path]) -> list[str]:
    """规则 13：模板占位（{xxx}、{repeat_block}）不得残留在发布内容里。"""
    errors = []
    for path in paths:
        if not path.exists():
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = TEMPLATE_RESIDUE_RE.search(line)
            if match:
                errors.append(f"TEMPLATE_RESIDUE: {path}:{lineno}: 残留模板占位 {match.group(0)[:40]}")
    return errors


def check_strict_evidence(evidence_md: Path) -> list[str]:
    """S1：strict 下任何 confidence: low 的证据卡都不允许进入发布包。"""
    if not evidence_md.exists():
        return []
    errors = []
    for card in _load_provenance().parse_evidence_cards(evidence_md.read_text(encoding="utf-8")):
        level = CONFIDENCE_VALUE_RE.match(card["fields"].get("confidence", ""))
        if level and level.group(1) == "low":
            errors.append(f"STRICT_LOW_CONFIDENCE: {evidence_md} [{card['title']}]: confidence 为 low")
    return errors


def check_strict_review(review: dict | None, where: Path) -> list[str]:
    """S2/S3：strict 下审查结论必须是真审过的 PASS。"""
    if review is None:
        return [f"STRICT_NO_REVIEW: {where}: 没有审查记录"]
    if review.get("verdict") != "PASS":
        return [f"STRICT_REVIEW_NOT_PASS: {where}: 审查结论为 {review.get('verdict')!r}"]
    return []


def _non_space_len(text: str) -> int:
    return sum(1 for ch in text if not ch.isspace())


def check_quote_lengths(skill_md: Path, evidence_md: Path, voice_md: Path) -> list[str]:
    """伦理规则 L1：逐字引文不超过引用量级（核心层 / 证据卡 / 语感样本 / 证据合计）。"""
    limits = PACKAGE_SCHEMA["quote_max_chars"]
    prov = _load_provenance()
    errors: list[str] = []
    if skill_md.exists():
        for where, quote in prov.extract_skill_quotes(skill_md.read_text(encoding="utf-8")):
            n = _non_space_len(quote)
            if n > limits["core"]:
                errors.append(f"QUOTE_TOO_LONG_CORE: {skill_md} [{where}]: 引文 {n} 字，上限 {limits['core']}：{quote[:30]}…")
    if evidence_md.exists():
        total = 0
        for card in prov.parse_evidence_cards(evidence_md.read_text(encoding="utf-8")):
            n = _non_space_len(card["verbatim"])
            total += n
            if n > limits["evidence"]:
                errors.append(f"QUOTE_TOO_LONG_EVIDENCE: {evidence_md} [{card['title']}]: 原文 {n} 字，上限 {limits['evidence']}")
        if total > PACKAGE_SCHEMA["evidence_total_max_chars"]:
            errors.append(
                f"EVIDENCE_TOTAL_TOO_LONG: {evidence_md}: 证据原文合计 {total} 字，"
                f"上限 {PACKAGE_SCHEMA['evidence_total_max_chars']}——摘录过多已接近复制原书"
            )
    if voice_md.exists():
        text = voice_md.read_text(encoding="utf-8")
        blocks = VOICE_SPLIT_RE.split(text)[1:]
        for i, block in enumerate(blocks, 1):
            quote = "\n".join(m.group(1) for m in re.finditer(r"^>\s?(.*)$", block, re.MULTILINE))
            n = _non_space_len(quote)
            if n > limits["voice"]:
                errors.append(f"QUOTE_TOO_LONG_VOICE: {voice_md} [样本 {i}]: 原文 {n} 字，上限 {limits['voice']}")
    return errors


IDENTITY_YEARS_RE = re.compile(
    # 只许行内空白（[ \t]）：\s 会吞掉换行，把卒年为空的下一行内容误读成卒年。
    r"^\*\*[^*\n]+\*\*[ \t]*·[ \t]*(?:约|c\.[ \t]*)?(?:公元前|前)?(\d{1,4})[ \t]*年?[ \t]*[–—\-~～][ \t]*([^\n|·]*)",
    re.MULTILINE,
)
LIVING_MARKERS = {"", "至今", "今", "现在", "在世", "present", "now", "?", "？"}


def is_living_person(skill_text: str) -> bool:
    """身份卡生卒年的卒年为空或写「至今 / present」即视为在世人物。没有生卒年行时返回 False。"""
    match = IDENTITY_YEARS_RE.search(skill_text)
    return bool(match) and match.group(2).strip().lower() in LIVING_MARKERS


def check_living_person_notice(skill_md: Path) -> list[str]:
    """伦理规则 L2：在世人物的包必须声明「依据公开著述的研究性重建、不代表本人、不得冒充」。"""
    if not skill_md.exists():
        return []
    content = skill_md.read_text(encoding="utf-8")
    if not is_living_person(content):
        return []
    label = PACKAGE_SCHEMA["living_notice_label"]
    notice = re.search(rf"^\*\*{label}[：:]\*\*\s*(\S.*)$", content, re.MULTILINE)
    if notice is None:
        return [f"LIVING_PERSON_NOTICE_MISSING: {skill_md}: 在世人物须在身份卡写「**{label}：**……」"]
    missing = [w for w in ("公开", "不代表") if w not in notice.group(1)]
    if missing:
        return [f"LIVING_PERSON_NOTICE_INCOMPLETE: {skill_md}: 声明须说明依据「公开」著述且「不代表」本人，缺：{'、'.join(missing)}"]
    return []


def check_strict_rights(rights: dict | None, where: Path) -> list[str]:
    """S4：strict 下证据卡所在的每个语料文件都必须已登记、且权利状态在采集策略的 allowed_rights 里。"""
    if not isinstance(rights, dict) or not isinstance(rights.get("sources"), dict):
        return [f"STRICT_NO_RIGHTS_RECORD: {where}: 没有证据来源的权利记录（重跑 mdf index 生成 source_registry，再重新发布）"]
    acquire = _load_sibling("acquire")
    policy = acquire.load_policy()
    errors = []
    for rel, info in sorted(rights["sources"].items()):
        info = info if isinstance(info, dict) else {}
        status = info.get("rights_status") or "unregistered"
        if acquire.rights_decision(policy, status) != "allow" or info.get("rights_review_required"):
            errors.append(
                f"STRICT_RIGHTS_UNVERIFIED: {where}: 证据来源 {rel} 的权利状态为 {status}，"
                f"发布前须核实（在 sources/<slug>/rights.json 声明并重跑 mdf index）"
            )
    return errors


def validate_package(slug: str, strict: bool = False) -> list[str]:
    """构建期 v6 包校验（output/{slug}/）：结构 + P1–P6，P2 现场比对语料。

    strict 额外要求：无 confidence: low 的证据卡（S1），output/{slug}/review.md 结论为 PASS（S2）。
    """
    root = Path(".")
    output_dir = root / "output" / slug
    skill_md = output_dir / "SKILL.md"
    if not skill_md.exists():
        return [f"MISSING: {skill_md}"]

    errors: list[str] = []
    cluster_ids: list[str] = []
    core_file = output_dir / "framework_core.json"
    if not core_file.exists():
        # 硬性失败：cluster_ids 缺失会让按簇覆盖检查静默退化成空循环、不报任何错。
        errors.append(f"MISSING: {core_file}")
    else:
        try:
            core = read_json_file(core_file)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            errors.append(f"PARSE_ERROR: {core_file}: {e}")
        else:
            cluster_ids = [
                c.get("cluster_id") for c in core.get("principle_clusters", [])
                if c.get("cluster_id")
            ]
            if not cluster_ids:
                errors.append(
                    f"P4_EMPTY_CLUSTERS: {core_file}: principle_clusters 为空或均无 "
                    f"cluster_id，P4 的按簇覆盖检查无法执行"
                )

    errors.extend(_check_v6_package(output_dir, slug, root, cluster_ids, run_p2=True))
    if strict:
        review_md = output_dir / "review.md"
        evidence_md = output_dir / PACKAGE_SCHEMA["reference_dir"] / "evidence.md"
        pm = _load_sibling("package_manifest")
        errors.extend(check_strict_evidence(evidence_md))
        errors.extend(check_strict_review(pm.read_review_verdict(review_md), review_md))
        errors.extend(check_strict_rights(pm.evidence_rights(evidence_md, slug, root, _load_provenance()), evidence_md))
    return errors


def validate_published(slug: str, root: Path = Path("."), strict: bool = False) -> list[str]:
    """发布后校验（gallery/{slug}/）：只依赖包内文件 + manifest，不读 output/ 与 sources/。

    legacy 与 v6 一视同仁：都必须有 v2 manifest 且文件 hash 全部吻合。v6 额外重跑
    P1/P3–P6；P4 的簇列表取自 manifest，P2 不重跑（语料不随包发布），改由
    manifest 里的构建期证明担保——evidence.md 的 hash 与证明一致，证明才算数。
    """
    errors = check_published_package(root / "gallery" / slug, slug, root, strict=strict)
    errors.extend(_check_gallery_index_entry(slug, root))
    return errors


# 旧名保留：commands/、agents/ 与文档里都写的是 `gallery` 阶段。
validate_gallery = validate_published


def check_published_package(
    package_dir: Path, slug: str, root: Path = Path("."), strict: bool = False
) -> list[str]:
    """对任意目录做发布包校验（不查 index）。publish_skill.py 用它校验暂存目录。

    strict 额外要求：无 confidence: low 的证据卡（S1），manifest 有审查记录（S3）且为 PASS（S2）。
    legacy 包同样适用 S2/S3。
    """
    skill_md = package_dir / "SKILL.md"
    if not skill_md.exists():
        return [f"MISSING: {skill_md}"]

    pm = _load_sibling("package_manifest")
    v6 = is_v6_skill(skill_md.read_text(encoding="utf-8"))
    manifest, errors = pm.load_manifest(package_dir / pm.MANIFEST_NAME)
    clusters: list[str] = []
    if manifest is not None:
        errors.extend(pm.verify_manifest(package_dir, manifest, slug))
        expected = PACKAGE_SCHEMA["format_version"] if v6 else 1
        if manifest.get("format_version") != expected:
            errors.append(
                f"MANIFEST_FORMAT_MISMATCH: {package_dir / pm.MANIFEST_NAME}: "
                f"format_version={manifest.get('format_version')!r}，SKILL.md 实际为 {expected}"
            )
        if isinstance(manifest.get("clusters"), list):
            clusters = [c for c in manifest["clusters"] if isinstance(c, str) and c]

    if v6:
        errors.extend(_check_v6_package(package_dir, slug, root, clusters, run_p2=False))
    else:
        errors.extend(_validate_merged_skill(skill_md, slug))

    if strict:
        if v6:
            errors.extend(check_strict_evidence(package_dir / PACKAGE_SCHEMA["reference_dir"] / "evidence.md"))
            attestation = (manifest or {}).get("attestation") or {}
            rights = (attestation.get("p2") or {}).get("rights") if isinstance(attestation, dict) else None
            errors.extend(check_strict_rights(rights, package_dir / pm.MANIFEST_NAME))
        errors.extend(check_strict_review(manifest.get("review") if manifest else None, package_dir / pm.MANIFEST_NAME))
    return errors


def _check_gallery_index_entry(slug: str, root: Path = Path(".")) -> list[str]:
    index_file = root / "gallery" / "index.json"
    if not index_file.exists():
        return [f"MISSING: {index_file}"]
    try:
        index = read_json_file(index_file)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        return [f"PARSE_ERROR: {index_file}: {e}"]
    entry = next((e for e in index.get("skills", []) if e.get("slug") == slug), None)
    if not entry:
        return [f"MISSING_GALLERY_INDEX_ENTRY: {index_file}: slug='{slug}'"]
    if entry.get("skill_dir") != f"gallery/{slug}/":
        return [f"INVALID_GALLERY_INDEX_ENTRY: {index_file}: skill_dir='{entry.get('skill_dir')}'"]
    return []


def _check_v6_package(
    package_dir: Path, slug: str, root: Path, cluster_ids: list[str], *, run_p2: bool
) -> list[str]:
    """v6 包本体检查，构建期与发布后共用。

    run_p2=False 时跳过 P2（发布后无语料），由调用方核对 manifest 的构建期证明。
    """
    skill_md = package_dir / "SKILL.md"
    refs_dir = package_dir / PACKAGE_SCHEMA["reference_dir"]
    errors: list[str] = []

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
    errors.extend(check_p6_structure(skill_md))

    cases_md = refs_dir / "cases.md"
    evidence_md = refs_dir / "evidence.md"
    voice_md = refs_dir / "voice.md"

    if cases_md.exists():
        errors.extend(check_p4_cases(cases_md, cluster_ids))
        errors.extend(check_p5_index(skill_md, cases_md))

    if evidence_md.exists():
        prov = _load_provenance()
        errors.extend(check_evidence_cards(evidence_md, skill_md))
        errors.extend(prov.check_p1_quote_closure(skill_md, evidence_md))
        if run_p2:
            errors.extend(prov.check_p2_corpus_closure(evidence_md, slug, root))

    if voice_md.exists():
        errors.extend(check_voice_samples(voice_md))

    errors.extend(check_quote_lengths(skill_md, evidence_md, voice_md))
    errors.extend(check_living_person_notice(skill_md))
    errors.extend(check_template_residue([skill_md, cases_md, evidence_md, voice_md]))
    return errors


@functools.lru_cache(maxsize=None)
def _load_sibling(name: str):
    """按路径加载同目录的模块（scripts/ 不是包）。

    缓存：verify_provenance 在模块加载时构造 OpenCC 转换器，开销不小；一次校验会
    多处调用，每次重新执行模块会让整套校验慢上一倍。
    """
    import importlib.util
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_provenance():
    return _load_sibling("verify_provenance")


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
    "published": validate_published,
    "gallery": validate_published,
}

STRICT_STAGES = {"package", "published", "gallery"}


def main():
    args = [a for a in sys.argv[1:] if a != "--strict"]
    strict = len(args) != len(sys.argv) - 1
    if len(args) < 2:
        print(f"Usage: python {sys.argv[0]} <stage> <person-slug> [--strict]")
        print(f"Stages: {', '.join(STAGES.keys())}")
        sys.exit(1)

    stage = args[0]
    try:
        slug = _load_sibling("slug_rules").validate_slug(args[1])
    except ValueError as e:  # InvalidSlug 是 ValueError 子类
        print(f"Invalid slug: {e}")
        sys.exit(1)

    if stage not in STAGES:
        print(f"Unknown stage: {stage}. Available: {', '.join(STAGES.keys())}")
        sys.exit(1)
    if strict and stage not in STRICT_STAGES:
        print(f"--strict 仅适用于 {', '.join(sorted(STRICT_STAGES))} 阶段")
        sys.exit(1)

    print(f"Validating stage '{stage}' for '{slug}'{' (strict)' if strict else ''}...")
    errors = STAGES[stage](slug, strict=True) if strict else STAGES[stage](slug)

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
