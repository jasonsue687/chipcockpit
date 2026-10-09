---
name: Floorplan Macro
description: This skill should be used when the orchestrator (or user) needs to decide macro placement AND macro halo/blockage for the floorplan stage — covering both the macro_placement step (location, orientation, dataflow, channel width) and the add_blockage step (keep-out halo, placement blockage, voltage areas). Trigger on "place macros", "decide macro placement", "macro orientation", "macro channel width", "add macro halo", "add placement blockage", "voltage area", "macro_placement decision", "add_blockage decision", "摆 macro", "宏单元摆放", "macro 朝向", "channel 宽度", "加 halo", "加 blockage", "电压域", or whenever the flow's floorplan.macro_placement or floorplan.add_blockage step needs its decisions.yaml. Produces decisions.yaml (params + fragments + rationale); a deterministic baseline in scripts/gen_decisions.py (branching on --step) keeps the flow unattended.
version: 0.1.0
---

# Floorplan Macro — 宏摆放 + halo/blockage 决策 playbook（macro_placement + add_blockage）

这是 floorplan 阶段 **两个紧耦合的 AI 决策步**的共用 playbook：

| 步 | 决定 | 模板 |
|----|------|------|
| `macro_placement` | macro 位置 / 朝向 / channel 宽度（数据流驱动） | `templates/tcl/floorplan/macro_placement.tcl.tmpl` |
| `add_blockage` | macro 周围 halo / placement blockage / voltage area | `templates/tcl/floorplan/add_blockage.tcl.tmpl` |

两步同一 playbook，因为 **halo/blockage 紧贴 macro 摆位**（halo 宽度、blockage 形状由 macro 位置/朝向/channel 决定）。`scripts/gen_decisions.py` **按 `--step` 分支**产出对应 params/fragments。

> AI 决策节点内部流水线：**① 决策 → ② render-tcl → ③ run-eda-script → ④ parse-eda-report**。`add_blockage` 是 floorplan 末步，额外产 `reports/floorplan_check.rpt` 供 `floorplan_eval` gate 解析。

## 各步决定什么

**macro_placement**
- **位置**：按数据流把 macro 沿信号路径成组摆放，靠近其消费/生产逻辑或对应 IO。
- **朝向**（`macro_orientation`）：让 macro 的 pin 面朝向消费者，缩短绕线。
- **channel 宽度**（`macro_channel_width_um`）：macro 间/macro 到 core 边的通道，必须 ≥ spec `metrics.macro_channel_width_um.min`（gate 校验），并给 power/route 留量。

**add_blockage**
- **halo**（`halo_um`）：macro 四周 keep-out，防标准单元贴太近、给 pin access / PG 留空间。
- **blockage type**（`blockage_type`，soft/hard/partial）：控制布局器在 macro 周边/角落/channel 的行为。
- **voltage area**（`fragments`）：按 power intent（UPF/CPF）圈电压域。

## 决策前必读（READ before deciding）

1. **本阶段 spec**：`spec/stages/floorplan.yaml`
   - `metrics.macro_channel_width_um.target`：channel 决策的硬下界（gate 会比对）。
   - `parameters`：`macro_channel_width_um` / `macro_orientation` / `halo_um` / `blockage_type` 基线。
2. **上游产出**：`stages/floorplan/artifacts/fp_pins.def`（IO pin 侧别决定 macro 朝向）；回炉时读 `eval_result.yaml`（channel/util 失败 → 调 channel/halo）。
3. **知识库**（按需）：
   - 概念：[read-eda-concept]（"macro placement"、"halo"、"placement blockage"、"voltage area"）。
   - 专家经验：[read-expert-doc]（先 [list-expert-topics] 找 floorplan/macro tips）。
   - 命令写法：[read-eda-lab-doc]（`placeInstance` / `addHaloToBlock` / `createPlaceBlockage` / `createVoltageArea`）。

## 防幻觉护栏（红线）

**写进 `fragments`（`macro_placement_cmds` / `blockage_cmds`）的每条 Tcl，必须先经 [search-eda-command] 校验存在**（`placeInstance`、`setMacroPlaceConstraint`、`addHaloToBlock`、`createPlaceBlockage`、`createVoltageArea` …）。查不到不写。

## decisions.yaml 契约

`macro_placement`：
```yaml
params:                       # 键须与 macro_placement.tcl.tmpl 的 {{占位}} 一致
  macro_channel_width_um: 4.0 # >= spec metric min
  macro_orientation: "R0"
fragments:
  macro_placement_cmds: |     # 经校验的显式摆位/朝向 Tcl（可为空注释）
    # e.g. placeInstance u_sram0 100 200 R0 -fixed
rationale: "数据流/朝向/channel 权衡"
```

`add_blockage`：
```yaml
params:                       # 键须与 add_blockage.tcl.tmpl 的 {{占位}} 一致
  halo_um: 3.0
  blockage_type: "soft"
fragments:
  blockage_cmds: |            # 经校验的额外 blockage / voltage area Tcl
    # e.g. createPlaceBlockage -box {...} -type partial -partialDensity 30
rationale: "halo/blockage/电压域理由"
```

## 无人值守基线（按 --step 分支）

`scripts/gen_decisions.py` 按 `--step` 给确定性默认：`macro_placement` 用 spec channel（≥metric min）+ 默认朝向 + 并发自动摆位；`add_blockage` 用 spec halo + soft blockage。保证无人值守；AI 据真实数据流改进。

```bash
# macro 摆放
python3 ${CLAUDE_PLUGIN_ROOT}/skills/floorplan-macro/scripts/gen_decisions.py \
  --workspace <ws> --step floorplan.macro_placement \
  --spec <ws>/spec/stages/floorplan.yaml \
  --out <ws>/stages/floorplan/decisions/macro_placement_decisions.yaml

# halo / blockage
python3 ${CLAUDE_PLUGIN_ROOT}/skills/floorplan-macro/scripts/gen_decisions.py \
  --workspace <ws> --step floorplan.add_blockage \
  --spec <ws>/spec/stages/floorplan.yaml \
  --out <ws>/stages/floorplan/decisions/add_blockage_decisions.yaml
```

输出单个 JSON 摘要（`status`/`out`/`params`/`fragments`）。
