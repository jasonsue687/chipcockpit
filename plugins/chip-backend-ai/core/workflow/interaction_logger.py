#!/usr/bin/env python3
"""Append-only, workspace-local interaction records for chip-flow nodes.

The ledger stores explicit, user-visible summaries such as the request, plan,
decision evidence, tool result, approval, or error for a specific flow step. It
is not a capture mechanism for hidden model reasoning, system prompts, secrets,
or complete proprietary report bodies.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROLES = ("user", "assistant", "tool", "system")
KINDS = ("prompt", "plan", "decision", "result", "approval", "note", "error")
MAX_CONTENT_CHARS = 50_000


def _ledger_path(workspace: str | Path) -> Path:
    workspace_path = Path(workspace).expanduser().resolve()
    state_dir = workspace_path / "state"
    if not state_dir.is_dir():
        raise FileNotFoundError(
            f"Workspace state directory not found: {state_dir}"
        )
    return state_dir / "agent_interactions.jsonl"


def _validate_text(value: str, field: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{field} must not be empty")
    return value


def log_interaction(
    workspace: str | Path,
    step_id: str,
    role: str,
    kind: str,
    content: str,
    *,
    run_id: str | None = None,
    spec_version: str | None = None,
    model: str | None = None,
    references: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Append one explicit interaction summary to the workspace ledger."""
    step_id = _validate_text(step_id, "step_id")
    if "." not in step_id:
        raise ValueError("step_id must use <stage>.<step> format")
    if role not in ROLES:
        raise ValueError(f"role must be one of: {', '.join(ROLES)}")
    if kind not in KINDS:
        raise ValueError(f"kind must be one of: {', '.join(KINDS)}")
    content = _validate_text(content, "content")
    if len(content) > MAX_CONTENT_CHARS:
        raise ValueError(
            f"content exceeds the {MAX_CONTENT_CHARS}-character safety limit"
        )

    clean_references = [
        item.strip() for item in (references or []) if item and item.strip()
    ]
    stage, step = step_id.split(".", 1)
    record: dict[str, Any] = {
        "ts": timestamp or datetime.now(timezone.utc).isoformat(),
        "step_id": step_id,
        "stage": stage,
        "step": step,
        "role": role,
        "kind": kind,
        "content": content,
    }
    optional = {
        "run_id": run_id,
        "spec_version": spec_version,
        "model": model,
        "references": clean_references or None,
        "metadata": metadata or None,
    }
    record.update({key: value for key, value in optional.items() if value is not None})

    ledger = _ledger_path(workspace)
    with open(ledger, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def read_interactions(
    workspace: str | Path,
    *,
    step_id: str | None = None,
    last_n: int | None = None,
) -> list[dict[str, Any]]:
    """Read valid records, optionally filtered to one flow step."""
    ledger = _ledger_path(workspace)
    if not ledger.exists():
        return []

    records: list[dict[str, Any]] = []
    with open(ledger, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            value = json.loads(line)
            if isinstance(value, dict) and (
                step_id is None or value.get("step_id") == step_id
            ):
                records.append(value)
    return records[-last_n:] if last_n is not None else records


def _read_content(args: argparse.Namespace) -> str:
    if args.content is not None:
        return args.content
    return Path(args.content_file).read_text(encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Record explicit, auditable chip-flow model interactions"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    log_parser = sub.add_parser("log", help="Append one interaction summary")
    log_parser.add_argument("--workspace", required=True)
    log_parser.add_argument("--step", required=True, dest="step_id")
    log_parser.add_argument("--role", required=True, choices=ROLES)
    log_parser.add_argument("--kind", required=True, choices=KINDS)
    content_group = log_parser.add_mutually_exclusive_group(required=True)
    content_group.add_argument("--content")
    content_group.add_argument("--content-file")
    log_parser.add_argument("--run-id")
    log_parser.add_argument("--spec-version")
    log_parser.add_argument("--model")
    log_parser.add_argument("--reference", action="append", default=[])
    log_parser.add_argument(
        "--metadata-json",
        help="Optional compact JSON object with non-sensitive structured metadata",
    )
    log_parser.add_argument(
        "--timestamp",
        help="Optional source timestamp (defaults to current UTC time)",
    )

    read_parser = sub.add_parser("read", help="Read interaction summaries")
    read_parser.add_argument("--workspace", required=True)
    read_parser.add_argument("--step", dest="step_id")
    read_parser.add_argument("--last-n", type=int)

    args = parser.parse_args()
    try:
        if args.command == "log":
            metadata = json.loads(args.metadata_json) if args.metadata_json else None
            if metadata is not None and not isinstance(metadata, dict):
                raise ValueError("metadata-json must decode to a JSON object")
            record = log_interaction(
                args.workspace,
                args.step_id,
                args.role,
                args.kind,
                _read_content(args),
                run_id=args.run_id,
                spec_version=args.spec_version,
                model=args.model,
                references=args.reference,
                metadata=metadata,
                timestamp=args.timestamp,
            )
            result: Any = {"status": "ok", "record": record}
        else:
            if args.last_n is not None and args.last_n < 1:
                raise ValueError("last-n must be greater than zero")
            result = read_interactions(
                args.workspace,
                step_id=args.step_id,
                last_n=args.last_n,
            )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
