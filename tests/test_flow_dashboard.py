#!/usr/bin/env python3
"""Tests for the local, read-only chip-flow dashboard."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import urlopen


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPO_ROOT / "plugins" / "chip-backend-ai"
WORKFLOW_DIR = PLUGIN_ROOT / "core" / "workflow"
MANAGER_DIR = PLUGIN_ROOT / "skills" / "open-flow-dashboard" / "scripts"
FLOW_DEFINITION = PLUGIN_ROOT / "templates" / "flow_definition.yaml"
FIXTURES = REPO_ROOT / "tests" / "flow_e2e" / "fixtures"
sys.path.insert(0, str(WORKFLOW_DIR))
sys.path.insert(0, str(MANAGER_DIR))

from dashboard import build_snapshot, get_node, resolve_workspace, resolve_workspace_file  # noqa: E402
from dashboard_server import create_server  # noqa: E402
from flow_loader import mark_step, start  # noqa: E402
from interaction_logger import log_interaction, read_interactions  # noqa: E402
from manage_dashboard import dashboard_status, start_dashboard, stop_dashboard  # noqa: E402
from session_sync import sync_transcript  # noqa: E402
from workspace import init_workspace  # noqa: E402


def make_workspace(root: Path, name: str = "demo") -> Path:
    workspace = init_workspace(str(root), name)
    shutil.copytree(FIXTURES / "inputs", workspace / "inputs")
    shutil.copy2(
        FIXTURES / "spec" / "global_spec.yaml",
        workspace / "spec" / "global_spec.yaml",
    )
    for spec in (FIXTURES / "spec" / "stages").iterdir():
        shutil.copy2(spec, workspace / "spec" / "stages" / spec.name)
    start(workspace, FLOW_DEFINITION)
    return workspace


def existing_paths(files: list[dict]) -> list[str]:
    return [item["path"] for item in files if item["exists"] and item["is_file"]]


class DashboardFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.workspace = make_workspace(self.root)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_snapshot_reports_real_flow_and_current_node(self) -> None:
        snapshot = build_snapshot(self.workspace)

        self.assertTrue(snapshot["readonly"])
        self.assertEqual(snapshot["flow"]["source"], "workspace_snapshot")
        self.assertEqual(len(snapshot["stages"]), 9)
        self.assertEqual(snapshot["summary"]["total_steps"], 48)
        self.assertEqual(snapshot["summary"]["done_steps"], 0)
        self.assertEqual(snapshot["summary"]["current_step_id"], "import.version_check")
        self.assertEqual(snapshot["summary"]["action"], "ready")

        node = get_node(snapshot, "import.version_check")
        self.assertIsNotNone(node)
        self.assertEqual(len(node["inputs"]), 4)
        self.assertTrue(all(item["exists"] for item in node["inputs"]))
        self.assertEqual(node["outputs"][0]["path"], "stages/import/reports/version_check.rpt")
        self.assertFalse(node["outputs"][0]["exists"])

    def test_node_snapshot_includes_logs_and_interaction_summaries(self) -> None:
        log_path = self.workspace / "stages" / "import" / "logs" / "version_check.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("version inputs are consistent\n", encoding="utf-8")
        log_interaction(
            self.workspace,
            "import.version_check",
            "assistant",
            "plan",
            "检查四个输入文件中的 release 标记是否一致。",
            run_id="run_001",
            references=["inputs/netlist.v"],
        )
        log_interaction(
            self.workspace,
            "import.version_check",
            "tool",
            "result",
            "版本检查完成，所有输入一致。",
            run_id="run_001",
            references=["stages/import/logs/version_check.log"],
        )

        snapshot = build_snapshot(self.workspace)
        node = get_node(snapshot, "import.version_check")

        self.assertEqual(existing_paths(node["logs"]), ["stages/import/logs/version_check.log"])
        self.assertEqual(len(node["interactions"]), 2)
        self.assertEqual(node["interactions"][0]["role"], "assistant")
        self.assertEqual(node["interactions"][1]["kind"], "result")
        self.assertEqual(snapshot["interaction_ledger"]["loaded_records"], 2)

    def test_snapshot_finds_real_run_script_logs(self) -> None:
        log_path = (
            self.workspace
            / "stages"
            / "import"
            / "run_001"
            / "scripts"
            / "read_design.log"
        )
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("mock innovus completed\n", encoding="utf-8")

        node = get_node(build_snapshot(self.workspace), "import.read_design")

        self.assertIn(
            "stages/import/run_001/scripts/read_design.log",
            existing_paths(node["logs"]),
        )

    def test_session_sync_imports_only_visible_text_and_is_idempotent(self) -> None:
        transcript = self.root / "claude-session.jsonl"
        records = [
            {
                "type": "user",
                "uuid": "user-1",
                "sessionId": "session-1",
                "timestamp": "2026-07-19T10:25:43Z",
                "message": {"role": "user", "content": "继续"},
            },
            {
                "type": "assistant",
                "uuid": "thinking-1",
                "sessionId": "session-1",
                "timestamp": "2026-07-19T10:25:44Z",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "thinking", "thinking": "private reasoning"}],
                },
            },
            {
                "type": "assistant",
                "uuid": "tool-1",
                "sessionId": "session-1",
                "timestamp": "2026-07-19T10:25:45Z",
                "message": {
                    "role": "assistant",
                    "content": [{
                        "type": "tool_use",
                        "name": "Bash",
                        "input": {
                            "command": "python3 flow_loader.py resolve-human --step floorplan.confirm_macro"
                        },
                    }],
                },
            },
            {
                "type": "user",
                "uuid": "tool-result-1",
                "parentUuid": "tool-1",
                "sessionId": "session-1",
                "timestamp": "2026-07-19T10:25:46Z",
                "message": {
                    "role": "user",
                    "content": [{"type": "tool_result", "content": "secret tool body"}],
                },
            },
            {
                "type": "assistant",
                "uuid": "assistant-1",
                "sessionId": "session-1",
                "timestamp": "2026-07-19T10:25:47Z",
                "message": {
                    "role": "assistant",
                    "model": "claude-test",
                    "content": [{
                        "type": "text",
                        "text": "开始执行 floorplan.floorplan_eval。",
                    }],
                },
            },
            {
                "type": "user",
                "uuid": "user-2",
                "sessionId": "session-1",
                "timestamp": "2026-07-19T10:25:48Z",
                "message": {"role": "user", "content": "当前节点是什么？"},
            },
            {
                "type": "assistant",
                "uuid": "assistant-2",
                "sessionId": "session-1",
                "timestamp": "2026-07-19T10:25:49Z",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "当前节点等待版本检查。"}],
                },
            },
        ]
        transcript.write_text(
            "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
            encoding="utf-8",
        )

        first = sync_transcript(self.workspace, transcript)
        second = sync_transcript(self.workspace, transcript)
        interactions = read_interactions(self.workspace)

        self.assertEqual(first["added"], 4)
        self.assertEqual(second["added"], 0)
        self.assertEqual(
            [item["role"] for item in interactions],
            ["user", "assistant", "user", "assistant"],
        )
        self.assertEqual(interactions[0]["step_id"], "floorplan.confirm_macro")
        self.assertEqual(interactions[0]["kind"], "approval")
        self.assertEqual(interactions[1]["step_id"], "floorplan.floorplan_eval")
        self.assertEqual(interactions[1]["model"], "claude-test")
        self.assertEqual(interactions[2]["step_id"], "import.version_check")
        self.assertEqual(interactions[3]["step_id"], "import.version_check")
        serialized = json.dumps(interactions, ensure_ascii=False)
        self.assertNotIn("private reasoning", serialized)
        self.assertNotIn("secret tool body", serialized)

    def test_interaction_ledger_filters_by_step_and_is_created_at_init(self) -> None:
        ledger = self.workspace / "state" / "agent_interactions.jsonl"
        self.assertTrue(ledger.is_file())
        log_interaction(
            self.workspace,
            "import.version_check",
            "assistant",
            "plan",
            "检查版本。",
        )
        log_interaction(
            self.workspace,
            "import.read_design",
            "tool",
            "result",
            "设计读取完成。",
        )

        records = read_interactions(
            self.workspace,
            step_id="import.version_check",
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["content"], "检查版本。")

    def test_missing_required_input_is_reported_as_blocker(self) -> None:
        (self.workspace / "inputs" / "cells.lib").unlink()

        snapshot = build_snapshot(self.workspace)

        self.assertEqual(snapshot["summary"]["action"], "blocked_inputs")
        self.assertIn("inputs/cells.lib", snapshot["summary"]["blocker"])

    def test_existing_required_output_is_a_fact_without_mutating_progress(self) -> None:
        output = self.workspace / "stages" / "import" / "reports" / "version_check.rpt"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("status: consistent\n", encoding="utf-8")

        snapshot = build_snapshot(self.workspace)
        node = get_node(snapshot, "import.version_check")

        self.assertEqual(node["recorded_status"], "pending")
        self.assertEqual(node["status"], "done_on_disk")
        self.assertEqual(snapshot["summary"]["current_step_id"], "import.read_design")
        self.assertTrue(any(w["code"] == "output_present_progress_not_done" for w in snapshot["warnings"]))

        progress_text = (self.workspace / "state" / "flow_progress.yaml").read_text(encoding="utf-8")
        self.assertIn("status: pending", progress_text)

    def test_done_node_with_missing_output_is_inconsistent(self) -> None:
        mark_step(self.workspace, "import.version_check", "done")

        snapshot = build_snapshot(self.workspace)
        node = get_node(snapshot, "import.version_check")

        self.assertEqual(node["status"], "inconsistent")
        self.assertEqual(snapshot["summary"]["current_step_id"], "import.version_check")
        self.assertEqual(snapshot["summary"]["action"], "inconsistent")
        self.assertTrue(any(w["code"] == "recorded_done_missing_output" for w in snapshot["warnings"]))

    def test_workspace_file_resolution_rejects_escape(self) -> None:
        self.assertEqual(
            resolve_workspace_file(self.workspace, "inputs/netlist.v"),
            (self.workspace / "inputs" / "netlist.v").resolve(),
        )
        with self.assertRaises(PermissionError):
            resolve_workspace_file(self.workspace, "../outside.txt")
        with self.assertRaises(PermissionError):
            resolve_workspace_file(self.workspace, "/etc/passwd")

    def test_workspace_auto_discovery_prefers_dot_chipflow(self) -> None:
        project = self.root / "project"
        project.mkdir()
        discovered = project / ".chipflow"
        shutil.copytree(self.workspace, discovered)
        self.assertEqual(resolve_workspace(None, project), discovered.resolve())


class DashboardHTTPTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.workspace = make_workspace(self.root)
        self.server = create_server(self.workspace, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.tempdir.cleanup()

    def get_json(self, path: str) -> dict:
        with urlopen(f"{self.base_url}{path}", timeout=5) as response:
            self.assertEqual(response.headers.get("Cache-Control"), "no-store")
            return json.loads(response.read().decode("utf-8"))

    def test_health_snapshot_node_and_static_page(self) -> None:
        health = self.get_json("/api/health")
        self.assertEqual(health["status"], "ok")
        self.assertEqual(health["workspace"], str(self.workspace.resolve()))
        self.assertEqual(self.get_json("/api/snapshot")["summary"]["total_steps"], 48)
        node = self.get_json("/api/nodes/import.version_check")
        self.assertEqual(node["id"], "import.version_check")

        with urlopen(f"{self.base_url}/", timeout=5) as response:
            html = response.read().decode("utf-8")
            self.assertIn("ChipFlow 项目驾驶舱", html)
            self.assertIn("只读模式", html)

    def test_workspace_file_endpoint_serves_declared_input(self) -> None:
        path = quote("inputs/netlist.v", safe="")
        with urlopen(f"{self.base_url}/api/file?path={path}", timeout=5) as response:
            body = response.read().decode("utf-8")
            self.assertIn("release:", body)
            self.assertTrue(response.headers.get("Content-Type", "").startswith("text/plain"))

    def test_workspace_file_endpoint_blocks_traversal(self) -> None:
        path = quote("../outside.txt", safe="")
        with self.assertRaises(HTTPError) as context:
            urlopen(f"{self.base_url}/api/file?path={path}", timeout=5)
        self.assertEqual(context.exception.code, 403)
        context.exception.close()


class DashboardManagerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.project = self.root / "design_project"
        self.project.mkdir()
        self.workspace = make_workspace(self.project, ".chipflow")
        self.state_dir = self.root / "manager_state"
        self.started = None

    def tearDown(self) -> None:
        if self.started is not None:
            try:
                stop_dashboard(project_dir=self.project, state_dir=self.state_dir)
            except (FileNotFoundError, RuntimeError):
                pass
        self.tempdir.cleanup()

    def test_start_reuse_status_and_stop_from_project_directory(self) -> None:
        self.started = start_dashboard(
            project_dir=self.project,
            port=0,
            open_browser=False,
            state_dir=self.state_dir,
        )
        self.assertEqual(self.started["status"], "started")
        self.assertEqual(self.started["workspace"], str(self.workspace.resolve()))
        self.assertTrue(self.started["readonly"])

        running = dashboard_status(project_dir=self.project, state_dir=self.state_dir)
        self.assertEqual(running["status"], "running")
        self.assertEqual(running["pid"], self.started["pid"])

        repeated = start_dashboard(
            project_dir=self.project,
            port=0,
            open_browser=False,
            state_dir=self.state_dir,
        )
        self.assertEqual(repeated["status"], "already_running")
        self.assertEqual(repeated["pid"], self.started["pid"])

        stopped = stop_dashboard(project_dir=self.project, state_dir=self.state_dir)
        self.assertEqual(stopped["status"], "stopped")
        self.assertEqual(
            dashboard_status(project_dir=self.project, state_dir=self.state_dir)["status"],
            "stopped",
        )
        self.started = None


if __name__ == "__main__":
    unittest.main()
