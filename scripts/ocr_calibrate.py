#!/usr/bin/env python3
"""OCR 校准与扫描件诊断。

    python scripts/mdf.py ocr calibrate [--degrade all|none|light|heavy|severe] [--backend auto|all|NAME] [--font PATH] [--json]
    python scripts/mdf.py ocr scan <file.pdf> [--pages 1-3,40] [--out DIR] [--backend auto|NAME] [--json]

calibrate：把一份已知真值的文本渲染成无文字层的「扫描件」PDF（可选轻度/重度/严重退化：倾斜、
模糊、噪点、降采样），送进 index 用的同一条 PDF→OCR 路径（local_source_pipeline.
extract_pdf_pages），再与真值比对：

- 字符错误率 CER（去空白后的编辑距离 / 真值长度）；
- 逐字存活率：真值里每一句（≥6 字）在 OCR 文本里能否按 P2 的归一化规则逐字找回——
  这才是证据链关心的数字，CER 低不等于引文能溯源；
- 引擎置信度，以及清洗闸门对这份 OCR 结果打的标（如 low_ocr_confidence）。

不同退化档位的置信度与 CER 放在一张表里，用来校准 clean_corpus 的 OCR 阈值；--backend all
把每个装好的引擎各跑一遍，同一批图、同一套指标，引擎之间可以直接比。
scan：对真实扫描件逐页报告分类、OCR 状态与置信度（没有真值，不算 CER）。--pages 只抽几页
（几百页的书先抽样再决定要不要整本跑），--out 把每页送进 OCR 的图和识别出的文字成对存下，
供人对照原图核实——worker 规则里「OCR 页引文对照原图后才可标 high」靠的就是这一步。
"""

from __future__ import annotations

import argparse
import io
import json
import random
import re
import sys
import tempfile
import time
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
    # 老复印件 / 手机翻拍的低分辨率扫描：低置信阈值就落在这一档和 heavy 之间
    "severe": {"angle": 2.5, "blur": 1.3, "noise": 0.22, "scale": 0.42},
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
        # 噪点用带种子的随机字节（Image.effect_noise 不收种子，同一档两次跑出的数会不一样）
        noise = Image.frombytes("L", (width, height), rng.randbytes(width * height)).point(lambda v: 255 if v > 128 else 0)
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
    return pdf_quality.summarize_ocr(pages)


def calibrate(truth_pages: list[str], *, font: Path | None, degrades: list[str], dpi: int = 200,
              backends: list[str] | None = None, workdir: Path | None = None) -> dict[str, Any]:
    normalize = _normalize()
    levels = []
    with tempfile.TemporaryDirectory() as td:
        base = workdir or Path(td)
        pdfs = {}
        for level in degrades:  # 同一档的图只画一次，所有引擎读同一份 PDF
            images = [render_page(text, font, dpi=dpi, degrade=level, seed=i) for i, text in enumerate(truth_pages)]
            pdfs[level] = build_pdf(images, base / f"synthetic-{level}.pdf", dpi=dpi)
        for backend, level in ((b, lv) for b in backends or ["auto"] for lv in degrades):
            started = time.perf_counter()
            pages, meta = lsp.extract_pdf_pages(pdfs[level], ocr_backend=backend)
            seconds = time.perf_counter() - started
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
                "engine": backend, "degrade": level,
                "backend_used": sorted({r["backend"] for r in rows if r["backend"]}),
                "seconds_per_page": round(seconds / max(1, len(pages)), 2),
                "document_type": meta.get("document_type"),
                "cer": round(sum(r["cer"] * r["truth_chars"] for r in rows) / chars, 4),
                "verbatim_survival": round(sum(r["sentences_verbatim"] for r in rows) / sentences, 4) if sentences else None,
                "mean_confidence": stats["mean_confidence"], "suspect_lines": stats["suspect_lines"],
                "ocr_ok_pages": stats["ocr_ok"], "pages": len(pages),
                "gate_flags": gate.get("flags", []), "gate_reasons": gate.get("reasons", []),
                "page_rows": rows,
            })
    return {"schema": "ocr-calibration-v1", "font": str(font) if font else None, "dpi": dpi,
            "low_confidence_threshold": clean_corpus.THRESHOLDS["ocr_low_confidence"], "levels": levels}


def parse_pages(spec: str | None, count: int) -> list[int]:
    """「1-3,10」→ [1, 2, 3, 10]（从 1 起算，越界的丢掉）；不给就是全部页。"""
    if not spec:
        return list(range(1, count + 1))
    wanted: set[int] = set()
    for part in (p.strip() for p in spec.split(",")):
        if not part:
            continue
        low, _, high = part.partition("-")
        wanted.update(range(int(low), int(high or low) + 1))
    return sorted(n for n in wanted if 1 <= n <= count)


def scan(pdf: Path, backend: str = "auto", pages_spec: str | None = None, out_dir: Path | None = None) -> dict[str, Any]:
    import fitz  # type: ignore  # OCR 本身就要 PyMuPDF 渲染页面

    with fitz.open(pdf) as src, tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        selected = parse_pages(pages_spec, len(src))
        target = pdf
        if len(selected) < len(src):  # 只抽几页：拷进临时 PDF，走的仍是 index 的同一条路径
            target = Path(td) / "selected.pdf"
            with fitz.open() as part:
                for number in selected:
                    part.insert_pdf(src, from_page=number - 1, to_page=number - 1)
                part.save(target)
        pages, meta = lsp.extract_pdf_pages(target, ocr_backend=backend)
        for page, number in zip(pages, selected):
            page["page_number"] = number
        if out_dir:
            out_dir.mkdir(parents=True, exist_ok=True)
            for page in pages:
                stem = out_dir / f"p{page['page_number']:04d}"
                stem.with_suffix(".png").write_bytes(pdf_quality._to_image_bytes(src[page["page_number"] - 1]))
                stem.with_suffix(".txt").write_text((page.get("ocr") or {}).get("text", ""), encoding="utf-8")
    stats = _ocr_stats(pages)
    _, gate = clean_corpus.clean_pdf_pages([p.get("text", "") for p in pages], stats)
    rows = [{
        "page": p["page_number"], "classification": p.get("quality", {}).get("classification"),
        "ocr_status": (p.get("ocr") or {}).get("status"), "backend": (p.get("ocr") or {}).get("backend"),
        "confidence": (p.get("ocr") or {}).get("confidence"), "chars": len(_squash(p.get("text", ""))),
        "preview": _squash((p.get("ocr") or {}).get("text", ""))[:24],
        "layout": (p.get("ocr") or {}).get("layout"),
        "suspect_lines": int((p.get("ocr") or {}).get("dropped_lines") or 0)
        + int((p.get("ocr") or {}).get("short_lines") or 0),
    } for p in pages]
    return {"schema": "ocr-scan-v1", "file": str(pdf), "document_type": meta.get("document_type"),
            "pages_in_file": meta.get("page_count"), "out_dir": str(out_dir) if out_dir else None,
            **stats, "gate_flags": gate.get("flags", []), "gate_reasons": gate.get("reasons", []), "pages": rows}


def render_calibration(report: dict[str, Any]) -> str:
    lines = [f"## OCR 校准（字体 {report['font'] or 'PIL 内置'}，{report['dpi']} dpi）", "",
             "| 引擎 | 退化档 | CER | 逐字存活率 | 平均置信度 | 可疑行 | OCR 成功页 | 秒/页 | 清洗闸门 |",
             "|---|---|---|---|---|---|---|---|---|"]
    for lv in report["levels"]:
        gate = "、".join(lv["gate_reasons"] + lv["gate_flags"]) or "通过"
        survival = "—" if lv["verbatim_survival"] is None else f"{lv['verbatim_survival']:.0%}"
        conf = "—" if lv["mean_confidence"] is None else f"{lv['mean_confidence']:.3f}"
        engine = "/".join(lv.get("backend_used") or []) or lv.get("engine", "auto")
        lines.append(f"| {engine} | {lv['degrade']} | {lv['cer']:.2%} | {survival} | {conf} "
                     f"| {lv.get('suspect_lines', '—')} | {lv['ocr_ok_pages']}/{lv['pages']} "
                     f"| {lv.get('seconds_per_page', '—')} | {gate} |")
    lines += ["", f"清洗闸门的低置信阈值：{report['low_confidence_threshold']}。逐字存活率低于 100% 的档位，"
              "其引文必须对照原图核实，不能直接当 high 证据。"]
    lost = [("/".join(lv.get("backend_used") or []) or lv.get("engine", "auto"), lv["degrade"], s)
            for lv in report["levels"] for r in lv["page_rows"] for s in r["lost_sentences"]]
    if lost:
        lines += ["", "逐字丢失的句子（前 10 条）："] + [f"- [{e} · {d}] {s}" for e, d, s in lost[:10]]
    return "\n".join(lines) + "\n"


def render_scan(report: dict[str, Any]) -> str:
    lines = [f"## 扫描件诊断：{report['file']}", "",
             f"类型 {report['document_type']}；需 OCR {report['ocr_required']} 页，成功 {report['ocr_ok']} 页，"
             f"平均置信度 {report['mean_confidence']}；竖排 {report.get('vertical_pages', 0)} 页，"
             f"可疑行 {report.get('suspect_lines', 0)}（检测到却没认全的行）；清洗闸门："
             + ("、".join(report["gate_reasons"] + report["gate_flags"]) or "通过"), "",
             "| 页 | 分类 | OCR | 引擎 | 版式 | 置信度 | 可疑行 | 字数 | 识别开头 |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in report["pages"]:
        layout = {"vertical": "竖排", "horizontal": "横排"}.get(r.get("layout") or "", "—")
        lines.append(f"| {r['page']} | {r['classification']} | {r['ocr_status'] or '—'} | {r['backend'] or '—'} "
                     f"| {layout} | {r['confidence'] if r['confidence'] is not None else '—'} "
                     f"| {r.get('suspect_lines') or 0} | {r['chars']} "
                     f"| {r.get('preview') or '—'} |")
    if report.get("out_dir"):
        lines += ["", f"每页送进 OCR 的图与识别文字已成对存到 {report['out_dir']}（pNNNN.png / pNNNN.txt），"
                  "对照原图核实后再给引文标 high。"]
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
    p.add_argument("--backend", default="auto", help="auto（与 index 相同）、all（每个装好的引擎各跑一遍）或引擎名")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("scan", help="逐页报告真实扫描件的分类、OCR 状态与置信度")
    p.add_argument("pdf", type=Path)
    p.add_argument("--pages", help="只看这些页，如 1-3,40（从 1 起算）")
    p.add_argument("--out", type=Path, help="把每页的图与 OCR 文字成对存到这个目录，供人对照核实")
    p.add_argument("--backend", default="auto", help="auto 或引擎名")
    p.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    available = engine_available()
    if not available:
        print(f"没有可用的 OCR 引擎：pip install -e .[ocr]（rapidocr + onnxruntime），或把环境变量 "
              f"{pdf_quality.PADDLEOCR_JSON_ENV} 指向 PaddleOCR-json.exe（Umi-OCR 的 PaddleOCR-json 插件目录即可）。",
              file=sys.stderr)
        return 2
    if args.backend not in ("auto", "all") and args.backend not in available:
        print(f"引擎 {args.backend} 不可用；可用：{', '.join(available)}", file=sys.stderr)
        return 2
    if args.action == "scan":
        report = scan(args.pdf, "auto" if args.backend == "all" else args.backend, args.pages, args.out)
        print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else render_scan(report), end="\n" if args.json else "")
        return 0
    font = find_cjk_font(args.font)
    if font is None:
        print("找不到 CJK 字体：用 --font 指定一个能显示中文的字体文件。", file=sys.stderr)
        return 2
    levels = list(DEGRADE) if args.degrade == "all" else [args.degrade]
    backends = available if args.backend == "all" else [args.backend]
    report = calibrate(load_truth(args.truth), font=font, degrades=levels, dpi=args.dpi, backends=backends)
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else render_calibration(report), end="\n" if args.json else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
