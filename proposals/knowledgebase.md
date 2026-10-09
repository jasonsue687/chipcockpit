当前项目是一个关于芯片后端开发的插件系统，项目有一个芯片知识库系统，这个知识库系统最终会作为claude code的插件安装进去，然后在实际的AI后端项目开发中被应用，比如说，查询知识库回答问题，在实际写tcl脚本时，查询user guide
当前这套知识库系统包括：
1. 芯片eda软件的 各种 user guide，可能有几十份pdf文件。 当前这种类型的资料是通过 LLM + 结构化索引 + 文件路由的方式来处理的，你可以参考@plugins/chip-backend-ai/knowledge/processed_eda 
2. 专家经验，待建设

现在我有一个新类型资料，这个资料曾经的芯片设计项目文档资料包，其特点是：
- 资料包中，包含多个项目的资料，需要注意的是，他们没有按照项目划分子目录，而是平铺在一个目录下
- 文档类型包含word，excel，ppt，文件大小从几百KB到几十MB不等
- 数量比较多，可能将近百份的文件

这类知识库不需要参与到AI后端开发系统中，但是我需要解析并处理这个资料包，帮我分析一下，如果是这种情况的话，我应不应该将这个资料包整合到当前的知识库系统中，为什么？


需要注意的是：

- 不同类型的知识库必须分开处理，不能融合为单一数据库，因为：
    - user guide 是所有人都可以访问的，项目经验，是有脱敏要求，只能部分少数人才能访问，单一知识库，容易敏感信息泄漏
    - 专家经验，密度高，内容少，可直接作为系统提示词传入到上下文
- 不使用RAG和向量数据库，因为信息比较碎片化
- 项目经验库需要可溯源，也就是说在基于项目经验库回到问题的同时，同时给出引用关系


现在我们关注的重点是如何处理曾经多个项目的经验文档，这些曾经成功项目文档的经验是高质量的资料，如何在后续的芯片后端开发项目中，能够同时应用到这些资料。你需要思考的是：
1. 如何处理，分析项目的经验文档，以便形成有效的项目经验知识库
2. 形成项目经验知识库之后，如何和eda知识库，专家经验库，统一检索，使用，回答我们的问题
3. 后续如有增量项目文件，如何加入进来。比如说今天项目A的第一份文件，明天项目B的第3份文件，后天项目A的第二份文件
4. 项目经验库的内容如何组织？如何分类？ 按照阶段分类？按照类型分类

```
project_experience_kb/
  1_project_clusters/
  2_document_manifest/
  3_experience_cards/
  4_casebook/
  5_scripts_and_recipes/
  6_evidence_store/
  7_permission_manifest/
```

# 思考

你需要考虑的几个问题：


1. 联网检索一下，卡帕西的 LLM iwiki的核心思想是什么？ 如何将这个思想应用到我们项目文档，eda user guide和专家经验上
2. 项目目录中可能存在几百份的excel，word和ppt，如何让LLM有效的完成这个项目目录下的所有文档的分析工作


# 需要待澄清的问题

几个关键问题：
1. 如何解析？解析成markdown吗？ 图片怎么处理？
2. 解析之后，如何处理
3. 处理之后，如何组织？
4. 组织之后，如何使用。
5. 使用的时候，要不要溯源？
6. 项目知识库的文档是不是应该定一个模版格式


整体思路：
1. 程序化解析文本
2. LLM分析，链接当前仓库


- 支持溯源
- 多个项目的文档，需要LLM自行分析并关联


# 已经明确的地方
需要注意的是
- 不同类型的知识库必须分开处理，不能融合为单一数据库，因为：
    - user guide 是所有人都可以访问的，项目经验，是有脱敏要求，只能部分少数人才能访问，单一知识库，容易敏感信息泄漏
    - 专家经验，密度高，内容少，可直接作为系统提示词传入到上下文
- 不使用RAG和向量数据库，因为信息比较碎片化

固定芯片后端标签

```
domain:
  - floorplan
  - powerplan
  - placement
  - cts
  - routing
  - timing
  - power
  - ir_drop
  - em
  - physical_verification
  - eco
  - signoff
  - flow
  - automation

stage:
  - init
  - floorplan
  - pre_place
  - place_opt
  - pre_cts
  - post_cts
  - route
  - post_route
  - signoff
  - eco

issue_type:
  - congestion
  - setup_violation
  - hold_violation
  - skew_issue
  - transition_violation
  - fanout_violation
  - ir_drop
  - em_violation
  - drc
  - lvs
  - antenna
  - density
  - pin_access
  - macro_placement
  - clock_tree_quality
  - route_detour
  - runtime
  - memory
```


# 一些可能是笔记好的思考

- 给每个文档增加元数据
- 项目重建，需要知道每个文件的归属项目