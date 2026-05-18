#!/usr/bin/env python3
"""Extract text from PDF files for Mao Zedong source material collection."""

import sys
import json
from pathlib import Path

def extract_pdf_text(pdf_path, max_pages=None):
    """Extract text from PDF using PyMuPDF (fitz)."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        print("PyMuPDF not installed. Trying pypdf...")
        try:
            from pypdf import PdfReader
            reader = PdfReader(pdf_path)
            text_parts = []
            pages_to_read = min(len(reader.pages), max_pages) if max_pages else len(reader.pages)
            for i in range(pages_to_read):
                page = reader.pages[i]
                text_parts.append(f"\n--- Page {i+1} ---\n")
                text_parts.append(page.extract_text())
            return ''.join(text_parts)
        except ImportError:
            print("Neither PyMuPDF nor pypdf available. Please install: pip install PyMuPDF")
            return None

    # Use PyMuPDF
    doc = fitz.open(pdf_path)
    text_parts = []
    pages_to_read = min(len(doc), max_pages) if max_pages else len(doc)

    for page_num in range(pages_to_read):
        page = doc[page_num]
        text_parts.append(f"\n--- Page {page_num+1} ---\n")
        text_parts.append(page.get_text())

    doc.close()
    return ''.join(text_parts)

if __name__ == "__main__":
    import io
    # Force UTF-8 output
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    if len(sys.argv) < 2:
        print("Usage: python extract_pdf_text.py <pdf_path> [max_pages]")
        sys.exit(1)

    pdf_path = sys.argv[1]
    max_pages = int(sys.argv[2]) if len(sys.argv) > 2 else None

    text = extract_pdf_text(pdf_path, max_pages)
    if text:
        print(text)
    else:
        sys.exit(1)
