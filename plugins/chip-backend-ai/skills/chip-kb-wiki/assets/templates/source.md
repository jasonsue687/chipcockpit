---
doc_id: doc_NNN
source: raw/<filename>
source_sha: <12-char sha from parsed/<file>/_meta.json>
parsed_dir: parsed/<filename>/
project: <project_id or project_id?>
entities: [<entity1>, <entity2>]
has_images: false
ingested: YYYY-MM-DD
---

# <文档标题>

## 摘要

<≤200 字。该文档主要讲什么、覆盖哪些主题。不带数字细节，定位用。>

## 关键事实

<逐条列关键事实，每条带至少一个 citation。事实指数字、决策、结论；上下文铺垫不必每行带引。>

- 事实 1 [§N]
- 事实 2 [§K]
- 事实 3，多源印证 [§M][§slide-X]

## 待补 / 待澄清

<可选段。原文模糊或与其他文档冲突的地方写在这里，给 lint 与人审看。>

## 引用

[§1]: ../../parsed/<filename>/section-1.md
[§2]: ../../parsed/<filename>/section-2.md
