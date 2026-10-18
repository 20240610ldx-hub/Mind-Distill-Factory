#!/usr/bin/env python3
"""harness 适配层：让同一条流水线在 Claude Code / Codex / pi 里都能跑。

    python scripts/mdf.py harness [list] [--json]          # 检测已装的 harness、核对适配文件
    python scripts/mdf.py harness plan <slug> --target codex [--scope user|project]
    python scripts/mdf.py brief <slug> [step] [--harness pi] [--stdout]

三件事都是确定性的：
- list：读 config/harnesses.json，查 PATH 上有哪些 harness，核对插件清单、跨 harness
  编排 skill、子代理定义与指令文件是否就位、是否互相矛盾；
- plan：给出把 gallery 里的已发布包装进某个 harness 技能目录的命令，**只打印不执行**——
  往仓库外写文件（发布时自动安装）曾被刻意移除，是否恢复留给人决定；
- brief：把一个 agent 步骤打包成自足的任务简报（角色定义 + 输入输出 + 检查点），
  没有子代理的 harness 用一个新进程执行它，Stage 5 审查也因此能保证上下文隔离。
"""

from __future__ import annotations

import argparse
import functools
import importlib.util
import json
import os
import re
import shlex
import shutil
import sys
from pathlib import Path
from typing import Any, Iterable

CODE_ROOT = Path(__file__).resolve().parent.parent
PROFILES_SCHEMA = "harness-profiles-v1"
PLUGIN_MANIFEST = ".claude-plugin/plugin.json"
PLUGIN_NAME = "mind-distill-factory"
# Agent Skills 规范（agentskills.io）：name ≤64、小写字母数字与连字符；description ≤1024 字符。
SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
SKILL_DESCRIPTION_MAX = 1024
DOSSIER_NAME = "人物档案.md"  # 给人看的档案，进 gallery 但不进安装目录（CLAUDE.md）


@functools.lru_cache(maxsize=None)
def _sibling(name: str) -> Any:
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_harness_{name}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_profiles(code_root: Path = CODE_ROOT) -> dict[str, Any]:
    data = json.loads((code_root / "config" / "harnesses.json").read_text(encoding="utf-8"))
    if data.get("schema") != PROFILES_SCHEMA:
        raise ValueError(f"config/harnesses.json: schema 应为 {PROFILES_SCHEMA}")
    return data


def parse_frontmatter(text: str) -> dict[str, str]:
    """最小 YAML frontmatter 解析：`key: value` 与 `key: >-`/`|` 折叠块，够读 SKILL.md 与 agent 定义。"""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    fields: dict[str, str] = {}
    key = None
    block: list[str] = []
    for line in text[3:end].splitlines():
        match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if match and not line.startswith((" ", "\t")):
            if key is not None and block:
                fields[key] = " ".join(block).strip()
            key, value = match.group(1), match.group(2).strip()
            block = []
            if value in (">-", ">", "|", "|-"):
                fields[key] = ""
            else:
                fields[key] = value.strip("\"'")
                key = None
        elif key is not None:
            block.append(line.strip())
    if key is not None and block:
        fields[key] = " ".join(block).strip()
    return fields


# ── list：检测与核对 ─────────────────────────────────────────────────


def detect(profiles: dict[str, Any], which=shutil.which) -> dict[str, str | None]:
    found = {}
    for name, profile in profiles["harnesses"].items():
        found[name] = next((which(exe) for exe in profile["executables"] if which(exe)), None)
    return found


def adapter_checks(code_root: Path = CODE_ROOT, profiles: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """核对适配文件：插件清单、编排 skill、子代理定义、给 Codex/pi 的指令文件是否与 v6 规则一致。"""
    profiles = profiles or load_profiles(code_root)
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str, required: bool = True) -> None:
        checks.append({"name": name, "ok": ok, "required": required, "detail": detail})

    plugin = code_root / PLUGIN_MANIFEST
    try:
        manifest = json.loads(plugin.read_text(encoding="utf-8"))
        missing = [p for p in _plugin_paths(manifest) if not (code_root / p).exists()]
        ok = manifest.get("name") == PLUGIN_NAME and not missing
        add("Claude Code 插件清单", ok, f"{PLUGIN_MANIFEST}" + (f"；缺路径 {missing}" if missing else "")
            + ("" if manifest.get("name") == PLUGIN_NAME else f"；name 应为 {PLUGIN_NAME}"))
    except (OSError, ValueError) as exc:
        add("Claude Code 插件清单", False, f"{PLUGIN_MANIFEST} 不可读：{type(exc).__name__}")

    skill_rel = profiles["orchestrator_skill"]
    skill = code_root / skill_rel
    if skill.exists():
        meta = parse_frontmatter(skill.read_text(encoding="utf-8"))
        problems = []
        if meta.get("name") != skill.parent.name:
            problems.append(f"name={meta.get('name')!r} 与目录名 {skill.parent.name!r} 不一致")
        if not meta.get("description"):
            problems.append("缺 description")
        elif len(meta["description"]) > SKILL_DESCRIPTION_MAX:
            problems.append(f"description {len(meta['description'])} 字符，超过 {SKILL_DESCRIPTION_MAX}")
        add("跨 harness 编排 skill（Codex / pi）", not problems, skill_rel + ("；" + "；".join(problems) if problems else ""))
    else:
        add("跨 harness 编排 skill（Codex / pi）", False, f"缺 {skill_rel}")

    bad_agents = []
    for path in sorted((code_root / "agents").glob("*.md")):
        meta = parse_frontmatter(path.read_text(encoding="utf-8"))
        if meta.get("name") != path.stem or not meta.get("description"):
            bad_agents.append(path.name)
    add("子代理定义 agents/*.md", not bad_agents,
        "frontmatter name 与文件名一致且有 description" if not bad_agents else f"不合规：{bad_agents}")

    # Codex 与 pi 读 AGENTS.md；它若还停在 v6 之前，agent 会拿到「双语合一 SKILL.md」这类过时规则。
    agents_md = code_root / "AGENTS.md"
    text = agents_md.read_text(encoding="utf-8") if agents_md.exists() else ""
    current = "format_version: 6" in text or "Chinese-only" in text
    add("AGENTS.md 与 v6 规则一致", current,
        "已是 v6" if current else "仍是 v6 之前的规则（Codex / pi 会读到）；编排 skill 已声明以 CLAUDE.md 为准，"
        "根治需同步 AGENTS.md（见文档分支 claude/dreamy-hamilton-3fd992）", required=False)
    return checks


def _plugin_paths(manifest: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for key in ("commands", "agents", "skills", "outputStyles"):
        value = manifest.get(key)
        if isinstance(value, str):
            paths.append(value)
        elif isinstance(value, list):
            paths.extend(v for v in value if isinstance(v, str))
    return [p for p in paths if p not in (".", "./")]


def list_report(code_root: Path = CODE_ROOT, which=shutil.which) -> dict[str, Any]:
    profiles = load_profiles(code_root)
    found = detect(profiles, which)
    harnesses = []
    for name, profile in profiles["harnesses"].items():
        harnesses.append({
            "id": name, "label": profile["label"], "installed": found[name] is not None, "path": found[name],
            "invoke": profile["orchestrator"]["invoke"], "load": profile["orchestrator"]["load"],
            "subagents": profile["subagents"]["native"], "chapters": profile["chapters"]["native"],
        })
    checks = adapter_checks(code_root, profiles)
    return {
        "schema": "mdf-harness-v1", "verified_at": profiles["verified_at"], "harnesses": harnesses,
        "checks": checks, "ok": all(c["ok"] for c in checks if c["required"]),
    }


def render_list(report: dict[str, Any]) -> str:
    yes = {True: "✅", False: "—", None: "未核实"}
    lines = [f"## harness 适配（事实核对于 {report['verified_at']}）", "",
             "| harness | 已安装 | 怎样启动编排 | 原生子代理 | 原生章节 |", "|---|---|---|---|---|"]
    for h in report["harnesses"]:
        lines.append(f"| {h['label']} | {'✅' if h['installed'] else '—'} | {h['load']}；`{h['invoke']}` "
                     f"| {yes[h['subagents']]} | {yes[h['chapters']]} |")
    lines += ["", "| 适配文件 | 结果 | 说明 |", "|---|---|---|"]
    for c in report["checks"]:
        mark = "✅" if c["ok"] else ("❌" if c["required"] else "⚠️")
        lines.append(f"| {c['name']} | {mark} | {c['detail']} |")
    lines += ["", "没有原生子代理或章节的 harness：agent 步骤用 `mdf brief` 生成简报交给新进程，阶段标题用 H2 兜底。"]
    return "\n".join(lines) + "\n"


# ── plan：安装命令（只打印） ─────────────────────────────────────────


def install_plan(slug: str, target: str, scope: str = "user", code_root: Path = CODE_ROOT) -> dict[str, Any]:
    profiles = load_profiles(code_root)
    if target not in profiles["harnesses"]:
        raise SystemExit(f"未知 harness：{target}（可选 {'、'.join(profiles['harnesses'])}）")
    package = code_root / "gallery" / slug
    skill_md = package / "SKILL.md"
    if not skill_md.exists():
        raise SystemExit(f"gallery/{slug}/SKILL.md 不存在：先用 mdf publish 发布")
    pm = _sibling("package_manifest")
    _, manifest_errors = pm.load_manifest(package / pm.MANIFEST_NAME)
    meta = parse_frontmatter(skill_md.read_text(encoding="utf-8"))
    name = meta.get("name") or f"{slug}-wisdom"
    warnings = list(manifest_errors)
    if not SKILL_NAME_RE.match(name) or len(name) > 64:
        warnings.append(f"name {name!r} 不符合 Agent Skills 命名（小写字母数字与连字符，≤64）")
    if len(meta.get("description", "")) > SKILL_DESCRIPTION_MAX:
        warnings.append(f"description 超过 {SKILL_DESCRIPTION_MAX} 字符，部分 harness 会截断或拒绝")
    if target != "claude-code" and "argument-hint" in meta:
        warnings.append("frontmatter 里的 argument-hint 是 Claude Code 字段，其他 harness 会忽略")
    base = profiles["harnesses"][target]["skill_dirs"][scope]
    dest = f"{base}/{name}"
    src = f"gallery/{slug}"
    # 引号里的 ~ 不会展开，两种 shell 都改写成 $HOME。
    sh_dest = dest.replace("~", "$HOME", 1)
    bash = f'mkdir -p "{sh_dest}" && cp -R "{src}/." "{sh_dest}/" && rm -f "{sh_dest}/{DOSSIER_NAME}"'
    ps_dest = sh_dest.replace("/", "\\")
    powershell = (f'New-Item -ItemType Directory -Force "{ps_dest}" | Out-Null; '
                  f'Copy-Item -Recurse -Force "{src.replace("/", chr(92))}\\*" "{ps_dest}"; '
                  f'Remove-Item -Force -ErrorAction SilentlyContinue "{ps_dest}\\{DOSSIER_NAME}"')
    return {"slug": slug, "target": target, "scope": scope, "skill_name": name, "source": src,
            "destination": dest, "commands": {"bash": bash, "powershell": powershell}, "warnings": warnings}


def render_plan(plan: dict[str, Any]) -> str:
    lines = [f"## 安装计划：{plan['skill_name']} → {plan['target']}（{plan['scope']}）", "",
             f"来源 `{plan['source']}`，目标 `{plan['destination']}`；不复制 `{DOSSIER_NAME}`。本命令不写任何文件，请自己执行：", "",
             "```bash", plan["commands"]["bash"], "```", "", "```powershell", plan["commands"]["powershell"], "```"]
    if plan["warnings"]:
        lines += ["", "注意："] + [f"- {w}" for w in plan["warnings"]]
    return "\n".join(lines) + "\n"


# ── brief：agent 步骤的自足任务简报 ───────────────────────────────────

ISOLATED_STEPS = {"review"}  # 必须在与生成过程无关的上下文里执行
SLUG_PLACEHOLDERS = ("{slug}", "{person_slug}", "{person-slug}")  # agents/*.md 里三种写法都有


def find_step(tree: dict[str, Any], step_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    for phase in tree["phases"]:
        for step in phase["steps"]:
            if step["id"] == step_id:
                return phase, step
    raise SystemExit(f"阶段树里没有步骤 {step_id!r}（mdf stages 查看全部）")


def agent_names(step: dict[str, Any], code_root: Path = CODE_ROOT) -> list[str]:
    """从步骤的 agent 字段里取出在 agents/ 下确有定义的角色名，保持出现顺序。"""
    tokens = re.findall(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)+", step.get("agent", ""))
    return [t for t in dict.fromkeys(tokens) if (code_root / "agents" / f"{t}.md").exists()]


def _display_path(path: Path, code_root: Path) -> str:
    try:
        return path.resolve().relative_to(code_root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def build_brief(slug: str, step_id: str | None, root: Path, code_root: Path = CODE_ROOT) -> tuple[str, str]:
    """返回 (step_id, 简报 Markdown)。step_id 为空时取下一个未完成的 agent 步骤。"""
    ps = _sibling("pipeline_status")
    tree = ps.load_stage_tree(code_root)
    stages = ps.collect_status(slug, root, tree=tree)
    if step_id is None:
        pending = [s for s in stages if s.state not in ps.FINISHED]
        candidates = [s for s in pending if "agent" in find_step(tree, s.key)[1]["executor"].split("|")]
        if not candidates:
            raise SystemExit("没有待做的 agent 步骤（mdf status 查看进度）")
        if pending and pending[0].key != candidates[0].key:
            print(f"WARNING: 前面还有未完成的步骤「{pending[0].title}」：{pending[0].next_action or pending[0].detail}",
                  file=sys.stderr)
        step_id = candidates[0].key
    phase, step = find_step(tree, step_id)
    roles = agent_names(step, code_root)
    if not roles:
        raise SystemExit(f"步骤 {step_id!r} 不是 agent 步骤（执行者：{step['executor']}）；照 mdf next 给的命令跑")
    status = next(s for s in stages if s.key == step_id)
    chapter = phase["chapter"]
    heading = tree["chapter_policy"]["fallback_heading"].format(order=phase["order"], title=phase["title"])
    lines = [
        f"# 任务简报：{slug} · {chapter['title']} / {step['title']}",
        "",
        "> 由 `python scripts/mdf.py brief` 生成。读完全文再动手；只写角色定义里规定的输出文件；"
        "完成后运行检查点命令，把结果原样报告。",
        "",
        "## 上下文",
        "",
        f"- 人物 slug：`{slug}`（角色定义里的 slug 占位符已替换为此值）",
        f"- 工作目录：仓库根目录；数据根目录：`{_display_path(root, code_root) or '.'}`",
        f"- 当前状态：{status.detail or '（无）'}",
        f"- 待办：{status.next_action or '按角色定义完成本步骤'}",
        f"- 依次扮演的角色：{'、'.join(roles)}（定义全文附在后面）",
    ]
    separate = root.resolve() != code_root.resolve()
    if separate:  # worktree 里没有私有语料：数据根经 MDF_DATA_ROOT 指向别处
        data, code = root.resolve().as_posix(), code_root.resolve().as_posix()
        lines.append(f"- 路径约定：下文的 `sources/…`、`output/…` 都在数据根目录 `{data}` 下；"
                     f"`scripts/…`、`agents/…`、`config/…` 在仓库 `{code}` 下。"
                     "读写语料与产物用数据根下的绝对路径；跑命令先 cd 到数据根目录，脚本写仓库里的绝对路径。")
    lines += [
        "",
        "## 规则",
        "",
        "- 规则以 `CLAUDE.md`（v6）为准；与 `AGENTS.md` 冲突时以 `CLAUDE.md` 为准。",
        f"- 引文必须逐字来自 `sources/{slug}/raw/` 的语料，不得编造或改字；网络来源最高 confidence: medium。",
        f"- 进度标题：开始时输出一行 `{heading}`（harness 有章节工具就改用工具）。",
    ]
    if step_id in ISOLATED_STEPS:
        lines.append("- 你是独立审查者：没有参与生成，不得沿用生成过程的结论；只依据包内容、语料与审查标准下裁决。")
    # 步骤自带的检查点优先：阶段检查点（如 validate sources）要等整个阶段做完才可能通过，
    # 分片抽取这类中间步骤若被要求先过它，执行者必然报「未通过」。
    checkpoint = step.get("checkpoint") or phase.get("checkpoint")
    if checkpoint:
        lines += ["", "## 完成标准", "", f"- 检查点：`{checkpoint.replace('{slug}', slug)}` 必须通过。"]
        if separate:
            runnable = shlex.join(checkpoint_argv(checkpoint, slug, code_root.resolve(), python="python"))
            lines.append(f"- 在本机这样跑：`cd '{root.resolve().as_posix()}' && {runnable}`")
        if step.get("checkpoint_note"):
            lines.append(f"- 说明：{step['checkpoint_note'].replace('{slug}', slug)}")
    for role in roles:
        body = (code_root / "agents" / f"{role}.md").read_text(encoding="utf-8")
        for placeholder in SLUG_PLACEHOLDERS:
            body = body.replace(placeholder, slug)
        lines += ["", "---", "", f"## 角色定义：{role}", "", body.rstrip()]
    return step_id, "\n".join(lines) + "\n"


def write_brief(slug: str, step_id: str, text: str, root: Path) -> Path:
    path = root / "output" / slug / "briefs" / f"{step_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def brief_prompt(brief_path: str) -> str:
    return f"读取 {brief_path} 并严格按其执行，完成后报告检查点结果。"


def _declared_flag(profile: dict[str, Any], key: str, what: str) -> str:
    flag = profile.get(key)
    if not flag:
        raise SystemExit(f"{profile.get('label', '该 harness')} 没有配置 {key}，不能指定{what}")
    return flag


def isolated_argv(profile: dict[str, Any], executable: str, prompt: str, *, model: str | None = None,
                  effort: str | None = None, data_dirs: Iterable[str] = (), usage: bool = False) -> list[str]:
    """把 isolated_run 模板拆成新进程的 argv（不经过 shell，提示词原样作为一个参数）。

    - 模型、推理强度是单值选项，插在提示词前面：codex 的 --model 在 exec 子命令里核实过，放到子命令前面没核实；
    - 目录授权放在模板末尾：claude 的 --add-dir 与 --allowedTools 一样是可变参数，排在提示词前面会把它吞掉；
      档案没有 data_dir_flag（pi 没有目录沙箱）就不加；
    - usage=True 时追加 usage_flags（机器可读的结果与用量）。
    """
    tokens = shlex.split(profile["isolated_run"])
    options: list[str] = []
    if model:
        options += [_declared_flag(profile, "model_flag", "模型"), model]
    if effort:
        options += [_declared_flag(profile, "effort_flag", "推理强度（effort）"), effort]
    at = tokens.index("{prompt}")
    argv = [executable, *tokens[1:at], *options, prompt, *tokens[at + 1:]]
    if profile.get("data_dir_flag"):
        for directory in data_dirs:
            argv += [profile["data_dir_flag"], str(directory)]
    if usage:
        argv += list(profile.get("usage_flags") or [])
    return argv


def _quote(arg: str) -> str:
    return arg if re.fullmatch(r"[\w@%+=:,./-]+", arg) else f'"{arg}"'


def launch_commands(brief_path: str, profiles: dict[str, Any], only: str | None = None,
                    data_dirs: Iterable[str] = ()) -> dict[str, str]:
    """给人看、可复制的启动命令（bash、PowerShell 都认双引号）。"""
    prompt = brief_prompt(brief_path)
    commands = {}
    for name, profile in profiles["harnesses"].items():
        if only in (None, name):
            executable = shlex.split(profile["isolated_run"])[0]
            argv = isolated_argv(profile, executable, prompt, data_dirs=data_dirs)
            commands[name] = " ".join(_quote(a) for a in argv)
    return commands


def checkpoint_argv(command: str, slug: str, code_root: Path = CODE_ROOT, python: str = sys.executable) -> list[str]:
    """阶段树里写的检查点命令（相对仓库根）变成在数据根目录下可直接执行的 argv：
    `python` 换成给定解释器，`scripts/*.py` 换成仓库里的绝对路径，其余参数（sources/… output/…）留给数据根解析。"""
    tokens = shlex.split(command.replace("{slug}", slug))
    if tokens and tokens[0] in ("python", "python3"):
        tokens[0] = python
    return [(code_root / t).as_posix() if t.startswith("scripts/") and t.endswith(".py") else t for t in tokens]


# ── CLI ───────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    slug_arg = _sibling("slug_rules").slug_arg
    parser = argparse.ArgumentParser(prog="mdf harness", description="harness 适配：检测、安装计划、任务简报")
    sub = parser.add_subparsers(dest="action")

    p = sub.add_parser("list", help="检测已安装的 harness 并核对适配文件")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("plan", help="打印把已发布包装进 harness 技能目录的命令（不执行）")
    p.add_argument("slug", type=slug_arg)
    p.add_argument("--target", required=True)
    p.add_argument("--scope", choices=("user", "project"), default="user")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("brief", help="为 agent 步骤生成自足任务简报")
    p.add_argument("slug", type=slug_arg)
    p.add_argument("step", nargs="?", help="步骤 id（默认下一个未完成的 agent 步骤）")
    p.add_argument("--harness", help="只打印该 harness 的启动命令")
    p.add_argument("--stdout", action="store_true", help="只把简报打印到标准输出，不写文件")
    p.add_argument("--root", help="数据根目录（默认 MDF_DATA_ROOT，再默认仓库根）")

    if not argv or (argv[0].startswith("-") and argv[0] not in ("-h", "--help")):
        argv = ["list", *argv]  # `mdf harness` / `mdf harness --json` 即 list
    args = parser.parse_args(argv)
    action = args.action
    if action == "list":
        report = list_report()
        print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else render_list(report), end="\n" if args.json else "")
        return 0 if report["ok"] else 1
    if action == "plan":
        plan = install_plan(args.slug, args.target, args.scope)
        print(json.dumps(plan, ensure_ascii=False, indent=2) if args.json else render_plan(plan), end="\n" if args.json else "")
        return 0
    root = Path(args.root or os.environ.get("MDF_DATA_ROOT") or CODE_ROOT).resolve()
    step_id, text = build_brief(args.slug, args.step, root)
    if args.stdout:
        print(text, end="")
        return 0
    path = _display_path(write_brief(args.slug, step_id, text, root), CODE_ROOT)
    print(f"[OK] 简报已写入 {path}")
    print("在有子代理的 harness 里交给子代理执行；否则在新进程里执行（各 harness 的命令）：")
    data_dirs = () if root == CODE_ROOT.resolve() else (root.as_posix(),)
    for name, command in launch_commands(path, load_profiles(), args.harness, data_dirs).items():
        print(f"  {name}: {command}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
