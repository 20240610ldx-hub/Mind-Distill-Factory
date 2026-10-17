#!/usr/bin/env python3
"""PDF page classification, quality gates, and optional OCR adapters.

The module is dependency-light by design. PyMuPDF is used by the source
indexer when available; OCR engines are imported only for pages that need OCR.
"""

from __future__ import annotations

import atexit
import base64
import hashlib
import json
import os
import re
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


PDF_TYPES = {
    "pure_image_pdf",
    "mixed_text_image_pdf",
    "pure_text_pdf",
    "empty_or_unreadable_pdf",
}


@dataclass(frozen=True)
class PageQuality:
    page_number: int
    text_chars: int
    non_ws_chars: int
    replacement_chars: int
    image_count: int
    substantive_image_count: int
    image_area_ratio: float
    quality_score: float
    classification: str
    ocr_required: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "page_number": self.page_number,
            "text_chars": self.text_chars,
            "non_ws_chars": self.non_ws_chars,
            "replacement_chars": self.replacement_chars,
            "image_count": self.image_count,
            "substantive_image_count": self.substantive_image_count,
            "image_area_ratio": round(self.image_area_ratio, 4),
            "quality_score": round(self.quality_score, 4),
            "classification": self.classification,
            "ocr_required": self.ocr_required,
        }


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def text_quality_score(text: str) -> float:
    """Return a conservative 0..1 score for extracted page text."""
    if not text or not text.strip():
        return 0.0
    non_ws = sum(1 for ch in text if not ch.isspace())
    if not non_ws:
        return 0.0
    replacement = text.count("�")
    controls = sum(1 for ch in text if ord(ch) < 32 and ch not in "\n\r\t")
    score = 0.65
    if non_ws >= 80:
        score += 0.2
    elif non_ws < 20:
        score -= 0.25
    score -= min(0.25, replacement / max(1, non_ws) * 2)
    score -= min(0.15, controls / max(1, non_ws) * 2)
    return max(0.0, min(1.0, score))


def _image_area(info: dict[str, Any], page_area: float) -> tuple[float, int]:
    rect = info.get("bbox") or info.get("rect")
    area = 0.0
    if rect is not None:
        try:
            width = max(0.0, float(rect[2]) - float(rect[0]))
            height = max(0.0, float(rect[3]) - float(rect[1]))
            area = width * height
        except (TypeError, ValueError, IndexError):
            area = 0.0
    width = int(info.get("width") or 0)
    height = int(info.get("height") or 0)
    pixels = width * height
    ratio = area / page_area if page_area > 0 else 0.0
    return ratio, pixels


def classify_page(
    page_number: int,
    text: str,
    image_infos: list[dict[str, Any]] | None = None,
    page_area: float = 0.0,
    *,
    substantive_area_ratio: float = 0.08,
    substantive_pixels: int = 80_000,
) -> PageQuality:
    """Classify a page as text, mixed, or image-only.

    An image is considered substantive when it occupies meaningful page area
    or has enough pixels to contain a scanned passage/diagram. This deliberately
    errs toward OCR review for information-rich images; the OCR result still
    needs its own quality status before it can become high-confidence evidence.
    """
    infos = image_infos or []
    ratios: list[float] = []
    substantive = 0
    for info in infos:
        ratio, pixels = _image_area(info, page_area)
        ratios.append(ratio)
        if ratio >= substantive_area_ratio or pixels >= substantive_pixels:
            substantive += 1
    image_ratio = min(1.0, sum(ratios)) if ratios else 0.0
    non_ws = sum(1 for ch in text if not ch.isspace())
    replacement = text.count("�")
    text_score = text_quality_score(text)
    has_text = non_ws >= 20 and text_score >= 0.25
    has_substantive_image = substantive > 0

    if has_substantive_image and not has_text:
        classification = "image_only"
    elif has_substantive_image and has_text:
        classification = "mixed"
    elif has_text:
        classification = "text_only"
    else:
        classification = "empty"

    ocr_required = has_substantive_image and classification in {"image_only", "mixed"}
    if classification == "text_only" and replacement > 0:
        ocr_required = True

    return PageQuality(
        page_number=page_number,
        text_chars=len(text),
        non_ws_chars=non_ws,
        replacement_chars=replacement,
        image_count=len(infos),
        substantive_image_count=substantive,
        image_area_ratio=image_ratio,
        quality_score=text_score,
        classification=classification,
        ocr_required=ocr_required,
    )


def quality_band(score: float) -> str:
    if score >= 0.75:
        return "good"
    if score >= 0.45:
        return "review"
    if score > 0:
        return "poor"
    return "unreadable"


def classify_document(page_qualities: list[PageQuality]) -> str:
    if not page_qualities or all(p.classification == "empty" for p in page_qualities):
        return "empty_or_unreadable_pdf"
    if all(p.classification == "image_only" for p in page_qualities if p.classification != "empty"):
        return "pure_image_pdf"
    if any(p.classification == "mixed" for p in page_qualities):
        return "mixed_text_image_pdf"
    if any(p.classification == "image_only" for p in page_qualities):
        return "mixed_text_image_pdf"
    return "pure_text_pdf"


def _to_image_bytes(page: Any, dpi: int = 150) -> bytes:
    matrix = page.get_pixmap(matrix=__import__("fitz").Matrix(dpi / 72, dpi / 72), alpha=False)
    return matrix.tobytes("png")


def _mean(scores: list[float]) -> float:
    return sum(scores) / len(scores) if scores else 0.0


def _rapidocr_runner() -> Callable[[bytes], tuple[str, float]]:
    try:  # rapidocr ≥3（支持 Python 3.13）：返回 RapidOCROutput，文本与分数在 txts / scores
        from rapidocr import RapidOCR as RapidOCRv3  # type: ignore
    except ImportError:
        return _rapidocr_legacy_runner()
    engine_v3 = RapidOCRv3(params={"Global.log_level": "warning"})

    def run_v3(image: bytes) -> tuple[str, float]:
        out = engine_v3(image)
        texts = [str(t) for t in (getattr(out, "txts", None) or ())]
        scores = [float(s) for s in (getattr(out, "scores", None) or ())]
        return "\n".join(texts).strip(), _mean(scores)

    return run_v3


def _rapidocr_legacy_runner() -> Callable[[bytes], tuple[str, float]]:
    from rapidocr_onnxruntime import RapidOCR  # type: ignore  # 旧包，只支持 Python <3.13

    engine = RapidOCR()

    def run(image: bytes) -> tuple[str, float]:
        result, _elapsed = engine(image)
        if not result:
            return "", 0.0
        lines: list[str] = []
        scores: list[float] = []
        for item in result:
            if len(item) >= 3:
                lines.append(str(item[1]))
                try:
                    scores.append(float(item[2]))
                except (TypeError, ValueError):
                    pass
        return "\n".join(lines).strip(), _mean(scores)

    return run


PADDLEOCR_JSON_ENV = "MDF_PADDLEOCR_JSON"
PADDLEOCR_JSON_ARGS_ENV = "MDF_PADDLEOCR_JSON_ARGS"
PADDLEOCR_JSON_NAMES = ("PaddleOCR-json.exe", "PaddleOCR-json", "run.sh")


def paddleocr_json_exe() -> Path | None:
    """MDF_PADDLEOCR_JSON 指向 PaddleOCR-json 可执行文件或它所在的文件夹（Umi-OCR 的
    UmiOCR-data/plugins/win7_x64_PaddleOCR-json 就是）。不扫磁盘，不猜路径。"""
    raw = os.environ.get(PADDLEOCR_JSON_ENV, "").strip().strip('"')
    if not raw:
        return None
    path = Path(raw)
    if path.is_dir():
        return next((path / n for n in PADDLEOCR_JSON_NAMES if (path / n).is_file()), None)
    return path if path.is_file() else None


class PaddleOcrJsonPipe:
    """PaddleOCR-json 的管道协议：常驻子进程，stdin 每行一个请求 JSON，stdout 每行一个结果 JSON。
    code 100 = 有文字，101 = 图中没字，其余是错误。"""

    INIT_MARK = b"OCR init completed."

    def __init__(self, cmd: list[str], cwd: Path | None = None, init_timeout: float = 120.0):
        self.proc = subprocess.Popen(
            cmd, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        atexit.register(self.close)
        ready: dict[str, bool] = {}

        def wait_ready() -> None:
            for line in iter(self.proc.stdout.readline, b""):
                if self.INIT_MARK in line:
                    ready["ok"] = True
                    return

        waiter = threading.Thread(target=wait_ready, daemon=True)
        waiter.start()
        waiter.join(init_timeout)
        if not ready:
            self.close()
            raise RuntimeError(f"PaddleOCR-json did not finish init within {init_timeout:.0f}s")

    def __call__(self, image: bytes) -> tuple[str, float]:
        if self.proc.poll() is not None:
            raise RuntimeError(f"PaddleOCR-json exited (code {self.proc.returncode})")
        request = json.dumps({"image_base64": base64.b64encode(image).decode("ascii")})
        self.proc.stdin.write(request.encode("ascii") + b"\n")
        self.proc.stdin.flush()
        reply = json.loads(self.proc.stdout.readline().decode("utf-8", errors="replace") or "{}")
        code = reply.get("code")
        if code == 101:
            return "", 0.0
        if code != 100:
            raise RuntimeError(f"PaddleOCR-json code {code}: {reply.get('data')}")
        items = [d for d in reply.get("data") or [] if isinstance(d, dict)]
        texts = [str(d.get("text", "")) for d in items]
        scores = [float(d["score"]) for d in items if isinstance(d.get("score"), (int, float))]
        return "\n".join(texts).strip(), _mean(scores)

    def close(self) -> None:
        if self.proc.poll() is None:
            try:
                self.proc.kill()
            except OSError:
                pass
        try:  # 等进程真正退出：Windows 上它还占着 cwd，调用方删不掉目录
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        for stream in (self.proc.stdin, self.proc.stdout):
            try:
                stream.close()
            except (OSError, AttributeError):
                pass


def _paddleocr_json_runner() -> Callable[[bytes], tuple[str, float]]:
    exe = paddleocr_json_exe()
    if exe is None:
        raise ImportError(f"set {PADDLEOCR_JSON_ENV} to PaddleOCR-json.exe or its folder")
    # 额外启动参数用空格分隔，例如 --config_path=models/config_chinese_cht.txt --limit_side_len=2880
    args = os.environ.get(PADDLEOCR_JSON_ARGS_ENV, "").split()
    return PaddleOcrJsonPipe([str(exe), *args], cwd=exe.parent)


def _paddleocr_runner() -> Callable[[bytes], tuple[str, float]]:
    from paddleocr import PaddleOCR  # type: ignore

    try:
        engine = PaddleOCR(
            lang="ch",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )
    except TypeError:
        engine = PaddleOCR(lang="ch", use_angle_cls=False, show_log=False)

    def run(image: bytes) -> tuple[str, float]:
        result = engine.predict(image) if hasattr(engine, "predict") else engine.ocr(image, cls=False)
        lines: list[str] = []
        scores: list[float] = []
        for page_result in result or []:
            if isinstance(page_result, dict):
                texts = page_result.get("rec_texts") or []
                scores.extend(float(v) for v in (page_result.get("rec_scores") or []) if isinstance(v, (int, float)))
                lines.extend(str(v) for v in texts)
                continue
            for line in page_result or []:
                if len(line) >= 2 and isinstance(line[1], (list, tuple)):
                    lines.append(str(line[1][0]))
                    if len(line[1]) > 1:
                        try:
                            scores.append(float(line[1][1]))
                        except (TypeError, ValueError):
                            pass
        return "\n".join(lines).strip(), _mean(scores)

    return run


RUNNER_FACTORIES: dict[str, Callable[[], Callable[[bytes], tuple[str, float]]]] = {
    "rapidocr": _rapidocr_runner,
    "paddleocr_json": _paddleocr_json_runner,
    "paddleocr": _paddleocr_runner,
}
OCR_BACKEND_ENV = "MDF_OCR_BACKEND"
# 引擎加载很慢（ONNX / Paddle 模型），每个进程每个引擎只建一次——过去每页都新建一次，
# 600 页的扫描件要加载 600 次模型。缺依赖（ImportError）不缓存，装上后同一进程可重试。
_RUNNERS: dict[str, Callable[[bytes], tuple[str, float]]] = {}
_INJECTED: list[str] = []


def get_runner(name: str) -> Callable[[bytes], tuple[str, float]]:
    if name not in _RUNNERS:
        if name not in RUNNER_FACTORIES:
            raise ImportError(f"unknown OCR backend {name!r}")
        _RUNNERS[name] = RUNNER_FACTORIES[name]()
    return _RUNNERS[name]


def register_runner(name: str, runner: Callable[[bytes], tuple[str, float]]) -> None:
    """注入一个引擎并让 auto 优先用它（OCR 校准与测试用）。"""
    _RUNNERS[name] = runner
    if name not in _INJECTED:
        _INJECTED.insert(0, name)


def clear_injected_runners() -> None:
    for name in _INJECTED:
        _RUNNERS.pop(name, None)
    _INJECTED.clear()


def ocr_candidates(backend: str = "auto") -> list[str]:
    """auto 时按 RUNNER_FACTORIES 顺序取第一个出字的引擎；MDF_OCR_BACKEND 可把 auto 钉在一个引擎上
    （注入的测试引擎仍排最前）。显式指定的 backend 只用它自己。"""
    if backend != "auto":
        return [backend]
    pinned = os.environ.get(OCR_BACKEND_ENV, "").strip()
    return [*_INJECTED, *([pinned] if pinned and pinned != "auto" else RUNNER_FACTORIES)]


def run_ocr(page: Any, backend: str = "auto", *, dpi: int = 150) -> dict[str, Any]:
    """OCR one page, returning an explicit unavailable/error status."""
    if backend == "off":
        return {"status": "disabled", "backend": None, "text": "", "confidence": 0.0}
    candidates = ocr_candidates(backend)
    errors: list[str] = []
    try:
        image = _to_image_bytes(page, dpi=dpi)
    except Exception as exc:
        return {"status": "render_error", "backend": None, "text": "", "confidence": 0.0, "error": str(exc)}
    for candidate in candidates:
        try:
            runner = get_runner(candidate)
            text, confidence = runner(image)
            if text:
                return {
                    "status": "ok",
                    "backend": candidate,
                    "text": text,
                    "confidence": round(confidence, 4),
                }
            errors.append(f"{candidate}:empty")
        except ImportError:
            errors.append(f"{candidate}:not_installed")
        except Exception as exc:  # pragma: no cover - engine/runtime dependent
            errors.append(f"{candidate}:{exc}")
    return {
        "status": "unavailable",
        "backend": None,
        "text": "",
        "confidence": 0.0,
        "errors": errors,
    }
