# Wiki Page Schemas

Three page types, three schemas. All three drive lint behavior — keep the frontmatter fields consistent or lint warnings pile up.

## `wiki/sources/doc_NNN__<slug>.md`

One page per source document. Cites parsed/ slices directly.

```markdown
---
doc_id: doc_NNN
source: raw/<filename>
source_sha: <12-char sha copied from parsed/<file>/_meta.json>
parsed_dir: parsed/<filename>/
project: <project_id or project_id?>      # `?` suffix while unresolved
entities: [<entity1>, <entity2>, ...]
has_images: false                           # v1 parse_doc doesn't OCR; mark true if doc relies on figures
ingested: YYYY-MM-DD
---

# <文档标题>

## 摘要

<≤200 字。该文档主要讲什么、覆盖哪些主题。不带数字细节；这里是导航摘要，不是事实陈述。>

## 关键事实

- 事实 1 [§N]
- 事实 2 [§K]
- 事实 3，多源印证 [§M][§slide-X]

## 待补 / 待澄清

<可选段。原文模糊、解析不全、或与其他文档冲突之处。给 lint 与人审看。>

## 引用

[§1]: ../../parsed/<filename>/section-1.md
[§2]: ../../parsed/<filename>/section-2.md
```

**Why `source_sha`:** lint compares this to `parsed/<file>/_meta.json`'s current sha. Mismatch → `WARN stale_citation` → re-ingest needed.

**Why `parsed_dir`:** lint uses this to find `_meta.json`, and to detect `orphan_source` (parsed/ dirs that no source page points at).

## `wiki/projects/<project_id>.md`

Aggregates one project's facts across all its source docs. Cites source pages (two-layer indirection).

```markdown
---
project_id: <ChipA_v3 / ChipB_PowerPlan / ChipC_concept / ...>
status: <规划中 / 概念阶段 / 后端实现中 / tape-out 准备 / 已流片>
process: <EXAMPLE_N5 / EXAMPLE_N7 / EXAMPLE_NODE / ?>
sources: [doc_NNN, doc_NNN, ...]
entities: [<chip-name>, <key-IPs>, <process>, ...]
last_updated: YYYY-MM-DD
---

# <项目展示名>

## 项目概况

<工艺、关键模块、阶段、客户等 high-level 信息。一两段，每段带 citation。>

## 关键决策

<跨源整合后的关键决策与数字，按主题分组。每条带 citation，引用目标优先指向 wiki/sources/<doc-id>.md。>

- Floorplan：… [doc_NNN§K]
- CTS：… [doc_NNN§K][doc_MMM§slide-Y]
- Power：… [doc_NNN§K]
- PPA：… [doc_NNN/SheetName]

## 文档清单

| ID | 类型 | 文档 | 阶段 |
|---|---|---|---|
| doc_NNN | docx/xlsx/pptx | <name> | <floorplan/cts/route/sign-off/...> |

## 已知矛盾 / 待澄清

<同事实多源不一致、待人审项等。无则写"无"。>

## 引用

[doc_NNN§K]: ../sources/doc_NNN__<slug>.md
[doc_MMM§slide-Y]: ../sources/doc_MMM__<slug>.md
```

**Status vocabulary** — keep it controlled so by-project views in `wiki/index.md` can group meaningfully. The five values listed above are the current set; extend deliberately if needed.

**`sources` array** drives by-project filtering and serves as a quick "which docs belong here" check.

## `wiki/entities/<entity-name>.md`

Aggregates per-entity mentions across docs. Cites source pages.

```markdown
---
entity: <PLL_top / clock_mesh / EXAMPLE_N5 / ChipA / ...>
type: <IP_block / module / process_node / chip / customer>
appears_in: [doc_NNN, doc_NNN]
projects: [<project_id>, <project_id>]
last_updated: YYYY-MM-DD
---

# <实体名>

<一句话定义。"锁相环顶层模块" / "5nm 工艺节点" / "Acme Corp 客户" 这种粒度。>

## 跨文档提及

<列出该实体在哪些源文档中被提及，每条带 citation 指向 wiki/sources/<doc-id>.md。>

- ChipA Floorplan 中的 PLL 位置 [doc_002§2]
- ChipA 评审中 PLL 时序 [doc_003§slide-3]

## 关键参数 / 属性

<可选段。该实体的物理参数、配置、约束等，跨文档汇总。每条带 citation。如果同一参数多个值，lint 会报 contradicting_facts。>

- 面积：0.8 mm² [doc_002§2]
- 静态功耗：5.2 mW [doc_001/Power]

## 引用

[doc_NNN§K]: ../sources/doc_NNN__<slug>.md
```

**`type` vocabulary** — `IP_block`, `module`, `process_node`, `chip`, `customer`. Add new types only when an entity genuinely doesn't fit — every new type makes the by-entity index harder to scan.

**`projects` array** lets you query "all entities of project X" by scanning entity-page frontmatter, even before by-project views are built.

## Why frontmatter matters

- Lint relies on `source_sha` and `parsed_dir` to detect staleness and orphans
- `scan_index` preserves lazy-filled fields by sha — the `project` field in `INDEX.md` should match `wiki/sources/<doc-id>.md`'s `project` field
- Future automation (auto-attribution, doc clustering) will key on `entities` and `projects` arrays — keep them clean and de-duplicated

If you're tempted to add ad-hoc fields, first consider whether they belong in body sections instead. Frontmatter is for fields a tool will read.

## Templates

The skill's host repo (`chip-knowledge-ai`) keeps blank templates at `wiki/_templates/{source,project,entity}.md` excluded from the index. The schemas above match those templates one-to-one — when in doubt, open the host repo's `_templates/` directly.
