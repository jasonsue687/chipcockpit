---
name: Powerplan Design
description: This skill should be used when the orchestrator (or user) needs to decide the power-delivery network (PDN) for the powerplan stage's gen_power_plan step — power ring width/spacing/offset, stripe width/spacing/pitch, and the sroute strategy that ties the grid to std-cell rails and macro pins. Trigger on "design power plan", "decide power grid", "set ring width", "set stripe pitch", "plan PDN", "gen_power_plan decision", "power ring spacing", "sroute strategy", "规划电源网络", "设计 power plan", "决定电源环宽度", "设定 stripe pitch", "设定电源条带", "PDN 决策", or whenever the flow's powerplan.gen_power_plan step needs its decisions.yaml. Produces decisions.yaml (params + fragments + rationale); a deterministic baseline in scripts/gen_decisions.py keeps the flow unattended.
version: 0.1.0
---

# Powerplan Design — PDN 几何决策 playbook（gen_power_plan）

这是 powerplan 阶段 **`gen_power_plan`** 步的 **AI 决策 playbook**：把这颗芯片的供电需求（电流密度/IR 预算/EM 上限/可用金属层）转成电源网络（PDN）几何的 `decisions.yaml`，由 [render-tcl] 填进 `templates/tcl/powerplan/gen_power_plan.tcl.tmpl`，再交 [run-eda-script] 执行——该步会 **产出一份自包含的 `power_plan.tcl` 工件**，供下游 `run_power_plan` 机械步 `source`。

> 这是一条 AI 决策节点的内部流水线：**① 决策(本 playbook + 主 agent)→ ② render-tcl → ③ run-eda-script → ④ parse-eda-report**。本 skill 只装"怎么判断"，结果落 `decisions.yaml`（可审计、可重渲染、新会话可续跑）。

## 这一步决定什么

- **power ring（电源环）**：环走哪些金属层（顶/底用横向层、左/右用纵向层）、`width`（线宽，决定能扛多大电流）、`spacing`（VDD/VSS 间距）、`offset`（环到 core 边的偏移）。
- **power stripe（电源条带）**：`width`（条带宽）、`spacing`（同组 VDD/VSS 间距）、`pitch`（条带组间距 `set_to_set_distance`）——pitch 越小、width 越宽 → IR drop 越低，但占用越多布线资源 / 越多 EM 风险点、std-cell 面积越紧。
- **sroute 策略**：`sroute_target`（连什么——`corePin` 接 std-cell 电轨、`floatingStripe`/`blockPin` 接宏 PG pin 等），以及 ring↔stripe 的层变换范围。
- **IR / EM 权衡（核心取舍）**：更宽更密的网格压低 IR drop（gate 指标 `power_grid_ir_drop`，单位 mV）、改善 EM 余量，但吃掉布线轨道、抬高拥塞与面积。决策就是在 spec 的 IR 预算（`metrics.power_grid_ir_drop.max`）下选**刚好够用**的网格密度。

## 决策前必读（READ before deciding）

1. **本阶段 spec**：`spec/stages/powerplan.yaml`
   - `metrics[].target`：`power_grid_ir_drop`（IR 预算，gate 会校验 `actual <= max`，单位 mV）——网格密度决策必须把预期 IR 压在带内。
   - `parameters`：`ring_width_um` / `ring_spacing_um` / `stripe_width_um` / `stripe_spacing_um` / `stripe_pitch_um` / `sroute_target` / 层选择 等基线，可被本步覆盖。
2. **上游真实信息**：floorplan 的 `stages/floorplan/eval_result.yaml`（实际 utilization / 可用 channel → 决定能给 PDN 留多少布线资源）；若是失败回炉，读上一轮 `stages/powerplan/eval_result.yaml`（`retry_context.failed_metrics`）——IR 超标就加宽 ring/stripe 或缩小 pitch。
3. **知识库**（按需，progressive disclosure）：
   - 概念：[read-eda-concept]（"IR drop"、"power planning"、"EM"、"power mesh"）。
   - 专家经验：[read-expert-doc]（power-plan / PDN tips）；先 [list-expert-topics] 找文件名。
   - 命令片段写法：[read-eda-lab-doc]（DBTCL labs 里 addRing/addStripe/sroute 用法）。

## 防幻觉护栏（红线）

**本 playbook 写进 `fragments` 的每一条 Tcl 命令，必须先用 [search-eda-command] 校验它在 Innovus 命令空间里真实存在**（如 `addRing`、`addStripe`、`sroute`、`setViaGenMode`、`editPowerVia`）。查不到的命令一律不写——把决策约束在真实命令空间内是防幻觉的关键。固定骨架（ring/stripe/sroute）已在模板里，`fragments.extra_pg_cmds` 只放经校验的增量（额外 block ring、二级 stripe、特定层的 via 策略等）。

## decisions.yaml 契约

```yaml
params:                       # 键须与 gen_power_plan.tcl.tmpl 的 {{占位}} 完全一致
  ring_layer: M7              # 横向环层
  ring_layer_v: M8            # 纵向环层
  ring_width_um: 2.0
  ring_spacing_um: 0.5
  ring_offset_um: 1.0
  stripe_layer: M8
  stripe_width_um: 1.0
  stripe_spacing_um: 0.5
  stripe_pitch_um: 20.0       # set_to_set_distance；越小 IR 越低、布线越紧
  sroute_target: corePin
fragments:                    # 键须与模板 `### @inject:<名>` 一致
  extra_pg_cmds: |            # 经 search-eda-command 校验过的增量 Tcl（可为空注释）
    # e.g. addRing -nets ... (block ring around a hard macro)
rationale: "为什么这样选（IR 预算 vs 布线资源/EM 权衡），便于审计与回炉"
```

> `power_net` / `ground_net` / `artifact_dir` 不是设计决策，由 spec 参数 + harness `--var` 提供，不在 `params` 里重复。

## 无人值守基线

`scripts/gen_decisions.py` 给一份**确定性默认 decisions.yaml**（ring/stripe 宽度·间距·pitch 取 spec 参数，sroute 接 corePin），保证流程无人也能走完；AI 在此基础上对真实芯片改进——按 IR 预算与可用层资源调网格密度。

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/powerplan-design/scripts/gen_decisions.py \
  --workspace <ws> --step powerplan.gen_power_plan \
  --spec <ws>/spec/stages/powerplan.yaml \
  [--upstream-eval <ws>/stages/floorplan/eval_result.yaml] \
  --out <ws>/stages/powerplan/decisions/gen_power_plan.yaml
```

输出单个 JSON 摘要（`status`/`out`/`params`/`fragments`）。
