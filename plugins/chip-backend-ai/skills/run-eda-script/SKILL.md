---
name: Run EDA Script
description: This skill should be used when the user or orchestrator needs to execute a Tcl script in an EDA tool (Innovus) and collect its log + output files. Trigger on "run eda script", "run tcl in innovus", "execute innovus script", "run the floorplan/cts/route tcl", "跑这个 tcl", "在 innovus 里执行脚本", "执行 EDA 脚本", "运行 innovus 脚本", or whenever a flow step (executor.ref = run-eda-script) needs to run. Locates the tool via env_manager; falls back to a clearly-marked stub mode when the tool is unavailable.
version: 0.1.0
---

# Run EDA Script — EDA 脚本执行器

在 EDA 工具（Innovus）里执行一个 Tcl 脚本，捕获 log，并校验脚本应当产出的文件是否生成。这是后端流程里被引用最多的执行类 skill：几乎所有非 gate、非判断型的步骤（import、power、placement、route、tapeout…）都通过它把 Tcl 真正跑起来。

**它刻意"笨"**：只负责"跑脚本 + 收 log + 验产出"，不解析指标（那是 [parse-eda-report] 的职责），也不决定流程走向（那是编排器状态机的职责）。

## 何时使用

- 流程驱动：`flow_loader.py next` 返回一个 `executor.ref == run-eda-script` 的 `run` 步骤。
- 手动：用户让你"在 Innovus 里跑这个 tcl 并看结果"。

## 工具定位

复用 `core/env/env_manager.py` 的机器级配置（`~/.chip-backend-ai/env.json`）。先确保已配置：
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/core/env/env_manager.py check --tool innovus
```
退出码 `0`=就绪。若未配置，先 `detect --save` 或 `set --tool innovus --path <path>`（见 run-chip-flow 的 Phase 0）。

## 如何调用

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/run-eda-script/scripts/run_eda_script.py \
  --script        <workspace>/stages/<stage>/artifacts/<step>.tcl \
  --expect-output <workspace>/stages/<stage>/artifacts/<step_out>.def \
  --expect-output <workspace>/stages/<stage>/reports/<step>.rpt \
  --log           <workspace>/stages/<stage>/logs/<step>.log
```

- `--script`：要执行的 Tcl（通常由上游 `gen-*-tcl` skill 或 agent 生成）。
- `--expect-output`：可重复。**直接对应 flow step 的 `outputs`**——执行后逐一校验是否生成，作为成败判据。
- `--log`：合并 stdout/stderr 的日志路径（默认 `<script>.log`）。
- `--tool`/`--config`：默认 `innovus` + 机器级 env.json。
- `--timeout`：超时秒数（防止工具挂死）。
- `--stub`：强制 stub 模式（不调工具，占位产出，绝不造指标）。
- `--mock`：强制仿真模式（不调工具，产出标注 SIMULATED 的占位文件，并生成"在目标区间内"的合成指标）。
- `--report`：（mock）写一份可被 [parse-eda-report] 解析的合成指标报告路径——让下游 gate 在仿真下能 PASS；**需同时传 `--stage` 与 `--spec`**。
- `--stage`：（mock）阶段名，用于报告头与指标选择。
- `--spec`：（mock）该阶段 spec yaml，提供指标清单与目标值。

调用约定：把 flow step 返回的 `outputs[].path` 逐个映射成 `--expect-output`，把要跑的 Tcl 映射成 `--script`。

## 输出

单个 JSON 对象：
```json
{
  "status": "ok",          // ok | mock | stub | failed | error
  "mode": "run",           // run | mock | stub
  "tool": "innovus",
  "binary": "/opt/cadence/INNOVUS221/bin/innovus",
  "returncode": 0,
  "log": ".../route.log",
  "produced": [".../routed.def", ".../drc.rpt"],
  "missing": []
}
```

判定：`returncode == 0` **且** 所有 `--expect-output` 都生成 → `status: ok`；否则 `failed`（`missing` 列出缺失产出）。`--mock` 仿真运行成功时返回 `status: "mock"`（产出已标注 SIMULATED），`--stub` 降级成功时返回 `status: "stub"`。退出码：`ok`/`mock`/`stub` → 0，其余 → 1。

编排器据此 `flow_loader.py mark`：`ok`/`mock`/`stub` → `--status done`；`failed`/`error` → `--status failed`（交回状态机判 retry/rollback）。`mock`/`stub` 表示该步骤是仿真/降级产出，并非真实 EDA 结果——务必据此向用户说明。

## Stub 模式（工具不可用时的降级）

当 Innovus 未配置/不可用，或显式传 `--stub` 时进入 stub 模式：
- **不调用工具**，写一份明确标注的 stub 日志；
- 为每个 `--expect-output` 创建**占位文件**（带 "STUB" 头），让 `flow_loader.py next` 看到产出存在、流程结构可以继续 dry-run；
- **绝不编造指标数值**。占位报告里没有真实数字，因此下游 gate 步骤经 [parse-eda-report] 解析会如实得到 `missing`（overall=partial），而不是假装通过。

这让你在没有 EDA 环境的机器上也能把整条流程的**结构**走通，同时诚实地把"没有真实数据"暴露出来。

## 关键规则

1. **只执行，不判断。** 成败只看退出码 + 产出文件是否齐全；指标判定交给 [parse-eda-report]，流程决策交给编排器。
2. **stub 不造假。** 工具缺失时创建占位产出让流程能走，但绝不伪造 PPA 数字。
3. **每次执行都留 log。** 真实跑或 stub 都写日志，便于排查。
