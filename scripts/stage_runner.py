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
               usage: bool = False) -> list[str]:
    """把 isolated_run 模板（如 `claude -p "{prompt}" --permission-mode acceptEdits …`）拆成 argv。
    不经过 shell：提示词原样作为一个参数传入。usage=True 时追加 usage_flags（机器可读的结果与用量）。"""
    tokens = shlex.split(profile["isolated_run"])
    argv = [executable, *[prompt if t == "{prompt}" else t for t in tokens[1:]]]
    if model:
        flag = profile.get("model_flag")
        if not flag:
            raise SystemExit(f"{profile.get('label', '该 harness')} 没有配置 model_flag，不能指定 --model")
        argv[1:1] = [flag, model]
    if usage:
        argv += list(profile.get("usage_flags") or [])
    return argv


def parse_usage(log: Path, parser: str | None) -> dict[str, Any]:
    """从日志里取费用、轮数、token。只认已核实的格式：claude-json = `claude -p --output-format json`
    在结尾打印的结果对象（墨子试跑的费用统计就靠它）。认不出就返回空，不猜。"""
    if parser != "claude-json":
        return {}
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    start = text.rfind('{"type":"result"')
    if start < 0:
        start = text.rfind("{")
    try:
        data = json.loads(text[start:])
    except ValueError:
        return {}
    usage = data.get("usage") or {}
    return {
        "cost_usd": data.get("total_cost_usd"),
        "turns": data.get("num_turns"),
        "output_tokens": usage.get("output_tokens"),
        "cache_read_tokens": usage.get("cache_read_input_tokens"),
        "result_excerpt": str(data.get("result") or "")[:300],
    }


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
    """跑阶段树里写的检查点命令。`python` 换成当前解释器，`scripts/*.py` 换成仓库里的绝对路径，
    在数据根目录下执行（命令里的 sources/… output/… 相对数据根目录）。"""
    if not command:
        return None
    command = command.replace("{slug}", slug)
    tokens = shlex.split(command)
    if tokens and tokens[0] in ("python", "python3"):
        tokens[0] = sys.executable
    tokens = [str(CODE_ROOT / t) if t.startswith("scripts/") and t.endswith(".py") else t for t in tokens]
    done = subprocess.run(tokens, cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env={**os.environ, "MDF_DATA_ROOT": str(root), "PYTHONUTF8": "1"})
    tail = [ln for ln in (done.stdout + done.stderr).splitlines() if ln.strip()][-3:]
    return {"command": command, "exit_code": done.returncode, "tail": tail}


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
    argv = build_argv(profile, executable, prompt, model, usage=True)
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
    # 步骤自带的检查点每次都跑；阶段检查点要等本阶段的步骤都做完才有意义（墨子试跑发现 1）
    commands = [step.get("checkpoint")]
    if phase_finished and phase.get("checkpoint") != step.get("checkpoint"):
        commands.append(phase.get("checkpoint"))
    process_ok = proc.returncode == 0 and not timed_out
    checks = [c for c in (_checkpoint(cmd, slug, root) for cmd in commands if cmd and process_ok) if c]
    ok = process_ok and state_after != "failed" and all(c["exit_code"] == 0 for c in checks)
    usage = parse_usage(log, profile.get("usage_parser"))

    labels = ps.STATE_LABELS
    if timed_out:
        verdict = f"⏱ 超时（{timeout_min:g} 分钟）已终止"
    elif proc.returncode != 0:
        verdict = f"❌ 进程退出码 {proc.returncode}"
    else:
        verdict = "✅ 进程正常结束" if ok else "⚠️ 进程结束，但步骤未通过"
    spent = "".join([f" · 费用 ${usage['cost_usd']:.2f}" if isinstance(usage.get("cost_usd"), (int, float)) else "",
                     f" · {usage['turns']} 轮" if usage.get("turns") else ""])
    out(f"{verdict}：{label}（{_clock(seconds)}{spent}）· 步骤 {labels.get(state_before, state_before)} → "
        f"{labels.get(state_after, state_after)} · 新产物 {len(changed)} 个")
    for check in checks:
        out(f"  检查点 `{check['command']}`：{'通过' if check['exit_code'] == 0 else '未通过'}"
            + ("" if check["exit_code"] == 0 else "\n    " + "\n    ".join(check["tail"])))
    if step.get("checkpoint_note") and any(c["exit_code"] for c in checks):
        out(f"  说明：{step['checkpoint_note'].replace('{slug}', slug)}")
    if not phase_finished and phase.get("checkpoint"):
        out("  本阶段还有步骤没完成，阶段检查点留到阶段末尾再跑。")
    out(f"  进度：{ps.progress_bar(after, tree)}")
    out(f"  日志：{harness._display_path(log, CODE_ROOT)}")

    record = {
        "schema": RUN_SCHEMA, "slug": slug, "step": step_id, "phase": phase["id"], "harness": harness_name,
        "model": model, "started_at": f"{started:%Y-%m-%d %H:%M:%S}", "seconds": round(seconds),
        "exit_code": proc.returncode, "timed_out": timed_out, "state_before": state_before, "state_after": state_after,
        "checkpoints": checks, "changed_files": len(changed), "ok": ok, **usage,
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
