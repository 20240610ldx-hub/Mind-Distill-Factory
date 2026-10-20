#!/usr/bin/env python3
"""Source registry and content fingerprints for local distillation corpora."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = "source-registry-v2"
SUPPORTED_SOURCE_EXTENSIONS = {".txt", ".md", ".markdown", ".pdf", ".epub"}
# mdf index 能读的格式。登记表另收 .epub 记指纹，索引器对它报 unsupported_extension
INDEXABLE_EXTENSIONS = frozenset({".txt", ".md", ".markdown", ".pdf"})


def indexable_raw_files(raw_dir: Path) -> list[Path]:
    """raw/ 下 mdf index 会处理的素材，含子目录（mdf acquire 落在 raw/acquired/<连接器>/ 下），按相对路径排序。

    校验器与状态表判断「有没有本地素材」都用这一份，别再各写一个 glob。
    """
    if not raw_dir.exists():
        return []
    return sorted(
        (p for p in raw_dir.rglob("*") if p.is_file() and p.suffix.lower() in INDEXABLE_EXTENSIONS),
        key=lambda p: p.relative_to(raw_dir).as_posix().lower(),
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_id(relative_path: str, digest: str) -> str:
    """Create a stable id for one content version, independent of absolute paths."""
    normalized = relative_path.replace("\\", "/").strip().lower()
    value = hashlib.sha256(f"{normalized}\n{digest}".encode("utf-8")).hexdigest()
    return f"src_{value[:20]}"


def canonical_url(url: str) -> str:
    """Normalize a URL without removing meaningful query parameters."""
    value = (url or "").strip()
    value = re.sub(r"^http://", "https://", value, flags=re.IGNORECASE)
    return value.rstrip("/")


def classify_extension(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".markdown":
        return "text/markdown"
    if ext == ".md":
        return "text/markdown"
    if ext == ".txt":
        return "text/plain"
    if ext == ".pdf":
        return "application/pdf"
    if ext == ".epub":
        return "application/epub+zip"
    return "application/octet-stream"


def make_record(
    path: Path,
    root: Path,
    *,
    role: str = "user_provided",
    origin: str = "local",
    rights_status: str = "unverified",
    url: str = "",
) -> dict[str, Any]:
    relative = path.relative_to(root).as_posix()
    digest = sha256_file(path)
    stat = path.stat()
    return {
        "source_id": source_id(relative, digest),
        "relative_path": relative,
        "filename": path.name,
        "media_type": classify_extension(path),
        "extension": path.suffix.lower(),
        "role": role,
        "origin": origin,
        "canonical_url": canonical_url(url),
        "rights_status": rights_status,
        "retrieved_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "bytes": stat.st_size,
        "sha256": digest,
        "version": 1,
        "duplicate_of": None,
    }


def load_acquisition_provenance(log_path: Path) -> dict[str, dict[str, Any]]:
    """Map raw-relative path -> latest `saved` record from acquisition_log.jsonl (see acquire.py)."""
    provenance: dict[str, dict[str, Any]] = {}
    if not log_path.exists():
        return provenance
    for line in log_path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict) and record.get("event") == "saved" and record.get("path"):
            provenance[str(record["path"])] = record
    return provenance


def apply_provenance(record: dict[str, Any], acquired: dict[str, Any] | None) -> dict[str, Any]:
    """Overlay acquisition metadata, but only when the file still has the hash that was logged."""
    if not acquired or acquired.get("sha256") != record["sha256"]:
        return record
    record.update(
        role="acquired",
        origin=f"acquired:{acquired.get('connector') or 'unknown'}",
        canonical_url=canonical_url(str(acquired.get("url") or "")),
        rights_status=str(acquired.get("rights_status") or "unverified"),
        rights_review_required=bool(acquired.get("rights_review_required")),
        retrieved_at=str(acquired.get("retrieved_at") or record["retrieved_at"]),
        acquisition_target=acquired.get("target_key"),
    )
    return record


RIGHTS_DECLARATION_SCHEMA = "rights-declaration-v1"
# 与 config/acquisition_policy.json 的 allowed_rights / review_rights 同一套词汇，外加两个否定态。
KNOWN_RIGHTS = {
    "public_domain", "public_domain_us", "cc0", "cc-by", "cc-by-sa",
    "user_owned_copy", "permission_granted", "unknown", "unverified", "restricted",
}


def load_rights_declarations(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """读 sources/{slug}/rights.json——人对本地自备文件的权利声明（权利判断是人的决定，不是脚本的）。

    格式：{"schema": "rights-declaration-v1", "declarations": [
        {"path": "传记/*.txt", "rights_status": "user_owned_copy", "basis": "自购纸书，本地研究"}]}
    path 是相对 raw/ 的 POSIX glob，按顺序首个匹配生效；basis 必填。无效条目跳过并报告，不阻断 index。
    """
    if not path.exists():
        return [], []
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        return [], [f"RIGHTS_DECLARATION_UNREADABLE: {path}: {exc}"]
    if not isinstance(data, dict) or data.get("schema") != RIGHTS_DECLARATION_SCHEMA:
        return [], [f"RIGHTS_DECLARATION_BAD_SCHEMA: {path}: schema 应为 {RIGHTS_DECLARATION_SCHEMA}"]
    declarations, errors = [], []
    for i, item in enumerate(data.get("declarations") or [], 1):
        if not isinstance(item, dict) or not item.get("path"):
            errors.append(f"RIGHTS_DECLARATION_INVALID: {path} #{i}: 缺 path")
        elif item.get("rights_status") not in KNOWN_RIGHTS:
            errors.append(f"RIGHTS_DECLARATION_INVALID: {path} #{i}: 未知权利状态 {item.get('rights_status')!r}")
        elif not str(item.get("basis") or "").strip():
            errors.append(f"RIGHTS_DECLARATION_INVALID: {path} #{i}: 必须写明 basis（权利依据）")
        else:
            declarations.append(item)
    return declarations, errors


def apply_rights_declaration(record: dict[str, Any], declarations: list[dict[str, Any]]) -> dict[str, Any]:
    """人工声明覆盖默认/采集得到的权利状态，并清掉待复核标记——声明本身就是那次复核。"""
    for item in declarations:
        if fnmatch.fnmatchcase(record["relative_path"], str(item["path"])):
            record.update(
                rights_status=item["rights_status"],
                rights_basis=str(item["basis"]).strip(),
                rights_declared=True,
                rights_review_required=False,
            )
            break
    return record


def build_registry(
    raw_dir: Path,
    *,
    role: str = "user_provided",
    origin: str = "local",
    rights_status: str = "unverified",
    provenance: dict[str, dict[str, Any]] | None = None,
    declarations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a deterministic registry, recursively including nested source files.

    `provenance` (from load_acquisition_provenance) fills origin/url/rights for acquired files;
    `declarations` (from load_rights_declarations) then applies the human rights decisions on top.
    """
    raw_dir = raw_dir.resolve()
    files = sorted(
        (
            path
            for path in raw_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in SUPPORTED_SOURCE_EXTENSIONS
        ),
        key=lambda path: path.relative_to(raw_dir).as_posix().lower(),
    )
    provenance = provenance or {}
    records = []
    for path in files:
        record = make_record(path, raw_dir, role=role, origin=origin, rights_status=rights_status)
        record = apply_provenance(record, provenance.get(record["relative_path"]))
        records.append(apply_rights_declaration(record, declarations or []))
    by_hash: dict[str, dict[str, Any]] = {}
    for record in records:
        previous = by_hash.get(record["sha256"])
        if previous:
            record["duplicate_of"] = previous["source_id"]
        else:
            by_hash[record["sha256"]] = record
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "root": str(raw_dir),
        "sources": records,
    }


def write_registry(path: Path, registry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_registry(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def registry_by_relative_path(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("relative_path")): item
        for item in registry.get("sources", [])
        if isinstance(item, dict) and item.get("relative_path")
    }


def registry_fingerprint(registry: dict[str, Any]) -> str:
    """Fingerprint source identity/content, excluding timestamps and diagnostics."""
    stable = [
        {
            "source_id": item.get("source_id"),
            "relative_path": item.get("relative_path"),
            "sha256": item.get("sha256"),
            "bytes": item.get("bytes"),
        }
        for item in registry.get("sources", [])
        if isinstance(item, dict)
    ]
    payload = json.dumps(sorted(stable, key=lambda item: str(item["relative_path"])), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
