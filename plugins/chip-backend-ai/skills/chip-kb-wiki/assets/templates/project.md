---
project_id: <ChipA_v3 / ChipB_PowerPlan / ...>
status: <规划中 / 后端实现中 / tape-out 准备 / 已流片 / 概念阶段>
process: <EXAMPLE_N5 / ?>
sources: [doc_NNN, doc_NNN, ...]
entities: [<chip-name>, <key-IPs>, <process>]
last_updated: YYYY-MM-DD
---

# <项目展示名>

## 项目概况

<工艺、关键模块、阶段、客户等 high-level 信息。引项目页范围内的源文档摘要。>

## 关键决策

<跨源整合后的关键决策与数字。每条带 citation，引用优先指向 wiki/sources/<doc-id>.md（两层间接）。>

- Floorplan：… [doc_NNN§K]
- CTS：… [doc_NNN§K][doc_MMM§slide-Y]
- Power：… [doc_NNN§K]
- PPA：… [doc_NNN/SheetName]

## 文档清单

| ID | 类型 | 文档 | 阶段 |
|---|---|---|---|
| doc_NNN | docx/xlsx/pptx | <name> | <floorplan/cts/route/...> |

## 已知矛盾 / 待澄清

<同事实多源不一致、待人审项等。无则写"无"。>

## 引用

[doc_NNN§K]: ../sources/doc_NNN__<slug>.md
[doc_MMM§slide-Y]: ../sources/doc_MMM__<slug>.md
