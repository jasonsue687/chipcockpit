"""scan_index: walk raw/ and (re)generate INDEX.md, preserving lazy-filled fields."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

from tools.handlers import docx_handler, pptx_handler, xlsx_handler
from tools.handlers.common import (
    SUPPORTED_EXTS,
    FileMeta,
    file_meta,
    find_repo_root,
    human_size,
    is_supported,
    relpath,
)


PRESERVED_FIELDS = ("summary", "entities", "project")
TBD = "<TBD>"


@dataclass
class IndexEntry:
    meta: FileMeta
    structure: object
    summary: str
    entities: str
    project: str
    relpath: str


@dataclass
class PreservedRecord:
    sha: str
    path: str | None
    fields: dict[str, str]


def _parse_existing_index(path: Path) -> list[PreservedRecord]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    blocks = re.split(r"(?m)^## ", text)
    out: list[PreservedRecord] = []
    for block in blocks[1:]:
        sha_m = re.search(r"(?m)^- .*\bsha:\s*([0-9a-f]{12})", block)
        if not sha_m:
            continue
        sha = sha_m.group(1)
        path_m = re.search(r"(?m)^- path:\s*(\S+)", block)
        rec_path = path_m.group(1).rstrip() if path_m else None
        fields: dict[str, str] = {}
        for fname in PRESERVED_FIELDS:
            m = re.search(rf"(?m)^- {fname}:\s*(.*)$", block)
            if m:
                fields[fname] = m.group(1).rstrip()
        out.append(PreservedRecord(sha=sha, path=rec_path, fields=fields))
    return out


def _has_filled_fields(fields: dict[str, str]) -> bool:
    return any(
        v and v.strip() != TBD
        for k, v in fields.items()
        if k in PRESERVED_FIELDS
    )


def _scan_one(path: Path) -> object | None:
    ext = path.suffix.lower().lstrip(".")
    try:
        if ext == "docx":
            return docx_handler.scan_meta(path)
        if ext == "xlsx":
            return xlsx_handler.scan_meta(path)
        if ext == "pptx":
            return pptx_handler.scan_meta(path)
    except Exception as e:
        print(f"warn: failed to scan {path}: {e}", file=sys.stderr)
        return None
    return None


def _render_entry(idx: int, e: IndexEntry) -> str:
    meta = e.meta
    head = f"## doc_{idx:03d} · {meta.name}"
    lines = [
        head,
        f"- path: {e.relpath}",
        f"- type: {meta.type} | size: {human_size(meta.size)} | mtime: {meta.mtime} | sha: {meta.sha}",
    ]
    if meta.type == "docx":
        scan = e.structure  # DocxScan
        sections = scan.sections  # type: ignore[attr-defined]
        split = scan.split_level  # type: ignore[attr-defined]
        if split is None:
            anno = " _(无标题层级，整篇为一段)_"
        else:
            anno = f" _(按 Heading {split} 切分)_"
        lines.append(f"- toc:{anno}")
        for s in sections:
            lines.append(
                f"    {s.idx}. {s.title} [paragraphs:{s.paragraphs}, images:{s.images}, tables:{s.tables}]"
            )
    elif meta.type == "xlsx":
        sheets = e.structure.sheets  # type: ignore[attr-defined]
        if sheets:
            lines.append("- sheets:")
            for s in sheets:
                tag = " (dense)" if s.dense else ""
                lines.append(
                    f"    - {s.name} [rows:{s.rows}, cols:{s.cols}, has_header:{s.has_header}]{tag}"
                )
        else:
            lines.append("- sheets: _(无)_")
    elif meta.type == "pptx":
        slides = e.structure.slides  # type: ignore[attr-defined]
        if slides:
            lines.append("- slides:")
            for s in slides:
                notes = " ✎" if s.has_notes else ""
                lines.append(
                    f"    {s.idx}. {s.title} [images:{s.images}]{notes}"
                )
        else:
            lines.append("- slides: _(无)_")
    lines.append(f"- summary: {e.summary or TBD}")
    lines.append(f"- entities: {e.entities or TBD}")
    lines.append(f"- project: {e.project or TBD}")
    return "\n".join(lines)


def _render_orphans(orphans: list[PreservedRecord]) -> str:
    if not orphans:
        return ""
    lines = ["## 已删除（archived）", ""]
    for rec in orphans:
        summary = rec.fields.get("summary", "")
        project = rec.fields.get("project", "")
        path = rec.path or "?"
        lines.append(
            f"- sha: {rec.sha} | path: {path} | project: {project} | summary: {summary}"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    repo = find_repo_root()
    raw_dir = repo / "raw"
    index_path = repo / "INDEX.md"

    if not raw_dir.exists():
        print(f"raw/ not found at {raw_dir}", file=sys.stderr)
        return 1

    preserved = _parse_existing_index(index_path)
    by_sha = {rec.sha: rec for rec in preserved}
    by_path: dict[str, PreservedRecord] = {}
    for rec in preserved:
        if rec.path:
            by_path.setdefault(rec.path, rec)

    files = sorted(
        [p for p in raw_dir.rglob("*") if p.is_file() and is_supported(p)],
        key=lambda p: p.name.lower(),
    )

    entries: list[IndexEntry] = []
    claimed: set[str] = set()  # sha of preserved records that got migrated
    migrated = 0

    for p in files:
        meta = file_meta(p)
        structure = _scan_one(p)
        if structure is None:
            continue
        rel = relpath(p, repo)

        rec = by_sha.get(meta.sha)
        if rec is None:
            old = by_path.get(rel)
            if old is not None and _has_filled_fields(old.fields):
                rec = old
                migrated += 1
        if rec is not None:
            claimed.add(rec.sha)
            fields = rec.fields
        else:
            fields = {}

        entries.append(
            IndexEntry(
                meta=meta,
                structure=structure,
                summary=fields.get("summary", TBD),
                entities=fields.get("entities", TBD),
                project=fields.get("project", TBD),
                relpath=rel,
            )
        )

    orphans = [
        rec
        for rec in preserved
        if rec.sha not in claimed and _has_filled_fields(rec.fields)
    ]

    header = [
        "# 文档索引",
        "",
        "> 本文件由 `tools/scan_index.py` 生成；"
        "summary/entities/project 字段在被首次问到时由 Claude 写回（懒填充）。",
        "> 可重复运行 `uv run scan-index` —— 已填充字段会按 sha 保留。",
        "",
        f"_共 {len(entries)} 份文档；支持类型：{', '.join(sorted(SUPPORTED_EXTS))}_",
        "",
    ]

    body_chunks: list[str] = []
    orphan_block = _render_orphans(orphans)
    if orphan_block:
        body_chunks.append(orphan_block)

    for i, e in enumerate(entries, start=1):
        body_chunks.append(_render_entry(i, e))
        body_chunks.append("")

    output = "\n".join(header) + "\n" + "\n".join(body_chunks).rstrip() + "\n"
    index_path.write_text(output, encoding="utf-8")
    note = f" · migrated {migrated} by path" if migrated else ""
    print(
        f"wrote {index_path} · {len(entries)} entries · {len(orphans)} archived{note}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
