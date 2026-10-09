---
name: Read EDA Lab Doc
description: This skill should be used when the user asks to "read lab doc", "open EDA user guide", "show DBTCL lab", "read Innovus user guide chapter", "list chapters in [filename]", "show me Module [N] of DBTCL labs", "read section dbGet basics", "what's in example_lab_doc.md", "open example_ug", "读取实验文档", "显示用户指南章节", "查看 lab 文档", "列出文档章节", "读取 Innovus UG 章节", or wants to browse and load specific chapters from large EDA PDF-converted User Guide or Lab documents. This skill handles progressive chapter-by-chapter access to documents in knowledge/processed_eda/ to avoid loading entire large files into context. Use this skill whenever the user references EDA lab exercises, User Guide modules, or wants to read content from processed PDF documents — even if they don't explicitly say "lab doc".
version: 0.4.0
---

> **Public notice (ChipCockpit open release):** `knowledge/processed_eda/` is **not**
> shipped in this repository. Vendor manuals and lab PDFs must stay in a private
> workspace under your license. The navigation steps below apply only when you
> have built a private corpus locally.

# Read EDA Lab Doc

Load chapters from large EDA User Guide / Lab documents stored in `knowledge/processed_eda/`.
These files are converted from PDF and can be thousands of lines long — never load them entirely.
This skill uses a **hierarchical folder structure** for progressive disclosure. The depth of the
hierarchy mirrors the TOC depth of each document (2, 3, 4, or more levels).

## When to Use This Skill

Use this skill when:
- User asks what documents or chapters are available in the processed EDA knowledge base
- User wants to read a specific module, lab, section, or subsection from a User Guide
- User references a file like `example_lab_doc.md` or `example_ug.md`
- User asks about a specific EDA command or concept and needs the User Guide explanation

**Do not** use this skill for `knowledge/expert_base/` documents — those use `list-expert-topics` + `read-expert-doc`.

---

## Lookup Flow

Every query follows this deterministic path. Stop at the earliest step that fully answers
the question — only go deeper when the user explicitly needs more detail.

```
User query
    │
    ▼
Step 1: processed_eda/_global_index.md        (route to manual)
    │   identify manual → <doc_name>/_summary.md
    ▼
Step 2: processed_eda/<doc_name>/_summary.md  (chapter table + FAQ)
    │   identify chapter → <doc_name>/NN_slug/
    ▼
Step 3+: Descend the hierarchy (repeat until detail file reached)
    │   Read _summary.md at current level.
    │   ┌─ Contains "## Sub-Folders" → one more subfolder level exists
    │   │     Pick the most relevant subfolder, read its _summary.md (repeat Step 3)
    │   └─ Contains "## Sub-Files"   → leaf level reached
    │         Pick the most relevant detail_*.md, proceed to Step 4
    ▼
Step 4: processed_eda/<...>/detail_<slug>.md  (100–500 lines — full content)
```

**Key decision signal**: Every `_summary.md` file ends with either `## Sub-Folders` or
`## Sub-Files`. This tells you whether to go one level deeper or read a detail file next.

---

### Step 1: Read the Global Index

```
$CLAUDE_PLUGIN_ROOT/knowledge/processed_eda/_global_index.md
```

This file lists all available EDA manuals with title, description, folder path, and chapter count.
Identify which manual the user's query relates to. Note the `Folder` and `Manual summary` path.

If the query is ambiguous or the user has not specified a manual, list the available manuals
(titles + descriptions) and ask the user to choose. Do not proceed to Step 2 until a manual
is identified.

**Graceful degradation**: if `_global_index.md` does not exist, fall back to the **Old Lookup
Flow** described at the end of this skill.

---

### Step 2: Read the Manual Summary

```
$CLAUDE_PLUGIN_ROOT/knowledge/processed_eda/<doc_name>/_summary.md
```

This file contains:
- **Chapters table** — folder name, chapter title, immediate sub-items for each chapter
- **Max depth** — the number of folder levels in this document's hierarchy
- **Purpose** — 2–3 sentence description of the manual
- **Quick FAQ Pointers** — topic → chapter folder mappings

Use the Chapters table and FAQ Pointers to identify the target chapter folder.

**Stop here if:**
- The user asked for a chapter list or overview → return the Chapters table directly.
- No specific chapter is identified yet → present the Chapters table and ask the user to choose.

Otherwise, note the target chapter folder (e.g., `05_design_planning_capabilities/`).

**Graceful degradation**: if `<doc_name>/_summary.md` does not exist, the document was converted
before this structure was built. Use the **Old Lookup Flow** for this document.

---

### Step 3+: Descend the Hierarchy (repeat as needed)

```
$CLAUDE_PLUGIN_ROOT/knowledge/processed_eda/<doc_name>/<...>/_summary.md
```

Read the `_summary.md` at the current level. This file contains:
- **TL;DR** — first ~200 words of content at this level
- **Key Topics** — bullet list of immediate sub-headings
- **Sub-Folders** or **Sub-Files** — the navigation signal

**If the file contains `## Sub-Folders`:**
The hierarchy has one more depth level at this location. The Sub-Folders table lists
subfolder names and titles. Pick the most relevant subfolder and read its `_summary.md`
(repeat this step).

**If the file contains `## Sub-Files`:**
You have reached the leaf level. The Sub-Files table maps `detail_*.md` filenames to their
content titles. Pick the most relevant file and proceed to **Step 4**.

**Stop here if:**
- The user asked for an overview of this section → return TL;DR + Key Topics.
- The user's question is answered by the TL;DR alone.

**Example depth paths:**

| Document | Path depth | Example path |
|----------|-----------|--------------|
| example_lab (2-level) | 2 | `example_lab/01_module_1/detail_lab_1_1.md` |
| example_ug (4-level) | 4 | `example_ug/02_intro/01_product_info/02_packages/detail_related_information.md` |

---

### Step 4: Read the Detail File

```
$CLAUDE_PLUGIN_ROOT/knowledge/processed_eda/<...>/detail_<slug>.md
```

Read the identified file in full. Return the content with this wrapper:

```
## <heading path: chapter > section > subsection>
**Source**: knowledge/processed_eda/<path to detail file>

<content>

---
**Parent overview**: `<parent _summary.md path>`
**Next**: <next detail file name, if any — from the Sub-Files table>
To look up a Tcl command mentioned here, ask: "search EDA command innovus <command_name>"
```

If the user's question spans multiple detail files, load the most relevant one and name the
others: "Related sections: `detail_lab_2_3.md` (pattern matching), `detail_lab_2_4.md` (results filtering)."

---

## Handling Keyword and Command Queries

When the user asks about a specific command or concept (e.g., "explain dbTransform -inst"):

1. **Step 1**: Identify the manual from `_global_index.md`.
2. **Step 2**: Use the FAQ Pointers in `_summary.md` to locate the chapter folder directly.
3. **Step 3+**: Follow the Sub-Folders/Sub-Files chain to the most relevant detail file.
4. **Step 4**: Load that detail file.

If the query matches multiple chapters, load the best-matching one and mention the others.

---

## Error Handling

| Situation | Action |
|-----------|--------|
| `_global_index.md` not found | Fall back to Old Lookup Flow |
| `<doc_name>/_summary.md` not found | Document uses old format — use Old Lookup Flow |
| `_summary.md` has `Sub-Folders` but subfolder is missing | List folder contents with Glob and ask user to choose |
| `_summary.md` has `Sub-Files` but detail file is missing | Re-read `_summary.md` Sub-Files table and pick closest match |
| Hierarchy is deeper than expected | Continue reading `_summary.md` at each level until `Sub-Files` is found |
| No manual matches query | List all manuals from `_global_index.md` and ask user to choose |

---

## Old Lookup Flow (Graceful Degradation)

Use this flow when `_global_index.md` or a document's `_summary.md` does not exist
(i.e., the document was converted before the hierarchical structure was introduced).

### Old Step 1: Read the Top-Level Index

```
$CLAUDE_PLUGIN_ROOT/knowledge/INDEX.md
```

Lists EDA tools and their processed UG index paths. Identify the tool, note the **Processed UG Index** path.

### Old Step 2: Read the Document Overview Index

```
$CLAUDE_PLUGIN_ROOT/knowledge/processed_eda/INDEX.md
```

Lists all documents with Title, Description, and **Latest Version Index** path.
Identify the document; note the version index path. If ambiguous, list documents and ask.

### Old Step 3: Read the Per-Document Chapter Index

```
$CLAUDE_PLUGIN_ROOT/knowledge/processed_eda/<doc_name>/<version>/INDEX.md
```

Contains **Source file**, **Total Lines**, and **Chapters** (`Line N: chapter title`).
Identify the target chapter and its start line. If not specified, present the list and ask.

### Old Step 4: Load the Chapter by Line Offset

```
file: $CLAUDE_PLUGIN_ROOT/knowledge/processed_eda/<doc_name>/<version>/<doc_name>.md
offset: <start_line>
limit: <end_line - start_line + 1>
```

Where `end_line` = next chapter's start line − 1 (or total lines for the last chapter).

Return content with attribution:
```
## Chapter: <title>
**Source**: knowledge/processed_eda/<doc_name>/<version>/<doc_name>.md (lines N–M)

<chapter content>

---
**Next chapter**: <next chapter title> (line N)
To look up a Tcl command mentioned here, ask: "search EDA command innovus <command_name>"
```

---

## Design Principle

This skill uses a **static file hierarchy** instead of dynamic scanning or line-offset arithmetic:

- Each file in the hierarchy is small and purposeful (30–500 lines)
- Reading stops as soon as the question is answered — no over-loading
- The `## Sub-Folders` vs `## Sub-Files` signal in each `_summary.md` tells you exactly how
  deep to go — no guessing, no hardcoded depth assumptions
- The hierarchy depth mirrors the TOC depth of each document exactly
- Graceful degradation ensures backward compatibility with documents in the old format

The hierarchy is built and maintained by the `pdf-to-markdown` skill (Step 7) whenever a
document is converted or re-converted.
