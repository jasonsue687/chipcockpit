---
name: Floorplan IO Pins
description: This skill should be used when the orchestrator (or user) needs to decide IO pin placement for the floorplan stage's place_io_pins step — pin layers, spacing, side assignment, and bus/group constraints (block level) or pad ring (top level). Trigger on "place io pins", "decide pin placement", "assign io pins", "group bus pins", "pin layer assignment", "place_io_pins decision", "pad ring", "摆 IO pin", "决定引脚摆放", "分配 IO 引脚", "引脚分组", or whenever the flow's floorplan.place_io_pins step needs its decisions.yaml. Produces decisions.yaml (params + fragments + rationale); a deterministic baseline in scripts/gen_decisions.py keeps the flow unattended.
version: 0.1.0
---

# Floorplan IO Pins — IO 引脚摆放决策 playbook（place_io_pins）

这是 floorplan 阶段 **`place_io_pins`** 步的 **AI 决策 playbook**：决定 IO pin 落在哪层、怎么分布、按总线/功能分组（block 级），或 pad ring 布置（top 级），产出 `decisions.yaml`，由 [render-tcl] 填进 `templates/tcl/floorplan/place_io_pins.tcl.tmpl`，再交 [run-eda-script] 执行。

> AI 决策节点内部流水线：**① 决策 → ② render-tcl → ③ run-eda-script → ④ parse-eda-report**。本 skill 只装方法，结果落 `decisions.yaml`。

## 这一步决定什么

- **pin 布线层**（`pin_layer_h` 等）：选合适金属层，避免和 power/clock 抢资源，匹配上层 routing 方向。
- **pin spacing / side**：均匀铺开 vs 按消费者侧聚集；控制 pin 拥塞。
- **bus / group 约束**（`fragments`）：把同一总线/接口的 pin 成组、对齐到消费它的 block 一侧（数据流），减少绕线。
- top 级则是 pad ring / bump 分配。

## 决策前必读（READ before deciding）

1. **本阶段 spec**：`spec/stages/floorplan.yaml` 的 `parameters`（`pin_layer_h` / `pin_spacing_um` / `pin_side` 基线）。
2. **上游产出**：`stages/floorplan/artifacts/fp_init.def`（已定 die/core 形状，决定每侧可用边长）；回炉时读上一轮 `eval_result.yaml`。
3. **知识库**（按需）：
   - 概念：[read-eda-concept]（"IO pin placement"、"pin assignment"）。
   - 专家经验：[read-expert-doc]（先 [list-expert-topics]）。
   - 命令写法：[read-eda-lab-doc]（`editPin` / `assignIoPins` / `setPinAssignMode` 用法）。

## 防幻觉护栏（红线）

**写进 `fragments.io_pin_assignments` 的每条 Tcl（如 `editPin`、`assignIoPins`、`setPinAssignMode`）必须先经 [search-eda-command] 校验存在**；查不到不写。固定骨架在模板里，fragment 只放经校验的分组/对齐约束。

## decisions.yaml 契约

```yaml
params:                       # 键须与 place_io_pins.tcl.tmpl 的 {{占位}} 完全一致
  pin_layer_h: "M3"
  pin_spacing_um: 0.5
  pin_side: "Left"
fragments:                    # 键须与模板 `### @inject:<名>` 一致
  io_pin_assignments: |       # 经 search-eda-command 校验过的分组/对齐 Tcl
    # e.g. editPin -pin {data_bus*} -side Left -layer M3 -spreadType range ...
rationale: "分组/分层/分侧理由（数据流、拥塞、层资源），便于审计"
```

## 无人值守基线

`scripts/gen_decisions.py` 给确定性默认（均匀铺开、spec 指定层/侧/间距、无显式分组），保证无人值守走完；AI 据真实接口/总线改进。

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/floorplan-io-pins/scripts/gen_decisions.py \
  --workspace <ws> --step floorplan.place_io_pins \
  --spec <ws>/spec/stages/floorplan.yaml \
  --out <ws>/stages/floorplan/decisions/place_io_pins_decisions.yaml
```

输出单个 JSON 摘要（`status`/`out`/`params`/`fragments`）。
