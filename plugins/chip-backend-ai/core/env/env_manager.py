#!/usr/bin/env python3
"""EDA tool environment detection and config management.

Detects EDA tool installations on the current machine and persists the result
in a JSON config so later flow stages can locate the binaries.

Default config location:
    ~/.chip-backend-ai/env.json    (machine-level, recommended)

Per-workspace override:
    pass `--config <workspace>/env.json` to scope the config to one project.

Config schema (extensible — only `innovus` is implemented today; adding Genus
or Tempus only needs a new entry in `eda_tools`):

    {
      "version": "1",
      "detected_at": "2026-05-17T10:30:00+00:00",
      "eda_tools": {
        "innovus": {
          "binary": "/opt/cadence/INNOVUS221/bin/innovus",
          "install_dir": "/opt/cadence/INNOVUS221",
          "version": "22.10",
          "source": "PATH" | "env:INNOVUS_HOME" | "glob:..." | "user-provided"
        }
      }
    }

CLI:
    env_manager.py detect [--save]            # auto-detect, optionally persist
    env_manager.py set --tool innovus --path <path>
    env_manager.py read
    env_manager.py check --tool innovus
"""

import argparse
import glob
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_CONFIG_DIR = Path.home() / ".chip-backend-ai"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "env.json"
SUPPORTED_TOOLS = ["innovus"]

INNOVUS_SEARCH_PATTERNS = [
    "/opt/cadence/INNOVUS*/bin/innovus",
    "/opt/cadence/installs/INNOVUS*/bin/innovus",
    "/opt/cadence/innovus*/bin/innovus",
    "/tools/cadence/INNOVUS*/bin/innovus",
    "/tools/cadence/innovus*/bin/innovus",
    "/usr/local/cadence/INNOVUS*/bin/innovus",
    "/cadence/INNOVUS*/bin/innovus",
    str(Path.home() / "cadence" / "INNOVUS*" / "bin" / "innovus"),
]

INNOVUS_ENV_VARS = ["INNOVUS_HOME", "INNOVUS_ROOT", "CDS_INST_DIR"]


def detect_innovus() -> dict | None:
    """Try to locate the Innovus binary on this machine.

    Search order: PATH → env vars → common install paths.
    Returns an eda_tools entry dict, or None if not found.
    """
    # 1. PATH
    binary = shutil.which("innovus")
    if binary:
        return _resolve_innovus(Path(binary), source="PATH")

    # 2. Vendor-style env vars
    for var in INNOVUS_ENV_VARS:
        val = os.environ.get(var)
        if not val:
            continue
        candidate = Path(val) / "bin" / "innovus"
        if candidate.exists() and os.access(candidate, os.X_OK):
            return _resolve_innovus(candidate, source=f"env:{var}")

    # 3. Glob common install paths
    for pattern in INNOVUS_SEARCH_PATTERNS:
        matches = glob.glob(pattern)
        if not matches:
            continue
        matches.sort(reverse=True)  # prefer higher version lexically
        for m in matches:
            p = Path(m)
            if p.exists() and os.access(p, os.X_OK):
                return _resolve_innovus(p, source=f"glob:{pattern}")

    return None


def _resolve_innovus(binary_path: Path, source: str) -> dict:
    """Build an eda_tools entry from a verified binary path."""
    binary_path = binary_path.resolve()
    if binary_path.parent.name == "bin":
        install_dir = binary_path.parent.parent
    else:
        install_dir = binary_path.parent
    return {
        "binary": str(binary_path),
        "install_dir": str(install_dir),
        "version": _detect_version(install_dir),
        "source": source,
    }


def _detect_version(install_dir: Path) -> str | None:
    """Best-effort version extraction from install dir name (e.g. INNOVUS221)."""
    m = re.search(r"INNOVUS[_\-]?(\d+(?:\.\d+)?)", install_dir.name, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"(\d+\.\d+)", install_dir.name)
    if m:
        return m.group(1)
    return None


def validate_path(raw_path: str, tool: str) -> tuple[bool, str]:
    """Resolve a user-provided path to an executable binary.

    Accepts either the binary directly or an install dir; returns
    (ok, resolved_path_or_error_message).
    """
    p = Path(raw_path).expanduser()
    if not p.exists():
        return False, f"Path does not exist: {p}"
    if p.is_dir():
        candidate = p / "bin" / tool
        if candidate.exists() and os.access(candidate, os.X_OK):
            return True, str(candidate.resolve())
        return False, f"Directory has no executable bin/{tool}: {p}"
    if not os.access(p, os.X_OK):
        return False, f"Path is not executable: {p}"
    return True, str(p.resolve())


def read_config(config_file: Path = DEFAULT_CONFIG_FILE) -> dict | None:
    """Read the env config, returning None if missing or malformed."""
    if not config_file.exists():
        return None
    try:
        with open(config_file) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def write_config(config: dict, config_file: Path = DEFAULT_CONFIG_FILE) -> Path:
    """Atomically write the env config."""
    config_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = config_file.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
        f.write("\n")
    tmp.replace(config_file)
    return config_file


def get_tool_binary(tool: str, config_file: Path = DEFAULT_CONFIG_FILE) -> str | None:
    """Helper for agents: return the configured binary path for a tool, or None."""
    config = read_config(config_file)
    if not config:
        return None
    entry = config.get("eda_tools", {}).get(tool)
    if not entry:
        return None
    binary = Path(entry["binary"])
    if binary.exists() and os.access(binary, os.X_OK):
        return str(binary)
    return None


def _upsert_tool_entry(config: dict | None, tool: str, entry: dict) -> dict:
    config = config or {"version": "1", "eda_tools": {}}
    config.setdefault("eda_tools", {})[tool] = entry
    config["version"] = "1"
    config["detected_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return config


# ---------- CLI ----------

def cmd_detect(args) -> int:
    detected = {}
    if "innovus" in args.tools:
        innovus = detect_innovus()
        if innovus:
            detected["innovus"] = innovus

    if not detected:
        print(json.dumps({
            "status": "not_found",
            "message": "No EDA tools auto-detected. Ask the user for the path, then run `set`.",
            "searched": {
                "PATH": True,
                "env_vars": INNOVUS_ENV_VARS,
                "install_globs": INNOVUS_SEARCH_PATTERNS,
            },
        }, indent=2, ensure_ascii=False))
        return 1

    if args.save:
        config = read_config(args.config)
        for tool, entry in detected.items():
            config = _upsert_tool_entry(config, tool, entry)
        path = write_config(config, args.config)
        print(json.dumps({
            "status": "saved",
            "config_file": str(path),
            "eda_tools": config["eda_tools"],
        }, indent=2, ensure_ascii=False))
    else:
        print(json.dumps({
            "status": "found",
            "saved": False,
            "config_file": str(args.config),
            "detected": detected,
        }, indent=2, ensure_ascii=False))
    return 0


def cmd_set(args) -> int:
    ok, resolved = validate_path(args.path, args.tool)
    if not ok:
        print(json.dumps({"status": "error", "message": resolved}, indent=2, ensure_ascii=False))
        return 1

    binary = Path(resolved)
    install_dir = binary.parent.parent if binary.parent.name == "bin" else binary.parent
    entry = {
        "binary": str(binary),
        "install_dir": str(install_dir),
        "version": _detect_version(install_dir),
        "source": "user-provided",
    }
    config = _upsert_tool_entry(read_config(args.config), args.tool, entry)
    path = write_config(config, args.config)
    print(json.dumps({
        "status": "saved",
        "config_file": str(path),
        "tool": args.tool,
        "entry": entry,
    }, indent=2, ensure_ascii=False))
    return 0


def cmd_read(args) -> int:
    config = read_config(args.config)
    if config is None:
        print(json.dumps({
            "status": "missing",
            "config_file": str(args.config),
            "message": "No env config exists yet. Run `detect --save` or `set --tool ... --path ...` first.",
        }, indent=2, ensure_ascii=False))
        return 1
    print(json.dumps({
        "status": "ok",
        "config_file": str(args.config),
        "config": config,
    }, indent=2, ensure_ascii=False))
    return 0


def cmd_check(args) -> int:
    """Exit codes: 0=ok, 1=stale binary, 2=missing config or tool."""
    config = read_config(args.config)
    if config is None:
        print(json.dumps({
            "status": "missing_config",
            "config_file": str(args.config),
        }, indent=2, ensure_ascii=False))
        return 2
    entry = config.get("eda_tools", {}).get(args.tool)
    if not entry:
        print(json.dumps({
            "status": "missing_tool",
            "tool": args.tool,
            "config_file": str(args.config),
        }, indent=2, ensure_ascii=False))
        return 2
    binary = Path(entry["binary"])
    if not binary.exists() or not os.access(binary, os.X_OK):
        print(json.dumps({
            "status": "stale",
            "tool": args.tool,
            "binary": str(binary),
            "message": "Configured binary is missing or not executable. Re-run `detect --save` or `set`.",
        }, indent=2, ensure_ascii=False))
        return 1
    print(json.dumps({
        "status": "ok",
        "tool": args.tool,
        "binary": str(binary),
        "version": entry.get("version"),
        "source": entry.get("source"),
    }, indent=2, ensure_ascii=False))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Detect, store, and look up EDA tool paths for the chip-backend-ai plugin.",
    )
    parser.add_argument(
        "--config", type=Path, default=DEFAULT_CONFIG_FILE,
        help=f"Config file path (default: {DEFAULT_CONFIG_FILE})",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_detect = sub.add_parser("detect", help="Auto-detect EDA tools on this machine")
    p_detect.add_argument("--save", action="store_true", help="Persist detection result to config")
    p_detect.add_argument(
        "--tool", action="append", dest="tools", choices=SUPPORTED_TOOLS, default=None,
        help="Limit detection to specific tools (default: all supported)",
    )
    p_detect.set_defaults(func=cmd_detect)

    p_set = sub.add_parser("set", help="Manually set an EDA tool path")
    p_set.add_argument("--tool", required=True, choices=SUPPORTED_TOOLS)
    p_set.add_argument("--path", required=True, help="Path to the tool binary or install dir")
    p_set.set_defaults(func=cmd_set)

    p_read = sub.add_parser("read", help="Read the current env config")
    p_read.set_defaults(func=cmd_read)

    p_check = sub.add_parser("check", help="Verify a tool is configured and binary is valid")
    p_check.add_argument("--tool", required=True, choices=SUPPORTED_TOOLS)
    p_check.set_defaults(func=cmd_check)

    args = parser.parse_args()
    if getattr(args, "tools", None) is None and args.cmd == "detect":
        args.tools = SUPPORTED_TOOLS
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
