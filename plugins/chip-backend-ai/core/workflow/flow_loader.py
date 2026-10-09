#!/usr/bin/env python3
"""Flow-definition-driven execution engine for chip backend design flows.

This is the step-level driver that sits *inside* the orchestrator's
STAGE_RUNNING phase. It does NOT replace the global state machine
(state_manager.py) — that machine still owns the meta-lifecycle
(SPEC_REVIEW, retry budget, rollback, abort). This engine owns the
fine-grained "which sub-step runs next, with which executor, reading
and writing which files" decision, and persists step-level progress so
a brand-new session can resume exactly where a prior one stopped.

Design contract
---------------
- A *flow definition* (templates/flow_definition.yaml) is a static, project
  -independent recipe: ordered stages → ordered steps. Each step names an
  executor and its optional input/output files.
- An executor is one of:
    skill  — mechanical / parameterizable; the orchestrator calls a skill
    agent  — judgement step; the orchestrator wakes a sub-agent to reason
    human  — a human gate; the flow pauses until a human resolves it
- *Progress* (state/flow_progress.yaml) records each step's status. The set
  of output files on disk is the source of truth for "did this step finish"
  — so resuming a flow is just: re-read progress, reconcile with disk, ask
  for the next runnable step.

Resumability (req 1 & 2): `next` recomputes the next action purely from the
on-disk flow snapshot + progress + existing output files. No in-memory state.

Human-in-the-loop (req 3): when `next` reaches a `human` step it returns
`await_human`; after the person finishes the manual operation, calling
`resolve-human` marks the step done and the flow continues.
"""

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

VALID_EXECUTORS = {"skill", "agent", "human"}
VALID_STATUSES = {"pending", "running", "done", "failed", "awaiting_human", "skipped"}

# Step-status values that mean "no more work needed here".
TERMINAL_STATUSES = {"done", "skipped"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _plugin_root() -> Path:
    """core/workflow/flow_loader.py → plugin root is two parents up from core/."""
    return Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------
# Flow-definition loading & iteration
# --------------------------------------------------------------------------

def load_flow_def(flow_path: str | Path) -> dict:
    flow_path = Path(flow_path)
    if not flow_path.exists():
        raise FileNotFoundError(f"Flow definition not found: {flow_path}")
    with open(flow_path) as f:
        return yaml.safe_load(f)


def iter_steps(flow_def: dict):
    """Yield (stage_dict, step_dict, composite_id) in declaration order."""
    for stage in flow_def.get("stages", []):
        for step in stage.get("steps", []):
            yield stage, step, f"{stage['id']}.{step['id']}"


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

def validate(flow_path: str | Path) -> dict:
    """Structurally validate a flow definition.

    Returns a report with hard `errors` (block use) and soft `warnings`
    (e.g. an executor ref that doesn't resolve to an existing skill/agent yet
    — planned-but-not-built skills are expected during bring-up).
    """
    flow_def = load_flow_def(flow_path)
    errors: list[str] = []
    warnings: list[str] = []

    if not flow_def.get("stages"):
        errors.append("flow has no 'stages'")

    root = _plugin_root()
    known_skills = {p.parent.name for p in root.glob("skills/*/SKILL.md")}
    known_agents = {p.parent.name for p in root.glob("agents/*/AGENT.md")}

    produced: dict[str, str] = {}   # output path -> step id that produces it
    step_ids: set[str] = set()
    external_inputs: set[str] = set()

    for stage, step, sid in iter_steps(flow_def):
        if sid in step_ids:
            errors.append(f"duplicate step id: {sid}")
        step_ids.add(sid)

        ex = step.get("executor", {})
        etype = ex.get("type")
        if etype not in VALID_EXECUTORS:
            errors.append(f"{sid}: invalid executor.type '{etype}' (want {VALID_EXECUTORS})")
        if etype == "skill":
            ref = ex.get("ref")
            if not ref:
                errors.append(f"{sid}: skill executor missing 'ref'")
            elif ref not in known_skills:
                warnings.append(f"{sid}: skill '{ref}' not found under skills/ (planned?)")
        elif etype == "agent":
            ref = ex.get("ref")
            if not ref:
                errors.append(f"{sid}: agent executor missing 'ref'")
            elif ref not in known_agents:
                warnings.append(f"{sid}: agent '{ref}' not found under agents/")
        elif etype == "human":
            if not step.get("instruction"):
                warnings.append(f"{sid}: human step has no 'instruction' for the operator")

        for out in step.get("outputs", []) or []:
            produced[out["path"]] = sid

    # Second pass: any required input not produced upstream is an external input.
    for stage, step, sid in iter_steps(flow_def):
        for inp in step.get("inputs", []) or []:
            if inp.get("required") and inp["path"] not in produced:
                external_inputs.add(inp["path"])

    return {
        "ok": not errors,
        "flow": flow_def.get("flow"),
        "version": flow_def.get("version"),
        "stage_count": len(flow_def.get("stages", [])),
        "step_count": len(step_ids),
        "errors": errors,
        "warnings": warnings,
        "external_inputs": sorted(external_inputs),
    }


# --------------------------------------------------------------------------
# Progress persistence
# --------------------------------------------------------------------------

def _snapshot_path(workspace: Path) -> Path:
    return workspace / "flow" / "flow_definition.yaml"


def _progress_path(workspace: Path) -> Path:
    return workspace / "state" / "flow_progress.yaml"


def _load_progress(workspace: Path) -> dict:
    p = _progress_path(workspace)
    if not p.exists():
        raise FileNotFoundError(
            f"No flow progress at {p}. Run 'flow_loader.py start' first."
        )
    with open(p) as f:
        return yaml.safe_load(f)


def _save_progress(workspace: Path, progress: dict) -> None:
    progress["updated_at"] = _now()
    p = _progress_path(workspace)
    tmp = p.with_suffix(".yaml.tmp")
    with open(tmp, "w") as f:
        yaml.dump(progress, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    tmp.replace(p)


def start(workspace: str | Path, flow_path: str | Path) -> dict:
    """Snapshot the flow definition into the workspace and init progress.

    Idempotent-ish: refuses to clobber an existing progress file so a resume
    never loses state. Use the existing workspace if you want to continue.
    """
    workspace = Path(workspace)
    flow_def = load_flow_def(flow_path)

    if _progress_path(workspace).exists():
        raise FileExistsError(
            f"Flow already started (progress exists at {_progress_path(workspace)}). "
            "Use 'next'/'status' to resume."
        )

    # Snapshot the recipe so later edits to the template don't mutate a live run.
    (workspace / "flow").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(flow_path, _snapshot_path(workspace))

    # Pre-create output (and input) directories so executors can just write.
    (workspace / "inputs").mkdir(exist_ok=True)
    for stage, step, sid in iter_steps(flow_def):
        for out in step.get("outputs", []) or []:
            (workspace / out["path"]).parent.mkdir(parents=True, exist_ok=True)

    steps = {}
    for stage, step, sid in iter_steps(flow_def):
        ex = step.get("executor", {})
        steps[sid] = {
            "stage": stage["id"],
            "step": step["id"],
            "name": step.get("name", step["id"]),
            "executor_type": ex.get("type"),
            "executor_ref": ex.get("ref"),
            "gate": bool(step.get("gate", False)),
            "status": "pending",
            "updated_at": _now(),
            "note": "",
        }

    progress = {
        "flow": flow_def.get("flow"),
        "flow_version": flow_def.get("version"),
        "flow_snapshot": "flow/flow_definition.yaml",
        "started_at": _now(),
        "updated_at": _now(),
        "steps": steps,
    }
    _save_progress(workspace, progress)

    # State-machine <-> flow-definition stage reconciliation: workspace.py init
    # seeds machine.yaml with only the DEFAULT_STAGES (floorplan/cts/route), but
    # the flow definition declares all stages (import, powerplan, placement, ...).
    # Without this, state_manager.py update-stage raises "Unknown stage" when the
    # orchestrator records progress for any non-default stage. Backfill any
    # missing stage entry here, preserving existing ones.
    _reconcile_machine_stages(workspace, flow_def)

    return progress


def _reconcile_machine_stages(workspace: Path, flow_def: dict) -> None:
    """Ensure state/machine.yaml has an entry for every flow-definition stage.

    Uses the same default stage shape as workspace.py. If machine.yaml does not
    exist for some reason, skip silently so `start` never crashes.
    """
    machine_path = workspace / "state" / "machine.yaml"
    if not machine_path.exists():
        return
    with open(machine_path) as f:
        machine = yaml.safe_load(f) or {}
    machine.setdefault("stages", {})
    changed = False
    for stage in flow_def.get("stages", []):
        stage_id = stage.get("id")
        if stage_id and stage_id not in machine["stages"]:
            machine["stages"][stage_id] = {
                "status": "pending",
                "current_run": None,
                "retry_count": 0,
                "last_eval": None,
            }
            changed = True

    # Spec -> runtime budget sync: workspace.py seeds machine.yaml with hardcoded
    # defaults (global_retry_budget {max:15, used:0}, no max_stage_retries). The
    # user-approved global_spec.yaml owns these limits, so reconcile them here at
    # start time. Fully defensive: any missing file/section/key leaves the
    # machine.yaml defaults untouched and never crashes.
    spec_path = workspace / "spec" / "global_spec.yaml"
    if spec_path.exists():
        try:
            with open(spec_path) as f:
                spec = yaml.safe_load(f) or {}
        except Exception:
            spec = {}
        constraints = spec.get("global_constraints") or {}
        spec_budget_max = constraints.get("global_retry_budget")
        if spec_budget_max is not None:
            budget = machine.get("global_retry_budget")
            if not isinstance(budget, dict):
                budget = {"max": spec_budget_max, "used": 0}
            else:
                budget["max"] = spec_budget_max  # preserve existing 'used'
                budget.setdefault("used", 0)
            machine["global_retry_budget"] = budget
            changed = True
        spec_max_stage_retries = constraints.get("max_stage_retries")
        if spec_max_stage_retries is not None:
            machine["max_stage_retries"] = spec_max_stage_retries
            changed = True

    if changed:
        with open(machine_path, "w") as f:
            yaml.dump(machine, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


# --------------------------------------------------------------------------
# Disk reconciliation + next-step computation
# --------------------------------------------------------------------------

def _required_outputs(step: dict) -> list[str]:
    return [o["path"] for o in (step.get("outputs", []) or []) if o.get("required")]


def _missing_inputs(workspace: Path, step: dict) -> list[dict]:
    missing = []
    for inp in step.get("inputs", []) or []:
        if inp.get("required") and not (workspace / inp["path"]).exists():
            missing.append({"name": inp.get("name"), "path": inp["path"]})
    return missing


def _reconcile_disk(workspace: Path, flow_def: dict, progress: dict) -> bool:
    """Mark a step done if all its required outputs already exist on disk.

    This is what makes a flow resumable across sessions: even if a prior
    session crashed before recording 'done', the presence of its output
    artifacts is authoritative. Returns True if anything changed.
    """
    changed = False
    step_by_id = {sid: step for _, step, sid in iter_steps(flow_def)}
    for sid, st in progress["steps"].items():
        if st["status"] in TERMINAL_STATUSES:
            continue
        if st["status"] == "failed":
            continue  # a recorded failure is a deliberate signal; don't auto-clear
        step = step_by_id.get(sid)
        req_out = _required_outputs(step) if step else []
        if req_out and all((workspace / p).exists() for p in req_out):
            st["status"] = "done"
            st["updated_at"] = _now()
            st["note"] = "auto-marked done: required outputs present on disk (resume)"
            changed = True
    return changed


def compute_next(workspace: str | Path) -> dict:
    """Return the next action the orchestrator should take.

    action ∈ {run, await_human, blocked_inputs, blocked, flow_complete}
    """
    workspace = Path(workspace)
    flow_def = load_flow_def(_snapshot_path(workspace))
    progress = _load_progress(workspace)

    if _reconcile_disk(workspace, flow_def, progress):
        _save_progress(workspace, progress)

    for stage, step, sid in iter_steps(flow_def):
        st = progress["steps"][sid]
        if st["status"] in TERMINAL_STATUSES:
            continue

        if st["status"] == "failed":
            return {
                "action": "blocked",
                "step_id": sid,
                "stage": stage["id"],
                "name": st["name"],
                "reason": "step is marked failed; orchestrator must decide retry / rollback",
            }

        if st["status"] == "running":
            # A prior dispatch never recorded completion and produced no outputs.
            return {
                "action": "blocked",
                "step_id": sid,
                "stage": stage["id"],
                "name": st["name"],
                "reason": "step left in 'running' (interrupted); re-dispatch or mark done/failed",
            }

        etype = step.get("executor", {}).get("type")

        if etype == "human":
            return {
                "action": "await_human",
                "step_id": sid,
                "stage": stage["id"],
                "name": st["name"],
                "instruction": step.get("instruction", ""),
                "outputs": step.get("outputs", []) or [],
            }

        missing = _missing_inputs(workspace, step)
        if missing:
            return {
                "action": "blocked_inputs",
                "step_id": sid,
                "stage": stage["id"],
                "name": st["name"],
                "missing": missing,
            }

        return {
            "action": "run",
            "step_id": sid,
            "stage": stage["id"],
            "name": st["name"],
            "executor": step.get("executor", {}),
            "inputs": step.get("inputs", []) or [],
            "outputs": step.get("outputs", []) or [],
            "gate": bool(step.get("gate", False)),
            "template": step.get("template"),
            "decisions": step.get("decisions"),
            "report": step.get("report"),
        }

    return {"action": "flow_complete"}


# --------------------------------------------------------------------------
# Status mutation
# --------------------------------------------------------------------------

def mark_step(workspace: str | Path, step_id: str, status: str, note: str = "") -> dict:
    workspace = Path(workspace)
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid status '{status}' (want {VALID_STATUSES})")
    progress = _load_progress(workspace)
    if step_id not in progress["steps"]:
        raise ValueError(f"unknown step id: {step_id}")
    st = progress["steps"][step_id]
    st["status"] = status
    st["updated_at"] = _now()
    if note:
        st["note"] = note
    _save_progress(workspace, progress)
    return st


def resolve_human(workspace: str | Path, step_id: str, note: str = "") -> dict:
    """Mark a human gate as completed so the flow can continue (req 3)."""
    return mark_step(
        workspace, step_id, "done",
        note=note or "human operation completed; flow resumed",
    )


def status(workspace: str | Path) -> dict:
    workspace = Path(workspace)
    progress = _load_progress(workspace)
    counts: dict[str, int] = {}
    for st in progress["steps"].values():
        counts[st["status"]] = counts.get(st["status"], 0) + 1
    total = len(progress["steps"])
    done = counts.get("done", 0) + counts.get("skipped", 0)
    return {
        "flow": progress.get("flow"),
        "flow_version": progress.get("flow_version"),
        "total_steps": total,
        "done": done,
        "percent": round(100 * done / total, 1) if total else 0.0,
        "counts": counts,
        "steps": [
            {"step_id": sid, "status": st["status"], "name": st["name"],
             "executor": st["executor_type"], "gate": st["gate"]}
            for sid, st in progress["steps"].items()
        ],
    }


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Flow-definition-driven execution engine")
    sub = parser.add_subparsers(dest="command")

    p_val = sub.add_parser("validate", help="Validate a flow definition")
    p_val.add_argument("--flow", required=True, help="Path to flow_definition.yaml")

    p_start = sub.add_parser("start", help="Snapshot flow into workspace + init progress")
    p_start.add_argument("--workspace", required=True)
    p_start.add_argument("--flow", required=True, help="Path to flow_definition.yaml")

    p_next = sub.add_parser("next", help="Compute the next action (resumable)")
    p_next.add_argument("--workspace", required=True)

    p_status = sub.add_parser("status", help="Show flow progress")
    p_status.add_argument("--workspace", required=True)

    p_mark = sub.add_parser("mark", help="Set a step's status")
    p_mark.add_argument("--workspace", required=True)
    p_mark.add_argument("--step", required=True, help="Composite step id, e.g. floorplan.macro_placement")
    p_mark.add_argument("--status", required=True, choices=sorted(VALID_STATUSES))
    p_mark.add_argument("--note", default="")

    p_hum = sub.add_parser("resolve-human", help="Mark a human gate done and continue")
    p_hum.add_argument("--workspace", required=True)
    p_hum.add_argument("--step", required=True)
    p_hum.add_argument("--note", default="")

    args = parser.parse_args()

    if args.command == "validate":
        print(json.dumps(validate(args.flow), ensure_ascii=False, indent=2))

    elif args.command == "start":
        progress = start(args.workspace, args.flow)
        print(json.dumps({"status": "ok", "total_steps": len(progress["steps"])}, ensure_ascii=False))

    elif args.command == "next":
        print(json.dumps(compute_next(args.workspace), ensure_ascii=False, indent=2))

    elif args.command == "status":
        print(json.dumps(status(args.workspace), ensure_ascii=False, indent=2))

    elif args.command == "mark":
        st = mark_step(args.workspace, args.step, args.status, args.note)
        print(json.dumps({"status": "ok", "step": args.step, "new_status": st["status"]}, ensure_ascii=False))

    elif args.command == "resolve-human":
        st = resolve_human(args.workspace, args.step, args.note)
        print(json.dumps({"status": "ok", "step": args.step, "new_status": st["status"]}, ensure_ascii=False))

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
