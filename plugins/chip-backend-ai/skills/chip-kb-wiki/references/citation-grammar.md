# Citation Grammar

The single hardest rule in this skill: **every factual statement carries at least one inline citation pointing back to a parsed/ slice.** This file is the spec.

## Why citations matter

Wiki pages are LLM-maintained summaries — they drift, they can be wrong, they can over-paraphrase. parsed/ slices are deterministic outputs of `parse_doc.py`, so they are the canonical fact layer. Citations let a reader (or the lint script) verify any claim by clicking back to the parsed slice. Without them, the wiki becomes another lossy summary and you've lost the audit trail.

## Inline syntax

Reference-style markdown. Inline `[label]` markers go directly after the fact; link definitions go at the bottom of the file:

```markdown
ChipA Floorplan die 4mm×4mm，PLL_top 西北角 [doc_002§2]。
post-CTS skew 71ps，目标 <80ps，buffer 1242 [doc_003§slide-4][doc_001/Timing]。

…

[doc_002§2]: ../../parsed/ChipA_后端实现报告_v3.docx/section-2.md
[doc_003§slide-4]: ../../parsed/ChipA_设计评审_2026-04.pptx/slides-1-5.md
[doc_001/Timing]: ../../parsed/ChipA_PPA_汇总.xlsx/sheet-Timing-full.md
```

## Anchor conventions

| Source type | Anchor format | Example | Resolves to |
|---|---|---|---|
| docx section | `§N` | `[doc_002§3]` | `parsed/<file>/section-3.md` |
| pptx slides (single) | `§slide-K` | `[doc_003§slide-4]` | `parsed/<file>/slides-A-B.md` containing slide K |
| pptx slides (range) | `§slides-A-B` | `[doc_003§slides-1-5]` | `parsed/<file>/slides-1-5.md` |
| xlsx sheet | `/SheetName` | `[doc_001/Power]` | `parsed/<file>/sheet-Power-full.md` (or `-schema.md`) |

The `doc_NNN` prefix matches the `doc_id` in `wiki/sources/<doc-id>.md`'s frontmatter and the heading in `INDEX.md`. Be consistent — lint relies on the `doc_NNN` prefix to validate citation targets.

## Two-layer indirection

Wiki pages reference different targets depending on where they sit in the hierarchy:

- `wiki/projects/*.md` and `wiki/entities/*.md` → cite **`wiki/sources/<doc-id>.md`** (one layer up, easier to update)
- `wiki/sources/<doc-id>.md` → cite **`parsed/<file>/<slice>.md`** directly

Rationale: when a source doc is re-ingested, you only edit the source page; downstream project/entity pages keep working because their citations point at the source page, not at the parsed slice. Two-layer indirection isolates churn.

**Example layered citations:**

```markdown
# wiki/projects/ChipA_v3.md
post-CTS skew 71ps，目标 80ps [doc_002§3][doc_003§slide-4]。

[doc_002§3]: ../sources/doc_002__ChipA_后端实现报告_v3.md
[doc_003§slide-4]: ../sources/doc_003__ChipA_设计评审_2026-04.md
```

```markdown
# wiki/sources/doc_003__ChipA_设计评审_2026-04.md
post-CTS skew 71ps；CTS buffer 1242 [§slide-4]。

[§slide-4]: ../../parsed/ChipA_设计评审_2026-04.pptx/slides-1-5.md
```

Inside `wiki/sources/` the `doc_NNN` prefix can be dropped because the whole page belongs to one doc — labels like `[§slide-4]` are fine.

## Multi-source corroboration

If two or more docs say the same thing, cite **all** of them:

```markdown
die 4mm×4mm [doc_002§2][doc_003§slide-3]
```

Lint compares numeric values across multiply-cited facts and flags `contradicting_facts` if they disagree. Multi-source citations are the wiki's main quality signal — keep them.

## When you may skip a citation

Only for **non-factual** statements:

- Recap / framing: "下面分四步介绍 CTS 流程" (no facts asserted)
- Inferences explicitly marked as such, with a leading prefix:

```markdown
> 推断：clock_mesh 与 PLL_top 共享 power domain，未在原文明示。
> 待证：sign-off corner 暂无文档说明，请人工确认。
```

The `> 推断：` / `> 待证：` markers tell lint and future readers "this claim is editorial, not extracted."

## Hard rules

- A bare number with no citation is a lint candidate. If you find yourself writing one, either add a citation or rephrase as inference.
- Citation paths must `Read` successfully. Lint resolves the path and errors out if the target file is missing.
- The label format `[doc_NNN§…]` and `[doc_NNN/…]` is matched by lint regex; don't invent new anchor shapes without updating `tools/lint_wiki.py`.
- Don't cite `raw/` files directly. The contract is: facts come from `parsed/`, which is regenerable; `raw/` is binary and immutable.

## Quick checklist before saving a wiki page

1. Every numeric value carries `[…]`?
2. Every key decision / conclusion carries `[…]`?
3. Inferences prefixed with `> 推断：` or `> 待证：`?
4. Link definitions at the bottom resolve (relative paths from this file)?
5. Multi-source facts cite all sources (not just the first)?

If all five pass, ingest is clean.
