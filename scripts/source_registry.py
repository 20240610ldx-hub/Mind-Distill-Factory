#!/usr/bin/env python3
"""Source registry and content fingerprints for local distillation corpora."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = "source-registry-v2"
SUPPORTED_SOURCE_EXTENSIONS = {".txt", ".md", ".markdown", ".pdf", ".epub"}


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


def build_registry(
    raw_dir: Path,
    *,
    role: str = "user_provided",
    origin: str = "local",
    rights_status: str = "unverified",
    provenance: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a deterministic registry, recursively including nested source files.

    `provenance` (from load_acquisition_provenance) fills origin/url/rights for acquired files.
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
        records.append(apply_provenance(record, provenance.get(record["relative_path"])))
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
