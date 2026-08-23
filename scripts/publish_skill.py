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
    gallery_skill = gallery_dir / "SKILL.md"
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
        shutil.copy2(output_skill, gallery_skill)
        print(f"  Copied {output_skill.name} to {gallery_skill}")
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
            "notes": args.notes or f"Distilled skill for {name_en}."
        }
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
