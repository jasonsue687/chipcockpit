#!/usr/bin/env python3
"""Workspace initialization and management for chip backend design flows.

Creates and manages the standard workspace directory structure:

    workspace/
    ├── spec/          (global_spec.yaml, stages/*.yaml, history/)
    ├── state/         (machine.yaml, decisions.jsonl, agent_interactions.jsonl)
    ├── stages/        (floorplan/, cts/, route/ with run_NNN/ dirs)
    └── checkpoints/   (DEF/DB snapshots)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

# Default stages in the chip backend flow
DEFAULT_STAGES = ["floorplan", "cts", "route"]

# Default hidden workspace name created under cwd when user doesn't specify one
DEFAULT_WORKSPACE_NAME = ".chipflow"

# Initial state machine snapshot
INITIAL_STATE = {
    "current_state": "INIT",
    "spec_version": None,
    "global_retry_budget": {"max": 15, "used": 0},
    "stages": {},
    "history": [],
}


def init_workspace(base_path: str, project_name: str, stages: list[str] | None = None) -> Path:
    """Create a new workspace with the standard directory structure.

    Args:
        base_path: Parent directory for the workspace.
        project_name: Name of the project (becomes the workspace folder name).
        stages: List of stage names. Defaults to ["floorplan", "cts", "route"].

    Returns:
        Path to the created workspace root.
    """
    stages = stages or DEFAULT_STAGES
    workspace = Path(base_path) / project_name

    if workspace.exists():
        raise FileExistsError(f"Workspace already exists: {workspace}")

    # spec/
    (workspace / "spec" / "stages").mkdir(parents=True)
    (workspace / "spec" / "history").mkdir(parents=True)

    # state/
    state_dir = workspace / "state"
    state_dir.mkdir(parents=True)

    # Write initial machine.yaml
    initial_state = dict(INITIAL_STATE)
    initial_state["stages"] = {
        stage: {
            "status": "pending",
            "current_run": None,
            "retry_count": 0,
            "last_eval": None,
        }
        for stage in stages
    }
    with open(state_dir / "machine.yaml", "w") as f:
        yaml.dump(initial_state, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    # Empty decisions log
    (state_dir / "decisions.jsonl").touch()
    # Empty explicit model/user/tool interaction ledger for per-node dashboard history
    (state_dir / "agent_interactions.jsonl").touch()

    # stages/
    for stage in stages:
        (workspace / "stages" / stage).mkdir(parents=True)

    # checkpoints/
    (workspace / "checkpoints").mkdir(parents=True)

    return workspace


def create_run_dir(
    workspace: str | Path,
    stage: str,
    run_id: str | None = None,
    parent_run: str | None = None,
) -> Path:
    """Create a new run directory under stages/<stage>/run_NNN/.

    Args:
        workspace: Path to the workspace root.
        stage: Stage name (e.g., "floorplan").
        run_id: Explicit run ID (e.g., "run_003"). If None, auto-increments.
        parent_run: Optional parent run reference (e.g., "route/run_001") recording
            that this run was spawned because of a downstream failure (cross-stage
            rollback). When provided, a _meta.yaml is written in the new run dir.

    Returns:
        Path to the created run directory.
    """
    workspace = Path(workspace)
    stage_dir = workspace / "stages" / stage

    if not stage_dir.exists():
        raise FileNotFoundError(f"Stage directory not found: {stage_dir}")

    if run_id is None:
        run_id = _next_run_id(stage_dir)

    run_dir = stage_dir / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "artifacts").mkdir()
    (run_dir / "reports").mkdir()

    if parent_run is not None:
        # Record rollback parentage so the orchestrator can index this run.
        # Field names follow templates/meta_template.yaml.
        meta = {
            "parent_run": parent_run,
            "stage": stage,
            "run_id": run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        with open(run_dir / "_meta.yaml", "w") as f:
            yaml.dump(meta, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    return run_dir


def get_latest_run(workspace: str | Path, stage: str) -> Path | None:
    """Return the path to the highest-numbered run_NNN directory for a stage.

    Returns None if no runs exist yet.
    """
    workspace = Path(workspace)
    stage_dir = workspace / "stages" / stage

    if not stage_dir.exists():
        return None

    runs = sorted(
        [d for d in stage_dir.iterdir() if d.is_dir() and re.match(r"run_\d+", d.name)],
        key=lambda d: int(d.name.split("_")[1]),
    )
    return runs[-1] if runs else None


def list_runs(workspace: str | Path, stage: str) -> list[str]:
    """List all run IDs for a stage, sorted ascending."""
    workspace = Path(workspace)
    stage_dir = workspace / "stages" / stage

    if not stage_dir.exists():
        return []

    return sorted(
        [d.name for d in stage_dir.iterdir() if d.is_dir() and re.match(r"run_\d+", d.name)],
        key=lambda name: int(name.split("_")[1]),
    )


def pick_default_workspace(base_path: Path, base_name: str = DEFAULT_WORKSPACE_NAME) -> Path:
    """Return a workspace path under ``base_path`` that doesn't yet exist.

    Tries ``base_name`` first; if taken, appends ``_2``, ``_3``, ... until a free
    name is found. Used when the caller doesn't pass --name and we need a stable,
    hidden default directory.
    """
    candidate = base_path / base_name
    if not candidate.exists():
        return candidate
    n = 2
    while True:
        candidate = base_path / f"{base_name}_{n}"
        if not candidate.exists():
            return candidate
        n += 1


def _next_run_id(stage_dir: Path) -> str:
    """Compute the next run_NNN ID for a stage directory."""
    existing = [
        int(d.name.split("_")[1])
        for d in stage_dir.iterdir()
        if d.is_dir() and re.match(r"run_\d+", d.name)
    ]
    next_num = max(existing, default=0) + 1
    return f"run_{next_num:03d}"


def main():
    parser = argparse.ArgumentParser(description="Workspace management for chip backend flows")
    sub = parser.add_subparsers(dest="command")

    # init
    p_init = sub.add_parser("init", help="Initialize a new workspace")
    p_init.add_argument("--path", default=None, help="Parent directory for workspace (default: cwd)")
    p_init.add_argument("--name", default=None, help=f"Workspace dir name (default: {DEFAULT_WORKSPACE_NAME}, auto-suffixed if taken)")
    p_init.add_argument("--stages", nargs="*", default=None, help="Stage names (default: floorplan cts route)")

    # create-run
    p_run = sub.add_parser("create-run", help="Create a new run directory")
    p_run.add_argument("--workspace", required=True, help="Workspace root path")
    p_run.add_argument("--stage", required=True, help="Stage name")
    p_run.add_argument("--run-id", default=None, help="Explicit run ID (auto-increments if omitted)")
    p_run.add_argument("--parent-run", default=None, help="Parent run reference (e.g. route/run_001) recording rollback parentage")

    # latest-run
    p_latest = sub.add_parser("latest-run", help="Get the latest run for a stage")
    p_latest.add_argument("--workspace", required=True, help="Workspace root path")
    p_latest.add_argument("--stage", required=True, help="Stage name")

    args = parser.parse_args()

    if args.command == "init":
        base = Path(args.path).resolve() if args.path else Path.cwd()
        if args.name:
            target = base / args.name
        else:
            target = pick_default_workspace(base)
        ws = init_workspace(str(target.parent), target.name, args.stages)
        print(json.dumps({"status": "ok", "workspace": str(ws)}))

    elif args.command == "create-run":
        run_dir = create_run_dir(args.workspace, args.stage, args.run_id, args.parent_run)
        print(json.dumps({"status": "ok", "run_dir": str(run_dir), "run_id": run_dir.name}))

    elif args.command == "latest-run":
        latest = get_latest_run(args.workspace, args.stage)
        print(json.dumps({"status": "ok", "latest_run": str(latest) if latest else None}))

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
