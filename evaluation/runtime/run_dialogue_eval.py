#!/usr/bin/env python3
"""Run or import runtime dialogue evaluations for Mind Distill Factory skills.

This module is independent from the /distill workflow. It writes only under the
requested reports directory and never writes into output/, gallery/, sources/,
commands/, or agents/.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_MODEL = "deepseek-v4-pro"
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_ENV_FILE = Path("evaluation/runtime/.env")
LLM_MODE_VALUES = {"auto", "off", "deepseek"}
TEN_QUESTION_MODE_VALUES = {"auto", "off", "on"}
SOUL_QUESTION_SCHEMA_VERSION = "MindDistillSoulQuestions-v1"
SOUL_APPENDIX_NOTICE = "This appendix is not part of SkillEval-MDF benchmark scoring."
SOUL_SUMMARY_HEADINGS = [
    "\u6574\u4f53\u5370\u8c61",
    "\u6700\u80fd\u663e\u51fa\u7075\u9b42\u7684\u56de\u7b54",
    "\u503c\u5f97\u7528\u6237\u81ea\u884c\u5224\u65ad\u7684\u5730\u65b9",
    "\u53ef\u80fd\u7684\u4e0d\u9002\u6216\u76f2\u70b9",
    "\u7ed9\u7528\u6237\u7684\u81ea\u8bc4\u63d0\u793a",
]
SOUL_QUESTION_ARCHETYPES = [
    {
        "id": "regret",
        "description": "Ask about a historically grounded regret, limitation, or unresolved personal failure.",
    },
    {
        "id": "alternate_historical_road",
        "description": "Ask the thinker to imagine one plausible alternate road inside their historical constraints.",
    },
    {
        "id": "principle_life_contradiction",
        "description": "Ask about a tension between an endorsed principle and the thinker's lived choices.",
    },
    {
        "id": "hardest_compromise",
        "description": "Ask about the hardest compromise, concession, or survival bargain they made.",
    },
    {
        "id": "most_misunderstood_principle",
        "description": "Ask about the principle later readers most easily simplify or misuse.",
    },
    {
        "id": "decisive_moment",
        "description": "Ask about one decisive moment that reveals the method under pressure.",
    },
    {
        "id": "unique_personality_wisdom",
        "description": "Ask a question that surfaces the thinker's distinctive personality-shaped wisdom.",
    },
    {
        "id": "warning_against_imitation",
        "description": "Ask what users should not imitate even if they admire the thinker.",
    },
    {
        "id": "modern_use_boundary",
        "description": "Ask how to use the method today without pretending the thinker personally witnessed the present.",
    },
    {
        "id": "final_self_judgment",
        "description": "Ask the thinker for a final self-judgment that leaves room for the reader's own evaluation.",
    },
]


def load_env_file(path: Path, *, override: bool = False) -> bool:
    if not path.exists():
        return False
    if not path.is_file():
        raise ValueError(f"Env path is not a file: {path}")

    text = path.read_text(encoding="utf-8-sig")
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            raise ValueError(f"Invalid env line {line_number} in {path}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"Invalid env line {line_number} in {path}: empty key")
        if override or key not in os.environ:
            os.environ[key] = parse_env_value(value.strip())
    return True


def parse_env_value(value: str) -> str:
    if not value:
        return ""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def env_value(*names: str, default: str | None = None) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value is not None and value != "":
            return value
    return default


def normalize_llm_mode(raw: str | None) -> str:
    value = (raw or "auto").strip().lower()
    if value in {"0", "false", "no", "none", "disabled"}:
        return "off"
    if value in {"1", "true", "yes", "on"}:
        return "auto"
    if value not in LLM_MODE_VALUES:
        raise ValueError(f"Invalid LLM mode '{raw}'. Expected one of: auto, off, deepseek")
    return value


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


def read_json(path: Path) -> Any:
    return json.loads(read_text(path))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def find_skill_path(root: Path, slug: str, explicit: str | None = None) -> Path:
    if explicit:
        return (root / explicit).resolve() if not Path(explicit).is_absolute() else Path(explicit)
    output_skill = root / "output" / slug / "SKILL.md"
    gallery_skill = root / "gallery" / slug / "SKILL.md"
    if output_skill.exists():
        return output_skill
    return gallery_skill


def deepseek_chat(
    *,
    api_key: str,
    base_url: str,
    model: str,
    messages: list[dict[str, str]],
    reasoning_effort: str,
    json_mode: bool = False,
    max_tokens: int | None = None,
    retries: int = 2,
) -> dict[str, Any]:
    endpoint = base_url.rstrip("/") + "/chat/completions"
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "reasoning_effort": reasoning_effort,
        "thinking": {"type": "enabled"},
    }
    if max_tokens:
        body["max_tokens"] = max_tokens
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        request = urllib.request.Request(endpoint, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            last_error = RuntimeError(f"DeepSeek HTTP {exc.code}: {detail}")
        except Exception as exc:  # pragma: no cover - network dependent
            last_error = exc
        if attempt < retries:
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(str(last_error))


def assistant_content(response: dict[str, Any]) -> str:
    choices = response.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    # Intentionally ignore reasoning_content. Runtime records must contain only
    # user-visible final answers.
    return (message.get("content") or "").strip()


def build_system_prompt(skill_text: str) -> str:
    return (
        "You are executing the following Mind Distill Factory SKILL.md. "
        "Follow it as the active instruction for every answer. "
        "Answer the user's language. Do not reveal hidden reasoning.\n\n"
        "===== SKILL.md =====\n"
        f"{skill_text}\n"
        "===== END SKILL.md ====="
    )


def run_generation(
    *,
    api_key: str,
    base_url: str,
    model: str,
    reasoning_effort: str,
    skill_text: str,
    cases: list[dict[str, Any]],
    limit: int | None = None,
) -> list[dict[str, Any]]:
    messages: list[dict[str, str]] = [{"role": "system", "content": build_system_prompt(skill_text)}]
    records: list[dict[str, Any]] = []
    selected_cases = cases[:limit] if limit else cases
    for idx, case in enumerate(selected_cases, start=1):
        prompt = case["prompt"]
        messages.append({"role": "user", "content": prompt})
        response = deepseek_chat(
            api_key=api_key,
            base_url=base_url,
            model=model,
            messages=messages,
            reasoning_effort=reasoning_effort,
            max_tokens=2500,
        )
        answer = assistant_content(response)
        messages.append({"role": "assistant", "content": answer})
        records.append({
            "case_number": idx,
            "case_id": case.get("id"),
            "title": case.get("title"),
            "category": case.get("category"),
            "question": prompt,
            "answer": answer,
            "source": "generated",
        })
    return records


def parse_legacy_dialogues(paths: list[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in paths:
        text = read_text(path)
        pairs = extract_qa_pairs(text)
        for question, answer in pairs:
            records.append({
                "case_number": len(records) + 1,
                "case_id": f"imported_{len(records) + 1:02d}",
                "title": "Imported Dialogue",
                "category": "imported",
                "question": question.strip(),
                "answer": answer.strip(),
                "source": "imported",
                "source_path": str(path),
            })
    return records


def extract_qa_pairs(text: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    current_q: list[str] = []
    current_a: list[str] = []
    state: str | None = None

    def marker(line: str) -> tuple[str, str] | None:
        stripped = line.strip()
        bold = re.match(r"^\*\*([QA]):\*\*\s*(.*)$", stripped, re.IGNORECASE)
        if bold:
            return bold.group(1).upper(), bold.group(2)
        legacy = re.match(r"^(?:#+\s*)?\*{0,3}([QA])\*{0,3}\s*:?\s*(.*)$", stripped, re.IGNORECASE)
        if legacy:
            return legacy.group(1).upper(), legacy.group(2)
        return None

    for line in text.splitlines():
        found = marker(line)
        if found:
            kind, rest = found
            if kind == "Q":
                if current_q and current_a:
                    pairs.append((strip_wrapping_quotes("\n".join(current_q).strip()), "\n".join(current_a).strip()))
                current_q = [rest] if rest else []
                current_a = []
                state = "Q"
            else:
                current_a = [rest] if rest else []
                state = "A"
            continue
        if state == "Q":
            current_q.append(line)
        elif state == "A":
            current_a.append(line)
    if current_q and current_a:
        pairs.append((strip_wrapping_quotes("\n".join(current_q).strip()), "\n".join(current_a).strip()))
    return pairs


def strip_wrapping_quotes(text: str) -> str:
    text = text.strip()
    quote_chars = "\"'“”‘’"
    if len(text) >= 2 and text[0] in quote_chars and text[-1] in quote_chars:
        return text[1:-1].strip()
    return text


def records_from_pairs(
    pairs: list[tuple[str, str]],
    cases: list[dict[str, Any]],
    *,
    source: str,
    source_path: Path | None = None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for idx, (question, answer) in enumerate(pairs, start=1):
        case = cases[idx - 1] if idx - 1 < len(cases) else {}
        records.append({
            "case_number": idx,
            "case_id": case.get("id") or f"{source}_{idx:02d}",
            "title": case.get("title") or "Imported Dialogue",
            "category": case.get("category") or source,
            "question": question.strip(),
            "answer": answer.strip(),
            "source": source,
            "source_path": str(source_path) if source_path else None,
        })
    return records


def render_dialogue_markdown(
    *,
    slug: str,
    model: str,
    reasoning_effort: str,
    records: list[dict[str, Any]],
    source: str,
) -> str:
    lines = [
        f"# Dialogue Test Set - {slug}",
        "",
        f"Model: {model}",
        f"Reasoning Effort: {reasoning_effort}",
        f"Date: {dt.date.today().isoformat()}",
        f"Source: {source}",
        "",
    ]
    for idx, record in enumerate(records, start=1):
        title = record.get("title") or record.get("category") or "Dialogue"
        lines.extend([
            f"## Case {idx:02d} - {title}",
            "",
            f"**Q:** {record.get('question', '').strip()}",
            "",
            f"**A:** {record.get('answer', '').strip()}",
            "",
        ])
    return "\n".join(lines).rstrip() + "\n"


def build_judge_prompt(
    *,
    skill_text: str,
    rubric: dict[str, Any],
    records: list[dict[str, Any]],
    standard_case_count: int,
) -> str:
    judge_input = {
        "rubric": rubric,
        "standard_case_count": standard_case_count,
        "records": records,
    }
    return (
        "You are a strict evaluator for Mind Distill Factory runtime dialogue tests. "
        "Score each case using the rubric. Penalize overconfident ratings. "
        "A good single answer does not prove stability across the set. "
        "Return ONLY valid JSON with English keys using this shape: "
        "{\"schema_version\":\"MindDistillRuntimeJudgment-v1\","
        "\"case_judgments\":[{\"case_id\":\"...\",\"scores\":{...},"
        "\"failure_flags\":[],\"severity\":\"none|P2|P1|P0\",\"notes\":\"...\"}],"
        "\"aggregate\":{\"runtime_score_25\":0,\"coverage\":\"standard|partial|imported\","
        "\"p0_count\":0,\"p1_count\":0,\"summary\":\"...\"}}.\n\n"
        "Do not include chain of thought.\n\n"
        "===== TARGET SKILL.md =====\n"
        f"{skill_text[:60000]}\n"
        "===== END TARGET SKILL.md =====\n\n"
        "===== JUDGE INPUT =====\n"
        f"{json.dumps(judge_input, ensure_ascii=False)}\n"
        "===== END JUDGE INPUT ====="
    )


def parse_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


def judge_records(
    *,
    api_key: str,
    base_url: str,
    model: str,
    reasoning_effort: str,
    skill_text: str,
    rubric: dict[str, Any],
    records: list[dict[str, Any]],
    standard_case_count: int,
) -> dict[str, Any]:
    prompt = build_judge_prompt(
        skill_text=skill_text,
        rubric=rubric,
        records=records,
        standard_case_count=standard_case_count,
    )
    response = deepseek_chat(
        api_key=api_key,
        base_url=base_url,
        model=model,
        messages=[
            {"role": "system", "content": "You are a strict JSON-only evaluation judge."},
            {"role": "user", "content": prompt},
        ],
        reasoning_effort=reasoning_effort,
        json_mode=True,
        max_tokens=12000,
    )
    content = assistant_content(response)
    if not content:
        response = deepseek_chat(
            api_key=api_key,
            base_url=base_url,
            model=model,
            messages=[
                {"role": "system", "content": "You are a strict JSON-only evaluation judge. Return compact valid JSON."},
                {"role": "user", "content": prompt},
            ],
            reasoning_effort=reasoning_effort,
            json_mode=True,
            max_tokens=16000,
        )
        content = assistant_content(response)
    try:
        judgment = parse_json_object(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError("DeepSeek judge did not return parseable JSON final content.") from exc
    judgment.setdefault("schema_version", "MindDistillRuntimeJudgment-v1")
    judgment.setdefault("metadata", {})
    judgment["metadata"].update({
        "model": model,
        "reasoning_effort": reasoning_effort,
        "judged_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    })
    return judgment


def skipped_judgment(*, reason: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "MindDistillRuntimeJudgment-v1",
        "metadata": {
            "judge_skipped": True,
            "reason": reason,
            "judged_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        },
        "case_judgments": [],
        "aggregate": {
            "runtime_score_25": None,
            "coverage": "imported" if any(r.get("source") == "imported" for r in records) else "partial",
            "p0_count": None,
            "p1_count": None,
            "summary": reason,
        },
    }


def render_runtime_evaluation(slug: str, records: list[dict[str, Any]], judgment: dict[str, Any]) -> str:
    aggregate = judgment.get("aggregate") or {}
    lines = [
        f"# Runtime Evaluation - {slug}",
        "",
        f"Runtime Score: `{aggregate.get('runtime_score_25')}` / 25",
        f"Coverage: `{aggregate.get('coverage')}`",
        f"P0 Count: `{aggregate.get('p0_count')}`",
        f"P1 Count: `{aggregate.get('p1_count')}`",
        "",
        "## Summary",
        "",
        str(aggregate.get("summary") or "No summary provided."),
        "",
        "## Case Judgments",
        "",
        "| Case | Category | Severity | Key Flags | Notes |",
        "|---|---|---|---|---|",
    ]
    judgments = {item.get("case_id"): item for item in judgment.get("case_judgments", [])}
    for idx, record in enumerate(records, start=1):
        item = judgments.get(record.get("case_id"), {})
        flags = ", ".join(item.get("failure_flags") or [])
        notes = str(item.get("notes") or "").replace("|", "\\|")
        lines.append(
            f"| {idx:02d} | {record.get('category')} | {item.get('severity', 'not_judged')} | {flags or 'none'} | {notes} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def truncate_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]..."


def collect_soul_context(root: Path, slug: str, skill_text: str) -> dict[str, Any]:
    output_dir = root / "output" / slug
    context: dict[str, Any] = {
        "slug": slug,
        "skill_excerpt": truncate_text(skill_text, 50000),
        "frameworks": {},
        "principle_files": [],
        "review_excerpt": "",
    }
    for name in ["framework_core.json", "frameworks.zh.json", "frameworks.en.json"]:
        path = output_dir / name
        text = read_text(path)
        if text:
            context["frameworks"][name] = truncate_text(text, 18000)
    for path in sorted(output_dir.glob("principles_*.json")):
        text = read_text(path)
        if text:
            context["principle_files"].append({
                "path": str(path),
                "content_excerpt": truncate_text(text, 12000),
            })
    review_text = read_text(output_dir / "review.md")
    if review_text:
        context["review_excerpt"] = truncate_text(review_text, 8000)
    return context


def build_soul_question_prompt(*, slug: str, language: str, context: dict[str, Any]) -> str:
    question_shape = {
        "questions": [
            {
                "id": "Q01",
                "archetype": SOUL_QUESTION_ARCHETYPES[0]["id"],
                "question": "...",
                "why_this_question": "...",
                "principle_or_source_anchor": "...",
            }
        ]
    }
    return (
        "Generate a non-benchmark 'Soul Ten Questions' appendix for a Mind Distill Factory thinker skill.\n"
        "The appendix is for human judgment after the scored runtime test. It must not mention scores, grades, "
        "benchmark readiness, or numeric evaluation.\n\n"
        f"Slug: {slug}\n"
        f"Language code: {language}\n"
        "If the language code is zh, write all question-facing fields in natural Chinese. Otherwise use English.\n\n"
        "Generate exactly 10 questions in this exact archetype order. Tailor every question to the target thinker; "
        "avoid generic philosophy prompts. Each question should ask the thinker directly, using a respectful interview "
        "tone. Use specific works, events, principles, tensions, or source anchors from the supplied context. Do not "
        "invent quotes or pretend a historical thinker witnessed events after their death.\n\n"
        "===== ARCHETYPES =====\n"
        f"{json.dumps(SOUL_QUESTION_ARCHETYPES, ensure_ascii=False, indent=2)}\n"
        "===== END ARCHETYPES =====\n\n"
        "Return ONLY valid JSON in this shape. Do not answer the questions.\n"
        f"{json.dumps(question_shape, ensure_ascii=False, indent=2)}\n\n"
        "===== TARGET CONTEXT =====\n"
        f"{json.dumps(context, ensure_ascii=False)}\n"
        "===== END TARGET CONTEXT ====="
    )


def normalize_soul_questions(data: Any) -> list[dict[str, Any]]:
    raw_questions = data.get("questions") if isinstance(data, dict) else data
    if not isinstance(raw_questions, list):
        raise RuntimeError("DeepSeek soul-question generator did not return a questions list.")
    if len(raw_questions) != len(SOUL_QUESTION_ARCHETYPES):
        raise RuntimeError(
            f"Expected {len(SOUL_QUESTION_ARCHETYPES)} soul questions, got {len(raw_questions)}."
        )

    normalized: list[dict[str, Any]] = []
    for idx, (raw_item, archetype) in enumerate(zip(raw_questions, SOUL_QUESTION_ARCHETYPES), start=1):
        if not isinstance(raw_item, dict):
            raise RuntimeError(f"Soul question Q{idx:02d} is not an object.")
        question = str(raw_item.get("question") or "").strip()
        why = str(raw_item.get("why_this_question") or "").strip()
        anchor = str(raw_item.get("principle_or_source_anchor") or "").strip()
        if not question or not why or not anchor:
            raise RuntimeError(
                f"Soul question Q{idx:02d} must include question, why_this_question, and principle_or_source_anchor."
            )
        normalized.append({
            "id": f"Q{idx:02d}",
            "archetype": archetype["id"],
            "archetype_description": archetype["description"],
            "question": question,
            "why_this_question": why,
            "principle_or_source_anchor": anchor,
        })
    return normalized


def generate_soul_questions(
    *,
    api_key: str,
    base_url: str,
    model: str,
    reasoning_effort: str,
    root: Path,
    slug: str,
    skill_text: str,
    language: str,
) -> list[dict[str, Any]]:
    prompt = build_soul_question_prompt(
        slug=slug,
        language=language,
        context=collect_soul_context(root, slug, skill_text),
    )
    response = deepseek_chat(
        api_key=api_key,
        base_url=base_url,
        model=model,
        messages=[
            {"role": "system", "content": "You generate strict JSON for a non-scored evaluation appendix."},
            {"role": "user", "content": prompt},
        ],
        reasoning_effort=reasoning_effort,
        json_mode=True,
        max_tokens=7000,
    )
    content = assistant_content(response)
    if not content:
        raise RuntimeError("DeepSeek soul-question generator returned empty content.")
    return normalize_soul_questions(parse_json_object(content))


def answer_soul_questions(
    *,
    api_key: str,
    base_url: str,
    model: str,
    reasoning_effort: str,
    skill_text: str,
    questions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    system_prompt = (
        build_system_prompt(skill_text)
        + "\n\nYou are answering one independent Soul Ten Questions appendix item. "
        "Treat each item as a standalone exchange. Do not reference other appendix questions. "
        "Do not reveal hidden reasoning."
    )
    records: list[dict[str, Any]] = []
    for question in questions:
        response = deepseek_chat(
            api_key=api_key,
            base_url=base_url,
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question["question"]},
            ],
            reasoning_effort=reasoning_effort,
            max_tokens=3500,
        )
        answer = assistant_content(response)
        if not answer:
            raise RuntimeError(f"DeepSeek returned an empty answer for {question['id']}.")
        item = dict(question)
        item["answer"] = answer
        item["model_metadata"] = {
            "question_model": model,
            "answer_model": model,
            "reasoning_effort": reasoning_effort,
        }
        records.append(item)
    return records


def build_soul_summary_prompt(*, slug: str, language: str, records: list[dict[str, Any]]) -> str:
    compact_records = []
    for record in records:
        compact_records.append({
            "id": record["id"],
            "archetype": record["archetype"],
            "question": record["question"],
            "why_this_question": record["why_this_question"],
            "principle_or_source_anchor": record["principle_or_source_anchor"],
            "answer_excerpt": truncate_text(record["answer"], 2500),
        })
    headings = [f"## {heading}" for heading in SOUL_SUMMARY_HEADINGS]
    return (
        "Write a brief subjective reading note for a non-benchmark Soul Ten Questions appendix.\n"
        "Do not give a numeric score, grade, ranking, benchmark label, pass/fail verdict, or release recommendation. "
        "The purpose is to leave space for the user to judge the skill alone.\n\n"
        f"Slug: {slug}\n"
        f"Language code: {language}\n"
        "Use Chinese if the language code is zh; otherwise use English, but keep the five section headings exactly.\n\n"
        "Use exactly these Markdown section headings in this order:\n"
        + "\n".join(headings)
        + "\n\n===== QUESTION AND ANSWER RECORDS =====\n"
        + json.dumps(compact_records, ensure_ascii=False)
        + "\n===== END RECORDS ====="
    )


def default_soul_summary() -> str:
    body = [
        "This appendix is for the user's private reading judgment and is not scored.",
        "Look for whether the answer reveals a living method rather than a generic persona.",
        "Notice where the response feels historically anchored and where it may still feel too smooth.",
        "Any discomfort or blind spot should be treated as evidence for further human review.",
        "Read one answer slowly and decide whether it changed how you would use the skill.",
    ]
    lines: list[str] = []
    for heading, paragraph in zip(SOUL_SUMMARY_HEADINGS, body):
        lines.extend([f"## {heading}", "", paragraph, ""])
    return "\n".join(lines).rstrip()


def ensure_soul_summary_headings(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return default_soul_summary()
    if all(f"## {heading}" in stripped for heading in SOUL_SUMMARY_HEADINGS):
        return stripped
    return default_soul_summary()


def generate_soul_summary(
    *,
    api_key: str,
    base_url: str,
    model: str,
    reasoning_effort: str,
    slug: str,
    language: str,
    records: list[dict[str, Any]],
) -> str:
    response = deepseek_chat(
        api_key=api_key,
        base_url=base_url,
        model=model,
        messages=[
            {"role": "system", "content": "You write concise human-facing evaluation notes without scores."},
            {"role": "user", "content": build_soul_summary_prompt(slug=slug, language=language, records=records)},
        ],
        reasoning_effort=reasoning_effort,
        max_tokens=3000,
    )
    return ensure_soul_summary_headings(assistant_content(response))


def render_soul_markdown(
    *,
    slug: str,
    model: str,
    reasoning_effort: str,
    generated_at: str,
    records: list[dict[str, Any]],
) -> str:
    lines = [
        f"# Soul Ten Questions Q/A - {slug}",
        "",
        SOUL_APPENDIX_NOTICE,
        "",
        f"Schema: `{SOUL_QUESTION_SCHEMA_VERSION}`",
        "Benchmark Included: `false`",
        f"Model: `{model}`",
        f"Reasoning Effort: `{reasoning_effort}`",
        f"Generated At: `{generated_at}`",
        "",
    ]
    for record in records:
        lines.extend([
            f"## {record['id']} - {record['archetype']}",
            "",
            f"Anchor: `{record['principle_or_source_anchor']}`",
            "",
            f"Why this question: {record['why_this_question']}",
            "",
            f"**Q:** {record['question']}",
            "",
            f"**A:** {record['answer']}",
            "",
        ])
    return "\n".join(lines).rstrip() + "\n"


def render_soul_summary_markdown(*, slug: str, summary: str) -> str:
    return "\n".join([
        f"# Soul Ten Questions Summary - {slug}",
        "",
        SOUL_APPENDIX_NOTICE,
        "",
        ensure_soul_summary_headings(summary),
        "",
    ])


def run_soul_appendix(
    *,
    api_key: str,
    base_url: str,
    model: str,
    reasoning_effort: str,
    root: Path,
    slug: str,
    skill_path: Path,
    skill_text: str,
    language: str,
    out_dir: Path,
) -> dict[str, Path]:
    generated_at = dt.datetime.now(dt.timezone.utc).isoformat()
    questions = generate_soul_questions(
        api_key=api_key,
        base_url=base_url,
        model=model,
        reasoning_effort=reasoning_effort,
        root=root,
        slug=slug,
        skill_text=skill_text,
        language=language,
    )
    records = answer_soul_questions(
        api_key=api_key,
        base_url=base_url,
        model=model,
        reasoning_effort=reasoning_effort,
        skill_text=skill_text,
        questions=questions,
    )
    summary = generate_soul_summary(
        api_key=api_key,
        base_url=base_url,
        model=model,
        reasoning_effort=reasoning_effort,
        slug=slug,
        language=language,
        records=records,
    )

    payload = {
        "schema_version": SOUL_QUESTION_SCHEMA_VERSION,
        "benchmark_included": False,
        "metadata": {
            "slug": slug,
            "skill_path": str(skill_path),
            "model": model,
            "reasoning_effort": reasoning_effort,
            "language": language,
            "generated_at": generated_at,
            "mode": "hybrid_archetype_deepseek_tailored",
            "notice": SOUL_APPENDIX_NOTICE,
        },
        "archetypes": SOUL_QUESTION_ARCHETYPES,
        "questions": records,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "ten-question-qa.json"
    md_path = out_dir / "ten-question-qa.md"
    summary_path = out_dir / "ten-question-summary.md"
    write_json(json_path, payload)
    md_path.write_text(
        render_soul_markdown(
            slug=slug,
            model=model,
            reasoning_effort=reasoning_effort,
            generated_at=generated_at,
            records=records,
        ),
        encoding="utf-8",
    )
    summary_path.write_text(render_soul_summary_markdown(slug=slug, summary=summary), encoding="utf-8")
    return {
        "json": json_path,
        "markdown": md_path,
        "summary": summary_path,
    }


def should_run_soul_questions(
    *,
    ten_questions: str,
    source: str,
    smoke: bool,
    limit: int | None,
    import_existing: bool,
    judge_existing_runtime: bool,
    record_count: int,
    standard_case_count: int,
) -> bool:
    if ten_questions == "off":
        return False
    if ten_questions == "on":
        return True
    return (
        source == "generated"
        and not smoke
        and limit is None
        and not import_existing
        and not judge_existing_runtime
        and standard_case_count > 0
        and record_count == standard_case_count
    )


def main(argv: list[str] | None = None) -> int:
    env_parser = argparse.ArgumentParser(add_help=False)
    env_parser.add_argument("--root", default=".")
    env_parser.add_argument("--env-file")
    env_parser.add_argument("--no-env-file", action="store_true")
    env_args, _ = env_parser.parse_known_args(argv)

    root_for_env = Path(env_args.root).resolve()
    loaded_env_file: Path | None = None
    if not env_args.no_env_file:
        env_path = Path(env_args.env_file) if env_args.env_file else root_for_env / DEFAULT_ENV_FILE
        if not env_path.is_absolute():
            env_path = root_for_env / env_path
        if load_env_file(env_path):
            loaded_env_file = env_path

    try:
        default_llm_mode = normalize_llm_mode(env_value("MIND_DISTILL_EVAL_LLM", default="auto"))
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", required=True)
    parser.add_argument("--root", default=".")
    parser.add_argument("--env-file", help="Load evaluation runtime variables from this file before reading defaults.")
    parser.add_argument("--no-env-file", action="store_true", help="Do not load evaluation/runtime/.env.")
    parser.add_argument("--out-dir")
    parser.add_argument("--skill-path")
    parser.add_argument("--test-set", default="evaluation/runtime/test_sets/mind_distill_standard_zh.json")
    parser.add_argument("--judge-rubric", default="evaluation/runtime/judge_rubric.json")
    parser.add_argument("--llm", choices=sorted(LLM_MODE_VALUES), default=default_llm_mode)
    parser.add_argument("--model", default=env_value("MIND_DISTILL_EVAL_MODEL", "DEEPSEEK_MODEL", default=DEFAULT_MODEL))
    parser.add_argument(
        "--reasoning-effort",
        default=env_value("MIND_DISTILL_EVAL_REASONING_EFFORT", "DEEPSEEK_REASONING_EFFORT", default="max"),
    )
    parser.add_argument(
        "--base-url",
        default=env_value("MIND_DISTILL_EVAL_BASE_URL", "DEEPSEEK_BASE_URL", default=DEFAULT_BASE_URL),
    )
    parser.add_argument("--limit", type=int)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--import-existing", action="store_true")
    parser.add_argument("--judge-existing-runtime", action="store_true")
    parser.add_argument("--no-judge", action="store_true")
    parser.add_argument(
        "--ten-questions",
        choices=sorted(TEN_QUESTION_MODE_VALUES),
        default="auto",
        help=(
            "Generate the non-benchmark Soul Ten Questions appendix. "
            "auto runs only after a full generated runtime test; on forces it; off disables it."
        ),
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    out_dir = Path(args.out_dir) if args.out_dir else root / "evaluation" / "reports" / args.slug
    if not out_dir.is_absolute():
        out_dir = root / out_dir

    test_set = read_json(root / args.test_set)
    rubric = read_json(root / args.judge_rubric)
    cases = test_set.get("cases", [])
    limit = 1 if args.smoke else args.limit
    skill_path = find_skill_path(root, args.slug, args.skill_path)
    skill_text = read_text(skill_path)
    if not skill_text:
        print(f"ERROR: SKILL.md not found for slug '{args.slug}' at {skill_path}", file=sys.stderr)
        return 2

    try:
        llm_mode = normalize_llm_mode(args.llm)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    llm_enabled = llm_mode != "off"
    api_key = env_value("MIND_DISTILL_EVAL_API_KEY", "DEEPSEEK_API_KEY") if llm_enabled else None
    if args.ten_questions == "on" and not api_key:
        print(
            "ERROR: --ten-questions on requires MIND_DISTILL_EVAL_API_KEY or DEEPSEEK_API_KEY.",
            file=sys.stderr,
        )
        return 2
    records: list[dict[str, Any]]
    source: str
    dialogue_path = out_dir / "runtime-dialogue-test.md"
    if args.judge_existing_runtime:
        if not dialogue_path.exists():
            print(f"ERROR: runtime dialogue file not found at {dialogue_path}", file=sys.stderr)
            return 2
        pairs = extract_qa_pairs(read_text(dialogue_path))
        if not pairs:
            print(f"ERROR: no Q/A pairs found in {dialogue_path}", file=sys.stderr)
            return 2
        records = records_from_pairs(pairs, cases, source="generated", source_path=dialogue_path)
        source = "generated"
    elif args.import_existing:
        legacy_paths = sorted((root / "output" / args.slug).glob("dialogue_test*.md"))
        if not legacy_paths:
            print(f"ERROR: no existing dialogue_test*.md files found for {args.slug}", file=sys.stderr)
            return 2
        records = parse_legacy_dialogues(legacy_paths)
        source = "imported"
    else:
        if not api_key:
            if not llm_enabled:
                print(
                    "ERROR: external LLM calls are disabled by MIND_DISTILL_EVAL_LLM=off. "
                    "Use --import-existing --no-judge, --judge-existing-runtime --no-judge, "
                    "or set MIND_DISTILL_EVAL_LLM=deepseek with MIND_DISTILL_EVAL_API_KEY.",
                    file=sys.stderr,
                )
            else:
                print(
                    "ERROR: MIND_DISTILL_EVAL_API_KEY or DEEPSEEK_API_KEY is required unless --import-existing is used.",
                    file=sys.stderr,
                )
            return 2
        records = run_generation(
            api_key=api_key,
            base_url=args.base_url,
            model=args.model,
            reasoning_effort=args.reasoning_effort,
            skill_text=skill_text,
            cases=cases,
            limit=limit,
        )
        source = "generated"

    out_dir.mkdir(parents=True, exist_ok=True)
    dialogue_md = render_dialogue_markdown(
        slug=args.slug,
        model=args.model,
        reasoning_effort=args.reasoning_effort,
        records=records,
        source=source,
    )
    dialogue_path.write_text(dialogue_md, encoding="utf-8")

    if args.no_judge:
        judgment = skipped_judgment(reason="Judge disabled by --no-judge.", records=records)
    elif not api_key:
        reason = (
            "External LLM calls disabled by MIND_DISTILL_EVAL_LLM=off; dialogue was not judged."
            if not llm_enabled
            else "MIND_DISTILL_EVAL_API_KEY / DEEPSEEK_API_KEY not set; dialogue was not judged."
        )
        judgment = skipped_judgment(reason=reason, records=records)
    else:
        judgment = judge_records(
            api_key=api_key,
            base_url=args.base_url,
            model=args.model,
            reasoning_effort=args.reasoning_effort,
            skill_text=skill_text,
            rubric=rubric,
            records=records,
            standard_case_count=len(cases),
        )

    judgment.setdefault("metadata", {})
    judgment["metadata"].update({
        "slug": args.slug,
        "skill_path": str(skill_path),
        "dialogue_path": str(dialogue_path),
        "source": source,
        "record_count": len(records),
        "standard_case_count": len(cases),
        "llm_mode": llm_mode,
        "model": args.model,
        "reasoning_effort": args.reasoning_effort,
        "base_url": args.base_url,
        "env_file": str(loaded_env_file) if loaded_env_file else None,
    })
    judgment_path = out_dir / "runtime-judgment.json"
    write_json(judgment_path, judgment)
    runtime_eval_path = out_dir / "runtime-evaluation.md"
    runtime_eval_path.write_text(render_runtime_evaluation(args.slug, records, judgment), encoding="utf-8")

    print(f"Wrote {dialogue_path}")
    print(f"Wrote {judgment_path}")
    print(f"Wrote {runtime_eval_path}")
    if should_run_soul_questions(
        ten_questions=args.ten_questions,
        source=source,
        smoke=args.smoke,
        limit=args.limit,
        import_existing=args.import_existing,
        judge_existing_runtime=args.judge_existing_runtime,
        record_count=len(records),
        standard_case_count=len(cases),
    ):
        try:
            soul_paths = run_soul_appendix(
                api_key=api_key or "",
                base_url=args.base_url,
                model=args.model,
                reasoning_effort=args.reasoning_effort,
                root=root,
                slug=args.slug,
                skill_path=skill_path,
                skill_text=skill_text,
                language=str(test_set.get("language") or "zh"),
                out_dir=out_dir,
            )
        except Exception as exc:
            if args.ten_questions == "on":
                print(f"ERROR: failed to generate Soul Ten Questions appendix: {exc}", file=sys.stderr)
                return 2
            print(f"WARNING: skipped Soul Ten Questions appendix: {exc}", file=sys.stderr)
        else:
            print(f"Wrote {soul_paths['json']}")
            print(f"Wrote {soul_paths['markdown']}")
            print(f"Wrote {soul_paths['summary']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
