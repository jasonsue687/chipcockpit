---
name: Spec Draft
description: This skill should be used when the orchestrator (or user) needs to turn a fuzzy human PPA goal into the structured flow spec — the global spec plus per-stage specs — at Phase 0, before the flow runs. Trigger on "draft spec", "generate global spec", "generate stage specs", "decompose PPA budget", "spec budget decomposition", "refine stage spec", "revise spec", "起草 spec", "生成 global_spec", "生成阶段 spec", "spec 预算分解", "PPA 预算分解到各 stage", "细化 stage spec", "修订 spec", or whenever the flow's SPEC_DRAFTING state needs spec/global_spec.yaml + spec/stages/<stage>.yaml drafted for human review. The MAIN agent executes this playbook directly (no sub-agent). An optional scripts/scaffold_spec.py writes skeletons from the templates to start from.
version: 0.1.0
---

# Spec Draft — 意图具象化 playbook（global_spec + per-stage spec）

这是 **Phase 0（Spec 层）** 的 **AI 决策 playbook**：把一句模糊的人类 PPA 目标（"跑通这个 block 的 route，主要看 congestion，时序稍微超一点没关系"）变成结构化的 **`spec/global_spec.yaml`** + **逐 stage 的 `spec/stages/<stage>.yaml`**，再经人类审批（SPEC_REVIEW）后驱动整条流水线。

> **无 sub-agent**：本 skill 只装"怎么把意图收敛成可度量的 spec"的方法，由**主 agent 现场加载执行**——读模板 + 人类目标 + 任何上游真实数据，现场推理出这颗芯片的 spec。skill 装方法不装结果（每颗芯片的 spec 都不同）。落盘的 spec 是 **draft**，人类批了才生效；状态机的 transition 由编排器（run-chip-flow）负责，本 playbook 不动 `state/machine.yaml`。

## 这一步产出什么

- **`spec/global_spec.yaml`**（模板 `${CLAUDE_PLUGIN_ROOT}/templates/global_spec_template.yaml`）：项目名、原文人类目标、全局 PPA 目标（timing/power/area）、全局约束（retry budget、technology）、stage 列表、终止条件。
- **`spec/stages/<stage>.yaml`**（模板 `${CLAUDE_PLUGIN_ROOT}/templates/stage_spec_template.yaml`，每 stage 一份）：该 stage 的 `metrics`（name + target，gate 据此比对 actual）+ `parameters`（AI 决策步与 render-tcl 的指导基线）+ `upstream` 依赖。

这两份 spec 之后被每个 stage **只读**地当作"北极星"喂三类节点（plan §4.3）：
```
读 spec/stages/<stage>.yaml
 ├─ metrics[].target      ──▶ 自动校验：gate 比对 actual vs target（parse-eda-report）
 ├─ parameters / 目标      ──▶ AI 决策：判断依据与约束（决策 skill / 主 agent 读）
 └─ 全局 technology/corner ──▶ 自动执行：模板渲染参数
```

## 输入（执行前必读）

主 agent 拿到的上下文（由编排器 Phase B/E 传入）：

1. **`workspace`** — 工作区根目录绝对路径。
2. **`scenario`** — `initial`（首次起草）/ `revision`（gate 反复失败、约束不可达，回炉放宽）/ `adjustment`（人类要改）。
3. **`human_goal`** — 人类模糊目标**原文**（不要转述，原样存进 `human_goal` 字段）。
4. **`context`**（可选）— revision 时是失败的 `eval_result`（哪个指标差多少）；adjustment 时是人类的修改说明；以及任何已有的约束文件（SDC/UPF）。

## 执行步骤

### Step 1 — 读懂目标（意图分类）
从 `human_goal` 里识别：
- **首要关注**：最看重什么？（时序 / 拥塞 / 功耗 / 只求跑通？）
- **可放宽的约束**："时序稍微超一点没关系" ⇒ WNS 阈值可放松。
- **硬约束**：绝不能违的（如 DRC clean 通常硬）。
- **隐含期望**：人类没明说但 PD 默认成立的（如 utilization 落在合理带内）。

### Step 2 — 读模板与上下文
1. 读 `${CLAUDE_PLUGIN_ROOT}/templates/global_spec_template.yaml`。
2. 读 `${CLAUDE_PLUGIN_ROOT}/templates/stage_spec_template.yaml`。
3. `scenario=revision` 时读现行 spec + 失败 eval：
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/core/workflow/spec_manager.py read --workspace <workspace>
   ```
4. 若 workspace 已有约束文件（SDC/UPF/lib header），读它们取 technology / timing / corner 上下文。

### Step 3 — 写 global_spec.yaml
按模板填**具体数字**：
- `project_name`：从目标或 workspace 名提取；`human_goal`：**原文逐字**保留。
- `target_ppa`：按意图设 timing（wns/tns/hold）/ power / area 阈值。时序被放宽 → `wns_ns` 给宽松值；以拥塞为主 → 收紧 congestion 类、放松 timing；"只求跑通" → 全面放松。
- `global_constraints`：`max_stage_retries` / `global_retry_budget` / `technology` / `design_intent`。
- `stages`：默认全 9 个（import→tapeout，见 flow_definition）；目标若明确只跑到某 stage 可裁剪。
- `termination_criteria`：流程"算完成"的条件。

### Step 4 — global → stage **PPA 预算分解**（本 playbook 的核心一步，plan §4.1–4.2）

把 global 的 **PPA 预算型**约束分解成每个 stage 的可度量 `metrics[].target`。**这是 spec-draft 区别于"逐 stage 各写一份"的关键一步**——stage spec 不是凭空写的，而是从 global PPA 预算**自上而下分配**出来的收敛检查点。

务必把握两条红线：
1. **stage spec 是 AI 预测、可重预算的"收敛检查点"，不是 PPA 的硬切分合约**。PPA 是全流程涌现 + 强耦合的——过紧的早期 gate 会造成**假失败**。预算要留裕量、初版宜宽（先成功再收紧），失败可回炉重分。
2. **只分解 PPA 预算型约束**（timing / area / power）；**PDK / 方法学固定型约束（DRC / EM / density / corner）一律加载、不由 AI 生成**——它们由 PDK/signoff deck 决定，spec 只是引用其固定值（如 `drc_violations.max: 0`、IR/EM 阈值取 deck 值），不要"预算"它们。

分解示意（自上而下把 global 预算落到各 stage 的"收敛点"）：

| global 预算 | 怎么分到 stage（PPA 预算型，AI 预测可重算） | 固定型（加载不生成） |
|------------|------------------------------------------|---------------------|
| timing `wns_ns` | floorplan/placement 设 pre-CTS slack 余量；cts 设 `global_skew_ps` / `max_insertion_delay_ps`；timing_eco 设最终 WNS/TNS/hold gate | corner/MMMC 视图来自基座，不分解 |
| area `utilization_min/max` | floorplan `utilization` 带；placement `congestion` 上限 | row/site/density 规则来自 PDK |
| power `total_power_mw` | powerplan `IR drop` 预算（连通性 + 早期 IR） | EM/fill 规则、tap/decap 方法学来自 PDK |
| —（固定型直接加载） | — | route `drc_violations.max:0`、signoff DRC/LVS clean、IR/EM deck 阈值 |

落地动作：对每个 stage（floorplan / powerplan / placement / cts / route / timing_eco / signoff / tapeout，import 主要靠 `blocked_inputs`+`version-check`+库/约束完整性），写它的 `metrics`（name 必须能被 EDA 报告/解析器产出一个数；target 给 min/max 带），并把 global 推导的指导参数写进 `parameters`（决策 skill 与 render-tcl 会读）。可对照 plan §6 的"9 stage × 节点"表确认每个 stage 该有哪些 gate 指标。

> 度量铁律：**每个 metric 必须可度量**——name 要对得上解析器（`core/router.py` 的 `METRIC_PATTERNS`）能从报告里提出来的指标，target 是一个数。提不出来的"指标"不要写成 gate。

### Step 5 — rolling-wave 两级细化（plan §4.2）
spec 是**两级**的，不必在 Phase 0 一次写到底：
```
本 stage 初版 spec（Phase 0 粗预算，信息最少）
    ＋ 上游已积累的真实信息（actual 指标 / 拥塞 / skew / 寄生 …）
    ＋ 人工补充输入（额外约束 / 偏好）
    ──spec-draft 细化──▶ 本 stage 最终 spec ──▶ 喂该 stage 三类节点
```
- **Phase 0**：给所有 stage 一份**粗预算**初版（信息最少、宜宽）。
- **just-in-time 前向细化**：真正进入某 stage 前，用初版 + 上游真实 eval（congestion/skew/寄生）+ 人工补充，**重新预算**该 stage 的最终 spec（前向细化）。
- **后向 `revise_spec`**：gate 失败、约束不可达时回炉放宽（与前向细化互补）。

### Step 6 — revision 场景
`scenario=revision` 时：读失败 eval 看差多少 → 找出过激的阈值 → 给出放宽方案并写清 rationale → 先归档旧 spec 再写新的：
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/core/workflow/spec_manager.py archive --workspace <workspace>
```
用 archive 返回的新版本号更新 `spec_version`。

### Step 7 — 落盘
直接写到（或用 scaffold 脚本先生成骨架再填）：
- `<workspace>/spec/global_spec.yaml`
- `<workspace>/spec/stages/<stage>.yaml`（每 stage 一份）

也可用 spec_manager 保证 YAML 格式一致：
```bash
python3 -c "
import sys; sys.path.insert(0, '${CLAUDE_PLUGIN_ROOT}')
from core.workflow.spec_manager import save_spec
import yaml
save_spec('<workspace>', yaml.safe_load(open('<global.yaml>')), 'global')
save_spec('<workspace>', yaml.safe_load(open('<stage.yaml>')), 'stage', '<stage>')
"
```

### Step 8 — 交人类审批
返回结构化摘要（项目 / 版本 / 原文目标 / 关键决策 + rationale / PPA 目标表 / 各 stage 阈值表 / 写了哪些文件），并提示编排器：spec 是 **draft**，需人类在 **SPEC_REVIEW** 批准（`human_approved`）后流程才开跑；被拒（`human_rejected`）则带反馈重跑本 playbook。

## 可选脚手架脚本（unattended baseline）

`scripts/scaffold_spec.py` 从模板写出 **`global_spec.yaml` + per-stage `<stage>.yaml` 骨架**（含占位 metrics/parameters），让主 agent 从骨架填具体数字，而不是从零拼 YAML。**它只生成骨架，不替代 Step 4 的 PPA 预算分解判断**——真正的"分多少、留多少裕量"是主 agent 现场推理的事。

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/spec-draft/scripts/scaffold_spec.py \
  --workspace <ws> --project <name> --goal "<human goal 原文>" \
  [--stages floorplan,powerplan,placement,cts,route,timing_eco,signoff,tapeout] \
  [--technology sim_n5] [--force]
```
输出单个 JSON 摘要（`status` / `global` / `stages`）。

## 红线（与 §8.4 一致）
- **原文目标逐字保留**在 `human_goal`，不转述。
- **每个 metric 可度量**——对得上解析器能从报告产出的数。
- **初版保守**：宽约束先成功、再收紧，胜过激进约束直接假失败。
- **只分解 PPA 预算型约束**；PDK/方法学固定型一律加载不生成。
- **不改 `state/machine.yaml`**——状态 transition 是编排器的事。
- spec 落盘即 **draft**，人类批了才生效。
