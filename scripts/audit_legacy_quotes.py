#!/usr/bin/env python3
"""
对既有出厂产物的引文做逐字审计——两个独立视图：

  - json 视图：frameworks.zh.json 的 core_principles[].original_quote /
    signature_quotes[].text / 顶层 signature_quote。
  - skill_md 视图：组装后交付给用户的 output/{slug}/SKILL.md，用
    verify_provenance.extract_skill_quotes 从「原文出处」行与「标志性名言」
    章节两处结构化位置抽取。

两个视图分开计数、分开打印，不合并成一个 total——JSON 视图干净不代表渲染稿
干净：装配阶段可能在把结构化字段渲染成 Markdown 时改写或截断引文（例如丢字），
而 P2 闸门至今只审计过 JSON 一侧。此外还比对同一条「原文出处」引文在两个视图
里的通过/失败状态，标出装配阶段引入的新分歧；并记录每条通过引文命中的语料
文件属于 raw/ 还是 processed/（后者是流水线派生产物，命中它可能只是在跟引文
自己的抽取样本兜圈子）。

用于把存量产物的溯源缺陷显性化，也是 P2 闸门的实弹验证工具。
Run: python scripts/audit_legacy_quotes.py <slug>
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

# 字面 '-' 未出现在此正则中，仍统一使用原始字符串以保持全库风格一致
PRINCIPLE_TAG_RE = re.compile(r"^principle(\d+)$")


def _load_provenance(root: Path):
    path = root / "scripts" / "verify_provenance.py"
    spec = importlib.util.spec_from_file_location("verify_provenance", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def collect_quotes(framework: dict) -> list[tuple[str, str]]:
    """从 frameworks.zh.json 收集所有出厂引文：顶层标志性引言 + 原则原文 + 标志性名言。"""
    quotes: list[tuple[str, str]] = []
    header = framework.get("signature_quote", "")
    if header:
        quotes.append(("signature_quote_header", header))
    for principle in framework.get("core_principles", []):
        text = principle.get("original_quote", "")
        if text:
            quotes.append((f"principle{principle.get('order', '?')}", text))
    for i, quote in enumerate(framework.get("signature_quotes", []), 1):
        text = quote.get("text", "")
        if text:
            quotes.append((f"quote{i}", text))
    return quotes


def _corpus_file_origins(slug: str, root: Path, prov) -> dict[str, str]:
    """文件名 -> 'raw' 或 'processed'，镜像 verify_provenance.load_corpus 的扫描顺序。

    load_corpus() 本身只返回 (文件名, 归一化正文)，不保留子目录来源，且按本任务
    约束不得修改该函数。这里独立做一次同规则（同一 TEXT_SUFFIXES、同样先 raw
    后 processed）的目录扫描，仅用于诊断标注，不参与逐字比对本身。若同名文件
    同时出现在两个子目录（未见于当前语料），保留先遇到的 raw 归类。
    """
    origins: dict[str, str] = {}
    for sub in ("raw", "processed"):
        base = root / "sources" / slug / sub
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in prov.TEXT_SUFFIXES:
                continue
            origins.setdefault(path.name, sub)
    return origins


def _check_quote(tag: str, quote: str, prov, corpus, origins: dict[str, str]) -> dict:
    hit = prov.find_verbatim(quote, corpus)
    if hit:
        return {
            "tag": tag,
            "quote": quote,
            "status": "pass",
            "matched_file": hit,
            "matched_dir": origins.get(hit, "unknown"),
        }
    return {
        "tag": tag,
        "quote": quote,
        "status": "fail",
        "longest_prefix": prov.longest_verbatim_prefix(quote, corpus),
    }


def _run_view(tag_quote_pairs: list[tuple[str, str]], prov, corpus, origins: dict[str, str]) -> dict:
    passed = 0
    failed: list[dict] = []
    passed_detail: list[dict] = []
    ordered: list[dict] = []  # 保留原始顺序，供跨视图按位对齐比对分歧
    for tag, quote in tag_quote_pairs:
        result = _check_quote(tag, quote, prov, corpus, origins)
        ordered.append(result)
        if result["status"] == "pass":
            passed += 1
            passed_detail.append(result)
        else:
            failed.append({
                "tag": tag,
                "quote": quote,
                "longest_prefix": result["longest_prefix"],
            })
    return {
        "total": len(tag_quote_pairs),
        "passed": passed,
        "failed": failed,
        "passed_detail": passed_detail,
        "ordered": ordered,
    }


def _find_divergences(json_view: dict, skill_md_view: dict) -> dict:
    """比对「同一条原文出处引文」在 JSON 视图与 SKILL.md 视图里的通过/失败状态。

    只有 core_principles[].original_quote ↔ SKILL.md 中文版「**原文出处：**」行
    是同一条引文在两个产物里的对应渲染，且两边都按原则编号的文档顺序出现，因此
    按位对齐（第 N 个 principle ↔ 第 N 条「原文出处」）。signature_quotes /
    signature_quote_header 在 SKILL.md 里没有可解析的对应位置——「标志性名言」
    表格用的是三级标题，而 extract_skill_quotes 的 QUOTES_SECTION_RE 只认二级
    标题，因此匹配不到任何「标志性名言」行（这是 verify_provenance.py 的既有
    行为，本工具按约束不改动它）——故不参与本比对。

    按位对齐这个假设本身可能不成立：如果某个 Skill 的 SKILL.md 渲染出的
    「原文出处」行数与 JSON 的 principle 数不一致（缺章节、标题变体、装配器
    漏渲染……），zip() 会在较短的一侧停止，未配对的 principle 就此从比对中
    静默消失——这正是本工具本来要拦截的那类「看不出问题」。因此这里不假装
    两者必然等长：数量对不上时仍然比对能对齐的那一段（能比多少比多少），但
    把两侧的计数都如实带回给调用方，让不完整的比对没法被误读成完整的比对。
    """
    json_principles = sorted(
        (item for item in json_view["ordered"] if PRINCIPLE_TAG_RE.match(item["tag"])),
        key=lambda item: int(PRINCIPLE_TAG_RE.match(item["tag"]).group(1)),
    )
    skill_source_lines = [item for item in skill_md_view["ordered"] if item["tag"] == "原文出处"]
    pairs: list[dict] = []
    for j, s in zip(json_principles, skill_source_lines):
        if j["status"] == s["status"]:
            continue
        pairs.append({
            "json_tag": j["tag"],
            "json_status": j["status"],
            "json_quote": j["quote"],
            "skill_md_status": s["status"],
            "skill_md_quote": s["quote"],
        })
    return {
        "pairs": pairs,
        "json_principle_count": len(json_principles),
        "skill_md_source_line_count": len(skill_source_lines),
    }


def audit(slug: str, root: Path) -> dict:
    prov = _load_provenance(root)
    corpus = prov.load_corpus(slug, root)
    origins = _corpus_file_origins(slug, root, prov)

    framework_path = root / "output" / slug / "frameworks.zh.json"
    framework = json.loads(framework_path.read_text(encoding="utf-8-sig"))
    json_view = _run_view(collect_quotes(framework), prov, corpus, origins)

    skill_md_path = root / "output" / slug / "SKILL.md"
    skill_md_quotes: list[tuple[str, str]] = []
    if skill_md_path.exists():
        skill_md_text = skill_md_path.read_text(encoding="utf-8")
        skill_md_quotes = prov.extract_skill_quotes(skill_md_text)
    skill_md_view = _run_view(skill_md_quotes, prov, corpus, origins)

    divergence_result = _find_divergences(json_view, skill_md_view)
    json_count = divergence_result["json_principle_count"]
    skill_md_count = divergence_result["skill_md_source_line_count"]

    return {
        "json": json_view,
        "skill_md": skill_md_view,
        "divergences": divergence_result["pairs"],
        "divergence_coverage": {
            "json_principle_count": json_count,
            "skill_md_source_line_count": skill_md_count,
            "matched": json_count == skill_md_count,
        },
    }


def _print_failures(view: dict) -> None:
    for item in view["failed"]:
        print(f"  FAIL {item['tag']:24s} 最长逐字前缀={item['longest_prefix']:2d}字  「{item['quote'][:32]}」")


def main() -> int:
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <slug>")
        return 1
    slug = sys.argv[1]
    root = Path(__file__).resolve().parent.parent
    result = audit(slug, root)

    json_view = result["json"]
    skill_md_view = result["skill_md"]

    print(f"逐字审计 '{slug}' [json: frameworks.zh.json]: {json_view['passed']}/{json_view['total']} PASS")
    _print_failures(json_view)

    print(f"逐字审计 '{slug}' [skill_md: 组装后 SKILL.md]: {skill_md_view['passed']}/{skill_md_view['total']} PASS")
    _print_failures(skill_md_view)

    coverage = result["divergence_coverage"]
    if not coverage["matched"]:
        print(
            "WARNING 分歧比对不完整：json 侧 "
            f"{coverage['json_principle_count']} 条 principle vs skill_md 侧 "
            f"{coverage['skill_md_source_line_count']} 条「原文出处」行，数量不一致——"
            "只比对了两者中较短的一段，未配对的 principle 未纳入下方分歧检测，"
            "以下列表并不完整。"
        )

    if result["divergences"]:
        print("JSON/SKILL.md 分歧（同一条原文出处引文在两个产物里的通过/失败状态不同）：")
        for d in result["divergences"]:
            print(
                f"  DIVERGE {d['json_tag']:12s} json={d['json_status']:4s}"
                f" skill_md={d['skill_md_status']:4s}  「{d['json_quote'][:32]}」"
            )

    processed_only = [
        item
        for view in (json_view, skill_md_view)
        for item in view["passed_detail"]
        if item["matched_dir"] == "processed"
    ]
    print(f"仅靠 processed/ 语料通过的引文数：{len(processed_only)}")
    for item in processed_only:
        print(f"  PROCESSED_ONLY {item['tag']:12s} 命中文件={item['matched_file']}")

    has_defects = bool(json_view["failed"]) or bool(skill_md_view["failed"])
    return 2 if has_defects else 0


if __name__ == "__main__":
    sys.exit(main())
