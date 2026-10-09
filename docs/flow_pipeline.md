# AI 后端设计流程 · 架构与节点开发指引

> 本文档梳理自 `docs/flow_pipeline.html` 看板。
> 节点数据忠实还原自 `plugins/chip-backend-ai/templates/flow_definition.yaml`（9 stage / 41 节点）。

## 总览

顶部 **Spec 层（Phase 0）** 把一份总需求（PPA 目标 / 自然语言）经 AI 分析**扇出成各 stage 的约束并向下映射**；其下横向 = 9 个 stage，纵向 = 每个 stage 的**节点**。本图是**流程架构设计**，用于指导按节点开发各步的 AI 能力。

核心设计决策：

- **判断由决策 playbook skill 承接、主 agent 执行，无 sub-agent**。
- **节点四分类**：AI 决策 / 自动执行 / 自动校验 / 人工确认。
- **横切的执行/解析能力**（`run-eda-script`、`render-tcl`、`parse-eda-report`）单列在「共享能力」，不在节点上逐个重复。

### 节点类型图例

| 标记 | 含义 | 说明 |
|------|------|------|
| **AI 决策** | AI 决策步 | 标了实现它的 skill 名；是 AI 开发重点 |
| **自动执行** | 自动执行 | 合并成 1 卡，模板化脚本 |
| **自动校验** | 自动校验 / 质量门 | 解析报告产出 eval_result |
| **人工确认** | 人工 gate | `await_human` 暂停 |
| **GATE** | 阶段质量门 | 末步产出 `eval_result.yaml` 交状态机判 pass/fail |

### 关键统计

- **11 个 AI 决策步 → 9 个决策 skill**（floorplan 拆 3、route 拆 2，其余各 1）是 AI 开发重点。
- **自动执行**合并为模板化脚本卡。
- **质量门**共用 `parse-eda-report`。

---

## 一、Spec 层（Phase 0）

芯片后端从一份**人类主导的需求输入**（PPA 目标 + 约束）开始：先结构化成 `global_spec.yaml`，再把全局 PPA **预算分解**到每个 stage（`spec/stages/<stage>.yaml`），人类审批后进入流水线。之后每个 stage 开始时**读取它那份 spec**，作为只读的"北极星"喂给三类节点。Spec 层属于**状态机**，坐在 `flow_definition.yaml` 之上。

### Phase 0 流程（状态机）

```
机器级 bootstrap（流程之外·一次性）：env_manager detect/check 定位 Innovus —— 不 gate spec，resume 廉价校验
══════
INIT ─human_input─▶ SPEC_DRAFTING ─spec_ready─▶ SPEC_REVIEW ─human_approved─▶ SCHEDULING ─▶ STAGE_RUNNING
 人工：写 PPA       AI 决策 (spec-draft playbook)：     人工审批                       (flow_definition.yaml 接管)
 目标 + 约束        结构化 global_spec + 派生 per-stage spec
                              ◀── human_rejected / revise_spec ──（驳回，或目标不可达时回炉）
```

**"前置就绪"拆两半、各归其位**（不再是顶部一道胖闸）：

1. **env / 工具** = 机器级一次性 bootstrap（`env_manager`，**不 gate spec**，resume 廉价校验即可）→ 归底部基座带 env 卡。
2. **输入齐全 + 版本一致** = 数据准备 → 归 `import` 头部（flow_loader `blocked_inputs` 查存在 + 1 个 `version-check` skill 步查版本）。

### ① 人类需求输入 → global_spec.yaml

```yaml
human_goal: "..."            # 人类原始意图（原文保留）
target_ppa:
  timing: { wns_ns: -0.1, tns_ns: -1.0, hold_wns_ns: 0.0 }
  power:  { total_power_mw: null }
  area:   { utilization_min: 0.60, utilization_max: 0.80 }
global_constraints: { technology: "tsmc_n5", design_intent: "..." }
```

### ② 预算分解：global → 每个 stage 的要求

全局 PPA 不能直接套用，要把它"分预算"给各 stage —— 这本身是判断，故由 `spec-draft` 决策、人类确认：

| 全局目标 | 分解进 stage spec（节选） |
|----------|---------------------------|
| area util 0.60~0.80 | floorplan：utilization 目标 ~0.70 · channel ≥ X |
| timing wns ≤ -0.1ns | cts：skew/insertion 目标 · route：timing 目标 · timing_eco：收敛余量 |
| power 上限 | powerplan：IR/EM 预算 · placement/cts：功耗档位 |

**两点务必把握（决定 spec 该怎么用）：**

1. 这些 stage spec 是 **AI 预测、可重预算的"收敛检查点"**，不是 PPA 的硬切分合约 —— PPA 全流程涌现 + 强耦合，过紧的早期 gate 会造成假失败。
2. 只**分解 PPA 预算型**约束（timing/area/power，看板紫框卡）；**PDK/方法学固定型**约束（DRC/EM/density/corner，灰框卡）一律**加载、不由 AI 生成**。

### 两级 spec：Phase 0 初版（粗）→ 进 stage 时细化（细）

Phase 0 信息最少，派生出来的只是**初版 / 粗预算**。真正喂给某 stage 的 spec，是在**该 stage 进场时 just-in-time 生成**的：

```
本 stage 初版 spec（Phase 0）
    ＋ 上游已积累的真实信息（actual 指标 / 拥塞 / skew / 寄生 …）
    ＋ 人工补充输入（额外约束 / 偏好）
    ──spec-draft 细化──▶ 本 stage 最终 spec ──▶ 喂该 stage 三类节点
```

这就是"**滚动细化 rolling-wave**"：开局给粗计划当北极星，临到每个 stage 再用最新真实数据 + 人工把它那份 spec 调准。注意它和 ④ 的区别：这是**开跑前的前向细化**，④ 是 gate 失败后的**后向回炉**，两者互补。

### ③ 每个 stage 怎么用它那份 spec（喂三类节点）

```
stage 开始 → 读 spec/stages/<stage>.yaml
   ├─ metrics[].target      ──▶ 自动校验：gate 比对 actual vs target   ✅ 已接 parse-eda-report
   ├─ parameters / 目标      ──▶ AI 决策：作为判断依据与约束（决策 skill / 主 agent 读）
   └─ 全局 technology/corner ──▶ 自动执行：模板渲染参数
```

一句话：**spec 是从上往下喂的"北极星"**，和流水里流动的 def/db 产物是两条线 —— 后者是**设计状态**，前者是**"什么算达标"**。

### ④ spec 不是写死的：反馈回炉

某 stage gate 长期不过、目标不可达 → 状态机 `revise_spec` → 回 `SPEC_DRAFTING` 调 spec（如放宽某 stage 预算）→ 重新审批 → 继续流水线。

**现状**：`global_spec_template.yaml` / `stage_spec_template.yaml` / 状态机 SPEC_DRAFTING→SPEC_REVIEW / `spec_manager.py` 均已就位，`parse-eda-report` 已按 stage spec 的 metrics 做 gate。**待补**：把"global→stage 预算分解"明确成 spec-draft 的一步。

---

## 二、流程看板（9 stage × 各节点）

### Spec 带向下映射

总需求经 AI 分析扇出成 N 份**初版** stage spec（Phase 0 粗预算）：

| Stage spec 文件 | 类型 | 内容 |
|-----------------|------|------|
| `import.yaml` | 加载型 | 全局 tech/corner/库路径 |
| `floorplan.yaml` | PPA 预算 | util 目标 · channel |
| `powerplan.yaml` | PPA 预算 | IR / EM 预算 |
| `placement.yaml` | PPA 预算 | congestion / pre-CTS 检查点 |
| `cts.yaml` | PPA 预算 | skew / insertion 目标 |
| `route.yaml` | PPA 预算 | DRC / timing 检查点 |
| `timing_eco.yaml` | PPA 预算 | WNS / TNS / hold 目标 |
| `signoff.yaml` | 加载型 | DRC/LVS/IR/EM（多为 PDK deck） |
| `tapeout.yaml` | 加载型 | GDS / checklist（全局） |

### Stage 0 — import（数据准备）· 0 决策 skill · 全模板

| 节点 | 类型 | 决策/说明 | in → out |
|------|------|-----------|----------|
| 数据就绪 | 前置检查 | 输入齐全（flow_loader `blocked_inputs` 逐文件查，缺→人工补）；版本一致（netlist·SDC·lib·PDK 同 release，`version-check` skill 步） | input manifest → 齐 ✓ / blocked |
| 自动执行 | 模板化脚本 | `read_design` · `setup_mmmc` · `global_net_connect` · `check_design` | netlist·SDC·UPF·scan·LEF·多corner库 → import_done.db · check_design.rpt |
| import_eval | GATE | 导入质量门：库/约束完整性 → eval_result | check_design.rpt → eval_result.yaml |

### Stage 1 — floorplan（布局规划）· 3 决策 skill

| 节点 | 类型 | skill | 决策 | in → out |
|------|------|-------|------|----------|
| gen_floorplan | AI 决策 | `floorplan-plan` | die/core 尺寸 · aspect ratio · utilization | import_done.db → fp_init.def |
| place_io_pins | AI 决策 | `floorplan-io-pins` | IO pin 摆位/分组（block）或 pad ring（top） | fp_init.def → fp_pins.def |
| macro_placement | AI 决策 | `floorplan-macro` | macro 摆位 / 朝向 / channel（依数据流） | fp_pins.def → fp_macro.def |
| confirm_macro | 人工确认 | — | 人工确认 macro/pin 摆放合理 | fp_macro.def → 确认 / 调整 |
| add_blockage | AI 决策 | `floorplan-macro`（同上） | halo / placement blockage / voltage area | fp_macro.def → floorplan.def |
| floorplan_eval | GATE | — | utilization / channel → eval_result | floorplan.def → eval_result.yaml |

### Stage 2 — powerplan（电源规划）· 1 决策 skill

| 节点 | 类型 | skill | 决策 | in → out |
|------|------|-------|------|----------|
| gen_power_plan | AI 决策 | `powerplan-design` | ring/stripe 宽度·间距·pitch · sroute 策略（IR/EM 权衡） | floorplan.def → power_plan.tcl |
| 自动执行 | 模板化脚本 | — | `run_power_plan` · `insert_tap_decap` · `early_ir` | power_plan.tcl → pg_full.def · ir.rpt |
| power_eval | GATE | — | IR drop / 连通性 → eval_result | ir.rpt → eval_result.yaml |

### Stage 3 — placement（标准单元布局）· 1 决策 skill

| 节点 | 类型 | skill | 决策 | in → out |
|------|------|-------|------|----------|
| place_opt | AI 决策 | `placement-design` | util margin · congestion 驱动选项 · HFNS · tie cell | pg_full.def → placed.def |
| 自动执行 | 模板化脚本 | — | `scan_reorder` | placed.def → placed_scan.def |
| congestion_analysis | 自动校验 | — | Trial route 拥塞分析（非 gate） | placed_scan.def → congestion.rpt |
| placement_eval | GATE | — | congestion / pre-CTS timing → eval_result | congestion.rpt → eval_result.yaml |

### Stage 4 — cts（时钟树综合）· 1 决策 skill

| 节点 | 类型 | skill | 决策 | in → out |
|------|------|-------|------|----------|
| gen_cts_spec | AI 决策 | `cts-design` | target skew · NDR · leaf cell · skew group · exclude pin | placed_scan.def → cts.spec |
| 自动执行 | 模板化脚本 | — | `build_clock_tree` · `postcts_opt` | cts.spec → cts_opt.def · clock_tree.rpt |
| cts_eval | GATE | — | skew / insertion delay → eval_result | clock_tree.rpt → eval_result.yaml |

### Stage 5 — route（布线）· 2 决策 skill

| 节点 | 类型 | skill | 决策 | in → out |
|------|------|-------|------|----------|
| global_route | AI 决策 | `route-strategy` | 层分配 · NDR · shielding（关键/时钟网） | cts_opt.def → groute.def |
| detail_route | AI 决策 | `route-strategy`（同上） | NanoRoute 选项 · post-route 优化档位 | groute.def → routed.def |
| drc_repair | AI 决策 | `route-drc-repair` | 修哪些 DRC/antenna · 怎么修（search&repair / 冗余 via） | routed.def → routed_clean.def · drc.rpt |
| route_eval | GATE | — | DRC / open / timing → eval_result | drc.rpt → eval_result.yaml |

### Stage 6 — timing_eco（时序收敛/ECO）· 1 决策 skill

| 节点 | 类型 | skill | 决策 | in → out |
|------|------|-------|------|----------|
| 自动执行 | 模板化脚本 | — | `extract_rc` · `signoff_sta` | routed_clean.def → design.spef · timing.rpt |
| fix_strategy | AI 决策 | `timing-eco-design` | 修哪条路 · 手段（buffer / resize / useful skew / 重布） | timing.rpt → eco.changes |
| 自动执行 | 模板化脚本 | — | `apply_eco` | eco.changes · routed_clean.def → eco.def · eco_timing.rpt |
| timing_eval | GATE | — | WNS / TNS / hold 全 view → eval_result | eco_timing.rpt → eval_result.yaml |

### Stage 7 — signoff（物理验证）· 0 决策 skill · 模板+人工

| 节点 | 类型 | 说明 | in → out |
|------|------|------|----------|
| 自动执行 | 模板化脚本 | `metal_fill` · `signoff_drc_lvs` · `signoff_ir_em`（规则来自 PDK deck） | eco.def → filled.def · drc_lvs.rpt · ir_em.rpt |
| waiver_review | 人工确认 | 人工 review violation 并判定 waiver | drc_lvs.rpt · ir_em.rpt → waiver 判定 |
| signoff_eval | GATE | DRC/LVS clean · IR/EM 达标 → eval_result | drc_lvs.rpt → eval_result.yaml |

### Stage 8 — tapeout（GDS 交付）· 0 决策 skill · 模板+人工

| 节点 | 类型 | 说明 | in → out |
|------|------|------|----------|
| 自动执行 | 模板化脚本 | `chip_finishing` · `streamout` | filled.def → final.def · chip.gds |
| final_checklist | 人工确认 | 人工 tapeout checklist 终审 | chip.gds → 交付 |

### 基座（贯穿全流程，被各节点读取）

| 基座 | 状态 | 职责 |
|------|------|------|
| **环境 / 工具（env）** | 已建 `env_manager` | 机器级 `~/.chip-backend-ai/env.json` 定位 Innovus 二进制；**一次性机器 bootstrap**（detect → 人工 set → check，跨所有项目共享）；resume 只 `check` 廉价校验。**不 gate spec**，只需在 import（首个 EDA 步）前就绪 —— 即"前置就绪"的工具那半。 |
| **EDA 知识库（KB）** | 已建 | `search-eda-command`（命令语法 + 防幻觉护栏）· `read-expert-doc` · `read-eda-concept` · `read-eda-lab-doc`；**AI 决策**读它来正确生成 / 校验该怎么调 EDA 命令。 |
| **工艺 / PDK 数据** | 输入侧配置 | 多 corner Liberty · RC tech(QRC/captable) · LEF/metal stack · 特殊单元 · signoff decks(DRC/LVS/antenna) · EM-IR/fill 规则。import 用库、route 用 RC、signoff 用 deck → 相对稳定、贯穿全程。 |

> 节点站在基座上：自动执行靠 **env** 找工具、AI 决策靠 **KB** 知道怎么调命令、import/route/signoff 靠 **工艺/PDK** 拿库与规则。

> 每个 stage 末步（GATE）产出 `eval_result.yaml` 交回状态机判 pass/fail；上一 stage 的产出即下一 stage 首步输入，构成横向流水。

---

## 三、节点架构（一个节点内部怎么分层）

看板上每个节点不是单一动作，而是一条**内部流水线**。AI 的价值集中在 **① 决策** 和 **⑤ 诊断**；**② 渲染 / ③ 执行 / ④ 自动校验** 是确定性的**横切共享能力** —— 这就是为什么 `run-eda-script` 等不画在每个节点上，而是抽到这一层只出现一次。

### 内部流水线

```
① 决策 / 诊断   读 spec + 上游产出 + 上次 eval，定参数 + 写定制片段，产出 decisions.yaml
                谁：主 agent 执行决策 skill（playbook）；查：知识库；这一层 = AI 本体
   ▼
② 渲染          模板 *.tmpl + decisions → 具体 step.tcl
                谁：render-tcl（共享）+ per-step 模板；确定性，无判断
   ▼
③ 执行          跑 tcl，收 log，验产出 → def / db / rpt
                谁：run-eda-script（共享，1 个）；经 env_manager 解析路径；工具不可用时 stub 降级
   ▼
④ 自动校验      解析报告 → eval_result.yaml（指标 vs target）
                谁：parse-eda-report（共享，1 个）；确定性，不做决策

⟲ 不达标：带上次 eval 回到 ①，让主 agent 据同一份 playbook 诊断后重新决策
```

### ① 决策时查的知识库

| 知识库 skill | 用途 |
|--------------|------|
| `read-eda-concept` | 这个旋钮起什么作用 |
| `read-expert-doc` | 该 stage 的专家经验/启发式 |
| `read-eda-lab-doc` | lab 示例（写片段参考） |
| `search-eda-command` | **护栏**：AI 写的每条命令先校验确实存在 |

> 知识系统（子系统①）由此接入编排系统（子系统②）：知识库不只给人看，更是主 agent 写脚本/诊断时的随身手册。

### 每一层"每步是否不同""复用粒度"

| 层 | 谁负责 | 每步不同？ | 复用粒度 | 是不是 skill |
|----|--------|-----------|----------|--------------|
| ① 决策 | 决策 skill（playbook）+ 主 agent | 是（判断逻辑不同） | 按复杂度：stage 或 step | 是，**playbook skill** |
| 跑哪段命令 | 模板 `*.tmpl` | 是（内容不同） | 每 step 一份模板 | 否，是**数据** |
| ② 渲染 | `render-tcl` | 否 | 全流程共享 | 是，**1 个共享** |
| ③ 执行 | `run-eda-script` | 否 | 全流程共享 | 是，**1 个共享** |
| ④ 自动校验 | `parse-eda-report` | 否 | 全流程共享 | 是，**1 个共享** |

> **结论**："每步专属的东西"是真的 —— 它活在**模板（数据）**和**决策 skill 的判断方法（playbook）**里；判断 skill 由**主 agent 执行（无 sub-agent）**。执行/渲染/自动校验这类机制横切共享，所以 `run-eda-script` 该多就让它多，但只此一个、且不画在节点上。

---

## 四、节点开发指引（给同事）

按节点类型对照开发。**AI 决策步**是主要工作量；自动执行/质量门/人工只需很少配置。

### AI 决策步 — 完整六步（如 floorplan / cts / route / eco）

1. **写黄金模板** `templates/tcl/<stage>/<step>.tcl.tmpl`：固定骨架 + `{{占位符}}` + `### @inject:` 定制片段注入点。
2. **定决策契约**：约定该 step 的 `<step>_decisions.yaml` 长什么样 —— `params`（要填的参数）/ `fragments`（AI 写的片段）/ `rationale`（理由，便于审计）。
3. **实现决策逻辑**（写进该步的**决策 skill / playbook**，主 agent 执行）：读 spec + 上游产出 + 上次 eval → 推理出 decisions。这是该节点真正的"AI"。
4. **接知识库 + 护栏**：决策查 `read-expert-doc`/`read-eda-concept`；写片段查 `read-eda-lab-doc`；**AI 写的每条命令必须过 `search-eda-command` 校验存在**（防幻觉）。
5. **复用共享层执行**：decisions + 模板 → `render-tcl` → `run-eda-script` → `parse-eda-report`。**不要自己写执行/解析代码。**
6. **配 flow_definition.yaml**：把该节点写成 `gen → run → eval` 三元组并声明 inputs/outputs；重跑时把上次 eval 作为 gen 的额外输入（诊断回路）。

### 自动执行 / 质量门 / 人工确认

| 类型 | 开发什么 |
|------|----------|
| 自动执行 | 只需第 ①、⑤、⑥ 步里的"模板 + 接执行"：写一份模板，参数直接来自 spec（无需判断），再走 `render-tcl → run-eda-script`。 |
| 质量门 | 无需写代码：在 stage spec 里声明该门的 `metrics`（名称 + target），节点执行者填 `parse-eda-report` 即可。指标提取不准时给该指标加 `pattern:` 覆盖。 |
| 人工确认 | 只写 `instruction`（让人做什么）。流程到此 `await_human` 暂停，人工完成后 `resolve-human` 继续。 |

### 红线（所有节点共同遵守）

- **执行永远用共享 `run-eda-script`**，别为某步单独写执行代码（否则就是 N 份雷同代码）。
- **AI 写的 Tcl 命令必须过 `search-eda-command` 校验**，约束在真实命令空间内 —— 防幻觉的关键。
- **每个 AI 决策落成 `decisions.yaml`**：可审计、人可改了 re-render、新会话可续跑。
- **stub 不造假**：工具缺失时产占位让流程结构走通，但绝不伪造 PPA 数字，下游 gate 如实报 missing。

### 判断放哪 & 决策 skill 怎么切分

判断不交给独立 sub-agent，而是写成**决策 playbook skill**（"怎么判断"的手册），由**主 agent** 加载执行 —— skill 装**方法 / rubric**，运行时主 agent 对这颗芯片的真实数字现场推理，产出 `decisions.yaml`。skill **不**装"结果"（每颗芯片都不同）。

**切分判据：默认 1 个 stage 1 个 skill；满足任一条就把该 step 单拎成独立 skill：**

1. 它自身**决策 / 知识量大**，一个 playbook 写下去又长又散焦；
2. 它有**独立的诊断 / 迭代回路**（如 drc_repair、fix_strategy）；
3. 它会被**单独复用**（人工或别的流程直接调它）；
4. 它和同 stage 其他步**知识体系不同**，硬合并会四不像。

反之：步骤短、共享同一套知识、总是一起做 → 合在一个 stage skill 里。**务实做法**：先按 stage 起步，写胖了 / 要独立复用了再拆；floorplan、route 已知较重，可一上来就拆好。

### 推荐决策 skill 清单（复杂度驱动，9 个）

| 决策 skill | 覆盖的 AI 决策步 | 来由 |
|------------|------------------|------|
| `floorplan-plan` | gen_floorplan | floorplan 4 步较重 → 拆 3 |
| `floorplan-io-pins` | place_io_pins | floorplan 4 步较重 → 拆 3 |
| `floorplan-macro` | macro_placement + add_blockage（halo 紧耦合 macro） | floorplan 4 步较重 → 拆 3 |
| `powerplan-design` | gen_power_plan | 单 AI 决策步 |
| `placement-design` | place_opt | 单 AI 决策步 |
| `cts-design` | gen_cts_spec | 单 AI 决策步 |
| `route-strategy` | global_route + detail_route（布线引擎配置，知识重叠） | route 3 步较重 → 拆 2 |
| `route-drc-repair` | drc_repair（迭代 search&repair，另一套心智模型） | route 3 步较重 → 拆 2 |
| `timing-eco-design` | fix_strategy | 单 AI 决策步 |

> 切分对比：按 stage = 6 个（floorplan 会太胖 ❌）；按 step = 11 个（powerplan/cts 等被无谓拆碎 ❌）；**复杂度驱动 = 9 个 ✅**。

> **封装红线**：即便把 AI 决策步打包成独立 skill，它也只装**判断方法（playbook）+ 模板引用**；渲染委托共享 `render-tcl`、执行委托共享 `run-eda-script`。**绝不**在决策 skill 里重写执行逻辑，也**绝不**做 per-step 的执行 skill。

---

## 五、共享能力 & 数据流

### 共享能力（横切，不在节点上重复）

这些是被所有 stage 反复复用的确定性能力。它们是流程的"手和尺"，AI 是"脑"。正因为横切，本图不在每个节点上重画它们。

| 能力 | 类型 | 状态 | 职责 |
|------|------|------|------|
| `render-tcl` | skill | 待建 | 模板 `*.tmpl` + `decisions.yaml` → 具体 `step.tcl`（确定性渲染） |
| `run-eda-script` | skill | 已建 | 跑 tcl、收 log、验产出；工具不可用时 stub 降级。**所有执行步共用这一个。** |
| `parse-eda-report` | skill | 已建 | 报告 → `eval_result.yaml`；全部 8 个质量门 + congestion 分析共用。 |
| `env_manager` | 基座 | 已建 | 定位 EDA 工具二进制（detect / set / check）；机器级 `~/.chip-backend-ai/env.json`，自动执行调用时解析路径 → **工程可移植**。 |
| `version-check` | import 步 | 待建 | 数据准备：校验 netlist·SDC·lib·PDK 同一 release（确定性、可复用）。 |

**取舍：为什么没有独立的"前置就绪"闸 / 胖 readiness-check skill？**

早先想把 **工具 + 输入齐全 + 版本一致** 合成一个横跨三者的胖 readiness-check 放流程最前、且"每次会话都重跑"。复盘后拆开各归其位 —— 因为三块的**作用域和生命周期都不同**：

1. **env / 工具**：机器级、跨所有项目共享、存在 workspace **之外**（`env.json`）—— 既塞不进 flow_loader 的输入模型（它只认 workspace 文件），也不该塞进 import（否则每个新项目都重找工具）。故它是**机器 bootstrap**，**不 gate spec**（spec 不调工具），resume 只 `check` 廉价校验。
2. **输入齐全**：flow_loader 的 `blocked_inputs` 逐文件查存在**本就免费做了**，跑到 import 自然拦。
3. **版本一致**：一个确定性 `version-check` skill 步，放 import 头部。

**结论**：三块都有现成的家，不必再造一个胖闸。"每次会话都重跑"也被收回 —— 只对 env 的廉价 `check` 成立；②③ 是普通 flow 步、跑一次即 `done`，resume 不重跑。

### 判断由谁承接：决策 playbook skill + 主 agent（无 sub-agent）

判断型步骤不再交给独立 sub-agent，而是把"判断方法"写进决策 **playbook skill**，由**主 agent** 加载执行。

| 执行者 | 承担 |
|--------|------|
| **主 agent** + 决策 playbook skill ×9 | 全部 11 个 AI 决策步 |
| human | confirm_macro · waiver_review · final_checklist |

### 主数据流（DEF/DB 链）

每步 output 是下一步 input，依赖关系即由此构成；引擎据此判断输入是否就位、能否续跑。

```
netlist+lef+lib → imported.db → mmmc.db → import_done.db → fp_init.def → fp_pins.def → fp_macro.def → floorplan.def
floorplan.def → power_plan.tcl → pg.def → pg_full.def → placed.def → placed_scan.def
placed_scan.def → cts.spec → cts.def → cts_opt.def → groute.def → routed.def → routed_clean.def
routed_clean.def → design.spef → timing.rpt → eco.changes → eco.def → filled.def → final.def → chip.gds
```

### 启动输入清单（按「输入信息」vs「基座信息」分类）

| 类别 | 内容 | 归类 | 主要用在 |
|------|------|------|----------|
| **设计数据** | netlist(.v) · SDC · UPF/CPF 电源意图 · DFT/scan · activity(SAIF/VCD) | 输入 | import 进，随流程流动 |
| **Macro / IP** | 硬核 macro 的 LEF/GDS/lib/CDL + 集成约束(halo/keep-out) | 输入 | import / floorplan |
| **物理约束** | die/core 尺寸 · IO/pad/pad ring · macro 摆放指引 · PG 策略 | 输入 | floorplan / powerplan |
| **工艺 / PDK** | 多 corner Liberty · RC tech · LEF/metal stack · 特殊单元 · signoff decks · EM-IR/fill 规则 | 基座 | 贯穿(import/route/signoff) |
| **分析配置** | MMMC 视图矩阵(corner × mode) · PVT | 基座 | setup_mmmc / 全程时序 |
| **工具 / 环境** | Innovus + 工具链路径(`env.json`) · 算力/grid | 基座 | 所有自动执行 |
| **项目元信息** | 层次(top/block) · tapeout 日期 · foundry/shuttle | spec | Spec 层 / 全局 |

> **输入信息** = 设计专属、从起点喂入、随流程流动；**基座信息** = 工艺/工具/知识，相对稳定、贯穿全程被节点读取。**工具/环境**由机器级 `env_manager` bootstrap 定位；**设计数据**的"齐不齐 + 版本一致"在 `import` 头部检查（flow_loader `blocked_inputs` + `version-check`）后进流水线。
