#!/usr/bin/env python3
"""Global state machine management for chip backend design flows.

Manages state/machine.yaml — the single source of truth for the orchestrator.
Enforces legal state transitions per the proposal state table.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

# Legal state transitions: {current_state: {event: target_state}}
TRANSITIONS = {
    "INIT": {
        "human_input": "SPEC_DRAFTING",
    },
    "SPEC_DRAFTING": {
        "spec_ready": "SPEC_REVIEW",
    },
    "SPEC_REVIEW": {
        "human_approved": "SCHEDULING",
        "human_rejected": "SPEC_DRAFTING",
    },
    "SCHEDULING": {
        "dispatch": "STAGE_RUNNING",
        "revise_spec": "SPEC_DRAFTING",
        "all_passed": "COMPLETED",
        "budget_exhausted": "ABORTED",
    },
    "STAGE_RUNNING": {
        "agent_done": "SCHEDULING",
    },
    "COMPLETED": {},
    "ABORTED": {},
}

ALL_STATES = set(TRANSITIONS.keys())


def read_state(workspace: str | Path) -> dict:
    """Load the current state machine snapshot from machine.yaml."""
    workspace = Path(workspace)
    state_file = workspace / "state" / "machine.yaml"

    if not state_file.exists():
        raise FileNotFoundError(f"State file not found: {state_file}")

    with open(state_file) as f:
        return yaml.safe_load(f)


def write_state(workspace: str | Path, state: dict) -> None:
    """Write the state machine snapshot to machine.yaml (atomic overwrite)."""
    workspace = Path(workspace)
    state_file = workspace / "state" / "machine.yaml"
    tmp_file = state_file.with_suffix(".yaml.tmp")

    with open(tmp_file, "w") as f:
        yaml.dump(state, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    tmp_file.replace(state_file)


def transition(workspace: str | Path, event: str, detail: str = "") -> dict:
    """Execute a state transition.

    Args:
        workspace: Workspace root path.
        event: The transition event name (e.g., "dispatch", "human_approved").
        detail: Human-readable detail for the history log.

    Returns:
        Updated state dict.

    Raises:
        ValueError: If the transition is illegal from the current state.
    """
    state = read_state(workspace)
    current = state["current_state"]

    if current not in TRANSITIONS:
        raise ValueError(f"Unknown state: {current}")

    if event not in TRANSITIONS[current]:
        legal = list(TRANSITIONS[current].keys())
        raise ValueError(
            f"Illegal transition: event '{event}' not valid from state '{current}'. "
            f"Legal events: {legal}"
        )

    target = TRANSITIONS[current][event]
    ts = datetime.now(timezone.utc).isoformat()

    # Append to history
    state.setdefault("history", []).append({
        "ts": ts,
        "transition": f"{current} → {target}",
        "event": event,
        "detail": detail,
    })

    state["current_state"] = target
    write_state(workspace, state)
    return state


def update_stage_status(
    workspace: str | Path,
    stage: str,
    status: str,
    run_id: str | None = None,
    eval_path: str | None = None,
) -> dict:
    """Update the status of a specific stage in the state machine.

    Args:
        workspace: Workspace root path.
        stage: Stage name (e.g., "floorplan").
        status: New status ("pending", "running", "passed", "failed").
        run_id: Current run ID (e.g., "run_001").
        eval_path: Relative path to eval_result.yaml.

    Returns:
        Updated state dict.
    """
    state = read_state(workspace)

    if stage not in state.get("stages", {}):
        raise ValueError(f"Unknown stage: {stage}. Known: {list(state['stages'].keys())}")

    stage_info = state["stages"][stage]
    stage_info["status"] = status

    if run_id is not None:
        stage_info["current_run"] = run_id

    if eval_path is not None:
        stage_info["last_eval"] = eval_path

    if status == "failed":
        stage_info["retry_count"] = stage_info.get("retry_count", 0) + 1

    write_state(workspace, state)
    return state


def increment_budget(workspace: str | Path) -> dict:
    """Increment the used retry budget by 1."""
    state = read_state(workspace)
    budget = state.get("global_retry_budget", {"max": 15, "used": 0})
    budget["used"] = budget.get("used", 0) + 1
    state["global_retry_budget"] = budget
    write_state(workspace, state)
    return state


def check_budget(workspace: str | Path) -> dict:
    """Check the global retry budget status.

    Returns:
        Dict with max, used, remaining, exhausted fields.
    """
    state = read_state(workspace)
    budget = state.get("global_retry_budget", {"max": 15, "used": 0})
    remaining = budget["max"] - budget["used"]
    return {
        "max": budget["max"],
        "used": budget["used"],
        "remaining": remaining,
        "exhausted": remaining <= 0,
    }


def set_spec_version(workspace: str | Path, version: str) -> dict:
    """Update the spec_version field in the state machine."""
    state = read_state(workspace)
    state["spec_version"] = version
    write_state(workspace, state)
    return state


def main():
    parser = argparse.ArgumentParser(description="State machine management")
    sub = parser.add_subparsers(dest="command")

    # read
    p_read = sub.add_parser("read", help="Read current state")
    p_read.add_argument("--workspace", required=True)

    # transition
    p_trans = sub.add_parser("transition", help="Execute a state transition")
    p_trans.add_argument("--workspace", required=True)
    p_trans.add_argument("--event", required=True, help="Transition event name")
    p_trans.add_argument("--detail", default="", help="Detail message")

    # update-stage
    p_stage = sub.add_parser("update-stage", help="Update stage status")
    p_stage.add_argument("--workspace", required=True)
    p_stage.add_argument("--stage", required=True)
    p_stage.add_argument("--status", required=True, choices=["pending", "running", "passed", "failed"])
    p_stage.add_argument("--run-id", default=None)
    p_stage.add_argument("--eval-path", default=None)

    # check-budget
    p_budget = sub.add_parser("check-budget", help="Check retry budget")
    p_budget.add_argument("--workspace", required=True)

    # increment-budget
    p_incr = sub.add_parser("increment-budget", help="Consume one global retry budget unit")
    p_incr.add_argument("--workspace", required=True)

    # set-spec-version
    p_spec = sub.add_parser("set-spec-version", help="Update spec version in state")
    p_spec.add_argument("--workspace", required=True)
    p_spec.add_argument("--version", required=True)

    args = parser.parse_args()

    if args.command == "read":
        state = read_state(args.workspace)
        print(json.dumps(state, ensure_ascii=False, indent=2))

    elif args.command == "transition":
        state = transition(args.workspace, args.event, args.detail)
        print(json.dumps({"status": "ok", "current_state": state["current_state"]}))

    elif args.command == "update-stage":
        state = update_stage_status(args.workspace, args.stage, args.status, args.run_id, args.eval_path)
        print(json.dumps({"status": "ok", "stage": args.stage, "stage_status": args.status}))

    elif args.command == "check-budget":
        budget = check_budget(args.workspace)
        print(json.dumps(budget))

    elif args.command == "increment-budget":
        state = increment_budget(args.workspace)
        print(json.dumps({"status": "ok", "global_retry_budget": state["global_retry_budget"]}))

    elif args.command == "set-spec-version":
        state = set_spec_version(args.workspace, args.version)
        print(json.dumps({"status": "ok", "spec_version": args.version}))

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
