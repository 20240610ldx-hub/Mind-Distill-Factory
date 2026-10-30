#!/usr/bin/env python3
"""mdf run：把一个 agent 步骤交给全新的 harness 进程执行，过程看得见、结果核得了。

    python scripts/mdf.py run <slug> [step] --harness claude-code|codex|pi [--model M] [--yes]

试跑暴露的问题：编排者手写 `until [ -f x.done ]; do sleep 5; done` 轮询无头进程，用户在后台任务
面板里只看到一串看不懂的 shell，不知道在哪一阶段、跑了多久、过没过闸门。这里把整条路收成一条命令：

1. 阶段卡（与 mdf next --card 相同）：这一步做什么、怎么做、过哪道闸门、整体进度；
2. 生成任务简报（与 mdf brief 相同），用 config/harnesses.json 的 isolated_run 启动新进程，
   输出全部写进 output/{slug}/runs/{step}-{时间}.log；
3. 每隔 --heartbeat 秒一行心跳：已用时、日志大小、新产物数、最近一行输出；
4. 进程结束后重读流水线状态：这一步从什么状态变成什么状态；跑这一步自带的检查点，所在阶段的步骤都完成了，
   再跑该阶段的检查点；Claude Code 的结果对象里取费用、轮数、子代理数、被拒的工具调用；
5. 一行结果 + 进度条，并追加到 output/{slug}/runs/runs.jsonl（mdf status --html 的运行记录读它）。

启动的是按量计费的模型进程。不带 --yes 只打印计划、返回 3（fail-closed）；编排者在用户同意后才加 --yes。
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import harness  # noqa: E402
from workspace import Workspace  # noqa: E402
import pipeline_status as ps  # noqa: E402
import run_unit  # noqa: E402

CODE_ROOT = SCRIPTS.parent
NEEDS_CONSENT = 3
RUN_SCHEMA = "run-record-v1"


def _clock(seconds: float) -> str:
    minutes, sec = divmod(int(seconds), 60)
    return f"{minutes}分{sec:02d}秒" if minutes else f"{sec}秒"


def build_argv(profile: dict[str, Any], executable: str, prompt: str, model: str | None = None,
               usage: bool = False, *, effort: str | None = None, data_dirs: tuple[str, ...] = (),
               deny_network: bool = False) -> list[str]:
    """新进程的 argv，拼法见 harness.isolated_argv（模型/强度在提示词前，禁网参数与目录授权在末尾）。"""
    return harness.isolated_argv(profile, executable, prompt, model=model, effort=effort,
                                 data_dirs=data_dirs, usage=usage, deny_network=deny_network)


def _json_events(log: Path, tail_bytes: int | None = None) -> list[dict[str, Any]]:
    """日志里每行一个 JSON 对象（claude -p --output-format json / stream-json）；不是 JSON 的行跳过。"""
    try:
        with log.open("rb") as fh:
            if tail_bytes:
                fh.seek(max(0, log.stat().st_size - tail_bytes))
            text = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    events = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                event = json.loads(line)
            except ValueError:  # tail 截断的半行
                continue
            if isinstance(event, dict):
                events.append(event)
    return events


def parse_usage(log: Path, parser: str | None) -> dict[str, Any] | None:
    """从日志里取费用、轮数、token、子代理数、被拒的工具调用。只认已核实的格式：claude-json = Claude Code 的
    结果对象（`type: result`）。字段顺序不固定（2.1.301 以 duration_api_ms 起头），stream-json 下它也不在最后一行，
    所以逐行解析、取最后一个结果对象。认不出就返回 None，不猜。"""
    if parser != "claude-json":
        return None
    result = next((e for e in reversed(_json_events(log)) if e.get("type") == "result"), None)
    if result is None:
        return None
    usage = result.get("usage") or {}
    denials = result.get("permission_denials")
    record = {
        "cost_usd": result.get("total_cost_usd"),
        "turns": result.get("num_turns"),
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "cache_read_tokens": usage.get("cache_read_input_tokens"),
        "cache_write_tokens": usage.get("cache_creation_input_tokens"),
        # 新进程自己又派了子代理（墨子试跑的 review 步骤就这样）：费用与可复现性都变了，要看得见
        "subagents": (result.get("subagent_stats") or {}).get("spawned"),
        "permission_denials": len(denials) if isinstance(denials, list) else None,
        "result_excerpt": str(result.get("result") or "")[:300] or None,
    }
    return {k: v for k, v in record.items() if v is not None} or None


def usage_text(usage: dict[str, Any] | None) -> str:
    if not usage:
        return ""
    parts = []
    if usage.get("cost_usd") is not None:
        parts.append(f"${usage['cost_usd']:.2f}")
    if usage.get("turns") is not None:
        parts.append(f"{usage['turns']} 轮")
    if usage.get("output_tokens") is not None:
        parts.append(f"输出 {usage['output_tokens']:,} token")
    if usage.get("subagents"):
        parts.append(f"又派了 {usage['subagents']} 个子代理")
    if usage.get("permission_denials"):
        parts.append(f"{usage['permission_denials']} 次工具调用被拒")
    return " · ".join(parts)


def run_warnings(usage: dict[str, Any] | None) -> list[str]:
    """运行记录里要告警的事。新进程不得再派子代理（墨子试跑第 12 条，用户 2026-10-20 决定）：隔离靠新进程
    本身，再派一层只让费用与结果不可复现。只告警、不判失败——产物可能没问题，要人核对。"""
    spawned = (usage or {}).get("subagents")
    if not spawned:
        return []
    return [f"新进程又派了 {spawned} 个子代理：简报禁止这样做（Stage 5 的隔离靠新进程本身）；"
            "费用与结果不可复现，核对产物后再继续"]


def _describe_tool(name: str, args: dict[str, Any]) -> str:
    if args.get("file_path"):
        return f"{name} {Path(str(args['file_path'])).name}"
    detail = args.get("command") or args.get("pattern") or args.get("description") or ""
    return f"{name} {str(detail).splitlines()[0][:60]}".strip() if detail else name


def latest_activity(log: Path, parser: str | None) -> str:
    """心跳里的「最近」：stream-json 下取最后一次工具调用或文字回复，其他格式取日志最后一行。"""
    if parser == "claude-json":
        for event in reversed(_json_events(log, tail_bytes=65536)):
            if event.get("type") != "assistant":
                continue
            content = (event.get("message") or {}).get("content") or []
            for block in reversed(content if isinstance(content, list) else []):
                if block.get("type") == "tool_use":
                    return _describe_tool(str(block.get("name")), block.get("input") or {})
                if block.get("type") == "text" and str(block.get("text") or "").strip():
                    return str(block["text"]).strip().splitlines()[0][:80]
        return ""
    return _last_line(log)


def _snapshot(dirs: list[Path]) -> dict[str, float]:
    found: dict[str, float] = {}
    for base in dirs:
        if base.is_dir():
            for path in base.rglob("*"):
                if path.is_file() and "runs" not in path.relative_to(base).parts[:1]:
                    try:
                        found[str(path)] = path.stat().st_mtime
                    except OSError:
                        continue
    return found


def _changed(before: dict[str, float], dirs: list[Path]) -> list[str]:
    after = _snapshot(dirs)
    return sorted(p for p, mtime in after.items() if before.get(p) != mtime)


def _last_line(log: Path) -> str:
    try:
        with log.open("rb") as fh:
            fh.seek(max(0, log.stat().st_size - 2048))
            lines = [ln.strip() for ln in fh.read().decode("utf-8", errors="replace").splitlines() if ln.strip()]
        return lines[-1][:80] if lines else ""
    except OSError:
        return ""


def _checkpoint(command: str | None, slug: str, root: Path) -> dict[str, Any] | None:
    """跑阶段树里写的检查点命令：在数据根目录下执行（命令里的 sources/… output/… 相对数据根目录），
    命令怎么改写见 Workspace.checkpoint_argv（简报里给执行者的那一条也由它生成）。"""
    if not command:
        return None
    command = command.replace("{slug}", slug)
    workspace = Workspace(root, CODE_ROOT)
    tokens = workspace.checkpoint_argv(command, slug)
    done = subprocess.run(tokens, cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env=workspace.child_env())
    tail = [ln for ln in (done.stdout + done.stderr).splitlines() if ln.strip()][-3:]
    return {"command": command, "exit_code": done.returncode, "tail": tail}


def run_step(slug: str, step_id: str | None, root: Path, harness_name: str, *, yes: bool = False,
             model: str | None = None, effort: str | None = None, timeout_min: float = 60.0, heartbeat: float = 30.0,
             profiles: dict[str, Any] | None = None, which: Callable[[str], str | None] | None = None,
             out: Callable[[str], None] = print) -> int:
    profiles = profiles or harness.load_profiles()
    if harness_name not in profiles["harnesses"]:
        raise SystemExit(f"未知 harness {harness_name!r}；可选：{', '.join(profiles['harnesses'])}")
    profile = harness.HarnessProfile.from_config(harness_name, profiles["harnesses"][harness_name])
    workspace = Workspace(root, CODE_ROOT)
    step_id, brief = harness.build_brief(slug, step_id, root)  # 语料只有 1 个分片时是合并单位 small-corpus
    tree = ps.load_stage_tree()
    before = ps.collect_status(slug, root, tree=tree, gallery_root=workspace.gallery)
    unit = harness.plan_unit(slug, step_id, root, tree=tree, stages=before)
    phase, step = unit.members[0]
    states_before = {s.key: s.state for s in before}
    state_before = states_before[step["id"]]

    out(ps.render_card(slug, before, tree, step_key=step["id"], shard_count=run_unit.shard_count(root, slug)))
    if workspace.risk_notice():  # 数据根在临时 worktree 里：新进程的产物同样会随 worktree 回收丢失
        out(workspace.risk_notice())
    detected = harness.detect(profiles, which) if which else harness.detect(profiles)
    executable = detected.get(harness_name)
    brief_path = root / "output" / slug / "briefs" / f"{step_id}.md"  # 与 harness.write_brief 同一路径
    prompt = harness.brief_prompt(harness._display_path(brief_path, CODE_ROOT))
    if not executable:
        out(f"❌ 没找到 {profile.label} 的可执行文件（{', '.join(profile.executables)}）；"
            f"可先用 mdf brief {slug} {step_id} 生成简报，交给子代理执行。")
        return 2
    # 数据根不在仓库里时，新进程的工作目录（仓库）之外还要授权它读写数据根；禁网步骤再拿掉联网工具
    argv = profile.argv(executable, prompt, model=model, effort=effort, grants=workspace.grants(), usage=True,
                        deny_network=unit.forbids_network)
    what = f"{unit.title}：{unit.steps_text}" if unit.is_bundle else step["title"]
    if not yes:  # 只打印计划，不写任何文件
        out(f"计划：用 {profile.label} 在一个新进程里执行「{what}」（按量计费的模型调用）。")
        out(f"  命令：{shlex.join(argv)}")
        out(f"  简报：{harness._display_path(brief_path, CODE_ROOT)}（--yes 时写入）")
        out("用户同意后加 --yes 执行。")
        return NEEDS_CONSENT
    harness.write_brief(slug, step_id, brief, root)

    started = datetime.now()
    runs_dir = root / "output" / slug / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    log = runs_dir / f"{step_id}-{started:%Y%m%d-%H%M%S}.log"
    watch = [root / "output" / slug, root / "sources" / slug / "processed"]
    snapshot = _snapshot(watch)
    label = f"{unit.title}（{unit.steps_text}）" if unit.is_bundle else f"{phase['chapter']['title']} / {step['title']}"
    out(f"▶ 开始：{label} · {profile.label}" + (f" · 模型 {model}" if model else "")
        + (f" · 强度 {effort}" if effort else "") + f" · 日志 {log.name}")
    env = workspace.child_env()
    t0 = time.monotonic()
    timed_out = False
    with log.open("wb") as sink:
        proc = subprocess.Popen(argv, cwd=CODE_ROOT, stdin=subprocess.DEVNULL, stdout=sink,
                                stderr=subprocess.STDOUT, env=env)
        next_beat = heartbeat
        while proc.poll() is None:
            time.sleep(min(1.0, heartbeat))
            elapsed = time.monotonic() - t0
            if elapsed > timeout_min * 60:
                proc.kill()
                timed_out = True
                break
            if elapsed >= next_beat:
                next_beat += heartbeat
                size = log.stat().st_size / 1024
                last = latest_activity(log, profile.usage_parser)
                out(f"  … {_clock(elapsed)} · 日志 {size:.1f} KB · 新产物 {len(_changed(snapshot, watch))} 个"
                    + (f" · 最近：{last}" if last else ""))
        proc.wait()
    seconds = time.monotonic() - t0
    changed = _changed(snapshot, watch)

    after = ps.collect_status(slug, root, tree=tree, gallery_root=workspace.gallery)
    states_after = {s.key: s.state for s in after}
    state_after = states_after[unit.step_ids[-1]]

    def phase_finished(phase_id: str) -> bool:
        return all(s.state in ps.FINISHED for s in after if s.phase == phase_id)

    # 单个步骤：自带的检查点（extract 的 task_status --strict、review 的 --strict）每次都跑，阶段检查点要等
    # 本阶段的步骤都做完才有意义（墨子试跑发现 1）。合并单位：成员的检查点一律都跑（墨子试跑第 14 条）。
    commands = unit.checkpoints(phase_finished=phase_finished)
    process_ok = proc.returncode == 0 and not timed_out
    checks = [c for c in (_checkpoint(cmd, slug, root) for cmd in commands if process_ok) if c]
    ok = (process_ok and all(states_after[s] != "failed" for s in unit.step_ids)
          and all(c["exit_code"] == 0 for c in checks))
    usage = parse_usage(log, profile.usage_parser)
    warnings = run_warnings(usage)

    labels = ps.STATE_LABELS
    if timed_out:
        verdict = f"⏱ 超时（{timeout_min:g} 分钟）已终止"
    elif proc.returncode != 0:
        verdict = f"❌ 进程退出码 {proc.returncode}"
    else:
        verdict = "✅ 进程正常结束" if ok else "⚠️ 进程结束，但步骤未通过"
    members = [{"step": s, "before": states_before[s], "after": states_after[s]} for s in unit.step_ids]
    changes = "、".join(f"{m['title']} {labels.get(states_before[m['id']], states_before[m['id']])} → "
                       f"{labels.get(states_after[m['id']], states_after[m['id']])}" for _, m in unit.members)
    out(f"{verdict}：{label}（{_clock(seconds)}）· "
        + (changes if unit.is_bundle else f"步骤 {labels.get(state_before, state_before)} → "
           f"{labels.get(state_after, state_after)}")
        + f" · 新产物 {len(changed)} 个" + (f" · {usage_text(usage)}" if usage else ""))
    if not process_ok and (usage or {}).get("result_excerpt"):
        # 2026-10-20 实跑：额度用完时 claude 退出码 1，「session limit」只写在结果对象里
        out(f"  原因：{usage['result_excerpt']}")
    for warning in warnings:
        out(f"  ⚠️ {warning}")
    for check in checks:
        out(f"  检查点 `{check['command']}`：{'通过' if check['exit_code'] == 0 else '未通过'}"
            + ("" if check["exit_code"] == 0 else "\n    " + "\n    ".join(check["tail"])))
    if any(c["exit_code"] for c in checks):
        for _, member in unit.members:
            if member.get("checkpoint_note"):
                out(f"  说明{'（' + member['title'] + '）' if unit.is_bundle else ''}："
                    f"{member['checkpoint_note'].replace('{slug}', slug)}")
    if not unit.is_bundle and not phase_finished(phase["id"]) and phase.get("checkpoint"):
        out("  本阶段还有步骤没完成，阶段检查点留到阶段末尾再跑。")
    out(f"  进度：{ps.progress_bar(after, tree)}")
    out(f"  日志：{harness._display_path(log, CODE_ROOT)}")

    record = {
        "schema": RUN_SCHEMA, "slug": slug, "step": step_id, "phase": phase["id"], "harness": harness_name,
        "model": model, "effort": effort, "started_at": f"{started:%Y-%m-%d %H:%M:%S}", "seconds": round(seconds),
        "exit_code": proc.returncode, "timed_out": timed_out, "state_before": state_before, "state_after": state_after,
        "checkpoints": checks, "changed_files": len(changed), "ok": ok, "usage": usage, "warnings": warnings,
        "summary": verdict.split(" ", 1)[-1] + f" · {labels.get(state_after, state_after)}",
        "log": harness._display_path(log, CODE_ROOT), "brief": harness._display_path(brief_path, CODE_ROOT),
    }
    if unit.is_bundle:  # 合并单位：state_before 是第一步的、state_after 是最后一步的，逐步的在 members 里
        record["members"] = members
    with (runs_dir / "runs.jsonl").open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    if sys.platform.startswith("win"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
        except AttributeError:
            pass
    slug_arg = harness._sibling("slug_rules").slug_arg
    parser = argparse.ArgumentParser(prog="mdf run", description="把 agent 步骤交给新进程执行：阶段卡、心跳、日志、闸门、运行记录")
    parser.add_argument("slug", type=slug_arg)
    parser.add_argument("step", nargs="?", help="步骤 id 或合并单位 id（默认下一个未完成的 agent 步骤；只有 1 个分片时抽取、合并、原则提取合成 small-corpus）")
    parser.add_argument("--harness", required=True, help="claude-code / codex / pi（见 config/harnesses.json）")
    parser.add_argument("--model", help="指定模型（按各 harness 的 model_flag 传入）")
    parser.add_argument("--effort", help="推理强度（按各 harness 的 effort_flag 传入：claude --effort，pi --thinking）")
    parser.add_argument("--yes", action="store_true", help="确认启动按量计费的模型进程；不加只打印计划")
    parser.add_argument("--timeout", type=float, default=60.0, help="超时分钟数（默认 60）")
    parser.add_argument("--heartbeat", type=float, default=30.0, help="心跳间隔秒数（默认 30）")
    parser.add_argument("--root", help="数据根目录（默认 MDF_DATA_ROOT，再默认仓库根）")
    args = parser.parse_args(argv)
    root = Workspace.resolve(args.root).data_root
    out = lambda line: print(line, flush=True)  # noqa: E731 - 心跳要即时出现在后台任务面板里
    return run_step(args.slug, args.step, root, args.harness, yes=args.yes, model=args.model, effort=args.effort,
                    timeout_min=args.timeout, heartbeat=args.heartbeat, out=out)


if __name__ == "__main__":
    raise SystemExit(main())
