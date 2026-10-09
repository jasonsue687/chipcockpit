# Flow Implementation — Orchestration Progress (orchestrator's durable notes)

> 编排者(我)的跨会话记账。三角色：**编排者**(我，调度/监控/决定优化方向) · **开发者**(改 skill/流程) · **测试验证者**(跑端到端、汇总问题回报)。
> 红线：所有优化交开发者，我不直接改实现。每完成一个里程碑就发起一次测试验证。

> ## ✅ 项目完成（2026-06-14，M1–M10 全部 PASS）
> 全后端流程已作为 skill 实现，并在无 EDA(mock)环境下从 import 一路端到端跑到 **flow_complete**：
> **9 stage / 48 步 / 8 gate 全 PASS / 0 个 type:agent / 22 skill 齐 / chip.gds 产出**。
> 一键验证：`python3 tests/flow_e2e/run_e2e.py`（每次新建 ws，断言 48/48 done + 8 gate + flow_complete）。
> plan §11 全部待建项闭环。后续可选增强见末尾"后续可选"。
>
> ## ✅ M11 编排护栏 + 逐 stage 人工门（2026-06-28，PASS）
> 修复 problem 1（主 agent 自写 `_orchestrate.py`/`_drive_flow.py` 把流程一把梭，绕过人工门与逐步判断）：
> ① `run-chip-flow/SKILL.md` 加护栏——"你就是 driver loop，一次 `next` 一个动作；禁止自写驱动脚本；
> await_human 无条件停且不可脚本化；每步先落盘再 mark"+ Anti-patterns 清单 + Phase D 跨 stage 检查点。
> ② `flow_definition.yaml` 在 6 个 key/timing stage（floorplan/powerplan/placement/cts/route/timing_eco）
> 各自 `*_eval` 后插入 `confirm_<stage>_result` 人工门 → **42→48 步、3→9 人工门**。
> ③ `run_e2e.py` 步数 + 人工门集合改为从 flow_def **推导**（不再写死 42/3）。state_manager 无需改动。
> 验证：fresh-ws e2e **48/48 done + 8/8 gate PASS + 9/9 人工门 auto-resolve**；`~/chip-demo` 干净重跑同样通过。

## 目标
按 `docs/flow_pipeline.md` + `docs/flow_pipeline_plan.md` 实现完整后端流程；EDA 工具调用先做**模拟版**（当前环境无 EDA）；在独立测试目录安装/调用 skill 走通从 import 到 tapeout 的完整流程。重点：流程顺畅性与完整性。

## 关键架构事实
- 步级引擎 `core/workflow/flow_loader.py`：`next` 算下一步动作（run/await_human/blocked_inputs/blocked/flow_complete）；磁盘 required outputs 存在=自动 done（可续跑）。
- 元状态机 `core/workflow/state_manager.py`：INIT→SPEC_DRAFTING→SPEC_REVIEW→SCHEDULING⇄STAGE_RUNNING→COMPLETED/ABORTED。
- 共享执行 `skills/run-eda-script`：现仅 stub（占位文件，无指标）。**需加 mock 模式产出可解析报告**。
- 共享解析 `skills/parse-eda-report`（via `core/router.py parse-report`）：报告→eval_result，无指标=missing=partial。**gate 要 pass 必须报告里有指标**。
- 节点四分类：AI决策(playbook skill+主agent→decisions.yaml) / 自动执行(render-tcl→run-eda-script) / 自动校验(parse-eda-report) / 人工(await_human)。
- flow_definition.yaml 现状：含 5 个 `type:agent`(place_io_pins/macro_placement/gen_cts_spec/drc_repair/fix_strategy) + 1 个不存在 skill ref `gen-power-plan-tcl`。需改为 skill 化 + gen→run→eval。

## 关键设计决定（编排者拍板，交开发者执行）
1. **mock EDA 层**：run-eda-script 增加显式 `--mock` 路径——按 step 声明的报告模板/spec 指标生成"合理但明确标注 SIMULATED"的报告，让 gate 能 pass。诚实 stub 保留。绝不冒充真实 PPA。
2. **每个机械/决策步引用模板**：flow_definition step 增加 `template:`(tcl 模板) 与决策步 `decision_skill:`；render-tcl 读 模板+decisions(+spec)→step.tcl。
3. **决策 skill 双轨**：每个决策 skill = playbook(SKILL.md, AI 方法) + `scripts/gen_decisions.py`(从 spec/上游 eval 推确定性默认 decisions.yaml)，保证无人值守也能走完，AI 可改进。
4. **测试目录**：harness 与 fixtures 放 `tests/flow_e2e/`；每次跑新建 workspace `tests/flow_e2e/runs/ws_<ts>/`。

## 决策步执行契约（编排者拍板，开发者照此实现，避免反复设计）
一个"AI 决策"节点 = 1 个 flow step，`executor:{type:skill, ref:<决策skill名>}` + 额外字段 `template:`、`decisions:`(写入路径)。执行顺序（harness/主agent）：
1. **gen**：`skills/<决策skill>/scripts/gen_decisions.py --workspace <ws> --step <stage.step> --spec <ws>/spec/stages/<stage>.yaml [--upstream-eval ...] --out <ws>/<decisions路径>` → decisions.yaml(`{params,fragments,rationale}`)。SKILL.md=AI方法(playbook)，脚本=确定性默认值保证无人值守。
2. **render**：`render_tcl.py --template <PR templates>/<template> --decisions <..> --spec <..> --out <ws>/stages/<stage>/scripts/<step>.tcl`。params 键须匹配模板 `{{占位}}`，fragments 键须匹配 `### @inject:<名>`。
3. **run**：`run_eda_script.py --mock --script <step.tcl> --expect-output <每个output> [--report <rpt> --stage --spec]`。
4. `flow_loader mark done`。harness 判定"决策步"：step 含 `decisions:` 字段 → 跑 gen_decisions(ref)。

## 里程碑
- [x] **M1 基座+import 竖切**：render-tcl skill；run-eda-script mock 模式；import 4 步 tcl 模板；fixtures；harness；import gate mock 下 PASS。✅ 验证 PASS-WITH-ISSUES。
- [x] **M2 floorplan**：3 决策 skill(floorplan-plan/io-pins/macro)+confirm_macro 人工+gate。flow_definition agent→skill。✅ 验证 PASS-WITH-ISSUES：两 gate(import+floorplan)mock 下 PASS、决策步契约真实跑通、SKILL.md playbook 含 search-eda-command 护栏、human gate 自动 resolve、可续跑(next→powerplan)。横切 #1#2 已修。
- [x] **M3 powerplan**：powerplan-design 决策 skill + 机械步模板 + gate。✅ 验证 **PASS**(无 blocker/无 correctness bug)：三 gate(import+floorplan+powerplan)PASS(IR=35≤50mV)、validate 0 warning(过时 ref 已清)、决策契约真实、SKILL.md 含护栏、M2-a/M2-b 修复确认、可续跑(next→placement)。
- [x] **M4 placement**：placement-design 决策 skill(place_opt) + scan_reorder/congestion_analysis 机械模板 + gate。✅ 验证 **PASS**(无 blocker/无 correctness bug)：四 gate(import+floorplan+powerplan+placement)PASS(congestion=0.56≤0.8)、validate 0 warning、决策契约真实跑通、congestion_analysis 保持机械且悬空 `@inject` 已删、placement_eval 加显式 report、可续跑(next→cts)。
- [x] **M5 cts**：cts-design 决策 skill(gen_cts_spec, agent→skill) + build_clock_tree/postcts_opt 机械模板 + gate。✅ 验证 **PASS**(无 blocker)：五 gate(import+floorplan+powerplan+placement+cts)PASS(skew=56≤80ps、insertion=280≤400ps)、validate 0 warning、gen_cts_spec output 保持 cts.spec、METRIC_PATTERNS 未动(复用现有 skew/insertion)、可续跑(next→route)。
- [x] **M6 route**：route-strategy(global+detail_route, --step 分支) + route-drc-repair(drc_repair, agent→skill) + gate。✅ 验证 **PASS**(无 blocker)：六 gate(import+floorplan+powerplan+placement+cts+route)PASS(drc=0≤0)、validate 0 warning、3 决策 skill 步契约真实、两 SKILL.md 含护栏(drc-repair 含迭代回路)、METRIC_PATTERNS 未动、仅剩 timing_eco.fix_strategy 一个 type:agent、可续跑(next→timing_eco)。
- [x] **M7 timing_eco**：timing-eco-design 决策 skill(fix_strategy, **最后一个 agent→skill**) + extract/sta/apply 机械模板 + gate。✅ 验证 **PASS-WITH-ISSUES**(无 blocker)：七 gate PASS(wns-0.09≥-0.1/tns-0.9≥-1.0/hold0.1≥0.0)、validate 0 warning、**全流程 0 个 type:agent(里程碑目标达成)**、timing_eval 读 post-ECO eco_timing.rpt、METRIC_PATTERNS 未动、可续跑(next→signoff)。2 个 cosmetic issue(见下)已 defer。
- [x] **M8 signoff+tapeout(全流程端到端完成)**：两个 0 决策 stage 合并。signoff 机械(metal_fill→filled.def/signoff_drc_lvs→drc_lvs.rpt/signoff_ir_em→ir_em.rpt)+waiver_review 人工+signoff_eval gate(单 report drc_lvs.rpt，drc_violations{max:0})；tapeout 机械(chip_finishing→final.def/streamout→chip.gds)+final_checklist 人工+**无 gate**。harness 去掉 STOP-at-gate、驱动到 **flow_complete**。✅ 验证 **PASS-WITH-ISSUES**(无 blocker，**核心目标达成**)：**全流程 import→tapeout 跑到 flow_complete**(两次 clean run)、status 41/41 done(100.0%)、8 gate(import…signoff)全 PASS+simulated:true、三人工 gate(confirm_macro/waiver_review/final_checklist)自动 resolve、11 个 decisions.yaml、DEF→GDS 产物链完整、chip.gds 产出(SIMULATED)、next 幂等返回 flow_complete、validate 0 warning、METRIC_PATTERNS/mock_eda 未动。遗留 5 个 minor(banner 文案 + M9/M10 收尾项)。
- [x] **M9 version-check**：建确定性 `version-check` skill + import 头部步 + harness 分支 + version 标记 fixture。✅ 验证 **PASS**(无 correctness bug)：全流程 **42/42 done** 跑到 flow_complete、version_check 为首步且 CONSISTENT、**mismatch+missing-marker 检测均生效(非 no-op)**、blocked_inputs 仍工作、validate 0 warning step_count 42、banner 已修。
- [x] **M10 收尾(doc/skill 迁移，不影响 harness)**：建 `spec-draft` skill(从 agents/spec-agent 迁 playbook，含 global→stage 预算分解 + rolling-wave) + 可选 `scripts/scaffold_spec.py`(从模板写 global+per-stage 骨架) + run-chip-flow SKILL.md 对齐(env 改为 advisory 机器级 bootstrap、不 gate spec、去掉"Do NOT proceed to Phase A until innovus exit 0"；Phase B/D/E 改 skill+flow_loader 驱动模型，去掉全部 sub-agent dispatch；executor.type 表 `agent`→legacy/removed；Failure-Scenario/Error 去 agent 文案) + agents/ 5 个 AGENT.md 加 DEPRECATED 标注(各指向对应 skill) + run_e2e.py cosmetic 注释修复 + (可选)tests/flow_e2e/test_version_check.py 最小单测(4 case PASS)。✅ 验证 **PASS-WITH-ISSUES**(tester 独立验证，4 issue 经编排者核验全为非功能性=git 未提交状态误读 / diff 误读 / 路径措辞松)：全流程 **42/42 done** 跑到 flow_complete、8 gate PASS、3 人工 gate 自动 resolve、validate 0 warning step_count 42、py_compile 干净、version_check 单测 4/4 PASS、22/22 skill 齐、SKILL.md 无 subagent_type/Spawn-Agent 主路径且 env advisory、5 AGENT.md banner OK。编排者核验 flow_definition 无重复 template: 键(读 read_design 仅 1 个，30 步 30 行)。**METRIC_PATTERNS / mock_eda / flow_definition 步图未动。plan §11 全部待建项闭环。**

## 待开发者处理的 issue
### 已闭环（M1/M2）
- ~~#1~~ placement.congestion_analysis executor 已改 run-eda-script。~~#2~~ parse-report --simulated 已加。~~#3~~ harness 决策步分支已加。~~#4~~ await_human 自动 resolve 已加。~~#5~~ floorplan_check.rpt + gate report 已接。~~#6/#7~~ floorplan fixture+模板已补。
### M2 遗留 minor（折进 M3 dev 顺手修，非阻塞）
- **M2-a MINOR**：fixtures/spec/stages/floorplan.yaml 的 `pin_layer_v` 未被 place_io_pins 模板/gen_decisions 使用 → 模板加 `{{pin_layer_v}}` + gen_decisions 读它(默认 M4)。
- **M2-b MINOR**：floorplan 4 个渲染 tcl 的 defOut 路径含非规范 `{{report_dir}}/../artifacts/` → 改用单独 `--var artifact_dir=` 传规范路径(仿 add_blockage 的 floorplan_check.rpt 写法)。
- **驳回** tester 建议给 congestion_analysis 加决策 skill：按 plan §6 placement 仅 1 决策 skill(placement-design→place_opt)，congestion_analysis 是非 gate 自动校验，保持机械，M4 给模板即可。

## M7 遗留 cosmetic issue（defer，非阻塞，M9 收尾可选处理）
- **M7-a**：mock 给 signoff_sta 的 timing.rpt(pre-ECO) 与 apply_eco 的 eco_timing.rpt(post-ECO) 写了相同指标值。gate 读对了文件(eco_timing.rpt)，仅"前后无差异"不利于将来 retry 路径测试。defer。
- **M7-b**：timing-eco-design/gen_decisions.py 的 `hold_pressure` 用 `<0` 而非 `<=0`，加注释说明意图即可(逻辑正确，spec params 已 override)。defer。

## 🎉 里程碑：全流程端到端打通（M8 完成）
import→floorplan→powerplan→placement→cts→route→timing_eco→signoff→tapeout 在 mock 下从头跑到 **flow_complete**，41/41 步 done、8 gate PASS、chip.gds 产出。用户核心目标"能从头到尾完成整个流程的运行"**已达成**。剩 M9(version-check 步)+M10(spec-draft skill + 文档对齐 + agents 弃用) 为 plan §11 待建项收尾。

## M10 收尾开发要点（编排者交底）—— 最后一个里程碑（doc/skill 迁移，不影响 harness）
- **建 `skills/spec-draft`**(SKILL.md playbook + 可选 scaffolding 脚本)：从 `agents/spec-agent/AGENT.md` 迁判断方法，主 agent 执行；明确"human_goal → global_spec.yaml + per-stage spec"，含 **global→stage PPA 预算分解**(plan §4.2/§11-9)。只装方法不装结果。
- **run-chip-flow/SKILL.md 对齐**(plan §11-7)：① env = 机器级 bootstrap，**不 gate spec**——把"Do NOT proceed to Phase A until check innovus exit 0"改为 advisory(env 只需在首个 EDA 步 import 前就绪，不阻塞 workspace init/spec)；② Phase B 把 spawn spec-agent sub-agent 改为调 `spec-draft` skill(主 agent 执行)；③ Phase D 把 spawn floorplan/cts/route/timing-eco sub-agent 改为 **flow_loader 驱动的 skill 决策步**模型(参 docs/flow_impl_progress 决策步执行契约 + flow_definition)；去掉过时 sub-agent dispatch 文案。
- **agents/ 弃用**：5 个 AGENT.md(spec/floorplan/cts/route/timing-eco) 顶部加 `> DEPRECATED — 已迁为 skills/<name>，由主 agent + flow_loader 驱动，保留仅作历史参考`，指向对应 skill。
- **cosmetic**：run_e2e.py 模块 docstring "Milestone 8"→现状(或泛化措辞)、line~416 注释 "both"→"all 3 human steps"。
- **最终 clean 验证**：harness 全流程仍 42/42 done 跑到 flow_complete、validate 0 warning、py_compile 干净。(可选)给 version_check.py 加最小单测。
- ⚠️ 别动 METRIC_PATTERNS / mock_eda；别破坏已跑通的 flow。完成后全部 plan §11 待建项闭环。

## 进度日志
- 2026-06-13: 读完两方案 + 全部现有基座代码。拍板设计（mock 层 + 决策步契约 + 决策 skill 双轨 + tests/flow_e2e）。
- 2026-06-13: M1 开发(developer)完成→验证(tester)PASS-WITH-ISSUES。import 端到端走通、gate mock 下 PASS、可续跑(next 指向 floorplan)。issue 见上。下一步 M2 floorplan（含 #1#2 横切修复）。
- 2026-06-13: M2 开发(developer)完成→验证(tester)PASS-WITH-ISSUES。floorplan 3 决策 skill + agent→skill 迁移 + human 自动 resolve + 横切 #1#2 修复全部跑通；import+floorplan 两 gate PASS。遗留 2 个 minor(M2-a/M2-b)折进 M3。下一步 M3 powerplan(ref 改 powerplan-design)。
- 2026-06-13: M3 开发(developer)完成→验证(tester)**PASS**(无 blocker)。powerplan-design 决策 skill + 机械步模板 + M2-a/M2-b 修复全部跑通；import+floorplan+powerplan 三 gate PASS、validate 0 warning。下一步 M4 placement(placement-design)。
- 2026-06-13: M4 开发(developer)完成→验证(tester)**PASS**(无 blocker)。placement-design 决策 skill + 机械模板 + placement.yaml fixture 全部跑通；四 gate(import+floorplan+powerplan+placement)PASS、validate 0 warning、可续跑(next→cts)。tester 误称 global_skew_ps/max_insertion_delay_ps 缺失→编排者驳回(已在 METRIC_PATTERNS)。下一步 M5 cts(cts-design，gen_cts_spec 仍 type:agent 待迁)。
- 2026-06-13: M5 开发(developer)完成→验证(tester)**PASS**(无 blocker)。cts-design 决策 skill(gen_cts_spec agent→skill) + build/postcts 模板 + cts.yaml fixture 全部跑通；五 gate PASS、validate 0 warning、METRIC_PATTERNS 未动、可续跑(next→route)。tester 又误称 drc_violations 缺失→编排者驳回(已在 METRIC_PATTERNS，import 在用)。下一步 M6 route(route-strategy 覆盖 global+detail_route、route-drc-repair 覆盖 drc_repair；drc_repair 仍 type:agent 待迁)。
- 2026-06-13: M6 开发(developer)完成→验证(tester)**PASS**(无 blocker)。route-strategy(global+detail，--step 分支)+route-drc-repair(drc_repair agent→skill) 全部跑通；六 gate PASS、validate 0 warning、METRIC_PATTERNS 未动、仅剩 1 个 type:agent(timing_eco.fix_strategy)。tester 误说 timing_eval 读 timing.rpt→编排者纠正为 eco_timing.rpt(post-ECO，gate 判最终时序)。下一步 M7 timing_eco(timing-eco-design)。
- 2026-06-14: M7 开发(developer)完成→验证(tester)**PASS-WITH-ISSUES**(无 blocker，2 cosmetic defer)。timing-eco-design(fix_strategy 最后一个 agent→skill) + extract/sta/apply 模板全部跑通；七 gate PASS、validate 0 warning、**全流程 0 type:agent**、可续跑(next→signoff)。下一步 M8 signoff+tapeout 合并收口(驱动到 flow_complete，8 gate)。
- 2026-06-14: **M8 开发(developer)完成→验证(tester)PASS-WITH-ISSUES——🎉 全流程端到端打通**。signoff+tapeout 模板/fixture + harness 驱动到 flow_complete 全部跑通；两次 clean run：import→tapeout 41/41 done(100%)、8 gate PASS、3 人工 gate 自动 resolve、11 decisions.yaml、DEF→GDS 链完整、chip.gds 产出、next 幂等 flow_complete、validate 0 warning。**用户核心目标达成**。5 个 minor(banner 文案 + version-check/spec-draft/run-chip-flow 文案/agents 弃用=M9/M10)。下一步 M9 version-check。
- 2026-06-14: M9 开发(developer)完成→验证(tester)**PASS**(无 correctness bug)。version-check skill(确定性，mismatch+missing 检测生效) + import 首步 + harness 分支 + version 标记 fixture + banner 修复全部跑通；全流程 **42/42 done** 跑到 flow_complete、8 gate PASS、validate 0 warning step_count 42。下一步 M10 收尾(spec-draft skill + run-chip-flow 文案对齐 + agents 弃用 + 最终验证)——最后一个里程碑。
- 2026-06-14: **M10 开发(developer)完成→验证(tester)PASS-WITH-ISSUES——🏁 项目收官**。spec-draft skill + run-chip-flow SKILL.md 对齐(去 sub-agent/env advisory) + 5 AGENT.md 弃用 + cosmetic + version_check 单测全部跑通；全流程 42/42 done 跑到 flow_complete、8 gate PASS、validate 0 warning、22/22 skill 齐。tester 4 个 issue 经编排者核验全为非功能性(git 未提交累积 diff 误读 ×3 + template 重复键误读 ×1，实测无重复)。**用户目标全部达成：所有 skill 已建 + 全流程端到端跑通。** 后续为可选增强，非必需。

## 后续可选（非必需，项目目标已达成）
- 失败注入路径测试：用 stage_simulator force_fail / run-chip-flow fail_plan 验 state_manager 的 retry/rollback/revise_spec 编排(当前 harness 只测 happy-path flow_loader)。
- M7-a：mock 让 pre-ECO timing.rpt 比 post-ECO 差，使 retry 路径更真实。
- 真实 EDA 接入：把 run-eda-script 的 mock 换成真 Innovus(env_manager 已就绪)，decision skill 的 gen_decisions 之外让主 agent 按 playbook 现场推理。
- 提交：当前 M1–M10 全部改动尚未 git commit（用户未要求；需要时再提）。
- 2026-06-14: **M10 开发(developer)完成——最后一个里程碑，plan §11 全部待建项闭环**。建 `skills/spec-draft`(playbook + scaffold_spec.py，含 global→stage PPA 预算分解 + rolling-wave + revision)；run-chip-flow SKILL.md 全面对齐无 sub-agent / flow_loader 驱动模型(env advisory 不 gate spec、Phase B/D/E 改 skill、executor 表 agent→legacy、引用 9 决策 skill + 共享 skill)；5 个 AGENT.md 加 DEPRECATED banner；run_e2e.py 两处 cosmetic 注释修复；新增 test_version_check.py(4 case PASS)。自检：全流程 42/42 done 到 flow_complete、8 gate PASS、validate 0 warning step_count 42、py_compile 干净、SKILL.md grep 无主路径 sub-agent。**未动 METRIC_PATTERNS/mock_eda/flow_definition 步图。待 tester 端到端复核。**
