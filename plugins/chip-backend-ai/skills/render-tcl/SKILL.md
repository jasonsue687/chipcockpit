---
name: Render Tcl
description: This skill should be used when the user or orchestrator needs to turn a golden Tcl template plus an AI decisions file into a concrete, ready-to-run Tcl script. Trigger on "render tcl", "render the template", "fill the tcl template", "generate tcl from decisions", "渲染 tcl", "渲染模板", "用 decisions 生成 tcl", "把模板填成脚本", or whenever a flow step needs its `template` rendered before run-eda-script. Deterministic; carries no judgement and does not invoke any EDA tool.
version: 0.1.0
---

# Render Tcl — 模板渲染器（确定性，无判断）

把黄金模板（`templates/tcl/<stage>/<step>.tcl.tmpl`）+ 决策文件（`decisions.yaml`）渲染成一份具体可跑的 `<step>.tcl`，交给 [run-eda-script] 执行。这是后端流程"自动执行"和"AI 决策"两类节点共用的横切**渲染层**。

**它刻意"笨"且确定性**：只做"填占位符 + 注入片段"，不做任何判断（判断在决策 skill / 主 agent 那一步，结果落在 `decisions.yaml`），也不调用任何 EDA 工具。

## 何时使用

- 流程驱动：`flow_loader.py next` 返回一个带 `template:` 字段的 `run` 步骤（executor.ref == run-eda-script）。先 render，再把渲染出的 `.tcl` 喂给 run-eda-script。
- 手动：用户让你"把这个模板按 decisions 渲染成脚本"。

## 上下文合并（后者覆盖前者）

渲染时把多个来源合并成一个扁平 context，优先级从低到高：

1. **stage spec 顶层标量**（如 `technology`、`top_module`）——`--spec`
2. **stage spec `parameters`**（每阶段指导参数）——`--spec`
3. **decisions `params`**（AI 为这颗芯片决定的参数）——`--decisions`
4. **workspace 派生路径变量**（`--workspace`+`--stage` 自动注入的 7 个路径）
5. **`--var k=v`**（调用时的显式覆盖，最高优先级）

> 第 4 类：同时给 `--workspace <ws>` 和 `--stage <stage>`，会自动注入 7 个 workspace 路径变量，无需手写：
> `report_dir`、`artifact_dir`、`netlist`、`lef`、`lib`、`sdc`、`lib_search_path`。
> 其中 `report_dir`/`artifact_dir` 会被自动创建。其余占位符仍由 `--spec`（stage spec 标量/parameters）、`--decisions` 与显式 `--var`（最高优先级）补齐。

## 占位符与注入

- `{{name}}`：用 context 里的 `name` 替换。
- `### @inject:<blockname>`：整行替换为 `decisions.fragments.<blockname>` 的多行 Tcl（AI 写的片段）。该 block 不存在时，替换成 `# (no fragment ...)` 注释——**绝不**在输出里留下裸 `### @inject:`。

**护栏：** 若替换后仍有任何 `{{...}}` 未填，**拒绝产出 Tcl**，以非零退出码返回未填变量名列表（绝不写一份带裸 `{{...}}` 的脚本去让工具报神秘错误）。

## 如何调用

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/render-tcl/scripts/render_tcl.py \
  --template ${CLAUDE_PLUGIN_ROOT}/templates/tcl/import/read_design.tcl.tmpl \
  --out      <workspace>/stages/import/scripts/read_design.tcl \
  --spec     <workspace>/spec/stages/import.yaml \
  --decisions <workspace>/stages/import/decisions/read_design_decisions.yaml \
  --workspace <workspace> --stage import
```

- `--template`：黄金模板（`flow_definition.yaml` 步骤的 `template:` 字段，相对 plugin `templates/`）。
- `--out`：渲染产出，通常 `<workspace>/stages/<stage>/scripts/<step>.tcl`。
- `--workspace` + `--stage`：成对给出即自动注入 7 个 workspace 路径变量（`report_dir`、`artifact_dir`、`netlist`、`lef`、`lib`、`sdc`、`lib_search_path`），无需再手写这些路径 `--var`。
- `--spec` / `--decisions`：可选；缺省即只用 workspace 路径变量与 `--var`。
- `--var`：可重复，最高优先级，用来覆盖任意变量或补充上述来源未覆盖的占位符。

## 输出

单个 JSON 对象：

```json
{
  "status": "ok",                       // ok | error
  "template": ".../read_design.tcl.tmpl",
  "out": ".../read_design.tcl",
  "filled_vars": ["netlist", "lef", "lib", "top_module"],
  "injected_blocks": ["extra_read_options"]
}
```

`status: error` 时附 `unfilled_vars`（护栏触发）或 `message`。退出码：`ok` → 0，其余 → 1。

## 关键规则

1. **零判断、确定性。** 同样的模板 + 同样的 decisions/spec/var → 字节级相同输出（除时间戳头）。判断全在上游决策步。
2. **绝不产出带裸占位符的 Tcl。** 未填即报错，让上游补 decisions/var，而不是把坏脚本交给工具。
3. **不调工具、不解析报告。** 执行是 [run-eda-script]、解析是 [parse-eda-report] 的事。
