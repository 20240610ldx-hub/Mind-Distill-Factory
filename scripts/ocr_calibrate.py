#!/usr/bin/env python3
"""OCR 校准与扫描件诊断。

    python scripts/mdf.py ocr calibrate [--degrade all|none|light|heavy] [--font PATH] [--json]
    python scripts/mdf.py ocr scan <file.pdf> [--json]

calibrate：把一份已知真值的文本渲染成无文字层的「扫描件」PDF（可选轻度/重度退化：倾斜、
模糊、噪点、降采样），送进 index 用的同一条 PDF→OCR 路径（local_source_pipeline.
extract_pdf_pages），再与真值比对：

- 字符错误率 CER（去空白后的编辑距离 / 真值长度）；
- 逐字存活率：真值里每一句（≥6 字）在 OCR 文本里能否按 P2 的归一化规则逐字找回——
  这才是证据链关心的数字，CER 低不等于引文能溯源；
- 引擎置信度，以及清洗闸门对这份 OCR 结果打的标（如 low_ocr_confidence）。

不同退化档位的置信度与 CER 放在一张表里，用来校准 clean_corpus 的 OCR 阈值。
scan：对真实扫描件逐页报告分类、OCR 状态与置信度（没有真值，不算 CER）。
"""

from __future__ import annotations

import argparse
import io
import json
import random
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import clean_corpus  # noqa: E402
import local_source_pipeline as lsp  # noqa: E402
import pdf_quality  # noqa: E402

CODE_ROOT = SCRIPTS.parent
DEFAULT_TRUTH = CODE_ROOT / "evaluation" / "fixtures" / "ocr" / "sample_zh.txt"
PAGE_SEPARATOR = re.compile(r"^---\s*$", re.MULTILINE)
SENTENCE_RE = re.compile(r"[^。！？；!?;\n]+[。！？；!?;]?")
FONT_CANDIDATES = (
    "C:/Windows/Fonts/simsun.ttc", "C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/NotoSerifSC-VF.ttf",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSerifCJK-Regular.ttc", "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc", "/System/Library/Fonts/PingFang.ttc",
)
DEGRADE = {
    "none": {"angle": 0.0, "blur": 0.0, "noise": 0.0, "scale": 1.0},
    "light": {"angle": 0.6, "blur": 0.4, "noise": 0.06, "scale": 1.0},
    "heavy": {"angle": 1.5, "blur": 0.9, "noise": 0.14, "scale": 0.55},
}
MIN_SENTENCE_CHARS = 6


def load_truth(path: Path = DEFAULT_TRUTH) -> list[str]:
    pages = [p.strip() for p in PAGE_SEPARATOR.split(path.read_text(encoding="utf-8"))]
    return [p for p in pages if p]


def find_cjk_font(explicit: str | None = None) -> Path | None:
    for candidate in ([explicit] if explicit else []) + list(FONT_CANDIDATES):
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    return None


# ── 合成扫描件 ────────────────────────────────────────────────────────


def _wrap(text: str, per_line: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.splitlines():
        while len(paragraph) > per_line:
            lines.append(paragraph[:per_line])
            paragraph = paragraph[per_line:]
        lines.append(paragraph)
    return lines


def render_page(text: str, font: Path | None, *, dpi: int = 200, degrade: str = "none", seed: int = 0) -> bytes:
    """把一页文字画成 A5 灰度图（PNG 字节）。font 为 None 时用 PIL 内置字体，只供管线测试。"""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    width, height = round(148 / 25.4 * dpi), round(210 / 25.4 * dpi)
    size = round(12 / 72 * dpi)
    face = ImageFont.truetype(str(font), size) if font else ImageFont.load_default()
    margin = round(15 / 25.4 * dpi)
    image = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(image)
    y = margin
    for line in _wrap(text, max(1, (width - 2 * margin) // size)):
        draw.text((margin, y), line, fill=0, font=face)
        y += round(size * 1.6)
    spec = DEGRADE[degrade]
    rng = random.Random(seed)
    if spec["scale"] < 1.0:  # 低分辨率扫描：缩小再放大
        small = (max(1, int(width * spec["scale"])), max(1, int(height * spec["scale"])))
        image = image.resize(small, Image.BILINEAR).resize((width, height), Image.BILINEAR)
    if spec["angle"]:
        image = image.rotate(rng.uniform(-spec["angle"], spec["angle"]), resample=Image.BICUBIC, fillcolor=255)
    if spec["blur"]:
        image = image.filter(ImageFilter.GaussianBlur(spec["blur"]))
    if spec["noise"]:
        noise = Image.effect_noise((width, height), 64).point(lambda v: 255 if v > 128 else 0)
        image = Image.blend(image, noise, spec["noise"])
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", dpi=(dpi, dpi))
    return buffer.getvalue()


def build_pdf(images: list[bytes], path: Path, dpi: int = 200) -> Path:
    """每张图一页，不带文字层——与扫描书完全同构。"""
    import fitz  # type: ignore

    doc = fitz.open()
    for png in images:
        pix = fitz.Pixmap(png)
        page = doc.new_page(width=pix.width * 72 / dpi, height=pix.height * 72 / dpi)
        page.insert_image(page.rect, stream=png)
    doc.save(path)
    doc.close()
    return path


# ── 指标 ──────────────────────────────────────────────────────────────


def levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def _squash(text: str) -> str:
    return "".join(ch for ch in text if not ch.isspace())


def _normalize() -> Callable[[str], str]:
    try:
        import verify_provenance  # 与 P2 用同一套归一化（去标点、繁简折叠）
        return verify_provenance.normalize
    except Exception:  # noqa: BLE001 - 缺 opencc 等可选依赖时退回只去空白
        return _squash


def page_metrics(truth: str, ocr_text: str, normalize: Callable[[str], str] | None = None) -> dict[str, Any]:
    normalize = normalize or _normalize()
    t, o = _squash(truth), _squash(ocr_text)
    sentences = [s for s in (m.group(0).strip() for m in SENTENCE_RE.finditer(truth))
                 if len(normalize(s)) >= MIN_SENTENCE_CHARS]
    haystack = normalize(ocr_text)
    survived = [s for s in sentences if normalize(s) in haystack]
    return {
        "truth_chars": len(t),
        "cer": round(levenshtein(t, o) / len(t), 4) if t else 0.0,
        "sentences": len(sentences),
        "sentences_verbatim": len(survived),
        "lost_sentences": [s for s in sentences if s not in survived],
    }


# ── 运行 ──────────────────────────────────────────────────────────────


def engine_available() -> list[str]:
    names = list(pdf_quality._INJECTED)
    for name in pdf_quality.RUNNER_FACTORIES:
        try:
            pdf_quality.get_runner(name)
            names.append(name)
        except Exception:  # noqa: BLE001 - 没装就是不可用
            continue
    return names


def _ocr_stats(pages: list[dict[str, Any]]) -> dict[str, Any]:
    ok = [float((p.get("ocr") or {}).get("confidence") or 0) for p in pages if (p.get("ocr") or {}).get("status") == "ok"]
    return {
        "pages_total": len(pages),
        "ocr_required": sum(1 for p in pages if p.get("quality", {}).get("ocr_required")),
        "ocr_ok": len(ok),
        "mean_confidence": round(sum(ok) / len(ok), 4) if ok else None,
    }


def calibrate(truth_pages: list[str], *, font: Path | None, degrades: list[str], dpi: int = 200,
              workdir: Path | None = None) -> dict[str, Any]:
    normalize = _normalize()
    levels = []
    with tempfile.TemporaryDirectory() as td:
        base = workdir or Path(td)
        for level in degrades:
            images = [render_page(text, font, dpi=dpi, degrade=level, seed=i) for i, text in enumerate(truth_pages)]
            pdf = build_pdf(images, base / f"synthetic-{level}.pdf", dpi=dpi)
            pages, meta = lsp.extract_pdf_pages(pdf)
            rows = []
            for truth, page in zip(truth_pages, pages):
                ocr = page.get("ocr") or {}
                row = page_metrics(truth, ocr.get("text", ""), normalize)
                row.update(status=ocr.get("status"), backend=ocr.get("backend"), confidence=ocr.get("confidence"),
                           classification=page.get("quality", {}).get("classification"))
                rows.append(row)
            stats = _ocr_stats(pages)
            _, gate = clean_corpus.clean_pdf_pages([p.get("text", "") for p in pages], stats)
            chars = sum(r["truth_chars"] for r in rows) or 1
            sentences = sum(r["sentences"] for r in rows)
            levels.append({
                "degrade": level,
                "document_type": meta.get("document_type"),
                "cer": round(sum(r["cer"] * r["truth_chars"] for r in rows) / chars, 4),
                "verbatim_survival": round(sum(r["sentences_verbatim"] for r in rows) / sentences, 4) if sentences else None,
                "mean_confidence": stats["mean_confidence"],
                "ocr_ok_pages": stats["ocr_ok"], "pages": len(pages),
                "gate_flags": gate.get("flags", []), "gate_reasons": gate.get("reasons", []),
                "page_rows": rows,
            })
    return {"schema": "ocr-calibration-v1", "font": str(font) if font else None, "dpi": dpi,
            "low_confidence_threshold": clean_corpus.THRESHOLDS["ocr_low_confidence"], "levels": levels}


def scan(pdf: Path) -> dict[str, Any]:
    pages, meta = lsp.extract_pdf_pages(pdf)
    stats = _ocr_stats(pages)
    _, gate = clean_corpus.clean_pdf_pages([p.get("text", "") for p in pages], stats)
    rows = [{
        "page": p["page_number"], "classification": p.get("quality", {}).get("classification"),
        "ocr_status": (p.get("ocr") or {}).get("status"), "backend": (p.get("ocr") or {}).get("backend"),
        "confidence": (p.get("ocr") or {}).get("confidence"), "chars": len(_squash(p.get("text", ""))),
    } for p in pages]
    return {"schema": "ocr-scan-v1", "file": str(pdf), "document_type": meta.get("document_type"),
            **stats, "gate_flags": gate.get("flags", []), "gate_reasons": gate.get("reasons", []), "pages": rows}


def render_calibration(report: dict[str, Any]) -> str:
    lines = [f"## OCR 校准（字体 {report['font'] or 'PIL 内置'}，{report['dpi']} dpi）", "",
             "| 退化档 | CER | 逐字存活率 | 平均置信度 | OCR 成功页 | 清洗闸门 |", "|---|---|---|---|---|---|"]
    for lv in report["levels"]:
        gate = "、".join(lv["gate_reasons"] + lv["gate_flags"]) or "通过"
        survival = "—" if lv["verbatim_survival"] is None else f"{lv['verbatim_survival']:.0%}"
        conf = "—" if lv["mean_confidence"] is None else f"{lv['mean_confidence']:.3f}"
        lines.append(f"| {lv['degrade']} | {lv['cer']:.2%} | {survival} | {conf} | {lv['ocr_ok_pages']}/{lv['pages']} | {gate} |")
    lines += ["", f"清洗闸门的低置信阈值：{report['low_confidence_threshold']}。逐字存活率低于 100% 的档位，"
              "其引文必须对照原图核实，不能直接当 high 证据。"]
    lost = [(lv["degrade"], s) for lv in report["levels"] for r in lv["page_rows"] for s in r["lost_sentences"]]
    if lost:
        lines += ["", "逐字丢失的句子（前 10 条）："] + [f"- [{d}] {s}" for d, s in lost[:10]]
    return "\n".join(lines) + "\n"


def render_scan(report: dict[str, Any]) -> str:
    lines = [f"## 扫描件诊断：{report['file']}", "",
             f"类型 {report['document_type']}；需 OCR {report['ocr_required']} 页，成功 {report['ocr_ok']} 页，"
             f"平均置信度 {report['mean_confidence']}；清洗闸门："
             + ("、".join(report["gate_reasons"] + report["gate_flags"]) or "通过"), "",
             "| 页 | 分类 | OCR | 引擎 | 置信度 | 字数 |", "|---|---|---|---|---|---|"]
    for r in report["pages"]:
        lines.append(f"| {r['page']} | {r['classification']} | {r['ocr_status'] or '—'} | {r['backend'] or '—'} "
                     f"| {r['confidence'] if r['confidence'] is not None else '—'} | {r['chars']} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    if sys.platform.startswith("win"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except AttributeError:
            pass
    parser = argparse.ArgumentParser(prog="mdf ocr", description="OCR 校准（合成扫描件对真值）与扫描件逐页诊断")
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("calibrate", help="合成扫描件 → OCR → 对真值算 CER 与逐字存活率")
    p.add_argument("--truth", type=Path, default=DEFAULT_TRUTH, help="真值文本，页之间用单独一行 --- 分隔")
    p.add_argument("--degrade", choices=[*DEGRADE, "all"], default="all")
    p.add_argument("--font", help="CJK 字体文件（默认在常见系统路径里找）")
    p.add_argument("--dpi", type=int, default=200)
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("scan", help="逐页报告真实扫描件的分类、OCR 状态与置信度")
    p.add_argument("pdf", type=Path)
    p.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if not engine_available():
        print("没有可用的 OCR 引擎：pip install -e .[ocr]（rapidocr_onnxruntime）后重试。", file=sys.stderr)
        return 2
    if args.action == "scan":
        report = scan(args.pdf)
        print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else render_scan(report), end="\n" if args.json else "")
        return 0
    font = find_cjk_font(args.font)
    if font is None:
        print("找不到 CJK 字体：用 --font 指定一个能显示中文的字体文件。", file=sys.stderr)
        return 2
    levels = list(DEGRADE) if args.degrade == "all" else [args.degrade]
    report = calibrate(load_truth(args.truth), font=font, degrades=levels, dpi=args.dpi)
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else render_calibration(report), end="\n" if args.json else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
