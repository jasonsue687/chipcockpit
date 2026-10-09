
### 芯片后端设计 AI Agent 核心实施方案 (Master Plan V3)

本方案旨在构建一个高度自治的芯片后端设计 AI 控制系统。系统摒弃静态的预设生命周期，转而采用"抽象目标具象化 -> 人类审批 -> 编排器按规矩统筹 -> 智能体干活并落盘"的工作流。

---

#### 一、 启动初始化：目标具象化与物理工作区

**1. 专属工作目录创建 (Workspace Initialization)**
* **需求定义：** 每次启动新任务时，系统必须首先在本地创建一个独立的、具备强隔离性的"项目工作区 (Workspace)"。
* **Claude Code 任务：** 本方案不限定具体目录结构。要求 Claude Code 自行设计并创建一套合理的目录树，该目录必须能够分类存储：全局/阶段 Spec 规范、状态机存档、各阶段 Sub-agent 的输出记录（Artifacts）、以及底层工具提取的 PPA 数据集。
* **标准工作区目录结构：**

```
workspace/
├── spec/
│   ├── global_spec.yaml              # 当前生效的全局 Spec
│   ├── stages/
│   │   ├── floorplan.yaml            # floorplan 阶段 Spec
│   │   ├── cts.yaml                  # CTS 阶段 Spec
│   │   └── route.yaml                # route 阶段 Spec
│   └── history/                      # Spec 变更历史（只增不删）
│       ├── global_spec_v1.yaml
│       └── global_spec_v2.yaml
│
├── state/
│   ├── machine.yaml                  # 全局状态机快照（编排器读写）
│   └── decisions.jsonl               # 编排器决策日志（append-only）
│
├── stages/
│   ├── floorplan/
│   │   ├── run_001/
│   │   │   ├── _meta.yaml            # 元数据
│   │   │   ├── eval_result.yaml      # 结构化评估结果
│   │   │   ├── artifacts/            # Tcl 脚本、生成的约束文件等
│   │   │   └── reports/              # EDA 工具原始 report
│   │   └── run_002/                  # 重试则递增 run_id
│   ├── cts/
│   │   └── run_001/
│   └── route/
│       └── run_001/
│
└── checkpoints/                      # DEF/DB 快照（回滚恢复点）
    ├── post_floorplan_run001.def
    └── post_cts_run001.def
```

**2. 目标具象化与人类审批 (Human-in-the-Loop Spec Generation)**
* **输入：** 系统启动时，仅接收人类给出的"模糊抽象目标"（例如："跑通这个 block 的 route，主要看有没有大的 congestion，时序稍微超一点没关系"）。
* **AI 具象化：** `Spec_Agent`（意图层）负责将该模糊语言翻译为结构化的数据契约。生成一份包含"总 PPA 目标约束"及"拆解到各个子阶段的物理红线约束"的完整 Spec。
* **审批与落盘：** 生成的完整 Spec 必须呈现给人类进行 Check。一旦人类审查通过，该 Spec 立即持久化落盘至工作区 `spec/` 目录。后续所有 Agent 的行为边界严格以磁盘上的这份文件为准。

#### 二、 意图层：Spec_Agent 设计

`Spec_Agent` 是一个特殊的 Sub-agent，而非编排器的子模块。它遵循与其他 Sub-agent 相同的生命周期（唤醒 → 读盘 → 执行 → 落盘 → 休眠），但其输出（Spec 文件）在落盘前**必须经过人类审批**。

**1. 为什么是独立 Sub-agent 而非编排器子模块**

编排器的核心职责是"读状态 → 选路由 → 调度 Agent"，属于**调度决策**能力。而 Spec 生成/修订是"理解人类意图 → 与当前 PPA 现实做 tradeoff → 输出约束契约"，属于**领域协商**能力。两种能力对 prompt/context 的需求完全不同，塞进同一个 Agent 会导致 context 互相污染、prompt 难以调优。

独立为 Sub-agent 后，编排器用统一的调度接口管理它，无需特殊逻辑。

**2. Spec_Agent 的唤醒场景**

| 场景 | 触发者 | 输入 |
|------|--------|------|
| 初始化 | 人类提供模糊目标 | 模糊目标文本 + 设计约束文件（SDC/UPF 等） |
| Spec 不可达 | 编排器判定 | 失败证据（eval_result 数据） + 当前 Spec |
| 人类主动调整 | 人类 | 人类的修改意图 + 当前 Spec |

**3. Spec 可变性与版本管理**

* Spec 是可变的。运行中如果发现约束过严或需要调整，编排器唤醒 `Spec_Agent` 提出修订建议，经人类审批后生效。
* 旧版本 Spec 移入 `spec/history/`，新版本覆写主文件，`spec_version` 递增。
* 每个 Sub-agent 的 `_meta.yaml` 和 `eval_result.yaml` 中记录其运行时依据的 `spec_version`，保证回溯时知道"当时的标准是什么"。
* Spec 变更后，编排器需判断哪些已完成阶段的结果被新 Spec 推翻（例如放松 timing 后之前的失败可能变为通过），这属于编排器的调度职责。

#### 三、 中枢大脑：高自治编排器 (Autonomous Orchestrator)

* **自主阅读与思考：** 编排器是系统的唯一决策中枢。它启动后，主动读取磁盘上的 Spec 文件，思考当前的约束条件和最终目的。
* **按需路由：** 编排器不依赖写死的线性流水线。它根据 Spec 要求、Sub-agent 的评估结果以及当前状态，自主决定当下最应该唤醒哪一个 Sub-agent 来解决问题。
* **状态记录：** 编排器负责维护全局状态机。每一次决策流转、分支探索或跨阶段回滚，编排器都必须将最新的状态机切片同步更新到 `state/machine.yaml`，并将决策记录追加到 `state/decisions.jsonl`。
* **跨阶段归因：** 当某个 Sub-agent 反复失败时，编排器负责判断是本阶段参数问题，还是需要回滚到更早阶段。这种跨阶段影响评估是编排器独有的职责，不由任何 Sub-agent 承担。

#### 四、 执行单元：Sub-agent 矩阵

**1. Sub-agent 角色定义**

系统只需定义出所需的能力矩阵，具体内部逻辑后续实现。目前的 Sub-agents 包含但不限于：
* `[Spec_Agent]` - 负责将模糊目标具象化为结构化 Spec，以及运行时的 Spec 修订（输出需人类审批）。
* `[Floorplan_Agent]` - 负责宏单元摆放与电源网络规划。
* `[CTS_Agent]` - 负责时钟树综合。
* `[Route_Agent]` - 负责绕线及拥塞解决。
* `[Timing_ECO_Agent]` - 负责时序与 DRC 违例的局部修复。

**2. 统一生命周期**

所有 Sub-agent（包括 Spec_Agent）遵循相同的生命周期：

```
唤醒 → 读取 Spec + 上游落盘数据 → 执行 → 自评估 → 落盘（_meta + eval_result + artifacts） → 休眠
```

**3. 阶段内评估机制**

评估由 Sub-agent 在完成执行后自行完成，不设独立的评估模块。理由：

* **领域知识复用：** Sub-agent 在执行过程中已经需要理解本阶段指标（congestion、WNS、DRC 等），评估只是"提取数字 → 比对阈值"，零额外成本。
* **指标客观性：** 芯片后端指标是硬数字，直接来自 EDA 工具 report，Sub-agent 无法主观美化。
* **架构简洁：** 不引入独立 Eval 模块，减少组件间通信。

**评估输出的两条框架约束：**

* **约束一：必须包含原始数值。** `eval_result.yaml` 中每项指标必须同时记录 `target` 和 `actual`，不能只输出 pass/fail。编排器据此可独立验证，也可在 Spec 变更后重新判定历史结果。
* **约束二：跨阶段影响不归 Sub-agent。** Sub-agent 只评估本阶段指标。"floorplan 的 macro 摆放是否导致 routing congestion"这类跨阶段归因由编排器负责。

#### 五、 落盘交接协议 (File-System Handoff Protocol)

**1. 核心原则**

* **禁止直接内存传参：** Sub-agent 之间、以及 Sub-agent 与编排器之间，禁止传递海量的上下文对象。
* **只增不删：** 工作区中的文件一旦写入就不删除或覆写（Spec 主文件除外，但旧版本会归档到 `history/`）。保证完整的审计链和回滚能力。

**2. 元数据协议（`_meta.yaml`）**

每个 `run_NNN/` 下必须有 `_meta.yaml`，是编排器识别和索引所有 run 的唯一入口：

```yaml
agent: floorplan_agent          # 谁产出的
stage: floorplan                # 属于哪个阶段
run_id: run_001                 # 本阶段第几次执行
timestamp: "2026-04-12T14:30:00Z"
spec_version: v2                # 基于哪个版本的 Spec 执行的
parent_run: null                # 如果是回滚后重跑，指向触发回滚的 run
status: completed               # running | completed | failed
checkpoint: "checkpoints/post_floorplan_run001.def"  # 关联的恢复点
```

**3. 评估结果协议（`eval_result.yaml`）**

```yaml
stage: floorplan
run_id: run_001
spec_version: v2
overall: pass                   # pass | fail | partial

metrics:
  - name: utilization
    target: { min: 0.65, max: 0.75 }
    actual: 0.71
    status: pass

  - name: congestion_hotspot
    target: { max: 0.85 }
    actual: 0.72
    status: pass

  - name: macro_channel_width_um
    target: { min: 2.0 }
    actual: 2.3
    status: pass

recommendation: proceed         # proceed | retry | rollback | escalate
retry_context: null             # recommendation=retry 时，说明建议调整什么参数
escalation_reason: null         # recommendation=escalate 时，说明为什么无法自行解决
```

**协议规则：**
* `metrics` 中每一项必须同时包含 `target` 和 `actual`，编排器可独立验证 `status`
* `recommendation` 是 Sub-agent 对编排器的建议，编排器可采纳也可覆盖
* `overall: partial` 表示部分指标通过、部分失败，编排器需读 metrics 明细来决策

**4. 编排器决策日志（`decisions.jsonl`）**

Append-only，每行一条 JSON，记录编排器每次决策：

```json
{"ts":"2026-04-12T14:35:00Z","from":"SCHEDULING","to":"STAGE_RUNNING","action":"dispatch","target":"floorplan_agent","run_id":"run_001","reason":"Initial floorplan execution per spec v1"}
{"ts":"2026-04-12T15:10:00Z","from":"SCHEDULING","to":"STAGE_RUNNING","action":"retry","target":"floorplan_agent","run_id":"run_002","reason":"run_001 congestion 0.91 > threshold 0.85"}
{"ts":"2026-04-12T15:45:00Z","from":"SCHEDULING","to":"SPEC_DRAFTING","action":"revise_spec","reason":"floorplan run_002 still failing, utilization target may be too aggressive"}
```

**5. 文件生命周期规则**

| 场景 | 处理方式 |
|------|---------|
| Sub-agent 重试（同阶段新 run） | 旧 run 目录保留不动，创建新 `run_NNN/` |
| 编排器回滚到更早阶段 | 被回滚阶段的 run 目录保留（审计用），新 run 的 `parent_run` 指向触发回滚的 run |
| Spec 变更 | 旧 Spec 移入 `history/`，新 Spec 覆写主文件，`spec_version` 递增 |
| 任务最终完成或中止 | 整个 workspace 保留，不自动清理 |

#### 六、 全局状态机 (Global State Machine)

**1. 状态定义**

| 状态 | 含义 |
|------|------|
| `INIT` | 工作区已创建，等待人类输入模糊目标 |
| `SPEC_DRAFTING` | Spec_Agent 正在生成或修订 Spec |
| `SPEC_REVIEW` | Spec 等待人类审批 |
| `SCHEDULING` | 编排器读盘思考，决定下一步动作（中枢状态） |
| `STAGE_RUNNING` | 某个 Sub-agent 正在执行（含自评估） |
| `COMPLETED` | 全局终止条件满足，任务成功结束 |
| `ABORTED` | 不可恢复的失败或总重试预算耗尽 |

**2. 状态转移图**

```
                    ┌─── 人类拒绝，要求修改 ───┐
                    │                          │
                    ▼                          │
INIT ──→ SPEC_DRAFTING ──→ SPEC_REVIEW ──→ SCHEDULING
              ▲                                 │  ▲
              │                                 │  │
              │    ┌────────────────────────────┘  │
              │    │                                │
              │    ▼                                │
              │  STAGE_RUNNING ─────────────────────┘
              │    (Sub-agent 完成,
              │     eval_result 落盘,
              │     控制权回到 SCHEDULING)
              │
              └── SPEC_REVISION ◄── SCHEDULING
                   (Spec不可达时,
                    编排器唤醒Spec_Agent,
                    修订后进入SPEC_REVIEW)

         SCHEDULING ──→ COMPLETED  (终止条件满足)
         SCHEDULING ──→ ABORTED    (预算耗尽/不可恢复)
```

**3. 状态转移事件表**

| 当前状态 | 事件 | 目标状态 | 触发条件 |
|---------|------|---------|---------|
| `INIT` | `human_input` | `SPEC_DRAFTING` | 人类提供模糊目标 |
| `SPEC_DRAFTING` | `spec_ready` | `SPEC_REVIEW` | Spec_Agent 完成 Spec 生成/修订 |
| `SPEC_REVIEW` | `human_approved` | `SCHEDULING` | 人类审批通过 |
| `SPEC_REVIEW` | `human_rejected` | `SPEC_DRAFTING` | 人类要求修改 |
| `SCHEDULING` | `dispatch` | `STAGE_RUNNING` | 编排器选定 Sub-agent 并唤醒 |
| `SCHEDULING` | `revise_spec` | `SPEC_DRAFTING` | 编排器判定当前 Spec 不可达 |
| `SCHEDULING` | `all_passed` | `COMPLETED` | 全局终止条件满足 |
| `SCHEDULING` | `budget_exhausted` | `ABORTED` | 总重试次数超限或不可恢复错误 |
| `STAGE_RUNNING` | `agent_done` | `SCHEDULING` | Sub-agent 落盘完成并休眠 |

**4. `machine.yaml` 快照结构**

```yaml
current_state: SCHEDULING
spec_version: v2
global_retry_budget: { max: 15, used: 4 }

stages:
  floorplan:
    status: passed              # pending | running | passed | failed
    current_run: run_002
    retry_count: 1
    last_eval: stages/floorplan/run_002/eval_result.yaml
  cts:
    status: running
    current_run: run_001
    retry_count: 0
    last_eval: null
  route:
    status: pending
    current_run: null
    retry_count: 0
    last_eval: null

history:
  - { ts: "...", transition: "SCHEDULING → STAGE_RUNNING", detail: "dispatch floorplan run_001" }
  - { ts: "...", transition: "STAGE_RUNNING → SCHEDULING", detail: "floorplan run_001 failed" }
  - { ts: "...", transition: "SCHEDULING → STAGE_RUNNING", detail: "retry floorplan run_002" }
  - { ts: "...", transition: "STAGE_RUNNING → SCHEDULING", detail: "floorplan run_002 passed" }
  - { ts: "...", transition: "SCHEDULING → STAGE_RUNNING", detail: "dispatch cts run_001" }
```

**5. SCHEDULING 状态下编排器的决策逻辑框架**

```
读取 state/machine.yaml（当前状态全貌）
读取最近一次 run 的 eval_result.yaml

IF eval_result.overall == pass:
    IF 全局终止条件满足 → COMPLETED
    ELSE → dispatch 下一阶段的 Sub-agent

IF eval_result.overall == fail:
    IF 该阶段重试次数 < 阶段最大重试次数:
        → dispatch 同一个 Sub-agent（retry）
    ELIF eval_result.recommendation == rollback:
        → dispatch 更早阶段的 Sub-agent（rollback）
    ELIF 总重试预算耗尽:
        → ABORTED
    ELSE:
        → revise_spec（Spec 可能过于严格）

IF eval_result.overall == partial:
    编排器自行判断：partial 的部分是否阻塞后续阶段
    → 可以选择带着 partial 继续推进，或者 retry
```

#### 七、 标准运行时闭环工作流 (Runtime Loop)

1. **项目启动：** 系统引导建立工作目录，按标准目录结构初始化 workspace。人类输入模糊目标。
2. **制定宪法：** 编排器唤醒 `Spec_Agent` 具象化目标 → 人类审批 → Spec 文件落盘至 `spec/`。
3. **编排思考：** 编排器读取 Spec 和 `state/machine.yaml`，决策出当前应该解决的核心矛盾，并挑选对应的 Sub-agent。
4. **智能体执行：** 选中的 Sub-agent 被唤醒，读取阶段 Spec + 上游落盘数据，调用底层 MCP 工具链执行并收集结果。
5. **自评估与落盘：** Sub-agent 将执行结果与阶段 Spec 比对，生成 `eval_result.yaml`（含原始数值），连同 `_meta.yaml` 和 artifacts 一并落盘至 `stages/<阶段>/run_NNN/`，结束本次生命周期。
6. **再编排：** 编排器读取落盘的 `eval_result.yaml`，更新 `state/machine.yaml`，追加 `decisions.jsonl`，决定是继续推进（dispatch 下一阶段）、重试、跨阶段回滚，还是唤醒 `Spec_Agent` 修订 Spec。
7. **循环往复，直至进入 `COMPLETED`（满足 Spec 终止条件）或 `ABORTED`（预算耗尽/不可恢复）。**
