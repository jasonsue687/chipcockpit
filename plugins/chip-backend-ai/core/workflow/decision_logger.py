#!/usr/bin/env python3
"""Append-only decision log for the orchestrator.

Writes to state/decisions.jsonl — one JSON line per orchestrator decision.
This provides a complete audit trail of all scheduling, dispatch, retry,
rollback, and spec revision decisions.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def log_decision(
    workspace: str | Path,
    from_state: str,
    to_state: str,
    action: str,
    reason: str,
    target: str | None = None,
    run_id: str | None = None,
) -> dict:
    """Append a decision record to decisions.jsonl.

    Args:
        workspace: Workspace root path.
        from_state: State before this decision.
        to_state: State after this decision.
        action: Decision action (dispatch, retry, rollback, revise_spec, complete, abort).
        reason: Human-readable reason for this decision.
        target: Target agent name (e.g., "floorplan_agent").
        run_id: Associated run ID (e.g., "run_001").

    Returns:
        The decision record that was logged.
    """
    workspace = Path(workspace)
    log_file = workspace / "state" / "decisions.jsonl"

    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "from": from_state,
        "to": to_state,
        "action": action,
        "reason": reason,
    }

    if target is not None:
        record["target"] = target
    if run_id is not None:
        record["run_id"] = run_id

    with open(log_file, "a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    return record


def read_decisions(workspace: str | Path, last_n: int | None = None) -> list[dict]:
    """Read decision records from decisions.jsonl.

    Args:
        workspace: Workspace root path.
        last_n: If set, return only the last N records.

    Returns:
        List of decision records (dicts).
    """
    workspace = Path(workspace)
    log_file = workspace / "state" / "decisions.jsonl"

    if not log_file.exists():
        return []

    records = []
    with open(log_file) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    if last_n is not None:
        records = records[-last_n:]

    return records


def main():
    parser = argparse.ArgumentParser(description="Decision log operations")
    sub = parser.add_subparsers(dest="command")

    # log
    p_log = sub.add_parser("log", help="Append a decision")
    p_log.add_argument("--workspace", required=True)
    p_log.add_argument("--from-state", required=True)
    p_log.add_argument("--to-state", required=True)
    p_log.add_argument("--action", required=True)
    p_log.add_argument("--reason", required=True)
    p_log.add_argument("--target", default=None)
    p_log.add_argument("--run-id", default=None)

    # read
    p_read = sub.add_parser("read", help="Read decisions")
    p_read.add_argument("--workspace", required=True)
    p_read.add_argument("--last-n", type=int, default=None)

    args = parser.parse_args()

    if args.command == "log":
        record = log_decision(
            args.workspace, args.from_state, args.to_state,
            args.action, args.reason, args.target, args.run_id,
        )
        print(json.dumps({"status": "ok", "record": record}, ensure_ascii=False))

    elif args.command == "read":
        records = read_decisions(args.workspace, args.last_n)
        print(json.dumps(records, ensure_ascii=False, indent=2))

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
