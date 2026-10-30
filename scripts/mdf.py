#!/usr/bin/env python3
"""mdf — Mind Distill Factory 的统一命令行入口。

所有 harness（Claude Code / Codex / pi …）和人都通过同一套命令驱动流水线：
编排逻辑写在 commands/ 与 AGENTS.md 里，确定性的活全部落在这里，输出既有
给人看的 Markdown，也有给程序读的 JSON（--json）。

    python scripts/mdf.py stages                 # 阶段逻辑树（含章节标签）
    python scripts/mdf.py init <slug>            # 建目录
    python scripts/mdf.py classify <slug> --primary governance --secondary philosophy,conduct   # 记下用户确认的类目
    python scripts/mdf.py status <slug> [--check] [--json]
    python scripts/mdf.py next <slug> [--json]   # 只看下一步
    python scripts/mdf.py doctor [--json]        # 环境与可选依赖自检
    python scripts/mdf.py index|reduce|stats <slug> ...
    python scripts/mdf.py validate <stage> <slug> [--strict]
    python scripts/mdf.py publish --slug <slug> [--dry-run] [--force]
    python scripts/mdf.py manifest backfill <slug> [--corpus-root DIR]
    python scripts/mdf.py harness [list|plan <slug> --target codex]
    python scripts/mdf.py brief <slug> [step] [--harness pi]
    python scripts/mdf.py run <slug> [step] --harness claude-code --yes   # 新进程执行，过程可读
    python scripts/mdf.py next <slug> --card     # 阶段卡；status <slug> --html 写可视化面板

数据根目录默认是仓库根；init/status/next/doctor/validate 可用 --root 或环境变量
MDF_DATA_ROOT 指向另一份数据（例如在 git worktree 里查看主仓库的私有语料）。
转交的子命令里，acquire/index/reduce/stats/clean/publish 认 MDF_DATA_ROOT（acquire/clean/publish 另有 --root），
manifest 仍以仓库根为准。gallery/ 入库，publish 与 validate published 总在仓库根（代码根）下读写它，
数据根在仓库外时也不例外。
"""

import argparse
import functools
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Callable
_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:  # 按路径加载本模块时也能找到同目录的 workspace
    sys.path.insert(0, _SCRIPTS_DIR)
from sibling import load_sibling  # noqa: E402  按路径加载兄弟模块的唯一入口
from workspace import Workspace, data_root  # noqa: E402  数据根解析规则只在 workspace.py 定义

CODE_ROOT = Path(__file__).resolve().parent.parent


@functools.lru_cache(maxsize=None)
def _module(name: str) -> Any:
    return load_sibling(name, f"_mdf_cli_{name}")


def _delegate(module: str, argv: list[str], cwd: Path | None = None) -> int:
    """以给定 argv 调用某个脚本的 main()，把 SystemExit 转成返回码。"""
    old_argv, old_cwd = sys.argv, os.getcwd()
    sys.argv = [f"scripts/{module}.py", *argv]
    try:
        if cwd is not None:
            os.chdir(cwd)
        result = _module(module).main()
        return int(result or 0)
    except SystemExit as e:
        if e.code is None or isinstance(e.code, int):
            return e.code or 0
        # `raise SystemExit("说明")` 由解释器打印到 stderr；在进程内接住后要自己打印。
        print(e.code, file=sys.stderr)
        return 1
    finally:
        sys.argv = old_argv
        os.chdir(old_cwd)


def _data_root(arg: str | None) -> Path:
    return data_root(arg)


def _risk_notice(root: Path, *, stream: Any = None) -> None:
    """数据根在临时 worktree 里就提醒（发现 0）。文本输出走 stdout，跟着阶段卡一起贴给用户；JSON 输出走 stderr。"""
    notice = Workspace(root).risk_notice()
    if notice:
        print(notice, file=stream or sys.stdout)


def _print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


# ── 子命令 ────────────────────────────────────────────────────────────


def cmd_stages(args: argparse.Namespace) -> int:
    ps = _module("pipeline_status")
    tree = ps.load_stage_tree(CODE_ROOT)
    if args.json:
        _print_json(tree)
    elif args.mermaid:
        print(ps.render_mermaid(tree), end="")
    else:
        print(ps.render_tree(tree), end="")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    root = _data_root(args.root)
    created = []
    for rel in (f"sources/{args.slug}/raw", f"sources/{args.slug}/processed", f"output/{args.slug}"):
        path = root / rel
        if not path.exists():
            path.mkdir(parents=True)
            created.append(rel)
    print(f"[OK] {args.slug}: " + ("新建 " + "、".join(created) if created else "目录均已存在"))
    print(f"下一步：把原始资料放进 sources/{args.slug}/raw/，然后运行 python scripts/mdf.py status {args.slug}")
    return 0


def cmd_classify(args: argparse.Namespace) -> int:
    """记下用户在阶段 0.3 确认的类目。只在用户确认之后调用；不带 --primary 时只显示当前记录。"""
    cls = _module("classification")
    root = _data_root(args.root)
    if args.primary is None:
        try:
            data = cls.load(root, args.slug)
        except ValueError as exc:
            print(f"[FAIL] {exc}", file=sys.stderr)
            return 1
        if data is None:
            print(f"{args.slug}：类目尚未确认。先让用户确认，再 mdf classify {args.slug} --primary <主类> --secondary <副类1,副类2>")
            return 1
        print(f"{args.slug}：{cls.describe(data)}（{data.get('confirmed_at', '')} 确认）")
        return 0
    secondary = [c.strip() for c in (args.secondary or "").split(",") if c.strip()]
    try:
        path = cls.write(root, args.slug, args.primary, secondary, args.name)
    except ValueError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1
    data = cls.load(root, args.slug)
    print(f"[OK] {args.slug}：{cls.describe(data)} → {path.relative_to(root).as_posix()}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    ps = _module("pipeline_status")
    root = _data_root(args.root)
    stages = ps.collect_status(args.slug, root, check=getattr(args, "check", False),
                               gallery_root=Workspace(root).gallery)
    if args.html:
        from datetime import datetime

        path = Path(args.html) if args.html != "-" else root / "output" / args.slug / "status.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        html = ps.render_html(args.slug, stages, runs=ps.load_runs(root, args.slug),
                              generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"))
        path.write_text(html, encoding="utf-8", newline="\n")
        print(f"[OK] 进度面板已写入 {path}")
        print(ps.progress_bar(stages))
    elif args.json:
        _print_json(ps.to_json(args.slug, stages))
        _risk_notice(root, stream=sys.stderr)
    else:
        print(ps.to_markdown(args.slug, stages), end="")
        print("\n" + ps.progress_bar(stages))
        _risk_notice(root)
    return 0


def cmd_next(args: argparse.Namespace) -> int:
    ps = _module("pipeline_status")
    root = _data_root(args.root)
    stages = ps.collect_status(args.slug, root, gallery_root=Workspace(root).gallery)
    nxt = ps.next_stage(stages)
    if args.card:
        print(ps.render_card(args.slug, stages, shard_count=_module("run_unit").shard_count(root, args.slug)), end="")
    elif args.json:
        _print_json({"slug": args.slug, "complete": nxt is None, "next": ps.to_json(args.slug, stages)["next"]})
        _risk_notice(root, stream=sys.stderr)
        return 0
    elif nxt is None:
        print("全部完成。")
    else:
        print(f"{nxt.chapter.get('title', '')} / {nxt.title}：{nxt.next_action or nxt.detail}")
    _risk_notice(root)
    return 0


def cmd_budget(args: argparse.Namespace) -> int:
    ce = _module("cost_estimator")
    shard_dir = _data_root(args.root) / "sources" / args.slug / "processed" / "local_shards"
    try:
        estimate = json.loads((shard_dir / "cost_estimate.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print(f"没有可读的 {shard_dir / 'cost_estimate.json'}：先运行 mdf index {args.slug}")
        return 1
    budget = ce.load_budget(CODE_ROOT)
    reason = budget.verdict(estimate)
    if reason is None:
        print(f"未超预算：预计输入 {int(estimate['tokens']['selected_input']):,} token"
              f"（上限 {budget.max_selected_input_tokens or 0:,}），无需批准。")
        return 0
    print(reason)
    if not args.approve:
        print("先用 AskUserQuestion 问用户；用户选全量处理后，加 --approve 记下批准。")
        return 3
    path = ce.write_approval(shard_dir, estimate)
    print(f"[OK] 已记下用户批准：{reason}（{path}）")
    return 0


OPTIONAL_DEPS = [
    ("fitz", "PyMuPDF", "pdf", "PDF 文本抽取（首选）"),
    ("pypdf", "pypdf", "pdf", "PDF 文本抽取（回退）"),
    ("PIL", "Pillow", "ocr", "OCR 图像处理"),
    ("rapidocr", "rapidocr", "ocr", "OCR 默认引擎（PP-OCRv6，校准实测最好）"),
    ("onnxruntime", "onnxruntime", "ocr", "rapidocr 的推理后端"),
    ("paddleocr", "PaddleOCR", "ocr-high-accuracy", "OCR 高精度档"),
    ("opencc", "opencc-python-reimplemented", "provenance", "繁简异体折叠（P1/P2 比对）"),
]


def doctor_report(root: Path) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str, required: bool = True) -> None:
        checks.append({"name": name, "ok": ok, "required": required, "detail": detail})

    add("Python ≥ 3.11", sys.version_info >= (3, 11), sys.version.split()[0])
    add("git", shutil.which("git") is not None, shutil.which("git") or "未找到", required=False)
    for rel in ("config/taxonomy.json", "config/defaults.json", "config/pipeline_stages.json"):
        path = CODE_ROOT / rel
        try:
            json.loads(path.read_text(encoding="utf-8"))
            add(rel, True, "可解析")
        except (OSError, ValueError) as e:
            add(rel, False, f"{type(e).__name__}")
    for rel in ("sources", "output"):
        add(f"数据目录 {rel}/", (root / rel).is_dir(), str(root / rel), required=False)
    gallery = Workspace(root).gallery  # 发布产物入库，在代码根下
    add("发布目录 gallery/", gallery.is_dir(), str(gallery), required=False)
    for module, package, extra, purpose in OPTIONAL_DEPS:
        found = importlib.util.find_spec(module) is not None
        add(f"可选依赖 {package}", found, purpose + ("" if found else f"；安装：pip install -e .[{extra}]"), required=False)
    exe = _module("pdf_quality").paddleocr_json_exe()
    add("可选引擎 PaddleOCR-json", exe is not None, str(exe) if exe else
        "未配置（可选；环境变量 MDF_PADDLEOCR_JSON 指向 PaddleOCR-json.exe 或其目录，Umi-OCR 插件目录即可）",
        required=False)
    harness = _module("harness")
    profiles = harness.load_profiles(CODE_ROOT)
    for name, path in harness.detect(profiles).items():
        add(f"harness {profiles['harnesses'][name]['label']}", path is not None,
            path or "未安装（可选；详情 mdf harness）", required=False)
    return {
        "schema": "mdf-doctor-v1",
        "data_root": str(root),
        "ok": all(c["ok"] for c in checks if c["required"]),
        "checks": checks,
    }


def cmd_doctor(args: argparse.Namespace) -> int:
    report = doctor_report(_data_root(args.root))
    if args.json:
        _print_json(report)
    else:
        print(f"## 环境自检（数据根目录：{report['data_root']}）\n")
        print("| 项目 | 结果 | 说明 |\n|---|---|---|")
        for c in report["checks"]:
            mark = "✅" if c["ok"] else ("❌" if c["required"] else "⚠️")
            print(f"| {c['name']} | {mark} | {c['detail']} |")
        print("\n" + ("必需项全部满足。" if report["ok"] else "有必需项未满足，先修复再运行流水线。"))
    return 0 if report["ok"] else 1


def _passthrough(module: str, prefix: list[str] | None = None) -> Callable[[argparse.Namespace], int]:
    def run(args: argparse.Namespace) -> int:
        return _delegate(module, [*(prefix or []), *args.rest], cwd=CODE_ROOT)
    return run


def cmd_validate(args: argparse.Namespace) -> int:
    # validate_output 的路径全部相对 cwd 解析（不读 config/），切到数据根目录即可。
    argv = [args.stage, args.slug, *(["--strict"] if args.strict else [])]
    return _delegate("validate_output", argv, cwd=_data_root(args.root))


# ── 解析 ──────────────────────────────────────────────────────────────


ROOT_HELP = "数据根目录（默认 MDF_DATA_ROOT，再默认仓库根）"


def build_parser() -> argparse.ArgumentParser:
    slug_arg = _module("slug_rules").slug_arg
    parser = argparse.ArgumentParser(prog="mdf", description="Mind Distill Factory 统一入口")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("stages", help="打印流水线阶段树（含章节标签）")
    p.add_argument("--json", action="store_true")
    p.add_argument("--mermaid", action="store_true", help="输出 Mermaid 流程图")
    p.set_defaults(func=cmd_stages)

    p = sub.add_parser("init", help="建立人物目录")
    p.add_argument("slug", type=slug_arg)
    p.add_argument("--root", help=ROOT_HELP)
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("classify", help="记下用户确认的类目（1 主 + 至多 2 副），下游简报只读不选")
    p.add_argument("slug", type=slug_arg)
    p.add_argument("--primary", help="主类 id（config/taxonomy.json）；不给则只显示当前记录")
    p.add_argument("--secondary", help="副类 id，逗号分隔，至多 2 个")
    p.add_argument("--name", help="人物显示名，如 墨子")
    p.add_argument("--root", help=ROOT_HELP)
    p.set_defaults(func=cmd_classify)

    for name, func, help_text in (("status", cmd_status, "查看流水线状态"), ("next", cmd_next, "只看下一步")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("slug", type=slug_arg)
        p.add_argument("--json", action="store_true")
        p.add_argument("--root", help=ROOT_HELP)
        if name == "status":
            p.add_argument("--check", action="store_true", help="同时运行各阶段的确定性校验（较慢）")
            p.add_argument("--html", nargs="?", const="-", metavar="PATH",
                           help="写可视化进度面板（默认 output/<slug>/status.html）")
        else:
            p.add_argument("--card", action="store_true", help="输出阶段卡（进入阶段时贴给用户）")
        p.set_defaults(func=func)

    p = sub.add_parser("budget", help="分片抽取的预算核对；用户同意超预算全量处理后，--approve 记下批准")
    p.add_argument("slug", type=slug_arg)
    p.add_argument("--approve", action="store_true", help="记下用户批准当前规模（须先在对话里问过用户）")
    p.add_argument("--root", help=ROOT_HELP)
    p.set_defaults(func=cmd_budget)

    p = sub.add_parser("doctor", help="环境与可选依赖自检")
    p.add_argument("--json", action="store_true")
    p.add_argument("--root", help=ROOT_HELP)
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("validate", help="运行某阶段的校验")
    p.add_argument("stage")
    p.add_argument("slug", type=slug_arg)
    p.add_argument("--strict", action="store_true")
    p.add_argument("--root", help=ROOT_HELP)
    p.set_defaults(func=cmd_validate)

    for name, (module, prefix, help_text) in PASSTHROUGH.items():
        # 只为 `mdf --help` 列出；真正的参数在 main() 里原样转交，避免 argparse
        # 吞掉 `--help`、`--slug` 这类以横线开头的参数。
        p = sub.add_parser(name, help=help_text, add_help=False)
        p.add_argument("rest", nargs=argparse.REMAINDER)
        p.set_defaults(func=_passthrough(module, prefix))
    return parser


PASSTHROUGH: dict[str, tuple[str, list[str], str]] = {
    "acquire-plan": ("acquisition_planner", [], "采集计划：候选清单 → 白名单站点目录核对 → 用户批准后交给 acquire"),
    "acquire-settings": ("acquisition_settings", [], "采集的本地设置（联系方式、法域），问过用户后存在数据根"),
    "acquire": ("acquire", [], "合规采集文献到 sources/{slug}/raw/acquired/"),
    "index": ("local_source_pipeline", ["index"], "抽取、清洗、分片 sources/{slug}/raw"),
    "clean": ("clean_corpus", [], "查看清洗报告；clean check <文件> 预检单个文件"),
    "reduce": ("local_source_pipeline", ["reduce"], "合并分片抽取结果"),
    "stats": ("local_source_pipeline", ["stats"], "分片统计"),
    "metrics": ("persona_metrics", [], "主张账本、来源集中度、文体指纹、对话漂移（代理指标）"),
    "publish": ("publish_skill", [], "事务化发布到 gallery"),
    "manifest": ("package_manifest", [], "发布清单工具（backfill）"),
    "ocr": ("ocr_calibrate", [], "OCR 校准（合成扫描件对真值：CER、逐字存活率）与扫描件逐页诊断"),
    "harness": ("harness", [],"harness 适配：检测与核对（list）、安装命令（plan，只打印）"),
    "brief": ("harness", ["brief"], "为 agent 步骤生成自足任务简报，供子代理或新进程执行"),
    "run": ("stage_runner", [], "把 agent 步骤交给新进程执行：阶段卡、心跳、日志、闸门、运行记录"),
}


def main(argv: list[str] | None = None) -> int:
    if sys.platform.startswith("win"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except AttributeError:
            pass
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in PASSTHROUGH:
        module, prefix, _ = PASSTHROUGH[argv[0]]
        return _delegate(module, [*prefix, *argv[1:]], cwd=CODE_ROOT)
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
