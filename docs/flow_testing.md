# 芯片后端流程测试指南

本文档介绍如何对 `chip-backend-ai` 编排器进行端到端流程测试：既包括"正常通路"（全部阶段 pass），也包括人为注入异常来验证重试、回滚、Spec 修订、预算耗尽等异常处理路径。

> **适用范围：** EDA 工具（Innovus/Genus）集成尚未落地的当前阶段。所有 Sub-agent 默认通过 `stage_simulator.py` 生成合成的 `_meta.yaml` / `eval_result.yaml`，用于跑通状态机与编排逻辑。EDA 集成完成后，本文档的"失败注入"手段仍可作为回归测试工具。

---

## 零、贯穿全文的测试用例：AES 加密 Block

为了让测试贴近真实场景，本文所有 Scenario 都围绕同一个虚构但符合真实后端工程特征的 block 展开。你在会话中可以直接把这段描述贴给编排器作为"模糊目标"。

### 0.1 设计规格（Design Intent）

| 项目 | 取值 |
|------|------|
| Block 名称 | `aes_core` |
| 功能 | 128-bit AES-CBC 加密引擎，带输入/输出 FIFO |
| 工艺节点 | TSMC N5（Tight pitch，7 层金属可用于 signal） |
| 门数（post-synth） | ~210K gates |
| 存储 Macro | 6 × SRAM 1RW 2048×64（均为 foundry 提供的物理宏） |
| 时钟 | `clk_core` 2 GHz（period 500 ps），`clk_axi` 800 MHz |
| Die size | 800 µm × 800 µm（die area ≈ 0.64 mm²） |
| 电源域 | 单电压域，0.75 V，无 MTCMOS |
| IO | AXI4-Stream slave/master（各 64-bit data + sideband） |

### 0.2 交付指标（Acceptance Criteria）

| 类别 | Metric | 目标 |
|------|--------|------|
| 时序 | `wns_ns` | ≥ -0.05 ns（轻微违例可接受） |
| 时序 | `tns_ns` | ≥ -0.5 ns |
| 时序 | `hold_wns_ns` | ≥ 0 ns（hold 零违例） |
| Floorplan | `utilization` | 0.62 ~ 0.72 |
| Floorplan | `congestion_hotspot` | < 0.85 |
| Floorplan | `macro_channel_width_um` | ≥ 3.0 µm |
| CTS | `clock_skew_ps` | < 60 ps |
| CTS | `insertion_delay_ps` | < 400 ps |
| Route | `drc_violations` | 0（signoff 必须 clean） |
| Route | `congestion_overflow` | < 0.5% |

### 0.3 Fuzzy 目标（直接提给编排器）

> "跑通 `aes_core` 这个 block 的 P&R 全流程。我优先关心 routing congestion 和 DRC，最终必须 DRC clean；时序上 setup 可以有小量违例（WNS 不要差于 -50ps 就行），hold 必须零违例。Macro 一共 6 个 SRAM，希望留出至少 3µm 的 channel 方便 pin access。工艺 TSMC N5，时钟 2GHz。"

这就是 Spec Agent 要"具象化"的原始输入，也是后续所有 Scenario 的共同起点。

---

## 一、测试基础

### 1.1 前置条件

- Python 3，已安装 `PyYAML`（`pip3 install pyyaml`）
- 仓库根目录：`/path/to/chipcockpit`
- 插件根目录：`plugins/chip-backend-ai`

### 1.2 启动方式

在 Claude Code 会话中说"跑芯片流程 / start backend flow / run chip flow"等即可触发 `run-chip-flow` skill。编排器会自动在当前目录创建隐藏 workspace `.chipflow/`（若已存在则加后缀 `_2`、`_3`…），**无需手动 init**。

### 1.3 Workspace 关键观察点

| 路径 | 用途 |
|------|------|
| `state/machine.yaml` | 全局状态机快照 |
| `state/decisions.jsonl` | 编排器 append-only 决策日志 |
| `spec/global_spec.yaml` | 当前生效 Spec（旧版本进入 `history/`） |
| `stages/<stage>/run_NNN/eval_result.yaml` | 每次 run 的评估结果 |
| `stages/<stage>/run_NNN/_meta.yaml` | 每次 run 的元信息（spec_version、parent_run、checkpoint） |
| `checkpoints/` | 仅 pass 的 run 才会生成 checkpoint 占位文件 |

### 1.4 一键检查命令

```bash
WS=./.chipflow                                             # 改成你的 workspace 路径

# 当前状态 + 各 stage 状态
python3 plugins/chip-backend-ai/core/workflow/state_manager.py read --workspace $WS \
  | python3 -c "import sys,json; s=json.load(sys.stdin); print('state:',s['current_state']); print('stages:',{k:v['status'] for k,v in s['stages'].items()}); print('budget:',s.get('global_retry_budget'))"

# 最近 10 条决策
python3 plugins/chip-backend-ai/core/workflow/decision_logger.py read --workspace $WS --last-n 10

# 查看 spec 版本历史
python3 plugins/chip-backend-ai/core/workflow/spec_manager.py history --workspace $WS
```

---

## 二、场景 A：aes_core 正常完成 P&R

**目标：** 验证 `INIT → SPEC_DRAFTING → SPEC_REVIEW → SCHEDULING → STAGE_RUNNING (×3) → COMPLETED` happy path，拿到全 pass 结果。

### 步骤

1. **启动流程** — 会话中说：
   > "帮我跑一遍 aes_core 的后端 P&R 流程"

2. **提供模糊目标** — 粘贴 §0.3 的那段 fuzzy 目标。

3. **审批 Spec** — Spec Agent 会生成：
   - `global_spec.yaml`：wns_ns=-0.05，hold_wns_ns=0，utilization 0.62~0.72，technology=tsmc_n5
   - `stages/floorplan.yaml`：congestion_hotspot<0.85，macro_channel_width_um≥3.0
   - `stages/cts.yaml`：clock_skew<60ps，insertion_delay<400ps
   - `stages/route.yaml`：drc_violations=0，congestion_overflow<0.5%

   核对 §0.2 的各阈值是否都被正确翻译到 Spec 里，符合就回复 "approve"。

4. **观察三阶段自动执行** — 每阶段 Sub-agent 会调用 `stage_simulator.py` 在 target 范围内选 actual 值，落盘后编排器 dispatch 下一阶段。

5. **验证终态**
   - 状态：`COMPLETED`
   - `stages/{floorplan,cts,route}/run_001/eval_result.yaml` 全部 `overall: pass`
   - `decisions.jsonl` 约 7 条（3 次 dispatch + 3 次 agent_done + 1 次 all_passed）
   - `checkpoints/` 下有 `post_floorplan_run_001.def`、`post_cts_run_001.def`、`post_route_run_001.def` 三个占位文件

---

## 三、场景 B：CTS run_001 超 skew，retry 一次后通过

**现实动因：** AES 的 `clk_core` 跑到 2GHz，第一次 CTS 可能因 buffer library 选型不当导致 skew 微超。正常做法是调整 target_skew 后重跑，这是后端工程中最常见的异常。

### 触发方式

在会话（Spec 审批后）告诉编排器：
> "让 cts 第一次失败（clock_skew 超阈），recommendation=retry，第二次通过"

编排器会在 dispatch cts run_001 的 agent prompt 中追加：
```
Simulate fail: true
Fail metrics: clock_skew
Recommendation: retry
```

### 期望结果

- `stages/cts/run_001/eval_result.yaml`: `overall: fail`, `clock_skew.status: fail`, `recommendation: retry`
- `stages/cts/run_001/_meta.yaml`: `status: failed`, `checkpoint: null`（失败不产出 checkpoint）
- `stages/cts/run_002/eval_result.yaml`: `overall: pass`
- `machine.yaml` 中 `stages.cts.retry_count: 1`, `status: passed`
- `global_retry_budget.used` 从 0 变为 1
- 最终状态：`COMPLETED`

---

## 四、场景 C：Floorplan 约束过紧，耗尽重试触发 Spec 修订

**现实动因：** 0.62 下限利用率 + N5 pin density 高，如果 Spec Agent 初版把 `congestion_hotspot` 卡到 0.70（过于激进），floorplan 可能连续失败——这时正确做法不是无限 retry，而是让 Spec Agent 放宽到 0.85。

### 触发方式

> "让 floorplan 连续 3 次失败（congestion_hotspot 超阈），每次 recommendation=retry；之后由编排器触发 revise_spec，放宽 congestion 阈值到 0.88"

### 期望结果

- `stages/floorplan/run_001` ~ `run_003` 全部 fail，`congestion_hotspot` 三次都是 fail 状态
- 第 4 次 scheduling 时，编排器检测到 `retry_count >= max_stage_retries (3)`，触发 `revise_spec` 事件，状态回到 `SPEC_DRAFTING`
- Spec Agent 以 `scenario: revision` 运行，旧 Spec 归档为 `spec/history/global_spec_v1.yaml`
- 新 Spec `spec_version: v2`，`congestion_hotspot.max` 放宽到 0.88
- 人类审批通过后，继续 `floorplan/run_004`，在新 Spec 下 pass
- 最终状态：`COMPLETED`

### 可观察

```bash
# 确认归档
python3 plugins/chip-backend-ai/core/workflow/spec_manager.py history --workspace $WS
# 期望输出：["global_spec_v1.yaml"]

# 确认 run_004 使用的是 v2
cat $WS/stages/floorplan/run_004/_meta.yaml | grep spec_version
# 期望：spec_version: v2
```

---

## 五、场景 D：CTS 判定为上游问题，触发跨阶段 rollback

**现实动因：** AES 的 6 个 SRAM 若摆放过密，clock tree 很难在保证 skew 的同时留出 pin access，这时 CTS Agent 会把锅甩回 floorplan（`recommendation: rollback`），请求重新做 macro placement。这是真实工程里经典的跨阶段归因场景。

### 触发方式

> "让 cts 第一次失败，recommendation=rollback，理由是 SRAM macro 摆放过密导致 skew 不可收敛，需要 floorplan 重做"

### 期望结果

- `stages/cts/run_001/eval_result.yaml`: `overall: fail`, `recommendation: rollback`
- 编排器不 retry cts，而是 dispatch `floorplan/run_002`，其 `_meta.yaml.parent_run` 指向 `cts/run_001`
- `global_retry_budget.used` 递增
- `floorplan/run_002` pass → 重新 dispatch `cts/run_002` pass → `route/run_001` pass → `COMPLETED`

---

## 六、场景 E：预算耗尽 → ABORTED

**现实动因：** 当某个阶段反复 retry + rollback 都无法收敛（例如设计本身就不可综合），需要有硬性刹车防止无限循环。

### 触发方式

1. 启动并审批 Spec 后，**编辑 `state/machine.yaml`** 手动调小预算：
   ```yaml
   global_retry_budget:
     max: 2
     used: 0
   ```
2. 告诉编排器：
   > "让 floorplan 连续 5 次失败，recommendation=retry"

### 期望结果

- `used` 递增到 2 后，下次 scheduling 触发 `budget_exhausted` 事件
- 终态：`ABORTED`
- `decisions.jsonl` 最后一条：`action: abort`
- 编排器向你汇报最后一次失败的 eval 摘要和预算消耗

---

## 七、场景 F：Route DRC 命中不可恢复错误（escalate）

**现实动因：** 如果 route 阶段发现 DRC 违例位于 foundry library cell 内部（例如 LVS 规则与 cell abstract 不一致），这是设计层面无法通过调参解决的，必须上报人类。

### 触发方式

> "让 route 第一次失败，recommendation=escalate，escalation_reason='DRC violation inside foundry SRAM macro abstract, cannot be resolved by router'"

### 期望结果

- `route/run_001/eval_result.yaml`: `overall: fail`, `recommendation: escalate`, `escalation_reason` 有明确文本
- 编排器**不 retry**，把 escalation 信息汇报给你，询问下一步（通常选择 ABORTED 或人工介入）
- `decisions.jsonl` 记录 escalation 事件

---

## 八、场景 G：Spec 审批拒绝与调整

**现实动因：** Spec Agent 初版给的 `utilization_max: 0.75`，但项目经理担心 congestion，希望收紧到 0.70；WNS 放宽到 -0.2 让综合压力更小。

### 步骤

1. 启动流程，提供 §0.3 模糊目标
2. Spec 展示后不 approve，回复：
   > "不行，utilization 最大改成 0.70，wns 放宽到 -0.2ns，其他保持不变"
3. 编排器触发 `human_rejected` 事件，重新 spawn Spec Agent（`scenario: adjustment`）
4. Spec Agent 产出新草案（仍是 v1，因为 v1 没有真正生效过），再次展示
5. 再次 approve 后进入正常 SCHEDULING

### 期望结果

- 最终 `spec_version: v1`（拒绝只在草案阶段来回，不递增版本号）
- `decisions.jsonl` 中能看到 `human_rejected` 和 `human_approved` 各一条
- `spec/history/` 为空（只有生效过的 Spec 被修订后才会归档）

---

## 九、场景 H：中断后 Resume

**现实动因：** P&R 全流程可能跨天。编排器必须能读 `state/machine.yaml` 从任意状态续跑，而不是每次从 INIT 开始。

### 操作

1. 跑到 cts 阶段时主动结束会话，或让编排器停在 SCHEDULING
2. 新开会话，再次触发 `run-chip-flow`
3. 告诉编排器：
   > "继续跑 ./.chipflow 里的 aes_core 流程"

### 期望结果

- 编排器读 `machine.yaml`，识别 `current_state` 和各 stage 的 `status`
- 不重新 init，不重新生成 Spec
- 直接进入 SCHEDULING 循环，dispatch 下一个 pending stage

---

## 十、失败注入机制速查表

`stage_simulator.py` 接受的失败参数（编排器通过 agent prompt 透传到 Sub-agent）：

| Prompt 指令 | 对应 CLI 参数 | 作用 |
|------------|---------------|------|
| `Simulate fail: true` | `--force-fail` | 所有 metric 都 fail |
| `Fail metrics: a, b` | `--fail-metric a --fail-metric b` | 仅指定 metric fail，其他 pass（产生 `overall: partial` 或 `fail`） |
| `Recommendation: retry` | `--recommendation retry` | 编排器走 retry 分支 |
| `Recommendation: rollback` | `--recommendation rollback` | 编排器走跨阶段回滚 |
| `Recommendation: escalate` | `--recommendation escalate` | 编排器标记不可恢复 |
| `Escalation reason: <文本>` | `--escalation-reason <text>` | escalate 场景附带原因 |

**编排器 fail_plan 管理规则（见 `run-chip-flow` SKILL.md）：**
- 按 `(stage, run_number)` 为键维护失败计划
- 只在匹配的 run 注入 fail hints，其他 run 正常 pass
- 每次注入时，编排器必须明确告诉你 `[sim] <stage> run_NNN 将被人为标记失败, recommendation=<X>`，便于区分"真实失败"和"测试失败"

---

## 十一、重置与清理

每次新测试建议换一个干净 workspace：

```bash
# 列出所有测试 workspace
ls -la | grep chipflow

# 删除某一个（不可逆，确认后再删）
rm -rf ./.chipflow_2

# 或让编排器用新后缀自动创建 — 下次启动会自动得到 .chipflow_N
```

> **不要删除正在运行中的 workspace。** 保留失败 workspace 有助于事后 debug `decisions.jsonl` 和 `eval_result.yaml`。

---

## 十二、冒烟测试检查清单（推荐顺序）

一次完整回归大约 30-45 分钟。按以下顺序跑：

- [ ] 场景 A：aes_core 正常通过 → `COMPLETED`
- [ ] 场景 G：Spec 拒绝 → 调整后通过
- [ ] 场景 B：cts run_001 fail → run_002 pass → `COMPLETED`
- [ ] 场景 D：cts rollback → floorplan 重跑 → 全部 pass
- [ ] 场景 C：floorplan 耗尽重试 → revise_spec → 新 Spec v2 pass
- [ ] 场景 E：预算耗尽 → `ABORTED`
- [ ] 场景 F：escalate → 上报人类
- [ ] 场景 H：Resume 中断的 workspace

每个场景跑完，至少检查：
1. `machine.yaml` 终态是否符合预期
2. `decisions.jsonl` 决策序列是否符合预期
3. 失败 run 没有生成 checkpoint 占位文件（`stage_simulator.py` 的设计约定）
4. spec_version 变化是否与场景吻合（只有 C 应该让 v1 → v2）

---

## 十三、EDA 集成后的演进

当 Innovus/Genus 集成落地后：
- Sub-agent 的"Real Execution Steps"章节将取代模拟分支
- 本文的"失败注入"仍可作为回归手段（通过给 Sub-agent 传入 mock 报告路径，或让工具运行在特制的失败场景库上）
- 需要新增的测试场景：
  - **场景 I**：Innovus 进程段错误 / 超时 → Sub-agent 容错
  - **场景 J**：report 文件格式变化 → 解析容错
  - **场景 K**：checkpoint DEF 损坏 → 下游 stage 拒绝执行并上报

届时请在本文末尾追加对应章节，并把 §0 的 aes_core 用例扩展成真实可运行的 block（例如 OpenCores 的 AES 实现 + TSMC N5 PDK mock）。
