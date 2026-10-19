#!/usr/bin/env python3
"""Automated Skill Publishing Script for Mind Distill Factory.

把 output/{slug}/ 发布到 gallery/{slug}/ 并更新 gallery/index.json，全程事务化：

1. 在 gallery/ 下的隐藏暂存目录里组装新包、写 v2 manifest，跑 published 校验
2. 新 index 先写到临时文件
3. 旧包改名为隐藏备份 → 暂存目录改名为正式目录 → 临时 index 替换正式 index（提交点）
4. 发布后再校验一次；任一步失败都回滚：旧包与旧 index 原样恢复
5. 成功后删除备份

暂存与备份目录放在 gallery/ 里而不是系统临时目录：os.replace 只有在同一文件系统
内才是原子改名，跨盘会退化成「复制 + 删除」。进程中途被杀时，下一次发布开头的
recover_interrupted() 依据提交点是否已过，回滚或清理残留。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Error reading JSON from {path}: {e}", file=sys.stderr)
        sys.exit(1)


def run_command(cmd: list[str], cwd: Path) -> tuple[int, str, str]:
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace"
    )
    return proc.returncode, proc.stdout, proc.stderr


DOSSIER_NAME = "人物档案.md"
REFERENCE_DIR = "references"
STAGING_PREFIX = ".staging-"
BACKUP_PREFIX = ".backup-"


class MetadataError(ValueError):
    """v6 身份卡缺字段或类目不在 taxonomy 内——拒绝发布，不回落默认值。"""


class PublishError(RuntimeError):
    """发布失败且已回滚。errors 是导致失败的校验错误列表。"""

    def __init__(self, message: str, errors: list[str] | None = None):
        super().__init__(message)
        self.errors = list(errors or [])


def _load_sibling(name: str):
    """按路径加载同目录的模块（scripts/ 不是包）。"""
    import importlib.util
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    # 先登记再执行：workspace 等模块在 `from __future__ import annotations` 下定义 dataclass，
    # dataclass 要到 sys.modules 里查模块，没登记就崩
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_validator():
    return _load_sibling("validate_output")


def is_v6_package(skill_md: Path) -> bool:
    """v6 包由 SKILL.md frontmatter 的 format_version 判定。

    委托给 validate_output.is_v6_skill（Task 4 已加固：只在解析出的 frontmatter
    块内匹配，避免正文示例代码块误判），避免两套独立实现互相漂移。
    """
    content = skill_md.read_text(encoding="utf-8")
    return _load_validator().is_v6_skill(content)


# ── 元数据 ────────────────────────────────────────────────────────────

_H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_CARD_ROW_RE = re.compile(r"^\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*$", re.MULTILINE)
_CATEGORY_ID_RE = re.compile(r"[（(]\s*([a-z_]+)\s*[)）]")
_TITLE_SUFFIX = "的思维框架"
MAX_SECONDARY_CATEGORIES = 2


def extract_v6_metadata(skill_md: Path) -> dict:
    """从 v6 包的 SKILL.md 提取 index 元数据（H1 标题 + 「身份卡」表）。

    缺字段时返回 None / 空列表，不再回落到 "Unknown" / "philosophy"——那样
    会把一个身份卡残缺的包悄悄登记成哲学类人物。是否拒绝由 resolve_metadata 决定。
    """
    content = skill_md.read_text(encoding="utf-8")

    person_name = ""
    title = _H1_RE.search(content)
    if title:
        person_name = title.group(1).strip()
        if person_name.endswith(_TITLE_SUFFIX):
            person_name = person_name[: -len(_TITLE_SUFFIX)].strip()

    rows = {k: v for k, v in _CARD_ROW_RE.findall(content)}

    primary = _CATEGORY_ID_RE.search(rows.get("主类", ""))
    secondary = _CATEGORY_ID_RE.findall(rows.get("副类", ""))

    return {
        "person_name": person_name or None,
        "era": rows.get("时代") or None,
        "primary_category": primary.group(1) if primary else None,
        "secondary_categories": secondary,
    }


def load_taxonomy_ids(root: Path | None = None) -> set[str]:
    root = root or Path(__file__).resolve().parent.parent
    taxonomy = json.loads((root / "config" / "taxonomy.json").read_text(encoding="utf-8"))
    return {c["id"] for c in taxonomy.get("categories", []) if isinstance(c, dict) and c.get("id")}


def v6_metadata_problems(meta: dict, taxonomy_ids: set[str]) -> list[str]:
    problems = []
    if not meta.get("person_name"):
        problems.append("缺少 H1 标题（人物名）")
    if not meta.get("era"):
        problems.append("身份卡缺少「时代」行")
    primary = meta.get("primary_category")
    if not primary:
        problems.append("身份卡缺少「主类」行或其中没有 (category_id)")
    elif primary not in taxonomy_ids:
        problems.append(f"主类 {primary!r} 不在 config/taxonomy.json 中")
    secondary = meta.get("secondary_categories") or []
    if len(secondary) > MAX_SECONDARY_CATEGORIES:
        problems.append(f"副类 {len(secondary)} 个，超过上限 {MAX_SECONDARY_CATEGORIES}")
    for cat in secondary:
        if cat not in taxonomy_ids:
            problems.append(f"副类 {cat!r} 不在 config/taxonomy.json 中")
    return problems


def resolve_metadata(output_dir: Path, slug: str, taxonomy_ids: set[str] | None = None) -> dict | None:
    """按包格式取 index 元数据。

    v6：身份卡不完整或类目非法时抛 MetadataError。legacy：缺 frameworks.zh.json
    时返回 None（调用方报错退出），其余行为保持原状。
    """
    skill_md = output_dir / "SKILL.md"

    if skill_md.exists() and is_v6_package(skill_md):
        meta = extract_v6_metadata(skill_md)
        problems = v6_metadata_problems(meta, taxonomy_ids if taxonomy_ids is not None else load_taxonomy_ids())
        if problems:
            raise MetadataError(f"{skill_md}: " + "；".join(problems))
        name_zh = meta["person_name"]
        return {
            "name_zh": name_zh,
            "name_en": slug.replace("-", " ").title(),
            "name_original": name_zh,
            "era": meta["era"],
            "primary_cat": meta["primary_category"],
            "secondary_cats": meta["secondary_categories"],
        }

    zh_framework_path = output_dir / "frameworks.zh.json"
    if not zh_framework_path.exists():
        return None

    en_framework_path = output_dir / "frameworks.en.json"
    zh_fw = load_json(zh_framework_path)
    en_fw = load_json(en_framework_path) if en_framework_path.exists() else {}
    name_zh = zh_fw.get("person_name")
    return {
        "name_zh": name_zh,
        "name_en": en_fw.get("person_name") or slug.replace("-", " ").title(),
        "name_original": (
            zh_fw.get("person_name_original") or en_fw.get("person_name_original") or name_zh
        ),
        "era": zh_fw.get("era") or en_fw.get("era") or "Unknown",
        "primary_cat": zh_fw.get("primary_category") or "philosophy",
        "secondary_cats": zh_fw.get("secondary_categories") or [],
    }


# ── 审查关卡 ──────────────────────────────────────────────────────────

FORCEABLE_VERDICTS = frozenset({"REVISE", "MISSING"})


def review_gate(verdict: str, force: bool) -> tuple[bool, str]:
    """根据 Stage 5 审查结论决定能否发布，以及 index.json 里记什么 review_status。

    verdict 取值见 package_manifest.read_review_verdict：
      PASS / REVISE / FAIL / MISSING（无 review.md）/ UNPARSEABLE（裁决节缺失或矛盾）
    force 为命令行 --force。

    返回 (是否允许发布, 写入 index 的 review_status)。review_status 会进版本控制，
    读 index 的人靠它判断这个 skill 有没有真的审过——不要写成一律 "PASS"。

    策略：
    - PASS 直接放行
    - REVISE / MISSING 只有 --force 才放行，记为 FORCED_<verdict>，与真审过的 PASS 可区分
    - FAIL（需回到 Stage 1/2 重做）与 UNPARSEABLE（坏掉的报告可能藏着 FAIL）
      加 --force 也拒绝；未知取值同样拒绝（fail-closed）
    """
    if verdict == "PASS":
        return True, "PASS"
    if verdict in FORCEABLE_VERDICTS and force:
        return True, f"FORCED_{verdict}"
    return False, f"BLOCKED_{verdict}"


def read_distill_confidence(output_dir: Path) -> float | None:
    """frameworks.zh.json 的 distill_confidence.score；文件或字段缺失返回 None。"""
    try:  # 不用 load_json：它读不到就 sys.exit，这里缺失要如实报「缺失」
        data = json.loads((output_dir / "frameworks.zh.json").read_text(encoding="utf-8-sig"))
        score = data.get("distill_confidence", {}).get("score")
    except (OSError, ValueError, AttributeError):
        return None
    return score if isinstance(score, (int, float)) and not isinstance(score, bool) else None


def confidence_gate(score: float | None, force: bool, review_status: str) -> tuple[bool, str]:
    """CLAUDE.md 质量门：distill_confidence.score ≥ 3 才能进 gallery（门槛取自 validate_output）。

    低于门槛（或读不到分数）默认拒绝；--force 放行，但 review_status 不再是 PASS，
    validate published --strict 据此知道它没过质量门（2026-10-19 鲁迅验收发现 10：score=2 一路通过）。
    """
    minimum = _load_validator().FRAMEWORK_SCHEMA["min_distill_confidence"]
    if score is not None and score >= minimum:
        return True, review_status
    if not force:
        return False, "BLOCKED_LOW_CONFIDENCE"
    return True, "FORCED_LOW_CONFIDENCE" if review_status == "PASS" else review_status


# ── 组包 / manifest / index ───────────────────────────────────────────


def copy_package(output_dir: Path, gallery_dir: Path, is_v6: bool) -> list[str]:
    """把 output/{slug}/ 的包内容复制到 gallery_dir，返回已复制的相对路径。"""
    gallery_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []

    shutil.copy2(output_dir / "SKILL.md", gallery_dir / "SKILL.md")
    copied.append("SKILL.md")
    if not is_v6:
        return copied

    refs_src = output_dir / REFERENCE_DIR
    if refs_src.exists():
        refs_dst = gallery_dir / REFERENCE_DIR
        refs_dst.mkdir(exist_ok=True)
        for path in sorted(refs_src.glob("*.md")):
            shutil.copy2(path, refs_dst / path.name)
            copied.append(f"{REFERENCE_DIR}/{path.name}")

    dossier = output_dir / DOSSIER_NAME
    if dossier.exists():
        shutil.copy2(dossier, gallery_dir / DOSSIER_NAME)
        copied.append(DOSSIER_NAME)

    return copied


def write_manifest(gallery_dir: Path, slug: str, is_v6: bool, output_dir: Path, root: Path) -> Path:
    """写 manifest.json（v2）：文件 sha256 + 审查结论，v6 另加簇列表与 P2 证明。

    format_version 必须反映实际检测到的包格式——legacy 发布不能被打上 6 的戳。
    P2 证明针对 gallery_dir 里刚复制好的 evidence.md 取 hash，绑定的是实际发布的字节。
    """
    pm = _load_sibling("package_manifest")
    review = pm.read_review_verdict(output_dir / "review.md")
    if is_v6:
        manifest = pm.build_manifest(
            gallery_dir, slug, format_version=6,
            clusters=pm.load_cluster_ids(output_dir / "framework_core.json"),
            p2_attestation=pm.attest_p2(
                gallery_dir / pm.EVIDENCE_REL, slug, root, _load_sibling("verify_provenance")
            ),
            review=review,
        )
    else:
        manifest = pm.build_manifest(gallery_dir, slug, format_version=1, review=review)
    path = gallery_dir / pm.MANIFEST_NAME
    pm.write_manifest(path, manifest)
    return path


def apply_index_entry(
    index_data: dict,
    slug: str,
    meta: dict,
    is_v6: bool,
    review_status: str,
    notes: str | None,
    today: str,
) -> dict:
    """在 index 数据里新建或更新 slug 的条目，返回该条目。纯函数式修改 index_data。

    "lang": "zh" 只对 v6 有意义（中文核心；英文是独立的 {slug}-en skill）。legacy
    是单文件双语，打上 "zh" 会在每次重发布时把它误标成纯中文，所以只在 v6 时写。
    """
    skills = index_data.setdefault("skills", [])
    entry = next((e for e in skills if e.get("slug") == slug), None)
    if entry is None:
        entry = {
            "slug": slug,
            "name_zh": meta["name_zh"],
            "name_en": meta["name_en"],
            "name_original": meta["name_original"],
            "primary_category": meta["primary_cat"],
            "secondary_categories": meta["secondary_cats"],
            "era": meta["era"],
            "distilled_on": today,
            "distill_method": "pipeline",
            "review_status": review_status,
            "skill_dir": f"gallery/{slug}/",
            "install_path": f"{slug}-wisdom",
            "notes": notes or f"Distilled skill for {meta['name_en']}.",
            "format_version": 6 if is_v6 else 1,
            "has_attachments": is_v6,
        }
        if is_v6:
            entry["lang"] = "zh"
        skills.append(entry)
        return entry

    entry["name_zh"] = meta["name_zh"]
    entry["name_en"] = meta["name_en"]
    entry["name_original"] = meta["name_original"]
    entry["primary_category"] = meta["primary_cat"]
    entry["secondary_categories"] = meta["secondary_cats"]
    entry["era"] = meta["era"]
    entry["distilled_on"] = today
    entry["review_status"] = review_status
    if is_v6:
        entry["lang"] = "zh"
    entry["format_version"] = 6 if is_v6 else 1
    entry["has_attachments"] = is_v6
    if notes:
        entry["notes"] = notes
    return entry


# ── 事务 ──────────────────────────────────────────────────────────────


def _replace_with_retry(src: Path, dst: Path, attempts: int = 5, delay: float = 0.2) -> None:
    """os.replace，遇 PermissionError 短暂重试。

    Windows 上杀毒软件或索引服务常会短暂占用刚写完的文件，改名随即报
    PermissionError；隔一两百毫秒再试通常就过了。POSIX 上基本不会走到重试。
    """
    for attempt in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)


def _rmtree(path: Path) -> None:
    """删除目录；Windows 上只读文件会让 rmtree 失败，先去掉只读位再删。"""
    if not path.exists():
        return

    def _clear_readonly(func, target, _exc):
        os.chmod(target, stat.S_IWRITE)
        func(target)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_clear_readonly)
    else:  # pragma: no cover - onerror 在 3.12 起弃用
        shutil.rmtree(path, onerror=_clear_readonly)


def _discard_dir(path: Path, gallery_root: Path, slug: str) -> None:
    """先改名成暂存前缀再删：即使删到一半失败，残留也会被下次 recover_interrupted 清掉。"""
    if not path.exists():
        return
    trash = gallery_root / f"{STAGING_PREFIX}{slug}-discard-{uuid.uuid4().hex[:8]}"
    _replace_with_retry(path, trash)
    try:
        _rmtree(trash)
    except OSError:
        pass


def _index_tmp(gallery_root: Path, slug: str) -> Path:
    return gallery_root / f".index-{slug}.json.tmp"


def recover_interrupted(gallery_root: Path, slug: str) -> list[str]:
    """清理上一次被中途杀掉的发布留下的残局，返回处理记录。

    提交点是「临时 index 替换正式 index」。临时 index 还在 = 没到提交点：
    若有备份就回滚到备份。临时 index 不在但备份还在 = 已提交、只差删备份：删掉。
    正式目录缺失而备份在 = 卡在两次改名之间：恢复备份。
    """
    notes: list[str] = []
    final = gallery_root / slug
    index_tmp = _index_tmp(gallery_root, slug)
    uncommitted = index_tmp.exists()
    backups = sorted(gallery_root.glob(f"{BACKUP_PREFIX}{slug}-*"), key=lambda p: p.stat().st_mtime)

    if backups and (uncommitted or not final.exists()):
        _discard_dir(final, gallery_root, slug)
        _replace_with_retry(backups[-1], final)
        notes.append(f"上次发布未完成，已从 {backups[-1].name} 回滚")
        backups = backups[:-1]
    for backup in backups:
        _rmtree(backup)
        notes.append(f"删除已提交发布的残留备份 {backup.name}")
    if uncommitted:
        index_tmp.unlink()
        notes.append(f"删除未提交的临时 index {index_tmp.name}")
    for staging in gallery_root.glob(f"{STAGING_PREFIX}{slug}-*"):
        _rmtree(staging)
        notes.append(f"删除残留暂存目录 {staging.name}")
    return notes


def publish_transaction(
    root: Path,
    slug: str,
    output_dir: Path,
    is_v6: bool,
    update_index: Callable[[dict], None],
) -> list[str]:
    """事务化发布，返回执行记录；失败时抛 PublishError（或原始异常），且旧包与旧 index 已恢复。

    update_index 接收解析好的 index 数据并就地修改（通常包一层 apply_index_entry）。
    """
    validator = _load_validator()
    gallery_root = root / "gallery"
    gallery_root.mkdir(parents=True, exist_ok=True)
    log = recover_interrupted(gallery_root, slug)

    token = uuid.uuid4().hex[:8]
    final = gallery_root / slug
    staging = gallery_root / f"{STAGING_PREFIX}{slug}-{token}"
    backup = gallery_root / f"{BACKUP_PREFIX}{slug}-{token}"
    index_file = gallery_root / "index.json"
    index_tmp = _index_tmp(gallery_root, slug)

    # 阶段 1：暂存 + 校验 + 备好新 index。这里失败时旧包与 index 从未被碰过。
    try:
        copied = copy_package(output_dir, staging, is_v6)
        write_manifest(staging, slug, is_v6, output_dir, root)
        errors = [
            e for e in validator.check_published_package(staging, slug, root)
            if not e.startswith("WARNING:")
        ]
        if errors:
            raise PublishError("暂存包未通过 published 校验，未改动 gallery", errors)
        old_index = index_file.read_bytes() if index_file.exists() else None
        index_data = json.loads(old_index.decode("utf-8")) if old_index else {
            "version": "1.0",
            "description": "Mind Distill Factory — Gallery Index",
            "skills": [],
        }
        update_index(index_data)
        index_tmp.write_text(
            json.dumps(index_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
    except BaseException:
        _rmtree(staging)
        index_tmp.unlink(missing_ok=True)
        raise
    log.append(f"暂存并校验通过：{', '.join(copied)} + manifest.json")

    # 阶段 2：切换。任何失败都回滚到切换前的状态。
    swapped = committed = False
    try:
        if final.exists():
            _replace_with_retry(final, backup)
        _replace_with_retry(staging, final)
        swapped = True
        _replace_with_retry(index_tmp, index_file)  # 提交点
        committed = True
        errors = [e for e in validator.validate_published(slug, root) if not e.startswith("WARNING:")]
        if errors:
            raise PublishError("发布后校验失败，已回滚", errors)
    except BaseException:
        _rollback(gallery_root, slug, backup, index_file, index_tmp, old_index, swapped, committed)
        raise

    try:
        _rmtree(backup)
    except OSError as e:  # 残留备份不影响已提交的发布，下次发布时清理
        log.append(f"WARNING: 备份目录删除失败（下次发布会清理）：{e}")
    log.append(f"已发布到 {final}，index 已更新")
    return log


def _rollback(
    gallery_root: Path,
    slug: str,
    backup: Path,
    index_file: Path,
    index_tmp: Path,
    old_index: bytes | None,
    swapped: bool,
    committed: bool,
) -> None:
    final = gallery_root / slug
    if swapped:
        _discard_dir(final, gallery_root, slug)
    if backup.exists():
        _replace_with_retry(backup, final)
    if committed:
        if old_index is None:
            index_file.unlink(missing_ok=True)
        else:
            restore = index_file.with_name(index_file.name + ".restore")
            restore.write_bytes(old_index)
            _replace_with_retry(restore, index_file)
    index_tmp.unlink(missing_ok=True)
    for staging in gallery_root.glob(f"{STAGING_PREFIX}{slug}-*"):
        try:
            _rmtree(staging)
        except OSError:
            pass


# ── CLI ───────────────────────────────────────────────────────────────


def main() -> int:
    # Handle Windows console encoding for UTF-8 output
    if sys.platform.startswith('win'):
        try:
            sys.stdout.reconfigure(encoding='utf-8')
            sys.stderr.reconfigure(encoding='utf-8')
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="Publish a thinker skill to the gallery.")
    parser.add_argument(
        "--slug", required=True, type=_load_sibling("slug_rules").slug_arg,
        help="The slug of the thinker (e.g. seneca); rejected, not normalized, if malformed",
    )
    parser.add_argument("--dry-run", action="store_true", help="Perform checks but do not modify files")
    parser.add_argument(
        "--force", action="store_true",
        help="Skip the build-stage pre-check; review_gate decides how --force treats the review "
             "verdict. The staged published check can never be skipped.",
    )
    parser.add_argument("--notes", help="Custom notes to add/update in gallery/index.json")
    parser.add_argument("--root", help="数据根目录（默认 MDF_DATA_ROOT，再默认仓库根）")
    args = parser.parse_args()

    # 和其他命令一样认数据根：数据根放在 worktree 之外时，发布不能回仓库根找 output/
    workspace = _load_sibling("workspace").Workspace.resolve(args.root)
    root, code_root = workspace.data_root, workspace.code_root
    slug = args.slug

    output_dir = root / "output" / slug
    output_skill = output_dir / "SKILL.md"

    print(f"=== Publishing Distilled Skill for '{slug}' ===")

    # 1. 构建期预检
    if not output_skill.exists():
        print(f"ERROR: Compiled skill file not found at {output_skill}", file=sys.stderr)
        return 1

    if not args.force:
        print("Running pre-publication validation check...")
        ret, stdout, stderr = run_command(
            [sys.executable, str(code_root / "scripts" / "validate_output.py"), "skill", slug],
            root
        )
        if ret != 0:
            print("ERROR: Skill validation failed!", file=sys.stderr)
            print(stdout, file=sys.stderr)
            print(stderr, file=sys.stderr)
            return 1
        print("[OK] Skill stage validation passed.")

    # 2. 元数据
    try:
        meta = resolve_metadata(output_dir, slug)
    except MetadataError as e:
        print(f"ERROR: 身份卡不完整，拒绝发布：{e}", file=sys.stderr)
        return 1
    if meta is None:
        print(
            f"ERROR: Chinese framework JSON not found at {output_dir / 'frameworks.zh.json'} "
            f"(legacy packages require it; v6 packages read metadata from SKILL.md)",
            file=sys.stderr,
        )
        return 1

    print("Extracted Metadata:")
    print(f"  Name (ZH): {meta['name_zh']}")
    print(f"  Name (EN): {meta['name_en']}")
    print(f"  Original Name: {meta['name_original']}")
    print(f"  Era: {meta['era']}")
    print(f"  Categories: primary={meta['primary_cat']}, secondary={meta['secondary_cats']}")

    # 3. 审查关卡
    verdict = _load_sibling("package_manifest").read_review_verdict(output_dir / "review.md")
    allowed, review_status = review_gate(verdict["verdict"], args.force)
    print(f"Review verdict: {verdict['verdict']} → review_status={review_status}")
    if not allowed:
        print(f"ERROR: 审查关卡未放行（verdict={verdict['verdict']}）", file=sys.stderr)
        return 1

    # 4. 置信度关卡
    score = read_distill_confidence(output_dir)
    allowed, review_status = confidence_gate(score, args.force, review_status)
    print(f"distill_confidence: {score if score is not None else '缺失'} → review_status={review_status}")
    if not allowed:
        print(f"ERROR: distill_confidence={score} 低于质量门 3，拒绝发布（补一手素材重跑，或用户决定后加 --force）",
              file=sys.stderr)
        return 1

    if args.dry_run:
        print("\n[DRY RUN] Publishing steps skipped.")
        return 0

    # 4. 事务化发布
    v6 = is_v6_package(output_skill)
    today = dt.date.today().isoformat()
    try:
        log = publish_transaction(
            root, slug, output_dir, v6,
            lambda index: apply_index_entry(index, slug, meta, v6, review_status, args.notes, today),
        )
    except PublishError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        for err in e.errors:
            print(f"  {err}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"ERROR: 发布失败，已回滚：{type(e).__name__}: {e}", file=sys.stderr)
        return 1

    for line in log:
        print(f"  {line}")
    print(f"[OK] Success! Skill '{slug}' published and validated (format_version={'6' if v6 else 'legacy'}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
