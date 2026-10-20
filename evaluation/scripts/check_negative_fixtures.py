#!/usr/bin/env python3
"""负例夹具：确认闸门本身没有退化。

    python evaluation/scripts/check_negative_fixtures.py [--json]

每个负例 = evaluation/fixtures/negative/_base（全规则合规的 v6 包）+ 一处故意的缺陷
（fixtures.json）。逐个在临时目录里组装成 output/ + sources/ 结构，跑
validate_output 的 package 阶段（strict 负例加 --strict），要求期望的错误码全部出现。

阳性对照同样重要：_base 在默认与 strict 下都必须零错误。否则所有负例都会「被拦」，
而闸门其实什么也没分辨出来——这正是本项目反复出现的「该拒的报 clean」的镜像。
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "scripts") not in sys.path:  # 按路径加载本模块时也能找到 scripts/ 里的 sibling
    sys.path.insert(0, str(REPO / "scripts"))
from sibling import load_sibling  # noqa: E402  按路径加载兄弟模块的唯一入口

FIXTURE_DIR = REPO / "evaluation" / "fixtures" / "negative"
SCHEMA = "negative-fixtures-v1"


@functools.lru_cache(maxsize=None)
def _script(name: str) -> Any:
    return load_sibling(name, f"_negfx_{name}")


def load_manifest(fixture_dir: Path = FIXTURE_DIR) -> dict[str, Any]:
    data = json.loads((fixture_dir / "fixtures.json").read_text(encoding="utf-8"))
    if data.get("schema") != SCHEMA:
        raise ValueError(f"fixtures.json: schema 应为 {SCHEMA}")
    ids = [f["id"] for f in data["fixtures"]]
    if len(ids) != len(set(ids)):
        raise ValueError("fixtures.json: id 重复")
    return data


def _repeat(spec: list | None) -> str:
    if not spec:
        return ""
    text, times = spec
    return str(text) * int(times)


def apply_patch(root: Path, patch: dict[str, Any]) -> None:
    """把一处缺陷打进夹具副本；找不到要替换的原文就报错，不能让负例悄悄变成阳性。"""
    path = root / patch["file"]
    text = path.read_text(encoding="utf-8")
    if "find" in patch:
        new = patch.get("replace", "") + _repeat(patch.get("replace_repeat"))
        if patch["find"] not in text:
            raise ValueError(f"{patch['file']}: 找不到 {patch['find'][:30]!r}")
        text = text.replace(patch["find"], new, 1)
    elif "regex" in patch:
        new = patch.get("replace", "") + _repeat(patch.get("replace_repeat"))
        text, n = re.subn(patch["regex"], lambda _: new, text, count=1)
        if n == 0:
            raise ValueError(f"{patch['file']}: 正则 {patch['regex'][:30]!r} 没有匹配")
    elif "append" in patch:
        text += patch["append"] + _repeat(patch.get("append_repeat"))
    else:
        raise ValueError(f"无法识别的 patch：{sorted(patch)}")
    path.write_text(text, encoding="utf-8", newline="\n")


def assemble(workdir: Path, slug: str, fixture: dict[str, Any] | None, fixture_dir: Path = FIXTURE_DIR) -> Path:
    """在 workdir 里搭出 validate_output 认的目录结构，返回数据根目录。"""
    stage = workdir / "fixture"
    shutil.copytree(fixture_dir / "_base", stage)
    for patch in (fixture or {}).get("patches", []):
        apply_patch(stage, patch)
    root = workdir / "root"
    out = root / "output" / slug
    shutil.copytree(stage / "package", out)
    shutil.copy(stage / "framework_core.json", out / "framework_core.json")
    shutil.copy(stage / "review.md", out / "review.md")
    raw = root / "sources" / slug / "raw"
    shutil.copytree(stage / "corpus", raw)
    registry = _script("source_registry")
    rights = (fixture or {}).get("rights", "public_domain")
    registry.write_registry(root / "sources" / slug / "processed" / "source_registry.json",
                            registry.build_registry(raw, rights_status=rights))
    return root


def validate(root: Path, slug: str, strict: bool) -> list[str]:
    cwd = os.getcwd()
    try:
        os.chdir(root)  # validate_package 按 cwd 解析 output/、sources/
        return _script("validate_output").validate_package(slug, strict=strict)
    finally:
        os.chdir(cwd)


def codes(errors: list[str]) -> list[str]:
    return sorted({e.split(":", 1)[0] for e in errors if not e.startswith("WARNING")})


def run(fixture_dir: Path = FIXTURE_DIR) -> dict[str, Any]:
    manifest = load_manifest(fixture_dir)
    slug = manifest["slug"]
    controls = []
    for strict in (False, True):
        with tempfile.TemporaryDirectory() as td:
            found = codes(validate(assemble(Path(td), slug, None, fixture_dir), slug, strict))
        controls.append({"strict": strict, "codes": found, "clean": not found})
    results = []
    for fixture in manifest["fixtures"]:
        strict = bool(fixture.get("strict"))
        with tempfile.TemporaryDirectory() as td:
            found = codes(validate(assemble(Path(td), slug, fixture, fixture_dir), slug, strict))
        missing = [c for c in fixture["expect"] if c not in found]
        results.append({"id": fixture["id"], "defect": fixture["defect"], "strict": strict,
                        "expect": fixture["expect"], "found": found, "caught": not missing, "missing": missing})
    ok = all(c["clean"] for c in controls) and all(r["caught"] for r in results)
    return {"schema": "negative-fixtures-report-v1", "ok": ok, "controls": controls, "fixtures": results}


def render(report: dict[str, Any]) -> str:
    lines = ["## 负例夹具", "", "| 对照 | 模式 | 结果 |", "|---|---|---|"]
    for c in report["controls"]:
        lines.append(f"| _base（阳性对照） | {'strict' if c['strict'] else '默认'} | "
                     + ("✅ 零错误" if c["clean"] else f"❌ 报了 {', '.join(c['codes'])}") + " |")
    lines += ["", "| 负例 | 缺陷 | 期望 | 结果 |", "|---|---|---|---|"]
    for r in report["fixtures"]:
        verdict = "✅ 已拦截" if r["caught"] else f"❌ 漏拦：{', '.join(r['missing'])}"
        lines.append(f"| {r['id']}{'（strict）' if r['strict'] else ''} | {r['defect']} | {', '.join(r['expect'])} | {verdict} |")
    caught = sum(r["caught"] for r in report["fixtures"])
    lines += ["", f"{caught}/{len(report['fixtures'])} 个负例被拦截；" + ("闸门未退化。" if report["ok"] else "**闸门有退化，先修再合入。**")]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    if sys.platform.startswith("win"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except AttributeError:
            pass
    parser = argparse.ArgumentParser(description="负例夹具：确认闸门本身没有退化")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = run()
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else render(report), end="\n" if args.json else "")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
