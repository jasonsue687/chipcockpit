#!/usr/bin/env python3
"""
build_knowledge_base.py — Step 7 of pdf-to-markdown skill

Converts a processed EDA Markdown file into the hierarchical knowledge base.
The depth of the output folder hierarchy mirrors the depth of the TOC exactly:
  - TOC L1 → chapter folder (NN_slug/)
  - TOC L2 → section subfolder or detail file (leaf)
  - TOC L3 → subsection subfolder or detail file (leaf)
  - ... and so on, no depth limit

Output root: processed_eda/<doc_name>/

Usage:
    python3 build_knowledge_base.py <source.md> [--doc-name NAME] [--dry-run] [--overwrite]
"""

import argparse
import re
import sys
from pathlib import Path
from datetime import date
from typing import Optional


# ---------------------------------------------------------------------------
# Slug helpers
# ---------------------------------------------------------------------------

def slugify(text: str, max_len: int = 50) -> str:
    """Convert heading text to a filesystem-safe slug."""
    s = text.lower()
    s = re.sub(r"[:\s]+", "_", s)
    s = re.sub(r"[^a-z0-9_]", "", s)
    s = re.sub(r"_+", "_", s)
    s = s.strip("_")
    return s[:max_len]


def lab_slug(heading: str) -> str:
    """
    For headings like 'Lab 1-1  Using dbGet...' extract 'lab_1_1'.
    Falls back to slugify if pattern not found.
    """
    m = re.match(r"(?i)lab\s+(\d+)-(\d+)", heading)
    if m:
        return f"lab_{m.group(1)}_{m.group(2)}"
    return slugify(heading)


def strip_toc_text(s: str) -> str:
    """Strip markdown bold/italic markers and normalize whitespace."""
    s = re.sub(r"\*+", "", s)          # remove ** and *
    s = re.sub(r"\s+", " ", s)         # collapse whitespace
    return s.strip().rstrip(":").strip()


# ---------------------------------------------------------------------------
# TOC tree extraction
# ---------------------------------------------------------------------------

def extract_toc_tree(lines: list[str]) -> dict:
    """
    Parse the '## Table of Contents' section into a tree indexed by depth.

    Returns:
        {
          "max_depth": 4,       # deepest indent level found (no artificial limit)
          "norms": {            # normalized title sets per depth
            1: {"About This Manual", "Flows", ...},
            2: {"Product and Licensing Information", ...},
            ...
          }
        }

    If no TOC section is found, returns {"max_depth": 0, "norms": {}}.
    """
    norms: dict[int, set] = {}
    max_depth = 0
    in_toc = False

    for raw in lines:
        s = raw.rstrip("\n")
        if s == "## Table of Contents":
            in_toc = True
            continue
        if in_toc:
            if re.match(r"^#+ ", s):
                break  # end of TOC section
            m = re.match(r"^( *)- (.+)", s)
            if m:
                depth = len(m.group(1)) // 2 + 1   # 2-space indent per level
                norm = strip_toc_text(m.group(2))
                if norm:
                    norms.setdefault(depth, set()).add(norm)
                    max_depth = max(max_depth, depth)

    return {"max_depth": max_depth, "norms": norms}


def matches_toc(title: str, depth: int, toc_info: dict) -> bool:
    """
    Check whether a document heading title matches any TOC entry at the given depth.

    Matching strategy (in order):
    1. Exact match (after normalization)
    2. Bidirectional prefix match — handles truncated TOC entries (lab guides)
    3. First-N-words overlap — handles minor wording differences between TOC and
       actual heading (e.g. TOC says 'Using the "." to...' but heading says 'Using "." to...')

    When a title does NOT match the TOC at its depth, the heading is dropped.
    """
    norms_at_depth = toc_info["norms"].get(depth, set())
    if not norms_at_depth:
        return True   # no TOC entries at this depth → no filtering
    h_norm = strip_toc_text(title)
    h_words = h_norm.split()

    for t in norms_at_depth:
        t_words = t.split()
        # 1. Exact
        if h_norm == t:
            return True
        # 2. Bidirectional prefix
        if h_norm.startswith(t) or t.startswith(h_norm):
            return True
        # 3. First-N-words overlap (handles minor wording divergence between TOC and body).
        #    Use n=3 words: e.g. "Lab 1-2 Using" matches regardless of what follows.
        #    This is safe because Lab/Module IDs (word 2) are unique within a document.
        n = min(3, len(h_words), len(t_words))
        if n >= 2 and h_words[:n] == t_words[:n]:
            return True

    return False


# ---------------------------------------------------------------------------
# Structure parser — produces an arbitrary-depth tree
# ---------------------------------------------------------------------------

def find_headings_in_range(
    lines: list[str],
    level: int,
    start_line: int,   # 1-indexed inclusive
    end_line: int,     # 1-indexed inclusive
    toc_info: dict,
) -> list[dict]:
    """
    Scan lines[start_line-1 : end_line] for headings at the given Markdown level
    (level=1 → '# ', level=2 → '## ', etc.).

    Filtering logic (same as current: TOC allowlist with code-block fallback):
    - If TOC norms exist at this depth:
        - TOC match → always accept (ignore code-block state)
        - No TOC match → accept only if NOT inside a code block
    - If no TOC norms at this depth: accept only if NOT inside a code block

    Returns list of {"line": int (1-indexed), "title": str}.
    """
    prefix = "#" * level + " "
    results = []
    in_code = False

    for i in range(start_line - 1, end_line):
        s = lines[i].rstrip("\n")
        if s.lstrip().startswith("```"):
            in_code = not in_code
            continue
        if s.startswith(prefix):
            title = s[len(prefix):].strip()
            toc_norms = toc_info["norms"].get(level, set())
            if toc_norms:
                # TOC exists at this depth → strict allowlist only.
                # Non-matching headings (Tcl comments, log lines, incomplete TOC entries)
                # are silently dropped. This is intentional: if a chapter/section is not
                # referenced in the TOC, it is not navigable via progressive disclosure.
                accept = matches_toc(title, level, toc_info)
            else:
                # No TOC entries at this depth → code-block gating
                accept = not in_code
            if accept:
                results.append({"line": i + 1, "title": title})

    return results


def parse_structure_tree(lines: list[str], toc_info: dict) -> list[dict]:
    """
    Parse the source file into an arbitrary-depth tree that mirrors the TOC depth.

    Node schema (recursive):
        {
          "number": int,       # 1-based index within its parent
          "line": int,         # 1-indexed start line (the heading line itself)
          "end_line": int,     # 1-indexed inclusive last line of this node's content
          "title": str,
          "children": [...]    # empty list if leaf
        }

    Depth 1 nodes = L1 chapters (H1 headings).
    Depth 2 nodes = L2 sections (H2 headings inside a chapter).
    ... etc., up to toc_info["max_depth"].
    """
    max_depth = max(toc_info["max_depth"], 1)
    total = len(lines)

    def build_level(depth: int, start: int, end: int) -> list[dict]:
        """Recursively build nodes at `depth` within [start, end] (1-indexed)."""
        if depth > max_depth:
            return []

        raw = find_headings_in_range(lines, depth, start, end, toc_info)

        # Depth-1 special filtering
        if depth == 1:
            # When TOC norms exist at L1, the document title is filtered out by
            # matches_toc() (it won't be in the TOC entries list). Only apply the
            # "skip first" heuristic when there is NO TOC (empty norms at depth 1).
            toc_l1 = toc_info["norms"].get(1, set())
            if not toc_l1 and raw:
                raw = raw[1:]   # no TOC → skip doc title by position
            # Skip "Table of Contents" heading (may still appear without TOC filter)
            raw = [h for h in raw if h["title"] != "Table of Contents"]

        nodes = []
        for idx, h in enumerate(raw):
            h_end = raw[idx + 1]["line"] - 2 if idx + 1 < len(raw) else end
            children = build_level(depth + 1, h["line"] + 1, h_end)
            nodes.append({
                "number": idx + 1,
                "line": h["line"],
                "end_line": h_end,
                "title": h["title"],
                "children": children,
            })
        return nodes

    return build_level(1, 1, total)


# ---------------------------------------------------------------------------
# Source path layout inference
# ---------------------------------------------------------------------------

def infer_source_layout(source_path: Path) -> tuple:
    """
    Support two source file location patterns:

    1. With version subfolder:   .../processed_eda/<doc>/<version>/<doc>.md
       e.g. example_ug/unknown/example_ug.md
    2. Without version subfolder: .../processed_eda/<doc>/<doc>.md
       e.g. example_lab_doc/example_lab_doc.md

    Returns: (doc_name, version, processed_eda_dir, output_root)
    """
    stem = source_path.stem
    parent_name = source_path.parent.name

    if stem == parent_name:
        # No version subfolder
        doc_name = parent_name
        version = ""
        processed_eda_dir = source_path.parent.parent
        output_root = source_path.parent
    else:
        # Has version subfolder
        doc_name = source_path.parent.parent.name
        version = parent_name
        processed_eda_dir = source_path.parent.parent.parent
        output_root = processed_eda_dir / doc_name

    return doc_name, version, processed_eda_dir, output_root


def source_ref(doc_name: str, version: str) -> str:
    """Return a human-readable source path for comments and headers."""
    if version:
        return f"{doc_name}/{version}/{doc_name}.md"
    return f"{doc_name}/{doc_name}.md"


# ---------------------------------------------------------------------------
# File content builders
# ---------------------------------------------------------------------------

def build_detail_header(sref: str, sub_start: int, sub_end: int, doc_name: str, version: str) -> str:
    img_base = f"processed_eda/{doc_name}/{version}/" if version else f"processed_eda/{doc_name}/"
    return (
        f"<!-- Source: {sref}, lines {sub_start}–{sub_end} -->\n"
        f"<!-- Image paths are relative to: {img_base} -->\n\n"
    )


def build_tldr(node_lines: list[str]) -> str:
    """
    Extract up to 200 words of meaningful text from node_lines (skipping
    the heading line itself, code blocks, and stopping at the second sub-heading).
    """
    tldr_lines = []
    word_count = 0
    in_code = False
    hit_first_sub = False

    for raw in node_lines[1:]:   # skip heading line
        s = raw.rstrip("\n")
        if s.startswith("```"):
            in_code = not in_code
        if in_code:
            continue
        if re.match(r"^#{2,} ", s):
            if hit_first_sub:
                break
            hit_first_sub = True
            continue
        if re.match(r"^# ", s):
            break
        tldr_lines.append(s)
        word_count += len(s.split())
        if word_count >= 200:
            break

    return "\n".join(tldr_lines).strip()


def build_node_summary(
    node: dict,
    sref: str,
    depth: int,
    parent_title: str,
    raw_lines: list[str],
    is_leaf: bool,
) -> str:
    """
    Build _summary.md content for a node at any depth.

    - Non-leaf: has children that become subfolders → uses '## Sub-Folders' table
    - Leaf: children become detail_*.md files → uses '## Sub-Files' table
    """
    title = node["title"]
    start = node["line"]
    end = node["end_line"]
    node_lines = raw_lines[start - 1: end]

    tldr = build_tldr(node_lines)

    # Key Topics
    topics = "\n".join(f"- {c['title']}" for c in node["children"]) or "- (no sub-sections)"

    # Sub-Folders or Sub-Files table
    if not node["children"]:
        nav_section = "_No sub-sections (single detail_overview.md)_"
    elif is_leaf:
        # children → detail files
        rows = []
        for c in node["children"]:
            fname = f"detail_{lab_slug(c['title'])}.md"
            rows.append(f"| `{fname}` | {c['title'][:60]} |")
        nav_section = "## Sub-Files\n\n| File | Content |\n|------|---------|\n" + "\n".join(rows)
    else:
        # children → subfolders
        rows = []
        for c in node["children"]:
            folder = f"{c['number']:02d}_{slugify(c['title'])}/"
            rows.append(f"| `{folder}` | {c['title'][:60]} |")
        nav_section = "## Sub-Folders\n\n| Folder | Title |\n|--------|-------|\n" + "\n".join(rows)

    depth_label = "Chapter" if depth == 1 else "Section" if depth == 2 else f"Level-{depth}"
    parent_info = f"\n**Parent**: {parent_title}" if parent_title else ""

    return f"""# {title}

**Source**: `{sref}`, lines {start}–{end}{parent_info}

## TL;DR

{tldr}

## Key Topics

{topics}

{nav_section}
"""


def build_manual_summary(
    doc_title: str,
    sref: str,
    chapters: list[dict],
    today: str,
    max_depth: int,
) -> str:
    """Manual-level _summary.md with chapter table."""
    rows = []
    for ch in chapters:
        folder = f"{ch['number']:02d}_{slugify(ch['title'])}/"
        if ch["children"]:
            # Show immediate children (subfolders or detail files)
            children_leaf = all(not c["children"] for c in ch["children"])
            if children_leaf or max_depth <= 2:
                sub_items = ", ".join(
                    f"detail_{lab_slug(c['title'])}.md" for c in ch["children"]
                ) or "detail_overview.md"
            else:
                sub_items = ", ".join(
                    f"{c['number']:02d}_{slugify(c['title'])}/" for c in ch["children"]
                )
        else:
            sub_items = "detail_overview.md"
        rows.append(f"| `{folder}` | {ch['title'][:60]} | {sub_items} |")

    table = "| Folder | Title | Sub-Items |\n|--------|-------|----------|\n" + "\n".join(rows)

    faq_items = []
    for ch in chapters[:5]:
        topic_hint = ch["title"].split(":")[1].strip() if ":" in ch["title"] else ch["title"]
        folder = f"{ch['number']:02d}_{slugify(ch['title'])}/"
        faq_items.append(f"- To learn about {topic_hint[:50]} → read `{folder}`")
    faq = "\n".join(faq_items)

    return f"""# {doc_title}

**Source**: `{sref}`
**Chapters**: {len(chapters)}
**Max depth**: {max_depth}
**Converted**: {today}

## Chapters

{table}

## Purpose

<!-- TODO: fill 2-3 sentence description of what this document covers -->

## Quick FAQ Pointers

{faq}
"""


def build_global_index_entry(doc_name: str, title: str, num_chapters: int) -> str:
    return f"""## {doc_name}

**Title**: {title}
**Description**: <!-- TODO: fill description -->
**Folder**: `{doc_name}/`
**Manual summary**: `{doc_name}/_summary.md`
**Chapters**: {num_chapters}
"""


# ---------------------------------------------------------------------------
# Recursive file generation
# ---------------------------------------------------------------------------

def generate_node_files(
    node: dict,
    node_dir: Path,
    depth: int,
    max_depth: int,
    raw_lines: list[str],
    sref: str,
    doc_name: str,
    version: str,
    parent_title: str,
    processed_eda_dir: Path,
    write_file_fn,
) -> None:
    """
    Recursively generate files for a node.

    Decision rule:
      - A node's children become SUBFOLDERS if they themselves have children
        (i.e., they are not leaves in the tree).
      - A node's children become DETAIL FILES if they are leaves (no children).
      - If the node itself has no children, write a single detail_overview.md.
    """
    node_lines = raw_lines[node["line"] - 1: node["end_line"]]

    if not node["children"]:
        # Leaf node: single detail_overview.md
        content = build_detail_header(sref, node["line"], node["end_line"], doc_name, version)
        content += "".join(node_lines)
        write_file_fn(node_dir / "detail_overview.md", content)
        return

    # Determine if children are themselves leaves
    children_are_leaves = all(not c["children"] for c in node["children"])

    if children_are_leaves:
        # Children → detail_*.md files in the current node_dir.
        # Deduplicate filenames: if two children produce the same slug, append _N.
        seen_names: dict[str, int] = {}
        for child in node["children"]:
            child_lines = raw_lines[child["line"] - 1: child["end_line"]]
            base_slug = lab_slug(child["title"])
            if base_slug in seen_names:
                seen_names[base_slug] += 1
                fname = f"detail_{base_slug}_{seen_names[base_slug]}.md"
            else:
                seen_names[base_slug] = 1
                fname = f"detail_{base_slug}.md"
            content = build_detail_header(sref, child["line"], child["end_line"], doc_name, version)
            content += "".join(child_lines)
            write_file_fn(node_dir / fname, content)

        # _summary.md: Sub-Files
        summary = build_node_summary(
            node, sref, depth, parent_title, raw_lines, is_leaf=True
        )
        write_file_fn(node_dir / "_summary.md", summary)

    else:
        # Children → subfolders (recursion)
        seen_dirs: dict[str, int] = {}
        for child in node["children"]:
            base_dir_name = f"{child['number']:02d}_{slugify(child['title'])}"
            if base_dir_name in seen_dirs:
                seen_dirs[base_dir_name] += 1
                child_dir_name = f"{base_dir_name}_{seen_dirs[base_dir_name]}"
            else:
                seen_dirs[base_dir_name] = 1
                child_dir_name = base_dir_name
            child_dir = node_dir / child_dir_name
            generate_node_files(
                child, child_dir, depth + 1, max_depth,
                raw_lines, sref, doc_name, version,
                node["title"], processed_eda_dir, write_file_fn,
            )

        # _summary.md: Sub-Folders
        summary = build_node_summary(
            node, sref, depth, parent_title, raw_lines, is_leaf=False
        )
        write_file_fn(node_dir / "_summary.md", summary)


# ---------------------------------------------------------------------------
# Main build logic
# ---------------------------------------------------------------------------

def build(source_path: Path, doc_name_override: Optional[str], dry_run: bool, overwrite: bool) -> None:
    doc_name, version, processed_eda_dir, output_root = infer_source_layout(source_path)
    if doc_name_override:
        doc_name = doc_name_override
        output_root = processed_eda_dir / doc_name

    sref = source_ref(doc_name, version)
    global_index_path = processed_eda_dir / "_global_index.md"

    print(f"Source  : {source_path}")
    print(f"Doc name: {doc_name}  |  Version: {version or '(none)'}")
    print(f"Output  : {output_root}")
    print()

    raw_lines = source_path.read_text(encoding="utf-8").splitlines(keepends=True)
    total_lines = len(raw_lines)
    print(f"Source file: {total_lines} lines")

    # Extract document title (first # heading)
    doc_title = ""
    for line in raw_lines:
        if re.match(r"^# ", line):
            doc_title = line[2:].strip()
            break

    # Parse TOC and structure
    toc_info = extract_toc_tree(raw_lines)
    print(f"TOC depth: {toc_info['max_depth']}  |  Depths: "
          + ", ".join(f"L{d}={len(toc_info['norms'].get(d,set()))}" for d in range(1, toc_info['max_depth']+1)))

    chapters = parse_structure_tree(raw_lines, toc_info)
    max_depth = toc_info["max_depth"] or 1

    print(f"Chapters found: {len(chapters)}")
    for ch in chapters:
        def count_tree(nodes):
            return sum(1 + count_tree(c["children"]) for c in nodes)
        total_nodes = count_tree(ch["children"])
        print(f"  Ch{ch['number']:02d} line={ch['line']:6d}  {len(ch['children'])} direct children"
              f"  ({total_nodes} total sub-nodes)  {ch['title'][:60]}")
    print()

    # When --overwrite is set, remove stale chapter subfolders from any previous build
    # so that old detail files from a different depth structure don't persist.
    if overwrite and not dry_run and output_root.exists():
        import shutil
        for item in output_root.iterdir():
            # Remove NN_slug chapter folders; preserve source files (*.md in root, images/)
            if item.is_dir() and re.match(r"^\d{2}_", item.name):
                shutil.rmtree(item)
                print(f"  [CLEAN] removed stale folder {item.relative_to(processed_eda_dir)}/")
        print()

    files_written = 0
    files_skipped = 0

    def write_file(path: Path, content: str) -> None:
        nonlocal files_written, files_skipped
        if dry_run:
            print(f"  [DRY-RUN] would write {path.relative_to(processed_eda_dir)}")
            files_written += 1
            return
        if path.exists() and not overwrite:
            print(f"  [SKIP] {path.relative_to(processed_eda_dir)} (already exists)")
            files_skipped += 1
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        print(f"  [WRITE] {path.relative_to(processed_eda_dir)}")
        files_written += 1

    today = date.today().isoformat()

    # Generate chapter folders and files
    for ch in chapters:
        ch_folder_name = f"{ch['number']:02d}_{slugify(ch['title'])}"
        ch_dir = output_root / ch_folder_name

        generate_node_files(
            ch, ch_dir, depth=1, max_depth=max_depth,
            raw_lines=raw_lines, sref=sref,
            doc_name=doc_name, version=version,
            parent_title="",
            processed_eda_dir=processed_eda_dir,
            write_file_fn=write_file,
        )

    # Manual-level _summary.md
    manual_summary = build_manual_summary(doc_title, sref, chapters, today, max_depth)
    write_file(output_root / "_summary.md", manual_summary)

    # Update _global_index.md
    if not dry_run:
        if global_index_path.exists():
            existing = global_index_path.read_text(encoding="utf-8")
            marker = "<!-- New document entries are appended here"
            entry = build_global_index_entry(doc_name, doc_title, len(chapters))
            if f"## {doc_name}" in existing:
                pattern = rf"## {re.escape(doc_name)}\n.*?(?=\n## |\n<!--|$)"
                existing = re.sub(pattern, entry.strip(), existing, flags=re.DOTALL)
                global_index_path.write_text(existing, encoding="utf-8")
                print(f"  [UPDATE] _global_index.md (updated {doc_name} entry)")
            else:
                if marker in existing:
                    existing = existing.replace(marker, entry + "\n---\n\n" + marker)
                else:
                    existing = existing.rstrip() + "\n\n---\n\n" + entry
                global_index_path.write_text(existing, encoding="utf-8")
                print(f"  [UPDATE] _global_index.md (appended {doc_name} entry)")
        else:
            header = (
                "# EDA Processed Documents — Global Index\n\n"
                "> Maintained by pdf-to-markdown skill. Lists all converted EDA manuals.\n"
                "> Read this file as the first step when routing any user query to a manual.\n\n"
                "---\n\n"
            )
            entry = build_global_index_entry(doc_name, doc_title, len(chapters))
            global_index_path.write_text(header + entry, encoding="utf-8")
            print(f"  [CREATE] _global_index.md")
    else:
        print(f"  [DRY-RUN] would update _global_index.md")

    print()
    print("=" * 60)
    print(f"Done.  Files written: {files_written}  |  Skipped: {files_skipped}")
    print(f"Hierarchical KB root: {output_root}")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build hierarchical knowledge base from a processed EDA Markdown file."
    )
    parser.add_argument("source", help="Path to the source .md file")
    parser.add_argument("--doc-name", help="Override document name")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be written, but don't create any files")
    parser.add_argument("--overwrite", action="store_true",
                        help="Overwrite existing files (default: skip)")
    args = parser.parse_args()

    source_path = Path(args.source).resolve()
    if not source_path.exists():
        print(f"ERROR: source file not found: {source_path}", file=sys.stderr)
        sys.exit(1)

    build(source_path, args.doc_name, dry_run=args.dry_run, overwrite=args.overwrite)


if __name__ == "__main__":
    main()
