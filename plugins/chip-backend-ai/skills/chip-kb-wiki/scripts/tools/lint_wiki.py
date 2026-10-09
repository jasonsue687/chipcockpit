"""Lint the wiki/ knowledge base for citation / index / freshness problems.

Usage:
    uv run tools/lint_wiki.py

Exit codes:
    0 - clean
    1 - warnings only
    2 - errors (broken / undefined citations or index drift)

Checks:
  ERROR
    broken_citation       link def [label]: <path> with non-existent target
    undefined_inline      inline [doc_NNN§...] with no matching link def in the same file
    index_drift           wiki/{projects,entities}/*.md vs wiki/index.md mismatch (both directions)
  WARN
    stale_citation        wiki/sources/<doc>.md frontmatter source_sha != current parsed/<file>/_meta.json sha
    orphan_source         parsed/<dir>/ exists but no wiki/sources/<doc>.md references it
  INFO
    ambiguous_project     wiki/projects/_candidates.md entry older than 7 days
    contradicting_facts   entities/<e>.md has same labelled fact with different numeric values
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

from tools.handlers.common import PARSED_ROOT_NAME, find_repo_root


FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
FM_KV_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.+?)\s*$")
LINK_DEF_RE = re.compile(r"^\[([^\]]+)\]:\s+(\S+)\s*$", re.MULTILINE)
INLINE_CITE_RE = re.compile(r"\[(doc_\d+(?:§[\w-]+|/[\w\-.]+))\]")
INDEX_LINK_RE = re.compile(r"^- \[[^\]]+\]\((projects|entities)/([^)]+)\)", re.MULTILINE)
NUMBER_FACT_RE = re.compile(
    r"^\s*-\s*(?P<label>[^:：\[]+?)\s*[:：]\s*(?P<value>[\d.]+\s*[a-zA-Zµμ%²/]+)\s*\["
)
LOG_DATE_RE = re.compile(r"## \[(\d{4}-\d{2}-\d{2})\]")


def parse_frontmatter(text: str) -> dict[str, str]:
    m = FM_RE.match(text)
    if not m:
        return {}
    out: dict[str, str] = {}
    for line in m.group(1).splitlines():
        kv = FM_KV_RE.match(line)
        if kv:
            out[kv.group(1)] = kv.group(2).strip()
    return out


def body_after_frontmatter(text: str) -> str:
    m = FM_RE.match(text)
    return text[m.end():] if m else text


def find_wiki_pages(wiki_root: Path) -> list[Path]:
    out = []
    for p in sorted(wiki_root.rglob("*.md")):
        if "_templates" in p.parts:
            continue
        out.append(p)
    return out


def relpath(p: Path, root: Path) -> str:
    try:
        return str(p.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(p)


# ---------- checks ----------

def check_broken_and_undefined(
    wiki_root: Path, repo_root: Path, errors: list
) -> None:
    for page in find_wiki_pages(wiki_root):
        text = page.read_text(encoding="utf-8")
        defs = {m.group(1): m.group(2) for m in LINK_DEF_RE.finditer(text)}

        # broken: defined links whose targets do not exist
        for label, target in defs.items():
            if not label.startswith("doc_"):
                continue  # only citation labels are validated here
            target_path = (page.parent / target).resolve()
            if not target_path.exists():
                errors.append(
                    (
                        "ERROR",
                        "broken_citation",
                        f"{relpath(page, repo_root)}: [{label}] -> {target} (target missing)",
                    )
                )

        # undefined inline: cite used in body but no matching def
        body = body_after_frontmatter(text)
        # strip the link-def block so it isn't counted as inline use
        body_no_defs = LINK_DEF_RE.sub("", body)
        used = {m.group(1) for m in INLINE_CITE_RE.finditer(body_no_defs)}
        for label in sorted(used):
            if label not in defs:
                errors.append(
                    (
                        "ERROR",
                        "undefined_inline",
                        f"{relpath(page, repo_root)}: [{label}] used inline but no link def",
                    )
                )


def check_index_drift(wiki_root: Path, repo_root: Path, errors: list) -> None:
    index_path = wiki_root / "index.md"
    if not index_path.exists():
        errors.append(("ERROR", "index_drift", "wiki/index.md missing"))
        return
    text = index_path.read_text(encoding="utf-8")
    indexed = {f"{m.group(1)}/{m.group(2)}" for m in INDEX_LINK_RE.finditer(text)}

    actual = set()
    for kind in ("projects", "entities"):
        d = wiki_root / kind
        if d.exists():
            for p in d.glob("*.md"):
                if p.name.startswith("_"):
                    continue  # _candidates.md is excluded from index
                actual.add(f"{kind}/{p.name}")

    for m in sorted(actual - indexed):
        errors.append(
            ("ERROR", "index_drift", f"wiki/{m} exists but not listed in wiki/index.md")
        )
    for m in sorted(indexed - actual):
        errors.append(
            ("ERROR", "index_drift", f"wiki/index.md references wiki/{m} but file missing")
        )


def check_stale_citations(wiki_root: Path, repo_root: Path, warnings: list) -> None:
    sources_dir = wiki_root / "sources"
    if not sources_dir.exists():
        return
    for src_page in sorted(sources_dir.glob("*.md")):
        fm = parse_frontmatter(src_page.read_text(encoding="utf-8"))
        recorded_sha = fm.get("source_sha")
        parsed_dir_field = fm.get("parsed_dir")
        if not recorded_sha or not parsed_dir_field:
            warnings.append(
                (
                    "WARN",
                    "stale_citation",
                    f"{relpath(src_page, repo_root)}: frontmatter missing source_sha or parsed_dir",
                )
            )
            continue
        meta_path = repo_root / parsed_dir_field.rstrip("/") / "_meta.json"
        if not meta_path.exists():
            warnings.append(
                (
                    "WARN",
                    "stale_citation",
                    f"{relpath(src_page, repo_root)}: parsed/_meta.json missing ({parsed_dir_field}); run parse_doc",
                )
            )
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception as e:
            warnings.append(
                (
                    "WARN",
                    "stale_citation",
                    f"{relpath(src_page, repo_root)}: _meta.json parse failed: {e}",
                )
            )
            continue
        current_sha = meta.get("sha")
        if current_sha and recorded_sha != current_sha:
            warnings.append(
                (
                    "WARN",
                    "stale_citation",
                    f"{relpath(src_page, repo_root)}: source_sha={recorded_sha} != current parsed sha={current_sha}; needs re-ingest",
                )
            )


def check_orphan_sources(wiki_root: Path, repo_root: Path, warnings: list) -> None:
    parsed_root = repo_root / PARSED_ROOT_NAME
    if not parsed_root.exists():
        return
    sources_dir = wiki_root / "sources"
    referenced = set()
    if sources_dir.exists():
        for src_page in sources_dir.glob("*.md"):
            fm = parse_frontmatter(src_page.read_text(encoding="utf-8"))
            pd = fm.get("parsed_dir", "").rstrip("/")
            if pd:
                referenced.add(pd)
    for parsed_dir in sorted(parsed_root.iterdir()):
        if not parsed_dir.is_dir():
            continue
        rel = f"{PARSED_ROOT_NAME}/{parsed_dir.name}"
        if rel not in referenced:
            warnings.append(
                ("WARN", "orphan_source", f"{rel}: parsed but no matching wiki/sources/<doc>.md")
            )


def check_ambiguous_project(wiki_root: Path, repo_root: Path, infos: list) -> None:
    candidates = wiki_root / "projects" / "_candidates.md"
    if not candidates.exists():
        return
    text = candidates.read_text(encoding="utf-8")
    today = date.today()
    for m in LOG_DATE_RE.finditer(text):
        try:
            d = date.fromisoformat(m.group(1))
        except ValueError:
            continue
        age = (today - d).days
        if age > 7:
            infos.append(
                (
                    "INFO",
                    "ambiguous_project",
                    f"wiki/projects/_candidates.md: entry dated {d} unresolved for {age} days",
                )
            )


def check_contradicting_facts(wiki_root: Path, repo_root: Path, infos: list) -> None:
    entities_dir = wiki_root / "entities"
    if not entities_dir.exists():
        return
    for page in sorted(entities_dir.glob("*.md")):
        text = body_after_frontmatter(page.read_text(encoding="utf-8"))
        seen: dict[str, set[str]] = defaultdict(set)
        for line in text.splitlines():
            m = NUMBER_FACT_RE.match(line)
            if m:
                label = m.group("label").strip().lower()
                value = re.sub(r"\s+", "", m.group("value")).lower()
                seen[label].add(value)
        for label, vals in seen.items():
            if len(vals) > 1:
                infos.append(
                    (
                        "INFO",
                        "contradicting_facts",
                        f"{relpath(page, repo_root)}: '{label}' has {len(vals)} different values: {sorted(vals)}",
                    )
                )


# ---------- main ----------

def main() -> int:
    repo_root = find_repo_root()
    wiki_root = repo_root / "wiki"
    if not wiki_root.exists():
        print("wiki/ does not exist; nothing to lint", file=sys.stderr)
        return 0

    errors: list[tuple[str, str, str]] = []
    warnings: list[tuple[str, str, str]] = []
    infos: list[tuple[str, str, str]] = []

    check_broken_and_undefined(wiki_root, repo_root, errors)
    check_index_drift(wiki_root, repo_root, errors)
    check_stale_citations(wiki_root, repo_root, warnings)
    check_orphan_sources(wiki_root, repo_root, warnings)
    check_ambiguous_project(wiki_root, repo_root, infos)
    check_contradicting_facts(wiki_root, repo_root, infos)

    print("# wiki lint report")
    print(f"errors:   {len(errors)}")
    print(f"warnings: {len(warnings)}")
    print(f"infos:    {len(infos)}")
    print()

    if not (errors or warnings or infos):
        print("✓ all clean")
        return 0

    by_kind: dict[tuple[str, str], list[str]] = defaultdict(list)
    for level, kind, msg in errors + warnings + infos:
        by_kind[(level, kind)].append(msg)

    for (level, kind), msgs in sorted(by_kind.items()):
        print(f"## [{level}] {kind} ({len(msgs)})")
        for m in msgs:
            print(f"  - {m}")
        print()

    if errors:
        return 2
    if warnings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
