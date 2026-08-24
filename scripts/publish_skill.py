#!/usr/bin/env python3
"""Automated Skill Publishing Script for Mind Distill Factory.

This script automates copying a thinker skill from output/ to gallery/
and updating gallery/index.json after running verification checks.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Error reading JSON from {path}: {e}", file=sys.stderr)
        sys.exit(1)


def save_json(path: Path, data: Any) -> None:
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as e:
        print(f"Error writing JSON to {path}: {e}", file=sys.stderr)
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


def _load_validator():
    """按路径加载同目录的 validate_output 模块（scripts/ 不是包）。"""
    import importlib.util
    path = Path(__file__).resolve().parent / "validate_output.py"
    spec = importlib.util.spec_from_file_location("validate_output", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def is_v6_package(skill_md: Path) -> bool:
    """v6 包由 SKILL.md frontmatter 的 format_version 判定。

    委托给 validate_output.is_v6_skill（Task 4 已加固：只在解析出的 frontmatter
    块内匹配，避免正文示例代码块误判），避免两套独立实现互相漂移。
    """
    content = skill_md.read_text(encoding="utf-8")
    return _load_validator().is_v6_skill(content)


def copy_package(output_dir: Path, gallery_dir: Path, is_v6: bool) -> list[str]:
    """把 output/{slug}/ 的包内容同步到 gallery/{slug}/，返回已复制的相对路径。"""
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


def file_sha256(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_manifest(gallery_dir: Path, copied: list[str], is_v6: bool) -> Path:
    """写 gallery/{slug}/manifest.json，含每个文件的 sha256。

    format_version 必须反映实际检测到的包格式——legacy 发布（is_v6=False）不能被
    打上 6 的戳，否则会跟同一次运行打印的 format_version=legacy 与
    index.json 里记的 format_version: 1 互相矛盾。
    """
    manifest = {
        "format_version": 6 if is_v6 else 1,
        "files": {rel: file_sha256(gallery_dir / rel) for rel in sorted(copied)},
    }
    path = gallery_dir / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def main() -> int:
    # Handle Windows console encoding for UTF-8 output
    if sys.platform.startswith('win'):
        try:
            sys.stdout.reconfigure(encoding='utf-8')
            sys.stderr.reconfigure(encoding='utf-8')
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="Publish a thinker skill to the gallery.")
    parser.add_argument("--slug", required=True, help="The slug of the thinker (e.g. seneca)")
    parser.add_argument("--dry-run", action="store_true", help="Perform checks but do not modify files")
    parser.add_argument("--force", action="store_true", help="Skip pre-publication validation check")
    parser.add_argument("--notes", help="Custom notes to add/update in gallery/index.json")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    slug = args.slug.strip().lower()

    output_dir = root / "output" / slug
    output_skill = output_dir / "SKILL.md"
    gallery_dir = root / "gallery" / slug
    index_file = root / "gallery" / "index.json"

    print(f"=== Publishing Distilled Skill for '{slug}' ===")

    # 1. Validation Checks
    if not output_skill.exists():
        print(f"ERROR: Compiled skill file not found at {output_skill}", file=sys.stderr)
        return 1

    if not args.force:
        print("Running pre-publication validation check...")
        # Check skill stage validation
        ret, stdout, stderr = run_command(
            [sys.executable, "scripts/validate_output.py", "skill", slug],
            root
        )
        if ret != 0:
            print("ERROR: Skill validation failed!", file=sys.stderr)
            print(stdout, file=sys.stderr)
            print(stderr, file=sys.stderr)
            return 1
        print("[OK] Skill stage validation passed.")

    # 2. Extract Metadata
    zh_framework_path = output_dir / "frameworks.zh.json"
    en_framework_path = output_dir / "frameworks.en.json"

    if not zh_framework_path.exists():
        print(f"ERROR: Chinese framework JSON not found at {zh_framework_path}", file=sys.stderr)
        return 1

    zh_fw = load_json(zh_framework_path)
    en_fw = load_json(en_framework_path) if en_framework_path.exists() else {}

    name_zh = zh_fw.get("person_name")
    name_en = en_fw.get("person_name") or slug.replace("-", " ").title()
    name_original = zh_fw.get("person_name_original") or en_fw.get("person_name_original") or name_zh
    era = zh_fw.get("era") or en_fw.get("era") or "Unknown"
    primary_cat = zh_fw.get("primary_category") or "philosophy"
    secondary_cats = zh_fw.get("secondary_categories") or []

    print(f"Extracted Metadata:")
    print(f"  Name (ZH): {name_zh}")
    print(f"  Name (EN): {name_en}")
    print(f"  Original Name: {name_original}")
    print(f"  Era: {era}")
    print(f"  Categories: primary={primary_cat}, secondary={secondary_cats}")

    if args.dry_run:
        print("\n[DRY RUN] Publishing steps skipped.")
        return 0

    # 3. Artifact Syncing
    print(f"Syncing artifacts to {gallery_dir}...")
    gallery_dir.mkdir(parents=True, exist_ok=True)
    try:
        v6 = is_v6_package(output_skill)
        copied = copy_package(output_dir, gallery_dir, is_v6=v6)
        manifest_path = write_manifest(gallery_dir, copied, is_v6=v6)
        print(f"  Copied {len(copied)} file(s) to {gallery_dir}: {', '.join(copied)}")
        print(f"  Wrote {manifest_path.name} (format_version={'6' if v6 else 'legacy'})")
    except Exception as e:
        print(f"ERROR copying files: {e}", file=sys.stderr)
        return 1

    # 4. Update gallery/index.json
    if not index_file.exists():
        print(f"WARNING: gallery/index.json not found. Creating a new one...", file=sys.stderr)
        index_data = {
            "version": "1.0",
            "description": "Mind Distill Factory — Gallery Index",
            "skills": []
        }
    else:
        index_data = load_json(index_file)

    skills_list = index_data.setdefault("skills", [])
    entry = next((e for e in skills_list if e.get("slug") == slug), None)

    current_date = dt.date.today().isoformat()

    # "lang": "zh" only means something for a v6 package (zh-only core; English is a
    # separate {slug}-en skill). A legacy skill is a single bilingual file — stamping
    # "zh" on it would misrepresent it as zh-only on every republish, so the field is
    # only set for v6 publishes and left untouched/absent otherwise (matching the
    # pre-v6 status quo: none of the existing legacy gallery/index.json entries carry
    # a "lang" key today).
    if entry:
        print(f"Updating existing index entry for '{slug}'...")
        entry["name_zh"] = name_zh
        entry["name_en"] = name_en
        entry["name_original"] = name_original
        entry["primary_category"] = primary_cat
        entry["secondary_categories"] = secondary_cats
        entry["era"] = era
        entry["distilled_on"] = current_date
        entry["review_status"] = "PASS"
        if v6:
            entry["lang"] = "zh"
        entry["format_version"] = 6 if v6 else 1
        entry["has_attachments"] = v6
        if args.notes:
            entry["notes"] = args.notes
    else:
        print(f"Creating new index entry for '{slug}'...")
        new_entry = {
            "slug": slug,
            "name_zh": name_zh,
            "name_en": name_en,
            "name_original": name_original,
            "primary_category": primary_cat,
            "secondary_categories": secondary_cats,
            "era": era,
            "distilled_on": current_date,
            "distill_method": "pipeline",
            "review_status": "PASS",
            "skill_dir": f"gallery/{slug}/",
            "install_path": f"{slug}-wisdom",
            "notes": args.notes or f"Distilled skill for {name_en}.",
            "format_version": 6 if v6 else 1,
            "has_attachments": v6,
        }
        if v6:
            new_entry["lang"] = "zh"
        skills_list.append(new_entry)

    save_json(index_file, index_data)
    print("[OK] gallery/index.json updated.")

    # 5. Post-publication Verification
    print("Running post-publication gallery verification...")
    ret, stdout, stderr = run_command(
        [sys.executable, "scripts/validate_output.py", "gallery", slug],
        root
    )
    if ret != 0:
        print("ERROR: Gallery validation failed after publishing!", file=sys.stderr)
        print(stdout, file=sys.stderr)
        print(stderr, file=sys.stderr)
        return 1

    print(f"[OK] Success! Skill '{slug}' published and validated successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
