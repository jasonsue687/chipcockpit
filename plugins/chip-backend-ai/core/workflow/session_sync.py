#!/usr/bin/env python3
"""Synchronize visible Claude Code conversation text into flow-node history.

Only explicit user messages and assistant ``text`` blocks are imported. Thinking
blocks, tool results, system events, and hidden prompts are never copied into the
workspace ledger.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from interaction_logger import log_interaction


TERMINAL_STATUSES = {"done", "skipped"}
MAX_VISIBLE_CHARS = 12_000
SOURCE_NAME = "claude_transcript"
FLOW_COMMAND_HINTS = (
    "flow_loader.py",
    "run_eda_script.py",
    "render_tcl.py",
    "gen_decisions.py",
    "version_check.py",
    "router.py parse-report",
)
SYSTEM_BLOCK_PATTERN = re.compile(
    r"<(system-reminder|local-command-caveat)>.*?</\1>",
    re.DOTALL | re.IGNORECASE,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_yaml(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    with open(path, encoding="utf-8") as handle:
        value = yaml.safe_load(handle)
    return default if value is None else value


def _looks_like_workspace(path: Path) -> bool:
    return path.is_dir() and (path / "state" / "machine.yaml").is_file()


def discover_workspace(cwd: str | Path) -> Path | None:
    """Find the current project's workspace without creating or mutating one."""
    base = Path(cwd).expanduser().resolve()
    if _looks_like_workspace(base):
        return base
    exact = base / ".chipflow"
    if _looks_like_workspace(exact):
        return exact.resolve()
    candidates = [
        candidate
        for candidate in base.glob(".chipflow_*")
        if _looks_like_workspace(candidate)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.stat().st_mtime).resolve()


def _load_transcript(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                # A hook can observe the file while Claude is appending. The
                # incomplete line will be retried on the next event.
                continue
            if isinstance(value, dict):
                value["_line_number"] = line_number
                records.append(value)
    return records


def _flow_nodes(workspace: Path) -> tuple[list[str], dict[str, str], str | None]:
    progress = _read_yaml(workspace / "state" / "flow_progress.yaml", {})
    steps = progress.get("steps", {}) if isinstance(progress, dict) else {}
    node_ids = list(steps)
    executors: dict[str, str] = {}

    flow = _read_yaml(workspace / "flow" / "flow_definition.yaml", {})
    for stage in flow.get("stages", []) if isinstance(flow, dict) else []:
        stage_id = stage.get("id")
        for step in stage.get("steps", []) or []:
            step_id = f"{stage_id}.{step.get('id')}"
            if step_id not in node_ids:
                node_ids.append(step_id)
            executor = step.get("executor", {}) or {}
            executors[step_id] = executor.get("type", "unknown")

    current = next(
        (
            step_id
            for step_id in node_ids
            if (steps.get(step_id, {}) or {}).get("status", "pending")
            not in TERMINAL_STATUSES
        ),
        None,
    )
    return node_ids, executors, current


def _context_text(
    record: dict[str, Any], *, include_tool_results: bool = False
) -> str:
    """Return fields useful for node mapping, excluding thinking blocks."""
    if record.get("isMeta"):
        return ""
    message = record.get("message") or {}
    content = message.get("content")
    parts: list[str] = []
    if isinstance(content, str):
        parts.append(content)
    elif isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "text":
                parts.append(str(block.get("text", "")))
            elif block_type == "tool_use":
                tool_input = block.get("input", {}) or {}
                if isinstance(tool_input, dict):
                    command = tool_input.get("command")
                    if isinstance(command, str) and any(
                        hint in command for hint in FLOW_COMMAND_HINTS
                    ):
                        parts.append(command)
                    else:
                        for key in ("file_path", "path"):
                            value = tool_input.get(key)
                            if isinstance(value, str):
                                parts.append(value)
            elif block_type == "tool_result" and include_tool_results:
                result = block.get("content", "")
                parts.append(
                    result
                    if isinstance(result, str)
                    else json.dumps(result, ensure_ascii=False)
                )
    return "\n".join(parts)


def _extract_node_ids(text: str, node_ids: list[str]) -> list[str]:
    matches: list[tuple[int, str]] = []
    for node_id in node_ids:
        match = re.search(
            rf"(?<![A-Za-z0-9_]){re.escape(node_id)}(?![A-Za-z0-9_])",
            text,
        )
        if match:
            matches.append((match.start(), node_id))
            continue

        stage, step = node_id.split(".", 1)
        path_match = re.search(
            rf"stages/{re.escape(stage)}/(?:run_\d+/)?"
            rf"(?:scripts|logs|reports|artifacts)/{re.escape(step)}(?:[./_]|$)",
            text,
        )
        if path_match:
            matches.append((path_match.start(), node_id))
            continue

        if step.endswith("_eval"):
            gate_match = re.search(
                rf"{re.escape(stage)}[^\n]{{0,80}}(?:gate|评估)",
                text,
                re.IGNORECASE,
            )
            if gate_match:
                matches.append((gate_match.start(), node_id))
    return [node_id for _, node_id in sorted(matches)]


def _flow_result_parents(records: list[dict[str, Any]]) -> set[str]:
    """Identify tool results whose command can safely reveal the offered node."""
    parents: set[str] = set()
    for record in records:
        if record.get("type") != "assistant" or not record.get("uuid"):
            continue
        message = record.get("message") or {}
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            command = json.dumps(block.get("input", {}), ensure_ascii=False)
            if "flow_loader.py next" in command:
                parents.add(str(record["uuid"]))
    return parents


def _visible_messages(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        record_type = record.get("type")
        message = record.get("message") or {}
        content = message.get("content")
        if record_type == "user" and isinstance(content, str):
            messages.append({
                "index": index,
                "block": 0,
                "role": "user",
                "content": content,
                "record": record,
            })
        elif record_type == "assistant" and isinstance(content, list):
            for block_index, block in enumerate(content):
                if isinstance(block, dict) and block.get("type") == "text":
                    messages.append({
                        "index": index,
                        "block": block_index,
                        "role": "assistant",
                        "content": str(block.get("text", "")),
                        "record": record,
                    })
    return messages


def _clean_visible_text(text: str) -> str:
    text = SYSTEM_BLOCK_PATTERN.sub("", text).strip()
    if len(text) > MAX_VISIBLE_CHARS:
        text = text[:MAX_VISIBLE_CHARS].rstrip() + "\n\n[内容过长，已截断]"
    return text


def _turn_bounds(
    messages: list[dict[str, Any]], message_index: int
) -> tuple[int, int]:
    current = messages[message_index]
    user_positions = [
        item["index"] for item in messages if item["role"] == "user"
    ]
    starts = [position for position in user_positions if position <= current["index"]]
    start = starts[-1] if starts else 0
    ends = [position for position in user_positions if position > start]
    end = ends[0] if ends else 10**12
    return start, end


def _choose_node(
    message: dict[str, Any],
    message_position: int,
    messages: list[dict[str, Any]],
    node_events: list[tuple[int, str]],
    node_ids: list[str],
    current_node: str | None,
) -> str | None:
    is_last_visible = message_position == len(messages) - 1
    asks_for_human = bool(
        re.search(r"继续|确认|批准|审批|是否|请回复|\?$|？$", message["content"])
    )
    if is_last_visible and current_node and asks_for_human:
        return current_node

    direct = _extract_node_ids(message["content"], node_ids)
    if direct:
        return direct[-1]

    start, end = _turn_bounds(messages, message_position)
    turn_events = [event for event in node_events if start <= event[0] < end]
    if message["role"] == "user":
        following = [event for event in turn_events if event[0] >= message["index"]]
        if following:
            return following[0][1]
        return current_node if end == 10**12 else None

    preceding = [event for event in turn_events if event[0] <= message["index"]]
    following = [event for event in turn_events if event[0] > message["index"]]
    if preceding:
        selected = preceding[-1][1]
    elif following:
        selected = following[0][1]
    else:
        selected = None

    if selected is None and end == 10**12:
        return current_node
    return selected


def _kind(role: str, content: str, executor: str | None) -> str:
    compact = content.strip().lower()
    if role == "user":
        approval_words = (
            "批准",
            "确认",
            "继续",
            "同意",
            "approve",
            "approved",
            "proceed",
        )
        if executor == "human" and any(
            word in compact for word in approval_words
        ):
            return "approval"
        return "prompt"
    if any(word in compact for word in ("失败", "错误", "阻塞", "error", "failed")):
        return "error"
    if any(word in compact for word in ("决策", "选择", "基于", "recommendation")):
        return "decision"
    if any(word in compact for word in ("下一步", "首先", "我将", "现在", "开始执行")):
        return "plan"
    if re.search(r"继续|确认|批准|审批|是否|请回复|\?$|？$", content):
        return "prompt"
    return "result"


def _references(content: str, workspace: Path) -> list[str]:
    references: list[str] = []
    root = str(workspace)
    pattern = (
        r"(?:/[^\s`'\"，。；：]+|"
        r"(?:state|stages|spec|inputs|flow)/[^\s`'\"，。；：]+)"
    )
    for match in re.findall(pattern, content):
        candidate = match.rstrip(")]}>.,;:")
        if candidate.startswith(root + "/"):
            candidate = candidate[len(root) + 1:]
        if candidate.startswith(
            ("state/", "stages/", "spec/", "inputs/", "flow/")
        ):
            if candidate not in references:
                references.append(candidate)
        if len(references) >= 8:
            break
    return references


def _existing_source_keys(workspace: Path) -> set[str]:
    ledger = workspace / "state" / "agent_interactions.jsonl"
    if not ledger.is_file():
        return set()
    keys: set[str] = set()
    with open(ledger, encoding="utf-8") as handle:
        for line in handle:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            metadata = value.get("metadata", {}) if isinstance(value, dict) else {}
            if (
                metadata.get("source") == SOURCE_NAME
                and metadata.get("source_key")
            ):
                keys.add(str(metadata["source_key"]))
    return keys


def sync_transcript(
    workspace: str | Path,
    transcript_path: str | Path,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Import visible transcript messages and return a structured summary."""
    workspace_path = Path(workspace).expanduser().resolve()
    transcript = Path(transcript_path).expanduser().resolve()
    if not _looks_like_workspace(workspace_path):
        raise FileNotFoundError(f"Invalid chip-flow workspace: {workspace_path}")
    if not transcript.is_file():
        raise FileNotFoundError(f"Claude transcript not found: {transcript}")

    node_ids, executors, current_node = _flow_nodes(workspace_path)
    if not node_ids:
        return {"status": "no_flow_progress", "added": 0, "preview": []}

    records = _load_transcript(transcript)
    messages = _visible_messages(records)
    flow_result_parents = _flow_result_parents(records)
    node_events: list[tuple[int, str]] = []
    for index, record in enumerate(records):
        include_result = str(record.get("parentUuid")) in flow_result_parents
        mapping_text = _context_text(
            record,
            include_tool_results=include_result,
        )
        for node_id in _extract_node_ids(mapping_text, node_ids):
            if not node_events or node_events[-1] != (index, node_id):
                node_events.append((index, node_id))

    existing_keys = _existing_source_keys(workspace_path)
    preview: list[dict[str, Any]] = []
    added = 0
    skipped_unmapped = 0
    for position, message in enumerate(messages):
        content = _clean_visible_text(message["content"])
        if not content:
            continue
        node_id = _choose_node(
            message,
            position,
            messages,
            node_events,
            node_ids,
            current_node,
        )
        if node_id is None:
            skipped_unmapped += 1
            continue

        record = message["record"]
        session_id = str(record.get("sessionId") or "unknown-session")
        event_id = str(
            record.get("uuid") or f"line-{record.get('_line_number')}"
        )
        source_key = f"{session_id}:{event_id}:{message['block']}"
        if source_key in existing_keys:
            continue

        context = _context_text(record)
        run_match = re.search(r"run_\d+", context)
        item = {
            "step_id": node_id,
            "role": message["role"],
            "kind": _kind(message["role"], content, executors.get(node_id)),
            "content": content,
            "timestamp": record.get("timestamp") or _now(),
            "model": (record.get("message") or {}).get("model"),
            "run_id": run_match.group(0) if run_match else None,
            "references": _references(content, workspace_path),
            "metadata": {
                "source": SOURCE_NAME,
                "source_key": source_key,
                "session_id": session_id,
            },
        }
        preview.append({
            "step_id": item["step_id"],
            "role": item["role"],
            "kind": item["kind"],
            "content": content[:160],
        })
        if dry_run:
            continue
        log_interaction(
            workspace_path,
            item["step_id"],
            item["role"],
            item["kind"],
            item["content"],
            run_id=item["run_id"],
            model=item["model"],
            references=item["references"],
            metadata=item["metadata"],
            timestamp=item["timestamp"],
        )
        existing_keys.add(source_key)
        added += 1

    result = {
        "status": "ok",
        "workspace": str(workspace_path),
        "transcript": str(transcript),
        "added": len(preview) if dry_run else added,
        "skipped_unmapped": skipped_unmapped,
        "dry_run": dry_run,
        "preview": preview,
    }
    if not dry_run:
        state = {
            "last_sync_at": _now(),
            "session_id": records[-1].get("sessionId") if records else None,
            "transcript": transcript.name,
            "added": added,
        }
        state_path = workspace_path / "state" / "claude_session_sync.json"
        temp_path = state_path.with_suffix(".json.tmp")
        temp_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(state_path)
    return result


def _hook_mode() -> int:
    try:
        payload = json.load(sys.stdin)
        workspace = discover_workspace(payload.get("cwd") or Path.cwd())
        transcript = payload.get("transcript_path")
        if workspace is not None and transcript:
            sync_transcript(workspace, transcript)
        print(json.dumps({"continue": True, "suppressOutput": True}))
        return 0
    except Exception as exc:  # Hooks must not block the user's Claude session.
        print(f"chip-flow session sync failed: {exc}", file=sys.stderr)
        return 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sync visible Claude Code messages into chip-flow node history"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("hook", help="Read a Claude hook payload from stdin")
    sync_parser = sub.add_parser("sync", help="Synchronize one transcript")
    sync_parser.add_argument("--workspace", required=True)
    sync_parser.add_argument("--transcript", required=True)
    sync_parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.command == "hook":
        sys.exit(_hook_mode())
    try:
        result = sync_transcript(
            args.workspace,
            args.transcript,
            dry_run=args.dry_run,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (FileNotFoundError, OSError, ValueError, yaml.YAMLError) as exc:
        print(
            json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
