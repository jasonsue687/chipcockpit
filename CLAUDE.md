# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Claude Code plugin (`chip-backend-ai`) that serves as an AI assistant for chip physical design (backend). It has two subsystems:

1. **Knowledge system**: Progressive-disclosure knowledge base for EDA tools (primarily Cadence Innovus) — skills for browsing expert docs, navigating hierarchical user guides, and looking up Tcl commands.
2. **Orchestration system**: Autonomous backend design flow engine. A **two-layer, agent-free, skill-driven** orchestrator: a meta state machine owns the lifecycle (spec approval, retry, rollback, abort) and a step-level flow engine drives the 9-stage / 48-step physical-implementation recipe (9 human-confirm gates — a per-stage `confirm_<stage>_result` on every key/timing stage plus floorplan's mid-stage `confirm_macro`, signoff `waiver_review`, tapeout `final_checklist`). Per-stage judgement lives in **decision skills the main agent executes itself** — there are no live sub-agent dispatches, and the agent drives the loop itself (never via a self-authored driver script). Validated end-to-end in a mock-EDA environment (M1–M10).

## Repository Layout

- `plugins/chip-backend-ai/` — Plugin root (`$CLAUDE_PLUGIN_ROOT`)
  - `.claude-plugin/plugin.json` — Plugin manifest (metadata only; skills are auto-discovered)
  - `skills/*/SKILL.md` — 22 skills (see below)
  - `skills/pdf-to-markdown/scripts/` — Skill-local tooling (`pdf_to_markdown.py`, `analyze_pdf_fonts.py`, `build_knowledge_base.py`). There is no top-level `scripts/` dir for skill logic — put new scripts with the skill that owns them (e.g. each decision skill has `scripts/gen_decisions.py`).
  - `core/router.py` — CLI dispatch layer for knowledge skills + `parse-report` (JSON output, `argparse`)
  - `core/workflow/` — Orchestration engine: `flow_loader.py` (step engine), `state_manager.py` (meta state machine), `workspace.py`, `spec_manager.py`, `decision_logger.py`, `stage_simulator.py`
  - `core/env/env_manager.py` — Machine-level EDA tool bootstrap (detects/validates Innovus; config at `~/.chip-backend-ai/env.json`)
  - `core/sim/mock_eda.py` — Mock-EDA layer: generates loudly-`SIMULATED` but parseable reports so gates can run with no real tool installed
  - `templates/flow_definition.yaml` — **The flow recipe** (9 stages, 48 steps, 9 human gates). Static, cross-project. Loaded by `flow_loader.py`.
  - `templates/tcl/<stage>/*.tcl.tmpl` — Golden Tcl templates, one dir per stage; rendered by `render-tcl` with a step's `decisions.yaml`
  - `templates/*.yaml` — Canonical schemas for the filesystem handoff: `global_spec_template.yaml`, `stage_spec_template.yaml`, `meta_template.yaml`, `eval_result_template.yaml`
  - `agents/*/AGENT.md` — **LEGACY / DEPRECATED.** The per-stage judgement that used to live in sub-agents now lives in decision skills (see Orchestration). Kept for historical reference only; do not dispatch these.
  - `parsers/pdf_to_structured.py` — Offline Markdown → JSON parser for Tcl command extraction
  - `knowledge/expert_base/` — Human-curated expert Markdown docs (kebab-case filenames)
  - `knowledge/processed_eda/` — **Not shipped publicly.** Optional private hierarchical KB from your licensed manuals (gitignored)
- `tests/flow_e2e/` — End-to-end flow harness (`run_e2e.py`), fixtures (`fixtures/inputs`, `fixtures/spec`), and per-run workspaces (`runs/ws_<UTC>/`)
- `docs/` — Design docs and HTML dashboards. Authoritative for the flow engine: `flow_pipeline.md` + `flow_pipeline_plan.md` (design), `flow_impl_progress.md` (orchestrator's cross-session implementation log / milestone ledger), `flow_testing.md`.
- `proposals/` — Earlier design proposals (`floorplan.md`, `knowledgebase.md`)
- `AGENTS.md` — Contributor-guide mirror of this file (Chinese). Keep in sync when layout/commands change.

## Skills

Decision skills, shared/cross-cutting skills, and knowledge skills:

| Skill | Class | Role |
|-------|-------|------|
| `spec-draft` | spec | Phase 0: fuzzy human goal → `global_spec.yaml` + per-stage specs (PPA budget split, rolling-wave). Has `scripts/scaffold_spec.py`. |
| `floorplan-plan`, `floorplan-io-pins`, `floorplan-macro` | decision | Floorplan judgement steps |
| `powerplan-design` | decision | Power planning |
| `placement-design` | decision | Standard-cell placement |
| `cts-design` | decision | Clock tree synthesis spec |
| `route-strategy` | decision | Global + detail route (branches on `--step`) |
| `route-drc-repair` | decision | DRC/antenna repair strategy |
| `timing-eco-design` | decision | Setup/hold/power ECO strategy |
| `render-tcl` | shared | `template + decisions.yaml (+spec)` → concrete `step.tcl` |
| `run-eda-script` | shared | Runs a Tcl script; `--mock` produces SIMULATED parseable reports |
| `parse-eda-report` | shared | Report → `eval_result.yaml` (via `router.py parse-report`); no metrics = partial |
| `version-check` | shared | Deterministic: netlist·SDC·lib·PDK same-release check (import-head, no EDA) |
| `run-chip-flow` | orchestrator | The orchestrator skill — runs the full lifecycle |
| `list-expert-topics`, `read-expert-doc`, `read-eda-lab-doc`, `search-eda-command`, `read-eda-concept`, `chip-kb-wiki` | knowledge | Browse/look up expert docs, hierarchical UG, and Tcl commands |
| `pdf-to-markdown` | tooling | PDF → Markdown + hierarchical KB build |

Every decision skill is **dual-track**: `SKILL.md` is the AI playbook (how the main agent reasons), and `scripts/gen_decisions.py` emits deterministic default `decisions.yaml` so the flow can run unattended.

## Orchestration Architecture

Two layers drive the flow. Edit the right one:

1. **Meta state machine** (`core/workflow/state_manager.py`) — owns the lifecycle:
   ```
   INIT → SPEC_DRAFTING → SPEC_REVIEW → SCHEDULING ⇄ STAGE_RUNNING → COMPLETED | ABORTED
   ```
   Legal transitions live in the `TRANSITIONS` dict at `core/workflow/state_manager.py:17` — that one source of truth. (Event names `agent_done`/etc. are historical contract names; in the agent-free model `agent_done` means "this stage's flow_loader steps reached their gate and the result is on disk.")
2. **Step engine** (`core/workflow/flow_loader.py` + `templates/flow_definition.yaml`) — drives *inside* `STAGE_RUNNING`: which sub-step runs next, with which executor, reading/writing which files. `next` returns one of `run` / `await_human` / `blocked_inputs` / `blocked` / `flow_complete`. **A step is auto-`done` when all its `required: true` outputs exist on disk** — this is what makes the flow resumable.

**Node four-classification** (`executor.type` in `flow_definition.yaml`):
- **AI-decision** (`type: skill` + a `decisions:` field) — main agent runs the playbook → `decisions.yaml`
- **auto-exec** (`type: skill, ref: run-eda-script`) — render template → run
- **auto-eval** (`type: skill, ref: parse-eda-report`, `gate: true`) — parse report → `eval_result.yaml`
- **human** (`type: human`) — flow pauses at `await_human` until `resolve-human`

There are **0 `type: agent`** steps remaining — the agent-free migration is complete.

**Decision-step execution contract** (what the orchestrator/harness does for a step that has a `decisions:` field):
1. `skills/<ref>/scripts/gen_decisions.py --workspace <ws> --step <stage.step> --spec <ws>/spec/stages/<stage>.yaml [--upstream-eval ...] --out <ws>/<decisions path>` → `decisions.yaml` (`{params, fragments, rationale}`)
2. `render_tcl.py --template <templates>/<step.template> --decisions <..> --spec <..> --out <ws>/stages/<stage>/scripts/<step>.tcl` — `params` keys match `{{placeholders}}`, `fragments` keys match `### @inject:<name>`
3. `run_eda_script.py --mock --script <step.tcl> --expect-output <each output> [--report <rpt> --stage --spec]`
4. `flow_loader.py mark <step> done`

**Handoff is filesystem-only.** Each flow gets an isolated workspace (`spec/`, `state/`, `stages/`, `checkpoints/`). Sub-steps communicate via files (`decisions.yaml`, `eval_result.yaml`, DEF/report artifacts) — never large in-context objects. `state/decisions.jsonl` is an append-only audit log. Schemas in `templates/*.yaml` are the contract; don't hand-roll new handoff fields without updating the template.

> When changing the flow: edit `flow_definition.yaml` for step graph / executors / IO; edit `gen_decisions.py` + `SKILL.md` for a decision step's logic; edit `templates/tcl/<stage>/` for the emitted Tcl; edit `state_manager.py:17` for lifecycle transitions. **Do not casually touch `METRIC_PATTERNS` (in `parse-eda-report`/router) or `mock_eda.py`** — the e2e gates depend on them.

## Knowledge Base Architecture

Two-pipeline system:

**Pipeline 1: Expert docs** (human-curated)
```
expert_base/*.md → list-expert-topics (index) → read-expert-doc (full content)
```

**Pipeline 2: PDF user guides** (auto-generated hierarchy)
```
PDF → pdf_to_markdown.py → flat .md → build_knowledge_base.py → hierarchical folders
                                    → pdf_to_structured.py → <tool>.json (command DB)
```

The hierarchical KB uses TOC-driven folder depth (no hardcoded limit). Navigation signal: each `_summary.md` ends with `## Sub-Folders` (descend deeper) or `## Sub-Files` (read `detail_*.md` leaf files).

**Public tree ships no vendor UG dumps.** If you maintain a private `processed_eda/` corpus from licensed manuals, never `Read` a full PDF-converted `.md` directly — enter via `_global_index.md` → `_summary.md` → `detail_*.md` with explicit `offset`/`limit`. Do not commit manuals or `processed_eda/` to the public repo.

## Common Commands

No package manager or build system. All operations use direct Python commands. (`PyYAML` is required for workflow/flow utilities; `PyMuPDF` for PDF tooling.)

```bash
# Syntax check (run on every modified Python file)
python3 -m py_compile plugins/chip-backend-ai/core/workflow/flow_loader.py
python3 -m py_compile plugins/chip-backend-ai/core/workflow/state_manager.py
python3 -m py_compile plugins/chip-backend-ai/core/env/env_manager.py
python3 -m py_compile plugins/chip-backend-ai/core/sim/mock_eda.py

# End-to-end flow test (the primary verification — fresh ws, asserts 48/48 done + 8 gates PASS + flow_complete; step count + human gates derived from flow_def)
python3 tests/flow_e2e/run_e2e.py
# Unit test for the version-check skill
python3 tests/flow_e2e/test_version_check.py

# Flow engine (step-level)
python3 plugins/chip-backend-ai/core/workflow/flow_loader.py validate --flow plugins/chip-backend-ai/templates/flow_definition.yaml
python3 plugins/chip-backend-ai/core/workflow/flow_loader.py start  --workspace <ws> --flow plugins/chip-backend-ai/templates/flow_definition.yaml
python3 plugins/chip-backend-ai/core/workflow/flow_loader.py next   --workspace <ws>
python3 plugins/chip-backend-ai/core/workflow/flow_loader.py status --workspace <ws>
python3 plugins/chip-backend-ai/core/workflow/flow_loader.py mark   --workspace <ws> --step floorplan.macro_placement --status done
python3 plugins/chip-backend-ai/core/workflow/flow_loader.py resolve-human --workspace <ws> --step floorplan.confirm_macro

# Meta state machine
python3 plugins/chip-backend-ai/core/workflow/state_manager.py read --workspace <ws>
python3 plugins/chip-backend-ai/core/workflow/state_manager.py transition --workspace <ws> --event human_input --detail "..."

# Workspace / spec / decision log
python3 plugins/chip-backend-ai/core/workflow/workspace.py init --path <parent_dir> --name <project>
python3 plugins/chip-backend-ai/core/workflow/spec_manager.py read --workspace <ws>
python3 plugins/chip-backend-ai/core/workflow/decision_logger.py read --workspace <ws> --last-n 5

# EDA env bootstrap (machine-level, shared across projects)
python3 plugins/chip-backend-ai/core/env/env_manager.py detect
python3 plugins/chip-backend-ai/core/env/env_manager.py check --tool innovus

# Shared decision-step tooling
python3 plugins/chip-backend-ai/skills/<decision-skill>/scripts/gen_decisions.py --workspace <ws> --step <stage.step> --spec <ws>/spec/stages/<stage>.yaml --out <ws>/<path>
python3 plugins/chip-backend-ai/skills/render-tcl/scripts/render_tcl.py --template <tmpl> --decisions <d.yaml> --out <step.tcl>
python3 plugins/chip-backend-ai/skills/run-eda-script/scripts/run_eda_script.py --mock --script <step.tcl> --expect-output <out>
python3 plugins/chip-backend-ai/skills/version-check/scripts/version_check.py --input <f> --out <rpt>

# Knowledge router CLI
python3 plugins/chip-backend-ai/core/router.py list-topics
python3 plugins/chip-backend-ai/core/router.py read-doc --file example-floorplan-tips.md
python3 plugins/chip-backend-ai/core/router.py search-cmd --tool innovus --cmd-name place_opt
python3 plugins/chip-backend-ai/core/router.py explain --concept CTS
python3 plugins/chip-backend-ai/core/router.py parse-report --simulated ...

# PDF pipeline (requires PyMuPDF)
python3 plugins/chip-backend-ai/skills/pdf-to-markdown/scripts/pdf_to_markdown.py <input.pdf> <output.md> [--start N] [--end N]
python3 plugins/chip-backend-ai/parsers/pdf_to_structured.py --input <guide.md> --tool innovus --output /path/to/private/processed_eda/
python3 plugins/chip-backend-ai/skills/pdf-to-markdown/scripts/build_knowledge_base.py <source.md> --overwrite   # use --dry-run first
```

## Verification

No pytest suite. After changes:
- Run `py_compile` on modified Python files.
- **Run `python3 tests/flow_e2e/run_e2e.py`** — this is the regression gate for any orchestration/skill/template change. It must reach `flow_complete` with 48/48 steps done and 8/8 gates PASS (9 human gates auto-resolved).
- Run `flow_loader.py validate --flow ...` after editing `flow_definition.yaml` (expect 0 warnings, step_count 42).
- For a knowledge skill change: run the relevant `router.py` subcommand.
- For KB changes: run `build_knowledge_base.py --dry-run` and spot-check `_summary.md` and `detail_*.md`.

## Conventions

- **Python**: 4-space indent, `argparse` for CLI, `pathlib.Path` for paths, JSON output for router results.
- **Mock honesty**: mock-EDA output must be loudly labeled `SIMULATED` and never impersonate real PPA. Keep honest stubs honest.
- **Expert docs**: kebab-case filenames (`example-floorplan-tips.md`).
- **Generated KB**: numbered-prefix folders (`01_chapter_slug/`), leaf files use `detail_*.md`.
- **Skills**: YAML front matter with `name`, `description`, `version`; description must list trigger phrases.
- **Commits**: concise, Chinese or English, optional Conventional Commit prefix (`feat:`, `docs:`).

## Security

- `router.py` validates filenames to prevent path traversal — knowledge file access is restricted to `knowledge/` subdirectories.
- Do not commit proprietary EDA manuals or large PDF-derived excerpts.
