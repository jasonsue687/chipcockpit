---
name: Parse EDA Report
description: This skill should be used when the user or orchestrator needs to turn a raw EDA report (timing/congestion/utilization/power/DRC .rpt) into a structured eval_result.yaml. Trigger on "parse eda report", "parse timing report", "extract metrics from report", "evaluate stage metrics", "generate eval_result", "解析 EDA 报告", "解析时序/拥塞报告", "提取报告指标", "评估阶段指标", "生成 eval_result", or whenever a flow gate step (gate: true, executor.ref = parse-eda-report) runs. Deterministic; does not require an EDA tool.
version: 0.1.0
---

# Parse EDA Report — 报告解析与阶段自评

把 EDA 工具产出的原始报告（`.rpt`）解析成结构化的 `eval_result.yaml`。这是后端流程里被引用最多的横切动作类 skill：所有 `gate: true` 的阶段质量门都用它产出供编排器/状态机判 pass/fail 的评估结果。

**它是确定性的**：只做"读报告 → 正则提取数值 → 与 spec 目标比对 → 组装 eval_result"，不调用任何 EDA 工具。因此可以在没有 Innovus 的环境里先跑通流程的 gate 逻辑。

## 何时使用

- 流程驱动：`flow_loader.py next` 返回一个 `executor.ref == parse-eda-report` 的 `run` 步骤（即某 stage 的 `*_eval` 门）。
- 手动：用户让你"解析这份 timing/congestion 报告并给出是否达标"。

## 输入约定

| 输入 | 来源 | 说明 |
|------|------|------|
| 报告文件 | stage 的 `reports/*.rpt` | 一个或多个，全部拼接后搜索 |
| stage spec | `<workspace>/spec/stages/<stage>.yaml` | 提供 `metrics:` 列表（指标名 + `target.min/max`） |
| header 信息 | 编排器传入 | `stage` / `run_id` / `spec_version` |

stage spec 的 `metrics` 沿用 `templates/stage_spec_template.yaml` 的格式：
```yaml
metrics:
  - name: utilization
    target: { min: 0.60, max: 0.80 }
  - name: congestion_hotspot
    target: { min: null, max: 0.80 }
  - name: wns_ns
    target: { min: -0.1, max: null }      # actual 必须 ≥ -0.1
```

## 如何调用

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/core/router.py parse-report \
  --report  <workspace>/stages/<stage>/reports/timing.rpt \
  --report  <workspace>/stages/<stage>/reports/congestion.rpt \
  --spec    <workspace>/spec/stages/<stage>.yaml \
  --stage   <stage> \
  --run-id  <run_id> \
  --spec-version <version> \
  --output  <workspace>/stages/<stage>/eval_result.yaml
```

- `--report` 可重复，多份报告会被拼接后统一搜索。
- 省略 `--output` 时把 eval_result 以 JSON 打到 stdout（适合预览）。
- 写入 `--output` 后，该文件就是流程 gate 步骤声明的 output，`flow_loader.py next` 会据此判该步完成。

## 输出（eval_result 契约）

遵循 `templates/eval_result_template.yaml`：

```yaml
stage: floorplan
run_id: run_001
spec_version: v1
overall: pass            # pass | fail | partial
metrics:
  - name: utilization
    target: { min: 0.6, max: 0.8 }
    actual: 0.72
    status: pass         # pass | fail | missing
recommendation: proceed  # proceed | retry | escalate
retry_context: null      # {failed_metrics: [...]} 当有 fail
escalation_reason: null  # 当有 missing（报告里没提取到该指标）
generated_by: parse-eda-report
```

判定规则：
- `status`：`actual` 落在 `[min, max]` 内为 `pass`（任一边界为 null 表示不约束）；越界为 `fail`；报告里提取不到为 `missing`。
- `overall`：任一 `fail` → `fail`；否则有 `missing` → `partial`；全 `pass` → `pass`。
- `recommendation`：`pass→proceed`、`fail→retry`、`partial→escalate`。

## 指标提取与扩展

内置一组启发式正则（`core/router.py` 的 `METRIC_PATTERNS`），覆盖常见指标名：
`wns_ns` · `tns_ns` · `hold_wns_ns` · `utilization` · `congestion_hotspot` ·
`macro_channel_width_um` · `power_grid_ir_drop` · `drc_violations` ·
`total_power_mw` · `global_skew_ps` · `max_insertion_delay_ps`。

报告格式各家不同。**当某指标的内置正则匹配不到（status=missing）时**，在 stage spec 的该指标项里加一行 `pattern:` 覆盖，捕获组 1 为数值：
```yaml
metrics:
  - name: utilization
    target: { min: 0.6, max: 0.8 }
    pattern: 'Core Density\s*=\s*([0-9.]+)'   # 覆盖内置正则
```
若发现某种报告格式反复出现，应把对应正则补进 `METRIC_PATTERNS`，让它成为默认能力。

## 关键规则

1. **绝不编造数值。** 提取不到就 `actual: null` + `status: missing`，让 `overall=partial` 上抛，而不是猜一个数。
2. **只解析、不判决流程走向。** 本 skill 给出 `recommendation` 作为建议；retry/rollback/abort 的最终决策权在编排器的状态机。
3. **单位由调用方对齐。** 提取的是报告里的原始数值，不做单位换算（如 % 与小数）；spec 的 `target` 必须与报告同单位。
