#!/usr/bin/env python3
"""
analyze_pdf_fonts.py — Analyze font distribution in a PDF to auto-detect
heading size thresholds for pdf_to_markdown.py style configuration.

Usage:
    python3 analyze_pdf_fonts.py <input.pdf> [--pages N]

Output (JSON to stdout):
    {
        "fonts": {
            "FontName": {"count": 123, "sizes": [10.0, 12.0, ...], "is_mono": true}
        },
        "size_clusters": [10.0, 12.0, 14.0, 18.0, 22.0],
        "suggested_config": {
            "heading_fonts": ["BoldFontName"],
            "code_fonts": ["MonoFontName"],
            "body_fonts": ["RegularFontName"],
            "h1_size": 22,
            "h2_size": 18,
            "h3_size": 14,
            "h4_size": 12,
            "header_y_max": 60,
            "footer_y_min": 740
        },
        "sample_spans": [...]
    }
"""

import json
import sys
import argparse
from collections import defaultdict
from pathlib import Path

try:
    import fitz
except ImportError:
    print(json.dumps({"error": "PyMuPDF not installed. Run: pip install pymupdf"}))
    sys.exit(1)


MONO_KEYWORDS = ("courier", "mono", "nimbusmono", "nimbusmonl", "consolas",
                 "inconsolata", "sourcecodepro", "droidmono", "lucidasans",
                 "typewriter", "teletype", "fixed", "ocr")

BOLD_KEYWORDS = ("bold", "black", "heavy", "semibold", "demibold", "extrabold")


def is_mono_font(name: str) -> bool:
    n = name.lower()
    return any(kw in n for kw in MONO_KEYWORDS)


def is_bold_font(name: str) -> bool:
    n = name.lower()
    return any(kw in n for kw in BOLD_KEYWORDS)


def analyze(pdf_path: str, max_pages: int = 30) -> dict:
    doc = fitz.open(pdf_path)
    total = doc.page_count
    scan_pages = min(max_pages, total)

    font_data = defaultdict(lambda: {"count": 0, "sizes": [], "bold_flags": 0})
    sample_spans = []

    page_height = None

    for page_num in range(scan_pages):
        page = doc[page_num]
        if page_height is None:
            page_height = page.rect.height

        for blk in page.get_text("dict", sort=True)["blocks"]:
            if blk["type"] != 0:
                continue
            for line in blk["lines"]:
                for span in line["spans"]:
                    text = span["text"].strip()
                    if not text:
                        continue
                    font = span["font"]
                    size = round(span["size"], 1)
                    flags = span["flags"]

                    fd = font_data[font]
                    fd["count"] += 1
                    fd["sizes"].append(size)
                    if flags & 16:
                        fd["bold_flags"] += 1

                    if len(sample_spans) < 50 and size > 11:
                        sample_spans.append({
                            "font": font,
                            "size": size,
                            "bold": is_bold_font(font) or bool(flags & 16),
                            "mono": is_mono_font(font),
                            "text": text[:80],
                            "page": page_num + 1,
                        })

    # Summarize
    fonts_summary = {}
    for fname, fd in font_data.items():
        sizes = fd["sizes"]
        fonts_summary[fname] = {
            "count": fd["count"],
            "sizes_unique": sorted(set(round(s, 1) for s in sizes)),
            "size_max": max(sizes) if sizes else 0,
            "is_mono": is_mono_font(fname),
            "is_bold": is_bold_font(fname),
            "bold_flag_ratio": round(fd["bold_flags"] / fd["count"], 2) if fd["count"] else 0,
        }

    # Collect all unique sizes across bold/heading fonts
    all_sizes = []
    for fname, fd in font_data.items():
        if is_bold_font(fname) or any(fd["bold_flags"] > 0 for fd in [font_data[fname]]):
            all_sizes.extend(set(round(s, 1) for s in fd["sizes"]))

    # Also include all sizes for clustering
    all_sizes_global = []
    for fd in font_data.values():
        all_sizes_global.extend(set(round(s, 1) for s in fd["sizes"]))

    size_counts = defaultdict(int)
    for s in all_sizes_global:
        size_counts[s] += 1

    # Find candidate heading sizes: large sizes (>= 11), sorted descending
    large_sizes = sorted([s for s in size_counts if s >= 11], reverse=True)

    # Determine thresholds by picking gaps in size distribution
    thresholds = []
    for s in large_sizes:
        if not thresholds or thresholds[-1] - s >= 1.5:
            thresholds.append(s)
        if len(thresholds) >= 4:
            break

    while len(thresholds) < 4:
        thresholds.append(thresholds[-1] - 2 if thresholds else 10)

    h1, h2, h3, h4 = thresholds[0], thresholds[1], thresholds[2], thresholds[3]

    # Identify heading, code, body font families
    heading_fonts = sorted(
        [f for f, d in fonts_summary.items()
         if (d["is_bold"] or d["bold_flag_ratio"] > 0.5) and not d["is_mono"]
         and d["size_max"] >= h3],
        key=lambda f: -fonts_summary[f]["size_max"]
    )

    code_fonts = [f for f, d in fonts_summary.items() if d["is_mono"]]

    body_fonts = sorted(
        [f for f, d in fonts_summary.items()
         if not d["is_bold"] and not d["is_mono"] and d["count"] > 20],
        key=lambda f: -fonts_summary[f]["count"]
    )[:5]

    # Estimate header/footer zones from page height
    header_y_max = round(page_height * 0.08) if page_height else 60
    footer_y_min = round(page_height * 0.88) if page_height else 740

    suggested = {
        "heading_fonts": heading_fonts[:6],
        "code_fonts": code_fonts[:8],
        "body_fonts": body_fonts[:5],
        "h1_size": h1,
        "h2_size": h2,
        "h3_size": h3,
        "h4_size": h4,
        "header_y_max": header_y_max,
        "footer_y_min": footer_y_min,
        "skip_pages": [],
    }

    return {
        "pdf": pdf_path,
        "total_pages": total,
        "scanned_pages": scan_pages,
        "page_height": page_height,
        "fonts": fonts_summary,
        "large_sizes_observed": large_sizes[:15],
        "suggested_config": suggested,
        "sample_spans": sample_spans[:30],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyze PDF font distribution")
    parser.add_argument("pdf", help="Input PDF file")
    parser.add_argument("--pages", type=int, default=30, help="Max pages to scan (default: 30)")
    args = parser.parse_args()

    result = analyze(args.pdf, args.pages)
    print(json.dumps(result, indent=2, ensure_ascii=False))
