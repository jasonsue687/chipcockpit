---
name: Route Strategy
description: This skill should be used when the orchestrator (or user) needs to decide routing strategy for the route stage's global_route AND detail_route steps — routing-layer window, clock/critical-net non-default routing rule (NDR), shielding, NanoRoute options, and post-route optimization effort. Trigger on "design route strategy", "decide routing strategy", "global route decision", "detail route decision", "layer assignment", "route NDR", "shield clock nets", "NanoRoute options", "post-route optimization", "track assignment", "布线策略决策", "全局布线决策", "详细布线决策", "层分配", "布线 NDR", "时钟网络屏蔽", "NanoRoute 选项", "post-route 优化", or whenever the flow's route.global_route or route.detail_route step needs its decisions.yaml. Produces decisions.yaml (params + fragments + rationale); a deterministic baseline in scripts/gen_decisions.py (branching on --step) keeps the flow unattended.
version: 0.1.0
---

# Route Strategy — 布线策略决策 playbook（global_route + detail_route）

这是 route 阶段 **两个紧耦合的 AI 决策步**的共用 playbook（plan §7.1：route 是最重的 stage，拆 2 个决策 skill；本 skill 覆盖 global+detail，`route-drc-repair` 覆盖 drc_repair）：

| 步 | 决定 | 模板 |
|----|------|------|
| `global_route` | 路由层窗 / 时钟·关键网络 NDR / shielding（全局布线 + track assignment） | `templates/tcl/route/global_route.tcl.tmpl` |
| `detail_route` | NanoRoute 选项 / post-route 优化档位（详细布线 + 优化） | `templates/tcl/route/detail_route.tcl.tmpl` |

两步同一 playbook，因为 **global route 的层分配/NDR/shield 约束了 detail route 的 NanoRoute 选项与 post-route 优化档位**。`scripts/gen_decisions.py` **按 `--step` 分支**产出对应 params/fragments，由 [render-tcl] 填进模板，再交 [run-eda-script] 执行。

> AI 决策节点内部流水线：**① 决策(本 playbook + 主 agent)→ ② render-tcl → ③ run-eda-script → ④ parse-eda-report**。本 skill 只装"怎么判断"，结果落 `decisions.yaml`（可审计、可重渲染、新会话可续跑）。drc_repair（DRC/antenna 修复，产 `routed_clean.def` + `drc.rpt`）由独立的 [route-drc-repair] skill 决策；真正的 gate 是 `route_eval`（比对 `drc_violations`，max=0）。

## 各步决定什么

**global_route**（全局布线 + track assignment）
- **路由层窗**（`route_top_layer` / `route_bottom_layer`）：`setNanoRouteMode -routeTopRoutingLayer / -routeBottomRoutingLayer`——限定可用金属栈；关键/时钟网络一般往上层走（电阻低、耦合小）。
- **时钟·关键网络 NDR**（`ndr_name` + `ndr_width_mult` / `ndr_spacing_mult`）：`create_route_rule`——给时钟与关键网络加宽、加间距，降低串扰与 OCV 引起的 skew/timing 变化。加得越多越稳，但吃布线资源（拥塞重时务实些）。
- **shielding**（`fragments.critical_net_route_cmds`）：对最敏感网络（时钟 / 异步 / 模拟）加屏蔽线（接地/电源夹护），进一步压串扰。
- **timing / SI 驱动**（`timing_driven` / `si_driven`）：`setNanoRouteMode -routeWithTimingDriven / -routeWithSiDriven`——让全局布线兼顾时序与串扰。

**detail_route**（NanoRoute + post-route 优化）
- **NanoRoute 选项**（`droute_end_iteration` / `route_with_eco` / `fragments.nanoroute_opts`）：详细布线迭代预算与 ECO 模式；DRC/时序残留多时提迭代或加 litho/antenna 选项。
- **post-route 优化档位**（`postroute_opt_effort`）：`setOptMode -postRouteOptEffort` + `optDesign -postRoute`——档位越高越收时序/DRV，但运行越久。

## 决策前必读（READ before deciding）

1. **本阶段 spec**：`spec/stages/route.yaml`
   - `metrics[].target`：`drc_violations`（gate 校验 `actual <= max`，mock 出 `total violations = <int>`，max=0）——层分配/NDR/shield + NanoRoute 迭代/effort 都要服务于布线干净、零 DRC。
   - `parameters`：`route_top_layer` / `route_bottom_layer` / `ndr_name`(+`ndr_width_mult`/`ndr_spacing_mult`) / `timing_driven` / `si_driven` / `critical_net_layers` / `shield_nets` / `nanoroute_effort`(→`droute_end_iteration`) / `route_with_eco` / `postroute_opt_level`(→`postroute_opt_effort`) 等基线，可被本步覆盖。
2. **上游真实信息**：cts 的 `stages/cts/eval_result.yaml`（实际 skew/insertion → 时钟网络是否需更强 NDR/shield）；若是失败回炉，读上一轮 `stages/route/eval_result.yaml`（`retry_context.failed_metrics`）——DRC 超标就提 NanoRoute 迭代 / 放宽过激 NDR / 收紧 shielding 区域。
3. **知识库**（按需，progressive disclosure）：
   - 概念：[read-eda-concept]（"global routing"、"detail routing"、"NanoRoute"、"non-default routing rule"、"shielding"、"crosstalk"）。
   - 专家经验：[read-expert-doc]（routing / NanoRoute tips）；先 [list-expert-topics] 找文件名。
   - 命令片段写法：[read-eda-lab-doc]（DBTCL labs 里 globalRoute / routeDesign / setNanoRouteMode / create_route_rule 用法）。

## 防幻觉护栏（红线）

**本 playbook 写进 `fragments` 的每一条 Tcl 命令，必须先用 [search-eda-command] 校验它在 Innovus 命令空间里真实存在**（如 `setNanoRouteMode`、`globalRoute`、`routeDesign`、`create_route_rule`、`setAttribute`、`addRouteShield`、`optDesign`）。查不到的命令一律不写——把决策约束在真实命令空间内是防幻觉的关键。固定骨架（层窗 / NDR / timing·SI 驱动 / routeDesign / post-route opt）已在模板里，`fragments.critical_net_route_cmds`（global）与 `fragments.nanoroute_opts`（detail）只放经校验的增量。

## decisions.yaml 契约

`global_route`：
```yaml
params:                       # 键须与 global_route.tcl.tmpl 的 {{占位}} 完全一致
  route_top_layer: M7         # 路由层窗上界
  route_bottom_layer: M1      # 路由层窗下界
  ndr_name: ROUTE_2W2S        # 时钟/关键网络 NDR 名
  ndr_spacing_mult: 2         # NDR 间距倍数
  ndr_width_mult: 2           # NDR 线宽倍数
  timing_driven: "true"       # -routeWithTimingDriven
  si_driven: "true"           # -routeWithSiDriven
fragments:                    # 键须与模板 `### @inject:<名>` 一致
  critical_net_route_cmds: |  # 经 search-eda-command 校验的层分配/NDR/shield 增量
    # e.g. setAttribute -net clk -non_default_rule ROUTE_2W2S
rationale: "为什么这样选（层分配/NDR/shield vs 布线资源权衡）"
```

`detail_route`：
```yaml
params:                       # 键须与 detail_route.tcl.tmpl 的 {{占位}} 完全一致
  timing_driven: "true"
  si_driven: "true"
  droute_end_iteration: 5     # NanoRoute 详细布线迭代预算
  route_with_eco: "false"     # 是否 ECO 模式布线
  postroute_opt_effort: high  # -postRouteOptEffort 档位
fragments:
  nanoroute_opts: |           # 经校验的额外 setNanoRouteMode 选项（可为空注释）
    # e.g. setNanoRouteMode -routeWithLithoDriven true
rationale: "NanoRoute 迭代/effort 与 DRC/时序残留权衡"
```

> `artifact_dir`（groute.def / routed.def 的写入目录）不是设计决策，由 harness `--var` 提供，不在 `params` 里重复。

## 无人值守基线（按 --step 分支）

`scripts/gen_decisions.py` 按 `--step` 给确定性默认：`global_route` 用 spec 层窗 + NDR 倍数 + timing/SI 驱动 on；`detail_route` 用 spec NanoRoute 迭代/effort（`nanoroute_effort`→`droute_end_iteration`、`postroute_opt_level`→`postroute_opt_effort`）。保证流程无人也能走完；AI 在此基础上对真实芯片改进——按 `drc_violations` 预算与上游 cts skew/拥塞资源占用调层分配、NDR 倍数、shield 范围与 NanoRoute 迭代/effort。

```bash
# 全局布线策略
python3 ${CLAUDE_PLUGIN_ROOT}/skills/route-strategy/scripts/gen_decisions.py \
  --workspace <ws> --step route.global_route \
  --spec <ws>/spec/stages/route.yaml \
  [--upstream-eval <ws>/stages/cts/eval_result.yaml] \
  --out <ws>/stages/route/decisions/global_route.yaml

# 详细布线策略
python3 ${CLAUDE_PLUGIN_ROOT}/skills/route-strategy/scripts/gen_decisions.py \
  --workspace <ws> --step route.detail_route \
  --spec <ws>/spec/stages/route.yaml \
  [--upstream-eval <ws>/stages/cts/eval_result.yaml] \
  --out <ws>/stages/route/decisions/detail_route.yaml
```

输出单个 JSON 摘要（`status`/`out`/`params`/`fragments`）。
