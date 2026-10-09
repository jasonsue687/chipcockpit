"""parse_doc CLI: parse a doc into parsed/<source>/*.md and print the path(s).

Default (no slice args): parse ALL slices of the document.
    docx: one .md per Heading-N section
    xlsx: one .md per sheet (dense sheets default to schema-only)
    pptx: one .md containing all slides

Slice args (--section / --sheet / --slides) override default and parse only that slice.

Layout:
    parsed/
    └── <source-filename>/
        ├── _meta.json    {"sha": ..., "source": ..., "last_parsed": ...}
        ├── section-1.md
        ├── section-2.md
        ├── sheet-Power-full.md
        ├── sheet-Timing-full.md
        └── slides-1-12.md

Cache invalidation: if _meta.json's sha differs from the current source sha,
all stale .md files in the dir are purged before re-parsing.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from tools.handlers import docx_handler, pptx_handler, xlsx_handler
from tools.handlers.common import (
    file_meta,
    find_repo_root,
    is_supported,
    now_iso,
    parsed_dir,
    parsed_meta_path,
    parsed_path,
    relpath,
    slugify,
    write_md,
)


@dataclass
class SliceJob:
    slug: str
    desc: str
    body_fn: Callable[[], str]


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="parse-doc",
        description=(
            "Parse a Word/Excel/PPT document into parsed/<source>/*.md. "
            "Default: parse all slices. Use --section/--sheet/--slides for surgical mode."
        ),
    )
    p.add_argument("path", type=Path, help="Path to the source document under raw/")
    p.add_argument("--section", type=int, help="docx surgical: 1-based section index")
    p.add_argument("--sheet", type=str, help="xlsx surgical: sheet name")
    p.add_argument("--schema-only", action="store_true", help="xlsx surgical: schema preview only")
    p.add_argument("--rows", type=str, help="xlsx surgical: row range, e.g. '100:300'")
    p.add_argument("--slides", type=str, help="pptx surgical: slide range, e.g. '3-7'")
    p.add_argument("--force", action="store_true", help="ignore existing markdown and re-parse")
    return p


def _parse_rows(spec: str) -> tuple[int, int]:
    if ":" not in spec:
        raise ValueError(f"--rows must be 'start:end', got {spec!r}")
    a, b = spec.split(":", 1)
    return int(a), int(b)


def _parse_slides(spec: str) -> tuple[int, int]:
    if "-" not in spec:
        raise ValueError(f"--slides must be 'start-end', got {spec!r}")
    a, b = spec.split("-", 1)
    return int(a), int(b)


def _build_frontmatter(src_relpath: str, slice_desc: str) -> str:
    return (
        f"<!-- source: {src_relpath} -->\n"
        f"<!-- slice: {slice_desc} -->\n"
        f"<!-- generated: {now_iso()} -->\n\n"
    )


def _read_meta(meta_path: Path) -> dict | None:
    if not meta_path.exists():
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _write_meta(meta_path: Path, sha: str, source_rel: str) -> None:
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta = {"sha": sha, "source": source_rel, "last_parsed": now_iso()}
    meta_path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _purge_stale_slices(parsed_dir_path: Path) -> int:
    if not parsed_dir_path.exists():
        return 0
    n = 0
    for p in parsed_dir_path.iterdir():
        if p.is_file() and p.name != "_meta.json":
            p.unlink()
            n += 1
    return n


def _surgical_jobs(meta, src: Path, args) -> list[SliceJob]:
    if meta.type == "docx":
        if args.section is None:
            raise ValueError("docx surgical mode requires --section <N>")
        return [
            SliceJob(
                slug=slugify(f"section-{args.section}"),
                desc=f"section={args.section}",
                body_fn=lambda: docx_handler.parse_section(src, args.section),
            )
        ]
    if meta.type == "xlsx":
        if not args.sheet:
            raise ValueError("xlsx surgical mode requires --sheet <NAME>")
        rows_range = _parse_rows(args.rows) if args.rows else None
        mode = "schema" if args.schema_only else (f"rows-{args.rows}" if args.rows else "full")
        return [
            SliceJob(
                slug=slugify(f"sheet-{args.sheet}-{mode}"),
                desc=f"sheet={args.sheet} · {mode}",
                body_fn=lambda: xlsx_handler.parse_sheet(
                    src, args.sheet, schema_only=args.schema_only, rows_range=rows_range
                ),
            )
        ]
    if meta.type == "pptx":
        if not args.slides:
            raise ValueError("pptx surgical mode requires --slides A-B")
        start, end = _parse_slides(args.slides)
        return [
            SliceJob(
                slug=slugify(f"slides-{start}-{end}"),
                desc=f"slides={start}-{end}",
                body_fn=lambda: pptx_handler.parse_slides(src, start, end),
            )
        ]
    raise ValueError(f"unsupported type {meta.type}")


def _all_jobs(meta, src: Path) -> list[SliceJob]:
    if meta.type == "docx":
        scan = docx_handler.scan_meta(src)
        jobs: list[SliceJob] = []
        for s in scan.sections:
            idx = s.idx
            jobs.append(
                SliceJob(
                    slug=slugify(f"section-{idx}"),
                    desc=f"section={idx}",
                    body_fn=lambda i=idx: docx_handler.parse_section(src, i),
                )
            )
        return jobs
    if meta.type == "xlsx":
        scan = xlsx_handler.scan_meta(src)
        jobs = []
        for s in scan.sheets:
            schema_only = s.dense
            mode = "schema" if schema_only else "full"
            name = s.name
            jobs.append(
                SliceJob(
                    slug=slugify(f"sheet-{name}-{mode}"),
                    desc=f"sheet={name} · {mode}",
                    body_fn=lambda n=name, so=schema_only: xlsx_handler.parse_sheet(
                        src, n, schema_only=so
                    ),
                )
            )
        return jobs
    if meta.type == "pptx":
        scan = pptx_handler.scan_meta(src)
        n = len(scan.slides)
        if n == 0:
            return []
        return [
            SliceJob(
                slug=slugify(f"slides-1-{n}"),
                desc=f"slides=1-{n}",
                body_fn=lambda: pptx_handler.parse_slides(src, 1, n),
            )
        ]
    raise ValueError(f"unsupported type {meta.type}")


def main() -> int:
    args = _build_parser().parse_args()
    repo = find_repo_root()

    src = args.path.resolve()
    if not src.is_file():
        print(f"error: file not found: {args.path}", file=sys.stderr)
        return 2
    if not is_supported(src):
        print(
            f"error: unsupported extension {src.suffix!r}; expected .docx/.xlsx/.pptx",
            file=sys.stderr,
        )
        return 2

    meta = file_meta(src)
    src_rel = relpath(src, repo)
    meta_path = parsed_meta_path(repo, src)
    existing = _read_meta(meta_path)
    out_dir = parsed_dir(repo, src)

    surgical = (
        args.section is not None or args.sheet is not None or args.slides is not None
    )

    try:
        jobs = _surgical_jobs(meta, src, args) if surgical else _all_jobs(meta, src)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if not jobs:
        print(f"warn: no slices to parse for {src_rel}", file=sys.stderr)
        return 0

    if existing and existing.get("sha") != meta.sha:
        n = _purge_stale_slices(out_dir)
        if n:
            print(
                f"info: source sha changed; purged {n} stale slice(s)",
                file=sys.stderr,
            )

    sha_match = bool(existing) and existing.get("sha") == meta.sha
    output_paths: list[Path] = []
    parsed_count = 0

    for job in jobs:
        target = parsed_path(repo, src, job.slug)
        if target.exists() and sha_match and not args.force:
            output_paths.append(target)
            continue
        try:
            body = job.body_fn()
        except Exception as e:
            print(f"error: failed to parse {job.desc}: {e}", file=sys.stderr)
            return 1
        content = _build_frontmatter(src_rel, job.desc) + body
        write_md(target, content)
        output_paths.append(target)
        parsed_count += 1

    _write_meta(meta_path, meta.sha, src_rel)

    for p in output_paths:
        print(p)

    if parsed_count and not surgical:
        print(
            f"info: parsed {parsed_count} new slice(s) of {len(jobs)} total",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
