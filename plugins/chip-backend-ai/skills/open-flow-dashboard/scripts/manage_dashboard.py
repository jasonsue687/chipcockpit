#!/usr/bin/env python3
"""Start, query, or stop a detached local ChipFlow dashboard server."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import socket
import subprocess
import sys
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


PLUGIN_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_DIR = PLUGIN_ROOT / "core" / "workflow"
SERVER_SCRIPT = WORKFLOW_DIR / "dashboard_server.py"
sys.path.insert(0, str(WORKFLOW_DIR))

from dashboard import resolve_workspace  # noqa: E402


_OWNED_PROCESSES: dict[int, subprocess.Popen] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _runtime_root(state_dir: str | Path | None = None) -> Path:
    root = (
        Path(state_dir).expanduser()
        if state_dir is not None
        else Path.home() / ".chip-backend-ai" / "dashboard"
    )
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _workspace_key(workspace: Path) -> str:
    digest = hashlib.sha256(str(workspace).encode("utf-8")).hexdigest()[:12]
    safe_name = "".join(
        char if char.isalnum() or char in "-_" else "-"
        for char in workspace.name
    )
    return f"{safe_name or 'workspace'}-{digest}"


def _state_path(workspace: Path, state_dir: str | Path | None = None) -> Path:
    return _runtime_root(state_dir) / f"{_workspace_key(workspace)}.json"


def _load_state(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _save_state(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _health(url: str, expected_workspace: Path, timeout: float = 0.4) -> bool:
    try:
        with urlopen(f"{url.rstrip('/')}/api/health", timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, json.JSONDecodeError):
        return False
    return (
        payload.get("status") == "ok"
        and payload.get("readonly") is True
        and payload.get("workspace") == str(expected_workspace)
    )


def _process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except (OSError, ValueError):
        return False
    return True


def _runtime_alive(runtime: dict, workspace: Path) -> bool:
    try:
        pid = int(runtime.get("pid", 0))
    except (TypeError, ValueError):
        return False
    url = runtime.get("url")
    return bool(url) and _process_exists(pid) and _health(str(url), workspace)


def _choose_port(preferred: int) -> int:
    if not 0 <= preferred <= 65535:
        raise ValueError("port must be between 0 and 65535")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        # Match the HTTP server's reuse behavior so a clean restart can reclaim
        # the preferred port while an old connection is briefly in TIME_WAIT.
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", preferred))
        except OSError:
            sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_until_ready(url: str, workspace: Path, timeout: float = 8.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _health(url, workspace):
            return True
        time.sleep(0.1)
    return False


def start_dashboard(
    workspace: str | Path | None = None,
    project_dir: str | Path | None = None,
    port: int = 8765,
    open_browser: bool = True,
    state_dir: str | Path | None = None,
) -> dict:
    resolved = resolve_workspace(workspace, project_dir)
    state_path = _state_path(resolved, state_dir)
    existing = _load_state(state_path)
    if _runtime_alive(existing, resolved):
        opened = bool(webbrowser.open(existing["url"])) if open_browser else False
        return {
            "status": "already_running",
            "workspace": str(resolved),
            "url": existing["url"],
            "pid": existing["pid"],
            "readonly": True,
            "browser_opened": opened,
        }

    selected_port = _choose_port(port)
    url = f"http://127.0.0.1:{selected_port}/"
    log_path = state_path.with_suffix(".log")
    command = [
        sys.executable,
        str(SERVER_SCRIPT),
        "--workspace",
        str(resolved),
        "--host",
        "127.0.0.1",
        "--port",
        str(selected_port),
    ]
    with open(log_path, "a", encoding="utf-8") as log_handle:
        process = subprocess.Popen(
            command,
            cwd=str(Path(project_dir).resolve()) if project_dir else str(resolved),
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    _OWNED_PROCESSES[process.pid] = process

    if not _wait_until_ready(url, resolved):
        if _process_exists(process.pid):
            process.terminate()
            process.wait(timeout=3)
        _OWNED_PROCESSES.pop(process.pid, None)
        raise RuntimeError(f"Dashboard failed to become ready; see log: {log_path}")

    runtime = {
        "workspace": str(resolved),
        "url": url,
        "pid": process.pid,
        "started_at": _now(),
        "log": str(log_path),
        "readonly": True,
    }
    _save_state(state_path, runtime)
    opened = bool(webbrowser.open(url)) if open_browser else False
    return {
        "status": "started",
        **runtime,
        "browser_opened": opened,
    }


def dashboard_status(
    workspace: str | Path | None = None,
    project_dir: str | Path | None = None,
    state_dir: str | Path | None = None,
) -> dict:
    resolved = resolve_workspace(workspace, project_dir)
    runtime = _load_state(_state_path(resolved, state_dir))
    if _runtime_alive(runtime, resolved):
        return {
            "status": "running",
            "workspace": str(resolved),
            "url": runtime["url"],
            "pid": runtime["pid"],
            "readonly": True,
        }
    return {
        "status": "stopped",
        "workspace": str(resolved),
        "url": runtime.get("url"),
        "readonly": True,
    }


def _process_matches(pid: int, workspace: Path) -> bool:
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    command = result.stdout.strip()
    return "dashboard_server.py" in command and str(workspace) in command


def stop_dashboard(
    workspace: str | Path | None = None,
    project_dir: str | Path | None = None,
    state_dir: str | Path | None = None,
) -> dict:
    resolved = resolve_workspace(workspace, project_dir)
    state_path = _state_path(resolved, state_dir)
    runtime = _load_state(state_path)
    if not _runtime_alive(runtime, resolved):
        return {"status": "already_stopped", "workspace": str(resolved)}

    pid = int(runtime["pid"])
    if not _process_matches(pid, resolved):
        raise RuntimeError(
            "Refusing to stop a process that is not the recorded dashboard server"
        )
    os.kill(pid, signal.SIGTERM)
    owned_process = _OWNED_PROCESSES.pop(pid, None)
    if owned_process is not None:
        try:
            owned_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
    else:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and _process_exists(pid):
            time.sleep(0.1)
    runtime["stopped_at"] = _now()
    runtime["status"] = "stopped"
    _save_state(state_path, runtime)
    return {
        "status": "stopped",
        "workspace": str(resolved),
        "url": runtime.get("url"),
        "pid": pid,
    }


def _error_payload(exc: Exception) -> dict:
    return {
        "status": "error",
        "error": str(exc),
        "type": type(exc).__name__,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manage the local read-only ChipFlow dashboard"
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=["start", "status", "stop"],
        default="start",
    )
    parser.add_argument("--workspace", default=None, help="Explicit .chipflow workspace")
    parser.add_argument(
        "--project-dir",
        default=None,
        help="Project directory used for workspace discovery",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Preferred local port; falls back automatically",
    )
    parser.add_argument("--no-open", action="store_true", help="Do not open the system browser")
    parser.add_argument("--state-dir", default=None, help=argparse.SUPPRESS)
    args = parser.parse_args()

    try:
        if args.command == "start":
            result = start_dashboard(
                args.workspace,
                args.project_dir,
                args.port,
                open_browser=not args.no_open,
                state_dir=args.state_dir,
            )
        elif args.command == "status":
            result = dashboard_status(
                args.workspace, args.project_dir, args.state_dir
            )
        else:
            result = stop_dashboard(
                args.workspace, args.project_dir, args.state_dir
            )
    except (FileNotFoundError, PermissionError, RuntimeError, ValueError) as exc:
        print(json.dumps(_error_payload(exc), ensure_ascii=False))
        raise SystemExit(2) from exc
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
