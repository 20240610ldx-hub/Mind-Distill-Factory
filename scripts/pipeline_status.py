#!/usr/bin/env python3
"""流水线状态：只读地检查一个人物 slug 走到了哪一步、下一步该做什么。

这是用户掌控流水线的主视图，也是各 harness（Claude Code / Codex / pi）的
编排者决定下一步的依据：人看 Markdown 表格，程序读 JSON（schema
`pipeline-status-v1`）。默认只看文件是否存在、状态文件写了什么，毫秒级完成；
`check=True` 时额外跑各阶段的确定性校验（P2 在大语料上需要数秒）。

状态取值：done / in_progress / pending / failed / blocked / skipped。
"""

import functools
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable
_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:  # 按路径加载本模块时也能找到同目录的 sibling / workspace
    sys.path.insert(0, _SCRIPTS_DIR)
from sibling import load_sibling  # noqa: E402  按路径加载兄弟模块的唯一入口

SCHEMA = "pipeline-status-v1"
STATE_LABELS = {
    "done": "✅ 完成",
    "in_progress": "⏳ 进行中",
    "pending": "⬜ 待办",
    "failed": "❌ 未通过",
    "blocked": "⛔ 受阻",
    "skipped": "➖ 跳过",
}
FINISHED = {"done", "skipped"}
EXECUTOR_LABELS = {"script": "脚本", "agent": "agent", "human": "人工"}
REQUIRED_REFS = ("cases.md", "evidence.md", "voice.md")


@dataclass
class StageStatus:
    key: str
    title: str
    state: str
    detail: str = ""
    next_action: str = ""
    artifacts: list[str] = field(default_factory=list)
    phase: str = ""
    chapter: dict[str, str] = field(default_factory=dict)


def load_stage_tree(code_root: Path | None = None) -> dict[str, Any]:
    """读 config/pipeline_stages.json（代码仓库里的唯一来源，与数据根目录无关）。"""
    code_root = code_root or Path(__file__).resolve().parent.parent
    return json.loads((code_root / "config" / "pipeline_stages.json").read_text(encoding="utf-8"))


@functools.lru_cache(maxsize=None)
def _sibling(name: str) -> Any:
    return load_sibling(name)


def _rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def _cmd(*parts: str) -> str:
    return "`python scripts/mdf.py " + " ".join(parts) + "`"


# ── 各阶段检查 ────────────────────────────────────────────────────────


def _stage_init(ctx: "Ctx") -> StageStatus:
    status = StageStatus("init", "目录初始化", "pending")
    dirs = [ctx.root / "sources" / ctx.slug, ctx.root / "output" / ctx.slug, ctx.root / "gallery" / ctx.slug]
    existing = [d for d in dirs if d.exists()]
    if existing:
        status.state = "done"
        status.detail = "已建立 " + "、".join(_rel(ctx.root, d) for d in existing)
    else:
        status.detail = "尚未建立人物目录"
        status.next_action = _cmd("init", ctx.slug)
    return status


def _stage_classify(ctx: "Ctx") -> StageStatus:
    """用户确认的类目（sources/{slug}/classification.json）。下游简报靠它，不让 agent 自选。"""
    cls = _sibling("classification")
    status = StageStatus("classify", "类目确认", "pending")
    try:
        data = cls.load(ctx.root, ctx.slug)
    except ValueError as exc:
        status.state = "failed"
        status.detail = str(exc)[:120]
        status.next_action = "重新让用户确认类目，再 " + _cmd("classify", ctx.slug, "--primary", "<主类>", "--secondary", "<副类>")
        return status
    if data is None and (ctx.root / "output" / ctx.slug / "frameworks.zh.json").exists():
        # 早于类目通道的人物：类目已写进产物，以产物为准，不倒逼补录。
        status.state = "skipped"
        status.detail = "未记录（早于类目通道；类目以已生成的产物为准）"
        return status
    if data is None:
        status.detail = "类目尚未确认"
        status.next_action = ("按 config/taxonomy.json 推荐 1 主 + 至多 2 副，用 AskUserQuestion 让用户确认，再 "
                              + _cmd("classify", ctx.slug, "--primary", "<主类>", "--secondary", "<副类1,副类2>"))
        return status
    status.state = "done"
    status.detail = cls.describe(data)
    status.artifacts = [_rel(ctx.root, cls.path_for(ctx.root, ctx.slug))]
    return status


def _stage_clean(ctx: "Ctx") -> StageStatus:
    processed = ctx.root / "sources" / ctx.slug / "processed"
    report_path = processed / "cleaning_report.json"
    status = StageStatus("clean", "清洗与质量闸门", "pending")
    if not ctx.has_raw:
        status.state = "skipped"
        status.detail = "没有本地素材"
        return status
    report = _read_json(report_path)
    if not isinstance(report, dict):
        if (processed / "local_shards" / "manifest.json").exists():
            status.state = "skipped"
            status.detail = "该语料用旧版流程分片，没有清洗报告（重跑 index 可补）"
        else:
            status.detail = "尚未清洗（由 index 一并完成）"
            status.next_action = _cmd("index", ctx.slug)
        return status
    status.artifacts = [_rel(ctx.root, report_path)]
    rejected = report.get("rejected_sources") or []
    flagged = report.get("flagged_sources") or []
    status.detail = f"{report.get('source_count', 0)} 个来源已清洗" + (
        f"，{len(flagged)} 个需人工复核" if flagged else ""
    ) + (f"，{len(rejected)} 个被拒" if rejected else "")
    if rejected:
        status.state = "blocked"
        status.next_action = "查看 cleaning_report.json 的 rejected_sources：乱码/空文本来源需换版本或走 OCR"
    else:
        status.state = "done"
    return status


def _stage_sources(ctx: "Ctx") -> StageStatus:
    raw = ctx.root / "sources" / ctx.slug / "raw"
    files = [p for p in raw.rglob("*") if p.is_file()] if raw.exists() else []
    usable = _sibling("source_registry").indexable_raw_files(raw)
    log = ctx.root / "sources" / ctx.slug / "processed" / "acquisition_log.jsonl"
    status = StageStatus("sources", "素材入库", "pending")
    if usable:
        status.state = "done"
        status.detail = f"{len(usable)} 个可处理文件" + (
            f"（另有 {len(files) - len(usable)} 个不支持的格式）" if len(files) > len(usable) else ""
        )
        status.artifacts = [_rel(ctx.root, raw)] + ([_rel(ctx.root, log)] if log.exists() else [])
    else:
        status.detail = "sources/{0}/raw/ 里还没有 PDF/TXT/MD".format(ctx.slug)
        status.next_action = f"把原始资料放进 `sources/{ctx.slug}/raw/`，或运行 {_cmd('acquire', ctx.slug, '--help')}"
    ctx.has_raw = bool(usable)
    return status


def _stage_index(ctx: "Ctx") -> StageStatus:
    processed = ctx.root / "sources" / ctx.slug / "processed"
    manifest_path = processed / "local_shards" / "manifest.json"
    status = StageStatus("index", "抽取与分片", "pending")
    if not ctx.has_raw:
        status.state = "skipped"
        status.detail = "没有本地素材（网络检索已禁用：先用 mdf acquire 合规采集）"
        return status
    manifest = _read_json(manifest_path)
    if not isinstance(manifest, dict):
        status.next_action = _cmd("index", ctx.slug)
        status.detail = "尚未生成分片清单"
        return status
    shards = manifest.get("shards") or []
    mode = manifest.get("sampling_mode", "exhaustive")
    status.state = "done"
    status.detail = f"{len(shards)} 个分片，抽样模式 {mode}"
    status.artifacts = [_rel(ctx.root, manifest_path)]
    return status


def _stage_extract(ctx: "Ctx") -> StageStatus:
    status_path = ctx.root / "sources" / ctx.slug / "processed" / "local_shards" / "task_status.json"
    status = StageStatus("extract", "分片抽取（agent）", "pending")
    if not ctx.has_raw:
        status.state = "skipped"
        status.detail = "没有本地素材"
        return status
    if not status_path.exists():
        status.detail = "尚未初始化任务状态"
        status.next_action = _cmd("index", ctx.slug)
        return status
    ts = _sibling("task_status")
    try:
        data = ts.refresh_status(ts.load_status(status_path))
    except Exception as e:  # 状态文件损坏也要如实报告，而不是让整个 status 崩掉
        status.state = "failed"
        status.detail = f"任务状态文件无法读取：{type(e).__name__}"
        return status
    units = data.get("input_units") or []
    done = len(data.get("completed_units") or [])
    failed = data.get("failed_units") or []
    status.artifacts = [_rel(ctx.root, status_path)]
    status.detail = f"{done}/{len(units)} 个分片已完成" + (f"，{len(failed)} 个失败" if failed else "")
    estimate = _read_json(status_path.parent / "cost_estimate.json")
    hold = None
    if isinstance(estimate, dict):
        ce = _sibling("cost_estimator")
        status.detail += f"，预计输入 {int((estimate.get('tokens') or {}).get('selected_input') or 0):,} token"
        over = ce.load_budget(Path(__file__).resolve().parent.parent).verdict(estimate)
        if over and ce.Budget.covers(_read_json(status_path.parent / ce.APPROVAL_FILE), estimate):
            status.detail += "（超预算，用户已批准）"
        elif over:
            hold = over
    state = data.get("status")
    merged = (ctx.root / "sources" / ctx.slug / "processed" / "user_sources.json").exists()
    if state == "completed":
        status.state = "done"
    elif merged and done:
        # 旧流程按抽样派工，但 task_status 登记了全部分片；已合并说明抽取阶段已收尾。
        status.state = "done"
        status.detail += "（已合并；其余分片按抽样未处理）"
    elif state == "blocked":
        status.state = "blocked"
        status.next_action = "有分片连续失败被标记 blocked：先拆分该分片或降低并发，再重试"
    elif hold:  # 超预算且没有覆盖当前规模的批准：用户拍板前不得派 worker
        status.state = "blocked"
        status.next_action = (f"{hold}。先用 AskUserQuestion 让用户选：全量处理 / 分层抽样 / 降低预算 / 取消；"
                              f"选全量就运行 {_cmd('budget', ctx.slug, '--approve')}，用户选定前不得派 worker")
    else:
        status.state = "in_progress" if done or failed else "pending"
        runnable = [u.get("unit_id") for u in ts.runnable_units(data)][:5]
        if runnable:
            status.next_action = "派发 local-source-worker 处理：" + "、".join(str(u) for u in runnable)
    return status


SOURCE_FILES = ("primary_sources.json", "secondary_sources.json", "expression_dna.json")


def _stage_reduce(ctx: "Ctx") -> StageStatus:
    processed = ctx.root / "sources" / ctx.slug / "processed"
    status = StageStatus("reduce", "合并与本地补充", "pending")
    expected = (["user_sources.json"] if ctx.has_raw else []) + list(SOURCE_FILES)
    present = [name for name in expected if (processed / name).exists()]
    missing = [name for name in expected if name not in present]
    status.artifacts = [_rel(ctx.root, processed / name) for name in present]
    if not missing:
        status.state = "done"
        status.detail = f"{len(present)} 个素材文件齐备"
        if ctx.check:
            errors = _hard(_validator().validate_sources, ctx)
            if errors:
                status.state = "failed"
                status.detail = f"素材校验 {len(errors)} 个错误：{errors[0][:80]}"
                status.next_action = _cmd("validate", "sources", ctx.slug)
        return status
    status.state = "in_progress" if present else "pending"
    status.detail = "缺少 " + "、".join(missing)
    if "user_sources.json" in missing:
        status.next_action = _cmd("reduce", ctx.slug)
    else:
        status.next_action = "派发 source-researcher 从本地语料补齐（禁止网络检索）：" + "、".join(missing)
    return status


def _stage_principles(ctx: "Ctx") -> StageStatus:
    out = ctx.root / "output" / ctx.slug
    files = sorted(out.glob("principles_*.json")) if out.exists() else []
    status = StageStatus("principles", "原则提取", "pending", artifacts=[_rel(ctx.root, p) for p in files])
    if not files:
        status.next_action = "派发 principle-extractor（Stage 2）"
        status.detail = "output/{0}/ 下没有 principles_*.json".format(ctx.slug)
        return status
    status.state = "done"
    status.detail = f"{len(files)} 个原则文件"
    if ctx.check:
        errors = _hard(_validator().validate_principles, ctx)
        if errors:
            status.state = "failed"
            status.detail = f"原则校验 {len(errors)} 个错误：{errors[0][:80]}"
            status.next_action = _cmd("validate", "principles", ctx.slug)
    return status


def _stage_frameworks(ctx: "Ctx") -> StageStatus:
    out = ctx.root / "output" / ctx.slug
    names = ("framework_core.json", "frameworks.zh.json", "framework_alignment_review.md")
    present = [n for n in names if (out / n).exists()]
    status = StageStatus("frameworks", "框架合成", "pending", artifacts=[_rel(ctx.root, out / n) for n in present])
    if len(present) == len(names):
        review = (out / "framework_alignment_review.md").read_text(encoding="utf-8", errors="replace")
        if "[PASS]" in review:
            status.state = "done"
            status.detail = "共同核心 + 中文框架 + 自检 [PASS]"
        else:
            status.state = "failed"
            status.detail = "框架自检结论不是 [PASS]"
            status.next_action = "按 framework_alignment_review.md 重派对应 unit（Stage 3）"
        return status
    if (out / "framework_core.json").exists() and (out / "SKILL.md").exists():
        # v6 早期包（如样板）只留下 framework_core.json，其余中间产物未归档。
        status.state = "done"
        status.detail = "只有 framework_core.json（其余中间产物未归档）"
        return status
    status.state = "in_progress" if present else "pending"
    status.detail = "缺少 " + "、".join(n for n in names if n not in present)
    status.next_action = "继续 Stage 3（framework-core-synthesizer → framework-synthesizer-zh → alignment-reviewer）"
    return status


def _stage_assemble(ctx: "Ctx") -> StageStatus:
    skill = ctx.root / "output" / ctx.slug / "SKILL.md"
    status = StageStatus("assemble", "核心层组装", "pending")
    if not skill.exists():
        status.next_action = "派发 skill-assembler（Stage 4）"
        status.detail = "output/{0}/SKILL.md 尚未生成".format(ctx.slug)
        return status
    v6 = _validator().is_v6_skill(skill.read_text(encoding="utf-8", errors="replace"))
    status.state = "done"
    status.detail = "v6 中文核心" if v6 else "legacy 双语单文件"
    status.artifacts = [_rel(ctx.root, skill)]
    ctx.is_v6 = v6
    return status


def _stage_attachments(ctx: "Ctx") -> StageStatus:
    refs = ctx.root / "output" / ctx.slug / "references"
    status = StageStatus("attachments", "附件生成", "pending")
    if not ctx.is_v6:
        status.state = "skipped"
        status.detail = "legacy 包没有附件层" if (ctx.root / "output" / ctx.slug / "SKILL.md").exists() else "等待核心层"
        if status.detail == "等待核心层":
            status.state = "pending"
        return status
    present = [n for n in REQUIRED_REFS if (refs / n).exists()]
    status.artifacts = [_rel(ctx.root, refs / n) for n in present]
    if len(present) == len(REQUIRED_REFS):
        status.state = "done"
        status.detail = "cases / evidence / voice 齐备"
    else:
        status.state = "in_progress" if present else "pending"
        status.detail = "缺少 " + "、".join(n for n in REQUIRED_REFS if n not in present)
        status.next_action = _attachments_todo(present)
    return status


# 每份附件由谁产出；voice.md 与案例索引回写是 skill-assembler 的第二次调用
ATTACHMENT_AUTHORS = {"cases.md": "case-builder", "evidence.md": "evidence-carder"}


def _attachments_todo(present: list[str]) -> str:
    """只派缺的那一份：恢复执行时重做已有附件既白花钱，又可能覆盖已过审的产物。"""
    authors = [role for name, role in ATTACHMENT_AUTHORS.items() if name not in present]
    todo = (f"派发 {' / '.join(authors)}，再" if authors else "") + "由 skill-assembler 续写 voice.md 并回写案例索引（Stage 4.5）"
    kept = [name for name in ATTACHMENT_AUTHORS if name in present]
    if kept:
        todo += f"；{'、'.join(kept)} 已有，不要重做"
    return todo


def _stage_gates(ctx: "Ctx") -> StageStatus:
    status = StageStatus("gates", "P1–P6 包校验", "pending")
    if not ctx.is_v6:
        status.state = "skipped" if (ctx.root / "output" / ctx.slug / "SKILL.md").exists() else "pending"
        status.detail = "legacy 包走 skill 阶段校验" if status.state == "skipped" else "等待核心层"
        return status
    if not ctx.check:
        records = _sibling("gate_records")
        current = records.package_gate_current(ctx.root / "output" / ctx.slug)
        if current:
            status.state = "done"
            status.detail = ("上次校验通过，产物未改动（加 --check 重新校验）"
                             + _coverage_hint(records.package_gate_notes(ctx.root / "output" / ctx.slug)))
            return status
        status.detail = ("上次校验后产物改过，需要重新校验" if current is False
                         else "未检查（加 --check 运行确定性闸门）")
        status.next_action = _cmd("validate", "package", ctx.slug)
        return status
    findings = _run(_validator().validate_package, ctx)
    errors = [e for e in findings if not e.startswith("WARNING:")]
    if errors:
        status.state = "failed"
        status.detail = f"{len(errors)} 个错误：{errors[0][:80]}"
        status.next_action = _cmd("validate", "package", ctx.slug)
    else:
        status.state = "done"
        status.detail = "P1–P6 与 M4 加固规则全部通过" + _coverage_hint(findings)
    return status


def _coverage_hint(lines: list[str]) -> str:
    """P2 只逐字核对了部分证据卡时，在阶段卡上一直挂着（鲁迅验收发现 11）。不挡路：语料外的卡已封顶 medium。"""
    coverage_type = _sibling("verify_provenance").EvidenceCoverage
    for line in lines:
        coverage = coverage_type.parse(line)
        if coverage and coverage.gap():
            return f"；但{coverage.gap()}——征得用户同意后用 mdf acquire 把原典采进 raw/，再让 evidence-carder 改卡"
    return ""


def _stage_review(ctx: "Ctx") -> StageStatus:
    review_md = ctx.root / "output" / ctx.slug / "review.md"
    verdict = _sibling("package_manifest").read_review_verdict(review_md)
    status = StageStatus("review", "质量审查", "pending")
    v = verdict["verdict"]
    if v == "MISSING":
        status.detail = "没有 review.md"
        status.next_action = "派发隔离的 quality-reviewer 子代理（Stage 5，不得自审）"
    elif v == "PASS":
        status.state = "done"
        status.detail = "审查结论 PASS"
        status.artifacts = [_rel(ctx.root, review_md)]
    else:
        status.state = "failed"
        status.detail = f"审查结论 {v}" + (f"：{verdict['detail'][:60]}" if verdict.get("detail") else "")
        status.next_action = "按 review.md 返回 Stage 4 / 4.5 修订" if v == "REVISE" else "检查 review.md 的「## 裁决」节"
        status.artifacts = [_rel(ctx.root, review_md)]
    return status


def _stage_publish(ctx: "Ctx") -> StageStatus:
    gallery = ctx.root / "gallery" / ctx.slug
    pm = _sibling("package_manifest")
    status = StageStatus("publish", "发布", "pending")
    manifest, errors = pm.load_manifest(gallery / pm.MANIFEST_NAME)
    if manifest is None:
        status.next_action = _cmd("publish", "--slug", ctx.slug)
        if not gallery.exists():
            status.detail = "尚未发布"
            _confidence_gate_ahead(ctx, status)
        elif errors and errors[0].startswith("MANIFEST_OUTDATED"):
            status.state = "failed"
            status.detail = "已发布但 manifest 是旧版 v1（无构建期证明）"
            status.next_action = _cmd("manifest", "backfill", ctx.slug) + " 或重新发布"
        else:
            status.state = "failed"
            status.detail = errors[0].split(":", 1)[0] if errors else "manifest 无法读取"
        return status
    status.artifacts = [_rel(ctx.root, gallery)]
    review = (manifest.get("review") or {}).get("verdict", "无记录")
    status.state = "done"
    status.detail = f"已发布（manifest v{manifest.get('manifest_version')}，审查记录 {review}）"
    coverage = _sibling("verify_provenance").EvidenceCoverage.from_attestation(
        (manifest.get("attestation") or {}).get("p2"))
    if coverage and coverage.gap():
        status.detail += f"；{coverage.gap()}，这些卡语料外、最高 medium"
    if ctx.check:
        hard = [e for e in _validator().validate_published(ctx.slug, ctx.root) if not e.startswith("WARNING:")]
        if hard:
            status.state = "failed"
            status.detail = f"发布包校验 {len(hard)} 个错误：{hard[0][:80]}"
            status.next_action = _cmd("validate", "published", ctx.slug)
    return status


def _confidence_gate_ahead(ctx: "Ctx", status: StageStatus) -> None:
    """发布前就亮出置信度门（鲁迅 GUI 复验问题 2）：以前要等 mdf publish 报 BLOCKED 才知道，
    可「补素材 / 接受不入 gallery / --force」是该先问用户的决定。门槛与判定都用 publish_skill 的那一份。"""
    publisher = _sibling("publish_skill")
    score = publisher.read_distill_confidence(ctx.root / "output" / ctx.slug)
    allowed, _ = publisher.confidence_gate(score, False, "PASS")
    if allowed or score is None:  # 读不到分数时，框架阶段还没做完，留给前面的阶段报
        return
    status.state = "blocked"
    status.detail = f"尚未发布；distill_confidence={score} 低于质量门 3，发布会被拒（BLOCKED_LOW_CONFIDENCE）"
    status.next_action = ("先用 AskUserQuestion 让用户选：补一手素材重跑 / 接受不入 gallery / "
                          f"加 --force 发布（审查状态记 FORCED_LOW_CONFIDENCE，不算 PASS）——选了才运行 "
                          f"{_cmd('publish', '--slug', ctx.slug)}")


CHECKS: dict[str, Callable[["Ctx"], StageStatus]] = {
    "init": _stage_init,
    "classify": _stage_classify,
    "sources": _stage_sources,
    "index": _stage_index,
    "clean": _stage_clean,
    "extract": _stage_extract,
    "reduce": _stage_reduce,
    "principles": _stage_principles,
    "frameworks": _stage_frameworks,
    "assemble": _stage_assemble,
    "attachments": _stage_attachments,
    "gates": _stage_gates,
    "review": _stage_review,
    "publish": _stage_publish,
}


@dataclass
class Ctx:
    slug: str
    root: Path
    check: bool
    has_raw: bool = False
    is_v6: bool = False


def _validator() -> Any:
    return _sibling("validate_output")


def _run(func: Callable[..., list[str]], ctx: Ctx) -> list[str]:
    """validate_output 的阶段函数按 cwd 解析路径，这里临时切到数据根目录。返回错误与警告。"""
    import os
    cwd = os.getcwd()
    try:
        os.chdir(ctx.root)
        return func(ctx.slug)
    finally:
        os.chdir(cwd)


def _hard(func: Callable[..., list[str]], ctx: Ctx) -> list[str]:
    return [e for e in _run(func, ctx) if not e.startswith("WARNING:")]


# ── 汇总与渲染 ────────────────────────────────────────────────────────


def collect_status(slug: str, root: Path, check: bool = False, tree: dict | None = None) -> list[StageStatus]:
    """按阶段树的顺序逐步检查。标题与章节取自阶段树，检查逻辑取自 CHECKS。"""
    tree = tree or load_stage_tree()
    ctx = Ctx(slug=slug, root=root, check=check)
    stages: list[StageStatus] = []
    for phase in tree["phases"]:
        for step in phase["steps"]:
            check_fn = CHECKS.get(step["id"])
            if check_fn is None:
                status = StageStatus(step["id"], step["title"], "pending", detail="（此步骤暂无自动检查）")
            else:
                status = check_fn(ctx)
                status.title = step["title"]
            status.phase = phase["id"]
            status.chapter = dict(phase["chapter"])
            stages.append(status)
    return stages


def next_stage(stages: list[StageStatus]) -> StageStatus | None:
    """第一个未完成的阶段；全部完成返回 None。"""
    return next((s for s in stages if s.state not in FINISHED), None)


def phase_states(stages: list[StageStatus], tree: dict | None = None) -> list[dict[str, Any]]:
    """把步骤状态汇总到 phase：全部完成=done，有失败=failed，有受阻=blocked，有进展=in_progress。"""
    tree = tree or load_stage_tree()
    result = []
    for phase in tree["phases"]:
        members = [s.state for s in stages if s.phase == phase["id"]]
        if members and all(m in FINISHED for m in members):
            state = "done"
        elif "failed" in members:
            state = "failed"
        elif "blocked" in members:
            state = "blocked"
        elif any(m in {"done", "in_progress"} for m in members):
            state = "in_progress"
        else:
            state = "pending"
        result.append({"id": phase["id"], "order": phase["order"], "title": phase["title"],
                       "chapter": phase["chapter"], "state": state})
    return result


def to_json(slug: str, stages: list[StageStatus], tree: dict | None = None) -> dict[str, Any]:
    nxt = next_stage(stages)
    return {
        "schema": SCHEMA,
        "slug": slug,
        "complete": nxt is None,
        "next": asdict(nxt) if nxt else None,
        "phases": phase_states(stages, tree),
        "stages": [asdict(s) for s in stages],
    }


def to_markdown(slug: str, stages: list[StageStatus], tree: dict | None = None) -> str:
    phases = {p["id"]: p for p in phase_states(stages, tree)}
    lines = [f"## 流水线状态：{slug}", "", "| 阶段 | 步骤 | 状态 | 说明 |", "|---|---|---|---|"]
    last_phase = None
    for s in stages:
        label = ""
        if s.phase != last_phase:
            p = phases.get(s.phase, {})
            label = f"{p.get('order', '')} · {p.get('title', s.phase)}"
            last_phase = s.phase
        detail = s.detail.replace("|", "\\|")
        lines.append(f"| {label} | {s.title} | {STATE_LABELS.get(s.state, s.state)} | {detail} |")
    nxt = next_stage(stages)
    lines.append("")
    if nxt is None:
        lines.append("**全部完成。**")
    else:
        lines.append(f"**下一步（{nxt.chapter.get('title', '')} / {nxt.title}）：** {nxt.next_action or nxt.detail}")
    return "\n".join(lines) + "\n"


# ── 叙述节奏：进度条、阶段卡、可视化面板 ──────────────────────────────
# 试跑反馈：只有底层命令滚动，用户找不到「现在在哪一阶段、这一步为什么、过没过闸门」。
# 编排者在每个阶段开头贴阶段卡、结尾贴进度条；面板给阶段边界做全局视图。

PROGRESS_MARKS = {"done": "▰", "in_progress": "◐", "failed": "✖", "blocked": "⛔"}


def progress_bar(stages: list[StageStatus], tree: dict | None = None) -> str:
    """一行进度：▶ 当前阶段、▰ 完成、◐ 部分完成、✖ 未通过、⛔ 受阻、▱ 未开始。"""
    phases = phase_states(stages, tree)
    nxt = next_stage(stages)
    bar = "".join("▶" if nxt and p["id"] == nxt.phase and p["state"] not in ("failed", "blocked")
                  else PROGRESS_MARKS.get(p["state"], "▱") for p in phases)
    done = sum(p["state"] == "done" for p in phases)
    return f"{bar} {done}/{len(phases)} · " + (nxt.chapter.get("title", "") if nxt else "全部完成")


def render_card(slug: str, stages: list[StageStatus], tree: dict | None = None, step_key: str | None = None,
                shard_count: int | None = None) -> str:
    """阶段卡：进入一个阶段时贴给用户的几行——这一步做什么、怎么做、过哪道闸门、整体走到哪。

    shard_count（run_unit.shard_count）给了且语料小到可以合并时，「怎么做」指向合并执行单位（墨子试跑第 14 条）。"""
    tree = tree or load_stage_tree()
    target = next((s for s in stages if s.key == step_key), None) if step_key else next_stage(stages)
    if target is None:
        return f"**{slug}：全部完成。** {progress_bar(stages, tree)}\n"
    phase = next(p for p in tree["phases"] if p["id"] == target.phase)
    step = next(s for s in phase["steps"] if s["id"] == target.key)
    who = "、".join(EXECUTOR_LABELS.get(e, e) for e in step["executor"].split("|"))
    unit = _sibling("run_unit").plan(tree, step["id"], pending=[s.key for s in stages if s.state not in FINISHED],
                                     shard_count=shard_count)
    gates = [step.get("checkpoint") or phase.get("checkpoint")]  # 步骤级检查点优先，与 mdf brief 一致
    if unit.is_bundle:
        gates = unit.checkpoints(phase_finished=lambda _: True)
        how = (f"{unit.title}——{unit.steps_text} 在一个新进程里依次做完，一份简报，{len(gates)} 个检查点都跑："
               f"`python scripts/mdf.py run {slug} {unit.id} --harness <名称> --yes`"
               f"（有子代理的 harness 把 `python scripts/mdf.py brief {slug} {unit.id}` 的简报交给一个子代理）")
    elif step.get("command"):
        how = f"`{step['command'].replace('{slug}', slug)}`"
    else:
        how = (f"agent：{step.get('agent', '')}（交给子代理；没有子代理的 harness 用 "
               f"`python scripts/mdf.py run {slug} {step['id']} --harness <名称> --yes` 交给新进程）")
    gates = [g for g in gates if g]
    lines = [
        tree["chapter_policy"]["fallback_heading"].format(order=phase["order"], title=phase["title"]),
        "",
        f"> {phase['chapter']['summary']}",
        "",
        f"- **这一步**：{step['title']}（{who}）——{target.next_action or target.detail or '按阶段树执行'}",
        f"- **怎么做**：{how}",
        f"- **闸门**：" + ("、".join(f"`{g.replace('{slug}', slug)}`" for g in gates) if gates
                         else "本阶段没有确定性检查点，靠独立审查"),
        f"- **进度**：{progress_bar(stages, tree)}",
    ]
    return "\n".join(lines) + "\n"


HTML_STATE = {"done": ("完成", "ok"), "in_progress": ("进行中", "run"), "pending": ("待办", "todo"),
              "failed": ("未通过", "bad"), "blocked": ("受阻", "bad"), "skipped": ("跳过", "skip")}


def _usage_cell(usage: dict[str, Any] | None) -> str:
    """运行记录里的用量（mdf run 从 Claude Code 的 JSON 结果里取；其他 harness 没有就留空）。"""
    if not usage:
        return "—"
    parts = []
    if usage.get("cost_usd") is not None:
        parts.append(f"${usage['cost_usd']:.2f}")
    if usage.get("turns") is not None:
        parts.append(f"{usage['turns']} 轮")
    if usage.get("subagents"):  # 简报禁止新进程再派子代理，出现了就标出来
        parts.append(f"⚠️ 子代理 {usage['subagents']}")
    return " · ".join(parts) or "—"


def load_runs(root: Path, slug: str, limit: int = 20) -> list[dict[str, Any]]:
    """mdf run 写下的运行记录（output/{slug}/runs/runs.jsonl），新的在前。"""
    path = root / "output" / slug / "runs" / "runs.jsonl"
    runs = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                runs.append(json.loads(line))
            except ValueError:
                continue
    except OSError:
        return []
    return runs[::-1][:limit]


def _run_usage(record: dict[str, Any]) -> dict[str, Any]:
    """运行记录里的用量：现在嵌在 usage 下；更早的记录把 cost_usd、turns 平铺在顶层。"""
    return record.get("usage") or {k: record[k] for k in ("cost_usd", "turns", "output_tokens")
                                    if record.get(k) is not None}


def render_html(slug: str, stages: list[StageStatus], tree: dict | None = None,
                runs: list[dict[str, Any]] | None = None, generated_at: str = "") -> str:
    """自包含的进度面板（mdf status --html）：左侧阶段轨对应对话里的章节，右侧逐阶段展开步骤、
    闸门与下一步，底部是 mdf run 的运行记录。不引用任何外部资源，离线可开。"""
    from html import escape

    tree = tree or load_stage_tree()
    phases = phase_states(stages, tree)
    nxt = next_stage(stages)
    done = sum(p["state"] == "done" for p in phases)
    rail, sections = [], []
    for phase, cfg in zip(phases, tree["phases"]):
        label, cls = HTML_STATE.get(phase["state"], (phase["state"], "todo"))
        current = " current" if nxt and nxt.phase == phase["id"] else ""
        rail.append(f'<li class="{cls}{current}"><a href="#{phase["id"]}"><span class="dot"></span>'
                    f'<span>{escape(phase["chapter"]["title"])}</span><em>{label}</em></a></li>')
        rows = []
        for s in (s for s in stages if s.phase == phase["id"]):
            s_label, s_cls = HTML_STATE.get(s.state, (s.state, "todo"))
            todo = f'<div class="next">下一步：{escape(s.next_action)}</div>' if s.next_action and s.state not in FINISHED else ""
            rows.append(f'<tr><td>{escape(s.title)}</td><td><span class="badge {s_cls}">{s_label}</span></td>'
                        f'<td>{escape(s.detail)}{todo}</td></tr>')
        gate = cfg.get("checkpoint")
        gate_html = f'<p class="gate">闸门：<code>{escape(gate.replace("{slug}", slug))}</code></p>' if gate else ""
        sections.append(f'<section id="{phase["id"]}" class="{cls}{current}"><h2>{escape(phase["chapter"]["title"])}'
                        f'<span class="badge {cls}">{label}</span></h2><p class="summary">{escape(phase["chapter"]["summary"])}</p>'
                        f'<table><thead><tr><th>步骤</th><th>状态</th><th>说明</th></tr></thead><tbody>{"".join(rows)}</tbody></table>'
                        f'{gate_html}</section>')
    segments = "".join(f'<span class="seg {HTML_STATE.get(p["state"], ("", "todo"))[1]}" title="{escape(p["chapter"]["title"])}"></span>'
                       for p in phases)
    callout = (f'<div class="callout"><strong>下一步 · {escape(nxt.chapter.get("title", ""))} / {escape(nxt.title)}</strong>'
               f'<p>{escape(nxt.next_action or nxt.detail)}</p></div>') if nxt else '<div class="callout ok"><strong>全部完成</strong></div>'
    run_rows = "".join(
        f'<tr><td>{escape(str(r.get("started_at", "")))}</td><td>{escape(str(r.get("step", "")))}</td>'
        f'<td>{escape(str(r.get("harness", "")))}</td><td>{escape(str(r.get("seconds", "")))} 秒</td>'
        f'<td><span class="badge {"ok" if r.get("ok") else "bad"}">{"通过" if r.get("ok") else "未通过"}</span></td>'
        f'<td>{escape(_usage_cell(_run_usage(r)))}</td>'
        f'<td>{escape(str(r.get("summary", "")))}</td></tr>' for r in runs or [])
    costs = [_run_usage(r)["cost_usd"] for r in runs or [] if _run_usage(r).get("cost_usd") is not None]
    total = (f'<p class="summary">共 {len(runs or [])} 次运行'
             + (f'，有用量记录的 {len(costs)} 次合计 ${sum(costs):.2f}' if costs else '') + '</p>') if runs else ""
    runs_html = (f'<section><h2>运行记录（mdf run）</h2>{total}<table><thead><tr><th>开始</th><th>步骤</th><th>harness</th>'
                 f'<th>用时</th><th>结果</th><th>用量</th><th>摘要</th></tr></thead><tbody>{run_rows}</tbody></table></section>') if run_rows else ""
    rail_html, sections_html = "".join(rail), "".join(sections)
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(slug)} 流水线进度</title>
<style>
:root{{--bg:#f7f6f2;--card:#fff;--ink:#1f2328;--muted:#6a6f76;--line:#e3e1da;--ok:#2f7d4f;--run:#2c62c9;--bad:#b3392f;--todo:#b9b6ad;--skip:#8d8a82}}
@media (prefers-color-scheme: dark){{:root:not([data-theme="light"]){{--bg:#16181c;--card:#1f2228;--ink:#e8e6e1;--muted:#9a9ea6;--line:#30343b;--ok:#5cb57f;--run:#6f9cf0;--bad:#e06c62;--todo:#545861;--skip:#7d8088}}}}
:root[data-theme="dark"]{{--bg:#16181c;--card:#1f2228;--ink:#e8e6e1;--muted:#9a9ea6;--line:#30343b;--ok:#5cb57f;--run:#6f9cf0;--bad:#e06c62;--todo:#545861;--skip:#7d8088}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 system-ui,"PingFang SC","Microsoft YaHei",sans-serif}}
header{{padding:20px 16px 8px;max-width:1100px;margin:auto}}h1{{font-size:20px;margin:0 0 8px}}
.bar{{display:flex;gap:4px;margin:6px 0}}.seg{{flex:1;height:8px;border-radius:4px;background:var(--todo)}}
.seg.ok{{background:var(--ok)}}.seg.run{{background:var(--run)}}.seg.bad{{background:var(--bad)}}.seg.skip{{background:var(--skip)}}
.meta{{color:var(--muted);font-size:13px}}
.layout{{display:grid;grid-template-columns:220px 1fr;gap:20px;max-width:1100px;margin:auto;padding:8px 16px 40px}}
nav ol{{list-style:none;margin:0;padding:0;position:sticky;top:12px;border-left:2px solid var(--line)}}
nav li a{{display:flex;align-items:center;gap:8px;padding:6px 10px;color:inherit;text-decoration:none;font-size:14px}}
nav li em{{margin-left:auto;font-style:normal;color:var(--muted);font-size:12px}}
.dot{{width:10px;height:10px;border-radius:50%;background:var(--todo);margin-left:-16px;flex:none;border:2px solid var(--bg)}}
li.ok .dot{{background:var(--ok)}}li.run .dot{{background:var(--run)}}li.bad .dot{{background:var(--bad)}}li.skip .dot{{background:var(--skip)}}
li.current a{{font-weight:600}}
section{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin-bottom:14px}}
section.current{{border-color:var(--run)}}h2{{font-size:16px;margin:0 0 4px;display:flex;gap:8px;align-items:center}}
.summary{{color:var(--muted);margin:0 0 8px;font-size:13px}}
table{{width:100%;border-collapse:collapse;font-size:14px}}th,td{{text-align:left;padding:6px 4px;border-top:1px solid var(--line);vertical-align:top}}
th{{color:var(--muted);font-weight:500}}td:first-child{{white-space:nowrap}}
.badge{{font-size:12px;padding:1px 8px;border-radius:10px;background:var(--todo);color:#fff;white-space:nowrap}}
.badge.ok{{background:var(--ok)}}.badge.run{{background:var(--run)}}.badge.bad{{background:var(--bad)}}.badge.skip{{background:var(--skip)}}
.next{{color:var(--run);font-size:13px;margin-top:2px}}.gate{{font-size:13px;color:var(--muted);margin:8px 0 0}}
code{{font-size:12px;background:var(--bg);padding:1px 4px;border-radius:4px;word-break:break-all}}
.callout{{border-left:4px solid var(--run);background:var(--card);padding:10px 14px;border-radius:6px;margin:10px 0}}
.callout.ok{{border-color:var(--ok)}}.callout p{{margin:4px 0 0}}
@media (max-width:720px){{.layout{{grid-template-columns:1fr}}nav ol{{position:static}}td:first-child{{white-space:normal}}}}
</style></head><body>
<header><h1>{escape(slug)} · 流水线进度</h1><div class="bar">{segments}</div>
<div class="meta">{done}/{len(phases)} 个阶段完成 · {escape(generated_at)} · 由 python scripts/mdf.py status {escape(slug)} --html 生成</div>{callout}</header>
<div class="layout"><nav><ol>{rail_html}</ol></nav><main>{sections_html}{runs_html}</main></div>
</body></html>
"""


def render_tree(tree: dict | None = None) -> str:
    """阶段逻辑树的 Markdown 视图（mdf stages）。"""
    tree = tree or load_stage_tree()
    lines = ["## 流水线阶段树", ""]
    for phase in tree["phases"]:
        lines.append(f"- **{phase['chapter']['title']}** — {phase['chapter']['summary']}")
        for step in phase["steps"]:
            who = "、".join(EXECUTOR_LABELS.get(e, e) for e in step["executor"].split("|"))
            parts = [f"`{step['command']}`"] if step.get("command") else []
            if step.get("agent"):
                parts.append(f"agent：{step['agent']}")
            lines.append(f"  - {step['title']}（{who}）" + ("：" + "；".join(parts) if parts else ""))
        if phase.get("checkpoint"):
            lines.append(f"  - ✓ 检查点：`{phase['checkpoint']}`")
    lines += ["", f"章节规则：{tree['chapter_policy']['rule']}"]
    return "\n".join(lines) + "\n"


MERMAID_SHAPES = {"script": ('["', '"]'), "agent": ('(["', '"])'), "human": ('[/"', '"/]')}


def render_mermaid(tree: dict | None = None) -> str:
    """阶段逻辑树的 Mermaid 流程图（mdf stages --mermaid）。docs/architecture.md 内嵌的就是它的输出，
    测试会比对两者，配置一改、图不跟着改就失败。形状：矩形=脚本、圆角=agent、平行四边形=人工。"""
    tree = tree or load_stage_tree()
    lines = ["flowchart TD"]
    chain: list[str] = []
    for phase in tree["phases"]:
        lines.append(f'    subgraph {phase["id"]}["{phase["chapter"]["title"]}"]')
        for step in phase["steps"]:
            node = f'{phase["id"]}_{step["id"]}'
            executors = step["executor"].split("|")
            left, right = MERMAID_SHAPES.get(executors[0], MERMAID_SHAPES["script"])
            who = "、".join(EXECUTOR_LABELS.get(e, e) for e in executors)
            lines.append(f"        {node}{left}{step['title']}<br/><small>{who}</small>{right}")
            chain.append(node)
        if phase.get("checkpoint"):
            node = f'{phase["id"]}_checkpoint'
            target = phase["checkpoint"].split("mdf.py ", 1)[-1].replace(" {slug}", "")
            lines.append(f'        {node}{{{{"✓ {target}"}}}}')
            chain.append(node)
        lines.append("    end")
    lines += [f"    {a} --> {b}" for a, b in zip(chain, chain[1:])]
    lines += [
        "    classDef agent fill:#eef4ff,stroke:#4a6fd1",
        "    classDef human fill:#fff6e5,stroke:#c98a12",
    ]
    for phase in tree["phases"]:
        for step in phase["steps"]:
            first = step["executor"].split("|")[0]
            if first in ("agent", "human"):
                lines.append(f'    class {phase["id"]}_{step["id"]} {first}')
    return "\n".join(lines) + "\n"
