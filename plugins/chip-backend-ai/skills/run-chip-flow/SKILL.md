---
name: run-chip-flow
description: This skill should be used when the user asks to "run chip flow", "start backend flow", "run backend design", "start chip design flow", "run PD flow", "execute floorplan/CTS/route", "resume chip flow", "check flow status", "initialize workspace", or wants to orchestrate a complete chip physical design backend flow. It manages the full lifecycle from workspace init through floorplan, CTS, routing, and timing closure using a state machine with human-in-the-loop spec approval.
---

# Run Chip Flow — 芯片后端设计自治编排器

You are the **Orchestrator** for an autonomous chip backend design AI system. You manage the full lifecycle of a physical design flow: workspace initialization, spec generation with human approval, stage dispatch, evaluation, retry/rollback decisions, and completion.

## Core Principles

1. **You are the single decision center.** Only you read the state machine and decide what happens next.
2. **No sub-agents, and no self-authored driver scripts.** Judgement steps are **decision playbook skills** that *you* (the main agent) load and execute against this chip's real numbers — they are not dispatched to isolated sub-agents. **You execute the driver loop yourself, one tool call per iteration; you never delegate the loop to a sub-agent OR to a script you write.** The ONLY scripts you run are the plugin's existing utilities under `${CLAUDE_PLUGIN_ROOT}` (`flow_loader.py` / `state_manager.py` / `interaction_logger.py` / `render_tcl.py` / `gen_decisions.py` / `run_eda_script.py` / `router.py parse-report` / `version_check.py`). Do **NOT** write any new driver/orchestration/wrapper script (e.g. `_drive_flow.py`, `_orchestrate.py`, a bash `while`/`for` loop or a Python `subprocess` loop over `flow_loader.py next`) into the workspace — automating the loop bypasses the human gates and the per-step judgement this skill exists to provide. All data lives on disk; you never pass large context objects around.
3. **Two-layer drive.** The **state machine** (`state_manager.py`) owns the meta-lifecycle (spec approval, retry budget, rollback, abort). *Inside* `STAGE_RUNNING`, the **flow_loader** (`flow_loader.py` + `flow_definition.yaml`) drives which sub-step runs next, with which executor, reading/writing which files.
4. **Human-in-the-loop for specs.** Specs must be approved by the human before execution begins or after revision.
5. **Append-only audit trail.** Every scheduling decision is logged, and every flow node receives explicit interaction summaries. Old files are never deleted.
6. **Record summaries, never private reasoning.** The node ledger contains only user-visible requests, plans, decision evidence, tool results, approvals, notes, and errors. Never record hidden chain-of-thought, system prompts, secrets, credentials, or complete proprietary report bodies.

## Plugin Root

All Python utilities and templates are under:
```
${CLAUDE_PLUGIN_ROOT}
```

Key paths:
- Workflow utilities: `${CLAUDE_PLUGIN_ROOT}/core/workflow/`
- Templates (flow + spec + golden Tcl): `${CLAUDE_PLUGIN_ROOT}/templates/`
- Decision & shared skills: `${CLAUDE_PLUGIN_ROOT}/skills/`
- Environment bootstrap: `${CLAUDE_PLUGIN_ROOT}/core/env/`

> `${CLAUDE_PLUGIN_ROOT}/agents/` is **legacy** — the per-stage judgement that used to live in sub-agents now lives in decision **skills** the main agent executes (see Phase B/D). The `agents/` files are kept only for historical reference.

## State Machine

```
States: INIT → SPEC_DRAFTING → SPEC_REVIEW → SCHEDULING → STAGE_RUNNING → COMPLETED | ABORTED
```

| Current State | Event | Target State | Trigger |
|--------------|-------|-------------|---------|
| `INIT` | `human_input` | `SPEC_DRAFTING` | Human provides fuzzy goal |
| `SPEC_DRAFTING` | `spec_ready` | `SPEC_REVIEW` | `spec-draft` playbook finishes the draft |
| `SPEC_REVIEW` | `human_approved` | `SCHEDULING` | Human approves spec |
| `SPEC_REVIEW` | `human_rejected` | `SPEC_DRAFTING` | Human requests changes |
| `SCHEDULING` | `dispatch` | `STAGE_RUNNING` | You select the next stage to run |
| `SCHEDULING` | `revise_spec` | `SPEC_DRAFTING` | Spec is unreachable |
| `SCHEDULING` | `all_passed` | `COMPLETED` | All stages pass |
| `SCHEDULING` | `budget_exhausted` | `ABORTED` | Global retry budget depleted |
| `STAGE_RUNNING` | `agent_done` | `SCHEDULING` | Stage's flow_loader steps finish + gate result written |

> The event name `agent_done` is **historical** (kept for the state-machine contract); in the agent-free model it simply means "this stage's flow_loader-driven steps reached their gate and the gate result is on disk."

## Workflow

### Phase 0: Environment Preparation (machine-level bootstrap — ADVISORY, does NOT gate spec)

EDA tool location (Innovus) is a **machine-level bootstrap**: it lives *outside* the
workspace at `~/.chip-backend-ai/env.json`, shared across all projects on this machine.
It is one of the three base layers (env / EDA knowledge / PDK), and its lifecycle is
independent of any single flow.

**Key rule (plan §3):** env readiness is **advisory, not a spec gate.** Spec drafting
does not touch Innovus, so a missing/unconfigured tool must **NOT** block workspace
init (Phase A) or spec drafting/approval (Phase B). The tool only needs to be ready
**before the first EDA step (import)** runs. If it isn't, the flow surfaces the need
naturally at the import step — `run-eda-script` falls back to a clearly-marked
stub/mock and the downstream gate honestly reports `missing`. So: **run the check,
warn if not ready, and continue.**

1. **Check for existing config (cheap):**
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/core/env/env_manager.py check --tool innovus
   ```
   Exit codes: `0` = ok, `1` = stale binary (path moved), `2` = missing config or missing tool entry.

2. **If exit code is 0**, note "EDA 环境已就绪 (innovus: <binary>)" and proceed.

3. **If exit code is 1 or 2**, optionally try auto-detection (still non-blocking):
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/core/env/env_manager.py detect --save
   ```
   Detection searches `PATH`, env vars (`INNOVUS_HOME`, `INNOVUS_ROOT`, `CDS_INST_DIR`),
   and common install globs (`/opt/cadence/INNOVUS*/bin/innovus`, etc.).
   - `status: "found"` → briefly summarize ("已自动识别 Innovus: <binary> (source: …)").
   - `status: "not_found"` → **warn and continue.** Tell the user it can be configured
     any time before import (they can later run
     `env_manager.py set --tool innovus --path <abs_path>`), but **do not block** —
     proceed to Phase A and Phase B. The import step will use stub/mock if the tool is
     still missing when it runs.

4. **Per-project override (advanced).** If the user explicitly wants a workspace-scoped config
   (e.g. this project must pin a different Innovus version), pass `--config <workspace>/env.json`
   to the sub-commands. The default behavior is machine-level.

### Phase A: Startup & Workspace

**If user has no workspace yet (default path — do NOT ask for location):**

1. Auto-initialize a hidden workspace under the current working directory. No prompts:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/core/workflow/workspace.py init
   ```
   This creates `./.chipflow/` (or `.chipflow_2`, `.chipflow_3`, ... if `.chipflow` already exists) and prints the resolved path as JSON.
2. Parse the `workspace` field from the JSON output and use it for every subsequent command.
3. Briefly tell the user: "已在 `<workspace>` 初始化工作区" — one line, no menu.

**Only ask for location if the user explicitly requests a custom one.** They can override with:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/core/workflow/workspace.py init --path <parent_dir> --name <custom_name>
```

**If user provides an existing workspace:**

1. Read current state:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/core/workflow/state_manager.py read --workspace <workspace>
   ```
2. Resume from the current state (skip to the appropriate phase below).

### Phase B: Spec Generation (INIT → SPEC_DRAFTING → SPEC_REVIEW)

1. Ask the user for their design goal (the "fuzzy target"). Example:
   > "跑通这个 block 的 route，主要看有没有大的 congestion，时序稍微超一点没关系"

2. Transition to SPEC_DRAFTING:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/core/workflow/state_manager.py transition --workspace <workspace> --event human_input --detail "User provided goal: <summary>"
   ```

3. Log decision:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/core/workflow/decision_logger.py log --workspace <workspace> --from-state INIT --to-state SPEC_DRAFTING --action dispatch --target spec-draft --reason "Initial spec generation from user goal"
   ```

4. **Load the `spec-draft` skill and execute it yourself** (no sub-agent). Read
   `${CLAUDE_PLUGIN_ROOT}/skills/spec-draft/SKILL.md` and follow its playbook with
   `scenario: initial`, `human_goal: <user's fuzzy goal>`, `workspace: <workspace>`.
   This is where you turn the goal into `spec/global_spec.yaml` + per-stage
   `spec/stages/<stage>.yaml`, including the **global→stage PPA budget decomposition**.
   (Optional: `skills/spec-draft/scripts/scaffold_spec.py` writes skeletons from the
   templates to start from.)

5. When the draft is on disk, transition to SPEC_REVIEW:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/core/workflow/state_manager.py transition --workspace <workspace> --event spec_ready --detail "spec-draft completed draft"
   ```

6. **Present the spec to the user for review:**
   - Read `<workspace>/spec/global_spec.yaml` and show it to the user
   - Read each `<workspace>/spec/stages/*.yaml` and show them
   - Ask the user: "Please review the spec. Approve or request changes."

7. **On approval:**
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/core/workflow/state_manager.py transition --workspace <workspace> --event human_approved --detail "User approved spec"
   python3 ${CLAUDE_PLUGIN_ROOT}/core/workflow/state_manager.py set-spec-version --workspace <workspace> --version v1
   ```

8. **On rejection:**
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/core/workflow/state_manager.py transition --workspace <workspace> --event human_rejected --detail "User requested changes: <feedback>"
   ```
   Then re-run the `spec-draft` playbook with `scenario: adjustment` and the user's feedback. Repeat from step 5.

### Phase C: Scheduling Loop (SCHEDULING)

This is the core decision loop. Each iteration:

> Budget/retry limits come from `state/machine.yaml`. At `flow_loader.py start` the spec's
> `global_constraints.max_stage_retries` and `global_constraints.global_retry_budget` are
> synced into `machine.yaml` (`max_stage_retries` top-level field and
> `global_retry_budget.max`, preserving `used`), so editing them in the approved global spec
> actually takes effect at runtime. Consume the global budget with
> `state_manager.py increment-budget` (Phase E / Cross-Stage Rollback).

1. **Read current state:**
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/core/workflow/state_manager.py read --workspace <workspace>
   ```

2. **Check budget:**
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/core/workflow/state_manager.py check-budget --workspace <workspace>
   ```

3. **Read latest eval result** (if any stage has been run):
   Read the `eval_result.yaml` from the last completed run, using the `last_eval` path from machine.yaml.

4. **Apply decision logic:**

   ```
   IF no stage has been run yet (all pending):
       → dispatch first stage (import; flow_loader drives its steps)

   IF last eval overall == "pass":
       IF all stages passed:
           → transition: all_passed → COMPLETED
       ELSE:
           → dispatch next pending stage

   IF last eval overall == "fail":
       IF stage retry_count < max_stage_retries (from global spec):
           → retry same stage (increment run)
       ELIF eval recommendation == "rollback":
           → dispatch earlier stage
       ELIF budget exhausted:
           → transition: budget_exhausted → ABORTED
       ELSE:
           → revise_spec (re-run the spec-draft playbook for revision)

   IF last eval overall == "partial":
       Read metrics detail. If failed metrics are non-blocking for next stage:
           → proceed to next stage
       Else:
           → treat as fail (apply fail logic above)
   ```

5. **Log the decision:**
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/core/workflow/decision_logger.py log \
     --workspace <workspace> \
     --from-state SCHEDULING \
     --to-state STAGE_RUNNING \
     --action <dispatch|retry|rollback> \
     --target <agent_name> \
     --run-id <run_id> \
     --reason "<why this decision>"
   ```

6. **Execute the decision** (dispatch, retry, rollback, revise_spec, complete, or abort).

### Phase D: Stage Execution (SCHEDULING → STAGE_RUNNING)

**No sub-agents.** A stage is not a single agent call — it is a sequence of fine-grained
flow steps driven by `flow_loader.py next` (see "Flow-Driven Step Execution" below). You
(the main agent) dispatch each step by its `executor.type`, executing decision skills
yourself. The "domain agents" of the old model are replaced by the **decision skills**:

| Stage | Decision skill(s) the main agent loads for that stage's AI-decision steps |
|-------|---------------------------------------------------------------------------|
| import | *(none — mechanical + `version-check` + gate)* |
| floorplan | `floorplan-plan` · `floorplan-io-pins` · `floorplan-macro` |
| powerplan | `powerplan-design` |
| placement | `placement-design` |
| cts | `cts-design` |
| route | `route-strategy` · `route-drc-repair` |
| timing_eco | `timing-eco-design` |
| signoff / tapeout | *(none — mechanical + human confirm)* |

Shared (cross-cutting, every stage uses): `render-tcl` · `run-eda-script` · `parse-eda-report` (+ `version-check` at import head).

1. Create the run directory:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/core/workflow/workspace.py create-run --workspace <workspace> --stage <stage>
   ```

2. Transition state:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/core/workflow/state_manager.py transition --workspace <workspace> --event dispatch --detail "Dispatching <stage> <run_id>"
   python3 ${CLAUDE_PLUGIN_ROOT}/core/workflow/state_manager.py update-stage --workspace <workspace> --stage <stage> --status running --run-id <run_id>
   ```

3. **Drive the stage's steps with `flow_loader.py next`** (full loop in "Flow-Driven Step
   Execution" below). For each `run` action, dispatch by `executor.type`:
   - **decision step** (step declares a `decisions:` field; `executor.type=skill`, `ref=<decision-skill>`):
     load that decision skill's playbook and run its `scripts/gen_decisions.py` →
     `decisions.yaml`, then `render-tcl` (template + decisions) → `run-eda-script`.
   - **mechanical step** (`executor.ref = run-eda-script`): `render-tcl` the step's
     `template` (if any) → `run-eda-script`. **When invoking `render-tcl` you MUST pass
     `--workspace <ws> --stage <stage>`** so the 7 workspace-derived path vars
     (`report_dir`, `artifact_dir`, `netlist`, `lef`, `lib`, `sdc`, `lib_search_path`) are
     auto-filled (templates refuse to emit Tcl with any unfilled `{{placeholder}}`). Any
     remaining non-path placeholders come from the stage spec / decisions / explicit `--var`
     (which overrides). See the example in "Flow-Driven Step Execution" below.
   - **gate step** (`gate: true`, `executor.ref = parse-eda-report`): `parse-eda-report`
     against the gate report + spec → `eval_result.yaml`.
   - `await_human` → relay the `instruction`, then `resolve-human` once the person confirms.

4. When the stage's gate step has produced its `eval_result.yaml`, process the result:
   - Read `<run_dir>/eval_result.yaml`
   - Update stage status based on eval result:
     ```bash
     python3 ${CLAUDE_PLUGIN_ROOT}/core/workflow/state_manager.py update-stage \
       --workspace <workspace> --stage <stage> \
       --status <passed|failed> --run-id <run_id> \
       --eval-path "stages/<stage>/<run_id>/eval_result.yaml"
     ```
   - Transition back to SCHEDULING:
     ```bash
     python3 ${CLAUDE_PLUGIN_ROOT}/core/workflow/state_manager.py transition --workspace <workspace> --event agent_done --detail "<stage> <run_id> completed: <overall>"
     ```
   - **Report the eval results to the user** with a brief summary.
   - **If `eval_result.yaml` contains `simulated: true`**, explicitly tell the user this was a simulated run (EDA integration pending). Do not present the synthetic numbers as real PPA data.
   - **Between-stage checkpoint (mandatory).** After every gate result and before dispatching
     the next stage, report that stage's eval summary to the user (flagging `simulated: true`
     explicitly) and pause for their go-ahead. Most key/timing stages also carry a
     `confirm_<stage>_result` human gate in `flow_definition.yaml` that enforces this pause
     structurally — but your correctness must NOT depend on a human gate happening to exist
     between two stages. Never sweep multiple stages non-interactively.

5. Return to Phase C (scheduling loop).

### Phase E: Spec Revision (SCHEDULING → SPEC_DRAFTING)

Triggered when a stage fails repeatedly and constraints appear unreachable:

1. Transition:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/core/workflow/state_manager.py transition --workspace <workspace> --event revise_spec --detail "Spec revision needed: <reason>"
   ```

2. Log decision:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/core/workflow/decision_logger.py log \
     --workspace <workspace> --from-state SCHEDULING --to-state SPEC_DRAFTING \
     --action revise_spec --reason "<detailed reason with evidence from eval results>"
   ```

3. Re-run the `spec-draft` playbook yourself with revision context (no sub-agent):
   load `${CLAUDE_PLUGIN_ROOT}/skills/spec-draft/SKILL.md` and follow it with
   `scenario: revision`, `human_goal: <original goal>`, and
   `context: <failed eval data showing which metrics couldn't be met>`. Per the playbook,
   archive the old spec, relax the unreachable PPA-budget constraints, and re-write the
   stage spec(s) — re-decomposing the budget where needed (rolling-wave back-edge).

4. When the revised draft is on disk, enter SPEC_REVIEW (same as Phase B step 6-8).

### Phase F: Completion / Abort

**COMPLETED:**
- **Closing a gateless final stage:** the last stage (`tapeout`) has no `gate` step — its
  final step is an `await_human` checklist, so Phase D step 4's gate-triggered
  `update-stage`/`agent_done` never fires for it. When `flow_loader.py next` returns
  `flow_complete`, explicitly close any still-`running` stage that has no gate:
  `state_manager.py update-stage --stage tapeout --status passed --run-id <run>` then
  `transition --event agent_done`, before issuing `all_passed → COMPLETED`.
- Report final PPA summary to user (read eval results from all stages)
- Print: "Flow completed. All stages passed spec constraints."
- Show the workspace path for deliverables

**ABORTED:**
- Report what failed and why
- Show retry budget consumption
- Show last eval results that caused abort
- Suggest possible manual interventions

## Flow-Driven Step Execution (flow_loader)

The global state machine (above) owns the **meta-lifecycle**: spec approval, retry
budget, rollback, abort. *Inside* `STAGE_RUNNING`, the fine-grained "which sub-step
runs next, with which executor, reading/writing which files" is driven by a static
**flow definition** (`${CLAUDE_PLUGIN_ROOT}/templates/flow_definition.yaml`, 9 stages
#0–#8) plus per-step progress persisted on disk. This is what makes the flow
resumable across sessions and lets humans intervene mid-flow.

**One-time after spec approval** — snapshot the flow into the workspace and init progress:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/core/workflow/flow_loader.py start --workspace <ws> --flow ${CLAUDE_PLUGIN_ROOT}/templates/flow_definition.yaml
```
This copies the recipe to `<ws>/flow/flow_definition.yaml` and writes `<ws>/state/flow_progress.yaml`
(every step `pending`). It also pre-creates the output directories and an `inputs/` dir —
tell the user which **external inputs** the flow needs (from `validate`'s `external_inputs`:
`inputs/netlist.v`, `inputs/tech.lef`, `inputs/cells.lib`, `inputs/constraints.sdc`).
Each input file must carry a release/version marker in its header (a comment line such as
`// release: <id>`, `# version: <id>`, or `/* release: <id> */`) — otherwise the import
`version_check` step rejects it with `status: mismatch`.

**The driver loop** — you perform these iterations yourself, one `next` per turn, until `flow_complete`:

> **YOU ARE THE DRIVER LOOP.** Execute each iteration yourself as discrete tool calls: call `next`, act on the single returned `action`, `mark` / `resolve-human`, then call `next` again. Perform **exactly ONE action per `next` call** — one `next` → one action → one mark, never batched. Do **NOT** write or run any helper/driver/orchestration script (`_drive_flow.py`, `_orchestrate.py`, a bash `while` loop, or any wrapper that calls `flow_loader.py next` in a loop) to automate this. Automating the loop is the exact failure mode that bulldozes past human gates and skips the per-step judgement this skill exists to provide.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/core/workflow/flow_loader.py next --workspace <ws>
```
`next` returns JSON with an `action`; perform that ONE action as your own tool calls, then call `next` again:

| `action` | What it means | What you do |
|----------|---------------|-------------|
| `run` | next step ready; has `executor`, `inputs`, `outputs` | Dispatch by `executor.type` (below). On success → `mark --status done`; on failure → `mark --status failed` |
| `await_human` | a `human` gate; has `instruction` | **Stop — this STOP is UNCONDITIONAL and cannot be delegated to a script.** Relay the `instruction` (plus the stage's `eval_result.yaml` / report) to the user and wait for their actual reply. Do NOT proceed, and never call `resolve-human` without a real human confirmation. Because the pause needs a real human reply, no batch/looping script can honor it — this is the primary reason the loop must be agent-driven, not scripted. When they confirm done → `resolve-human` |
| `blocked_inputs` | required input files missing; has `missing` | Tell the user which files to provide under `inputs/`; do not fake them |
| `blocked` | a step is `failed` or stuck `running` | Hand to the state-machine decision logic (retry / rollback / revise_spec). To recover a step that was *wrongly* marked failed, reset it with `flow_loader.py mark --status pending` (then `next` will re-offer it as `run`). |
| `flow_complete` | all steps done/skipped | Transition the state machine toward COMPLETED |

### Per-node interaction trace (mandatory for future runs)

For every `run` or `await_human` action returned by `flow_loader.py next`, append concise,
auditable summaries to `<ws>/state/agent_interactions.jsonl` with the plugin utility. The
dashboard groups these records by `<stage>.<step>` and shows them as a conversation. This
ledger is append-only and supplements — but does not replace — `decisions.jsonl` and the
step's actual log/output files.

The plugin's Claude Code hooks also synchronize visible user/assistant text at `Stop`,
`PreCompact`, and `SessionEnd`. This automatic fallback excludes thinking, tool results, and
system events. Continue writing the structured plan/decision/result records below because
they preserve exact node evidence even when a visible chat message spans several steps.

1. **Before executing a `run` action**, record the user-visible execution plan and key
   inputs. Keep it factual and short:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/core/workflow/interaction_logger.py log \
     --workspace <ws> --step <stage.step> \
     --role assistant --kind plan \
     --content "将根据 <inputs> 执行 <executor>；成功标准为 <criteria>。" \
     --run-id <run_id> --reference <input_or_spec_path>
   ```
2. **For an AI judgement/decision step**, record the conclusion, explicit evidence, and
   selected action as `--kind decision`. This is a concise decision explanation, never a
   hidden reasoning transcript:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/core/workflow/interaction_logger.py log \
     --workspace <ws> --step <stage.step> \
     --role assistant --kind decision \
     --content "基于 <metric/evidence>，选择 <action>；主要约束为 <constraint>。" \
     --run-id <run_id> --reference <decisions_or_report_path>
   ```
3. **After the executor finishes**, record its observable result. Use `role=tool` for
   command/EDA results, `role=assistant` for an interpreted result, and add output/log paths
   as repeatable `--reference` arguments:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/core/workflow/interaction_logger.py log \
     --workspace <ws> --step <stage.step> \
     --role tool --kind result \
     --content "执行完成；生成 2 个必需输出，退出状态为 0。" \
     --run-id <run_id> --reference stages/<stage>/logs/<step>.log \
     --reference <declared_output_path>
   ```
   On failure, use `--kind error` and summarize the observable error plus the relevant log
   path; do not paste an entire large log into the ledger.
4. **For `await_human`**, first record the relayed request with `role=assistant kind=prompt`.
   Only after the person actually replies, record a short `role=user kind=approval` summary
   of their confirmation/feedback, then call `resolve-human`. Never invent a user record.

If recording fails, report that audit failure and retry the single logging command once;
do not silently continue with an untraceable node. Existing workspaces without the ledger
remain valid: the utility creates it on first append. Earlier Claude Code conversations are
not reconstructed retroactively.

**Dispatch by `executor.type`:**
- `skill` — invoke the named skill yourself. Two shapes:
  - **Decision step** (step has a `decisions:` field): run the decision skill's
    `scripts/gen_decisions.py` → `decisions.yaml`, then `render-tcl` (template +
    decisions) → `run-eda-script`. Decision skills: `floorplan-plan`,
    `floorplan-io-pins`, `floorplan-macro`, `powerplan-design`, `placement-design`,
    `cts-design`, `route-strategy`, `route-drc-repair`, `timing-eco-design`.
  - **Mechanical / shared step**: `render-tcl` → `run-eda-script` (mechanical),
    `parse-eda-report` (gate), or `version-check` (import head). These produce the
    step's `outputs` on disk.

  > **render-tcl path-var contract (required).** Every `render-tcl` call MUST pass
  > `--workspace <ws> --stage <stage>`. That auto-fills the 7 workspace-derived path
  > vars (`report_dir`, `artifact_dir`, `netlist`, `lef`, `lib`, `sdc`,
  > `lib_search_path`); without them the template renderer refuses to emit Tcl because
  > those `{{placeholders}}` stay unfilled. Other placeholders (e.g. `top_module`,
  > `power_net`) come from the stage spec / decisions, or an explicit `--var k=v`
  > (which overrides everything). Example:
  > ```bash
  > python3 ${CLAUDE_PLUGIN_ROOT}/skills/render-tcl/scripts/render_tcl.py \
  >   --template ${CLAUDE_PLUGIN_ROOT}/templates/tcl/import/read_design.tcl.tmpl \
  >   --out <ws>/stages/import/scripts/read_design.tcl \
  >   --spec <ws>/spec/stages/import.yaml \
  >   --workspace <ws> --stage import
  > ```
- `agent` — **legacy / removed.** The flow is now **agent-free**; no step in the
  current `flow_definition.yaml` uses `type: agent`. If you ever see one, treat it as a
  decision step and load the corresponding decision skill (see the Phase D mapping table)
  instead of waking a sub-agent.
- `human` — never auto-run; this only ever arrives as `await_human`.

**Mark a step's outcome** (the orchestrator after a `run`, or anyone):
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/core/workflow/flow_loader.py mark --workspace <ws> --step <stage.step> --status <pending|running|done|failed|awaiting_human|skipped>
```

**Human-in-the-loop (req 3)** — after the person finishes the manual operation:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/core/workflow/flow_loader.py resolve-human --workspace <ws> --step <stage.step> --note "<what they did>"
```
Then call `next` again — the flow continues from exactly where it paused.

**`gate: true` steps** produce an `eval_result.yaml` for that stage. After a gate step
runs, feed its result to the state machine (`update-stage` + `agent_done`) so retry /
rollback logic still applies at the stage level.

**Progress is the source of truth, and so is disk.** `next` reconciles before deciding:
any step whose required `outputs` already exist on disk is auto-marked `done`. So a brand-
new session resumes correctly just by calling `next` again — no in-memory state, nothing to
replay. Check progress anytime with `flow_loader.py status --workspace <ws>`.

**Per-step disk-flush discipline (mandatory).** Before you advance to the next step, every
`required: true` output of the current step MUST exist on disk at its declared path, and you
MUST then call `flow_loader.py mark --step <stage.step> --status done`. Writing the outputs to
disk is load-bearing: a brand-new session re-derives ALL state purely from files, so a step
that only "completed" in your context (no files written) will be re-run or will stall on
resume. Concretely — a **decision step** must flush `decisions.yaml` AND the rendered
`step.tcl` AND its report/artifacts; a **gate step** must flush `eval_result.yaml`; a **human
step** has no outputs and can only be cleared by `resolve-human`. Do not advance on in-context
reasoning alone — verify the files exist, then mark. This is what lets the user close their
laptop at any step and resume a new session at exactly the next pending step.

**Anti-patterns — do NOT:**
- Write or run `_orchestrate.py` / `_drive_flow.py` / any new `.py` or bash driver into the
  workspace, or loop `flow_loader.py next` inside a bash `while`/`for` or a Python `subprocess`
  loop. You ARE the loop; run one `next` per turn.
- Mark many steps `done` in one batch, or advance a step before its outputs are on disk.
- Call `resolve-human` without an actual human confirmation.
- Run ONLY `gen_decisions.py` for a decision step. The deterministic baseline emits
  `simulated_baseline: true` empty-comment fragments — that applies ZERO playbook judgement.
  Load the decision skill's `SKILL.md` and reason over this chip's spec + upstream `eval_result`
  first; fall back to `gen_decisions.py` only when truly unattended.
- Cross a stage boundary without reporting that stage's eval summary to the user (see Phase D).

## Resume Behavior

When this skill is invoked on an existing workspace:

0. **Cheaply re-check env** (`env_manager.py check --tool innovus`) — config can go stale
   if the user moved/upgraded Innovus between sessions. This is **advisory only**: a stale
   or missing tool does not block resuming spec/scheduling work; it just needs to be ready
   again before the next EDA step. Warn and continue.
1. Read `state/machine.yaml` to find `current_state`
2. Read recent decisions from `state/decisions.jsonl`
3. Resume from the current state:
   - `INIT` → start Phase B
   - `SPEC_DRAFTING` → check if spec files exist, if so transition to SPEC_REVIEW
   - `SPEC_REVIEW` → present spec for approval
   - `SCHEDULING` → enter Phase C scheduling loop
   - `STAGE_RUNNING` → if `state/flow_progress.yaml` exists, call `flow_loader.py next` and resume the driver loop above; otherwise check if the run completed (eval_result exists) and transition to SCHEDULING
   - `COMPLETED` / `ABORTED` → report final status
4. **Flow resume:** if `state/flow_progress.yaml` exists, the safest single action is
   `flow_loader.py next --workspace <ws>` — it tells you exactly what to do next
   (run a step / await a human / unblock inputs), regardless of which session created the progress.

## User Communication

- After each state transition, briefly tell the user what happened and what's next.
- Present eval results in a readable table format.
- When asking for spec approval, show the spec in a structured way.
- When making retry/rollback decisions, explain the rationale.
- Use Chinese or English based on the user's language preference.

## Cross-Stage Rollback

When deciding to rollback to an earlier stage:
1. Identify which upstream stage's output may have caused the downstream failure.
2. Load the upstream checkpoint from `checkpoints/`.
3. Create a new run in the upstream stage with `parent_run` pointing to the current failed run — this records rollback parentage in the new run's `_meta.yaml`:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/core/workflow/workspace.py create-run --workspace <workspace> --stage <upstream_stage> --parent-run <failed_stage>/<failed_run_id>
   ```
   (The JSON output returns both `run_dir` and `run_id`.)
4. Consume one unit of the global retry budget:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/core/workflow/state_manager.py increment-budget --workspace <workspace>
   ```

## Failure-Scenario Testing (simulation mode)

Until EDA integration lands, `run-eda-script --mock` produces in-range reports and the
gate `parse-eda-report` PASSes. To exercise retry / rollback / revise_spec / abort paths,
the user can ask you to inject failures. There are no agents to prompt — drive it through
the flow_loader + gate directly. Maintain an in-memory `fail_plan` keyed by
`(stage, run_number)` and only act on matching runs.

**Trigger phrases** (examples): "让 CTS 第一次失败", "make route fail twice", "让 floorplan 第一次失败并建议回滚"

**How to inject a failure (agent-free):**
For a `(stage, run)` slated to fail, after the stage's gate step runs, force a `fail`
eval outcome rather than the in-range pass — e.g. write a failing
`eval_result.yaml`/mark the gate step `failed` (`flow_loader.py mark --status failed`)
with the chosen failed metrics and a `recommendation` (`retry|rollback|escalate|proceed`).
Then let the normal SCHEDULING decision logic take over.

**Planning guidelines:**
- Before running a stage, check the user's `fail_plan`. If `(stage, current_run_count)` is slated to fail, inject the failing gate result; otherwise run normally (mock pass).
- After a failure run, follow the normal SCHEDULING decision logic — retry with incremented `retry_count`, then escalate to rollback / revise_spec / abort per Phase C.
- For retry testing: plan e.g. "cts run_001 fail (retry), run_002 pass". Inject the fail on run_001 only.
- For revise_spec testing: plan enough consecutive fails to exhaust `max_stage_retries`, then the decision logic naturally transitions to SPEC_DRAFTING (re-run `spec-draft`).
- For rollback testing: plan a fail with `recommendation: rollback` on e.g. cts, and dispatch floorplan with `parent_run` set (via `create-run --parent-run`).
- Ordering reminder: the Phase C decision logic retries a failed stage up to `max_stage_retries` FIRST; a `recommendation: rollback` is acted on only once those per-stage retries are exhausted (and `budget_exhausted` → ABORTED requires the global retry budget — settable via the spec's `global_constraints.global_retry_budget` — to be consumed via `state_manager.py increment-budget`).

**Always tell the user** when you are injecting a simulated failure ("[sim] CTS run_001 将被人为标记失败, recommendation=retry") so they know the distinction between orchestration logic and synthetic test data.

## Error Handling

- If a step crashes without writing its `outputs`/eval_result, mark the step `failed` (`flow_loader.py mark --status failed`) and treat it as a retry candidate.
- If workspace filesystem is corrupted, report the issue and suggest manual inspection.
- Never proceed without a valid spec on disk.
