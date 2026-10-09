---
name: Floorplan Plan
description: This skill should be used when the orchestrator (or user) needs to decide the floorplan's die/core geometry — die/core size, aspect ratio, core-to-IO margin, and target utilization — for the floorplan stage's gen_floorplan step. Trigger on "plan floorplan", "decide die size", "decide core size", "set aspect ratio", "set target utilization", "gen_floorplan decision", "规划 floorplan", "决定 die/core 尺寸", "设定 aspect ratio", "设定目标利用率", or whenever the flow's floorplan.gen_floorplan step needs its decisions.yaml. Produces decisions.yaml (params + fragments + rationale); a deterministic baseline in scripts/gen_decisions.py keeps the flow unattended.
version: 0.1.0
---

# Floorplan Plan — die/core 几何决策 playbook（gen_floorplan）

这是 floorplan 阶段 **`gen_floorplan`** 步的 **AI 决策 playbook**：把这颗芯片的真实数字（面积/宏数量/IO 数/时序余量）转成 die/core 几何的 `decisions.yaml`，由 [render-tcl] 填进 `templates/tcl/floorplan/gen_floorplan.tcl.tmpl`，再交 [run-eda-script] 执行。

> 这是一条 AI 决策节点的内部流水线：**① 决策(本 playbook + 主 agent)→ ② render-tcl → ③ run-eda-script → ④ parse-eda-report**。本 skill 只装"怎么判断"，结果落 `decisions.yaml`（可审计、可重渲染、新会话可续跑）。

## 这一步决定什么

- **target utilization**（目标核心利用率）：在 spec `metrics.utilization` 的 `[min,max]` 带内取一个留有收敛余量的值（太高 → 后续 placement/route 拥塞，太低 → 浪费面积）。
- **aspect ratio**（核心宽高比）：默认 1.0（方形）；窄长 block、特定 IO/宏分布或上层 partition 形状会驱动非方形。
- **core-to-IO margin**：core 边到 IO/pad ring 的间距，给 power ring / IO routing 留空间。
- （隐含）die/core size：由 util + 单元面积估算 + margin 推导，`floorPlan -r` 用 util 反算。

## 决策前必读（READ before deciding）

1. **本阶段 spec**：`spec/stages/floorplan.yaml`
   - `metrics[].target`：`utilization`（带）、`macro_channel_width_um`（gate 会校验）——util 决策必须落在带内。
   - `parameters`：`target_utilization` / `aspect_ratio` / `core_to_io_margin_um` 的基线，可被本步覆盖。
2. **上游真实信息**：import 的 `stages/import/eval_result.yaml`（实际单元面积/util 提示）；若是失败回炉，读上一轮 `stages/floorplan/eval_result.yaml`（`retry_context.failed_metrics`）按需放松 util / 调 aspect。
3. **知识库**（按需，progressive disclosure）：
   - 概念：[read-eda-concept]（"floorplan"、"utilization"、"aspect ratio"）。
   - 专家经验：[read-expert-doc]（floorplan tips）；先 [list-expert-topics] 找文件名。
   - 命令片段写法：[read-eda-lab-doc]（DBTCL labs 里 floorPlan/specifyFloorplan 用法）。

## 防幻觉护栏（红线）

**本 playbook 写进 `fragments` 的每一条 Tcl 命令，必须先用 [search-eda-command] 校验它在 Innovus 命令空间里真实存在**（如 `floorPlan`、`specifyFloorplan`、`setObjFPlanBox`）。查不到的命令一律不写——决策被约束在真实命令空间内是防幻觉的关键。固定骨架已在模板里，`fragments.extra_floorplan_options` 只放经校验的增量。

## decisions.yaml 契约

```yaml
params:                       # 键须与 gen_floorplan.tcl.tmpl 的 {{占位}} 完全一致
  aspect_ratio: 1.0
  target_utilization: 0.70    # 落在 spec utilization 带内
  core_to_io_margin_um: 5.0
fragments:                    # 键须与模板 `### @inject:<名>` 一致
  extra_floorplan_options: |  # 经 search-eda-command 校验过的增量 Tcl（可为空注释）
    # e.g. setObjFPlanBox ...
rationale: "为什么这样选（面积/宏/时序权衡），便于审计与回炉"
```

## 无人值守基线

`scripts/gen_decisions.py` 给一份**确定性默认 decisions.yaml**（util 取 spec 带中点、方形、默认 margin），保证流程无人也能走完；AI 在此基础上对真实芯片改进。

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/floorplan-plan/scripts/gen_decisions.py \
  --workspace <ws> --step floorplan.gen_floorplan \
  --spec <ws>/spec/stages/floorplan.yaml \
  [--upstream-eval <ws>/stages/import/eval_result.yaml] \
  --out <ws>/stages/floorplan/decisions/gen_floorplan_decisions.yaml
```

输出单个 JSON 摘要（`status`/`out`/`params`/`fragments`）。
