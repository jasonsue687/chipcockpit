# Ingest Workflow (7 steps)

Run this every time a new document lands in `raw/`. The goal: turn a new docx/xlsx/pptx into a wiki entry that fits into existing project/entity pages without polluting them with low-confidence merges.

## Pre-flight checklist

- File sits at `raw/<file>` (don't move it into a subdirectory; raw/ is flat by convention)
- Filename follows the loose `<chip-or-customer>_<topic>_<version>.<ext>` shape if possible — it's a weak signal but useful
- You have `python-docx`, `openpyxl`, `python-pptx` installed (`uv sync` in a project with them in pyproject.toml, or `pip install` for ad-hoc use)

## Step 1 — Parse the whole doc

```bash
uv run parse-doc raw/<file>
# or (from any cwd, using bundled scripts):
uv run python ${CLAUDE_PLUGIN_ROOT}/skills/chip-kb-wiki/scripts/tools/parse_doc.py raw/<file>
```

stdout lists every slice path that was created or reused. Stderr summarises what changed ("parsed N new slice(s) of M total"). Note the slice paths — you'll cite them in step 2.

Skip the surgical flags (`--section`/`--sheet`/`--slides`) at ingest time. Default full-doc parsing is what you want; surgical mode is for huge files later, not for the first pass.

If `parsed/<file>/_meta.json` already exists with a stale sha, parse_doc purges stale slices and re-parses — that's automatic, no manual cleanup needed.

## Step 2 — Draft `wiki/sources/doc_NNN__<slug>.md`

Pick the next `doc_NNN` number by looking at `INDEX.md` and `wiki/sources/`. The slug is a kebab-case truncation of the filename.

Use the template in `wiki-schemas.md`. Required pieces:

1. **Frontmatter** — `doc_id`, `source` (raw/ path), `source_sha` (copy from `parsed/<file>/_meta.json`), `parsed_dir`, `project` (or `?` if unsure), `entities` (list), `has_images`, `ingested` (today's date in YYYY-MM-DD)
2. **摘要** — ≤200 字 orientation summary. No numbers; tell a future reader what this doc is for.
3. **关键事实** — bullet list, each line a single extractable fact with at least one inline citation (`[§N]` / `[§slide-K]` / `[/SheetName]`)
4. **待补 / 待澄清** — optional. Where the original is ambiguous or you suspect a contradiction with another doc.
5. **引用** — link definitions resolving each anchor used above to `../../parsed/<file>/<slice>.md`

Each "key fact" bullet should be one extractable claim. Don't pack three numbers into a single bullet — split them, each citation is then unambiguous.

## Step 3 — Extract entities and numeric fingerprints

While reading the slices in step 2, build two side lists:

**Entities** — chip names, IP block names, customer names, process nodes, anything that's a noun a future query will key on. Examples: `ChipA`, `PLL_top`, `clock_mesh`, `core_logic`, `EXAMPLE_N5`. These go into the source-page frontmatter and become candidates for `wiki/entities/<name>.md` pages.

**Numeric fingerprints** — distinctive numbers that uniquely tie this doc to a project. Examples: `die 4×4mm`, `skew 71ps target 80ps`, `1242 CTS buffers`. These are the cross-doc evidence for project attribution.

## Step 4 — Decide project attribution

Use the signals + thresholds in `references/attribution.md`. The three outcomes:

- **High confidence + shared anchor entity** → directly add to an existing `wiki/projects/<id>.md`
- **Mid confidence** → list in `wiki/projects/_candidates.md` with a `?` and a one-line rationale. Block the merge until a human OKs it.
- **Low confidence** → open a new `wiki/projects/<new-id>.md`

Misattribution is harder to undo than under-splitting. When in doubt, write to `_candidates.md`.

## Step 5 — Update `wiki/projects/<id>.md`

For each project page the new doc touches:

- Add the new `doc_NNN` to the `sources` array in the frontmatter
- Append new key facts to the "关键决策" section, each with a citation pointing to `../sources/doc_NNN__<slug>.md` (NOT directly to parsed/ — see two-layer indirection in `citation-grammar.md`)
- Add the doc to "文档清单" table
- Bump `last_updated`

Don't overwrite or summarise away existing facts. Append. Conflicts go in "已知矛盾 / 待澄清."

## Step 6 — Create / update `wiki/entities/*.md`

For each entity in the source's entity list:

- If `wiki/entities/<name>.md` exists: append a "跨文档提及" bullet citing the new source page; add new parameters under "关键参数" if the doc supplies any
- If it doesn't exist and the entity appears in ≥2 docs (now including this new one): create the page from the template
- Single-mention entities don't need a page — they live only in source-page frontmatter

## Step 7 — Update `wiki/index.md` and append to `wiki/log.md`

`wiki/index.md`:
- Under **By Project** — if a new project page was created, add a `- [<id>](projects/<id>.md) — <short tagline>` line
- Under **By Entity** — same for any newly created entity pages

`wiki/log.md` — append one block:

```markdown
## [YYYY-MM-DD] ingest | doc_NNN <filename-stem> → <project_id>
entities: [<list>]; sha <12-char>
<one-line note on attribution evidence if non-trivial>
```

The log is append-only and grep-friendly. Don't edit past entries.

## Post-ingest sanity

Run lint:

```bash
uv run python -m tools.lint_wiki
# or the bundled copy:
uv run python ${CLAUDE_PLUGIN_ROOT}/skills/chip-kb-wiki/scripts/tools/lint_wiki.py
```

Expect 0 errors. Warnings about `stale_citation` from other docs are unrelated. `orphan_source` for the doc you just ingested means you missed step 2 — go back.

Finally, lazy-fill `INDEX.md` for this doc — replace `<TBD>` in `summary` / `entities` / `project` to match the source page. `scan_index` preserves these by sha on next run.

## Common pitfalls

- **Forgetting `source_sha` in frontmatter** → lint can't detect future staleness; copy it from `parsed/<file>/_meta.json` exactly.
- **Citing parsed/ directly from a project page** → fine for now, but you lose the indirection benefit; if the source's slices change names, you'll have to update every project page that referenced them.
- **Merging into a project page on filename-prefix alone** → that's a ★☆☆ signal per `attribution.md`. Demand at least one ★★☆ or ★★★ corroboration.
- **Dropping figure-only docs** — v1 doesn't OCR images, but the surrounding paragraphs may still carry signal. Read them; flag `has_images: true` in frontmatter; note in "待补" that figures aren't extracted.
