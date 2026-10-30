#!/usr/bin/env python3
"""对 gallery/ 下每个人物包跑 `published` 校验（默认模式，不加 --strict）；CI 用它守住已发布的包。

已知例外只登记在 KNOWN_EXCEPTIONS 一处：例外包不过不算失败；它若意外通过，提示把它移出清单。
其余任何一个包不过，退出码为 1。只读 gallery/，不联网、不读语料。

Run: python scripts/validate_gallery_all.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
from sibling import load_sibling  # noqa: E402  按路径加载兄弟模块的唯一入口

# slug → 为什么留着不过的包。清空一条前先确认它真的过了（本脚本会提示）。
KNOWN_EXCEPTIONS: dict[str, str] = {
    "charlie-munger": "早期模板，缺 v5 章节与反公式规则；用户决定（2026-10-24）留作 legacy，"
                      "等用户提供自有副本后按 v6 重新蒸馏",
}


def gallery_slugs(root: Path) -> list[str]:
    gallery = root / "gallery"
    return sorted(p.name for p in gallery.iterdir() if p.is_dir()) if gallery.is_dir() else []


def check_gallery(root: Path, exceptions: dict[str, str] = KNOWN_EXCEPTIONS) -> tuple[list[str], list[str]]:
    """返回 (失败, 提示)。失败非空即 CI 失败；提示只提醒维护例外清单。"""
    validator = load_sibling("validate_output")
    slugs = gallery_slugs(root)
    failures: list[str] = []
    notices: list[str] = []
    if not slugs:
        failures.append(f"gallery 为空或不存在：{root / 'gallery'}")
    for slug in slugs:
        errors = [e for e in validator.validate_published(slug, root) if not e.startswith("WARNING:")]
        if slug in exceptions:
            if errors:
                print(f"⏭️  {slug}: 已知例外，{len(errors)} 个错误不计（{exceptions[slug]}）")
            else:
                notices.append(f"{slug} 已通过 published 校验，请把它移出 KNOWN_EXCEPTIONS")
            continue
        if errors:
            failures.append(f"{slug}: {len(errors)} 个错误")
            print(f"❌ {slug}:")
            for e in errors:
                print(f"  {e}")
        else:
            print(f"✅ {slug}")
    for slug in sorted(set(exceptions) - set(slugs)):
        notices.append(f"{slug} 不在 gallery/ 里，请把它移出 KNOWN_EXCEPTIONS")
    return failures, notices


def main() -> int:
    failures, notices = check_gallery(Path("."))
    prefix = "::warning::" if os.environ.get("GITHUB_ACTIONS") == "true" else "⚠️  "
    for n in notices:
        print(f"{prefix}{n}")
    if failures:
        print(f"\n❌ {len(failures)} 个包未通过 published 校验：")
        for f in failures:
            print(f"  {f}")
        return 1
    print("\n✅ gallery 全部通过 published 校验（已知例外除外）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
