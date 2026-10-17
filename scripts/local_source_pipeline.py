#!/usr/bin/env python3
"""Local source indexing, sharding, and reduction for Stage 1A.

This script keeps large local source libraries out of a single agent context.

Usage:
  python scripts/local_source_pipeline.py index <person-slug>
  python scripts/local_source_pipeline.py reduce <person-slug> [--person-name NAME]
  python scripts/local_source_pipeline.py stats <person-slug>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

try:
    from pdf_quality import classify_document, classify_page, quality_band, run_ocr
except ImportError:  # pragma: no cover - supports package-style imports
    from scripts.pdf_quality import classify_document, classify_page, quality_band, run_ocr  # type: ignore

try:
    from sampling import SamplingConfig, build_sampling_plan, write_plan
except ImportError:  # pragma: no cover - supports package-style imports
    from scripts.sampling import SamplingConfig, build_sampling_plan, write_plan  # type: ignore

try:
    from source_registry import build_registry, registry_by_relative_path, registry_fingerprint, write_registry
except ImportError:  # pragma: no cover - supports package-style imports
    from scripts.source_registry import build_registry, registry_by_relative_path, registry_fingerprint, write_registry  # type: ignore

try:
    from worker_dispatch import build_dispatch_plan
except ImportError:  # pragma: no cover - supports package-style imports
    from scripts.worker_dispatch import build_dispatch_plan  # type: ignore

try:
    from cost_estimator import estimate_cost, write_estimate
except ImportError:  # pragma: no cover - supports package-style imports
    from scripts.cost_estimator import estimate_cost, write_estimate  # type: ignore

try:
    from source_registry import sha256_file
except ImportError:  # pragma: no cover - supports package-style imports
    from scripts.source_registry import sha256_file  # type: ignore

try:
    from slug_rules import slug_arg
except ImportError:  # pragma: no cover - supports package-style imports
    from scripts.slug_rules import slug_arg  # type: ignore


TARGET_TOKENS = 30_000
SOFT_LIMIT_TOKENS = 50_000
HARD_LIMIT_TOKENS = 60_000
DEFAULT_MAX_EXTRACTS = 60
DEFAULT_MIN_EXTRACTS = 30
SUPPORTED_TEXT_EXTS = {".txt", ".md", ".markdown"}
SUPPORTED_PDF_EXTS = {".pdf"}


if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass


@dataclass
class Segment:
    source_file: str
    source_title: str
    source_detail: str
    source_priority: int
    language: str
    text: str
    token_estimate: int
    source_id: str = ""
    extraction_quality_band: str = "unknown"
    ocr_required: bool = False
    unit_id: str = ""
    stratum_key: str = ""


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def raw_dir(slug: str) -> Path:
    return repo_root() / "sources" / slug / "raw"


def processed_dir(slug: str) -> Path:
    return repo_root() / "sources" / slug / "processed"


def shard_dir(slug: str) -> Path:
    return processed_dir(slug) / "local_shards"


def estimate_tokens(text: str) -> int:
    """Conservative mixed Chinese/English token estimate."""
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    non_ws = sum(1 for ch in text if not ch.isspace()) - cjk
    return max(1, int(cjk * 1.05 + non_ws / 3.8))


def detect_language(text: str) -> str:
    sample = text[:4000]
    cjk = sum(1 for ch in sample if "\u4e00" <= ch <= "\u9fff")
    letters = sum(1 for ch in sample if ("a" <= ch.lower() <= "z"))
    if cjk > letters:
        return "zh"
    if letters:
        return "en"
    return "other"


def priority_for_name(name: str) -> int:
    lower = name.lower()
    if lower.startswith("p1_"):
        return 1
    if lower.startswith("p2_"):
        return 2
    if lower.startswith("p3_"):
        return 3
    if "primary" in lower or "first" in lower:
        return 2
    if "secondary" in lower or "biography" in lower:
        return 4
    if "duplicate" in lower:
        return 8
    return 5


def read_text_file(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "big5", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def read_json_file(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def init_stage1a_status(slug: str) -> None:
    try:
        import task_status  # type: ignore

        task_status.init_stage1a(slug)
    except Exception as e:
        print(f"WARNING: could not initialize Stage 1A task_status.json: {e}")


def extract_pdf_pages(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return every PDF page with text/image diagnostics and OCR eligibility."""
    pages: list[dict[str, Any]] = []
    metadata: dict[str, Any] = {}

    try:
        import fitz  # type: ignore

        doc = fitz.open(path)
        metadata = {
            "page_count": len(doc),
            "title": doc.metadata.get("title") or path.stem,
            "producer": doc.metadata.get("producer") or "",
            "backend": "fitz",
        }
        page_quality_records: list[Any] = []
        for idx in range(len(doc)):
            page = doc[idx]
            text = page.get_text("text") or ""
            image_infos: list[dict[str, Any]] = []
            try:
                page_rect = page.rect
                page_area = float(page_rect.width * page_rect.height)
                for image in page.get_images(full=True):
                    rects = page.get_image_rects(image)
                    rect = rects[0] if rects else None
                    image_infos.append({
                        "xref": image[0],
                        "width": image[2],
                        "height": image[3],
                        "bbox": [rect.x0, rect.y0, rect.x1, rect.y1] if rect else None,
                    })
            except Exception as image_error:
                page_area = 0.0
                metadata.setdefault("image_diagnostics_warnings", []).append(
                    f"page {idx + 1}: {image_error}"
                )
            quality = classify_page(idx + 1, text, image_infos, page_area)
            page_quality_records.append(quality)
            ocr = None
            if quality.ocr_required:
                ocr = run_ocr(page, backend="auto")
                if ocr.get("status") == "ok" and ocr.get("text"):
                    # Preserve both layers. The OCR text is only a fallback for
                    # indexing and remains explicitly marked in the page record.
                    text = (text.strip() + "\n\n" + ocr["text"].strip()).strip()
            pages.append({
                "page_number": idx + 1,
                "text": text.strip(),
                "native_text": (page.get_text("text") or "").strip(),
                "quality": quality.as_dict(),
                "quality_band": quality_band(quality.quality_score),
                "ocr": ocr,
            })
        doc.close()
        metadata["document_type"] = classify_document(page_quality_records)
        metadata["ocr_page_count"] = sum(1 for quality in page_quality_records if quality.ocr_required)
        metadata["ocr_success_count"] = sum(
            1 for page in pages if page.get("ocr", {}).get("status") == "ok"
        )
        return pages, metadata
    except Exception as fitz_error:
        # Do not merge a partially extracted fitz result with pypdf output.
        # A fallback starts from a clean page list and records the backend error.
        pages = []
        metadata["fitz_error"] = str(fitz_error)

    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(str(path))
        metadata.update({"page_count": len(reader.pages), "title": path.stem, "backend": "pypdf"})
        for idx, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            quality = classify_page(idx + 1, text)
            pages.append({
                "page_number": idx + 1,
                "text": text.strip(),
                "native_text": text.strip(),
                "quality": quality.as_dict(),
                "quality_band": quality_band(quality.quality_score),
                "ocr": {"status": "requires_fitz_for_images", "backend": None, "text": "", "confidence": 0.0},
            })
        metadata["document_type"] = classify_document([
            classify_page(page["page_number"], page["native_text"], [], 0.0)
            for page in pages
        ])
        metadata["ocr_page_count"] = 0
        metadata["ocr_success_count"] = 0
        return pages, metadata
    except Exception as pypdf_error:
        metadata["pypdf_error"] = str(pypdf_error)
        return pages, metadata


def write_pdf_sidecar(slug: str, path: Path, source_id: str, source_sha256: str, pages: list[dict[str, Any]]) -> None:
    """Persist page-addressable extracted text tied to the raw PDF hash."""
    if not pages or not source_id:
        return
    extracted_dir = processed_dir(slug) / "extracted"
    extracted_dir.mkdir(parents=True, exist_ok=True)
    text_path = extracted_dir / f"{source_id}.txt"
    metadata_path = extracted_dir / f"{source_id}.json"
    text_parts: list[str] = []
    page_records: list[dict[str, Any]] = []
    for page in pages:
        page_number = page["page_number"]
        page_text = page.get("text", "")
        text_parts.append(f"--- Page {page_number} ---\n{page_text}")
        ocr = page.get("ocr") or {}
        page_records.append({
            "page_number": page_number,
            "text_sha256": hashlib.sha256(page_text.encode("utf-8")).hexdigest(),
            "extraction_method": "ocr" if ocr.get("status") == "ok" else "fitz",
            "quality": page.get("quality", {}),
            "quality_band": page.get("quality_band", "unknown"),
            "ocr": ocr,
        })
    text_path.write_text("\n\n".join(text_parts).strip() + "\n", encoding="utf-8")
    metadata_path.write_text(
        json.dumps({
            "schema_version": "extracted-pdf-sidecar-v1",
            "source_id": source_id,
            "parent_sha256": source_sha256,
            "source_file": path.name,
            "pages": page_records,
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def split_text(text: str, max_tokens: int = HARD_LIMIT_TOKENS) -> list[str]:
    """Split a long text into paragraph-aware token-bounded chunks."""
    text = re.sub(r"\r\n?", "\n", text).strip()
    if estimate_tokens(text) <= max_tokens:
        return [text] if text else []

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n+", text) if p.strip()]
    if len(paragraphs) <= 1:
        return split_by_window(text, max_tokens)

    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for para in paragraphs:
        para_tokens = estimate_tokens(para)
        if para_tokens > max_tokens:
            if current:
                chunks.append("\n\n".join(current))
                current = []
                current_tokens = 0
            chunks.extend(split_by_window(para, max_tokens))
            continue
        if current and current_tokens + para_tokens > max_tokens:
            chunks.append("\n\n".join(current))
            current = [para]
            current_tokens = para_tokens
        else:
            current.append(para)
            current_tokens += para_tokens
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def split_by_window(text: str, max_tokens: int) -> list[str]:
    chars_per_token = 2 if detect_language(text) == "zh" else 4
    window = max(2000, int(max_tokens * chars_per_token * 0.85))
    overlap = min(1200, max(200, window // 20))
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + window)
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(0, end - overlap)
    return [chunk for chunk in chunks if chunk]


def collect_segments(slug: str) -> tuple[list[Segment], list[dict[str, Any]]]:
    source_dir = raw_dir(slug)
    if not source_dir.exists():
        raise SystemExit(f"Missing raw source directory: {source_dir}")

    segments: list[Segment] = []
    files_meta: list[dict[str, Any]] = []
    files = sorted(
        [p for p in source_dir.rglob("*") if p.is_file()],
        key=lambda p: (priority_for_name(p.name), p.relative_to(source_dir).as_posix().lower()),
    )
    registry = build_registry(source_dir)
    registry_map = registry_by_relative_path(registry)
    write_registry(processed_dir(slug) / "source_registry.json", registry)

    for path in files:
        ext = path.suffix.lower()
        priority = priority_for_name(path.name)
        relative_path = path.relative_to(source_dir).as_posix()
        registry_item = registry_map.get(relative_path, {})
        file_meta: dict[str, Any] = {
            "file": relative_path,
            "bytes": path.stat().st_size,
            "sha256": registry_item.get("sha256") or sha256_file(path),
            "source_id": registry_item.get("source_id"),
            "priority": priority,
            "extension": ext,
            "status": "indexed",
        }

        if ext in SUPPORTED_TEXT_EXTS:
            text = read_text_file(path)
            chunks = split_text(text)
            file_meta["chunk_count"] = len(chunks)
            file_meta["token_estimate"] = estimate_tokens(text)
            for idx, chunk in enumerate(chunks, start=1):
                segments.append(
                    Segment(
                        source_file=relative_path,
                        source_title=path.stem,
                        source_detail=f"{relative_path}, text chunk {idx}/{len(chunks)}",
                        source_priority=priority,
                        language=detect_language(chunk),
                        text=chunk,
                        token_estimate=estimate_tokens(chunk),
                        source_id=registry_item.get("source_id", ""),
                        extraction_quality_band="good",
                    )
                )
        elif ext in SUPPORTED_PDF_EXTS:
            pages, metadata = extract_pdf_pages(path)
            file_meta.update(metadata)
            write_pdf_sidecar(
                slug,
                path,
                registry_item.get("source_id", ""),
                registry_item.get("sha256", ""),
                pages,
            )
            file_meta["pages"] = [
                {
                    "page_number": page["page_number"],
                    "quality": page["quality"],
                    "quality_band": page["quality_band"],
                    "ocr": page.get("ocr"),
                }
                for page in pages
            ]
            if not pages or not any(page.get("text") for page in pages):
                file_meta["status"] = "no_extractable_text"
                file_meta["chunk_count"] = 0
            else:
                page_buffer: list[str] = []
                page_start = pages[0]["page_number"]
                page_end = pages[0]["page_number"]
                chunk_count = 0

                def flush_pdf_buffer() -> None:
                    nonlocal page_buffer, page_start, page_end, chunk_count
                    text = "\n\n".join(page_buffer).strip()
                    if not text:
                        return
                    for sub_idx, chunk in enumerate(split_text(text), start=1):
                        chunk_count += 1
                        detail = f"{relative_path}, pages {page_start}-{page_end}, chunk {chunk_count}"
                        if sub_idx > 1:
                            detail += f".{sub_idx}"
                        segments.append(
                            Segment(
                                source_file=relative_path,
                                source_title=metadata.get("title") or path.stem,
                                source_detail=detail,
                                source_priority=priority,
                                language=detect_language(chunk),
                                text=chunk,
                                token_estimate=estimate_tokens(chunk),
                                source_id=registry_item.get("source_id", ""),
                                extraction_quality_band=(
                                    "review" if any(page.get("quality_band") == "review" for page in pages)
                                    else "good"
                                ),
                                ocr_required=any(page.get("quality", {}).get("ocr_required") for page in pages),
                            )
                        )
                    page_buffer = []

                current_tokens = 0
                for page in pages:
                    page_number = page["page_number"]
                    page_text = page.get("text", "")
                    if not page_text:
                        continue
                    page_tokens = estimate_tokens(page_text)
                    if page_buffer and current_tokens + page_tokens > TARGET_TOKENS:
                        flush_pdf_buffer()
                        page_start = page_number
                        current_tokens = 0
                    if not page_buffer:
                        page_start = page_number
                    page_buffer.append(f"--- Page {page_number} ---\n{page_text}")
                    page_end = page_number
                    current_tokens += page_tokens
                flush_pdf_buffer()
                file_meta["chunk_count"] = chunk_count
                file_meta["token_estimate"] = sum(estimate_tokens(page.get("text", "")) for page in pages)
                file_meta["ocr_required_pages"] = sum(
                    1 for page in pages if page.get("quality", {}).get("ocr_required")
                )
                file_meta["ocr_success_pages"] = sum(
                    1 for page in pages if page.get("ocr", {}).get("status") == "ok"
                )
        else:
            file_meta["status"] = "unsupported_extension"
            file_meta["reason"] = "extension is not supported by the source indexer"
            file_meta["chunk_count"] = 0

        files_meta.append(file_meta)

    return segments, files_meta


def pack_shards(segments: list[Segment]) -> list[dict[str, Any]]:
    shards: list[dict[str, Any]] = []
    current: list[Segment] = []
    current_tokens = 0

    def flush() -> None:
        nonlocal current, current_tokens
        if not current:
            return
        shard_id = f"shard_{len(shards) + 1:03d}"
        passages = []
        for idx, segment in enumerate(current, start=1):
            passages.append(
                {
                    "passage_id": f"{shard_id}_p{idx:03d}",
                    "source_file": segment.source_file,
                    "source_title": segment.source_title,
                    "source_detail": segment.source_detail,
                    "source_priority": segment.source_priority,
                    "language": segment.language,
                    "source_id": segment.source_id,
                    "extraction_quality_band": segment.extraction_quality_band,
                    "ocr_required": segment.ocr_required,
                    "token_estimate": segment.token_estimate,
                    "text": segment.text,
                }
            )
        shards.append(
            {
                "shard_id": shard_id,
                "token_estimate": current_tokens,
                "target_tokens": TARGET_TOKENS,
                "soft_limit_tokens": SOFT_LIMIT_TOKENS,
                "hard_limit_tokens": HARD_LIMIT_TOKENS,
                "worker_extract_target": "8-15",
                "passages": passages,
            }
        )
        current = []
        current_tokens = 0

    for segment in segments:
        if segment.token_estimate > HARD_LIMIT_TOKENS:
            for chunk in split_text(segment.text):
                split_segment = Segment(
                    source_file=segment.source_file,
                    source_title=segment.source_title,
                    source_detail=f"{segment.source_detail}, oversize split",
                    source_priority=segment.source_priority,
                    language=detect_language(chunk),
                    text=chunk,
                    token_estimate=estimate_tokens(chunk),
                    source_id=segment.source_id,
                    extraction_quality_band=segment.extraction_quality_band,
                    ocr_required=segment.ocr_required,
                )
                if current and current_tokens + split_segment.token_estimate > HARD_LIMIT_TOKENS:
                    flush()
                current.append(split_segment)
                current_tokens += split_segment.token_estimate
                if current_tokens >= TARGET_TOKENS:
                    flush()
            continue

        if current and current_tokens + segment.token_estimate > HARD_LIMIT_TOKENS:
            flush()
        current.append(segment)
        current_tokens += segment.token_estimate
        if current_tokens >= TARGET_TOKENS:
            flush()

    flush()
    return shards


def recommended_workers(total_tokens: int) -> str:
    if total_tokens < 40_000:
        return "1"
    if total_tokens < 150_000:
        return "2-4"
    if total_tokens < 500_000:
        return "4-8"
    return "index-and-sample-first"


def write_index(slug: str) -> None:
    out_dir = shard_dir(slug)
    out_dir.mkdir(parents=True, exist_ok=True)

    # A re-index is a new source snapshot. Remove generated shard/worker files
    # first so the reducer cannot accidentally consume an older run.
    for stale in out_dir.glob("shard_*.json"):
        stale.unlink()
    worker_dir = out_dir / "worker_outputs"
    if worker_dir.exists():
        for stale in worker_dir.glob("*.json"):
            stale.unlink()

    segments, files_meta = collect_segments(slug)
    shards = pack_shards(segments)
    total_tokens = sum(s["token_estimate"] for s in shards)
    over_limit = [s["shard_id"] for s in shards if s["token_estimate"] > HARD_LIMIT_TOKENS]
    registry = json.loads((processed_dir(slug) / "source_registry.json").read_text(encoding="utf-8"))
    input_fingerprint = registry_fingerprint(registry)

    for shard in shards:
        shard["input_fingerprint"] = input_fingerprint
        shard["source_ids"] = sorted({p.get("source_id") for p in shard["passages"] if p.get("source_id")})

    sampling_units = [
        {
            "unit_id": shard["shard_id"],
            "shard_id": shard["shard_id"],
            "token_estimate": shard["token_estimate"],
            "source_ids": shard.get("source_ids", []),
            "source_file": ",".join(sorted({p.get("source_file", "") for p in shard["passages"] if p.get("source_file")})),
            "language": "mixed",
            "extraction_quality_band": "review" if any(
                p.get("extraction_quality_band") in {"review", "poor", "unreadable"}
                for p in shard["passages"]
            ) else "good",
            "ocr_required": any(p.get("ocr_required") for p in shard["passages"]),
            "input_fingerprint": input_fingerprint,
        }
        for shard in shards
    ]
    # For large corpora, select shard units before dispatch. Small corpora stay
    # exhaustive, but still emit the same auditable plan and coverage report.
    sample_config = SamplingConfig(mode="auto")
    sampling_plan = build_sampling_plan(sampling_units, config=sample_config)
    write_plan(out_dir / "sampling_plan.json", sampling_plan)
    selected_ids = {
        item.get("unit_id") for item in sampling_plan.get("selected_units", [])
    }
    if sampling_plan.get("mode") == "stratified":
        shards = [shard for shard in shards if shard.get("shard_id") in selected_ids]
        total_tokens = sum(s["token_estimate"] for s in shards)
        over_limit = [s["shard_id"] for s in shards if s["token_estimate"] > HARD_LIMIT_TOKENS]
    for shard in shards:
        (out_dir / f"{shard['shard_id']}.json").write_text(
            json.dumps(shard, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    dispatch_plan = build_dispatch_plan(sampling_plan["selected_units"])
    (out_dir / "dispatch_plan.json").write_text(
        json.dumps(dispatch_plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    ocr_pages = sum(int(item.get("ocr_required_pages") or 0) for item in files_meta)
    cost_estimate = estimate_cost(
        selected_tokens=total_tokens,
        total_tokens=sum(int(item.get("token_estimate") or 0) for item in files_meta),
        shard_count=len(shards),
        ocr_pages=ocr_pages,
    )
    write_estimate(out_dir / "cost_estimate.json", cost_estimate)

    manifest = {
        "schema_version": "local-source-manifest-v2",
        "person_slug": slug,
        "created_at": date.today().isoformat(),
        "input_fingerprint": input_fingerprint,
        "raw_dir": str(raw_dir(slug)),
        "shard_dir": str(out_dir),
        "source_registry": "../source_registry.json",
        "sampling_plan": "local_shards/sampling_plan.json",
        "dispatch_plan": "local_shards/dispatch_plan.json",
        "cost_estimate": "local_shards/cost_estimate.json",
        "target_tokens": TARGET_TOKENS,
        "soft_limit_tokens": SOFT_LIMIT_TOKENS,
        "hard_limit_tokens": HARD_LIMIT_TOKENS,
        "total_token_estimate": total_tokens,
        "recommended_worker_count": recommended_workers(total_tokens),
        "recommended_max_concurrency": dispatch_plan.get("recommended_max_concurrency"),
        "sampling_mode": sampling_plan.get("mode"),
        "shard_count": len(shards),
        "over_limit_shards": over_limit,
        "files": files_meta,
        "shards": [
            {
                "shard_id": shard["shard_id"],
                "path": f"local_shards/{shard['shard_id']}.json",
                "token_estimate": shard["token_estimate"],
                "passage_count": len(shard["passages"]),
                "source_files": sorted({p["source_file"] for p in shard["passages"]}),
                "input_fingerprint": shard.get("input_fingerprint"),
                "source_ids": shard.get("source_ids", []),
            }
            for shard in shards
        ],
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    init_stage1a_status(slug)

    print(f"[OK] Indexed {slug}")
    print(f"  files: {len(files_meta)}")
    print(f"  shards: {len(shards)}")
    print(f"  estimated tokens: {total_tokens:,}")
    print(f"  recommended workers: {manifest['recommended_worker_count']}")
    if over_limit:
        print(f"  WARNING: over-limit shards: {', '.join(over_limit)}")
    print(f"  manifest: {out_dir / 'manifest.json'}")
    print(f"  task status: {out_dir / 'task_status.json'}")


def normalize_text(text: str) -> str:
    text = re.sub(r"\s+", "", text).lower()
    text = re.sub(r"[^\w\u4e00-\u9fff]", "", text)
    return text


def extract_sort_key(ext: dict[str, Any]) -> tuple[int, int, int]:
    confidence_score = {"high": 0, "medium": 1, "low": 2}.get(ext.get("confidence"), 3)
    content_score = {
        "principle": 0,
        "quote": 1,
        "behavior_record": 2,
        "expression_sample": 3,
        "analysis": 4,
    }.get(ext.get("content_type"), 5)
    return (confidence_score, content_score, -len(ext.get("text", "")))


def load_worker_outputs(slug: str) -> list[dict[str, Any]]:
    out_dir = shard_dir(slug)
    manifest_path = out_dir / "manifest.json"
    manifest = read_json_file(manifest_path) if manifest_path.exists() else {}
    expected_ids = {item.get("shard_id") for item in manifest.get("shards", [])}
    expected_fingerprint = manifest.get("input_fingerprint")
    candidates = [
        out_dir / f"{shard_id}_extracts.json"
        for shard_id in sorted(expected_ids)
        if shard_id
    ]
    worker_dir = out_dir / "worker_outputs"
    if worker_dir.exists():
        candidates.extend(sorted(worker_dir.glob("*.json")))

    extracts: list[dict[str, Any]] = []
    for path in candidates:
        try:
            data = read_json_file(path)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, list):
            items = data
            metadata: dict[str, Any] = {}
        elif isinstance(data, dict):
            items = data.get("extracts", [])
            metadata = data
        else:
            continue
        fingerprint = metadata.get("input_fingerprint")
        if expected_fingerprint and fingerprint != expected_fingerprint:
            continue
        shard_id = metadata.get("shard_id")
        if expected_ids and (not shard_id or shard_id not in expected_ids):
            continue
        for item in items:
            if isinstance(item, dict):
                item.setdefault("_worker_output", path.name)
                item.setdefault("input_fingerprint", fingerprint)
                item.setdefault("shard_id", shard_id)
                extracts.append(item)
    return extracts


def is_duplicate(text: str, seen_hashes: set[str], accepted_norms: list[str]) -> bool:
    norm = normalize_text(text)
    if not norm:
        return True
    digest = hashlib.sha1(norm.encode("utf-8")).hexdigest()
    if digest in seen_hashes:
        return True
    prefix = norm[:120]
    for existing in accepted_norms:
        if prefix and prefix == existing[:120]:
            return True
        shorter = min(len(norm), len(existing))
        if shorter > 80 and SequenceMatcher(None, norm[:1200], existing[:1200]).ratio() >= 0.92:
            return True
    seen_hashes.add(digest)
    accepted_norms.append(norm)
    return False


def sanitize_extract(ext: dict[str, Any]) -> dict[str, Any]:
    content_type = ext.get("content_type") or "analysis"
    if content_type == "passage":
        content_type = "analysis"
    out = {
        "text": ext.get("text", "").strip(),
        "source_title": ext.get("source_title") or ext.get("title") or "Local source",
        "source_detail": ext.get("source_detail") or ext.get("detail") or ext.get("source_file") or "",
        "source_url": ext.get("source_url", ""),
        "language": ext.get("language") or detect_language(ext.get("text", "")),
        "content_type": content_type,
        "topic_tags": ext.get("topic_tags") or ext.get("style_tags") or [],
        "confidence": ext.get("confidence") or "high",
        "confidence_reason": ext.get("confidence_reason") or "用户提供的本地素材，由 Stage 1A shard worker 提取。",
    }
    if content_type == "expression_sample":
        out["style_tags"] = ext.get("style_tags") or ext.get("topic_tags") or []
        if ext.get("dimension"):
            out["dimension"] = ext["dimension"]
        if ext.get("analysis"):
            out["analysis"] = ext["analysis"]
    return out


def reduce_outputs(slug: str, person_name: str | None = None, max_extracts: int = DEFAULT_MAX_EXTRACTS) -> None:
    extracts = [sanitize_extract(ext) for ext in load_worker_outputs(slug)]
    extracts = [ext for ext in extracts if ext["text"] and ext["source_detail"]]
    extracts.sort(key=extract_sort_key)

    seen_hashes: set[str] = set()
    accepted_norms: list[str] = []
    accepted: list[dict[str, Any]] = []
    for ext in extracts:
        if is_duplicate(ext["text"], seen_hashes, accepted_norms):
            continue
        accepted.append(ext)
        if len(accepted) >= max_extracts:
            break

    if not accepted:
        raise SystemExit(
            f"No worker extracts found for {slug}. Expected files like "
            f"{shard_dir(slug)}\\shard_001_extracts.json or worker_outputs\\*.json"
        )

    manifest_path = shard_dir(slug) / "manifest.json"
    manifest = {}
    if manifest_path.exists():
        manifest = read_json_file(manifest_path)

    output = {
        "person": person_name or slug.replace("-", " ").title(),
        "person_slug": slug,
        "source_type": "user_provided",
        "collected_at": date.today().isoformat(),
        "extracts": accepted,
        "collection_notes": (
            "Stage 1A local-source reducer output. "
            f"Merged {len(extracts)} worker candidates into {len(accepted)} deduplicated extracts. "
            f"Shard count: {manifest.get('shard_count', 'unknown')}; "
            f"recommended workers: {manifest.get('recommended_worker_count', 'unknown')}."
        ),
    }

    out_path = processed_dir(slug) / "user_sources.json"
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] Reduced {len(accepted)} extracts to {out_path}")
    if len(accepted) < DEFAULT_MIN_EXTRACTS:
        print(f"WARNING: only {len(accepted)} extracts; target is {DEFAULT_MIN_EXTRACTS}-{DEFAULT_MAX_EXTRACTS}")


def print_stats(slug: str) -> None:
    manifest_path = shard_dir(slug) / "manifest.json"
    if not manifest_path.exists():
        raise SystemExit(f"Missing manifest: {manifest_path}. Run index first.")
    manifest = read_json_file(manifest_path)
    print(f"slug: {slug}")
    print(f"shards: {manifest['shard_count']}")
    print(f"estimated tokens: {manifest['total_token_estimate']:,}")
    print(f"recommended workers: {manifest['recommended_worker_count']}")
    print(f"hard limit: {manifest['hard_limit_tokens']:,}")
    for shard in manifest["shards"]:
        marker = "OVER" if shard["token_estimate"] > manifest["hard_limit_tokens"] else "OK"
        print(f"  {shard['shard_id']}: {shard['token_estimate']:,} tokens, {shard['passage_count']} passages [{marker}]")
    status_path = shard_dir(slug) / "task_status.json"
    if status_path.exists():
        try:
            import task_status  # type: ignore

            print("\nresume status:")
            task_status.cmd_summary(status_path)
        except Exception as e:
            print(f"WARNING: could not read task status: {e}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    index_parser = subparsers.add_parser("index", help="extract and shard sources/{slug}/raw")
    index_parser.add_argument("slug", type=slug_arg)

    reduce_parser = subparsers.add_parser("reduce", help="merge shard worker outputs into user_sources.json")
    reduce_parser.add_argument("slug", type=slug_arg)
    reduce_parser.add_argument("--person-name", default=None)
    reduce_parser.add_argument("--max-extracts", type=int, default=DEFAULT_MAX_EXTRACTS)

    stats_parser = subparsers.add_parser("stats", help="show shard manifest stats")
    stats_parser.add_argument("slug", type=slug_arg)

    args = parser.parse_args()
    if args.command == "index":
        write_index(args.slug)
    elif args.command == "reduce":
        reduce_outputs(args.slug, args.person_name, args.max_extracts)
    elif args.command == "stats":
        print_stats(args.slug)


if __name__ == "__main__":
    main()
