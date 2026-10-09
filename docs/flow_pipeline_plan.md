# AI 后端设计流程 — 方案文档（实现依据）

> 本文是 `docs/flow_pipeline.html`（流程看板）收敛后的文字版方案，用于指导后续按节点开发各步的 AI 能力。
> 定位：**AI 辅助的芯片后端（物理设计）开发设计流程**，不是"知识帮助执行"。
> 关键取向（本轮已定）：**无 sub-agent**（判断 = 决策 playbook skill，主 agent 现场执行）+ **节点四分类** + **Spec = Phase 0** + **前置就绪拆三块各归其位**。

---

## 1. 架构总览

### 1.1 两层驱动（互不替代）

```
┌─ 元生命周期（state_manager.py）────────────────────────────────┐
│  机器级 bootstrap(env)  ……  不 gate spec、流程之外、一次性        │
│  INIT ─human_input─▶ SPEC_DRAFTING ─spec_ready─▶ SPEC_REVIEW      │
│        ─human_approved─▶ SCHEDULING ⇄ STAGE_RUNNING ─▶ COMPLETED  │
│        (审批 / retry budget / rollback / abort 都在这一层)         │
└──────────────────────────┬───────────────────────────────────────┘
                           │ STAGE_RUNNING 内部
┌──────────────────────────▼───────────────────────────────────────┐
│  步级驱动（flow_loader.py + flow_definition.yaml）                  │
│  next → {run | await_human | blocked_inputs | blocked | complete} │
│  磁盘即真相：required outputs 已存在 = 自动判 done，新会话可续跑     │
└───────────────────────────────────────────────────────────────────┘
```

- **state_manager.py**：管元生命周期。它**只记账**（记录合法 transition），不"做事"。
- **flow_loader.py**：只活在 `STAGE_RUNNING` 内，驱动 `flow_definition.yaml` 的"下一步跑什么、用什么执行者、读写哪些文件"。
- **run-chip-flow（编排器 skill）**：唯一决策中心，调上面两者、把门、调度。

### 1.2 无 sub-agent

判断型步骤**不再**交给独立 sub-agent，而是写成**决策 playbook skill**（"怎么判断"的手册 / rubric），由**主 agent 加载执行**。

- skill 装**方法**，运行时主 agent 对这颗芯片的真实数字现场推理，产出 `decisions.yaml`；skill **不**装"结果"（每颗芯片都不同）。
- 取舍：换"上下文连续"、丢"上下文隔离"，靠**磁盘优先 + 按需加载 skill** 控上下文。
- `agents/*`（spec/floorplan/cts/route/timing-eco）计划迁移成 skill；`flow_definition.yaml` 里 `type:agent` 待改 `type:skill`。

### 1.3 节点四分类

| 类型 | 含义 | 实现落点 |
|------|------|---------|
| **AI 决策** | 需要判断（参数/策略/写定制片段） | 决策 playbook skill + 主 agent，产出 `decisions.yaml` |
| **自动执行** | 模板化脚本即可，跨项目复用、无需判断 | `render-tcl`（模板+decisions→tcl）→ `run-eda-script` |
| **自动校验** | 解析报告比对 target，质量门 | `parse-eda-report` → `eval_result.yaml` |
| **人工确认** | 必须人来拍板 | flow step `type:human`，`await_human` / `resolve-human` |

---

## 2. 信息分类：基座 / 输入 / spec

| 类别 | 内容 | 归类 | 主要用在 |
|------|------|------|---------|
| 设计数据 | netlist(.v) · SDC · UPF/CPF · DFT/scan · activity(SAIF/VCD) | **输入** | import 进，随流程流动 |
| Macro / IP | 硬核 macro 的 LEF/GDS/lib/CDL + 集成约束(halo/keep-out) | **输入** | import / floorplan |
| 物理约束 | die/core 尺寸 · IO/pad ring · macro 摆放指引 · PG 策略 | **输入** | floorplan / powerplan |
| 工艺 / PDK | 多 corner Liberty · RC tech · LEF/metal stack · 特殊单元 · signoff decks · EM-IR/fill 规则 | **基座** | 贯穿(import/route/signoff) |
| 分析配置 | MMMC 视图矩阵(corner × mode) · PVT | **基座** | setup_mmmc / 全程时序 |
| 工具 / 环境 | Innovus + 工具链路径(`env.json`) · 算力/grid | **基座** | 所有自动执行 |
| 项目元信息 | 层次(top/block) · tapeout 日期 · foundry/shuttle | **spec** | Spec 层 / 全局 |

- **输入** = 设计专属、从起点喂入、随流程流动。
- **基座** = 工艺/工具/知识，相对稳定、贯穿全程被节点读取。三大基座 = **env（工具）+ EDA 知识库 + 工艺/PDK**。
- license 不单列（有工具即有 license）。

---

## 3. 前置就绪（收敛设计 ★ 本轮重点）

**结论：不存在"顶部统一胖 readiness-check 闸 + 每次会话重跑"。** 拆三块各归其位，因为三块的**作用域和生命周期都不同**：

| 块 | 归属 | 实现 | 生命周期 |
|----|------|------|---------|
| ① **env / 工具** | 机器级 bootstrap | `env_manager`（已建）detect→人工 set→check | 跨所有项目共享；**不 gate spec**；resume 只 `check` 廉价校验、stale 才重 detect |
| ② **输入齐全** | import 头部 | flow_loader 的 `blocked_inputs` 逐文件查存在（**已有、免费**） | 普通 flow 步，跑一次即 done，resume 不重跑 |
| ③ **版本一致** | import 头部 | 确定性 `version-check` skill 步（**待建**）：netlist·SDC·lib·PDK 同一 release | 普通 flow 步，跑一次即 done |

**为什么不做成一个横跨三者的胖闸 / 不塞进 flow_loader / 不塞进 import：**
- env/工具是**机器级**、存在 workspace **之外**（`~/.chip-backend-ai/env.json`）—— 既塞不进 flow_loader 的输入模型（它只认 workspace 相对文件），也不该塞进 import（否则每个新项目都重找一遍工具，作用域错了）。
- "输入齐不齐"flow_loader 的 `blocked_inputs` 本就免费做了；"版本一致"是一个确定性 skill 步即可。
- 三块都有现成的家，不必再造胖闸。"每次会话都重跑"被收回——只对 env 的廉价 `check` 成立。

> 备注：env/工具就绪**不 gate spec**（spec 起草不调 Innovus），只需在 import（首个 EDA 步）前就绪。

---

## 4. Spec 层（Phase 0）

人类需求（PPA 目标 + 约束）→ 结构化 `global_spec.yaml` → **预算分解**到每个 stage（`spec/stages/<stage>.yaml`）→ 人类审批 → 进流水线。之后每个 stage **读它那份 spec**，作为只读"北极星"喂三类节点。

### 4.1 两点务必把握
1. stage spec 是 **AI 预测、可重预算的"收敛检查点"**，不是 PPA 的硬切分合约 —— PPA 全流程涌现 + 强耦合，过紧的早期 gate 会造成假失败。
2. 只**分解 PPA 预算型**约束（timing/area/power）；**PDK/方法学固定型**约束（DRC/EM/density/corner）一律**加载、不由 AI 生成**。

### 4.2 两级 spec（rolling-wave 滚动细化）
```
本 stage 初版 spec（Phase 0 粗预算，信息最少）
    ＋ 上游已积累的真实信息（actual 指标 / 拥塞 / skew / 寄生 …）
    ＋ 人工补充输入（额外约束 / 偏好）
    ──spec-draft 细化──▶ 本 stage 最终 spec ──▶ 喂该 stage 三类节点
```
- 前向细化（开跑前 just-in-time）与后向 `revise_spec`（gate 失败后回炉）互补。

### 4.3 stage 怎么用 spec（喂三类节点）
```
读 spec/stages/<stage>.yaml
 ├─ metrics[].target      ──▶ 自动校验：gate 比对 actual vs target（parse-eda-report）
 ├─ parameters / 目标      ──▶ AI 决策：判断依据与约束（决策 skill / 主 agent 读）
 └─ 全局 technology/corner ──▶ 自动执行：模板渲染参数
```

---

## 5. 三层驱动机制

| 驱动什么 | 谁驱动 | 怎么驱动 |
|---------|-------|---------|
| **前置就绪/env** | 编排器（Phase 0） | `env_manager check`，stale→`detect`/人工 `set`；不 gate spec；resume 廉价复查 |
| **Spec 阶段** | 编排器 + state_manager | `human_input`→draft→`spec_ready`→人审→`human_approved`；失败 `revise_spec` 回炉 |
| **stage 内步级** | flow_loader | `next` 取动作 → 按 `executor.type` 分派 → `mark`/`resolve-human` → 循环到 `flow_complete` |

`flow_loader.next` 的动作语义：
- `run`：按 `executor.type`（skill/agent/human）分派；成功 `mark done`，失败 `mark failed`。
- `await_human`：暂停，转达 `instruction`，人工完成后 `resolve-human`。
- `blocked_inputs`：required 输入缺失（这就是"输入齐全"检查），提示人工补，不伪造。
- `blocked`：步 failed / 卡 running，交回 state_manager 判 retry/rollback。
- `flow_complete`：推进 state_manager 向 COMPLETED。

---

## 6. 9 stage × 节点全景

> 列：**AI 决策步**（标决策 skill）/ **自动执行**（模板化脚本，合并一卡）/ **自动校验 GATE** / **人工确认**。

| # | stage | 决策 skill 数 | AI 决策步（决策内容） | 自动执行（模板脚本） | 质量门 GATE / 校验 | 人工确认 |
|---|-------|:---:|------|------|------|------|
| 0 | **import**<br>数据准备 | 0 | — | read_design · setup_mmmc · global_net_connect · check_design | **数据就绪**（blocked_inputs + `version-check`）· **import_eval**（库/约束完整性） | — |
| 1 | **floorplan**<br>布局规划 | 3 | gen_floorplan（die/core 尺寸·aspect·util）· place_io_pins（IO pin/pad ring）· macro_placement（摆位/朝向/channel）· add_blockage（halo/blockage/voltage area） | — | **floorplan_eval**（util / channel） | confirm_macro |
| 2 | **powerplan**<br>电源规划 | 1 | gen_power_plan（ring/stripe 宽度·间距·pitch·sroute，IR/EM 权衡） | run_power_plan · insert_tap_decap · early_ir | **power_eval**（IR drop / 连通性） | — |
| 3 | **placement**<br>标准单元布局 | 1 | place_opt（util margin·congestion 驱动·HFNS·tie cell） | scan_reorder | congestion_analysis（非 gate）· **placement_eval**（congestion / pre-CTS timing） | — |
| 4 | **cts**<br>时钟树综合 | 1 | gen_cts_spec（target skew·NDR·leaf cell·skew group·exclude pin） | build_clock_tree · postcts_opt | **cts_eval**（skew / insertion delay） | — |
| 5 | **route**<br>布线 | 2 | global_route（层分配·NDR·shielding）· detail_route（NanoRoute 选项·post-route 档位）· drc_repair（修哪些·怎么修） | — | **route_eval**（DRC / open / timing） | — |
| 6 | **timing_eco**<br>时序收敛/ECO | 1 | fix_strategy（修哪条路·手段 buffer/resize/useful skew/重布） | extract_rc · signoff_sta / apply_eco | **timing_eval**（WNS / TNS / hold 全 view） | — |
| 7 | **signoff**<br>物理验证 | 0 | — | metal_fill · signoff_drc_lvs · signoff_ir_em | **signoff_eval**（DRC/LVS clean · IR/EM 达标） | waiver_review |
| 8 | **tapeout**<br>GDS 交付 | 0 | — | chip_finishing · streamout | — | final_checklist |

---

## 7. 决策 skill 切分

### 7.1 判据
**默认 1 个 stage 1 个 skill；满足任一条就把该 step 单拎成独立 skill：**
1. 它自身**决策/知识量大**，一个 playbook 写下去又长又散焦；
2. 它有**独立的诊断/迭代回路**（如 drc_repair、fix_strategy）；
3. 它会被**单独复用**（人工或别的流程直接调它）；
4. 它和同 stage 其他步**知识体系不同**，硬合并会四不像。

> 务实做法：先按 stage 起步，写胖了/要独立复用了再拆；floorplan、route 已知较重，可一上来就拆好。
> 对比：按 stage=6 个（floorplan 太胖 ❌）；按 step=11 个（powerplan/cts 被无谓拆碎 ❌）；**复杂度驱动=9 个 ✅**。

### 7.2 推荐 9 个决策 skill

| 决策 skill | 覆盖的 AI 决策步 | 来由 |
|-----------|----------------|------|
| `floorplan-plan` | gen_floorplan | floorplan 4 步较重 → 拆 3 |
| `floorplan-io-pins` | place_io_pins | 同上 |
| `floorplan-macro` | macro_placement + add_blockage（halo 紧耦合 macro） | 同上 |
| `powerplan-design` | gen_power_plan | 单 AI 决策步 |
| `placement-design` | place_opt | 单 AI 决策步 |
| `cts-design` | gen_cts_spec | 单 AI 决策步 |
| `route-strategy` | global_route + detail_route（布线引擎配置，知识重叠） | route 3 步较重 → 拆 2 |
| `route-drc-repair` | drc_repair（迭代 search&repair，另一套心智模型） | 同上 |
| `timing-eco-design` | fix_strategy | 单 AI 决策步 |

---

## 8. 节点内部架构

### 8.1 运行时流水线（每个 AI 决策节点是一条内部流水线）
```
① 决策 / 诊断 ─▶ ② 渲染 ─▶ ③ 执行 ─▶ ④ 自动校验
  (主 agent      (render-tcl   (run-eda-     (parse-eda-
   +playbook)     +模板)        script)       report)
  ▲                                              │
  └────────── ⟲ 不达标：带上次 eval 回 ① ─────────┘
```
- AI 的价值集中在 **① 决策** 与 **诊断回路**；②③④ 是确定性**横切共享能力**（所以不画在每个节点上、抽到共享层只出现一次）。

### 8.2 开发一个 AI 决策步的六步配方
1. **写黄金模板** `templates/tcl/<stage>/<step>.tcl.tmpl`：固定骨架 + `{{占位符}}` + `### @inject:` 注入点。
2. **定决策契约** `<step>_decisions.yaml`：`params`（要填的参数）/ `fragments`（AI 写的片段）/ `rationale`（理由，便于审计）。
3. **实现决策逻辑**（写进该步的决策 skill/playbook，主 agent 执行）：读 spec + 上游产出 + 上次 eval → 推理出 decisions。这是该节点真正的 "AI"。
4. **接知识库 + 护栏**：决策查 `read-expert-doc`/`read-eda-concept`；写片段查 `read-eda-lab-doc`；**AI 写的每条命令必须过 `search-eda-command` 校验存在（防幻觉）**。
5. **复用共享层执行**：decisions + 模板 → `render-tcl` → `run-eda-script` → `parse-eda-report`。**不要自己写执行/解析代码。**
6. **配 flow_definition.yaml**：把该节点写成 `gen → run → eval` 三元组并声明 inputs/outputs；重跑时把上次 eval 作为 gen 的额外输入（诊断回路）。

### 8.3 其余三类怎么开发
- **自动执行**：只写模板（参数直接来自 spec，无需判断）+ 走 `render-tcl → run-eda-script`。
- **自动校验/质量门**：无需写代码 —— 在 stage spec 声明 `metrics`（名称+target），执行者跑 `parse-eda-report`；提取不准给该指标加 `pattern:` 覆盖。
- **人工确认**：只写 `instruction`；流程 `await_human` 暂停，人工完成 `resolve-human` 继续。

### 8.4 红线（所有节点共同遵守）
- **执行永远用共享 `run-eda-script`**，别为某步单独写执行代码。
- **AI 写的 Tcl 命令必须过 `search-eda-command` 校验**，约束在真实命令空间内（防幻觉关键）。
- **每个 AI 决策落成 `decisions.yaml`**：可审计、人可改了 re-render、新会话可续跑。
- **stub 不造假**：工具缺失时产占位让流程结构走通，但绝不伪造 PPA 数字，下游 gate 如实报 missing。

---

## 9. 共享能力清单（横切，不在节点上重复）

| 能力 | 类型 | 状态 | 职责 |
|------|------|------|------|
| `render-tcl` | skill | ⏳ 待建 | 模板 `*.tmpl` + `decisions.yaml` → 具体 `step.tcl`（确定性渲染） |
| `run-eda-script` | skill | ✅ 已建 | 跑 tcl、收 log、验产出；工具不可用 stub 降级。所有执行步共用 |
| `parse-eda-report` | skill | ✅ 已建 | 报告 → `eval_result.yaml`；全部 8 个质量门 + congestion 分析共用 |
| `env_manager` | 基座 | ✅ 已建 | 定位 EDA 工具二进制（detect/set/check）；机器级 `~/.chip-backend-ai/env.json`，工程可移植 |
| `version-check` | import 步 | ⏳ 待建 | 校验 netlist·SDC·lib·PDK 同一 release（确定性、可复用）。"输入齐不齐"由 `blocked_inputs` 覆盖、工具由 `env_manager` 覆盖 |

**知识库（基座）**：`search-eda-command`（命令语法 + 防幻觉护栏）· `read-expert-doc` · `read-eda-concept` · `read-eda-lab-doc`。AI 决策读它来正确生成/校验该怎么调 EDA 命令。

---

## 10. 主数据流（DEF/DB 链）

每步 output 是下一步 input，依赖关系即由此构成；引擎据此判断输入是否就位、能否续跑。
```
netlist+lef+lib → imported.db → mmmc.db → import_done.db → fp_init.def → fp_pins.def → fp_macro.def → floorplan.def
floorplan.def → power_plan.tcl → pg.def → pg_full.def → placed.def → placed_scan.def
placed_scan.def → cts.spec → cts.def → cts_opt.def → groute.def → routed.def → routed_clean.def
routed_clean.def → design.spef → timing.rpt → eco.changes → eco.def → filled.def → final.def → chip.gds
```

---

## 11. 实现清单（TODO）

### 已就位 ✅
- 编排骨架：`core/workflow/{state_manager,flow_loader,spec_manager,decision_logger,workspace}.py`
- 共享执行/解析：`skills/run-eda-script`、`skills/parse-eda-report`
- 环境基座：`core/env/env_manager.py`
- spec 脚手架：`templates/{global_spec,stage_spec}_template.yaml`、SPEC_DRAFTING/REVIEW
- 编排器 skill：`skills/run-chip-flow`（Phase 0 env prep 已含）

### 待建 / 待改 ⏳

**P0（打通 AI 决策闭环的最小集）**
1. `skills/render-tcl`：模板 + decisions → tcl（共享渲染层）。
2. 黄金模板目录 `templates/tcl/<stage>/<step>.tcl.tmpl` + 各 step 的 `<step>_decisions.yaml` 契约。
3. 先做 1 个决策 skill 跑通端到端：建议 `cts-design` 或 `placement-design`（单步、闭环短）。
4. `flow_definition.yaml`：`type:agent` → `type:skill`；按 §8.2 第 6 步把决策步写成 `gen→run→eval` 三元组、重跑把上次 eval 喂回 gen。

**P1（前置就绪收敛落地）**
5. `skills/version-check`：netlist·SDC·lib·PDK 同 release 校验，作为 import 头部 skill 步加入 `flow_definition.yaml`。
6. import lane 头部声明"数据就绪"：依赖 `blocked_inputs`（已有）+ `version-check`（新增）。
7. `run-chip-flow` 文案校正：env = 机器级 bootstrap，**不 gate spec**，resume 廉价复查（现 Phase 0 即可，去掉"胖 readiness gate"的描述）。

**P2（铺满决策层 + spec 细化）**
8. 其余 8 个决策 playbook skill（见 §7.2），每个按 §8.2 六步配方开发，统一接 §8.4 红线。
9. `spec-draft`：把 `agents/spec-agent` 迁成主 agent 执行的 playbook；明确"global→stage 预算分解"为其一步。
10. per-stage **spec-refine** 步（§4.2 rolling-wave）：进 stage 时用初版 + 上游真实数据 + 人工补充生成最终 spec。
11. `agents/{floorplan,cts,route,timing-eco}` → 决策 playbook skill（无 sub-agent）。

### 验证
- Python：改动文件跑 `py_compile`。
- 流程：`flow_loader.py validate --flow templates/flow_definition.yaml`；`next → run-eda-script(stub) → mark → parse-eda-report` 闭环（stub 下诚实给 partial）。
- 模板/KB：`build_knowledge_base.py --dry-run` 抽查。
