---
name: Placement Design
description: This skill should be used when the orchestrator (or user) needs to decide standard-cell placement strategy for the placement stage's place_opt step — utilization margin, congestion-driven placement effort, high-fanout-net synthesis (HFNS), and tie-cell insertion. Trigger on "design placement", "decide placement strategy", "set utilization margin", "congestion-driven placement", "place_opt decision", "HFNS threshold", "high-fanout net synthesis", "tie cell insertion", "标准单元布局决策", "设计 placement", "决定布局利用率裕量", "拥塞驱动布局", "设定 HFNS 阈值", "tie cell 插入", "place_opt 决策", or whenever the flow's placement.place_opt step needs its decisions.yaml. Produces decisions.yaml (params + fragments + rationale); a deterministic baseline in scripts/gen_decisions.py keeps the flow unattended.
version: 0.1.0
---

# Placement Design — 标准单元布局决策 playbook（place_opt）

这是 placement 阶段 **`place_opt`** 步的 **AI 决策 playbook**：把这颗芯片的 pre-CTS 现实（floorplan 实际利用率、电源网格留下的布线资源、拥塞热点、高扇出网络）转成标准单元布局 + 优化的 `decisions.yaml`，由 [render-tcl] 填进 `templates/tcl/placement/place_opt.tcl.tmpl`，再交 [run-eda-script] 执行——该步产出 `placed.def`，供下游 `scan_reorder` / `congestion_analysis` 使用。

> 这是一条 AI 决策节点的内部流水线：**① 决策(本 playbook + 主 agent)→ ② render-tcl → ③ run-eda-script → ④ parse-eda-report**。本 skill 只装"怎么判断"，结果落 `decisions.yaml`（可审计、可重渲染、新会话可续跑）。`congestion_analysis` 是本阶段一个**非 gate 的自动校验**（机械步，产 `congestion.rpt`）；真正的 gate 是 `placement_eval`（比对 congestion / pre-CTS timing）。

## 这一步决定什么

- **利用率裕量（utilization margin）**：`setPlaceMode -place_global_cong_effort` 之外，给 global place 留多少裕量（`target_utilization_margin`）。floorplan 实际 util 越高、PG 吃掉的轨道越多 → 越要留裕量压拥塞，否则 place 出来直接堵死。
- **拥塞驱动布局（congestion-driven placement）**：`-place_global_cong_effort`（low/medium/high）与 timing 努力档（`place_global_timing_effort`）的权衡。congestion effort 越高越能摊开热点，但牺牲时序与 runtime；timing effort 越高越追 WNS，但可能把单元堆密、加剧拥塞。决策就是在 spec 的 `congestion_hotspot` 预算（gate 指标 `max`）下选**刚好够用**的 congestion effort，timing 努力随 pre-CTS 余量给。
- **HFNS（high-fanout net synthesis，高扇出网络综合）**：`setPlaceMode -place_global_max_fanout`（即 `hfns_threshold_fanout`）——扇出超过阈值的网络在 place 时打 buffer/inverter 树，避免巨扇出网络拖垮 pre-CTS timing 和拥塞。阈值过低会插太多 buffer 抬面积，过高会留长尾高扇出网。
- **tie cell 插入（tie-high / tie-low）**：把常量 1/0 引脚连到 `tie_cell`（如 `TIEHI`/`TIELO`），并控制最大扇出/最大距离，避免悬空常量引脚在 signoff 报错。

## 决策前必读（READ before deciding）

1. **本阶段 spec**：`spec/stages/placement.yaml`
   - `metrics[].target`：`congestion_hotspot`（拥塞预算，gate 会校验 `actual <= max`，mock 出 `total overflow = <v>`）——congestion effort 与 util 裕量决策必须把预期拥塞压在带内。
   - `parameters`：`target_utilization_margin` / `congestion_effort` / `place_global_timing_effort` / `hfns_threshold_fanout` / `tie_cell` 等基线，可被本步覆盖。
2. **上游真实信息**：powerplan 的 `stages/powerplan/eval_result.yaml`（实际 IR drop / PG 连通性 → PG 越密留给信号布线的资源越少 → 越要保守的 util 裕量与更高 congestion effort）；若是失败回炉，读上一轮 `stages/placement/eval_result.yaml`（`retry_context.failed_metrics`）——拥塞超标就调高 congestion effort / 加大 util 裕量 / 降 timing effort。
3. **知识库**（按需，progressive disclosure）：
   - 概念：[read-eda-concept]（"placement optimization"、"congestion"、"high fanout net"、"tie cell"）。
   - 专家经验：[read-expert-doc]（placement / congestion tips）；先 [list-expert-topics] 找文件名。
   - 命令片段写法：[read-eda-lab-doc]（DBTCL labs 里 placeDesign/setPlaceMode/addTieHiLo 用法）。

## 防幻觉护栏（红线）

**本 playbook 写进 `fragments` 的每一条 Tcl 命令，必须先用 [search-eda-command] 校验它在 Innovus 命令空间里真实存在**（如 `placeDesign`、`place_opt_design`、`setPlaceMode`、`addTieHiLo`、`setOptMode`、`refinePlace`）。查不到的命令一律不写——把决策约束在真实命令空间内是防幻觉的关键。固定骨架（setPlaceMode / placeDesign / tie-cell）已在模板里，`fragments.extra_place_options` 只放经校验的增量（额外 `setPlaceMode` 选项、`createPlaceBlockage`、特定 module 的 `addPlacePartition` 等）。

## decisions.yaml 契约

```yaml
params:                            # 键须与 place_opt.tcl.tmpl 的 {{占位}} 完全一致
  target_utilization_margin: 0.05  # global place 利用率裕量（0~1）
  congestion_effort: medium        # -place_global_cong_effort low|medium|high
  place_global_timing_effort: medium  # -place_global_timing_effort
  hfns_threshold_fanout: 32        # HFNS 触发扇出阈值（-place_global_max_fanout）
  tie_cell: TIELO                  # tie-low/high 单元
fragments:                         # 键须与模板 `### @inject:<名>` 一致
  extra_place_options: |           # 经 search-eda-command 校验过的增量 Tcl（可为空注释）
    # e.g. createPlaceBlockage -box {...} (carve a soft blockage over a hotspot)
rationale: "为什么这样选（拥塞预算 vs 时序/面积权衡，PG 资源占用），便于审计与回炉"
```

> `tie_net_high` / `tie_net_low` / `artifact_dir` / `report_dir` 不是设计决策，由 spec 参数 + harness `--var` 提供，不在 `params` 里重复。

## 无人值守基线

`scripts/gen_decisions.py` 给一份**确定性默认 decisions.yaml**（util 裕量·congestion/timing effort·HFNS 阈值·tie cell 取 spec 参数），保证流程无人也能走完；AI 在此基础上对真实芯片改进——按 `congestion_hotspot` 预算与上游 IR/PG 资源占用调 congestion effort 与 util 裕量。

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/placement-design/scripts/gen_decisions.py \
  --workspace <ws> --step placement.place_opt \
  --spec <ws>/spec/stages/placement.yaml \
  [--upstream-eval <ws>/stages/powerplan/eval_result.yaml] \
  --out <ws>/stages/placement/decisions/place_opt.yaml
```

输出单个 JSON 摘要（`status`/`out`/`params`/`fragments`）。
