#!/usr/bin/env python3
"""
One-shot PDF to hierarchical EDA knowledge base converter.

This wraps the existing pdf-to-markdown skill scripts in one Python process:
  1. analyze_pdf_fonts.py
  2. pdf_to_markdown.py
  3. build_knowledge_base.py

Usage:
    python3 pdf_to_kb.py <input.pdf> --doc-name example_ug --version unknown --overwrite
"""

import argparse
import json
import re
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = SCRIPT_DIR.parents[2]
DEFAULT_PROCESSED_ROOT = PLUGIN_ROOT / "knowledge" / "processed_eda"


def safe_path_part(raw: str, fallback: str) -> str:
    """Return a conservative filesystem-safe path segment."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", raw).strip("._-")
    return cleaned or fallback


def count_files(root: Path, pattern: str) -> int:
    if not root.exists():
        return 0
    return sum(1 for _ in root.rglob(pattern))


def build_output_path(processed_root: Path, doc_name: str, version: str) -> Path:
    if version:
        return processed_root / doc_name / version / f"{doc_name}.md"
    return processed_root / doc_name / f"{doc_name}.md"


def load_converter_modules():
    try:
        import fitz  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "PyMuPDF is not installed. Install it with: python3 -m pip install pymupdf"
        ) from exc

    try:
        from analyze_pdf_fonts import analyze
        import build_knowledge_base
        import pdf_to_markdown
    except ImportError as exc:
        raise RuntimeError(f"failed to import converter modules: {exc}") from exc

    return analyze, build_knowledge_base, pdf_to_markdown


def write_font_analysis(analyze_fn, pdf_path: Path, output_md: Path, pages: int) -> None:
    print(f"[1/4] Analyzing PDF fonts ({pages} pages)...")
    result = analyze_fn(str(pdf_path), pages)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    analysis_path = output_md.parent / "font_analysis.json"
    analysis_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    suggested = result.get("suggested_config", {})
    print(f"      wrote {analysis_path}")
    print(f"      heading fonts: {', '.join(suggested.get('heading_fonts', [])[:4]) or '(none)'}")
    print(f"      code fonts   : {', '.join(suggested.get('code_fonts', [])[:4]) or '(none)'}")
    print(
        "      heading sizes: "
        f"H1>={suggested.get('h1_size')} "
        f"H2>={suggested.get('h2_size')} "
        f"H3>={suggested.get('h3_size')} "
        f"H4>={suggested.get('h4_size')}"
    )


def validate_outputs(processed_root: Path, doc_name: str) -> None:
    doc_root = processed_root / doc_name
    manual_summary = doc_root / "_summary.md"
    global_index = processed_root / "_global_index.md"

    print("[4/4] Checking generated knowledge base...")
    print(f"      manual summary: {manual_summary if manual_summary.exists() else '(missing)'}")
    print(f"      global index  : {global_index if global_index.exists() else '(missing)'}")
    print(f"      summary files : {count_files(doc_root, '_summary.md')}")
    print(f"      detail files  : {count_files(doc_root, 'detail_*.md')}")
    print(f"      images        : {count_files(doc_root, '*.png')}")

    if not manual_summary.exists():
        raise RuntimeError(f"manual summary was not generated: {manual_summary}")
    if count_files(doc_root, "detail_*.md") == 0:
        raise RuntimeError(f"no detail_*.md files were generated under: {doc_root}")


def run(args: argparse.Namespace) -> int:
    pdf_path = args.pdf.resolve()
    if not pdf_path.exists():
        print(f"ERROR: input PDF not found: {pdf_path}", file=sys.stderr)
        return 1
    if pdf_path.suffix.lower() != ".pdf":
        print(f"ERROR: input must be a PDF file: {pdf_path}", file=sys.stderr)
        return 1

    processed_root = args.processed_root.resolve()
    doc_name = safe_path_part(args.doc_name or pdf_path.stem, "converted_pdf")
    version = safe_path_part(args.version, "unknown") if args.version else ""
    output_md = build_output_path(processed_root, doc_name, version)

    if output_md.exists() and not args.overwrite and not args.resume:
        print(
            f"ERROR: output Markdown already exists: {output_md}\n"
            "Use --overwrite to regenerate it, or --resume with --start N to append.",
            file=sys.stderr,
        )
        return 1

    print(f"PDF       : {pdf_path}")
    print(f"Doc name  : {doc_name}")
    print(f"Version   : {version or '(none)'}")
    print(f"Output MD : {output_md}")
    print()

    analyze_fn, build_knowledge_base, pdf_to_markdown = load_converter_modules()

    if not args.skip_analyze:
        write_font_analysis(analyze_fn, pdf_path, output_md, args.analyze_pages)
    else:
        print("[1/4] Skipping font analysis.")

    print("[2/4] Converting PDF to Markdown...")
    start = args.start
    if args.resume and start <= 1:
        print("ERROR: --resume requires --start N where N > 1", file=sys.stderr)
        return 1
    pdf_to_markdown.convert(str(pdf_path), str(output_md), start_page=start, end_page=args.end)

    print()
    print("[3/4] Building hierarchical knowledge base...")
    build_knowledge_base.build(
        output_md.resolve(),
        doc_name_override=None,
        dry_run=False,
        overwrite=args.overwrite,
    )

    print()
    validate_outputs(processed_root, doc_name)
    print()
    print("Done.")
    print(f"Knowledge base root: {processed_root / doc_name}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert one EDA PDF into the processed_eda hierarchical knowledge base."
    )
    parser.add_argument("pdf", type=Path, help="Input PDF file")
    parser.add_argument("--doc-name", help="Document folder/name. Defaults to PDF stem.")
    parser.add_argument("--version", default="unknown", help="Version folder. Use '' for no version folder.")
    parser.add_argument(
        "--processed-root",
        type=Path,
        default=DEFAULT_PROCESSED_ROOT,
        help=f"processed_eda root. Default: {DEFAULT_PROCESSED_ROOT}",
    )
    parser.add_argument("--start", type=int, default=1, help="Start page, 1-indexed. Default: 1")
    parser.add_argument("--end", type=int, help="End page, inclusive. Default: last page")
    parser.add_argument("--resume", action="store_true", help="Append conversion from --start instead of regenerating")
    parser.add_argument("--overwrite", action="store_true", help="Regenerate existing Markdown and KB files")
    parser.add_argument("--analyze-pages", type=int, default=30, help="Pages to scan for font analysis. Default: 30")
    parser.add_argument("--skip-analyze", action="store_true", help="Skip font analysis JSON generation")
    args = parser.parse_args()

    try:
        raise SystemExit(run(args))
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
