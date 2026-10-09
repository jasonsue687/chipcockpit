# Project Attribution

`raw/` is flat by design — filenames follow loose conventions, but project membership is **not** in the filesystem. The wiki layer infers it from multiple signals and is intentionally conservative.

## Why "conservative"

Two failure modes:

- **Over-merging** (false positive) — two unrelated projects' docs end up on the same project page. Cleaning this up means manually re-extracting facts, untangling shared entity pages, and rewriting citations. Hours of work.
- **Under-merging** (false negative) — one project's docs end up scattered across multiple pages. Cleaning this up means moving facts and updating citations. Minutes of work.

Asymmetry → bias toward under-merging. When confidence is mid-grade, route through `wiki/projects/_candidates.md` for human review rather than guessing.

## Signal table

| Signal | Weight | Notes |
|---|---|---|
| Anchor entity match (chip name / customer name) | ★★★ | Strongly exclusive — `ChipA` and `ChipB` named in different docs almost never share a project page |
| Entity-set Jaccard with an existing project | ★★★ | Compare the new doc's `entities` to the union of entities on each candidate project page |
| Numeric fingerprint match (PPA, die size, skew, buffer count, …) | ★★☆ | Two docs quoting "die 4×4mm" + "skew 71ps" + "buffer 1242" are almost certainly the same project |
| Explicit cross-reference ("详见 ChipA 评审 v3" / shared table titles) | ★★☆ | Cite the cross-ref in the log line |
| Filename prefix | ★☆☆ | Convenient but unreliable — `ChipA_PPA_汇总.xlsx` could be a template reused across chips |
| Time + version suffix | ★☆☆ | `_v1` / `_v2` / `_v3` orders docs within a project but doesn't prove project membership |

## Thresholds

Treat the signals as a rough confidence score (sum of ★s, weighted):

- **High** — at least one ★★★ signal **and** one corroborating ★★☆ signal (or two ★★★ signals). → Merge directly into the existing project page.
- **Mid** — exactly one ★★★ signal, or several ★★☆ signals without a ★★★ anchor. → Add an entry to `wiki/projects/_candidates.md` with the evidence; do not modify the project page until a human resolves.
- **Low** — only ★☆☆ signals (filename, version) and no entity overlap. → Open a new project page; the new doc starts its own attribution thread.

When in doubt, prefer the lower bucket. The candidates file is cheap; bad merges aren't.

## Worked example: doc_003 (`ChipA_设计评审_2026-04.pptx`)

Evidence (from `wiki/log.md`):

- Entities `[ChipA, PLL_top, clock_mesh]` overlap entirely with existing `ChipA_v3` project entities (Jaccard ≈ 0.8) → ★★★
- Numeric fingerprints "die 4×4mm + PLL_top 西北角 + skew target 80ps" exactly match doc_002 (`ChipA_后端实现报告_v3`) → ★★☆ × 3
- Filename starts with `ChipA_` → ★☆☆

Two ★★★-class signals (entity-set Jaccard + anchor entity `ChipA`) + multiple ★★☆ fingerprints → **High** confidence → directly merge into `ChipA_v3`.

The log line records the evidence so a future reader can audit:

```markdown
## [2026-05-10] ingest | doc_003 ChipA_设计评审_2026-04 → ChipA_v3
entities: [ChipA, PLL_top, clock_mesh]; sha b5e89dfcb169
锚点匹配：与 doc_002 共享 die 4×4mm + PLL_top 西北角 + skew 目标 80ps（强指纹）
```

## Worked example: a hypothetical mid-confidence case

Suppose a new doc `Power_Plan_v2.docx` lands. Evidence:

- No chip name in the filename — no ★★★ anchor
- Entity list `[PLL, decap, M9, M10]` — `PLL` overlaps with both `ChipA_v3` and `ChipB_PowerPlan`; rest don't strongly anchor → ★★☆
- Numeric fingerprint "PG 50um spacing" matches `ChipB_PowerPlan` → ★★☆
- Filename starts with `Power_` (template-y) → ★☆☆

Two ★★☆ signals point to ChipB but nothing ★★★ — **Mid** confidence. Add to `_candidates.md`:

```markdown
## [2026-05-17] candidate | Power_Plan_v2.docx → ChipB_PowerPlan?
evidence: PG 50um spacing matches doc_004; entities overlap PLL but not anchor; no chip name in filename
review: <name>
```

Don't touch `ChipB_PowerPlan.md` yet. Wait for a human to confirm or split.

## When to retire a candidate

`wiki/projects/_candidates.md` entries older than 7 days surface as `INFO ambiguous_project` in lint. Options:

1. Resolve to a project page (most common)
2. Mark resolved-as-new — open a new project page and move the candidate out
3. Mark resolved-as-skip — the doc is irrelevant (template, scratch, etc.); delete the entry and note in the log

Don't let candidates rot. Stale `_candidates.md` is a sign the ingest discipline is slipping.
