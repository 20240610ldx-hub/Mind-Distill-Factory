#!/usr/bin/env python3
"""Extract text from PDF with proper CMap handling for Chinese fonts."""

import sys
import io
from pathlib import Path

def extract_with_cmap(pdf_path, start_page=0, max_pages=50):
    """Extract text using PyMuPDF with explicit CMap handling."""
    try:
        import fitz
    except ImportError:
        print("PyMuPDF not installed")
        return None

    doc = fitz.open(pdf_path)
    text_parts = []
    end_page = min(len(doc), start_page + max_pages)

    for page_num in range(start_page, end_page):
        page = doc[page_num]
        text_parts.append(f"\n--- Page {page_num+1} ---\n")

        # Try different extraction methods
        # Method 1: blocks (structured text)
        blocks = page.get_text("blocks")
        for block in blocks:
            if len(block) >= 5:  # block format: (x0, y0, x1, y1, "text", block_no, block_type)
                text_parts.append(block[4])

    doc.close()
    return ''.join(text_parts)

if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    if len(sys.argv) < 2:
        print("Usage: python extract_pdf_with_cmap.py <pdf_path> [start_page] [max_pages]")
        sys.exit(1)

    pdf_path = sys.argv[1]
    start_page = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    max_pages = int(sys.argv[3]) if len(sys.argv) > 3 else 50

    text = extract_with_cmap(pdf_path, start_page, max_pages)
    if text:
        print(text)
    else:
        sys.exit(1)
