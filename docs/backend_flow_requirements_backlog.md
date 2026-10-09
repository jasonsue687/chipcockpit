# 芯片后端 AI Flow 需求待办（按优先级与价值排序）

> 更新日期：2026-07-19  
> 适用范围：`chip-backend-ai` 的 **Netlist-to-GDS 芯片后端物理实现流程**。  
> 当前基线：mock 模式 9 stage / 48 step / 8 gate 已跑通；本文排序面向“从模拟流程升级为可信的真实 EDA 项目流程”。

## 1. 结论

当前系统已经证明了流程配方、step driver、模板渲染、模拟报告解析和人工暂停点能够串起来，但还不能把“mock 全流程完成”解释成“真实芯片后端流程可用”。

真实使用的首要矛盾不是增加更多 AI 能力或界面，而是先建立可信的数据面：

1. 每个 EDA 步骤必须真的加载上游设计状态，并真的保存声明的 DB/DEF/checkpoint。
2. 每次 retry/rollback 必须使用独立的 `run_NNN`，不能复用旧文件后被自动判定为 done。
3. real/mock/stub 必须强隔离，真实签核不能接受模拟或占位产物。
4. 输入、工具、报告、quality gate 和 tapeout 交付物必须覆盖真实项目所需的 PDK/MMMC/signoff 契约。

因此，近期路线应当是：

```text
可信执行底座
  → 真实 Import→Floorplan 纵向切片
  → 真实 Placement→CTS→Route→Timing 收敛
  → Signoff/Tapeout 闭环
  → AI 决策增强、规模化和全芯片生命周期扩展
```

## 2. 排序规则

### 优先级

- **P0**：不完成就无法可信地运行真实项目，或可能造成“假完成/假签核”。
- **P1**：真实项目能够运行后，决定是否可靠、可恢复、可审计、可进入 signoff。
- **P2**：提高工程效率、AI 决策质量、可维护性和团队使用体验。
- **P3**：扩大产品边界或支持更复杂设计形态，当前不阻塞首个真实 block。

### 价值等级

- **V5 极高**：直接解锁真实 Netlist-to-GDS，或避免错误流片/错误签核。
- **V4 高**：显著降低 P&R 调试、回滚和复现成本。
- **V3 中**：提升效率、可维护性或团队协作体验。
- **V2 低**：锦上添花，短期不影响真实项目成功率。

### 工作量

- **S**：约 1–3 人日。
- **M**：约 1–2 人周。
- **L**：约 3–6 人周。
- **XL**：跨工具/跨团队项目，需要拆分里程碑。

工作量只是单人粗估，用于排序，不是排期承诺。

## 3. 总排序

| 排名 | ID | 优先级 | 需求 | 价值 | 工作量 | 主要解锁 |
|---:|---|:---:|---|:---:|:---:|---|
| 1 | FLOW-001 | P0 | 建立真实 EDA 设计状态加载/保存链 | V5 | L | 让独立 Tcl 步骤真正串联 |
| 2 | FLOW-002 | P0 | 接通 `run_NNN`、不可变产物与 retry/rollback 失效传播 | V5 | L | 可信重试、回滚、审计 |
| 3 | FLOW-003 | P0 | real/mock/stub 强隔离与产物 provenance | V5 | M | 防止模拟产物进入真实签核 |
| 4 | FLOW-004 | P0 | 完整项目输入 manifest 与就绪校验 | V5 | L | 支持真实 PDK/MMMC/IP 输入 |
| 5 | FLOW-005 | P0 | 多工具 EDA adapter、环境、license 与版本探测 | V5 | L | Innovus/STA/IR/物理验证真实执行 |
| 6 | FLOW-006 | P0 | Tcl 命令知识库与版本化静态校验 | V5 | M | 消除未验证/幻觉命令风险 |
| 7 | FLOW-007 | P0 | Spec 阶段范围与终止条件真正控制流程 | V5 | M | 支持只跑 import/route 等目标流 |
| 8 | FLOW-008 | P0 | 首个真实 Import→Floorplan 纵向切片 | V5 | M | 获得第一份非模拟 DEF/report/gate |
| 9 | FLOW-009 | P0 | 重构质量门指标合同与多报告输入 | V5 | L | 防止“只测一个指标却宣称 stage pass” |
| 10 | FLOW-010 | P0 | Signoff/Tapeout 真实签核与交付包 | V5 | XL | 可信 GDS release |
| 11 | FLOW-011 | P1 | Spec schema、全量版本归档与审批证据 | V4 | M | 可追溯目标和预算变更 |
| 12 | FLOW-012 | P1 | 统一状态机、step driver 与人工门的事务边界 | V5 | L | 防止状态漂移和提前 stage pass |
| 13 | FLOW-013 | P1 | 输入/Spec/脚本变化后的增量失效与重跑计划 | V4 | L | 避免陈旧产物被继续复用 |
| 14 | FLOW-014 | P1 | 真实报告解析器：多 corner/mode、单位与证据定位 | V5 | L | 可信 PPA 和 signoff gate |
| 15 | FLOW-015 | P1 | 人工审批、waiver 与 tapeout release 记录 | V5 | M | 真实 Human-in-the-loop 签核 |
| 16 | FLOW-016 | P1 | EDA 运行可靠性：超时、日志错误、license/grid、取消 | V4 | M | 降低长任务假成功和卡死 |
| 17 | FLOW-017 | P1 | 失败分类、retry/rollback/revise-spec/abort 自动回归 | V4 | L | 验证异常路径而非只测 happy path |
| 18 | FLOW-018 | P1 | 可复现性 manifest 与 checkpoint 完整性校验 | V4 | M | 跨机器/跨会话复现结果 |
| 19 | FLOW-019 | P1 | 建立可公开的小型真实参考 block | V4 | M | 持续验证真实 Tcl 与 parser |
| 20 | FLOW-020 | P1 | PDK/IP 专有数据隔离与日志脱敏 | V4 | M | 满足真实企业数据安全要求 |
| 21 | FLOW-021 | P2 | AI 决策读取真实设计证据并输出可解释差分 | V4 | L | 让 AI 超越确定性默认参数 |
| 22 | FLOW-022 | P2 | 流程状态、PPA 趋势、失败归因可观测性 | V3 | M | 提升调试与人工决策效率 |
| 23 | FLOW-023 | P2 | CI、依赖锁定、schema/lint/unit/integration 测试 | V4 | M | 降低回归和发布风险 |
| 24 | FLOW-024 | P2 | 文档单一真源与版本一致性治理 | V3 | M | 消除 41/42/48、agent/skill 等冲突 |
| 25 | FLOW-025 | P2 | 计算资源、并行分析和缓存策略 | V3 | L | 缩短多 corner/signoff 周期 |
| 26 | FLOW-026 | P3 | 明确是否扩展到 RTL→综合→DFT→后端全生命周期 | V4 | XL | 从后端插件升级为全芯片开发平台 |
| 27 | FLOW-027 | P3 | Hierarchical/低功耗多电压/Top/3DIC/多芯片流程 | V4 | XL | 支持复杂 SoC 与先进封装 |
| 28 | FLOW-028 | P3 | 多用户协作、角色权限、审批通知与 Dashboard | V3 | XL | 团队级规模化使用 |

## 4. P0：真实项目阻塞项

### FLOW-001 建立真实 EDA 设计状态加载/保存链

**现状问题**

- `run-eda-script` 每一步都会启动一个新的 Innovus 进程。
- 30 个 Tcl 模板都标注“not validated for real runs”，没有模板真正 restore/load 上一步设计 DB/DEF。
- import 声明输出 `imported.db`、`mmmc.db`、`import_done.db`，但对应模板没有写出这些文件。
- mock runner 会替每一步创建声明的输出文件，因此上述断链在模拟回归里不可见。

**需求**

选择并落地一种明确的执行模型：

1. **每 stage 长驻一个 EDA session**，stage 内步骤共享设计内存；或
2. **每 step 独立进程**，但每个模板必须有统一的 restore prologue 和 save epilogue。

**验收标准**

- `read_design` 真实生成可恢复的 design DB/checkpoint，而不是仅生成 report。
- 任意步骤单独启动时，都能从声明的 required input 恢复完整设计上下文。
- 每个声明为 required 的 DB/DEF/SPEF/report 都由 EDA 命令真实生成。
- 删除进程内存后重新启动，下一步仍能继续运行。
- 至少完成真实 `read_design → setup_mmmc → global_net_connect → check_design → gen_floorplan` 连续运行。

**依赖**：FLOW-004、FLOW-005。  
**不应同时做**：在该问题解决前扩展更多 stage 模板。

### FLOW-002 接通 `run_NNN`、不可变产物与 retry/rollback 失效传播

**现状问题**

- 设计文档和 `workspace.py` 使用 `stages/<stage>/run_NNN/`。
- `flow_definition.yaml`、`render-tcl` 和当前 e2e 实际写入 `stages/<stage>/artifacts|reports|scripts` 平铺目录。
- retry 后旧输出仍存在，`flow_loader` 仅凭 required output “存在”就会自动标记 done。
- upstream rollback 后，没有机制将 downstream step 和产物标记为 stale。

**需求**

- flow step 的所有路径都绑定 `run_id`。
- run 完成后不可覆盖；retry 创建新 run；rollback 记录 `parent_run` 和因果链。
- 建立依赖 DAG 和失效传播：上游 run/spec/input 改变时，下游 run 不能继续作为 current result。

**验收标准**

- 同一 stage 连续执行两次会生成 `run_001`、`run_002`，两者文件互不覆盖。
- retry 不会因为 `run_001` 文件仍在而跳过 `run_002`。
- rollback floorplan 后，旧 powerplan 及其后续产物自动标记 stale，但仍保留审计。
- `machine.yaml`、`flow_progress.yaml`、`_meta.yaml` 对 current run 的指向一致。
- e2e 覆盖 retry、跨阶段 rollback、resume 三种路径。

**依赖**：FLOW-001。

### FLOW-003 real/mock/stub 强隔离与产物 provenance

**需求**

- workspace 创建时固定 `run_mode: real | mock | stub`，运行中不得静默混用。
- real 模式禁止把 STUB/SIMULATED 文件、`simulated:true` eval 或 mock report 标为完成。
- 所有产物记录生成模式、工具、版本、脚本 hash、Spec hash、输入 manifest hash、时间和主机。

**验收标准**

- real flow 读到任一 mock/stub upstream artifact 时立即 fail closed。
- `COMPLETED` 和 tapeout release 只允许全链路 `mode=real`。
- mock/stub 仍可用于流程测试，但 UI/CLI/报告始终带明显标识。
- 能从最终 GDS manifest 追溯到每个上游 run 和输入版本。

**依赖**：FLOW-002。

### FLOW-004 完整项目输入 manifest 与就绪校验

**现状问题**

当前 flow 只把单个 netlist、SDC、LEF、Liberty 声明为外部必需输入，无法表达真实项目的多 corner、RC tech、macro/IP、低功耗、DFT 和 signoff deck。

**需求范围**

- 设计：top、netlist、SDC、scan/DFT、UPF/CPF、SAIF/VCD。
- 库和工艺：tech LEF、cell/macro LEF、多 PVT Liberty、QRC/captable、metal stack、特殊单元列表。
- IP：macro GDS/CDL/lib/LEF、blackbox 和集成约束。
- Signoff：DRC/LVS/ERC/antenna/fill/EM deck、GDS layer map。
- 项目元信息：foundry、node、release、top/block、目标阶段、工具版本矩阵。

**验收标准**

- 使用结构化 `inputs/manifest.yaml`，支持单文件、文件组、corner/mode 映射和可选条件。
- readiness 输出 missing/mismatch/unsupported 的精确列表。
- 版本一致性以 manifest release + checksum 为主，不再要求修改每个专有输入文件头部加入 marker。
- manifest 能按目标阶段裁剪：只跑 import 不强制提供 signoff deck。
- 文件路径限制在允许的项目/PDK 根目录，专有输入默认不复制进 Git。

### FLOW-005 多工具 EDA adapter、环境、license 与版本探测

**需求**

- 把当前 Innovus-only 的执行原语升级为 tool adapter：命令行、batch 参数、成功判据、日志错误模式和输出检查由 adapter 定义。
- 至少规划 Innovus、Tempus、Voltus (or equivalent PI tool)、Pegasus/Calibre 的可插拔接口；实际采用哪套由项目配置决定。
- 环境检查覆盖 binary、版本、license、PDK/tool compatibility 和 grid queue。

**验收标准**

- `env_manager check` 能输出每个必需工具的 available/version/license 状态。
- 同一 flow step 可通过配置选择实现工具，不在模板里硬编码单一厂商。
- unsupported tool/version 在执行前阻塞，不到运行中才发现。
- tool adapter 有最小单测和真实 smoke test。

### FLOW-006 Tcl 命令知识库与版本化静态校验

**现状问题**

- 决策 skill 要求所有 AI Tcl 经过 `search-eda-command`。
- 当前 `knowledge/processed_eda/innovus.json` 不存在，因此该护栏实际不可用。
- 静态模板也没有做命令/参数级版本验证。

**需求**

- 生成并持续维护按工具版本索引的 command database，或让 `search-eda-command` 支持现有分层 Markdown 知识库。
- 对 golden template 和 AI 注入 fragment 执行 Tcl lint：命令存在、参数合法、版本兼容、危险命令受控。
- 每个非标准命令允许显式 waiver，但必须记录来源和理由。

**验收标准**

- `search-cmd --tool innovus --cmd-name <cmd>` 对流程使用的全部命令可返回结果或明确版本差异。
- CI 扫描 30 个模板，未识别命令默认失败。
- AI fragment 未通过 lint 时不得进入 real run。
- 每条已接受命令可追溯到手册章节、工具版本或团队 waiver。

### FLOW-007 Spec 阶段范围与终止条件真正控制流程

**现状问题**

测试 Spec 只声明 `stages: [import]`，但 flow loader 仍执行完整 9-stage recipe，说明 Spec scope 当前没有成为执行约束。

**需求**

- 支持 `start_stage`、`target_stage`、显式 stage 列表和 prerequisites 自动闭包。
- `termination_criteria` 必须参与完成判定，而不是只作为文档字段。
- 被裁剪 stage 使用 `not_in_scope`，不能与运行成功的 `skipped` 混淆。

**验收标准**

- `stages: [import]` 在 import 审批后返回 scoped complete，不进入 floorplan。
- `target_stage: route` 自动包含必要上游，但不进入 timing/signoff/tapeout。
- 缺失必要依赖时 Spec validation 阻塞并解释原因。
- 进度和最终报告同时显示 in-scope/out-of-scope stage。

### FLOW-008 首个真实 Import→Floorplan 纵向切片

**需求**

选择一个可合法共享的小 block，使用真实 Innovus 和真实/可公开 PDK 数据，逐步替换 mock。

**验收标准**

- 输入 manifest、Spec 和工具环境检查通过。
- 真实生成 design DB、floorplan DEF、报告和日志，所有文件不得包含 STUB/SIMULATED。
- import/floorplan gate 使用真实 report actual 值。
- 能在 floorplan 人工门暂停、关闭会话、重新打开后继续。
- 记录首个真实运行的已知问题清单，作为后续模板适配依据。

**依赖**：FLOW-001～FLOW-007。

### FLOW-009 重构质量门指标合同与多报告输入

**现状问题**

当前多数 stage 只检查 1–2 个模拟指标；质量门名称声称覆盖的内容多于实际检查内容，例如：

- power gate 未自动检查 PG connectivity 和 EM。
- placement gate 未自动检查 pre-CTS setup/hold/DRV。
- route gate 未自动检查 open/short/antenna/post-route timing。
- signoff gate 只解析 `drc_lvs.rpt` 中的 DRC 数量，没有把 `ir_em.rpt` 纳入自动 gate。

**需求**

- 定义每个 stage 的 hard gate、soft KPI、人工 review 三类指标。
- gate 支持多份 report、多个 corner/mode、severity 和 waiver。
- hard metric missing 必须 fail closed，不能通过人工描述掩盖。

**最低指标合同**

| Stage | Hard gate（最低要求） | Soft KPI / review |
|---|---|---|
| import | unresolved refs、unconstrained paths、library/MMMC 完整性、PG net 连接 | 初始面积/利用率 |
| floorplan | core/die 合法、macro overlap、pin legality、最小 channel | utilization、early congestion/timing |
| powerplan | PG connectivity、short/open、IR、EM | metal resource cost、decap/tap coverage |
| placement | legality、max tran/cap/fanout、setup/hold 下限 | congestion、density、power |
| CTS | clock coverage、skew、insertion、DRV、setup/hold | buffer count、clock power |
| route | open/short、DRC、antenna、connectivity | post-route WNS/TNS、via count |
| timing_eco | 全 MMMC setup/hold、DRV、SI | power/area delta、ECO size |
| signoff | DRC/LVS/ERC/antenna/density、static/dynamic IR、EM | waiver count/severity |
| tapeout | release manifest、GDS checksum、final verification record | 交付完整性 |

**验收标准**

- gate 输出每个指标的 target、actual、unit、corner/mode、source report 和 source location。
- signoff 任一 hard metric 缺失或失败都不能进入 tapeout。
- waiver 不改变原始 actual；只以独立审批记录改变 release decision。

### FLOW-010 Signoff/Tapeout 真实签核与交付包

**需求**

- 使用项目认可的 signoff 工具与 foundry deck 执行 DRC/LVS/ERC/antenna/fill/density/IR/EM。
- 生成完整交付包，而不是只有 `chip.gds`。

**交付包最低内容**

- GDS/OASIS、final DEF、LVS netlist/CDL、SPEF/SDF（按项目需要）。
- DRC/LVS/ERC/antenna/density/IR/EM/timing 报告。
- waiver log、tool/deck/version、input/output checksum manifest。
- release notes、审批记录、已知限制和复现命令。

**验收标准**

- tapeout 前自动验证 manifest 中所有 required deliverables 存在且 checksum 固定。
- signoff gate、waiver approval 和 final checklist 均完成后才允许 release。
- 任一 upstream real provenance 缺失时拒绝生成 release-ready 标记。

## 5. P1：生产可靠性与可审计性

### FLOW-011 Spec schema、全量版本归档与审批证据

- 用 JSON Schema/Pydantic 等方式严格校验字段、类型、单位、阈值、stage 名和 metric 名。
- 归档 global spec 与所有 stage spec；当前只归档 global spec 不够。
- Spec 审批记录 approver、时间、意见、Spec hash；审批后内容不可静默修改。
- 将 rolling-wave stage refine 变成显式流程动作，并在执行前重新审批受影响预算。

**验收**：修改任一已审批 stage spec 会使相关 run stale，并要求新版本审批。

### FLOW-012 统一状态机、step driver 与人工门的事务边界

- 明确定义 stage 完成点：必须是 gate pass **且** post-gate 人工确认完成之后。
- `machine.yaml`、`flow_progress.yaml` 和 run metadata 通过一个事务式命令更新，避免一半成功一半失败。
- 增加 workspace lock/lease，防止两个会话并发推进同一项目。
- `resolve-human` 只能作用于当前 awaiting 的 human step，不能任意 mark 其他步骤。

**验收**：崩溃注入发生在任意写入点后，resume 能恢复到唯一确定状态，不会提前标记 stage passed。

### FLOW-013 输入/Spec/脚本变化后的增量失效与重跑计划

- 计算 input、Spec、decision、template、rendered Tcl 的 hash。
- 变化后生成 impact plan：哪些 step 可复用、哪些必须重跑、哪些需要人工确认。
- `exists()` 只能作为恢复提示，不能单独作为产物有效性的最终依据。

**验收**：修改 SDC 后，所有 timing-dependent stage 被正确失效；只改文档不会触发 EDA 重跑。

### FLOW-014 真实报告解析器

- parser 按 tool/version/report type 插件化，不依赖少量通用 regex。
- 支持多报告、多 corner/mode、表格和单位归一化。
- 结果保留原始字符串、解析规则版本、report path、行号/section。
- 对格式变化做 schema detection 和明确错误，不静默取第一处数字。

**验收**：使用保存的真实报告 fixture 覆盖每个 hard metric，并验证格式变化/缺失/单位变化。

### FLOW-015 人工审批、waiver 与 release 记录

- approval 结构包含 decision（approve/reject/request-change）、人员、角色、时间、证据路径和备注。
- floorplan/PG/placement/CTS/route/timing/signoff/tapeout 分别定义最小 review checklist。
- waiver 单独建模：rule、location、severity、owner、expiry、依据和审批人。

**验收**：测试模式可显式 auto-resolve；real 模式禁止无身份、无证据、无备注的自动确认。

### FLOW-016 EDA 运行可靠性

- 每步配置 timeout、资源、queue、license feature、重试策略和可取消机制。
- 除 exit code/文件存在外，扫描 fatal/error/license checkout/segfault/terminated 等模式。
- 记录 CPU、内存、wall time、host/job id；超时后清理子进程和临时锁。

**验收**：覆盖进程超时、license 不足、exit 0 但日志 fatal、输出半写四类测试。

### FLOW-017 异常路径自动回归

把现有测试文档中的场景自动化：

- normal completed；Spec reject/adjust；stage retry；跨阶段 rollback；revise spec；budget exhausted；escalate；resume。
- 增加 tool crash、report format change、checkpoint corruption。

**验收**：每个场景断言 machine 终态、decisions 日志、run lineage、budget、Spec 版本和产物有效性。

### FLOW-018 可复现性 manifest 与 checkpoint 完整性

- 每个 run 生成 `_meta.yaml`：tool/version、host、command、env、Spec/input/script hash、parent run、状态和 checkpoint。
- checkpoint 不只是 DEF；按恢复需求保存 design DB、MMMC/RC、约束和工具所需附属文件。
- checkpoint 写完后做 reopen smoke test 和 checksum 校验。

**验收**：在另一会话/兼容机器上只靠 manifest 和 checkpoint 恢复并生成相同关键报告。

### FLOW-019 可公开的小型真实参考 block

- 选择许可证清晰的 RTL/netlist + 开放 PDK 或企业内部可控 fixture。
- 建立真实与 mock 两套预期结果：mock 测编排，real 测 Tcl/工具/parser。
- 逐步扩展到 macro、multi-clock、scan、UPF 场景。

**验收**：每次模板/parser 变更都可在该 block 上重复 smoke test。

### FLOW-020 PDK/IP 专有数据隔离与日志脱敏

- PDK/IP 文件通过外部路径或受控存储引用，默认不复制、不提交。
- `.gitignore`/pre-commit 阻止 GDS、Liberty、deck、真实 report 等误入仓库。
- 日志和决策记录对用户名、绝对路径、license server、IP 名做可配置脱敏。

**验收**：安全扫描能发现并阻止专有文件和敏感路径进入 commit/release 包。

## 6. P2：效率、AI 质量与工程治理

### FLOW-021 AI 决策读取真实设计证据并输出可解释差分

- 决策输入不止上游 `eval_result.yaml`，还应包含结构化拥塞 hotspot、critical path、macro/pin 几何、DRC 聚类和 power hotspot。
- `decisions.yaml` 记录 baseline、AI 建议、差分、依据、预期影响、风险和回退方案。
- 用 A/B 或 replay 比较 deterministic baseline 与 AI 决策的 PPA/收敛轮次。

**验收**：AI 决策必须引用具体 report/object/metric；没有证据时只能给建议，不能直接进入 real run。

### FLOW-022 可观测性

- 增加项目状态摘要：current stage/step/run、阻塞原因、PPA 趋势、retry budget、审批等待。
- 支持 run-to-run 和 Spec-to-Spec 指标差分。
- 生成 stage review 包：关键表格、热图/截图、失败聚类和建议动作。

**验收**：工程师无需手动遍历目录即可回答“现在卡在哪里、比上轮好多少、为什么回滚”。

### FLOW-023 CI、依赖锁定和自动质量检查

- 增加明确的 Python 依赖清单、支持版本和统一测试入口。
- CI 覆盖 py_compile/lint、flow/spec schema、模板 render、command lint、parser fixture、mock e2e、state e2e。
- plugin/marketplace version 一致性作为发布 gate。

**验收**：任何 flow/template/parser 改动必须通过自动回归后才能发布。

### FLOW-024 文档单一真源

**现状问题**

仓库中同时存在 41/42/48 步、sub-agent/无 sub-agent、待建/已建等互相冲突的文档和插件描述。

**需求**

- 从 `flow_definition.yaml` 和 schema 自动生成 stage/step/gate 统计与流程表。
- 明确 active docs、历史 proposal、deprecated docs。
- README、plugin manifest、SKILL 和测试文档引用同一状态源。

**验收**：CI 检测并阻止步骤数、版本号、能力状态漂移。

### FLOW-025 计算资源、并行分析和缓存策略

- 只在依赖允许的范围并行，例如多 corner STA、DRC 分区和报告解析。
- 增加 cache key 与资源配额，禁止因为缓存命中跳过输入/Spec hash 校验。
- 集成 grid scheduler job id、状态和取消。

**验收**：多 corner 分析时间下降，结果与串行基线一致且可追溯。

## 7. P3：产品边界扩展

### FLOW-026 是否扩展到完整芯片开发生命周期

当前仓库严格来说是 **后端物理实现流程**，从已综合 netlist 开始，不包含：

- 产品需求与芯片架构；
- 微架构/RTL；
- 仿真、形式验证、覆盖率；
- DFT 插入与 ATPG；
- 逻辑综合与 formal equivalence；
- 封装/板级协同和 post-silicon validation。

应先做产品决策：继续保持 Netlist-to-GDS 专注，还是扩展为 RTL-to-Silicon。若扩展，必须另立 program，不应塞进当前 P0。

### FLOW-027 复杂设计形态

- Hierarchical block/top integration、abstract/ILM。
- 多电压域、power switch、isolation/level shifter、UPF signoff。
- Pad ring/bump/package/IO planning。
- 3DIC/TSV/chiplet/multi-chip analysis。

这些需求应在首个单 block 真实流程稳定后再排期。

### FLOW-028 团队协作与 Dashboard

- 多用户角色、审批权限、通知、评论和责任人。
- Web dashboard、项目组合视图、进度与风险汇总。
- 外部系统集成（Issue/文档/消息/日历）。

该项价值建立在底层产物和状态可信之上，不应早于 FLOW-001～FLOW-018。

## 8. 建议里程碑

### M0：可信执行底座

范围：FLOW-001～FLOW-007。  
退出条件：真实模式不会接收 mock/stub；run 模型统一；输入、工具、Tcl 和范围均可验证。

### M1：真实 Import→Floorplan

范围：FLOW-008、FLOW-011～FLOW-016 的最小子集。  
退出条件：真实 block 产出可恢复 DB、floorplan DEF、真实 gate 和人工审批记录。

### M2：真实 P&R→Timing Closure

范围：扩展真实模板到 powerplan/placement/CTS/route/timing，完成 FLOW-009、FLOW-014、FLOW-017～FLOW-019。  
退出条件：全 MMMC 时序、DRC/connectivity 和 IR 等阶段门有真实证据；retry/rollback 可回归。

### M3：Signoff/Tapeout

范围：FLOW-010、FLOW-015、FLOW-018、FLOW-020。  
退出条件：真实 signoff 工具/deck、waiver、release manifest 和 GDS 交付包闭环。

### M4：AI 增强与规模化

范围：FLOW-021～FLOW-025。  
退出条件：AI 决策对真实 block 的收敛轮次或 PPA 有可重复收益，CI 和可观测性支持团队维护。

## 9. 建议立即进入 Sprint 的前 8 项

1. FLOW-001：拍板 EDA session/checkpoint 模型，修通真实状态交接。
2. FLOW-002：统一 run-scoped 路径，先解决 retry 被旧输出短路的问题。
3. FLOW-003：加 workspace run mode 和 real provenance fail-closed。
4. FLOW-004：定义 `inputs/manifest.yaml` v1 schema。
5. FLOW-005：实现 Innovus adapter v1，检查 binary/version/license。
6. FLOW-006：恢复可用的 Innovus command lookup，并对模板做 lint inventory。
7. FLOW-007：让 Spec scope 驱动 flow snapshot 裁剪和完成条件。
8. FLOW-008：准备真实小 block，完成 Import→Floorplan smoke test。

在这 8 项完成前，暂缓 Dashboard、并行调度、更多 AI agent/skill 和全生命周期扩张，因为它们不会解决当前最大的真实执行与签核可信度问题。

## 10. 审计依据摘要

- mock e2e 已证明 48 step/8 gate 的流程 plumbing，但所有 EDA 产物为模拟文件。
- 当前测试工作区没有覆盖完整 `machine.yaml + decisions.jsonl` 元状态机闭环。
- 30 个 Tcl 模板均声明未经过真实运行验证，且没有有效的上游 design restore。
- import 的三个 DB 输出在模板中没有真实写出命令。
- `run_NNN` 协议与 flow 实际平铺路径不一致。
- `flow_loader` 仅凭输出路径存在即可在 resume 时自动标记 done，没有 hash/provenance/staleness 判断。
- Spec stage scope 当前未限制完整 flow recipe。
- signoff gate 当前只解析 DRC/LVS report，没有把 IR/EM report 纳入自动 gate。
- `search-eda-command` 依赖的结构化 Innovus JSON database 当前缺失。
- 自动测试主要覆盖 mock happy path；异常场景仍主要停留在测试文档。
- 文档、manifest 和测试说明存在步骤数与架构描述漂移。

