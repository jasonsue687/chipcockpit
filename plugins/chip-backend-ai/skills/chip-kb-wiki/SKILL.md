---
name: chip-kb-wiki
description: Use this skill whenever the user wants to query, ingest into, or lint a Karpathy-style chip project document knowledge base — design docs (.docx/.xlsx/.pptx) parsed into `parsed/<file>/*.md` slices and aggregated in `wiki/sources|projects|entities/` with inline citations back to slices. Fire when the user names any chip-project document file (`ChipA_后端实现报告_v3.docx`, `ChipA_PPA_汇总.xlsx`, `ChipA_设计评审_2026-04.pptx`, `ChipB_Power_Plan_笔记.docx`, `ChipC_概念笔记.docx`, or any `Chip*_*.docx/xlsx/pptx` filename a user types); references `doc_NNN`, paths under `raw/`/`parsed/`/`wiki/sources|projects|entities/`, `wiki/index.md`, `INDEX.md`, or "Karpathy llm-wiki"; asks where a number or decision came from in a chip doc ("post-CTS skew 71ps 是哪份评审 PPT 来的", "die 4×4 mm 哪份报告写的"); says "ingest 这份 word/excel/ppt 进 wiki", "跑下 lint", "wiki 有几条 stale_citation 帮我看看"; mentions having added facts to a source page and asks whether to propagate to the project page (the compounding rule); or wants to bootstrap the same raw/parsed/wiki+INDEX layout in a new repo. Do NOT use this skill for sibling-skill territory: explaining EDA concepts in the abstract (use read-eda-concept), running an actual backend flow stage like floorplan/CTS/route in Innovus (use run-chip-flow), Tcl command syntax lookups (use search-eda-command), PDF-to-markdown conversion (use pdf-to-markdown), or listing/reading EDA User-Guide and expert docs (use list-expert-topics / read-eda-lab-doc / read-expert-doc); also skip generic python-docx, markdown-link-syntax, git, or Claude-Code-plugin-authoring questions that merely share keywords. Decisive test: is the user retrieving, extending, or validating a fact that lives inside parsed chip-project documents under citation discipline? If yes — even casually phrased without naming the skill — use this skill.
version: 0.1.0
---

# Chip Project Document Knowledge Base · Karpathy-style Wiki

A real-time-parsed, LLM-maintained multi-layer wiki for chip project documents (docx / xlsx / pptx). Inspired by Karpathy's `llm-wiki`: at ~100-document scale, navigated markdown indexes beat RAG.

## Architecture (load this picture first)

```
raw/         user-provided Word/Excel/PPT      (immutable, never Read directly)
parsed/      tools/parse_doc.py output         (atomic markdown slices = fact layer; regenerable; gitignored)
wiki/        LLM-maintained knowledge layer    (high-level views with inline citations back into parsed/)
├── index.md            multi-view directory (by-project / by-entity)
├── log.md              append-only ingest/lint timeline
├── sources/doc_NNN__<slug>.md   one page per source doc
├── projects/<id>.md             aggregated per project
├── entities/<name>.md            aggregated per entity (IP, process, chip, customer)
└── _templates/                  not in index
INDEX.md     tools/scan_index.py output, by-source machine view with lazy-filled fields
```

**Core principle: wiki gives high-level views (per project / per entity); parsed/ gives raw facts. Citations bridge them.** Never answer numeric questions from wiki summaries alone — always follow citations down to parsed/ slices.

## Prerequisites

The skill is portable — it runs in any cwd that satisfies these:

- **Python ≥ 3.11** with `python-docx`, `openpyxl`, `python-pptx` available
  ```bash
  uv pip install python-docx openpyxl python-pptx
  ```
- **A `pyproject.toml`** somewhere at or above cwd. The bundled scripts call `find_repo_root()`, which walks up looking for it; everything (`raw/`, `parsed/`, `wiki/`, `INDEX.md`) is resolved relative to that root. If the host repo doesn't have one, `Step 0 — Bootstrap` below drops in a stub.
- **The standard directory tree** (`raw/`, `parsed/`, `wiki/sources|projects|entities|_templates/`, optional `INDEX.md`). Again, `Step 0 — Bootstrap` lays this down with one command.

If any of the three is missing on a fresh repo, run bootstrap before anything else.

## The behavior contract

The skill exists to enforce a single behavior: **citation-first answers**. Every claim involving a number, a decision, or a conclusion must carry an inline citation that lints clean against the parsed/ slice it came from. The 4-step query flow, the 7-step ingest, and the lint loop all serve that one rule.

## Step 0 — Bootstrap a fresh repo (skip if `wiki/` already exists)

If cwd has no `wiki/` / `parsed/` / `pyproject.toml`, run the bundled bootstrap script before anything else. It's idempotent — re-running won't clobber existing files:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/chip-kb-wiki/scripts/bootstrap.sh             # bootstraps cwd
${CLAUDE_PLUGIN_ROOT}/skills/chip-kb-wiki/scripts/bootstrap.sh /path/to/new-repo  # bootstraps elsewhere
```

What it does:

1. `mkdir -p raw parsed wiki/{sources,projects,entities,_templates}`
2. Copies the three wiki page templates (`source.md` / `project.md` / `entity.md`) into `wiki/_templates/` (refreshed from the skill on every run so they stay in sync)
3. Seeds `wiki/index.md` and `wiki/log.md` with starter content (skipped if files already exist)
4. Drops a stub `pyproject.toml` listing `python-docx` / `openpyxl` / `python-pptx` (skipped if one exists — but verify deps are listed)
5. Appends `parsed/`, `.venv/`, `__pycache__/` etc. to `.gitignore`

After bootstrap, install deps (`uv pip install python-docx openpyxl python-pptx` or `uv sync`), drop source docs into `raw/`, then go to Step 1.

## Step 1 — Pick the right action

| User intent | Action | Section to read |
|---|---|---|
| First time in this repo, nothing set up | **Bootstrap** | Step 0 above |
| Ask a question about a chip project / doc / module | **Query** | Step 2 below |
| Drop a new file into `raw/` and want it indexed | **Ingest** | `references/ingest-workflow.md` |
| Check the wiki for broken / stale / orphan citations | **Lint** | Step 5 below |

## Step 2 — Query: the 4-step flow

This is the hot path. Follow it every time the user asks a fact question about a chip project document.

### 1. Read `wiki/index.md` first

From the by-project / by-entity views, pick 1–3 candidate wiki pages (project page, entity page, or source page). If `wiki/` is empty (not yet ingested), or the question names a specific source file, fall back to `INDEX.md`.

### 2. Read the candidate wiki pages

Each page lists key facts with inline citations. Decide whether the wiki page itself answers the question, or whether you need to drop down to parsed/ for the actual numbers.

### 3. Follow citations to `parsed/<file>/<slice>.md` (mandatory for numeric / table / decision-detail questions)

**Do not paraphrase numbers from wiki summaries.** The wiki summary is for orientation; the parsed/ slice is the source of truth. Re-read the slice and quote the figure exactly.

If the parsed/ slice doesn't exist yet (the doc was never parsed, or its sha changed), run:

```bash
uv run parse-doc raw/<file>                       # short form (registered in pyproject.toml)
# or, from a repo where the skill's bundled scripts are used:
uv run python ${CLAUDE_PLUGIN_ROOT}/skills/chip-kb-wiki/scripts/tools/parse_doc.py raw/<file>
```

stdout lists every slice path. Read only the slices relevant to the question.

### 4. Answer

State the conclusion first, then cite both the wiki page (for context) and the parsed/ slice (for the actual fact). This makes the answer auditable and lets the user dig deeper without retracing your search.

> **Compounding rule (Karpathy):** if you find a fact in parsed/ that the wiki page missed, append it to `wiki/sources/<doc-id>.md` (and to the downstream project/entity page if it changes the aggregated picture). Don't just answer — improve the wiki.

## Step 3 — Citation grammar (strong constraint)

Every factual statement carries at least one inline citation. The grammar is markdown reference-style. Full rules + anchor table are in `references/citation-grammar.md`. Quick reminders:

```
ChipA Floorplan die 4mm×4mm，PLL_top 西北角 [doc_002§2]。
post-CTS skew 71ps，目标 <80ps，buffer 1242 [doc_003§slide-4][doc_001/Timing]。

[doc_002§2]: ../../parsed/ChipA_后端实现报告_v3.docx/section-2.md
[doc_003§slide-4]: ../../parsed/ChipA_设计评审_2026-04.pptx/slides-1-5.md
[doc_001/Timing]: ../../parsed/ChipA_PPA_汇总.xlsx/sheet-Timing-full.md
```

Anchors: `§N` for docx sections, `§slide-K` / `§slides-A-B` for pptx, `/SheetName` for xlsx.

Subjective conclusions go un-cited but get a prefix `> 推断：…` or `> 待证：…` so lint and humans can tell them apart.

## Step 4 — Ingest a new document

When the user drops a new file into `raw/`, work through the 7-step procedure in `references/ingest-workflow.md`. The high-level skeleton:

1. `parse-doc raw/<file>` → grab the slice paths
2. Read slices, draft `wiki/sources/doc_NNN__<slug>.md` (frontmatter + summary + key facts, each with a citation)
3. Extract entities + numeric fingerprints; decide project attribution using the signals table in `references/attribution.md`
4. Update `wiki/projects/<id>.md` — merge new facts
5. Create / update `wiki/entities/*.md`
6. Update `wiki/index.md` (by-project / by-entity sections)
7. Append a `wiki/log.md` line: `## [YYYY-MM-DD] ingest | doc_NNN <name> → <project_id>`

Frontmatter schemas for the three wiki page types live in `references/wiki-schemas.md`. Use them — lint depends on those fields.

## Step 5 — Lint

```bash
uv run python ${CLAUDE_PLUGIN_ROOT}/skills/chip-kb-wiki/scripts/tools/lint_wiki.py
# or (in the chip-knowledge-ai repo, which registers it differently)
uv run python -m tools.lint_wiki
```

Exit codes: `0` clean, `1` warnings only, `2` errors. What gets checked:

| Level | Check | Meaning |
|---|---|---|
| ERROR | `broken_citation` | `[label]: <path>` target doesn't exist |
| ERROR | `undefined_inline` | `[doc_NNN§…]` used in body with no matching link def |
| ERROR | `index_drift` | `wiki/projects|entities/*.md` and `wiki/index.md` disagree |
| WARN | `stale_citation` | `wiki/sources/<doc>.md` frontmatter `source_sha` ≠ current `parsed/<file>/_meta.json` sha |
| WARN | `orphan_source` | `parsed/<dir>/` exists but no `wiki/sources/<doc>.md` references it |
| INFO | `ambiguous_project` | `wiki/projects/_candidates.md` entry older than 7 days |
| INFO | `contradicting_facts` | same labelled numeric fact has different values across entity-page lines |

Fix errors → fix warnings → resolve infos. Errors block; warnings flag stale state worth a quick refresh; infos surface attention areas.

## Cache invalidation

`parse_doc` uses `parsed/<file>/_meta.json` (sha + last_parsed) to detect source changes. If the source's sha differs, it purges that directory's stale slices automatically before re-parsing. **You never need to clean parsed/ manually.**

For wiki/: if `source_sha` ≠ current parsed sha, lint reports `stale_citation` — re-ingest the source page (project/entity pages only need touching when the new facts change aggregates).

## Hard prohibitions

- ❌ Don't `Read` a file under `raw/` (`.docx`/`.xlsx`/`.pptx` binaries) — always go through parsed/.
- ❌ Don't load every slice from a doc into context — read only the slices the question needs.
- ❌ Don't answer numbers from wiki summaries — always re-read the cited parsed/ slice.
- ❌ Don't use surgical parse modes (`--section`/`--sheet`/`--slides`) unless a file is genuinely huge — default to full-document parsing.
- ❌ Don't write wiki facts without inline citations — that breaks the contract and lint will catch it.
- ❌ Don't treat `> [图占位 ...]` placeholders as real image content — current parse_doc (v1) does not OCR images. Say so explicitly if asked about figures.

## Project attribution in one paragraph

`raw/` is flat by convention; project membership is inferred from multiple signals (anchor entities, entity-set Jaccard, numeric fingerprints, explicit cross-refs, filename prefixes, version stamps). Be conservative: high-confidence-with-shared-anchor merges directly; mid-confidence goes to `wiki/projects/_candidates.md` for human review; low-confidence opens a new project page. Misattribution-up-the-stack is much harder to undo than under-splitting. Full signal table and thresholds: `references/attribution.md`.

## Maintenance commands (canonical)

```bash
uv sync                                             # install/sync deps
uv run scan-index                                   # rebuild INDEX.md (lazy fields preserved by sha)
uv run parse-doc raw/<file>                         # parse all slices; stdout lists every output path
uv run parse-doc raw/<file> --section N             # surgical (docx)
uv run parse-doc raw/<file> --sheet NAME [--schema-only|--rows A:B]  # surgical (xlsx)
uv run parse-doc raw/<file> --slides A-B            # surgical (pptx)
uv run python -m tools.lint_wiki                    # validate wiki citation integrity
```

If the host repo doesn't have these as registered scripts, point Python directly at the bundled copies under `${CLAUDE_PLUGIN_ROOT}/skills/chip-kb-wiki/scripts/tools/`. Required PyPI packages: `python-docx`, `openpyxl`, `python-pptx` (Python ≥ 3.11).

## Where to read next

- `scripts/bootstrap.sh` — one-shot layout setup for a fresh repo (Step 0)
- `assets/templates/` — bundled `source.md` / `project.md` / `entity.md` / starter index & log / stub `pyproject.toml`
- `references/citation-grammar.md` — full citation rules, anchor conventions, two-layer indirection (projects → sources → parsed)
- `references/ingest-workflow.md` — the 7-step ingest in detail, with examples
- `references/attribution.md` — project-attribution signals, weights, and threshold policy
- `references/wiki-schemas.md` — frontmatter schemas and section templates for `sources/` `projects/` `entities/`
- `scripts/README.md` — installing & running the parser/lint scripts that ship with this skill
