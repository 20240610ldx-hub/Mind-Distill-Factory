#!/usr/bin/env python3
"""
v6 包验收度量。Run: python scripts/measure_package.py <slug>

对照规格 §八 的验收标准输出可比数字。
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
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
    # 注意：不用传入的 root 拼路径——measure() 的 root 参数在测试中指向一个
    # 临时目录（不含 scripts/），若照抄 root/scripts/verify_provenance.py 会
    # FileNotFoundError。verify_provenance.py 永远和本文件在同一目录下，改用
    # __file__ 定位，与 validate_output.py:_load_provenance() 的做法一致。
    path = Path(__file__).resolve().parent / "verify_provenance.py"
    spec = importlib.util.spec_from_file_location("verify_provenance", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def measure(slug: str, root: Path) -> dict:
    prov = _load_provenance(root)
    out = root / "output" / slug
    refs = out / "references"

    skill_text = (out / "SKILL.md").read_text(encoding="utf-8")
    lines = len(skill_text.splitlines())

    # 分母：processed/ 下所有 extracts[].text 的归一化字数
    denominator = 0
    for path in sorted((root / "sources" / slug / "processed").glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        for extract in data.get("extracts", []) if isinstance(data, dict) else []:
            denominator += len(prov.normalize(extract.get("text", "")))

    # 分子：核心层 + 证据卡的逐字引文，去重——子串感知。SKILL.md 里的引文
    # 常常是 evidence.md 对应卡片的一个截短片段（同一句话，卡片给更长上下
    # 文），二者只是字符串不同，不是内容不同；若只用精确字符串 set 去重，
    # 这种「短引文完整包含于长卡片」的情况会被计两次，虚增存活率。做法：
    # 按长度从长到短排序，若某片段已完整出现在某个已保留的更长片段中，
    # 则视为重复、不再计入；否则保留。
    fragments: list[str] = []
    for _, quote in prov.extract_skill_quotes(skill_text):
        normalized = prov.normalize(quote)
        if normalized:
            fragments.append(normalized)
    evidence_path = refs / "evidence.md"
    if evidence_path.exists():
        for card in prov.parse_evidence_cards(evidence_path.read_text(encoding="utf-8")):
            normalized = prov.normalize(card["verbatim"])
            if normalized:
                fragments.append(normalized)

    kept: list[str] = []
    for fragment in sorted(set(fragments), key=len, reverse=True):
        if not any(fragment in longer for longer in kept):
            kept.append(fragment)
    numerator = sum(len(f) for f in kept)

    cases = counter = 0
    clusters: set[str] = set()
    cases_path = refs / "cases.md"
    if cases_path.exists():
        text = cases_path.read_text(encoding="utf-8")
        blocks = re.split(r"^###\s+", text, flags=re.MULTILINE)[1:]
        cases = len(blocks)
        counter = sum(1 for b in blocks if "反例" in b)
        clusters = set(re.findall(r"^\*\*对应原则簇：\*\*\s*(\S+)\s*$", text, re.MULTILINE))

    return {
        "lines": lines,
        "evidence_chars": numerator,
        "corpus_chars": denominator,
        "evidence_survival_pct": round(100 * numerator / denominator, 2) if denominator else 0.0,
        "cases": cases,
        "counter_cases": counter,
        "clusters_covered": len(clusters),
    }


def main() -> int:
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <slug>")
        return 1
    root = Path(__file__).resolve().parent.parent
    result = measure(sys.argv[1], root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
