"""
PDF text extraction helper for the Feynman distillation pipeline.
Usage: python extract_pdf.py <mode> <filename> [start_page] [end_page]
Modes:
  toc     - Print table of contents
  pages   - Extract text from page range
  info    - Print page count and basic info
"""
import sys
import os
import fitz

# Force UTF-8 output
sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', errors='replace', buffering=1)

RAW_DIR = r"D:\mind distill factory\sources\richard-feynman\raw"

def get_filepath(filename):
    """Find the file in the raw directory."""
    path = os.path.join(RAW_DIR, filename)
    if os.path.exists(path):
        return path
    # Try partial match
    for f in os.listdir(RAW_DIR):
        if filename.lower() in f.lower():
            return os.path.join(RAW_DIR, f)
    raise FileNotFoundError(f"Cannot find '{filename}' in {RAW_DIR}")

def show_toc(filepath):
    doc = fitz.open(filepath)
    print(f"File: {os.path.basename(filepath)}")
    print(f"Total pages: {len(doc)}")
    toc = doc.get_toc()
    if toc:
        print(f"\nTable of Contents ({len(toc)} entries):")
        for item in toc:
            indent = "  " * (item[0] - 1)
            print(f"  {indent}[p.{item[2]}] {item[1]}")
    else:
        print("\nNo TOC found. Showing first 3 pages as preview:")
        for i in range(min(3, len(doc))):
            text = doc[i].get_text()
            print(f"\n--- PAGE {i+1} ---")
            print(text[:2000])
    doc.close()

def extract_pages(filepath, start, end):
    doc = fitz.open(filepath)
    total = len(doc)
    start = max(0, start - 1)  # Convert to 0-indexed
    end = min(total, end)
    print(f"Extracting pages {start+1}-{end} of {total} from {os.path.basename(filepath)}")
    for i in range(start, end):
        text = doc[i].get_text()
        print(f"\n--- PAGE {i+1} ---")
        print(text)
    doc.close()

def show_info(filepath):
    doc = fitz.open(filepath)
    print(f"File: {os.path.basename(filepath)}")
    print(f"Total pages: {len(doc)}")
    meta = doc.metadata
    for k, v in meta.items():
        if v:
            print(f"  {k}: {v}")
    doc.close()

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    mode = sys.argv[1]
    filename = sys.argv[2]
    filepath = get_filepath(filename)

    if mode == "toc":
        show_toc(filepath)
    elif mode == "pages":
        start = int(sys.argv[3]) if len(sys.argv) > 3 else 1
        end = int(sys.argv[4]) if len(sys.argv) > 4 else start + 19
        extract_pages(filepath, start, end)
    elif mode == "info":
        show_info(filepath)
    else:
        print(f"Unknown mode: {mode}")
        sys.exit(1)
