---
name: CTS Design
description: This skill should be used when the orchestrator (or user) needs to decide clock-tree-synthesis strategy for the cts stage's gen_cts_spec step — target skew, clock-net non-default routing rule (NDR), clock buffer/inverter leaf-cell selection, skew groups, and excluded pins. Trigger on "design CTS", "decide CTS strategy", "configure cts spec", "gen_cts_spec decision", "set target skew", "clock NDR", "non-default routing rule for clock", "clock buffer cell selection", "skew group", "exclude clock pin", "时钟树综合决策", "设计 CTS", "配置 CTS spec", "决定目标 skew", "时钟网络 NDR", "时钟 buffer 单元选择", "skew group 划分", "exclude pin", "gen_cts_spec 决策", or whenever the flow's cts.gen_cts_spec step needs its decisions.yaml. Produces decisions.yaml (params + fragments + rationale); a deterministic baseline in scripts/gen_decisions.py keeps the flow unattended.
version: 0.1.0
---

# CTS Design — 时钟树综合决策 playbook（gen_cts_spec）

这是 cts 阶段 **`gen_cts_spec`** 步的 **AI 决策 playbook**：把这颗芯片 placement 之后的真实情况（实际利用率/拥塞、时钟扇出、可用 buffer/inverter 库、时钟域划分）转成一份**CTS spec / CCOpt 配置**的 `decisions.yaml`，由 [render-tcl] 填进 `templates/tcl/cts/gen_cts_spec.tcl.tmpl`，再交 [run-eda-script] 执行——该步产出 **`cts.spec`（规格产物，不是 .def）**，供下游 `build_clock_tree` 读入构树。

> 这是一条 AI 决策节点的内部流水线：**① 决策(本 playbook + 主 agent)→ ② render-tcl → ③ run-eda-script → ④ parse-eda-report**。本 skill 只装"怎么判断"，结果落 `decisions.yaml`（可审计、可重渲染、新会话可续跑）。`build_clock_tree`（构树，产 `cts.def`）/ `postcts_opt`（post-CTS hold/setup + DRV，产 `cts_opt.def` + `clock_tree.rpt`）是本阶段两个**机械步**（无决策层）；真正的 gate 是 `cts_eval`（比对 `global_skew_ps` / `max_insertion_delay_ps`）。

## 这一步决定什么

- **目标 skew（target skew）**：`set_ccopt_property target_skew`——时钟树平衡的全局 skew 目标。必须**压在 spec 的 `global_skew_ps` gate 预算（`max`）之下**并留裕量；目标越紧、CCOpt 越下功夫平衡（插更多 buffer、走更宽 NDR），但抬插入延迟与面积。
- **时钟网络 NDR（non-default routing rule，非默认布线规则）**：`create_route_rule` + `set_ccopt_property routing_rule`——给时钟网络加宽（width multiplier）、加间距（spacing multiplier），降低串扰与 OCV 引起的 skew 变化。加得越多越稳，但吃布线资源。
- **leaf / clock-buffer cell 选择**：`set_ccopt_property buffer_cells` / `inverter_cells` / `use_inverters`——CCOpt 可用的时钟 buffer/inverter 单元清单。选低偏差、合适驱动的时钟专用单元（如 `CLKBUF`/`CLKINV`）；`use_inverters` 决定是否用反相器对降低占空比失真。
- **max fanout（每 buffer 扇出上限）**：`set_ccopt_property max_fanout`——每个时钟 buffer 的最大扇出，连同 `target_max_trans`（DRV transition 目标）一起控制树的扁平度。扇出越小树越扁、skew/insertion 越低，但单元越多。
- **skew group 划分**：`create_ccopt_skew_group`——把需要一起平衡的时钟域（sink）归组。多时钟/生成时钟时按域分组，避免无关时钟互相牵制。
- **exclude pin（排除引脚）**：把不应被 CTS 平衡的 sink（如 I/O 端、已被门控/分频的引脚、第三方 macro 的时钟入口）标为 `sink_type exclude`，避免 CCOpt 误把它们拉进同一棵树。写在 `fragments.extra_ccopt_props`。

## 决策前必读（READ before deciding）

1. **本阶段 spec**：`spec/stages/cts.yaml`
   - `metrics[].target`：`global_skew_ps`（skew 预算，gate 校验 `actual <= max`，mock 出 `global skew (ps) = <v>`）与 `max_insertion_delay_ps`（插入延迟预算，mock 出 `max insertion delay (ps) = <v>`）——target skew / NDR / max_fanout 决策必须把这两个指标压在带内。
   - `parameters`：`target_skew_ps` / `target_max_trans_ps` / `max_fanout` / `ndr_name`(+`ndr_width_mult`/`ndr_spacing_mult`) / `clock_buffer_cell` / `clock_inverter_cell` / `use_inverters` / `skew_group` 等基线，可被本步覆盖。
2. **上游真实信息**：placement 的 `stages/placement/eval_result.yaml`（实际 congestion / pre-CTS timing → 拥塞越重、给时钟 NDR 留的布线资源越紧 → NDR 倍数要务实、target skew 不能定太死）；若是失败回炉，读上一轮 `stages/cts/eval_result.yaml`（`retry_context.failed_metrics`）——skew 超标就收紧 target skew / 降 max_fanout / 加宽 NDR；insertion delay 超标就放宽 target skew、减小树深、少插 buffer。
3. **知识库**（按需，progressive disclosure）：
   - 概念：[read-eda-concept]（"CTS"、"clock skew"、"insertion delay"、"non-default routing rule"、"useful skew"）。
   - 专家经验：[read-expert-doc]（CTS / clock tree tips）；先 [list-expert-topics] 找文件名。
   - 命令片段写法：[read-eda-lab-doc]（DBTCL labs 里 create_ccopt_clock_tree_spec / set_ccopt_property / ccopt_design 用法）。

## 防幻觉护栏（红线）

**本 playbook 写进 `fragments` 的每一条 Tcl 命令，必须先用 [search-eda-command] 校验它在 Innovus 命令空间里真实存在**（如 `create_ccopt_clock_tree_spec`、`set_ccopt_property`、`create_ccopt_skew_group`、`create_route_rule`、`ccopt_design`）。查不到的命令一律不写——把决策约束在真实命令空间内是防幻觉的关键。固定骨架（NDR / buffer_cells / target_skew / skew group）已在模板里，`fragments.extra_ccopt_props` 只放经校验的增量（额外 `set_ccopt_property`、exclude pin 的 `set_ccopt_property -pin <pin> sink_type exclude`、额外 `create_ccopt_skew_group` 等）。

## decisions.yaml 契约

```yaml
params:                       # 键须与 gen_cts_spec.tcl.tmpl 的 {{占位}} 完全一致
  target_skew_ps: 60          # set_ccopt_property target_skew（压在 global_skew_ps 预算下）
  target_max_trans_ps: 100    # DRV transition 目标（max_tran）
  max_fanout: 32              # set_ccopt_property max_fanout（每 buffer 扇出上限）
  ndr_name: CTS_2W2S          # 时钟网络 NDR 名
  ndr_spacing_mult: 2         # NDR 间距倍数
  ndr_width_mult: 2           # NDR 线宽倍数
  clock_buffer_cell: CLKBUF   # 时钟 buffer leaf cell
  clock_inverter_cell: CLKINV # 时钟 inverter leaf cell
  use_inverters: "true"       # 是否用反相器对
  skew_group: main_clk_group  # skew group 名
fragments:                    # 键须与模板 `### @inject:<名>` 一致
  extra_ccopt_props: |        # 经 search-eda-command 校验过的增量 Tcl（可为空注释）
    # e.g. set_ccopt_property -pin <io_pin> sink_type exclude
rationale: "为什么这样选（skew/insertion 预算 vs 面积/布线资源权衡，NDR 倍数与 max_fanout 取舍），便于审计与回炉"
```

> `artifact_dir` 不是设计决策（cts.spec 的写入目录），由 harness `--var` 提供，不在 `params` 里重复。

## 无人值守基线

`scripts/gen_decisions.py` 给一份**确定性默认 decisions.yaml**（target skew 取 `global_skew_ps` 预算的 ~75%、DRV transition·max_fanout·NDR 倍数·buffer/inverter cell·skew group 取 spec 参数），保证流程无人也能走完；AI 在此基础上对真实芯片改进——按 `global_skew_ps` / `max_insertion_delay_ps` 预算与上游 congestion/timing 资源占用调 target skew、NDR 倍数与 max_fanout。

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/cts-design/scripts/gen_decisions.py \
  --workspace <ws> --step cts.gen_cts_spec \
  --spec <ws>/spec/stages/cts.yaml \
  [--upstream-eval <ws>/stages/placement/eval_result.yaml] \
  --out <ws>/stages/cts/decisions/gen_cts_spec.yaml
```

输出单个 JSON 摘要（`status`/`out`/`params`/`fragments`）。
