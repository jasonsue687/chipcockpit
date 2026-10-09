#!/usr/bin/env python3
"""Read-only project snapshots for the local chip-flow dashboard.

The dashboard deliberately does not mutate workflow state.  It combines the
static flow snapshot, the recorded lifecycle/step state, and facts from the
workspace filesystem into one JSON-serialisable view.  When those sources do
not agree, the disagreement is returned as a consistency warning instead of
being silently repaired by a GET request.
"""
from __future__ import annotations

import json
import mimetypes
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


TERMINAL_STATUSES = {"done", "skipped", "done_on_disk"}
RECORDED_TERMINAL_STATUSES = {"done", "skipped"}
RUN_DIR_PATTERN = re.compile(r"run_\d+$")
INTERACTION_LIMIT = 10_000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _plugin_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read_yaml(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as handle:
        value = yaml.safe_load(handle)
    return default if value is None else value


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except json.JSONDecodeError:
        return default
    return default if value is None else value


def _read_jsonl(path: Path, last_n: int = 50) -> list[dict]:
    if not path.exists():
        return []
    records: list[dict] = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                value = {"invalid_record": line}
            if isinstance(value, dict):
                records.append(value)
    return records[-last_n:]


def resolve_workspace(workspace: str | Path | None, base_path: str | Path | None = None) -> Path:
    """Resolve an explicit workspace or discover one below the current project.

    Discovery prefers ``.chipflow`` and otherwise chooses the most recently
    modified ``.chipflow_*`` directory.  A workspace is recognised by either
    state/machine.yaml or state/flow_progress.yaml.
    """
    if workspace is not None:
        resolved = Path(workspace).expanduser().resolve()
        if not resolved.is_dir():
            raise FileNotFoundError(f"Workspace directory not found: {resolved}")
        return resolved

    base = Path(base_path or Path.cwd()).expanduser().resolve()
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
        raise FileNotFoundError(
            f"No chip-flow workspace found below {base}. "
            "Pass --workspace <path> explicitly."
        )
    return max(candidates, key=lambda candidate: candidate.stat().st_mtime).resolve()


def _looks_like_workspace(path: Path) -> bool:
    return path.is_dir() and (
        (path / "state" / "machine.yaml").is_file()
        or (path / "state" / "flow_progress.yaml").is_file()
    )


def resolve_workspace_file(workspace: str | Path, relative_path: str) -> Path:
    """Resolve a relative workspace file while preventing path traversal."""
    root = Path(workspace).resolve()
    requested = Path(relative_path)
    if requested.is_absolute():
        raise PermissionError("Absolute paths are not available through the dashboard")
    target = (root / requested).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise PermissionError("Path escapes the selected workspace") from exc
    return target


def _file_fact(workspace: Path, entry: dict, *, kind: str) -> dict:
    relative = str(entry.get("path", ""))
    fact = {
        "name": entry.get("name") or Path(relative).name or kind,
        "path": relative,
        "kind": kind,
        "required": bool(entry.get("required", False)),
        "exists": False,
        "is_file": False,
        "size": None,
        "modified_at": None,
        "mime_type": mimetypes.guess_type(relative)[0] or "application/octet-stream",
    }
    if not relative:
        return fact
    try:
        path = resolve_workspace_file(workspace, relative)
    except PermissionError:
        fact["invalid_path"] = True
        return fact
    fact["exists"] = path.exists()
    fact["is_file"] = path.is_file()
    if path.is_file():
        stat = path.stat()
        fact["size"] = stat.st_size
        fact["modified_at"] = datetime.fromtimestamp(
            stat.st_mtime, tz=timezone.utc
        ).isoformat()
        fact["view_url"] = f"/api/file?path={relative}"
    return fact


def _flow_source(workspace: Path) -> tuple[Path, str]:
    snapshot = workspace / "flow" / "flow_definition.yaml"
    if snapshot.is_file():
        return snapshot, "workspace_snapshot"
    template = _plugin_root() / "templates" / "flow_definition.yaml"
    if template.is_file():
        return template, "plugin_template"
    raise FileNotFoundError("No flow definition found in workspace or plugin templates")


def _collect_runs(workspace: Path, stage_id: str) -> list[dict]:
    stage_dir = workspace / "stages" / stage_id
    if not stage_dir.is_dir():
        return []
    runs: list[dict] = []
    run_dirs = sorted(
        [item for item in stage_dir.iterdir() if item.is_dir() and RUN_DIR_PATTERN.fullmatch(item.name)],
        key=lambda item: int(item.name.split("_")[1]),
        reverse=True,
    )
    for run_dir in run_dirs:
        meta = _read_yaml(run_dir / "_meta.yaml", {})
        eval_result = _read_yaml(run_dir / "eval_result.yaml", None)
        files = [item for item in run_dir.rglob("*") if item.is_file()]
        runs.append({
            "run_id": run_dir.name,
            "path": str(run_dir.relative_to(workspace)),
            "status": meta.get("status") if isinstance(meta, dict) else None,
            "parent_run": meta.get("parent_run") if isinstance(meta, dict) else None,
            "spec_version": meta.get("spec_version") if isinstance(meta, dict) else None,
            "timestamp": (
                meta.get("timestamp") or meta.get("created_at")
                if isinstance(meta, dict)
                else None
            ),
            "checkpoint": meta.get("checkpoint") if isinstance(meta, dict) else None,
            "eval_overall": eval_result.get("overall") if isinstance(eval_result, dict) else None,
            "file_count": len(files),
        })
    return runs


def _collect_node_logs(
    workspace: Path,
    stage_id: str,
    step_name: str,
    stage_runs: list[dict],
) -> list[dict]:
    """Return canonical and run-scoped log files associated with one step."""
    candidates: list[tuple[str, str]] = [
        (f"stages/{stage_id}/logs/{step_name}.log", "节点日志"),
    ]
    for run in stage_runs:
        run_id = run["run_id"]
        candidates.extend(
            (f"stages/{stage_id}/{run_id}/logs/{step_name}{suffix}", f"{run_id} 节点日志")
            for suffix in (".log", ".out", ".err")
        )
        candidates.extend(
            (f"stages/{stage_id}/{run_id}/scripts/{step_name}{suffix}", f"{run_id} 执行日志")
            for suffix in (".log", ".out", ".err")
        )

    logs: list[dict] = []
    seen: set[str] = set()
    for relative, name in candidates:
        if relative in seen:
            continue
        seen.add(relative)
        fact = _file_fact(
            workspace,
            {"name": name, "path": relative, "required": False},
            kind="log",
        )
        # Always expose the canonical expected log. Run-scoped candidates are
        # only useful when they actually exist.
        if fact["exists"] or not logs:
            logs.append(fact)
    return logs


def _status_from_facts(
    recorded_status: str,
    required_outputs: list[dict],
    warnings: list[dict],
    step_id: str,
) -> str:
    if not required_outputs:
        return recorded_status
    present = [fact["exists"] and fact["is_file"] for fact in required_outputs]
    all_present = all(present)
    missing = [fact["path"] for fact in required_outputs if not (fact["exists"] and fact["is_file"])]

    if recorded_status == "done" and missing:
        warnings.append({
            "code": "recorded_done_missing_output",
            "step_id": step_id,
            "message": f"{step_id} 记录为 {recorded_status}，但缺少必需输出：{', '.join(missing)}",
        })
        return "inconsistent"
    if recorded_status not in RECORDED_TERMINAL_STATUSES and all_present:
        warnings.append({
            "code": "output_present_progress_not_done",
            "step_id": step_id,
            "message": f"{step_id} 的必需输出已存在，但记录状态仍为 {recorded_status}",
        })
        return "done_on_disk"
    return recorded_status


def _derive_action(current: dict | None, progress_exists: bool) -> tuple[str, str | None]:
    if not progress_exists:
        return "not_started", "步级流程尚未启动；当前展示插件流程模板"
    if current is None:
        return "flow_complete", None

    status = current["status"]
    if status == "failed":
        return "blocked", "节点已记录失败，等待调度器决定 retry 或 rollback"
    if status == "inconsistent":
        return "inconsistent", "记录状态与必需输出不一致"
    if status == "running":
        return "running", "节点记录为 running；请检查执行进程或中断恢复状态"
    if status == "awaiting_human" or current["executor"]["type"] == "human":
        return "await_human", current.get("instruction") or "等待人工确认"

    missing = [
        fact["path"]
        for fact in current["inputs"]
        if fact["required"] and not (fact["exists"] and fact["is_file"])
    ]
    if missing:
        return "blocked_inputs", f"缺少必需输入：{', '.join(missing)}"
    return "ready", None


def build_snapshot(workspace: str | Path) -> dict:
    """Build the authoritative, read-only dashboard snapshot."""
    workspace = Path(workspace).expanduser().resolve()
    if not workspace.is_dir():
        raise FileNotFoundError(f"Workspace directory not found: {workspace}")

    flow_path, flow_source = _flow_source(workspace)
    flow = _read_yaml(flow_path, {})
    machine = _read_yaml(workspace / "state" / "machine.yaml", {})
    progress_path = workspace / "state" / "flow_progress.yaml"
    progress_exists = progress_path.is_file()
    progress = _read_yaml(progress_path, {"steps": {}})
    progress_steps = progress.get("steps", {}) if isinstance(progress, dict) else {}
    machine_stages = machine.get("stages", {}) if isinstance(machine, dict) else {}
    interaction_records = _read_jsonl(
        workspace / "state" / "agent_interactions.jsonl",
        last_n=INTERACTION_LIMIT,
    )
    interactions_by_step: dict[str, list[dict]] = {}
    for record in interaction_records:
        step_id = record.get("step_id")
        if isinstance(step_id, str):
            interactions_by_step.setdefault(step_id, []).append(record)
    warnings: list[dict] = []
    stages: list[dict] = []
    flat_nodes: list[dict] = []

    for stage_index, stage_def in enumerate(flow.get("stages", [])):
        stage_id = stage_def["id"]
        stage_nodes: list[dict] = []
        stage_runs = _collect_runs(workspace, stage_id)
        for step_index, step_def in enumerate(stage_def.get("steps", [])):
            step_id = f"{stage_id}.{step_def['id']}"
            recorded = progress_steps.get(step_id, {})
            recorded_status = recorded.get("status", "pending")
            inputs = [
                _file_fact(workspace, entry, kind="input")
                for entry in (step_def.get("inputs") or [])
            ]
            outputs = [
                _file_fact(workspace, entry, kind="output")
                for entry in (step_def.get("outputs") or [])
            ]
            required_outputs = [fact for fact in outputs if fact["required"]]
            status = _status_from_facts(
                recorded_status, required_outputs, warnings, step_id
            )

            related: list[dict] = []
            for kind, key in (("decision", "decisions"), ("report", "report")):
                relative = step_def.get(key)
                if relative and all(item["path"] != relative for item in inputs + outputs):
                    related.append(
                        _file_fact(
                            workspace,
                            {"name": Path(relative).name, "path": relative, "required": False},
                            kind=kind,
                        )
                    )

            executor = step_def.get("executor", {}) or {}
            node = {
                "id": step_id,
                "stage": stage_id,
                "stage_name": stage_def.get("name", stage_id),
                "stage_index": stage_index,
                "step": step_def["id"],
                "step_index": step_index,
                "name": step_def.get("name", step_def["id"]),
                "executor": {
                    "type": executor.get("type", "unknown"),
                    "ref": executor.get("ref"),
                },
                "gate": bool(step_def.get("gate", False)),
                "instruction": step_def.get("instruction"),
                "template": step_def.get("template"),
                "recorded_status": recorded_status,
                "status": status,
                "updated_at": recorded.get("updated_at"),
                "note": recorded.get("note", ""),
                "inputs": inputs,
                "outputs": outputs,
                "related_files": related,
                "logs": _collect_node_logs(
                    workspace, stage_id, step_def["id"], stage_runs
                ),
                "interactions": interactions_by_step.get(step_id, []),
                "runs": stage_runs,
            }
            stage_nodes.append(node)
            flat_nodes.append(node)

        counts: dict[str, int] = {}
        for node in stage_nodes:
            counts[node["status"]] = counts.get(node["status"], 0) + 1
        terminal_count = sum(
            1 for node in stage_nodes if node["status"] in TERMINAL_STATUSES
        )
        machine_stage = machine_stages.get(stage_id, {})
        stages.append({
            "id": stage_id,
            "name": stage_def.get("name", stage_id),
            "index": stage_index,
            "recorded_status": machine_stage.get("status", "pending"),
            "current_run": machine_stage.get("current_run"),
            "retry_count": machine_stage.get("retry_count", 0),
            "last_eval": machine_stage.get("last_eval"),
            "total_steps": len(stage_nodes),
            "done_steps": terminal_count,
            "percent": round(100 * terminal_count / len(stage_nodes), 1) if stage_nodes else 0.0,
            "counts": counts,
            "runs": stage_runs,
            "nodes": stage_nodes,
        })

    current = next(
        (node for node in flat_nodes if node["status"] not in TERMINAL_STATUSES),
        None,
    ) if progress_exists else None
    action, blocker = _derive_action(current, progress_exists)
    total_steps = len(flat_nodes)
    done_steps = sum(1 for node in flat_nodes if node["status"] in TERMINAL_STATUSES)
    machine_state = machine.get("current_state") if isinstance(machine, dict) else None
    budget = machine.get("global_retry_budget", {}) if isinstance(machine, dict) else {}
    spec_version = (
        machine.get("spec_version") if isinstance(machine, dict) else None
    ) or (
        _read_yaml(workspace / "spec" / "global_spec.yaml", {}).get("spec_version")
    )

    if progress_exists:
        defined_ids = {node["id"] for node in flat_nodes}
        extra_ids = sorted(set(progress_steps) - defined_ids)
        missing_ids = sorted(defined_ids - set(progress_steps))
        if extra_ids:
            warnings.append({
                "code": "progress_has_unknown_steps",
                "message": f"进度文件包含流程快照中不存在的节点：{', '.join(extra_ids)}",
            })
        if missing_ids:
            warnings.append({
                "code": "progress_missing_steps",
                "message": f"进度文件缺少节点记录：{', '.join(missing_ids)}",
            })

    return {
        "readonly": True,
        "generated_at": _now(),
        "project": {
            "name": workspace.name,
            "workspace": str(workspace),
        },
        "flow": {
            "name": flow.get("flow"),
            "version": flow.get("version"),
            "source": flow_source,
            "source_path": str(flow_path),
            "progress_started": progress_exists,
            "progress_updated_at": progress.get("updated_at") if isinstance(progress, dict) else None,
        },
        "interaction_ledger": {
            "path": "state/agent_interactions.jsonl",
            "loaded_records": len(interaction_records),
            "recording_mode": "explicit_summaries",
            "sync_status": _read_json(
                workspace / "state" / "claude_session_sync.json",
                None,
            ),
        },
        "summary": {
            "lifecycle": machine_state or "UNRECORDED",
            "spec_version": spec_version,
            "total_steps": total_steps,
            "done_steps": done_steps,
            "percent": round(100 * done_steps / total_steps, 1) if total_steps else 0.0,
            "current_step_id": current["id"] if current else None,
            "current_stage": current["stage"] if current else None,
            "current_step_name": current["name"] if current else None,
            "action": action,
            "blocker": blocker,
            "retry_budget": {
                "used": budget.get("used", 0),
                "max": budget.get("max", 0),
                "remaining": max(0, budget.get("max", 0) - budget.get("used", 0)),
            },
        },
        "warnings": warnings,
        "stages": stages,
        "decisions": _read_jsonl(workspace / "state" / "decisions.jsonl"),
    }


def get_node(snapshot: dict, step_id: str) -> dict | None:
    for stage in snapshot.get("stages", []):
        for node in stage.get("nodes", []):
            if node.get("id") == step_id:
                return node
    return None
