#!/usr/bin/env python3
"""
PDF to Markdown converter for EDA user guide documents (Innovus/Cadence).

Supports two PDF styles detected automatically:
  Style A (RAK/Lab docs):  Arial/Times fonts, no native TOC
  Style B (User Guide):    NimbusSanL/NimbusMonL fonts, native TOC available

Usage:
    python3 pdf_to_markdown.py <input.pdf> [output.md] [--start N] [--end N]

Options:
    --start N   Start from page N (1-indexed, default: 1)
    --end N     End at page N inclusive (default: last page)

Images are saved to <output_dir>/images/.
Markdown output is appended if --start > 1 (resume mode).
"""

import re
import sys
import argparse
from pathlib import Path

import fitz  # pymupdf


# ---------------------------------------------------------------------------
# Style detection and per-style config
# ---------------------------------------------------------------------------

def detect_style(doc: fitz.Document) -> str:
    """Return 'A' (RAK/Lab) or 'B' (UserGuide) based on font inspection."""
    page = doc[min(5, doc.page_count - 1)]
    fonts = set()
    for b in page.get_text("dict")["blocks"]:
        if b["type"] == 0:
            for line in b["lines"]:
                for span in line["spans"]:
                    fonts.add(span["font"])
    if any("Nimbus" in f for f in fonts):
        return "B"
    return "A"


# Style A (RAK docs) config
STYLE_A = {
    "code_fonts":    {"CourierNewPSMT", "CourierNewPS-BoldMT", "Courier", "Courier-Bold"},
    "heading_fonts": {"Arial", "Calibri"},
    "body_fonts":    {"Times"},
    "h1_size":       22,
    "h2_size":       13,
    "h3_size":       11,
    "skip_pages":    {1, 2, 3, 4},
    "header_y_max":  0,     # Style A has no page header — don't skip any top content
    "footer_y_min":  740,
    "footer_fonts":  {"LiberationSans", "TimesNewRoman"},
    "page_num_font": "TimesNewRoman",
}

# Style B (User Guide) config — NimbusSanL font family
# Heading size hierarchy observed:
#   H1: ~23-25 bold  (chapter title, e.g. "About This Manual")
#   H2: ~20-22 bold  (major section, e.g. "Audience")
#   H3: ~14-16 bold  (subsection, e.g. "Product Packages and Options")
#   H4: ~11-13 bold  (minor heading)
# Non-bold large text (~21, NimbusSanL-Regu) = chapter number → skip
STYLE_B = {
    "code_fonts":    {"NimbusMonL", "NimbusMonL-Regu", "NimbusMonL-Bold",
                      "NimbusMonL-ReguObli", "NimbusMonL-BoldObli",
                      "CourierNewPSMT", "Courier"},
    "heading_fonts": {"NimbusSanL-Bold"},
    "body_fonts":    {"NimbusSanL-Regu", "NimbusSanL"},
    "h1_size":       22,    # chapter title ~23-25
    "h2_size":       19,    # major section ~20-22
    "h3_size":       13,    # subsection ~14-16
    "h4_size":       11,    # minor heading ~11-13
    "skip_pages":    set(),
    "header_y_max":  60,
    "footer_y_min":  740,
    "footer_fonts":  {"LiberationSans"},
    "page_num_font": "LiberationSans",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_bold(span: dict) -> bool:
    return "Bold" in span["font"] or "bold" in span["font"].lower() or bool(span["flags"] & 16)


def clean(text: str) -> str:
    replacements = [
        ("\u2019", "'"), ("\u2018", "'"), ("\u201c", '"'), ("\u201d", '"'),
        ("\u2013", "-"), ("\u2014", "--"), ("\u00ae", "(R)"), ("\u2122", "(TM)"),
        ("\u00b0", " deg"), ("\xa0", " "), ("\u00b7", "*"),
    ]
    for a, b in replacements:
        text = text.replace(a, b)
    return text


def is_code_font(span: dict, cfg: dict) -> bool:
    font = span["font"]
    return font in cfg["code_fonts"] or any(font.startswith(cf.split("-")[0])
                                             for cf in cfg["code_fonts"])


def heading_level(span: dict, cfg: dict):
    """Return 1/2/3/4 or None based on font size + bold."""
    if not is_bold(span):
        return None
    if not any(hf in span["font"] for hf in cfg["heading_fonts"]):
        return None
    size = span["size"]
    # Check levels from largest to smallest
    for level, key in [(1, "h1_size"), (2, "h2_size"), (3, "h3_size"), (4, "h4_size")]:
        threshold = cfg.get(key)
        if threshold and size >= threshold:
            return level
    return None


def is_header_or_footer(block_y: float, page_height: float, cfg: dict) -> bool:
    """True if block is in header or footer zone."""
    return block_y < cfg["header_y_max"] or block_y > min(cfg["footer_y_min"], page_height - 30)


def is_page_number_line(text: str, font: str, cfg: dict) -> bool:
    """Single integer line from footer font."""
    return bool(re.fullmatch(r"\d{1,4}", text.strip())) and \
           any(pf in font for pf in cfg["footer_fonts"])


# ---------------------------------------------------------------------------
# Per-page extraction
# ---------------------------------------------------------------------------

def extract_blocks(page: fitz.Page, page_num: int, img_dir: Path, cfg: dict) -> list:
    """Return ordered list of logical block dicts."""
    result = []
    page_height = page.rect.height
    raw_blocks = page.get_text("dict", sort=True)["blocks"]

    for blk in raw_blocks:
        blk_y = blk["bbox"][1]

        # --- images ---
        if blk["type"] == 1:
            if is_header_or_footer(blk_y, page_height, cfg):
                continue
            img_idx = len(list(img_dir.glob(f"page{page_num:04d}_*.png")))
            img_path = img_dir / f"page{page_num:04d}_img{img_idx:02d}.png"
            try:
                mat = fitz.Matrix(1.5, 1.5)
                clip = fitz.Rect(blk["bbox"])
                pix = page.get_pixmap(matrix=mat, clip=clip)
                if pix.width > 20 and pix.height > 20:  # skip tiny artifacts
                    pix.save(str(img_path))
                    result.append({"type": "image", "path": str(img_path)})
            except Exception:
                pass
            continue

        # --- text block ---
        if is_header_or_footer(blk_y, page_height, cfg):
            continue

        # Gather lines
        block_lines = []
        for line in blk["lines"]:
            if not line["spans"]:
                continue
            line_text = clean("".join(s["text"] for s in line["spans"]))
            stripped = line_text.strip()
            if not stripped:
                continue
            rep = next((s for s in line["spans"] if s["text"].strip()), line["spans"][0])
            # Skip page numbers
            if is_page_number_line(stripped, rep["font"], cfg):
                continue
            block_lines.append((rep, line_text, stripped))

        if not block_lines:
            continue

        # Detect module/chapter cover: all lines bold+large in same block
        if all(rep["size"] >= cfg["h1_size"] and is_bold(rep)
               for rep, _, _ in block_lines):
            merged = " ".join(s for _, _, s in block_lines)
            result.append({"type": "h1", "text": merged})
            continue

        # Process line by line
        skip_indices = set()
        for idx, (rep, line_text, stripped) in enumerate(block_lines):
            if idx in skip_indices:
                continue

            if is_code_font(rep, cfg):
                result.append({"type": "code", "text": line_text.rstrip()})
                continue

            lvl = heading_level(rep, cfg)

            # H2 "Lab X-X" split across lines within same block → merge with next line(s)
            if lvl == 2 and re.match(r"^Lab\s+\d+-\d+$", stripped):
                parts = [stripped]
                j = idx + 1
                while j < len(block_lines):
                    nrep, _, nstripped = block_lines[j]
                    if heading_level(nrep, cfg) == 2:
                        parts.append(nstripped)
                        skip_indices.add(j)
                        j += 1
                    else:
                        break
                result.append({"type": "h2", "text": "  ".join(parts)})
                continue

            # H2 split: non-"Lab" heading whose text wraps to next line (same size+font)
            if lvl == 2 and idx + 1 < len(block_lines):
                nrep, _, nstripped = block_lines[idx + 1]
                if (heading_level(nrep, cfg) == 2
                        and abs(nrep["size"] - rep["size"]) < 0.5
                        and nrep["font"] == rep["font"]):
                    result.append({"type": "h2", "text": stripped + " " + nstripped})
                    skip_indices.add(idx + 1)
                    continue

            # H3/H4 multi-line block heuristic: only first short ":" line is a heading,
            # subsequent bold lines become bold body
            if lvl in (3, 4) and len(block_lines) > 1:
                htype = "h3" if lvl == 3 else "h4"
                if idx == 0 and stripped.endswith(":") and len(stripped) < 50:
                    result.append({"type": htype, "text": stripped})
                else:
                    result.append({"type": "body", "text": f"**{stripped}**"})
                continue

            if lvl == 1:
                result.append({"type": "h1", "text": stripped})
            elif lvl == 2:
                result.append({"type": "h2", "text": stripped})
            elif lvl == 3:
                result.append({"type": "h3", "text": stripped})
            elif lvl == 4:
                result.append({"type": "h4", "text": stripped})
            else:
                m = re.match(r"^(\d+)\.\s+(.*)", stripped, re.DOTALL)
                if m:
                    result.append({"type": "list", "num": int(m.group(1)),
                                   "text": m.group(2).strip()})
                else:
                    result.append({"type": "body", "text": stripped})

    return result


# ---------------------------------------------------------------------------
# Post-processing
# ---------------------------------------------------------------------------

def postprocess(blocks: list) -> list:
    """Merge split Lab/heading lines."""
    out = []
    i = 0
    while i < len(blocks):
        b = blocks[i]
        # "Lab X-X" (Style A) h2 followed by another h2 → merge
        if (b["type"] == "h2" and re.match(r"^Lab\s+\d+-\d+$", b["text"])
                and i + 1 < len(blocks) and blocks[i + 1]["type"] == "h2"):
            out.append({"type": "h2", "text": b["text"] + "  " + blocks[i + 1]["text"]})
            i += 2
            continue
        out.append(b)
        i += 1
    return out


# ---------------------------------------------------------------------------
# Blocks → Markdown
# ---------------------------------------------------------------------------

def blocks_to_md(blocks: list, img_dir: Path, base_dir: Path) -> str:
    lines = []
    in_code = False
    prev_type = None

    def close_code():
        nonlocal in_code
        if in_code:
            lines.append("```")
            lines.append("")
            in_code = False

    def open_code():
        nonlocal in_code
        if not in_code:
            if lines and lines[-1] != "":
                lines.append("")
            lines.append("```")
            in_code = True

    for b in blocks:
        t = b["type"]
        if t == "code":
            open_code()
            lines.append(b["text"])
        else:
            close_code()
            if t == "h1":
                lines += ["", f"# {b['text']}", ""]
            elif t == "h2":
                lines += ["", f"## {b['text']}", ""]
            elif t == "h3":
                lines += ["", f"### {b['text']}", ""]
            elif t == "h4":
                lines += ["", f"#### {b['text']}", ""]
            elif t == "body":
                if prev_type not in ("body", "list"):
                    lines.append("")
                lines.append(b["text"])
            elif t == "list":
                if prev_type not in ("list",):
                    lines.append("")
                lines.append(f"{b['num']}. {b['text']}")
            elif t == "image":
                try:
                    rel = Path(b["path"]).relative_to(base_dir)
                except ValueError:
                    rel = Path(b["path"]).name
                lines += ["", f"![](images/{Path(b['path']).name})", ""]
        prev_type = t

    close_code()
    content = "\n".join(lines)
    content = re.sub(r"\n{3,}", "\n\n", content)
    return content


# ---------------------------------------------------------------------------
# TOC building
# ---------------------------------------------------------------------------

def build_toc_md(doc: fitz.Document) -> str:
    """Return Markdown TOC string."""
    toc = doc.get_toc()
    if not toc:
        return ""
    lines = ["## Table of Contents", ""]
    for level, title, page in toc:
        indent = "  " * (level - 1)
        title = clean(title)
        lines.append(f"{indent}- {title}")
    return "\n".join(lines)


def parse_toc_page_manual(doc: fitz.Document) -> str:
    """Fallback: parse TOC page visually (Style A)."""
    lines = ["## Table of Contents", ""]
    page = doc[2]
    for blk in page.get_text("dict", sort=True)["blocks"]:
        if blk["type"] != 0:
            continue
        for line in blk["lines"]:
            text = clean("".join(s["text"] for s in line["spans"])).strip()
            text = re.sub(r"[.\s]{4,}\d+\s*$", "", text).strip()
            text = re.sub(r"\s{2,}\d+\s*$", "", text).strip()
            if not text or re.fullmatch(r"\d+", text):
                continue
            if text in ("Table of Contents", "Database Access with DBTCL"):
                continue
            pending = getattr(parse_toc_page_manual, "_pending", None)
            if re.match(r"^Module\s+\d+\s*:", text):
                parse_toc_page_manual._pending = text
            elif re.match(r"^Lab\s+\d+-\d+$", text):
                parse_toc_page_manual._pending = text
            else:
                if pending:
                    full = f"{pending}  {text}"
                    if re.match(r"^Module", pending):
                        lines.append(f"- **{full}**")
                    else:
                        lines.append(f"  - {full}")
                    parse_toc_page_manual._pending = None
                else:
                    lines.append(f"- {text}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def detect_content_start(doc: fitz.Document, cfg: dict) -> int:
    """
    Return 1-indexed page number where real content starts.
    Skips cover/copyright pages and TOC pages (identified by header text).
    """
    toc_header_keywords = ("table of contents", "contents")
    content_start = 1
    for page_num in range(min(60, doc.page_count)):
        page = doc[page_num]
        # Read header zone text (y < header_y_max)
        header_text = ""
        for blk in page.get_text("dict", sort=True)["blocks"]:
            if blk["type"] == 0 and blk["bbox"][1] < cfg["header_y_max"]:
                header_text += " ".join(
                    s["text"] for line in blk["lines"] for s in line["spans"]
                ).lower()
        if any(kw in header_text for kw in toc_header_keywords):
            content_start = page_num + 2  # skip this page, content starts after
    return content_start


def convert(pdf_path: str, output_path=None, start_page: int = 1, end_page: int = None) -> None:
    pdf_path = Path(pdf_path)
    if output_path is None:
        output_path = pdf_path.with_suffix(".md")
    else:
        output_path = Path(output_path)

    img_dir = output_path.parent / "images"
    img_dir.mkdir(parents=True, exist_ok=True)

    print(f"Opening: {pdf_path}")
    doc = fitz.open(str(pdf_path))
    total = doc.page_count
    print(f"Total pages: {total}")

    # Detect style
    style = detect_style(doc)
    cfg = STYLE_A if style == "A" else STYLE_B
    print(f"Detected style: {style} ({'RAK/Lab' if style == 'A' else 'User Guide'})")

    # For Style B: auto-detect content start to skip cover/copyright/TOC pages
    auto_skip_before = 1
    if style == "B" and start_page == 1:
        auto_skip_before = detect_content_start(doc, cfg)
        print(f"Auto-detected content start: page {auto_skip_before}")

    # Clamp range
    start_page = max(1, start_page)
    if end_page is None or end_page > total:
        end_page = total

    print(f"Converting pages {start_page}–{end_page} ...")

    resume = start_page > 1

    # --- Build header (only on first run) ---
    if not resume:
        # Title
        p0 = doc[0]
        title_parts = []
        for blk in p0.get_text("dict")["blocks"]:
            if blk["type"] == 0:
                for line in blk["lines"]:
                    for span in line["spans"]:
                        if span["size"] >= 16 and is_bold(span):
                            t = clean(span["text"].strip())
                            if t:
                                title_parts.append(t)
        title = " ".join(dict.fromkeys(title_parts)) or pdf_path.stem

        # TOC
        toc_md = build_toc_md(doc)
        if not toc_md:
            toc_md = parse_toc_page_manual(doc)

        header = "\n".join([
            f"# {title}",
            "",
            toc_md,
            "",
            "---",
            "",
        ])
        output_path.write_text(header, encoding="utf-8")

    # --- Process pages ---
    all_blocks = []
    for page_num in range(start_page - 1, end_page):
        p1 = page_num + 1
        if p1 in cfg["skip_pages"]:
            continue
        if p1 < auto_skip_before:
            continue
        if (p1 - start_page) % 50 == 0:
            print(f"  Page {p1}/{end_page} ...")
        page = doc[page_num]
        blocks = extract_blocks(page, p1, img_dir, cfg)
        all_blocks.extend(blocks)

    all_blocks = postprocess(all_blocks)
    body_md = blocks_to_md(all_blocks, img_dir, output_path.parent)

    # Append to output
    with output_path.open("a", encoding="utf-8") as f:
        f.write(body_md)

    img_count = len(list(img_dir.glob("*.png")))
    size_kb = output_path.stat().st_size // 1024
    print(f"\nDone!")
    print(f"  Output : {output_path}  ({size_kb} KB)")
    print(f"  Images : {img_dir}  ({img_count} files)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert EDA PDF to Markdown")
    parser.add_argument("pdf", help="Input PDF file")
    parser.add_argument("output", nargs="?", help="Output .md file (default: same name)")
    parser.add_argument("--start", type=int, default=1, help="Start page (1-indexed)")
    parser.add_argument("--end", type=int, default=None, help="End page (inclusive)")
    args = parser.parse_args()

    convert(args.pdf, args.output, args.start, args.end)
