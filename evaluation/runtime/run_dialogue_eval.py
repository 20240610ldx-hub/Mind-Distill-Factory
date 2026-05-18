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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
