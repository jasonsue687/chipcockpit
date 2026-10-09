# chip-kb-wiki

A Claude Code skill that turns a pile of chip project documents (Word / Excel / PowerPoint) into a Karpathy-style multi-layer markdown wiki, and enforces **citation-first answers** — every numeric or decision-level claim must trace back to a parsed slice of the source doc.

---

## Who this is for

Hardware / EDA teams who:

- Get design docs as `.docx` / `.xlsx` / `.pptx` (后端实现报告, PPA 汇总, 设计评审 PPT, power plan 笔记…)
- Have **dozens to ~100 docs** per project that are too many to read every time but too few to justify RAG
- Want to ask "post-CTS skew 是哪份评审 PPT 里写的 71ps，buffer count 多少" and get a citation, not a paraphrase
- Care about not letting wiki summaries silently drift away from the source numbers

If your knowledge base is < 100 docs, this skill is sized for you. If it's 10,000+, use real RAG.

## What you get

| Layer | What it is | Who writes it |
|---|---|---|
| `raw/` | Original Word / Excel / PPT (immutable) | You |
| `parsed/<file>/*.md` | Atomic markdown slices — sections / sheets / slide ranges | `tools/parse_doc.py` (bundled) |
| `wiki/sources/doc_NNN__<slug>.md` | One page per source doc: summary + key facts with citations | Claude (via skill) |
| `wiki/projects/<id>.md` | Cross-source aggregation per project | Claude |
| `wiki/entities/<name>.md` | Cross-doc aggregation per entity (IP, chip, process) | Claude |
| `wiki/index.md` | by-project / by-entity navigation | Claude |
| `INDEX.md` | by-source machine view with lazy-filled summary/entities/project | `tools/scan_index.py` (bundled) |

Citations bridge wiki → parsed via reference-style markdown:

```markdown
ChipA Floorplan die 4mm×4mm，PLL_top 西北角 [doc_002§2]。
post-CTS skew 71ps，目标 <80ps，buffer 1242 [doc_003§slide-4][doc_001/Timing]。

[doc_002§2]: ../../parsed/ChipA_后端实现报告_v3.docx/section-2.md
[doc_003§slide-4]: ../../parsed/ChipA_设计评审_2026-04.pptx/slides-1-5.md
[doc_001/Timing]: ../../parsed/ChipA_PPA_汇总.xlsx/sheet-Timing-full.md
```

The bundled `lint_wiki.py` validates that every citation resolves and that `source_sha` in each `wiki/sources/<doc>.md` matches the current parsed sha.

---

## Quick start (from zero)

You only need this once per repo:

```bash
# 1. Bootstrap the layout in a fresh directory
${CLAUDE_PLUGIN_ROOT}/skills/chip-kb-wiki/scripts/bootstrap.sh /path/to/new-kb
cd /path/to/new-kb

# 2. Install runtime deps (Python ≥ 3.11)
uv sync                     # the stub pyproject.toml lists python-docx / openpyxl / python-pptx
# or:
uv pip install python-docx openpyxl python-pptx

# 3. Drop your first doc into raw/
cp ~/Downloads/ChipA_后端实现报告_v3.docx raw/

# 4. Ask Claude (in this repo or anywhere — skill is global):
#    "把 raw/ChipA_后端实现报告_v3.docx ingest 进 wiki"
```

Claude will trigger the skill, run `parse_doc` to make `parsed/<file>/*.md` slices, then walk you through the 7-step ingest to produce `wiki/sources/doc_001__ChipA_后端实现报告_v3.md`, update `wiki/projects/`, and append a `wiki/log.md` entry.

## Daily use — example prompts that trigger the skill

The skill's description is tuned to fire on these patterns. Use them as a phrase book:

### Query

- **By doc + fact:** "ChipA 那份后端实现报告 v3 里 floorplan 写的 die 是 4×4 mm 没记错吧？PLL_top 我记得是放西北角，能帮我从原文里把这两条引出来吗"
- **By trace-the-number:** "post-CTS 的 71ps skew 我记得是从某份评审 PPT 里看到的，目标好像是 80ps，给我找到原文那一页"
- **By doc_id:** "doc_004 那份 ChipB Power Plan 笔记里 PG 网络的 spacing 写的多少"
- **By xlsx sheet:** "ChipA_PPA_汇总.xlsx 里 Power sheet 三块（PLL_top + clock_mesh + core_logic）的动态功耗加起来多少"
- **By project meta:** "wiki/index.md 里 ChipA_v3 这个项目目前挂了几份源文档"

### Ingest

- "我刚把 raw/ChipB_signoff_v2.docx 扔进来，按 7 步流程 ingest"
- "raw/ChipC_概念笔记.docx 这份只是早期速记没有 heading 层级，先 parse 一下我看看切片长啥样"

### Compounding (writing facts back)

- "刚才回答你的问题时我在 sources/doc_002__... 又补了 2 条 CTS 决策，需要回填到 ChipA_v3 项目页吗"

### Lint

- "跑一下 lint 看看 wiki 里有没有 broken/stale citation"
- "wiki/ 里好像有几条 stale_citation，跑 lint 看看 source_sha 哪份对不上"

### Bootstrap a brand-new repo

- "我们换了个项目，也是按 raw → parsed → wiki/sources/projects/entities 这套 Karpathy llm-wiki 的搞法搭知识库，能帮我在新 repo 里 bootstrap 一遍"

## What WON'T trigger this skill (by design)

These have sibling skills in the same plugin — the skill description has explicit anti-triggers:

| Query pattern | Goes to instead |
|---|---|
| "解释下 hold slack / CTS / IR drop" | `read-eda-concept` |
| "在 Innovus 里跑 floorplan / cts / route" | `run-chip-flow` |
| "create_clock_tree_spec 的 syntax 是什么" | `search-eda-command` |
| "把这份 PDF 转成 markdown" | `pdf-to-markdown` |
| "列一下 expert_base 有哪些 topic" | `list-expert-topics` |
| "打开 example_lab_doc.md 的 Module 3" | `read-eda-lab-doc` |
| 通用 python-docx / markdown 链接语法 / git / Claude plugin 编写问题 | 不触发任何 skill，直接答 |

---

## What's bundled (skill anatomy)

```
chip-kb-wiki/
├── SKILL.md                  Claude's operating manual (always loaded when triggered)
├── README.md                 This file (human-facing usage doc)
├── references/               Progressive disclosure — Claude Reads on demand
│   ├── citation-grammar.md       full citation rules
│   ├── ingest-workflow.md        7-step ingest
│   ├── attribution.md            project attribution signals + thresholds
│   └── wiki-schemas.md           frontmatter schemas for sources/projects/entities
├── assets/templates/         Files copied into your repo by bootstrap.sh
│   ├── source.md / project.md / entity.md     wiki page templates
│   ├── index-starter.md / log-starter.md      starter wiki/ files
│   ├── pyproject-stub.toml                    stub for find_repo_root
│   └── gitignore-additions                    parsed/ etc.
├── scripts/
│   ├── bootstrap.sh              one-shot layout setup
│   ├── README.md                 script run instructions
│   └── tools/                    parse_doc / scan_index / lint_wiki + handlers
└── evals/
    ├── trigger_eval.json         20 trigger eval queries (for description tuning)
    └── eval_set.json             user-reviewed copy
```

### Loading model (why this is fast)

- **Description (frontmatter)** — always in Claude's context (~300 words). This is the router.
- **SKILL.md body** — loaded when description matches. ~190 lines.
- **`references/*.md`** — Claude Reads them only when a deeper section is needed. Total ~440 lines unloaded by default.
- **`scripts/`** — never loaded into context; executed via Bash.
- **`assets/templates/`** — never loaded into context; copied to your repo by bootstrap.

So an idle session with the skill installed pays ~300 words of context. A session that actually ingests a doc pays maybe 1000-2000 words from SKILL.md + 1-2 reference files.

---

## Maintenance commands

```bash
# Inside a bootstrapped repo (cwd = repo root):
PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/skills/chip-kb-wiki/scripts \
  uv run --with python-docx --with openpyxl --with python-pptx \
  python -m tools.parse_doc raw/<file>                  # parse all slices of <file>

PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/skills/chip-kb-wiki/scripts \
  uv run --with python-docx --with openpyxl --with python-pptx \
  python -m tools.scan_index                            # rebuild INDEX.md (preserves lazy-filled fields by sha)

PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/skills/chip-kb-wiki/scripts \
  uv run --with python-docx --with openpyxl --with python-pptx \
  python -m tools.lint_wiki                             # exit 0 clean / 1 warn / 2 err
```

If you'd rather not type that prefix every time, register the scripts in your repo's `pyproject.toml`:

```toml
[project.scripts]
parse-doc  = "tools.parse_doc:main"
scan-index = "tools.scan_index:main"
lint-wiki  = "tools.lint_wiki:main"

[tool.hatch.build.targets.wheel]
packages = ["tools"]
```

…and symlink or copy the `tools/` package into your repo so `uv run parse-doc raw/<file>` works.

## Cache & invalidation

- `parse_doc` keeps `parsed/<file>/_meta.json` with `{sha, source, last_parsed}`. On re-run, if the source's sha changed, it **purges that directory's stale slices** before re-parsing. No manual cleanup.
- `lint_wiki` reports `WARN stale_citation` when `wiki/sources/<doc>.md`'s frontmatter `source_sha` mismatches the parsed sha → re-ingest that source page.
- `lint_wiki` reports `WARN orphan_source` when `parsed/<dir>/` exists but no `wiki/sources/<doc>.md` references it → you parsed something but didn't write the wiki page.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `RuntimeError: Could not locate repo root` | No `pyproject.toml` at or above cwd | Run `scripts/bootstrap.sh` or drop one |
| `ModuleNotFoundError: docx / openpyxl / pptx` | Deps not installed | `uv pip install python-docx openpyxl python-pptx` |
| `parse_doc` outputs nothing | Source sha unchanged, slices cached | Add `--force`, or modify source |
| Skill doesn't fire for "ChipA 文档" | Query too short — Claude prefers handling simple queries directly | Phrase as a fact lookup ("die 多大", "skew 是哪份 PPT 写的") |
| Skill fires for "解释 CTS" but should go to `read-eda-concept` | Anti-trigger missed | Tell us the failing prompt — we'll tighten the description |
| Lint says `broken_citation` | Citation path doesn't resolve | Open the source page, check the link-def lines match parsed/ slice paths |

## Limitations (v0.1)

- **No image / figure OCR.** `parse_doc` v1 emits `> [图占位 ...]` placeholders. If a doc's content is mostly in figures (waveforms, layouts), expect gaps.
- **Dense xlsx sheets are schema-only by default.** Sheets ≥ 5000 rows get a 5-row preview unless you pass `--rows A:B`.
- **No automatic project attribution.** Mid-confidence merges go to `wiki/projects/_candidates.md` for human review. See `references/attribution.md`.
- **Templates not auto-synced.** If you edit `wiki/_templates/` in your repo, re-running `bootstrap.sh` will refresh them from the skill (it always refreshes `_templates/`). User-modified `wiki/index.md` / `wiki/log.md` / `pyproject.toml` are preserved.

---

## Where to read next

- **Full operating manual:** [`SKILL.md`](SKILL.md)
- **Why citations are mandatory + full grammar:** [`references/citation-grammar.md`](references/citation-grammar.md)
- **How to add a new doc — 7 steps:** [`references/ingest-workflow.md`](references/ingest-workflow.md)
- **How project attribution decisions get made:** [`references/attribution.md`](references/attribution.md)
- **Frontmatter schemas for the three page types:** [`references/wiki-schemas.md`](references/wiki-schemas.md)
- **How the bundled scripts work / how to sync them:** [`scripts/README.md`](scripts/README.md)

---

## Acknowledgements

Inspired by Andrej Karpathy's `llm-wiki` pattern — at ~100-doc scale, navigated markdown indexes beat RAG, and a multi-layer wiki with verifiable citations is both auditable and cheap to maintain.

Original implementation: [chip-knowledge-ai](https://github.com/jasonsue687/chip-knowledge-ai) (or wherever the upstream repo lives). This skill bundles the parser/lint scripts + methodology so the workflow can run in any cwd, not just that repo.
