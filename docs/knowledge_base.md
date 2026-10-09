
### 知识库扩展方案：项目文档支柱 + 跨项目经验复用 (Knowledge Base Architecture V1)

本方案在现有"专家经验 + EDA 工具文档"两支柱基础上，新增"项目文档"支柱，并设计跨项目经验复用机制，让历史项目沉淀的 Word/Excel/PPT 资料能被 LLM 有效利用，并把项目独有的踩坑与决策蒸馏成可在新项目中复用的模式与专家经验。

设计灵感来自 Andrej Karpathy 提出的 [LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) 模式（"the wiki is a persistent, compounding artifact"），但**仅选择性应用**——并非全部知识都适合 LLM 全权改写。

---

#### 一、 背景与动机

**现状（两支柱）：**
- `knowledge/expert_base/` — 人工沉淀的专家经验（kebab-case Markdown）
- `knowledge/processed_eda/` — PDF 用户手册自动构建的层级知识库

**缺口 1：项目沉淀无入库机制**
一个芯片项目目录可能积累几百份 docx/xlsx/pptx：spec、评审 PPT、timing/area/IR 报告、会议纪要、邮件截图。这些资料目前完全没有被知识库收纳，LLM 在新对话中无法引用本项目历史决策。

**缺口 2：项目经验无法跨项目复用**
即便单个项目入库了，"projA 怎么做的 CTS"是 project-specific 事实，新项目不知道哪些经验可借鉴。芯片后端是高度重复的领域——同样的踩坑会在不同项目反复出现。

**设计目标：**
1. 入库一个项目目录下数百份混杂源（Word/Excel/PPT），生成 LLM 可有效检索的合成 wiki
2. 项目完成后，把通用经验显式蒸馏到模式库与专家库，下个项目能直接受益
3. 全程不依赖向量数据库 / RAG，仅靠 LLM + 结构化文件系统

---

#### 二、 核心设计原则

**原则 1：按"所有权"分离三支柱**

不同知识有不同的所有者，决定了 LLM 能否改写：

| 支柱 | 所有者 | LLM 能改写 | 信息源 | 典型查询动机 |
|------|--------|-----------|--------|------------|
| EDA UG | 厂商 | 不能 | 厂商 PDF | "这个命令怎么用" |
| 项目文档 | LLM（用户指导下） | 能，且应该 | docx/xlsx/pptx | "我们项目决定了什么" |
| 专家经验 | 人 | 不能直接改，只能提议 | 人写 md | "这种场景一般怎么处理" |

**原则 2：Karpathy LLM Wiki 模式仅完整应用于"项目文档"**

| Karpathy 元素 | EDA UG | 项目文档 | 专家经验 |
|---------------|:------:|:--------:|:-------:|
| `raw/` vs `wiki/` 分离 | ✗ | ✓ | ✗ |
| Ingest 工作流 | ✗ | ✓ | ✗ |
| Lint 工作流 | 仅死链 | ✓ | ✓（仅提议） |
| LLM 全权拥有 wiki | ✗ | ✓ | ✗ |
| `log.md` 时间日志 | 极简 | ✓ | ✓ |
| 跨页合成 | ✗ | ✓ | ✗ |

EDA UG 是厂商权威，绝不能被 LLM 改写。专家经验是人沉淀的精华，LLM 可提议修订但不能直接改。**只有项目文档完全适合 LLM 全权拥有的合成 wiki 模式**。

**原则 3：跨支柱不预合成，对话时路由**

合成发生在**对话时**而非**存储时**。预合成会丢失来源、模糊权威性、引发同步问题。跨支柱关联通过顶层 `topics/` 指针表实现——只放路由信息，不复制内容。

**原则 4：项目经验通过显式蒸馏跨项目复用**

不靠"全文搜索 20 个项目"。项目结束时主动跑蒸馏，把可复用经验提炼到模式库（`_patterns/`）与专家候选（`expert/_pending/`），新项目通过结构化元数据索引找相似项目细节。

---

#### 三、 总体架构

```
knowledge/
├── INDEX.md                              # 顶层路由：三句话告诉 LLM 哪类问题查哪里
├── topics/                               # 跨支柱主题路由表（仅指针，不合成内容）
│   ├── cts.md
│   ├── ir_drop.md
│   └── ...
│
├── eda_ug/                               # 支柱 1（建议从 processed_eda 改名，可选）
│   ├── _index.md                         # 现 _global_index.md
│   ├── _log.md                           # 极简："2026-04-26 ingested example-power-tool v2026.1"
│   └── <manual>/                         # 现有层级结构 100% 不动
│       └── ...
│
├── projects/                             # 支柱 2：项目文档（新增）
│   ├── _global_index.md                  # 跨项目元数据索引（YAML）
│   ├── _patterns/                        # 跨项目重复成功做法
│   ├── _antipatterns/                    # 跨项目失败案例
│   ├── _retrospectives/                  # 项目复盘
│   └── <project>/
│       ├── raw/                          # 不可改：原 docx/xlsx/pptx + 中间 md
│       ├── manifest.jsonl                # Stage 1 输出
│       ├── triage.jsonl                  # Stage 2 输出
│       ├── clusters.jsonl                # Stage 3 输出
│       └── wiki/                         # LLM 全权拥有的合成层
│           ├── index.md
│           ├── log.md
│           ├── entities/
│           ├── decisions/
│           ├── concepts/
│           ├── reports/                  # 报告时间线
│           ├── threads/                  # 评审/会议线程
│           └── stages/                   # 阶段视图（指针）
│
└── expert/                               # 支柱 3：人拥有 + LLM 协助（建议从 expert_base 改名，可选）
    ├── _index.md
    ├── _log.md                           # 修订史
    ├── _suggestions.md                   # LLM lint 待裁决建议
    ├── _pending/                         # LLM 蒸馏的候选，等人审升级
    └── *.md                              # 人写专家经验
```

---

#### 四、 三支柱详细设计

##### 4.1 支柱 1：EDA UG（保持现状 + 极小扩展）

**结构不变**：现有 `processed_eda/<doc>/<层级目录>/_summary.md → detail_*.md` 全部保留。

**扩展点（仅两处）：**
- 新增 `_log.md`：极简变更日志，仅记录"何时 ingest 了哪份新手册"
- 死链 lint：周期性检查跨文件引用是否还有效

**禁止：**
- 不在 `eda_ug/` 内做任何 LLM 合成
- 不放 `_concepts/` 综述层（这层放在 `topics/`）
- LLM 永远只读，只有 `pdf_to_markdown.py` + `build_knowledge_base.py` 写入

##### 4.2 支柱 2：项目文档（新增，完整 Karpathy）

**双层结构：raw/ + wiki/**

- `raw/` — 原始 docx/xlsx/pptx + 机械转换得到的中间 md。**不可改，作为审计追溯源**。
- `wiki/` — LLM 全权拥有的合成层。新源 ingest 时 LLM 修订相关 wiki 页。

**wiki/ 内部按"内容"组织，不按"阶段"**：

| 子目录 | 内容 | 典型页数（300 源项目） |
|--------|------|-----------------------|
| `entities/` | 每个 macro / IP / clock domain 一页 | ~10 |
| `decisions/` | 每个关键决策一页（含来源、争论、最终结论） | ~10 |
| `concepts/` | 项目级策略性概念 | ~5 |
| `reports/` | 同 schema 的报告时间线（如所有 timing report） | ~5 |
| `threads/` | 评审/会议系列（如 floorplan 评审 W08-W14） | ~10 |
| `stages/` | 阶段视图（仅指针，不复制内容） | 6 |

**总页数约 ~40，对应 ~300 源文件，压缩比 7-8:1**。这是 Karpathy 模式的精髓——wiki 页数远小于源文件数。

**特殊文件：**
- `wiki/index.md` — 按内容（不按阶段）的内容目录，每次 ingest 后更新
- `wiki/log.md` — append-only 决策与变更流，前缀可解析（如 `## [2026-04-26] ingest | CTS Review v2 | 触动 5 页`）
- `_schema.md` — 本项目 wiki 约定（类似项目级 CLAUDE.md）

##### 4.3 支柱 3：专家经验（人主导 + LLM 协助）

**结构基本不变**，加两处 LLM 协助机制：

- `_suggestions.md` — LLM lint 输出（"X.md 与 Y.md 疑似矛盾"），人裁决后才动原文件
- `_pending/` — LLM 从项目复盘蒸馏的候选经验，等人审升级到 `expert/<topic>.md`

**铁律：LLM 永不直接修改 `expert/*.md`**。只能写到 `_suggestions.md` 或 `_pending/`，等人裁决。

---

#### 五、 跨支柱路由机制：`topics/`

**作用**：LLM 接到跨支柱问题（"怎么做 CTS"）时，第一站读 `topics/<topic>.md`，知道该去哪几个支柱的哪些文件。

**关键约束：仅放指针，不复制内容**。维护成本低，新增手册时手动加一两行；不会过时到无法使用。

**示例 `topics/cts.md`：**

```markdown
# CTS（Clock Tree Synthesis）

## 入门 / 决策框架
- [expert/cts-best-practices.md] — 团队的 CTS 经验

## 工具命令
- Innovus: [eda_ug/example_ug/04_cts/02_commands/detail_ccopt_design.md]
- example-power-tool: [eda_ug/example_power_manual/.../cts_signoff.md]

## 跨项目模式
- [projects/_patterns/cts_multi_clock.md]
- [projects/_antipatterns/cts_h_tree_for_skewed_clocks.md]

## 历史项目案例
- 活跃项目: projects/<active>/wiki/concepts/clock_strategy.md
- projA: [projects/projA/wiki/decisions/cts_strategy.md]
- projB: [projects/projB/wiki/decisions/cts_strategy_v2.md]

## 常见问题
- skew 大: [expert/cts-skew-tips.md]
```

每个 topics 文件 < 30 行。维护策略：手动维护，新增条目时由人加（不是 LLM 自动生成）。

---

#### 六、 项目文档 Ingest 五阶段管线

数百份混杂源不能 naive 地"每文件 LLM 读一遍"。设计为漏斗式管线，每阶段都有 checkpoint，可暂停人审再继续。

```
┌───────────────────┐  300 files
│ 1. Inventory      │  机械（python-docx/openpyxl/python-pptx 抽元数据）
│   零 LLM          │  → manifest.jsonl
└─────────┬─────────┘
          ↓
┌───────────────────┐  300 files × Haiku
│ 2. Triage         │  分类 + 2 行摘要 + 标签 + valuable_score
│   小模型          │  → triage.jsonl   ($5)
└─────────┬─────────┘
          ↓
┌───────────────────┐  代码 + 可选 LLM 辅助
│ 3. Cluster & Dedup│  按 (主题, 时间, 类型) 聚类，识别 V1/V2/V_final
│                   │  → clusters.jsonl + canonical 选择
└─────────┬─────────┘
          ↓
┌───────────────────┐  ~80 canonical × Sonnet
│ 4. Deep Ingest    │  完整 Karpathy ingest，按依赖顺序累积
│   大模型 + 选择性  │  → wiki/   ($50-80)
└─────────┬─────────┘
          ↓
┌───────────────────┐  新增/修改文件触发
│ 5. Incremental    │  hash → 已有则 skip；否则 triage→cluster→ingest
│                   │  + 周期 lint
└───────────────────┘
```

##### Stage 1: Inventory（无 LLM，秒级）

走遍目录，对每个 docx/xlsx/pptx 抽：`path, size, mtime, author, page/slide/sheet count, content_hash, first_chars`。content_hash 立刻做精确去重。

输出 `manifest.jsonl`，每行一文件：
```jsonl
{"path":"specs/floorplan_v3.docx","type":"word","mtime":"2026-03-12","pages":24,"hash":"abc...","author":"Wang"}
```

##### Stage 2: Triage（Haiku，~$5/300 文件）

对每个文件抽前 N 页/张/sheet（不是全部！），喂 Haiku：
- 一级分类：`spec | report | review | meeting | email | draft | misc`
- 二级主题：`floorplan | cts | route | timing | power | ir_drop | ...`
- 2 行摘要 + 关键词
- `valuable_score` 0-3（草稿/邮件标 0，spec/最终评审标 3）

**人审 checkpoint**：抽 20 个 sample 检查分类正确率。

##### Stage 3: Cluster & Dedup（代码主导）

按这个优先级聚类：
1. **精确重复**：content_hash 相同 → keep one，其他作 alias
2. **版本族**：filename pattern (`*_v1/v2/v_final`) + topic + author 相同 → 取最新或最大 score 作 canonical
3. **主题线程**：同 topic 同类型连续时间 → thread cluster（如"Floorplan 评审线程"含 5 份 PPT）
4. **同 schema Excel**：column 签名相同的报告（30 份 timing report）→ 一个 cluster，**生成 schema 页 + 时间线表**

输出 `clusters.jsonl`。**人审 checkpoint**：clusters 一般 ~30-50 个，肉眼可扫，发现错配手工调整。

##### Stage 4: Deep Ingest（Sonnet，仅 canonical）

**关键：按依赖顺序，不是按文件顺序**：

1. 先 ingest specs（奠定 entities/）
2. 再 ingest concepts/decisions（创建 decisions/）
3. 再 ingest threads（评审 PPT 系列按时间序累积更新同一页）
4. 再 ingest timeline（同 schema 报告抽指标，生成时间线表）
5. 最后 ingest 杂项（邮件/会议批量合并）

每个 cluster 的 ingest 策略：

| Cluster 策略 | 处理方式 | 输出 wiki 页数 |
|--------------|----------|---------------|
| `latest_only` | 只读 canonical 全文 | 1（其他作 alias） |
| `thread` | 按时间序累积，同一页持续更新 | 1（含演进史） |
| `schema_plus_timeline` | 读 schema + 每份抽关键指标 | 1 schema + 1 时间线 |
| `batch_summarize` | 多份合一（如邮件） | 1 摘要 |
| `skip` | 不入 wiki（noise，仅 manifest 留指针） | 0 |

##### Stage 5: Incremental & Lint

- 新文件：先 hash → 已有 skip；否则跑 Stage 2-4 单文件版
- 周期 lint：扫 wiki 找矛盾、过时、孤儿引用

##### 成本与时间估算

| 项目规模 | 首次 ingest 成本 | 时间 | 增量（1 新文件） |
|---------|-----------------|------|----------------|
| 100 文件 | ~$30 | ~1h | ~$0.3, ~20s |
| 300 文件 | ~$80 | ~3h | ~$0.5, ~30s |
| 1000 文件 | ~$200 | ~8h | ~$0.5, ~30s |

---

#### 七、 三类文档的特殊处理

##### 7.1 Word：多版本陷阱

默认 `latest_only` 策略。**只 ingest `_v_final` 或 mtime 最新**，旧版本：
- 在 canonical 页底部加 "Version history" 链接段
- 如果旧版与新版有重大决策反转，在 `decisions/<topic>.md` 用"曾经决定 X，后改为 Y 因为 Z"记录

##### 7.2 Excel：自动化报告陷阱

**最关键的一类**。30 份 `timing_report_w*.xlsx` 如果每份做一个 wiki 页就完蛋。

策略：
1. 检测 schema 一致 → 一个 cluster
2. 生成 `wiki/reports/timing_history.md`：
   - 顶部：schema 描述（来自第一份）
   - 中部：时间线表（每行一份报告，列是关键指标如 WNS/TNS/violating endpoints）
   - 底部：趋势分析（LLM 看到趋势写文字总结）
3. 单份原始 Excel 保留在 `raw/`，wiki 只放摘要

示例：

```markdown
# Timing Reports History

## Schema
| Column | Meaning |
| WNS | Worst negative slack |
| ...

## Timeline
| Week | WNS | TNS | Violations | Source |
| W08  | -150ps | -2300ps | 12 | [raw/.../w08.xlsx] |
| W12  | -50ps  | -800ps  | 4  | [raw/.../w12.xlsx] |
| W16  | 0ps    | 0ps     | 0  | [raw/.../w16.xlsx] |

## Trend
WNS 从 W08 的 -150ps 收敛到 W16 的 0ps，主要在 W12-W14 通过 ECO 修复 8 个关键路径。
```

##### 7.3 PPT：评审系列陷阱

评审 PPT 是**演进**不是**重复**。Week 12 评审 = Week 10 评审 + Δ。

策略：
1. 同 topic 同 series → thread cluster
2. **按时间序累积**到同一 wiki 页 `wiki/threads/floorplan_reviews.md`：
   - 顶部：当前最新结论
   - 中部：每次评审的 Δ（"W10 决定 X，W12 改为 Y 因为 Z"）
   - 底部：未决问题
3. 单张 slide 的图（截图、波形）保留在 `raw/<ppt>/images/`，wiki 用相对链接引用

---

#### 八、 跨项目经验复用机制（三条信息流）

项目 wiki 是单项目快照。要让历史项目对新项目有价值，需要三条独立信息流：

| 信息流 | 目的 | 何时跑 | 谁拥有 | 颗粒度 |
|--------|------|--------|--------|-------|
| **跨项目查询** | 找做过类似事的项目，看具体细节 | 新项目对话时 | 自动（结构化索引） | 项目级 |
| **模式提炼** | 多项目反复出现的做法 → 模式库 | 项目完成 + 周期 lint | LLM 写，人审 | 模式级 |
| **经验蒸馏** | 项目独特教训 → 专家库候选 | 项目完成 | LLM 写，人审，提升到 expert/ | 经验条目级 |

##### 流 1：跨项目查询 — `_global_index.md` 结构化元数据索引

**不用 embedding**。`projects/_global_index.md` 是 YAML 表格，LLM 读完后自然判断相似度：

```yaml
- id: projA
  status: tape_out_success
  tech_node: 7nm
  design_type: AI_accelerator
  die_size_mm2: 8
  power_target_mW: 500
  freq_target_GHz: 1.2
  memory_dominant: true
  hierarchical: false
  num_macros: 16
  num_clock_domains: 3
  duration_months: 8
  key_outcomes: ["WNS_0ps_signoff", "IR_drop_3%", "DRC_clean"]
  key_traps: ["mim_cap_density", "clock_domain_crossing_skew"]
  wiki_root: projects/projA/wiki/
  retrospective: projects/_retrospectives/projA_2025Q4.md

- id: projB
  status: in_progress_routing
  ...
```

**元数据来源**：在 Stage 4 深读 spec 时，LLM 顺手抽 `tech_node / design_type / ...`，写到 `<project>/wiki/index.md` frontmatter，再聚合到全局索引。

##### 流 2：模式提炼 — `_patterns/` 与 `_antipatterns/`

每个 `_patterns/<name>.md` 长这样：

```markdown
---
pattern: floorplan_memory_heavy
applies_when: memory_dominant=true AND die_size_mm2 > 4
confidence: high
last_updated: 2026-04-26
---

# Floorplan: Memory-Heavy Designs

## 做法
将主要 memory macros 放在 die 四角，预留 50um channel 给 power straps。

## 实证
| 项目 | 命中? | 效果 | 备注 |
|------|------|------|------|
| projA | ✓ | IR drop 3%，签收 | 16 个 SRAM，对称布局 |
| projB | ✓ | IR drop 4%，签收 | 8 个，加 MIM cap |
| projC | ✗ | IR drop 7%，重做 | 试了 center cluster |

## 不适用
- 小 die（< 2mm²）：四角浪费太多面积
- Memory 数 < 4：没必要专门策略

## 相关
- 反例: [_antipatterns/floorplan_corner_macros_small_die.md]
- UG: [eda_ug/.../floorplan_macro_placement.md]
- 专家: [expert/floorplan-tips.md]
```

**关键设计：**
- 每个模式带 `applies_when` 条件 → LLM 能判断"当前项目是否适用"
- 实证表列出哪些项目命中、效果如何
- 失败案例独立放 `_antipatterns/`，相互链接
- `confidence` 三档：`low / medium / high`

**生成与维护：**
- 项目完成时，LLM 扫该项目 wiki/decisions/ → 找哪些决策属于已有 pattern → 在实证表加一行
- LLM 提议**新 pattern 候选**（"projA 和 projB 都做了 X，没在 patterns 里"）→ 人审
- 模式失效自动降 confidence：lint 检查实证表 ✗ 比例

##### 流 3：经验蒸馏 — `_retrospectives/` + `expert/_pending/`

每个项目结束跑一次 `harvest`：

1. LLM 读完整项目 wiki（focus on `decisions/` + `log.md`）
2. 写 `_retrospectives/projX_<quarter>.md`：
   - 关键决策回顾
   - 实际效果 vs 预期
   - 踩坑（按时间顺序）
   - 下次项目应注意
3. 从复盘中提取候选专家经验，写入 `expert/_pending/`：

```markdown
---
source_project: projB
source_decision: projects/projB/wiki/decisions/cts_h_tree_failure.md
proposed_topic: cts-clock-domain-crossing
status: pending_review
---

# 候选经验：跨时钟域的 CTS skew 控制

## 来源情境
projB 5nm 低功耗设计，3 个时钟域，初期采用 H-tree 后发现跨域 skew > 100ps。

## 提炼建议
跨时钟域设计避免单一 H-tree，应每域独立 CTS + 显式跨域 buffer 控制。

## 证据强度
单项目（projB），需要更多案例验证。

[人审：accept / reject / edit / merge_with_existing]
```

**人审决定**：accept → 移到 `expert/<topic>.md`；reject → 删除；merge → 合并到现有 expert 条目。

**铁律重申**：`expert/` 始终人拥有，LLM 只能放候选到 `_pending/`。

---

#### 九、 典型场景演示

##### 场景 1：开始项目 C 的 floorplan 阶段

用户问："这个项目 floorplan 该怎么做？"

LLM 工作流：

```
1. 读 projects/_global_index.md
   → projC 是 7nm AI accelerator, memory_dominant=true, 8mm²
   → 找到相似: projA（同 7nm AI, memory-heavy, tape-out 成功）

2. 读 projects/_patterns/floorplan_memory_heavy.md
   → 模式适用（满足 applies_when）
   → 实证：projA 用了，效果好；projC 试过中心化失败
   → 推荐做法 + 警示

3. 读 expert/floorplan-tips.md
   → 一般性最佳实践（人沉淀的）

4. 读 projects/projA/wiki/decisions/floorplan_strategy.md
   → 类似项目的具体决策细节

5. 读 projects/_antipatterns/floorplan_corner_macros_small_die.md
   → 提醒：你这个 8mm²，处于阈值边界

6. 综合答复（标注每段来源支柱）
```

**精髓**：模式提供"框架"，专家提供"原则"，相似项目提供"细节"，反模式提供"警示"。每段来源可追溯。

##### 场景 2：项目结束后的复盘 + 蒸馏

用户触发 `harvest projB`：

```
1. LLM 读 projects/projB/wiki/ 全部
2. 生成 projects/_retrospectives/projB_2026Q1.md（人审）
3. 扫已有 patterns，更新实证表（projB 命中 floorplan_memory_heavy）
4. 提议新 pattern 候选（"projB 和 projA 都用了 X" → 写到提议区）
5. 提议 expert/_pending/ 新条目（CTS 跨域 skew 经验）
6. 人审决定：升级 / 拒绝 / 合并
```

---

#### 十、 实施路线

分 3 期，每期可独立验证。**强烈建议先小项目（< 50 文件）跑通，再上大项目**。

##### Phase 1：单项目 ingest 管线（基础）

| 任务 | 产物 |
|------|------|
| 基础解析器 | `parsers/{docx,xlsx,pptx}_to_markdown.py` |
| Stage 1+2 脚本 | `inventory.py` + `triage.py`（输出 manifest/triage.jsonl） |
| 检索 skill | `skills/read-project-doc/SKILL.md` |
| 在小项目验证 | 50 文件项目跑通完整 5 阶段 |

##### Phase 2：完整 ingest + 跨项目查询

| 任务 | 产物 |
|------|------|
| Stage 3+4 脚本 | `cluster.py` + `ingest.py`（含 cluster 策略调度） |
| Stage 5 增量 | 单文件触发的增量 ingest |
| `_global_index.md` 自动聚合 | spec ingest 时抽元数据 + 全局聚合脚本 |
| 跨项目查询 skill | `skills/recall-project-experience/SKILL.md` |
| 在 300 文件项目验证 | 完整成本与质量评估 |

##### Phase 3：跨项目经验复用（流 2 + 流 3）

**触发条件：知识库内有 ≥ 3 个完整项目**（模式提炼需要至少 3 个数据点）。

| 任务 | 产物 |
|------|------|
| 复盘脚本 | `harvest_project.py` |
| 复盘模板 | `_retrospectives/_template.md` |
| 模式提炼 | `extract_patterns.py`（扫 wiki + 写 candidates） |
| 反模式收集 | 复盘中追问"哪些决策事后看是错的" |
| `expert/_pending/` 流程 | 蒸馏 + 人审 + 升级脚本 |
| 跨支柱 lint | `lint_kb.py`（死链 + 矛盾 + confidence 调整） |

---

#### 十一、 待决策事项（开始实施前需确认）

##### 关于支柱命名
1. 是否将 `processed_eda` 改名为 `eda_ug`、`expert_base` 改名为 `expert`？（语义更准确，但破坏现有 skill 路径）

##### 关于项目文档 ingest
2. **三档 vs 双档 LLM**：Triage Haiku + Deep ingest Sonnet 是否够用？关键决策是否要上 Opus？
3. **noise 文件策略**：邮件/出勤表/草稿是 skip 不入 wiki 还是 batch 合并成低价值汇总页？倾向**skip 但 manifest 留指针**。
4. **版本文件**：仅 ingest `_v_final` 还是只要 mtime 最新？倾向**优先 mtime + 命名提示作辅助**。
5. **人审 checkpoint**：每阶段都暂停人审，还是只在 Stage 3 cluster 阶段暂停？倾向**triage 抽样 + cluster 全审**。
6. **raw/ 是否复制原件**：复制（自包含但占空间）vs 仅记录原路径（依赖原目录）。
7. **大 Excel 阈值**：500 行作为分级阈值？或固定保留全表？
8. **PPT 图片**：是否用 vision 模型给图加文字说明？显著增加 build 成本。
9. **多项目隔离**：是否需要"私密项目"机制（某些项目不参与跨项目检索）？

##### 关于跨项目复用
10. **何时触发 harvest**：仅项目完成时（`tape_out_success` 或 `aborted`），还是每个 stage 完成时也跑？倾向**仅完成时**。
11. **相似项目判定**：靠 LLM 读元数据自由判断，还是给硬规则（同 tech_node + 同 design_type 才算相似）？倾向**LLM 自由判断**。
12. **模式 confidence**：三档（low/medium/high）够用？还是数值 0-5？倾向**三档**。
13. **首版范围**：先上 Phase 1 + 流 1，等 3 个项目入库后启动流 2、3？倾向**是**。

---

#### 十二、 与现有系统的关系

##### 与现有 orchestrator workspace 的关系

`core/workflow/` 编排器在 workspace 下产出 `spec/`、`stages/`、`checkpoints/`。这些是**运行时**产物，`projects/` 是**沉淀知识**。两者关系：

- 编排运行结束后，由一个 `harvest_workspace` 步骤把关键产物（最终 spec、关键 eval_result、决策日志）摘要后落入 `projects/<name>/raw/`
- 不是同一份数据 — workspace 是过程档案，projects 是知识沉淀
- 此集成放到 Phase 2 之后，先不阻塞主线

##### 与现有 skills 的关系

新增 skill：

| Skill | 触发 | 调用 |
|-------|------|------|
| `read-project-doc` | "项目里"、"我们之前"、"评审记录" | 单项目 wiki 检索 |
| `recall-project-experience` | "之前的项目"、"经验"、"参考"、"类似的" | 跨项目（流 1 + 流 2） |

现有 skills 不变。`read-eda-concept` 在跨支柱场景下可读 `topics/<topic>.md` 后调用其他 skill。

##### 与 `docs/workflow.md`（Master Plan V3）的关系

本方案与 orchestrator 设计（`docs/workflow.md`）正交。orchestrator 负责"执行后端流程"，本方案负责"从历史资料中学习"。两者通过 `projects/` 的 `harvest_workspace` 步骤串接。

---

#### 附录 A：Karpathy LLM Wiki 核心思想摘要

来源：[gist.github.com/karpathy/442a6bf555914893e9891c11519de94f](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)（2026-04-03 发布）

**核心金句：**
- "The wiki is a persistent, compounding artifact" — wiki 是持续累积的产物
- "Knowledge that compounds rather than gets re-derived on every query" — 知识应累积，不应每次查询重新推导
- "维护知识库的繁琐部分不是阅读或思考，而是 bookkeeping" — LLM 的价值在接管 bookkeeping
- "人类不直接写 wiki，LLM 全权维护"（仅适用于其个人研究场景）

**三层架构：**
- `raw/` — 原件，不可改
- `wiki/` — LLM 全权拥有的合成 markdown
- schema 文件（如 CLAUDE.md）— 描述结构与约定

**三大工作流：**
- **Ingest**：新源 → LLM 读 → 与用户讨论 → 写摘要页 → 更新相关实体/概念页 → log
- **Query**：检索 wiki → 综合回答带引用 → 好的回答可回写为新页
- **Lint**：周期性健康检查（矛盾、过时、孤儿、缺失交叉引用）

**特殊文件：**
- `index.md`：按类别组织的内容目录
- `log.md`：append-only 时间日志，前缀可解析

**本方案的差异：**
- Karpathy 假设单一来源池且自己拥有所有内容；本方案三类知识所有权不同
- Karpathy 假设增量 ingest；本方案需处理首次数百份 bulk ingest
- Karpathy 跨页合成在存储时；本方案跨支柱合成在对话时
