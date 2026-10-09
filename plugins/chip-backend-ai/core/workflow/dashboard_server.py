#!/usr/bin/env python3
"""Local, read-only HTTP server for the chip-flow dashboard."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import yaml

from dashboard import build_snapshot, get_node, resolve_workspace, resolve_workspace_file


STATIC_DIR = Path(__file__).resolve().parents[2] / "ui"
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
}


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address, handler_class, workspace: Path):
        super().__init__(server_address, handler_class)
        self.workspace = workspace


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "ChipFlowDashboard/0.1"

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/health":
                self._write_json({
                    "status": "ok",
                    "readonly": True,
                    "workspace": str(self.server.workspace),
                })
                return
            if parsed.path == "/api/snapshot":
                self._write_json(build_snapshot(self.server.workspace))
                return
            if parsed.path.startswith("/api/nodes/"):
                step_id = unquote(parsed.path.removeprefix("/api/nodes/"))
                node = get_node(build_snapshot(self.server.workspace), step_id)
                if node is None:
                    self._write_json(
                        {"error": f"Unknown step: {step_id}"}, HTTPStatus.NOT_FOUND
                    )
                else:
                    self._write_json(node)
                return
            if parsed.path == "/api/file":
                values = parse_qs(parsed.query).get("path", [])
                if len(values) != 1:
                    self._write_json(
                        {"error": "Exactly one relative path is required"},
                        HTTPStatus.BAD_REQUEST,
                    )
                    return
                self._serve_workspace_file(values[0])
                return
            if parsed.path in STATIC_FILES:
                filename, content_type = STATIC_FILES[parsed.path]
                self._serve_static(filename, content_type)
                return
            self._write_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
        except PermissionError as exc:
            self._write_json({"error": str(exc)}, HTTPStatus.FORBIDDEN)
        except FileNotFoundError as exc:
            self._write_json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
        except (OSError, ValueError, yaml.YAMLError) as exc:
            self._write_json(
                {"error": str(exc), "type": type(exc).__name__},
                HTTPStatus.UNPROCESSABLE_ENTITY,
            )

    def _serve_static(self, filename: str, content_type: str) -> None:
        path = STATIC_DIR / filename
        if not path.is_file():
            raise FileNotFoundError(f"Dashboard asset not found: {path}")
        self._write_bytes(path.read_bytes(), content_type)

    def _serve_workspace_file(self, relative_path: str) -> None:
        path = resolve_workspace_file(self.server.workspace, relative_path)
        if not path.is_file():
            raise FileNotFoundError(f"Workspace file not found: {relative_path}")
        content_type = _content_type(path)
        self.send_response(HTTPStatus.OK)
        self._common_headers(content_type, path.stat().st_size)
        self.end_headers()
        with open(path, "rb") as handle:
            shutil.copyfileobj(handle, self.wfile)

    def _write_json(self, payload: dict | list, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self._common_headers("application/json; charset=utf-8", len(data))
        self.end_headers()
        self.wfile.write(data)

    def _write_bytes(self, data: bytes, content_type: str) -> None:
        self.send_response(HTTPStatus.OK)
        self._common_headers(content_type, len(data))
        self.end_headers()
        self.wfile.write(data)

    def _common_headers(self, content_type: str, content_length: int) -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(content_length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'",
        )

    def log_message(self, format: str, *args) -> None:
        sys.stderr.write(f"[dashboard] {self.address_string()} - {format % args}\n")


def _content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml", ".json", ".jsonl", ".log", ".rpt", ".tcl", ".txt", ".def", ".sdc", ".v", ".lef", ".lib"}:
        return "text/plain; charset=utf-8"
    if suffix == ".html":
        return "text/html; charset=utf-8"
    return "application/octet-stream"


def create_server(workspace: str | Path, host: str = "127.0.0.1", port: int = 8765) -> DashboardServer:
    resolved = resolve_workspace(workspace)
    return DashboardServer((host, port), DashboardHandler, resolved)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local read-only chip-flow dashboard")
    parser.add_argument("--workspace", default=None, help="Workspace root; auto-discovers .chipflow when omitted")
    parser.add_argument("--project-dir", default=None, help="Project directory used for workspace auto-discovery")
    parser.add_argument("--host", default="127.0.0.1", help="Listen host (default: localhost only)")
    parser.add_argument("--port", type=int, default=8765, help="Listen port (default: 8765)")
    parser.add_argument("--open", action="store_true", help="Open the dashboard in the default browser")
    args = parser.parse_args()

    workspace = resolve_workspace(args.workspace, args.project_dir)
    server = DashboardServer((args.host, args.port), DashboardHandler, workspace)
    host, port = server.server_address[:2]
    display_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    url = f"http://{display_host}:{port}/"
    print(json.dumps({
        "status": "ready",
        "url": url,
        "workspace": str(workspace),
        "readonly": True,
    }, ensure_ascii=False), flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
