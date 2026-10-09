---
name: Version Check
description: This skill should be used when the user or orchestrator needs to verify that the design+library inputs (netlist · SDC · lib · LEF/PDK) all come from the SAME release/version before the EDA flow starts. Trigger on "version check", "check release consistency", "verify inputs same release", "are these inputs from the same release", "校验版本一致", "检查 release 一致性", "确认 netlist/SDC/lib 同一版本", or whenever a flow step (executor.ref = version-check) runs at the import head. Deterministic; does not require an EDA tool.
version: 0.1.0
---

# Version Check — 输入版本一致性校验（前置就绪的"版本一致"半）

在后端流程真正开始（read_design 读网表之前）做的一个**确定性**检查：确认这次跑流程的几份外部输入——`netlist`（网表）、`SDC`（约束）、`lib`（时序库）、`LEF/PDK`（物理库/工艺）——**来自同一个 release/版本**。一旦混进了不同 release 的输入（比如新网表配旧 SDC、lib 与 PDK 版本对不上），后面整条 EDA 流程会跑出莫名其妙的错误且极难定位；这个 skill 在流程头部一次性把它挡掉。

**它是确定性的，不调用任何 EDA 工具**：只做"扫每个输入文件头部 → 提取 release 标记 → 比对是否一致 → 写报告"。因此可以在没有 Innovus 的环境里跑通。它在流程里是一个**普通流程步**（不是 gate），位于 import stage 最前；跑一次通过即 done。

## 它在"前置就绪"里的位置

`docs/flow_pipeline_plan.md §3` 的「前置就绪」由三块组成，各有归属，互不重叠：

| 前置就绪的一块 | 谁负责 | 说明 |
|----------------|--------|------|
| **输入齐备**（文件都在） | flow_loader 的 `blocked_inputs` | required input 缺失 → 该步阻塞，不进入本 skill |
| **版本一致**（同 release） | **本 skill `version-check`** | 文件都在的前提下，校验它们同一 release |
| **工具就绪**（EDA 可用） | `env_manager` | 定位/校验 EDA 工具，与本 skill 无关 |

本 skill 只负责中间这一块——"版本一致"。

## 何时使用

- 流程驱动：`flow_loader.py next` 返回 import stage 第一个步骤 `version_check`（`executor.ref == version-check`）。
- 手动：用户给一组输入文件，让你确认"这些是不是同一版/同一 release"。

## 输入 → 输出契约

| 输入 | 来源 | 说明 |
|------|------|------|
| 网表 | `inputs/netlist.v` | required |
| 约束 | `inputs/constraints.sdc` | required |
| 物理库/工艺 | `inputs/tech.lef` | required |
| 时序库 | `inputs/cells.lib` | required |

输出：一份 `version_check.rpt`（默认写到 `stages/import/reports/version_check.rpt`），内容是 CONSISTENT / MISMATCH 结论 + 每个文件的 release。stdout 同时打一个 JSON 摘要（`status` / `releases` / `report`）。

## 如何调用

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/version-check/scripts/version_check.py \
  --input <workspace>/inputs/netlist.v \
  --input <workspace>/inputs/constraints.sdc \
  --input <workspace>/inputs/tech.lef \
  --input <workspace>/inputs/cells.lib \
  --out   <workspace>/stages/import/reports/version_check.rpt \
  [--expected-release <id>]
```

- `--input` 可重复，给所有要校验的输入文件。
- `--out` 写报告文件（流程步声明的 output；`flow_loader.py next` 据此判该步完成）。
- `--expected-release` 可选：若给定，则要求所有文件都等于这个 release（spec 锁版本场景）。

## release 标记如何被识别

每个输入文件的头部（前 ~10 行）应带一个 release 标记，按各自的注释语法写：

```verilog
// release: simrel_2026Q2      ← .v / .lef / .sdc 等 //- 或 #- 注释
```
```liberty
# release: simrel_2026Q2       ← .lib 等 # 注释
```

识别规则（确定性，扫前 ~10 行）：在 `#` 或 `//` 注释里找 `release:` 或 `version:` 字段，取冒号后的第一个 token 作为该文件的 release id。也接受裸的 `release: <id>` / `version: <id>` 字段行（无注释前缀）。一个文件提取不到标记 → 记为 `missing`。

## "mismatch" 报告长什么样

- **全部一致**：报告写 `RESULT: CONSISTENT`，列出 `release=<id>` 与参与校验的文件清单；`status: ok`，退出码 0。
- **不一致 / 缺标记**：报告写 `RESULT: MISMATCH`，逐文件列出各自的 release（或 `<missing>`），并指出哪些与多数/期望 release 不符；`status: mismatch`，退出码非 0。流程因此在 import 头部停下，提示更换到同一 release 的输入集，而不是带着混版输入往下跑。

## 关键规则

1. **绝不猜版本。** 提取不到标记就记 `missing` 并按 mismatch 处理上抛，不替文件编一个 release。
2. **只校验、不修复。** 本 skill 只报告一致 / 不一致；换文件、改 spec 锁版本由调用方/编排器决定。
3. **不调 EDA 工具。** 纯文本扫描，与 `run-eda-script` / `parse-eda-report` 同属流程横切的确定性 skill。
