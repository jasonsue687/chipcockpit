---
name: Route DRC Repair
description: This skill should be used when the orchestrator (or user) needs to decide DRC / antenna repair strategy for the route stage's drc_repair step — which DRC and antenna violations to fix and HOW (ECO search & repair, redundant via insertion, antenna diode insertion). Trigger on "repair DRC", "fix DRC violations", "drc_repair decision", "fix antenna violations", "search and repair", "ecoRoute fix drc", "redundant via insertion", "double via", "antenna diode", "post-route DRC clean", "DRC 修复", "修 DRC", "antenna 修复", "search & repair", "冗余 via 插入", "天线效应修复", "布线后 DRC 清理", or whenever the flow's route.drc_repair step needs its decisions.yaml. Produces decisions.yaml (params + fragments + rationale); a deterministic baseline in scripts/gen_decisions.py keeps the flow unattended.
version: 0.1.0
---

# Route DRC Repair — DRC/antenna 修复决策 playbook（drc_repair）

这是 route 阶段 **`drc_repair`** 步的 **AI 决策 playbook**（plan §7.1/§7.2：route 拆 2 个决策 skill，本 skill 专管 DRC/antenna 修复，[route-strategy] 管 global+detail route）：把详细布线后残余的 DRC / antenna violation 转成一份**修复策略**的 `decisions.yaml`，由 [render-tcl] 填进 `templates/tcl/route/drc_repair.tcl.tmpl`，再交 [run-eda-script] 执行——该步产出 **`routed_clean.def`（DRC-clean 布线）+ `drc.rpt`（route gate 报告）**。

> AI 决策节点内部流水线：**① 决策(本 playbook + 主 agent)→ ② render-tcl → ③ run-eda-script → ④ parse-eda-report**。本 skill 只装"怎么判断"，结果落 `decisions.yaml`（可审计、可重渲染、新会话可续跑）。真正的 gate 是 `route_eval`（解析 `drc.rpt` 的 `drc_violations`，max=0）。

## 这一步决定什么

- **修哪些 violation**：先 `verify_drc` 诊断 → 分类残余（short / spacing / min-area / via / antenna）。这是一个**迭代诊断回路**（plan §7.1）：verify → 针对性修 → 再 verify，直到 `drc_violations` 归零。
- **怎么修 DRC**（`fragments.drc_repair_cmds` + `ecoRoute -fix_drc`）：search & repair——对 short/spacing 用 `ecoRoute` 局部重布；顽固 short 可 `editDelete` 该线段后 `ecoRoute -nets <net>` 重连。
- **antenna 修复**（`antenna_fix_mode` / `antenna_diode_cell`）：`setNanoRouteMode -drouteFixAntenna` + 指定二极管单元（`-routeAntennaCellName`），靠层跳变 / 插二极管保护栅氧。
- **冗余 via 插入**（`via_in_pin` / `redundant_via_effort`）：`addVias` 双 via，提升良率与 EM 余量；`-routeWithViaInPin` 控制 pin 上是否补 via。
- **report limit**（`drc_report_limit`）：`verify_drc -limit`——一次报告多少条 violation，足够诊断即可。

## 决策前必读（READ before deciding）

1. **本阶段 spec**：`spec/stages/route.yaml`
   - `metrics.drc_violations.target`：gate 校验 `actual <= max`（max=0），mock 出 `total violations = <int>`——修复目标就是把它清零。
   - `parameters`：`drc_report_limit` / `antenna_fix_mode` / `antenna_diode_cell` / `via_in_pin` / `redundant_via`(→`redundant_via_effort`) 基线，可被本步覆盖。
2. **上游产出**：本阶段 detail_route 的 `stages/route/artifacts/routed.def`（要修的对象）；本步自己产的 `stages/route/reports/drc.rpt`（诊断依据）；回炉时读 `eval_result.yaml`（`retry_context.failed_metrics`）——DRC 未清零就提 NanoRoute 迭代（回 [route-strategy]）/ 加针对性 `ecoRoute` / 加二极管。
3. **知识库**（按需，progressive disclosure）：
   - 概念：[read-eda-concept]（"DRC"、"antenna effect"、"redundant via"、"search and repair"）。
   - 专家经验：[read-expert-doc]（DRC repair / antenna tips）；先 [list-expert-topics] 找文件名。
   - 命令片段写法：[read-eda-lab-doc]（DBTCL labs 里 verify_drc / ecoRoute / addVias / setNanoRouteMode 用法）。

## 防幻觉护栏（红线）

**本 playbook 写进 `fragments.drc_repair_cmds` 的每一条 Tcl 命令，必须先用 [search-eda-command] 校验它在 Innovus 命令空间里真实存在**（如 `verify_drc`、`ecoRoute`、`addVias`、`editDelete`、`setNanoRouteMode`、`deleteFiller`）。查不到的命令一律不写——把决策约束在真实命令空间内是防幻觉的关键。固定骨架（verify_drc / ecoRoute -fix_drc / antenna fix / addVias / re-verify + 写报告）已在模板里，`fragments.drc_repair_cmds` 只放经校验的针对性修复增量。

## decisions.yaml 契约

```yaml
params:                       # 键须与 drc_repair.tcl.tmpl 的 {{占位}} 完全一致
  drc_report_limit: 1000      # verify_drc -limit（报告多少条 violation）
  antenna_fix_mode: "true"    # setNanoRouteMode -drouteFixAntenna
  antenna_diode_cell: ANTENNA # 天线二极管单元名
  via_in_pin: "true"          # setNanoRouteMode -routeWithViaInPin
  redundant_via_effort: 2     # addVias 冗余 via 力度
fragments:                    # 键须与模板 `### @inject:<名>` 一致
  drc_repair_cmds: |          # 经 search-eda-command 校验的针对性修复 Tcl（可为空注释）
    # e.g. editDelete -net <shorted_net> ; ecoRoute -nets <shorted_net>
rationale: "为什么这样修（short/spacing/antenna 分类与修法、冗余 via 取舍），便于审计与回炉"
```

> `report_dir`（drc.rpt 写入目录）与 `artifact_dir`（routed_clean.def 写入目录）不是设计决策，由 harness `--var` 提供，不在 `params` 里重复。

## 无人值守基线

`scripts/gen_decisions.py` 给一份**确定性默认 decisions.yaml**（report limit 给足、antenna fix on + 默认二极管、双 via on + 默认力度，靠 `ecoRoute -fix_drc` + `addVias` 兜底），保证流程无人也能走完；AI 在此基础上对真实芯片改进——按 `drc.rpt` 实际 violation 分类（short/spacing/antenna/via）走迭代修复回路，针对性写 `ecoRoute`/`editDelete`/二极管命令。

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/route-drc-repair/scripts/gen_decisions.py \
  --workspace <ws> --step route.drc_repair \
  --spec <ws>/spec/stages/route.yaml \
  [--upstream-eval <ws>/stages/cts/eval_result.yaml] \
  --out <ws>/stages/route/decisions/drc_repair.yaml
```

输出单个 JSON 摘要（`status`/`out`/`params`/`fragments`）。
