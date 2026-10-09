---
name: Analyze Netlist
description: This skill should be used when the user asks to "analyze netlist", "parse netlist", "read this verilog netlist", "show me the netlist hierarchy", "trace signal flow", "find clock fanout", "report port connectivity", "compute logic depth", "分析网表", "解析网表", "看一下这个网表的层次/端口/信号流", or hands over a `.v`/`.vg`/`.gv` file or an Innovus database and wants a structural report. Use it whenever the user wants to understand the structure of a netlist (gate-level Verilog, behavioral RTL, or loaded Innovus DB) without actually running placement/CTS/route. Produces a Markdown report covering: top-level port table, module hierarchy tree, combinational logic depth, port fanin/fanout, and clock/reset tree fanout. Even if the user does not explicitly say "report", treat any request to "look at" or "understand" a netlist as a trigger for this skill.
version: 0.1.0
---

# Analyze Netlist — 网表结构分析器

帮助用户在不跑 PD 工具的情况下，快速理解一个网表的结构。输入是一个 Verilog 文件（gate-level 或 RTL）或一个已经 load 进 Innovus 的 design，输出是一份 Markdown 结构报告。

## When to use

- 用户给出一份 `.v`/`.vg`/`.gv` 文件，希望知道它长什么样
- 用户在做 floorplan / power-plan 前，想确认 top 端口和模块结构
- 用户在 debug 信号流（"这个 clk 接到了哪些 flop?", "这个 input port 的 fanout 是什么?"）
- 用户希望对比综合前后的 hierarchy 是否一致

## What it produces

固定七段式 Markdown 报告，路径默认为 `<netlist_dir>/<netlist_basename>_analysis.md`（用户可指定其他路径）：

```
# Netlist Analysis Report
## 1. Summary
## 2. Top-level Port Table
## 3. Hierarchy Tree
## 4. Logic Depth (Combinational Levels)
## 5. Port Fanin / Fanout
## 6. Clock & Reset Tree
## 7. Notes & Limitations
```

四类分析对应四种数据维度：

| 维度 | 含义 | 适用输入 |
|------|------|----------|
| Hierarchy | top → submodule → leaf cell 的实例化树 | 全部 |
| Logic depth | 从 PI/FF-Q 到 PO/FF-D 的组合逻辑级数 | 仅 gate-level / Innovus DB |
| Port fanin/fanout | 每个 top port 直接相连的 cell pin | 全部（RTL 只列直接连线） |
| Clock & reset tree | clk/rst 类信号驱动的 sequential cell 列表 | 全部 |

## Workflow

### Step 1 — Ask for inputs (only if missing)

如果用户的消息里没有 netlist 路径，使用 `AskUserQuestion` 询问。同时确认 top module 名（可选 —— 没给就让脚本自己推断）。

不要静默猜路径。如果用户给了一个 symlink 但目标不存在，先把这个情况报告出来，再请用户提供真实路径。

### Step 2 — Detect format

按以下优先级判定：

1. 文件名以 `.enc.dat` / `.enc` 结尾，或是一个目录里包含 `.enc.dat` → **Innovus DB**，走 Tcl 路径
2. 用户在消息里说 "已经 load 进 Innovus" 或 "用 dbGet" → **Innovus DB**
3. 文件名以 `.v` / `.vg` / `.gv` / `.sv` 结尾 → **Verilog**，再交给 Python 脚本细分 gate-level / RTL（脚本内部启发：是否含 `always` / `assign` 行为级语句；leaf cell 命名是否匹配工艺库前缀）

### Step 3 — Run the analyzer

**Verilog 路径（默认）：**

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/analyze-netlist/scripts/analyze_netlist.py" \
    --netlist <path> \
    [--top <module_name>] \
    [--output <report_path>] \
    [--max-depth 10000]
```

脚本会：
- 用 stateful regex parser 提取 `module ... endmodule`、`input/output/inout`、`wire/reg`、实例化 `<cell> <inst> (.pin(net), ...)`。注释、`ifdef`、`timescale` 等会被剥离。
- 推断 top（被实例化最少 / 未被实例化的 module）。
- 构建 hierarchy 树。
- 对 gate-level：构建 net→driver / net→loads 图，标记 sequential cell（启发式：cell 名包含 `DFF|FF|LATCH|SDFF|TLAT`，或具有 `CK|CLK|CP` 输入），切断 sequential 边界后用 BFS 算 logic level。
- 启发式识别 clock / reset：port 名匹配 `^(clk|clock|.*_clk|.*_clock)$` / `^(rst|reset|.*_rst|.*_reset|.*_rstn|.*_resetn)$`；以及任何驱动了 sequential cell `CK|CLK|CP|R|RN|RB|SET|SETN|CDN` pin 的 net。
- 最终生成 Markdown 报告，并把结构化中间数据写为同名 `.json`（便于后续脚本二次使用）。

**Innovus DB 路径：**

```bash
innovus -no_gui -nolog -nowin -files \
    "${CLAUDE_PLUGIN_ROOT}/skills/analyze-netlist/scripts/analyze_netlist.tcl" \
    -overwrite -log /tmp/analyze_netlist.log
```

要求当前目录或 Tcl 内提供 `read_db <path>`。Tcl 用 `dbGet` 走出相同的四类数据，再调用 Python 脚本统一渲染报告。

### Step 4 — Hand back

报告路径用 `file_path:1` 形式贴给用户，并把 Section 1（Summary）的内容粘在回复里作为预览。如果脚本在某个维度上 fallback 了（例如 RTL 跳过 logic depth），在回复里点明，并提示用户怎么补齐（"想看 logic depth 的话，请提供综合后的 gate-level 网表，或先在 Innovus 里 read_design 后再跑一次"）。

## Heuristics & assumptions

1. **Top 推断**：先按 "未被任何 module 实例化" 选；若多于一个（典型情况是带顶层 testbench），优先取实例数最多的；若仍多于一个，列出候选请用户选。
2. **Sequential cell 识别**：先匹配 cell 名正则 `(DFF|FF|LATCH|SDFF|TLAT|FLOP)`；匹配不上时退回 "是否含 CK 输入" 这条启发，并在 Notes 段告知用户可用 `--seq-pattern` 自定义。
3. **Logic depth = 0 的边界**：primary input、sequential cell 的 Q 输出、`assign 1'b0/1'b1` 这种常量驱动。
4. **行为级 RTL**：Python 脚本只做 lexical 级抽取（module/port/instance），不展开 `always` 块或 `generate`；遇到这类输入时，Section 4 写 "Skipped (requires gate-level netlist)"。

## Bundled scripts

- `scripts/analyze_netlist.py` — 主分析器（详见脚本内 `--help`）
- `scripts/analyze_netlist.tcl` — Innovus dbGet 抽取脚本，输出 intermediate JSON 给 Python 脚本渲染
- `scripts/render_report.py` — 把中间 JSON 渲染成最终 Markdown（被前两个脚本内部调用）

## Notes & limitations

- 当前 parser 是基于行级 regex 的轻量 parser，不替代 pyverilog；对极端写法（多行括号深度嵌套、复杂 `defparam`）可能漏匹配。脚本会在末尾 `Notes` 段记录被跳过的行号。
- Logic depth 是组合深度（cell 级），不是 ns 级时序；如需 ns 级请跑 timing 工具。
- Clock 识别是启发式。CDC 复杂的设计需要用户用 `--clock-pattern` 显式指定。
