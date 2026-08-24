#!/usr/bin/env python3
"""
对既有 frameworks.{lang}.json 的出厂引文做逐字审计。

用于把存量产物的溯源缺陷显性化，也是 P2 闸门的实弹验证工具。
Run: python scripts/audit_legacy_quotes.py <slug>
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass


def _load_provenance(root: Path):
    path = root / "scripts" / "verify_provenance.py"
    spec = importlib.util.spec_from_file_location("verify_provenance", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def collect_quotes(framework: dict) -> list[tuple[str, str]]:
    """从 frameworks.zh.json 收集所有出厂引文：原则原文 + 标志性名言。"""
    quotes: list[tuple[str, str]] = []
    for principle in framework.get("core_principles", []):
        text = principle.get("original_quote", "")
        if text:
            quotes.append((f"principle{principle.get('order', '?')}", text))
    for i, quote in enumerate(framework.get("signature_quotes", []), 1):
        text = quote.get("text", "")
        if text:
            quotes.append((f"quote{i}", text))
    return quotes


def audit(slug: str, root: Path) -> dict:
    prov = _load_provenance(root)
    framework_path = root / "output" / slug / "frameworks.zh.json"
    framework = json.loads(framework_path.read_text(encoding="utf-8-sig"))
    corpus = prov.load_corpus(slug, root)
    passed = 0
    failed: list[dict] = []
    quotes = collect_quotes(framework)
    for tag, quote in quotes:
        hit = prov.find_verbatim(quote, corpus)
        if hit:
            passed += 1
            continue
        failed.append({
            "tag": tag,
            "quote": quote,
            "longest_prefix": prov.longest_verbatim_prefix(quote, corpus),
        })
    return {"total": len(quotes), "passed": passed, "failed": failed}


def main() -> int:
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <slug>")
        return 1
    slug = sys.argv[1]
    root = Path(__file__).resolve().parent.parent
    result = audit(slug, root)
    print(f"逐字审计 '{slug}': {result['passed']}/{result['total']} PASS")
    for item in result["failed"]:
        print(f"  FAIL {item['tag']:12s} 最长逐字前缀={item['longest_prefix']:2d}字  「{item['quote'][:32]}」")
    return 0 if not result["failed"] else 2


if __name__ == "__main__":
    sys.exit(main())
