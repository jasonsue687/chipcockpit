---
name: Place Boundary Pins
description: This skill should be used when the user asks to "place IO pins on the boundary", "snap top-level ports to cell pin Y", "摆 IO pin", "把 port 摆到边界", "把和某个 cell 直接连接的 port 摆到对应 Y 坐标", "place top ports near connected cells", "boundary pin assignment based on cell location", "rerun port placement after floorplan change", or hands over an Innovus floorplan DB and a target cell type and wants the top-level terms aligned with that cell's pins on the die edge. Even if the user only says "排一下 IO" or "把这些 input/output 摆到 left/right 边", treat it as a trigger when the request involves snapping top-level ports to specific Y coordinates derived from internal cell connectivity. Use whenever the request is "place ports based on where the connected logic ends up" rather than a uniform spread or `assignIoPins`. Produces editPin Tcl scripts, applies them in Innovus, and reports per-port deviation.
version: 0.1.0
---

# Place Boundary Pins — 边界 IO Pin 摆放工作流

把顶层 port 摆到 die 边沿，Y 坐标对齐到 *它真正连接的内部 cell 的引脚 Y*，而不是用 `assignIoPins` 那种均匀展开。适用于：

- 设计里有一类 *承载主要数据流的特定 cell*（latch 阵列、寄存器组、SRAM 接口、bus 中继 buffer 等），希望顶层 input port 和它的 D 引脚平齐、output port 和 Q 引脚平齐，缩短从 IO 到那一族 cell 的连线
- floorplan / placement 改过之后，cell 的物理位置变了，需要重新排 IO，保证 routing 友好
- 用 `editPin` 手摆几百到几千根 pin，要保证 track-aligned、无 overlap、有 deviation 报告

## What this skill produces

源 Innovus DB → 跑完后得到两份 Tcl + 两份 report：

| 文件 | 内容 |
|------|------|
| `lv_port_assign.tcl` | phase1 的全部 `editPin` 命令 |
| `lv_port_assign.rpt` | phase1 每个 port 的 yOrig / yFinal / dev / layer |
| `lv_port_remain_assign.tcl` | phase2 的全部 `editPin` 命令 |
| `lv_port_remain_assign.rpt` | phase2 每个 port 的 targetY / dev / layer / 触发用的 anchor 列表 |

之后只需 `saveDesign` 即可固化。

## When to use

- 用户给了一个 Innovus floorplan DB (`*.enc.dat`) + 想让 IO 顺着某个 cell 类 (如 `EXAMPLE_BUF_X4`) 的 pin Y 排
- 用户在做 custom placement / pipe array 设计，强调 "input 在左、output 在右，要和 cell 对齐"
- 用户跑过 `assignIoPins` 但不满意结果（pins 摆得太散，或不沿着 cell 对齐）
- 用户提出 "1um 容差 / 2um 容差" 这种几何约束

## Workflow

整个流程分两阶段。**两阶段共享同一套多层 track-bucket 分配算法**：把每条 dir=y track 看作一行 slot，每条 (track, layer) 组合就是一个 pin slot，按 layer 列表顺序填，相邻 track 兜底。

### Phase 1 — 直连 port 锚到 cell pin Y

对于和目标 cell *引脚直接同一条 net 的* 顶层 port：

1. `restoreDesign <db_path> <top_name>`
2. 收集所有 `cell.name == TARGET_CELL` 且 inst path 以 `TARGET_HIERS` 之一为前缀的 instance
3. 对每个 instance 的 instTerms，看它的 net 上是否挂着任何 top.terms；如果挂着，就建立一条 *port → (direction, Y_of_pin)* 映射（同名 port 取第一个出现，dedup）
4. `input` 方向去左边沿 (`xL`)，`output` 方向去右边沿 (`xR`)
5. 多层 track-bucket：尝试 `IO_LAYERS` 列表里的第一层在目标 trackIdx，若已占就第二层、第三层；都占就 trackIdx ±1 再试三层，依次扩大到 `MAX_PORT_DEV/track_step` 个 track（默认 ±1um）
6. 发出 `editPin -pin <port> -fixedPin 1 -snap TRACK -layer <Lk> -assign {<xEdge> <y>}`

### Phase 2 — 间接 port 通过逻辑 BFS 锚到附近的 anchor

phase1 跑完后，design 里还有一批顶层 port 没摆 —— 它们通过 inverter/buffer/mux/组合逻辑才到达目标 cell。这类 port 没有 "直接 Y"，要从已经摆好的 anchor port 推断：

1. 从 DB 重新读 `top.terms` 里 `pStatus == fixed` 的那些当 anchor，记下它们的 `(side, Y, layer, trackIdx)`，已占 slot 记入 `USED`
2. 对每个仍未 placed 的 top.term：
   - 从它的 net 出发 BFS：当前 net → 上面的 instTerms → 它们的 parent inst → 该 inst 其余 instTerms → 下一跳的 net
   - 跳过 fanout > `BFS_MAX_NET_FANOUT`（避免 clk/reset 主干爆炸）
   - 命中任何 anchor 时记录下来，最远 `BFS_MAX_HOPS` 跳（默认 3）
3. 取 *最近一跳 + 1 跳* 的 anchors，过滤同侧（input port 只看左边的 anchor），取它们 Y 的中位数作为 `targetY`
4. 在 `targetY` 周围 `±MAX_RELATED_DIST` track 邻域里搜空 slot，多层兜底，找不到再扩搜
5. 同样发 `editPin -fixedPin 1 -snap TRACK -layer L -assign {xEdge y}`
6. **No-skip 保证**：BFS 找不到 anchor 的 port（典型是 `clk`, `clk_out` 这种走 clock-gen 的大扇出网），phase2 不再跳过，而是 fallback 到 **net 直连负载的几何中位数**：遍历 `port.net.instTerms.pt` 全集（绕开 `BFS_MAX_NET_FANOUT`），取 Y 的中位数当 `targetY`，依然按 "数据走向" 摆。无 direction 的 port 用 net 几何 X 决定左/右边沿。彻底没负载的 port 兜底到 die 中心 Y。Report 里这类 port 的 `anchors` 字段会标记为 `netCentroid(N=...,fanout-uncapped)` 或 `die-center(no-net-loads)`

## Bundled scripts

`scripts/` 下放了三个文件，照搬即可，*只改顶部 param 块*：

- `phase1_place_anchor_ports.tcl` — phase 1，所有可调参数集中在前 30 行
- `phase2_place_remaining_ports.tcl` — phase 2，BFS 的可调参数也在顶部
- `run_phase12.tcl` — 顺序 source 两个 phase

调用模式（在 Innovus 里）：

```tcl
# 在脚本顶部按需改参数，然后：
innovus> source <skill-scripts>/phase1_place_anchor_ports.tcl
innovus> source <skill-scripts>/phase2_place_remaining_ports.tcl
innovus> saveDesign <new_db_path>
```

或者一把梭：

```tcl
innovus> source <skill-scripts>/run_phase12.tcl
```

## Parameters you almost always need to change

按重要程度排序：

| 参数 | 位置 | 默认 | 何时改 |
|------|------|------|--------|
| `DB_PATH` | phase1 顶部 | 写死的路径 | 总要改 |
| `TOP_NAME` | phase1 顶部 | `example_top` | 顶层 module 不同 |
| `TARGET_CELL` | phase1 顶部 | `EXAMPLE_BUF_X4` | 关心的 cell 类型 |
| `TARGET_HIERS` | phase1 顶部 | `u_example_block0 u_example_block1` | 要 cover 的层次前缀 |
| `IO_LAYER_NAMES` | 两个 phase 都有 | `M4 M6 M8` | 想用别的金属层 |
| `MAX_PORT_DEV` | phase1 | `1.0` (um) | 直连 port 的允许偏差 |
| `MAX_RELATED_DIST` | phase2 | `2.0` (um) | 间接 port 离 anchor 的最大距离 |
| `BFS_MAX_HOPS` | phase2 | `3` | BFS 跳数 |
| `BFS_MAX_NET_FANOUT` | phase2 | `50` | 屏蔽 clock/reset 网用 |

## Choosing the IO layers

容量 = `层数 × dir=y_track 数`。从 `dbGet top.fPlan.tracks` 看：
- 用更细 pitch 的层（如 M3 在 7nm 工艺 ~0.044um）单层容量更大但 IR drop / resistance 大
- 用更粗 pitch 的层（如 M11 ~0.126um）每层容量更小，但易于走线
- 多层是 *和差* 关系：三层 0.076um pitch 的层 = 单层 0.025um pitch 的有效容量

设计经验：先用 `M4 M6 M8`（中间偏低的 vertical metal），多数 7-track 工艺都能工作。`port 总数 > 单层 track 数 × 层数` 时，必然有 port 偏差超预算，到那时再加一层或换层。

## Common gotchas (踩过的坑)

### dbGet 的 filter 语法
要按 attribute 过滤再取 parent，用 `-pN`：
```tcl
# 错：把 -p1 / -p2 当 flag，把 attribute 名当值
dbGet top.insts -p1 cell.name LV_xxx     ;# 会报 'cell.name' is not recognized
# 对：attribute 路径全写出来，-pN 表示上溯 N 层
dbGet -p2 top.insts.cell.name LV_xxx -e  ;# 返回 inst 指针
```

### restoreDesign 的存在性判断
`dbHeadCell` 在没设计时返回 `0x0` 而不是抛异常，单靠 `catch` 不会触发恢复：
```tcl
# 错：永远进不去 if
if {[catch {dbHeadCell} _]} { restoreDesign ... }
# 对：检查返回值是否有效
catch {set hc [dbHeadCell]}
if {$hc eq "" || $hc eq "0x0"} { restoreDesign ... }
```

### editPin 在 Innovus 23.14 的正确写法
```tcl
# 错：选项名错
editPin -pinName {rx_a[0]} ...      ;# IMPTCM-48: not a legal option
# 错：用 -side 配 -offsetStart 还要 -edge
editPin -pin <p> -side Left -offsetStart 1.3 -offsetEnd 1.3 ...  ;# IMPPTN-3071
# 对：用 -assign 给绝对坐标
editPin -pin <p> -fixedPin 1 -snap TRACK -layer M4 -assign {0.0 1.3}
```

### 顶层 bus port 名的 brace 问题
`dbGet $termPtr.name` 对 bus 端 (如 `rx_a[16]`) 返回的已经是 `{rx_a[16]}`（带 brace）。再加一层 `\{$port\}` 会变成 `{{rx_a[16]}}`，Innovus 不认。直接 emit `$port`：
```tcl
# 错：双重 brace
puts $fh "editPin -pin \{$port\} ..."
# 对：dbGet 已经给你 brace
puts $fh "editPin -pin $port ..."
```

### Track 方向
- `dir=y` 的 track group ⇒ track 位置是 Y 坐标（横线），用于 left/right 边沿 pin 的 Y snap
- `dir=x` 的 track group ⇒ track 位置是 X 坐标（竖线），用于 top/bottom 边沿 pin 的 X snap
- 一个金属层同时定义两套 track 不奇怪。**左右边沿摆 pin 要看 dir=y**

### Phase 2 BFS 的 fanout cap
不加 fanout 上限的话，BFS 会从 `clk`/`reset`/`scan_en` 这类大扇出网爆炸到几千个 cell。`BFS_MAX_NET_FANOUT 50` 是经验值，能 cover 大部分数据流又不被 clock 拖死。如果数据网本身就 fanout > 50，把它调大。

被 fanout cap 屏蔽掉的 port 不会被跳过：会走 `directNetCentroid` 兜底（直接遍历 `port.net.instTerms.pt`，无 cap，取 Y 中位数）。这样 `clk`/`clk_out` 也会被摆到 clock 树几何中心。

### Phase 2 同侧过滤
input port 的 BFS 大概率会经过逻辑链碰到 output anchors。如果不过滤 side，input port 会被吸去右边沿。所以 phase2 要：先取同 side 的 anchors；同侧空了再 fallback 到所有 hop 的同侧。

## How to integrate with the chip flow

放在 floorplan 之后、placement 之前（这样 placement 知道 pin 在哪儿、能优化布线方向）。或者：

- floorplan 完成 → save `*.floorplan.enc.dat`
- 跑 phase1 + phase2 → `saveDesign *.floorplan_pins.enc.dat`
- 后续步骤都从 `*.floorplan_pins.enc.dat` 起步

如果用户跑 `run-chip-flow` skill 的 state machine，建议在 `floorplan` 阶段完成后作为一个 hook 自动调用本 skill 的两个 phase 脚本。

## Output report semantics

每行：
```
side  port                      yFinal   yOrig    dev     layer  instPath/pin (or anchors for phase2)
L     {rx_a[0]}                 1.3620   1.3000  0.062   M6     u_example_block0/.../D0
R     {tx_w1faa_s[31]}         27.1040  26.9400  0.164   M4     u_example_block1/.../Q15
```

- `dev = abs(yFinal - yOrig)` 或 `abs(yFinal - targetY)`
- 顶部 5 行注释概括: 每边总数 / 超阈值数 / 平均偏差 / 最大偏差 / 各层分配数
- phase2 多一栏 `anchors=...,...,...@hop` 让用户能直接看出 "我这个 port 是被哪些 anchor 拉过去的"

排查时按 `dev` 排序看最差的几个 port，再回过头看 anchors 列表，往往能定位是 BFS 落到了什么意外的 net 上。

## Quick adaptation checklist

把这个 skill 用到一个新设计上，照顺序改：

1. 改 `DB_PATH`, `TOP_NAME`
2. `dbGet top.insts.cell.name *` 抽样看，找出实际的 target cell 名 → 改 `TARGET_CELL`
3. `dbGet top.hInsts.name` 或目测 inst 命名前缀 → 改 `TARGET_HIERS`
4. 跑一次 `dbGet top.fPlan.tracks` 确认 `M4 M6 M8` 有 dir=y track 且 pitch 一致；若不一致改 `IO_LAYER_NAMES`
5. 估算 *单边 port 数* vs *三层 track 总数*，若密度 > 90% 就考虑加一层或换更细 pitch 层
6. 跑 phase1 看 report 里 `>1.0um` 的数量；可接受就跑 phase2

Phase 2 跑完看 `>2.0um` 的剩余数量，多数情况就是被 phase1 已占 slot 挤出去的 —— 这是物理密度限制，不是算法 bug。

**No-skip 不变量**：跑完两个 phase 后，`dbGet top.terms.pStatus` 应该全部是 `fixed`（没有 `unplaced`）。如果发现仍有 `unplaced` 的 port，说明 phase2 的兜底分支没走到 —— 检查 emit 那段是否漏了某条 `editPin`，或者 `editPin` 本身报错（去 log 里 grep `IMPTCM` / `IMPPTN` 错误号）。
