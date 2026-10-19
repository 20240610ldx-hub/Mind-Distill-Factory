#!/usr/bin/env python3
"""发布包 manifest：文件 hash 清单 + 构建期证明（v2）。

发布后的 gallery/{slug}/ 只剩包内文件，私有语料（sources/，gitignored）和中间产物
（framework_core.json）都不在了。P1/P3/P5/P6 只依赖包内文件，发布后可原样重跑；
真正无法重跑的只有两样：

- P2（evidence.md ↔ 语料逐字闭合）——需要语料
- P4 的按簇覆盖——需要 framework_core.json 里的 cluster_id 列表

所以 manifest 只记录这两样「不可重算」的东西，外加每个文件的 sha256。发布侧校验
不重跑 P2，而是核对：evidence.md 的 hash 仍等于构建期证明里记下的那个——证据没
变，构建期的 P2 结论就仍然成立。

manifest 刻意不含时间戳：同一内容重复发布得到逐字节相同的 manifest，gallery/ 进
版本控制，无变化的重发布不会产生 diff。

    {
      "manifest_version": 2,
      "slug": "demo",
      "format_version": 6,
      "files": {"SKILL.md": "<sha256>", "references/evidence.md": "<sha256>", ...},
      "clusters": ["cluster_a", ...],                       # 仅 v6
      "attestation": {"p2": {...}},                          # 仅 v6
      "review": {"verdict": "PASS", "detail": "...", "review_sha256": "..."}
    }
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
from typing import Any

MANIFEST_NAME = "manifest.json"
MANIFEST_VERSION = 2
EVIDENCE_REL = "references/evidence.md"
SUPPORTED_FORMAT_VERSIONS = (1, 6)
REVIEW_VERDICTS = ("PASS", "REVISE", "FAIL", "MISSING", "UNPARSEABLE")


# ── 基础工具 ──────────────────────────────────────────────────────────


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def is_safe_relative(rel: str) -> bool:
    """manifest 的文件键必须是包内的 POSIX 相对路径。

    拒绝空串、绝对路径、Windows 盘符/反斜杠、`.`/`..` 段——manifest 若被篡改成
    `../../x`，发布侧的 hash 校验就会去读包外文件。

    还要求键是规范形式：PurePosixPath 会把 `./a`、`a//b` 静默折叠成 `a`、`a/b`，
    非规范键既能绕过上面的段检查，也会和 list_package_files 产出的规范路径对不上。
    """
    if not rel or "\\" in rel or ":" in rel:
        return False
    path = PurePosixPath(rel)
    if path.is_absolute() or path.as_posix() != rel:
        return False
    return all(part not in ("", ".", "..") for part in path.parts)


def list_package_files(package_dir: Path) -> list[str]:
    """包目录下全部文件的 POSIX 相对路径（不含 manifest 自身），已排序。"""
    files = []
    for path in package_dir.rglob("*"):
        if path.is_file() and path.name != MANIFEST_NAME:
            files.append(path.relative_to(package_dir).as_posix())
    return sorted(files)


def load_cluster_ids(core_file: Path) -> list[str]:
    """从 framework_core.json 取 cluster_id 列表；文件缺失或格式错误时抛异常。"""
    core = json.loads(core_file.read_text(encoding="utf-8"))
    return [
        c["cluster_id"]
        for c in core.get("principle_clusters", [])
        if isinstance(c, dict) and isinstance(c.get("cluster_id"), str) and c["cluster_id"]
    ]


# ── 构建期证明 ────────────────────────────────────────────────────────


def corpus_fingerprint(corpus: list[tuple[str, str]]) -> str:
    """对 P2 实际比对的语料取指纹：按名称排序后的 (名称, 文本 sha256) 序列。

    指纹的是 load_corpus 归一化后的文本，而非原始文件字节——它证明的对象正是
    P2 看到的那份内容，和语料来自 raw 文本还是 hash 绑定的 PDF sidecar 无关。
    """
    digest = hashlib.sha256()
    for name, text in sorted(corpus):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(text.encode("utf-8")).hexdigest().encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def evidence_rights(
    evidence_md: Path, slug: str, root: Path, prov: Any, corpus: list[tuple[str, str]] | None = None
) -> dict[str, Any] | None:
    """证据卡所在语料文件的权利状态汇总（来自 source_registry.json）；没有登记表时返回 None。

    发布出去的只是引文量级的摘录，但摘录来自哪本书、那本书能不能这样用，必须能回答——
    这份汇总写进 P2 证明，strict 发布（S4）据此 fail-closed。
    """
    registry_path = root / "sources" / slug / "processed" / "source_registry.json"
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    by_path = {
        str(item.get("relative_path")): item
        for item in registry.get("sources", []) if isinstance(item, dict)
    }
    corpus = prov.load_corpus(slug, root) if corpus is None else corpus
    cards = prov.parse_evidence_cards(evidence_md.read_text(encoding="utf-8")) if evidence_md.exists() else []
    sources: dict[str, dict[str, Any]] = {}
    unlocated = 0
    for card in cards:
        name = prov.find_verbatim(card["verbatim"], corpus) if card["verbatim"] else None
        if name is None:
            unlocated += 1
            continue
        rel = name.split("#", 1)[0]
        item = by_path.get(rel)
        entry = sources.setdefault(rel, {
            "rights_status": (item or {}).get("rights_status") or "unregistered",
            "rights_review_required": bool((item or {}).get("rights_review_required")),
            "rights_basis": (item or {}).get("rights_basis"),
            "origin": (item or {}).get("origin"),
            "evidence_cards": 0,
        })
        entry["evidence_cards"] += 1
    return {"sources": sources, "unlocated_cards": unlocated}


def attest_p2(evidence_md: Path, slug: str, root: Path, prov: Any) -> dict[str, Any]:
    """在构建期运行 P2，返回可写入 manifest 的证明。

    prov 是 verify_provenance 模块（scripts/ 不是包，由调用方按路径加载）。
    语料只读一次，同一份既用于 P2 比对、取指纹，又用于权利汇总。
    """
    corpus = prov.load_corpus(slug, root)
    errors = prov.check_p2_corpus_closure(evidence_md, slug, root, corpus=corpus)
    hard = [e for e in errors if not e.startswith("WARNING:")]
    warnings = [e for e in errors if e.startswith("WARNING:")]
    # 覆盖率进 manifest：读 gallery 的人看得见「逐字核对」到底覆盖了几张卡（鲁迅验收发现 11）
    _, verified, total = (prov.p2_scan(evidence_md, slug, corpus) if evidence_md.exists() and corpus
                          else ([], 0, 0))
    return {
        "status": "pass" if not hard else "fail",
        "hard_errors": len(hard),
        "warnings": len(warnings),
        "cards_verified": verified,
        "cards_total": total,
        "evidence_sha256": sha256_file(evidence_md) if evidence_md.exists() else None,
        "corpus_fingerprint": corpus_fingerprint(corpus) if corpus else None,
        "corpus_files": len(corpus),
        "rights": evidence_rights(evidence_md, slug, root, prov, corpus=corpus),
    }


_VERDICT_HEADING_RE = re.compile(r"^##\s+(?:裁决|Verdict)\s*$", re.MULTILINE | re.IGNORECASE)
_NEXT_HEADING_RE = re.compile(r"^##\s+", re.MULTILINE)
_VERDICT_TOKEN_RE = re.compile(r"\[(PASS|REVISE|FAIL)(?:\s*[:：]\s*([^\]]*))?\]")


def read_review_verdict(review_md: Path) -> dict[str, Any]:
    """解析 Stage 5 的 review.md 裁决（quality-reviewer 输出格式的「## 裁决」节）。

    fail-closed：文件缺失 → MISSING；没有裁决节、节内无裁决、或节内出现多个
    互相矛盾的裁决（含未填的模板占位 `[PASS / REVISE / FAIL]`）→ UNPARSEABLE。
    """
    if not review_md.exists():
        return {"verdict": "MISSING", "detail": "", "review_sha256": None}
    text = review_md.read_text(encoding="utf-8")
    result: dict[str, Any] = {"verdict": "UNPARSEABLE", "detail": "", "review_sha256": sha256_file(review_md)}

    heading = _VERDICT_HEADING_RE.search(text)
    if heading is None:
        return result
    rest = text[heading.end():]
    next_heading = _NEXT_HEADING_RE.search(rest)
    section = rest[: next_heading.start()] if next_heading else rest

    tokens = _VERDICT_TOKEN_RE.findall(section)
    verdicts = {verdict for verdict, _ in tokens}
    if len(verdicts) != 1:
        return result
    verdict, detail = tokens[0]
    result["verdict"] = verdict
    result["detail"] = (detail or "").strip()
    return result


# ── 构建 / 读写 ───────────────────────────────────────────────────────


def build_manifest(
    package_dir: Path,
    slug: str,
    *,
    format_version: int,
    clusters: list[str] | None = None,
    p2_attestation: dict[str, Any] | None = None,
    review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """对「已暂存好的发布目录」构建 manifest：目录里有什么，就证明什么。

    必须在 staging 目录上调用，不能在 output/{slug}/ 上调用——后者含
    framework_core.json 等不发布的中间产物，会被一并记进清单。
    """
    manifest: dict[str, Any] = {
        "manifest_version": MANIFEST_VERSION,
        "slug": slug,
        "format_version": format_version,
        "files": {rel: sha256_file(package_dir / rel) for rel in list_package_files(package_dir)},
    }
    if format_version == 6:
        manifest["clusters"] = list(clusters or [])
        manifest["attestation"] = {"p2": p2_attestation}
    if review is not None:
        manifest["review"] = review
    return manifest


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    """原子写：同目录临时文件 + os.replace，中途失败不留半截 manifest。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    # newline="\n"：Windows 默认会把 \n 写成 \r\n，同一 manifest 跨平台就不再逐字节相同。
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    os.replace(temporary, path)


def load_manifest(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    """读取 manifest；返回 (manifest, errors)。manifest 为 None 时 errors 非空。"""
    if not path.exists():
        return None, [f"MANIFEST_MISSING: {path}"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        return None, [f"MANIFEST_PARSE_ERROR: {path}: {e}"]
    if not isinstance(data, dict):
        return None, [f"MANIFEST_PARSE_ERROR: {path}: 顶层不是对象"]
    if "manifest_version" not in data:
        # v6 首版 publish_skill.py 写的 manifest 只有 format_version + files，没有证明。
        return None, [f"MANIFEST_OUTDATED: {path}: 缺少 manifest_version（v1 清单，无构建期证明），需重新发布"]
    if data.get("manifest_version") != MANIFEST_VERSION:
        return None, [
            f"MANIFEST_UNSUPPORTED: {path}: manifest_version={data.get('manifest_version')!r}，"
            f"仅支持 {MANIFEST_VERSION}"
        ]
    return data, []


# ── 发布侧校验 ────────────────────────────────────────────────────────


def verify_manifest(package_dir: Path, manifest: dict[str, Any], slug: str) -> list[str]:
    """核对 manifest 与包目录的一致性，以及 v6 构建期证明的完整性。

    只查结构与 hash，不做策略判断：review 裁决是否允许发布由调用方决定。
    """
    errors: list[str] = []
    where = package_dir / MANIFEST_NAME

    if manifest.get("slug") != slug:
        errors.append(f"MANIFEST_SLUG_MISMATCH: {where}: slug={manifest.get('slug')!r}，期望 {slug!r}")

    format_version = manifest.get("format_version")
    if format_version not in SUPPORTED_FORMAT_VERSIONS:
        errors.append(f"MANIFEST_BAD_FORMAT_VERSION: {where}: format_version={format_version!r}")

    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        errors.append(f"MANIFEST_NO_FILES: {where}: files 为空或不是对象")
        files = {}
    if files and "SKILL.md" not in files:
        errors.append(f"MANIFEST_NO_SKILL_MD: {where}: files 未列出 SKILL.md")

    for rel, expected in sorted(files.items()):
        if not is_safe_relative(rel):
            errors.append(f"MANIFEST_UNSAFE_PATH: {where}: {rel!r}")
            continue
        path = package_dir / rel
        if not path.is_file():
            errors.append(f"MANIFEST_MISSING_FILE: {path}")
            continue
        actual = sha256_file(path)
        if actual != expected:
            errors.append(f"MANIFEST_HASH_MISMATCH: {path} (manifest={str(expected)[:12]}, actual={actual[:12]})")

    # 反方向：包里有、清单没有的文件——上一次发布残留的旧附件就是这么漏网的。
    for rel in list_package_files(package_dir):
        if rel not in files:
            errors.append(f"MANIFEST_UNLISTED_FILE: {package_dir / rel}")

    if format_version == 6:
        errors.extend(_verify_v6_attestation(where, manifest, files))

    review = manifest.get("review")
    if review is not None and (not isinstance(review, dict) or review.get("verdict") not in REVIEW_VERDICTS):
        errors.append(f"MANIFEST_BAD_REVIEW: {where}: review={review!r}")

    return errors


def _load_sibling(name: str) -> Any:
    """按路径加载同目录的模块（scripts/ 不是包）。"""
    import importlib.util
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def backfill(slug: str, root: Path, corpus_root: Path, force: bool = False) -> int:
    """给已在 gallery/ 里的包补发 v2 manifest，返回进程退出码。

    legacy 包只记文件 hash，不写 review——index.json 里的 review_status 是
    publish_skill.py 无条件写的 PASS，不能拿来冒充审查结论。v6 包需要
    output/{slug}/framework_core.json 取簇列表，并在 corpus_root/sources/{slug}/
    下重跑 P2；P2 不通过就拒绝写入，不生成一份注定校验失败的 manifest。
    """
    gallery_dir = root / "gallery" / slug
    skill_md = gallery_dir / "SKILL.md"
    if not skill_md.exists():
        print(f"ERROR: {skill_md} 不存在")
        return 1

    path = gallery_dir / MANIFEST_NAME
    if path.exists() and not force:
        existing, _ = load_manifest(path)
        if existing is not None:
            print(f"[SKIP] {path} 已是 v{MANIFEST_VERSION}（用 --force 覆盖）")
            return 0

    is_v6 = _load_sibling("validate_output").is_v6_skill(skill_md.read_text(encoding="utf-8"))
    if is_v6:
        output_dir = root / "output" / slug
        core_file = output_dir / "framework_core.json"
        if not core_file.exists():
            print(f"ERROR: v6 补发需要 {core_file} 提供簇列表")
            return 1
        p2 = attest_p2(gallery_dir / EVIDENCE_REL, slug, corpus_root, _load_sibling("verify_provenance"))
        if p2["status"] != "pass":
            print(f"ERROR: P2 未通过，拒绝写入：{json.dumps(p2, ensure_ascii=False)}")
            return 1
        manifest = build_manifest(
            gallery_dir, slug, format_version=6, clusters=load_cluster_ids(core_file),
            p2_attestation=p2, review=read_review_verdict(output_dir / "review.md"),
        )
    else:
        manifest = build_manifest(gallery_dir, slug, format_version=1)

    write_manifest(path, manifest)
    errors = verify_manifest(gallery_dir, manifest, slug)
    if errors:
        print(f"ERROR: 写入后自检失败：{errors}")
        return 1
    print(f"[OK] {path}: format_version={manifest['format_version']}, {len(manifest['files'])} 个文件")
    return 0


def main() -> int:
    import argparse
    import sys

    if sys.platform.startswith("win"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except AttributeError:
            pass

    parser = argparse.ArgumentParser(description="发布包 manifest 工具")
    sub = parser.add_subparsers(dest="command", required=True)
    bf = sub.add_parser("backfill", help="给 gallery/{slug}/ 补发 v2 manifest")
    bf.add_argument("slug", type=_load_sibling("slug_rules").slug_arg)
    bf.add_argument("--corpus-root", type=Path, default=None,
                    help="含 sources/{slug}/ 的目录（v6 重跑 P2 用），默认仓库根")
    bf.add_argument("--force", action="store_true", help="覆盖已有的 v2 manifest")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    return backfill(args.slug, root, args.corpus_root or root, args.force)


def _verify_v6_attestation(where: Path, manifest: dict[str, Any], files: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    clusters = manifest.get("clusters")
    if not isinstance(clusters, list) or not clusters or not all(isinstance(c, str) and c for c in clusters):
        errors.append(f"MANIFEST_NO_CLUSTERS: {where}: v6 包必须携带非空 clusters（P4 按簇覆盖依赖它）")

    attestation = manifest.get("attestation")
    p2 = attestation.get("p2") if isinstance(attestation, dict) else None
    if not isinstance(p2, dict):
        errors.append(f"MANIFEST_NO_P2_ATTESTATION: {where}: v6 包缺少构建期 P2 证明")
        return errors

    if p2.get("status") != "pass" or p2.get("hard_errors") != 0:
        errors.append(
            f"MANIFEST_P2_NOT_PASSED: {where}: 构建期 P2 status={p2.get('status')!r}, "
            f"hard_errors={p2.get('hard_errors')!r}"
        )
    if not p2.get("corpus_fingerprint"):
        errors.append(f"MANIFEST_P2_NO_CORPUS: {where}: P2 证明没有语料指纹（构建期语料为空？）")

    attested = p2.get("evidence_sha256")
    actual = files.get(EVIDENCE_REL)
    if actual is None:
        errors.append(f"MANIFEST_NO_EVIDENCE: {where}: files 未列出 {EVIDENCE_REL}")
    elif attested != actual:
        # evidence.md 在 P2 之后被改过：构建期结论不再覆盖当前证据。
        errors.append(
            f"MANIFEST_P2_STALE: {where}: P2 证明的 evidence sha256={str(attested)[:12]}，"
            f"当前 {EVIDENCE_REL}={str(actual)[:12]}"
        )
    return errors


if __name__ == "__main__":
    raise SystemExit(main())
