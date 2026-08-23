#!/usr/bin/env python3
"""Build TXT companions for Lu Xun local source PDFs.

The script prefers clean public-domain HTML text for Lu Xun works and uses OCR
only for local scans that do not have a reliable text source.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import html as html_lib
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import fitz  # type: ignore
import requests
from lxml import html  # type: ignore
from PIL import Image, ImageOps  # type: ignore
import pytesseract  # type: ignore


if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "sources" / "lu-xun" / "raw"
PROCESSED_DIR = ROOT / "sources" / "lu-xun" / "processed"
MANIFEST_PATH = PROCESSED_DIR / "txt_conversion_manifest.json"
LOG_PATH = PROCESSED_DIR / "txt_conversion.log"
TESSDATA_DIR = ROOT / "tools" / "tessdata"

HEADERS = {
    "User-Agent": "MindDistillFactorySourceConverter/1.0 (local user-requested conversion)",
    "Accept": "text/html,application/xhtml+xml,application/xml,application/json;q=0.9,*/*;q=0.8",
}


def u(text: str) -> str:
    return text.encode("ascii").decode("unicode_escape")


MARXISTS_BASE = "https://www.marxists.org/chinese/reference-books/luxun/"

MARXISTS_COLLECTIONS = [
    {
        "pdf": u("\\u71b1\\u98a8.pdf"),
        "title": u("\\u70ed\\u98ce"),
        "index": "02/index.htm",
    },
    {
        "pdf": u("\\u83ef\\u84cb\\u96c6.pdf"),
        "title": u("\\u534e\\u76d6\\u96c6"),
        "index": "08/index.htm",
    },
    {
        "pdf": u("\\u4e09\\u9592\\u96c6.pdf"),
        "title": u("\\u4e09\\u95f2\\u96c6"),
        "index": "12/index.htm",
    },
    {
        "pdf": u("\\u4e14\\u4ecb\\u4ead\\u96dc\\u6587.pdf"),
        "title": u("\\u4e14\\u4ecb\\u4ead\\u6742\\u6587"),
        "index": "18/index.htm",
    },
    {
        "pdf": u("\\u5357\\u8154\\u5317\\u8abf\\u96c6.pdf"),
        "title": u("\\u5357\\u8154\\u5317\\u8c03\\u96c6"),
        "index": "14/index.htm",
    },
    {
        "pdf": u("\\u507d\\u81ea\\u7531\\u66f8.pdf"),
        "title": u("\\u4f2a\\u81ea\\u7531\\u4e66"),
        "index": "15/index.htm",
    },
    {
        "pdf": u("\\u5436\\u558a.pdf"),
        "title": u("\\u5450\\u558a"),
        "index": "03/index.htm",
    },
    {
        "pdf": u("\\u5f77\\u5fa8.pdf"),
        "title": u("\\u5f77\\u5fa8"),
        "index": "04/index.htm",
    },
    {
        "pdf": u("\\u91ce\\u8349_\\u9b6f\\u8fc5\\u6563\\u6587\\u96c6.pdf"),
        "title": u("\\u91ce\\u8349"),
        "index": "05/index.htm",
    },
]

WIKISOURCE_SINGLE_PAGES = [
    {
        "pdf": "NLC416-01jh009292-71647_" + u("\\u56de\\u61b6\\u9b6f\\u8fc5\\u5148\\u751f.pdf"),
        "title": u("\\u56de\\u5fc6\\u9c81\\u8fc5\\u5148\\u751f"),
        "url": "https://zh.wikisource.org/zh-hans/%E5%9B%9E%E6%86%B6%E9%AD%AF%E8%BF%85%E5%85%88%E7%94%9F",
    },
]

ZAGAN_SELECTION = {
    "pdf": u("\\u9b6f\\u8fc5\\u96dc\\u611f\\u9078\\u96c6.pdf"),
    "title": u("\\u9c81\\u8fc5\\u6742\\u611f\\u9009\\u96c6"),
    "source_url": "https://commons.wikimedia.org/wiki/File:NLC416-13jh001554-42380_%E9%AD%AF%E8%BF%85%E9%9B%9C%E6%84%9F%E9%81%B8%E9%9B%86.pdf",
    "paths": [
        "02/001.htm", "02/006.htm", "02/007.htm", "02/018.htm", "02/019.htm", "02/025.htm",
        "02/028.htm", "02/029.htm", "02/034.htm",
        "01/014.htm", "01/020.htm", "01/015.htm", "01/013.htm", "01/024.htm", "01/017.htm",
        "01/022.htm", "01/008.htm", "01/021.htm", "01/019.htm",
        "08/003.htm", "08/004.htm", "08/006.htm", "08/009.htm", "08/010.htm", "08/012.htm",
        "08/020.htm", "08/024.htm", "08/025.htm", "08/027.htm", "08/030.htm",
        "09/004.htm", "09/005.htm", "09/006.htm", "09/009.htm", "09/010.htm", "09/011.htm",
        "09/012.htm", "09/015.htm", "09/016.htm", "09/023.htm", "09/026.htm",
        "11/003.htm", "11/004.htm", "11/009.htm", "11/021.htm", "11/027.htm", "11/014.htm",
        "11/023.htm", "11/030.htm", "11/026.htm", "11/015.htm", "11/017.htm", "11/022.htm",
        "11/016.htm",
        "12/031.htm", "12/033.htm", "12/030.htm", "12/014.htm", "12/013.htm", "12/020.htm",
        "12/016.htm", "12/025.htm", "12/029.htm", "12/009.htm", "12/027.htm",
        "13/017.htm", "13/016.htm", "13/004.htm", "13/037.htm", "13/022.htm", "13/025.htm",
        "13/003.htm", "13/038.htm", "13/006.htm", "13/001.htm",
    ],
}

LUXUNLIB_LETTERS = {
    "pdf": u("\\u9b6f\\u8fc5\\u624b\\u7a3f\\u5168\\u96c6_\\u66f8\\u4fe1_\\u7b2c1\\u518a.pdf"),
    "title": u("\\u9c81\\u8fc5\\u4e66\\u4fe1\\u5168\\u96c6"),
    "api": "https://luxunlib.com/wp-json/wp/v2/fcn_chapter",
    "category": 5561,
}

OCR_SOURCES = [
    {
        "pdf": u("\\u65e0\\u6cd5\\u76f4\\u9762\\u7684\\u4eba\\u751f.pdf"),
        "title": u("\\u65e0\\u6cd5\\u76f4\\u9762\\u7684\\u4eba\\u751f"),
        "orientation": "horizontal",
        "scale": 3.0,
    },
    {
        "pdf": u("\\u9c81\\u8fc5\\u6279\\u5224 (\\u674e\\u957f\\u4e4b) .pdf"),
        "title": u("\\u9c81\\u8fc5\\u6279\\u5224"),
        "orientation": "horizontal",
        "scale": 3.0,
    },
    {
        "pdf": u("\\u9c81\\u8fc5\\u5165\\u95e8\\u8bfb\\u672c.pdf"),
        "title": u("\\u9c81\\u8fc5\\u5165\\u95e8\\u8bfb\\u672c"),
        "orientation": "vertical",
        "scale": 3.0,
    },
]


@dataclass
class ConversionResult:
    title: str
    source_file: str
    output_file: str
    method: str
    char_count: int
    page_count: int | None = None
    section_count: int | None = None
    source_url: str | None = None
    status: str = "ok"
    warning: str = ""


def log(message: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    print(line, flush=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def output_path_for_pdf(pdf_name: str) -> Path:
    return (RAW_DIR / pdf_name).with_suffix(".txt")


def request_text(url: str, *, encoding: str | None = None, retries: int = 4, sleep: float = 1.0) -> str:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            response = requests.get(url, headers=HEADERS, timeout=60)
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", "5"))
                time.sleep(retry_after)
                continue
            if 400 <= response.status_code < 500:
                response.raise_for_status()
            response.raise_for_status()
            if encoding:
                return response.content.decode(encoding, errors="replace")
            if response.encoding:
                response.encoding = response.encoding
            return response.text
        except Exception as exc:  # pragma: no cover - operational retry path
            last_error = exc
            time.sleep(sleep * attempt)
    raise RuntimeError(f"Failed to fetch {url}: {last_error}")


def normalize_downloaded_text(text: str) -> str:
    text = html_lib.unescape(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    paragraphs: list[str] = []
    current: list[str] = []
    for line in lines:
        if not line:
            if current:
                paragraphs.append("".join(current).strip())
                current = []
            continue
        current.append(line)
    if current:
        paragraphs.append("".join(current).strip())
    return "\n\n".join(p for p in paragraphs if p)


def clean_ocr_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)
    text = re.sub(r"\s+([，。！？；：、」』）】》])", r"\1", text)
    text = re.sub(r"([「『（【《])\s+", r"\1", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def write_txt(path: Path, title: str, method: str, body: str, source_url: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = [
        f"# {title}",
        "",
        f"conversion_method: {method}",
        f"converted_at: {datetime.now(timezone.utc).isoformat()}",
    ]
    if source_url:
        header.append(f"source_url: {source_url}")
    header.extend(["", "---", ""])
    path.write_text("\n".join(header) + body.strip() + "\n", encoding="utf-8")


def marxists_links(index_url: str) -> list[tuple[str, str]]:
    try:
        text = request_text(index_url, encoding="gb18030")
    except RuntimeError:
        start_url = index_url.rsplit("/", 1)[0] + "/000.htm"
        return marxists_listing_or_follow(start_url)
    root = html.fromstring(text)
    links: list[tuple[str, str]] = []
    seen: set[str] = set()
    for a in root.xpath("//a[@href]"):
        href = a.get("href") or ""
        label = " ".join("".join(a.itertext()).split())
        if not label:
            continue
        target = urljoin(index_url, href)
        if not re.search(r"/\d{2}/\d{3}\.htm$", target):
            continue
        if target in seen:
            continue
        seen.add(target)
        links.append((label, target))
    links.sort(key=lambda item: item[1])
    if not links:
        start_url = index_url.rsplit("/", 1)[0] + "/000.htm"
        return marxists_listing_or_follow(start_url)
    if len(links) == 1 and links[0][1].endswith("/000.htm") and links[0][1] != index_url:
        expanded = marxists_listing_or_follow(links[0][1])
        if len(expanded) > 1:
            return expanded
    return links


def marxists_listing_or_follow(start_url: str) -> list[tuple[str, str]]:
    text = request_text(start_url, encoding="gb18030")
    root = html.fromstring(text)
    links: list[tuple[str, str]] = []
    seen: set[str] = set()
    for a in root.xpath("//a[@href]"):
        href = a.get("href") or ""
        label = " ".join("".join(a.itertext()).split())
        target = urljoin(start_url, href)
        if not label or not re.search(r"/\d{2}/\d{3}\.htm$", target):
            continue
        if target in seen:
            continue
        seen.add(target)
        links.append((label, target))
    links.sort(key=lambda item: item[1])
    if len(links) > 1:
        return links
    return marxists_follow_next_links(start_url)


def marxists_follow_next_links(start_url: str) -> list[tuple[str, str]]:
    links: list[tuple[str, str]] = []
    seen: set[str] = set()
    current = start_url
    while current and current not in seen:
        seen.add(current)
        text = request_text(current, encoding="gb18030")
        root = html.fromstring(text)
        title = " ".join(root.xpath("string(//title)").split()) or current.rsplit("/", 1)[-1]
        links.append((title, current))
        next_url = ""
        for a in root.xpath("//a[@href]"):
            label = " ".join("".join(a.itertext()).split())
            href = a.get("href") or ""
            candidate = urljoin(current, href)
            if label == u("\\u4e0b\\u4e00\\u7bc7") and re.search(r"/\d{2}/\d{3}\.htm$", candidate):
                next_url = candidate
                break
        current = next_url
        time.sleep(0.05)
    return links


def marxists_article_text(url: str) -> tuple[str, str]:
    text = request_text(url, encoding="gb18030")
    root = html.fromstring(text)
    title = " ".join(root.xpath("string(//title)").split()) or url.rsplit("/", 1)[-1]
    paragraphs = [
        normalize_downloaded_text("".join(p.itertext()))
        for p in root.xpath("//p")
    ]
    paragraphs = [p for p in paragraphs if p and not is_nav_text(p)]
    if not paragraphs:
        body = normalize_downloaded_text(root.xpath("string(//body)"))
    else:
        body = "\n\n".join(paragraphs)
    return title, body


def is_nav_text(text: str) -> bool:
    nav_terms = [
        u("\\u4e0a\\u4e00\\u7bc7"),
        u("\\u4e0b\\u4e00\\u7bc7"),
        u("\\u56de\\u4e3b\\u9875"),
        u("\\u4e2d\\u6587\\u9a6c\\u514b\\u601d\\u4e3b\\u4e49\\u6587\\u5e93"),
    ]
    return any(term in text for term in nav_terms) and len(text) < 120


def convert_marxists_collection(item: dict[str, str]) -> ConversionResult:
    pdf_name = item["pdf"]
    title = item["title"]
    index_url = urljoin(MARXISTS_BASE, item["index"])
    out_path = output_path_for_pdf(pdf_name)
    log(f"download {title}: index {index_url}")
    sections = []
    for label, article_url in marxists_links(index_url):
        article_title, body = marxists_article_text(article_url)
        if not body:
            continue
        sections.append(f"## {article_title}\nsource_url: {article_url}\n\n{body}")
        time.sleep(0.08)
    body = "\n\n".join(sections)
    write_txt(out_path, title, "public_html_marxists", body, index_url)
    return ConversionResult(
        title=title,
        source_file=pdf_name,
        output_file=str(out_path),
        method="public_html_marxists",
        char_count=len(body),
        section_count=len(sections),
        source_url=index_url,
    )


def convert_wikisource_page(item: dict[str, str]) -> ConversionResult:
    pdf_name = item["pdf"]
    title = item["title"]
    url = item["url"]
    out_path = output_path_for_pdf(pdf_name)
    log(f"download {title}: {url}")
    text = request_text(url, encoding="utf-8")
    root = html.fromstring(text)
    for el in root.xpath(
        "//table|//style|//script|//sup|//*[contains(@class,'mw-editsection')]|"
        "//*[contains(@class,'metadata')]|//*[contains(@class,'licenseContainer')]"
    ):
        parent = el.getparent()
        if parent is not None:
            parent.remove(el)
    nodes = root.xpath("//div[contains(@class,'mw-parser-output')]")
    if not nodes:
        raise RuntimeError(f"Could not find Wikisource content: {url}")
    paragraphs = [
        normalize_downloaded_text("".join(p.itertext()))
        for p in nodes[0].xpath(".//p")
    ]
    body = "\n\n".join(p for p in paragraphs if p)
    write_txt(out_path, title, "public_html_wikisource", body, url)
    return ConversionResult(
        title=title,
        source_file=pdf_name,
        output_file=str(out_path),
        method="public_html_wikisource",
        char_count=len(body),
        section_count=len(paragraphs),
        source_url=url,
    )


def convert_zagan_selection() -> ConversionResult:
    item = ZAGAN_SELECTION
    title = item["title"]
    pdf_name = item["pdf"]
    out_path = output_path_for_pdf(pdf_name)
    log(f"assemble {title}: {len(item['paths'])} selected articles")
    sections = []
    for path in item["paths"]:
        article_url = urljoin(MARXISTS_BASE, path)
        article_title, body = marxists_article_text(article_url)
        if body:
            sections.append(f"## {article_title}\nsource_url: {article_url}\n\n{body}")
        time.sleep(0.08)
    body = "\n\n".join(sections)
    write_txt(out_path, title, "public_html_marxists_selection_from_commons_toc", body, item["source_url"])
    return ConversionResult(
        title=title,
        source_file=pdf_name,
        output_file=str(out_path),
        method="public_html_marxists_selection_from_commons_toc",
        char_count=len(body),
        section_count=len(sections),
        source_url=item["source_url"],
        warning="Assembled from Wikimedia Commons table of contents and Marxists Lu Xun text pages.",
    )


def html_to_text(rendered: str) -> str:
    root = html.fragment_fromstring(rendered, create_parent=True)
    paragraphs = []
    for node in root.xpath(".//p|.//li|.//blockquote"):
        value = normalize_downloaded_text("".join(node.itertext()))
        if value:
            paragraphs.append(value)
    if not paragraphs:
        return normalize_downloaded_text("".join(root.itertext()))
    return "\n\n".join(paragraphs)


def convert_luxunlib_letters() -> ConversionResult:
    item = LUXUNLIB_LETTERS
    out_path = output_path_for_pdf(item["pdf"])
    log(f"download {item['title']}: luxunlib category {item['category']}")
    page = 1
    total_pages = None
    chapters: list[dict[str, str]] = []
    while total_pages is None or page <= total_pages:
        params = {
            "categories": str(item["category"]),
            "per_page": "50",
            "page": str(page),
            "_fields": "id,title,content,link,date",
        }
        response = requests.get(item["api"], params=params, headers=HEADERS, timeout=90)
        response.raise_for_status()
        total_pages = int(response.headers.get("X-WP-TotalPages", "1"))
        data = response.json()
        for chapter in data:
            title = html_lib.unescape(chapter.get("title", {}).get("rendered", "")).strip()
            content = html_to_text(chapter.get("content", {}).get("rendered", ""))
            link = chapter.get("link", "")
            if title and content:
                chapters.append({"title": title, "content": content, "link": link})
        log(f"  letters page {page}/{total_pages}: total chapters {len(chapters)}")
        page += 1
        time.sleep(0.2)
    chapters.sort(key=lambda c: c["title"])
    sections = [
        f"## {chapter['title']}\nsource_url: {chapter['link']}\n\n{chapter['content']}"
        for chapter in chapters
    ]
    body = "\n\n".join(sections)
    write_txt(out_path, item["title"], "public_rest_luxunlib", body, "https://luxunlib.com/story/%E4%B9%A6%E4%BF%A1/")
    return ConversionResult(
        title=item["title"],
        source_file=item["pdf"],
        output_file=str(out_path),
        method="public_rest_luxunlib",
        char_count=len(body),
        section_count=len(sections),
        source_url="https://luxunlib.com/story/%E4%B9%A6%E4%BF%A1/",
    )


def ink_crop(image: Image.Image) -> Image.Image:
    gray = image.convert("L")
    import numpy as np

    arr = np.array(gray)
    mask = arr < 225
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return ImageOps.autocontrast(gray)
    margin = 24
    box = (
        max(0, int(xs.min()) - margin),
        max(0, int(ys.min()) - margin),
        min(gray.width, int(xs.max()) + margin),
        min(gray.height, int(ys.max()) + margin),
    )
    return ImageOps.autocontrast(gray.crop(box))


def ocr_page(args: tuple[str, int, float, str, str]) -> tuple[int, str, int]:
    pdf_path, page_index, scale, orientation, tessdata_dir = args
    doc = fitz.open(pdf_path)
    page = doc[page_index]
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csGRAY, alpha=False)
    doc.close()
    image = Image.frombytes("L", [pix.width, pix.height], pix.samples)
    image = ink_crop(image)
    if orientation == "vertical":
        lang = "chi_tra_vert+chi_sim_vert+eng"
        config = f"--tessdata-dir {tessdata_dir} --oem 1 --psm 5"
    else:
        lang = "chi_sim+chi_tra+eng"
        config = "--oem 1 --psm 6"
    text = pytesseract.image_to_string(image, lang=lang, config=config)
    text = clean_ocr_text(text)
    return page_index + 1, text, len(text)


def convert_ocr_pdf(item: dict[str, Any], workers: int, limit_pages: int | None) -> ConversionResult:
    pdf_name = item["pdf"]
    title = item["title"]
    pdf_path = RAW_DIR / pdf_name
    out_path = output_path_for_pdf(pdf_name)
    if item["orientation"] == "vertical" and not (TESSDATA_DIR / "chi_tra_vert.traineddata").exists():
        raise RuntimeError(f"Missing vertical Tesseract data under {TESSDATA_DIR}")
    doc = fitz.open(pdf_path)
    page_count = len(doc)
    doc.close()
    if limit_pages:
        page_count = min(page_count, limit_pages)
    log(f"ocr {title}: {page_count} pages, orientation={item['orientation']}, workers={workers}")
    tasks = [
        (str(pdf_path), idx, float(item.get("scale", 3.0)), item["orientation"], "tools/tessdata")
        for idx in range(page_count)
    ]
    pages: dict[int, str] = {}
    done = 0
    started = time.time()
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
        for page_number, text, char_count in executor.map(ocr_page, tasks, chunksize=1):
            pages[page_number] = text
            done += 1
            if done == 1 or done % 10 == 0 or done == page_count:
                elapsed = max(1.0, time.time() - started)
                rate = done / elapsed
                remaining = int((page_count - done) / rate) if rate else 0
                log(f"  {title}: {done}/{page_count} pages, last={char_count} chars, eta={remaining}s")
    sections = [
        f"--- Page {page_number} ---\n{pages.get(page_number, '').strip()}"
        for page_number in range(1, page_count + 1)
    ]
    body = "\n\n".join(sections)
    write_txt(out_path, title, f"local_pdf_ocr_{item['orientation']}", body, str(pdf_path))
    warning = "OCR output should be spot-checked before using exact quotations."
    return ConversionResult(
        title=title,
        source_file=pdf_name,
        output_file=str(out_path),
        method=f"local_pdf_ocr_{item['orientation']}",
        char_count=len(body),
        page_count=page_count,
        source_url=str(pdf_path),
        warning=warning,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Rebuild existing TXT files.")
    parser.add_argument("--skip-ocr", action="store_true", help="Only fetch clean online text.")
    parser.add_argument("--only-ocr", action="store_true", help="Only run OCR sources.")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit-ocr-pages", type=int, default=None)
    args = parser.parse_args()

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    if args.force and LOG_PATH.exists():
        LOG_PATH.unlink()

    results: list[ConversionResult] = []
    try:
        if not args.only_ocr:
            for item in MARXISTS_COLLECTIONS:
                out = output_path_for_pdf(item["pdf"])
                if out.exists() and not args.force:
                    log(f"skip existing {out}")
                    continue
                results.append(convert_marxists_collection(item))
            for item in WIKISOURCE_SINGLE_PAGES:
                out = output_path_for_pdf(item["pdf"])
                if out.exists() and not args.force:
                    log(f"skip existing {out}")
                    continue
                results.append(convert_wikisource_page(item))
            out = output_path_for_pdf(ZAGAN_SELECTION["pdf"])
            if out.exists() and not args.force:
                log(f"skip existing {out}")
            else:
                results.append(convert_zagan_selection())
            out = output_path_for_pdf(LUXUNLIB_LETTERS["pdf"])
            if out.exists() and not args.force:
                log(f"skip existing {out}")
            else:
                results.append(convert_luxunlib_letters())

        if not args.skip_ocr:
            for item in OCR_SOURCES:
                out = output_path_for_pdf(item["pdf"])
                if out.exists() and not args.force:
                    log(f"skip existing {out}")
                    continue
                results.append(convert_ocr_pdf(item, workers=max(1, args.workers), limit_pages=args.limit_ocr_pages))

        manifest = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "raw_dir": str(RAW_DIR),
            "results": [result.__dict__ for result in results],
        }
        MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"wrote manifest {MANIFEST_PATH}")
        return 0
    except Exception as exc:
        log(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
