#!/usr/bin/env python3
"""mdf run：把一个 agent 步骤交给全新的 harness 进程执行，过程看得见、结果核得了。

    python scripts/mdf.py run <slug> [step] --harness claude-code|codex|pi [--model M] [--yes]

试跑暴露的问题：编排者手写 `until [ -f x.done ]; do sleep 5; done` 轮询无头进程，用户在后台任务
面板里只看到一串看不懂的 shell，不知道在哪一阶段、跑了多久、过没过闸门。这里把整条路收成一条命令：

1. 阶段卡（与 mdf next --card 相同）：这一步做什么、怎么做、过哪道闸门、整体进度；
2. 生成任务简报（与 mdf brief 相同），用 config/harnesses.json 的 isolated_run 启动新进程，
   输出全部写进 output/{slug}/runs/{step}-{时间}.log；
3. 每隔 --heartbeat 秒一行心跳：已用时、日志大小、新产物数、最近一行输出；
4. 进程结束后重读流水线状态：这一步从什么状态变成什么状态；所在阶段的步骤都完成了，就跑该阶段的检查点；
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
import pipeline_status as ps  # noqa: E402

CODE_ROOT = SCRIPTS.parent
NEEDS_CONSENT = 3
RUN_SCHEMA = "run-record-v1"


def _clock(seconds: float) -> str:
    minutes, sec = divmod(int(seconds), 60)
    return f"{minutes}分{sec:02d}秒" if minutes else f"{sec}秒"


def build_argv(profile: dict[str, Any], executable: str, prompt: str, model: str | None = None,
               extra: list[str] | None = None) -> list[str]:
    """把 isolated_run 模板（如 `claude -p --permission-mode acceptEdits "{prompt}"`）拆成 argv。
    不经过 shell：提示词原样作为一个参数传入。extra（如禁网步骤的 --disallowedTools）紧跟可执行文件。"""
    tokens = shlex.split(profile["isolated_run"])
    argv = [executable, *(extra or []), *[prompt if t == "{prompt}" else t for t in tokens[1:]]]
    if model:
        flag = profile.get("model_flag")
        if not flag:
            raise SystemExit(f"{profile.get('label', '该 harness')} 没有配置 model_flag，不能指定 --model")
        argv[1:1] = [flag, model]
    return argv


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


def parse_usage(log: Path) -> dict[str, Any] | None:
    """从新进程日志里取用量。目前只认 Claude Code `--output-format json` 的最终结果对象
    （type=result）；其他 harness 的输出格式未核实，取不到就返回 None，不猜。"""
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    start = text.rfind('{"type":"result"')
    if start < 0:
        start = text.find("{")
    if start < 0:
        return None
    try:
        data, _ = json.JSONDecoder().raw_decode(text[start:])
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("type") != "result":
        return None
    usage = data.get("usage") or {}
    record = {
        "cost_usd": data.get("total_cost_usd"),
        "turns": data.get("num_turns"),
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "cache_read_tokens": usage.get("cache_read_input_tokens"),
        "cache_write_tokens": usage.get("cache_creation_input_tokens"),
    }
    # 新进程自己又派了子代理（墨子试跑的 review 步骤就这样）：费用与可复现性都变了，要看得见。
    subagents = (data.get("subagent_stats") or {}).get("spawned")
    if subagents is not None:
        record["subagents"] = subagents
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
    return " · ".join(parts)


def _checkpoint(phase: dict[str, Any], slug: str, root: Path, command: str | None = None) -> dict[str, Any] | None:
    command = command or phase.get("checkpoint")
    if not command:
        return None
    tokens = shlex.split(command.replace("{slug}", slug))
    script = next((t for t in tokens if t.startswith("scripts/") and t.endswith(".py")), None)
    if script is None:
        raise SystemExit(f"检查点命令不是 python scripts/<脚本>.py 形式，不会执行：{command}")
    rest = tokens[tokens.index(script) + 1:]
    if script == "scripts/mdf.py":
        argv, cwd = [sys.executable, str(SCRIPTS / "mdf.py"), *rest, "--root", str(root)], CODE_ROOT
    else:  # 其他脚本（如 task_status.py）的路径参数相对数据根目录
        argv, cwd = [sys.executable, str(CODE_ROOT / script), *rest], root
    done = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    tail = [ln for ln in (done.stdout + done.stderr).splitlines() if ln.strip()][-3:]
    return {"command": command.replace("{slug}", slug), "exit_code": done.returncode, "tail": tail}


def run_step(slug: str, step_id: str | None, root: Path, harness_name: str, *, yes: bool = False,
             model: str | None = None, timeout_min: float = 60.0, heartbeat: float = 30.0,
             profiles: dict[str, Any] | None = None, which: Callable[[str], str | None] | None = None,
             out: Callable[[str], None] = print) -> int:
    profiles = profiles or harness.load_profiles()
    if harness_name not in profiles["harnesses"]:
        raise SystemExit(f"未知 harness {harness_name!r}；可选：{', '.join(profiles['harnesses'])}")
    profile = profiles["harnesses"][harness_name]
    step_id, brief = harness.build_brief(slug, step_id, root)
    tree = ps.load_stage_tree()
    phase, step = harness.find_step(tree, step_id)
    before = ps.collect_status(slug, root, tree=tree)
    state_before = next(s.state for s in before if s.key == step_id)

    out(ps.render_card(slug, before, tree, step_key=step_id))
    detected = harness.detect(profiles, which) if which else harness.detect(profiles)
    executable = detected.get(harness_name)
    brief_path = root / "output" / slug / "briefs" / f"{step_id}.md"  # 与 harness.write_brief 同一路径
    prompt = f"读取 {harness._display_path(brief_path, CODE_ROOT)} 并严格按其执行，完成后报告检查点结果。"
    if not executable:
        out(f"❌ 没找到 {profile['label']} 的可执行文件（{', '.join(profile['executables'])}）；"
            f"可先用 mdf brief {slug} {step_id} 生成简报，交给子代理执行。")
        return 2
    argv = build_argv(profile, executable, prompt, model, harness.step_extra_args(profile, step))
    if not yes:  # 只打印计划，不写任何文件
        out(f"计划：用 {profile['label']} 在新进程里执行「{step['title']}」（按量计费的模型调用）。")
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
    label = f"{phase['chapter']['title']} / {step['title']}"
    out(f"▶ 开始：{label} · {profile['label']}" + (f" · 模型 {model}" if model else "") + f" · 日志 {log.name}")
    env = {**os.environ, "MDF_DATA_ROOT": str(root), "PYTHONUTF8": "1"}
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
                last = _last_line(log)
                out(f"  … {_clock(elapsed)} · 日志 {size:.1f} KB · 新产物 {len(_changed(snapshot, watch))} 个"
                    + (f" · 最近输出：{last}" if last else ""))
        proc.wait()
    seconds = time.monotonic() - t0
    changed = _changed(snapshot, watch)

    after = ps.collect_status(slug, root, tree=tree)
    state_after = next(s.state for s in after if s.key == step_id)
    phase_finished = all(s.state in ps.FINISHED for s in after if s.phase == phase["id"])
    # 步骤自带检查点（如 extract 的 task_status、review 的 --strict）在步骤结束就跑；
    # 没有的话，等本阶段步骤全部完成再跑阶段检查点。
    clean_exit = proc.returncode == 0 and not timed_out
    if step.get("checkpoint"):
        check = _checkpoint(phase, slug, root, step["checkpoint"]) if clean_exit else None
    else:
        check = _checkpoint(phase, slug, root) if phase_finished and clean_exit else None
    usage = parse_usage(log)
    ok = proc.returncode == 0 and not timed_out and state_after != "failed" and (check is None or check["exit_code"] == 0)

    labels = ps.STATE_LABELS
    if timed_out:
        verdict = f"⏱ 超时（{timeout_min:g} 分钟）已终止"
    elif proc.returncode != 0:
        verdict = f"❌ 进程退出码 {proc.returncode}"
    else:
        verdict = "✅ 进程正常结束" if ok else "⚠️ 进程结束，但步骤未通过"
    out(f"{verdict}：{label}（{_clock(seconds)}）· 步骤 {labels.get(state_before, state_before)} → "
        f"{labels.get(state_after, state_after)} · 新产物 {len(changed)} 个"
        + (f" · {usage_text(usage)}" if usage else ""))
    if check:
        out(f"  检查点 `{check['command']}`：{'通过' if check['exit_code'] == 0 else '未通过'}"
            + ("" if check["exit_code"] == 0 else "\n    " + "\n    ".join(check["tail"])))
    elif not phase_finished and not step.get("checkpoint"):
        out(f"  本阶段还有步骤没完成，检查点留到阶段末尾再跑。")
    out(f"  进度：{ps.progress_bar(after, tree)}")
    out(f"  日志：{harness._display_path(log, CODE_ROOT)}")

    record = {
        "schema": RUN_SCHEMA, "slug": slug, "step": step_id, "phase": phase["id"], "harness": harness_name,
        "model": model, "started_at": f"{started:%Y-%m-%d %H:%M:%S}", "seconds": round(seconds),
        "exit_code": proc.returncode, "timed_out": timed_out, "state_before": state_before, "state_after": state_after,
        "checkpoint": check, "changed_files": len(changed), "ok": ok, "usage": usage,
        "summary": verdict.split(" ", 1)[-1] + f" · {labels.get(state_after, state_after)}",
        "log": harness._display_path(log, CODE_ROOT), "brief": harness._display_path(brief_path, CODE_ROOT),
    }
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
    parser.add_argument("step", nargs="?", help="步骤 id（默认下一个未完成的 agent 步骤）")
    parser.add_argument("--harness", required=True, help="claude-code / codex / pi（见 config/harnesses.json）")
    parser.add_argument("--model", help="指定模型（按各 harness 的 model_flag 传入）")
    parser.add_argument("--yes", action="store_true", help="确认启动按量计费的模型进程；不加只打印计划")
    parser.add_argument("--timeout", type=float, default=60.0, help="超时分钟数（默认 60）")
    parser.add_argument("--heartbeat", type=float, default=30.0, help="心跳间隔秒数（默认 30）")
    parser.add_argument("--root", help="数据根目录（默认 MDF_DATA_ROOT，再默认仓库根）")
    args = parser.parse_args(argv)
    root = Path(args.root or os.environ.get("MDF_DATA_ROOT") or CODE_ROOT).resolve()
    out = lambda line: print(line, flush=True)  # noqa: E731 - 心跳要即时出现在后台任务面板里
    return run_step(args.slug, args.step, root, args.harness, yes=args.yes, model=args.model,
                    timeout_min=args.timeout, heartbeat=args.heartbeat, out=out)


if __name__ == "__main__":
    raise SystemExit(main())
