---
entity: <PLL_top / clock_mesh / EXAMPLE_N5 / ChipA / ...>
type: <IP_block / module / process_node / chip / customer>
appears_in: [doc_NNN, doc_NNN]
projects: [<project_id>, <project_id>]
last_updated: YYYY-MM-DD
---

# <实体名>

<一句话定义。例："锁相环顶层模块" / "5nm 工艺节点"。>

## 跨文档提及

<列出该实体在哪些源文档中被提及，每条带 citation 指向 wiki/sources/<doc-id>.md。>

- ChipA Floorplan 中的 PLL 位置 [doc_002§2]
- ChipA 评审中 PLL 时序 [doc_003§slide-3]

## 关键参数 / 属性

<可选段。该实体的物理参数、配置、约束等，跨文档汇总。每条带 citation。>

- 面积：0.8 mm² [doc_002§2]
- 静态功耗：5.2 mW [doc_001/Power]

## 引用

[doc_NNN§K]: ../sources/doc_NNN__<slug>.md
