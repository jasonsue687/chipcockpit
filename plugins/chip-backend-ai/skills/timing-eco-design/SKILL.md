---
name: Timing ECO Design
description: This skill should be used when the orchestrator (or user) needs to decide the timing-closure / ECO repair strategy for the timing_eco stage's fix_strategy step — which timing paths to fix and the repair means (buffer insertion, gate resize / Vt-swap, useful skew, local reroute), and the setup vs hold vs DRV tradeoffs. Trigger on "design timing ECO", "decide ECO strategy", "fix_strategy decision", "timing closure strategy", "fix setup timing", "fix hold timing", "buffer insertion", "gate resize", "Vt swap", "useful skew", "WNS TNS hold fix", "post-route timing ECO", "时序收敛决策", "时序 ECO 策略", "fix_strategy 决策", "修 setup", "修 hold", "插 buffer", "单元 resize", "Vt 替换", "useful skew", "时序收敛策略", or whenever the flow's timing_eco.fix_strategy step needs its decisions.yaml. Produces decisions.yaml (params + fragments + rationale); a deterministic baseline in scripts/gen_decisions.py keeps the flow unattended.
version: 0.1.0
---

# Timing ECO Design — 时序收敛/ECO 决策 playbook（fix_strategy）

这是 timing_eco 阶段 **`fix_strategy`** 步的 **AI 决策 playbook**（plan §7.2：timing_eco 单 1 决策 skill；这是全流程**最后一个**由 `type:agent` 迁来的决策步）：把这颗芯片 route 之后的**真实 signoff 时序**（WNS/TNS/hold 各 corner/mode 的违例路径）转成一份**ECO 修复策略**的 `decisions.yaml`，由 [render-tcl] 填进 `templates/tcl/timing_eco/fix_strategy.tcl.tmpl`，再交 [run-eda-script] 执行——该步产出 **`eco.changes`（ECO 变更清单产物，不是 .def，仿 cts.spec）**，下游 `apply_eco` 读它回放到 `routed_clean.def`。

> AI 决策节点内部流水线：**① 决策(本 playbook + 主 agent)→ ② render-tcl → ③ run-eda-script → ④ parse-eda-report**。本 skill 只装"怎么判断"，结果落 `decisions.yaml`（可审计、可重渲染、新会话可续跑）。`extract_rc`（抽 RC，产 `design.spef`）/ `signoff_sta`（全 corner 时序，产 **pre-ECO** `timing.rpt`，供本决策步阅读）/ `apply_eco`（回放 ECO，产 `eco.def` + **post-ECO** `eco_timing.rpt`）是本阶段三个**机械步**（无决策层）；真正的 gate 是 `timing_eval`（解析 **`eco_timing.rpt`** 的 `wns_ns` / `tns_ns` / `hold_wns_ns`，下限语义 `actual >= min`）。

## 这一步决定什么

- **修哪条路（path selection）**：从 `signoff_sta` 的 `timing.rpt` 里按 path group / clock 域挑违例路径。先修结构性 setup 违例（WNS 最负、TNS 集中的 group），再统一修 hold；DRV（max_tran/max_cap/max_fanout）随路收敛。修哪条由"该 path 余量缺口 × 它在 TNS 里的占比"排序，避免在已收敛的 group 上空跑。
- **修复手段（repair means）**：
  - **buffer insertion**（`setup_buffer_cell` / `hold_buffer_cell` + `insertRepeater`）：长线/大扇出补 repeater 降 transition 与延迟；hold 违例插延迟 buffer/delay cell。
  - **gate resize / Vt-swap**（`resize_enable` + `size_cell`）：关键路径单元上驱动 / 换低 Vt（LVT）抢 setup 余量；非关键路径换高 Vt（HVT）回收 leakage——setup 与功耗的权衡点。
  - **useful skew**（`useful_skew_enable` + `setUsefulSkewMode`）：在 launch/capture 之间借时间，把 slack 从松路径挪给紧路径，常比硬插 buffer 更省面积，但牵动时钟树、要给 hold 留裕量。
  - **local reroute**（随 `apply_eco` 的 `ecoRoute`）：detour / 换层降耦合延迟，修因布线导致的少量 setup/SI 违例。
- **setup vs hold vs DRV 取舍**：`allow_setup_degrade` 允许修 hold 时容忍有界的 setup/TNS 退化（hold 必须干净，setup 可迭代）；`hold_target_slack_ns` / `setup_target_slack_ns` 设修复目标余量（留 OCV/SI 裕量，别贴边到 0）；`setup_fix_effort` / `hold_fix_effort` 控优化力度；`max_buffer_count` 给 ECO 规模设上限（防面积/功耗失控）。

## 决策前必读（READ before deciding）

1. **本阶段 spec**：`spec/stages/timing_eco.yaml`
   - `metrics[].target`：`wns_ns`（mock 出 `WNS (ns) = <v>`）、`tns_ns`（`TNS (ns) = <v>`）、`hold_wns_ns`（`hold WNS (ns) = <v>`）——**均为下限语义**（`target.min` 是地板，gate 校验 `actual >= min`；`max:null`）。ECO 目标就是把这三个 slack 顶到各自地板之上并留裕量。
   - `parameters`：`setup_fix_effort` / `hold_fix_effort` / `max_buffer_count` / `useful_skew_enable` / `eco_route_mode` / `setup_buffer_cell` / `hold_buffer_cell` / `resize_enable` / `allow_setup_degrade` / `hold_target_slack_ns` / `setup_target_slack_ns` / `fix_drv` 等基线，可被本步覆盖。
2. **上游真实信息**：
   - **本阶段 `signoff_sta` 的 `stages/timing_eco/reports/timing.rpt`（pre-ECO，最关键）**：违例路径清单、各 corner WNS/TNS/hold——决定修哪条、用什么手段、留多少余量的一手依据。
   - route 的 `stages/route/eval_result.yaml`（DRC 是否真干净；若残留会限制 ecoRoute 的腾挪空间）。
   - 失败回炉时读上一轮 `stages/timing_eco/eval_result.yaml`（`retry_context.failed_metrics`）——WNS/TNS 仍负就加 setup effort / 多 resize / 开 useful skew；hold 为负就加 hold buffer、收紧 `hold_target_slack_ns`，并确认 `allow_setup_degrade` 没把 setup 拖崩。
3. **知识库**（按需，progressive disclosure）：
   - 概念：[read-eda-concept]（"timing closure"、"setup/hold slack"、"WNS/TNS"、"useful skew"、"ECO"、"Vt swap"）。
   - 专家经验：[read-expert-doc]（timing ECO / hold fixing / useful-skew tips）；先 [list-expert-topics] 找文件名。
   - 命令片段写法：[read-eda-lab-doc]（DBTCL labs 里 optDesign / setOptMode / size_cell / insertRepeater / setUsefulSkewMode / ecoPlace / ecoRoute 用法）。

## 防幻觉护栏（红线）

**本 playbook 写进 `fragments.eco_ops` 的每一条 Tcl 命令，必须先用 [search-eda-command] 校验它在 Innovus 命令空间里真实存在**（如 `optDesign`、`setOptMode`、`setEcoMode`、`size_cell`、`insertRepeater`、`setUsefulSkewMode`、`saveTimingEco`、`loadTimingEco`、`ecoPlace`、`ecoRoute`）。查不到的命令一律不写——把决策约束在真实命令空间内是防幻觉的关键。固定骨架（setOptMode / fixing cells / useful_skew / optDesign -setup/-hold / setEcoMode / saveTimingEco）已在模板里，`fragments.eco_ops` 只放经校验的针对性增量（特定 path 的 `size_cell <inst> <lib_cell>`、`insertRepeater -net <net> -cell <buf>`、某 launch/capture 对的 `setUsefulSkewMode -maxSkew <ns>` 等）。

## decisions.yaml 契约

```yaml
params:                          # 键须与 fix_strategy.tcl.tmpl 的 {{占位}} 完全一致
  setup_fix_effort: high         # optDesign -postRoute -setup -effort
  hold_fix_effort: high          # optDesign -postRoute -hold -effort
  max_buffer_count: 5000         # setEcoMode -maxBufferCount（ECO 规模上限）
  useful_skew_enable: "true"     # set_ccopt_property useful_skew（是否借时间）
  setup_buffer_cell: BUFX4       # setup 修复用的 repeater/buffer cell
  hold_buffer_cell: DLYX1        # hold 修复用的 delay/hold buffer cell
  resize_enable: "true"          # setOptMode -optimizeFootprint（允许 resize/Vt-swap）
  allow_setup_degrade: "true"    # setOptMode -fixHoldAllowSetupTnsDegrade
  hold_target_slack_ns: 0.05     # 修 hold 的目标余量（留 OCV/SI 裕量）
  setup_target_slack_ns: 0.0     # 修 setup 的目标余量
  fix_drv: "true"                # setOptMode -fixFanoutLoad（顺手收 DRV）
fragments:                       # 键须与模板 `### @inject:<名>` 一致
  eco_ops: |                     # 经 search-eda-command 校验过的针对性 ECO Tcl（可为空注释）
    # e.g. size_cell <crit_inst> <LVT_lib_cell> ; insertRepeater -net <long_net> -cell BUFX8
rationale: "为什么这样修（按 WNS/TNS/hold 缺口选 path 与手段、setup↔hold↔功耗权衡、useful skew vs 硬插 buffer、ECO 规模上限取舍），便于审计与回炉"
```

> `artifact_dir`（eco.changes 的写入目录）与 `eco_route_mode`（apply_eco 机械步用，来自 spec params）不是本决策步的 `{{占位}}`，分别由 harness `--var` / spec 提供，不在本步 `params` 里重复。

## 无人值守基线

`scripts/gen_decisions.py` 给一份**确定性默认 decisions.yaml**（setup/hold effort、useful skew、buffer/hold cell、resize 开关、ECO 规模上限、hold/setup 目标余量取 spec 参数；并据 `wns_ns`/`tns_ns` 地板是否为负把 setup/hold effort 调到 high），保证流程无人也能走完；AI 在此基础上对真实芯片改进——读 `signoff_sta` 的 `timing.rpt` 按 path group 选路、按缺口选手段（buffer/resize/useful skew/reroute），并把每条增量命令过 [search-eda-command]。

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/timing-eco-design/scripts/gen_decisions.py \
  --workspace <ws> --step timing_eco.fix_strategy \
  --spec <ws>/spec/stages/timing_eco.yaml \
  [--upstream-eval <ws>/stages/route/eval_result.yaml] \
  --out <ws>/stages/timing_eco/decisions/fix_strategy.yaml
```

输出单个 JSON 摘要（`status`/`out`/`params`/`fragments`）。
