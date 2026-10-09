#!/usr/bin/env python3
"""run-eda-script — execute a Tcl script in an EDA tool and collect outputs.

This is the generic *execution* primitive behind the flow engine's
`executor: { type: skill, ref: run-eda-script }` steps. It is deliberately
dumb: it runs a script, captures the log, and verifies the files the step
said it should produce. It does NOT interpret metrics — that is
parse-eda-report's job.

Tool resolution reuses core/env/env_manager.py (machine-level config at
~/.chip-backend-ai/env.json). If the tool isn't configured/available — or
`--stub` is passed — it falls back to **stub mode**: no tool is invoked, a
clearly-marked stub log is written, and each declared `--expect-output` file
is created as a placeholder so the flow can still advance through its
structure for a dry run. Stub mode never fabricates metric values; downstream
gate steps will honestly report those metrics as `missing`.

**Mock mode** (`--mock`) is a *separate, explicitly-labeled* simulation path
distinct from stub: it still writes placeholder `--expect-output` files (each
marked SIMULATED), but additionally — when `--report`/`--stage`/`--spec` are
given — calls core/sim/mock_eda.generate_report to emit a parseable report with
in-range synthetic metric values, so a downstream gate can PASS in simulation.
Every mock artifact is loudly labeled SIMULATED. Stub stays honest (no metrics);
mock is opt-in and never produces unlabeled numbers.

CLI:
    run_eda_script.py --script <tcl> \
        [--expect-output <path> ...] \
        [--log <path>] [--tool innovus] [--config <env.json>] \
        [--stub] [--mock] [--report <path>] [--stage <name>] [--spec <path>] \
        [--timeout <seconds>]

All output is a single JSON object on stdout.
"""

import argparse
import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Innovus batch invocation: no GUI, exit when the script finishes.
DEFAULT_TOOL_ARGS = ["-no_gui", "-batch"]


def _plugin_root() -> Path:
    # skills/run-eda-script/scripts/run_eda_script.py → plugin root is 3 up from scripts/.
    return Path(__file__).resolve().parents[3]


def _load_env_manager():
    """Load core/env/env_manager.py by path (avoids package-import fragility)."""
    em_path = _plugin_root() / "core" / "env" / "env_manager.py"
    spec = importlib.util.spec_from_file_location("env_manager", em_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_mock_eda():
    """Load core/sim/mock_eda.py by path (avoids package-import fragility)."""
    me_path = _plugin_root() / "core" / "sim" / "mock_eda.py"
    spec = importlib.util.spec_from_file_location("mock_eda", me_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write_stub_outputs(expect_outputs: list[str], script: str, reason: str) -> list[str]:
    """Create placeholder files for each declared output so the flow advances."""
    created = []
    for out in expect_outputs:
        p = Path(out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            f"# STUB output — EDA tool not invoked ({reason}).\n"
            f"# Source script: {script}\n"
            f"# Generated: {_now()}\n"
            f"# This is a placeholder so the flow can dry-run its structure;\n"
            f"# it contains NO real design data or metrics.\n",
            encoding="utf-8",
        )
        created.append(str(p))
    return created


def _write_mock_outputs(expect_outputs: list[str], script: str, report: str | None) -> list[str]:
    """Create SIMULATED placeholder files for each declared output (mock mode).

    Like stub placeholders, but loudly labeled SIMULATED rather than STUB. The
    parseable metric report (if any) is written separately by mock_eda; these
    are just the DEF/DB-style structural outputs so the flow advances.
    """
    created = []
    for out in expect_outputs:
        p = Path(out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            f"# SIMULATED output — EDA tool not invoked (mock mode).\n"
            f"# Source script: {script}\n"
            f"# Generated: {_now()}\n"
            f"# Synthetic placeholder for flow validation, NOT real design data.\n"
            + (f"# Parseable metrics written to: {report}\n" if report else ""),
            encoding="utf-8",
        )
        created.append(str(p))
    return created


def run(
    script: str,
    expect_outputs: list[str],
    log_path: str | None,
    tool: str,
    config: str | None,
    stub: bool,
    timeout: float | None,
    mock: bool = False,
    report: str | None = None,
    stage: str | None = None,
    spec: str | None = None,
) -> dict:
    script_path = Path(script)
    if not script_path.exists():
        return {"status": "error", "message": f"Script not found: {script}"}

    log = Path(log_path) if log_path else script_path.with_suffix(".log")
    log.parent.mkdir(parents=True, exist_ok=True)

    # ---- Mock mode: explicit --mock (separate from stub; SIMULATED metrics) -
    if mock:
        log.write_text(
            f"# SIMULATED (mock) run — EDA tool not invoked.\n# script: {script}\n# {_now()}\n"
            f"# Synthetic in-range metrics for flow validation, NOT real PPA.\n",
            encoding="utf-8",
        )
        created = _write_mock_outputs(expect_outputs, script, report)
        report_info = None
        if report:
            if not (stage and spec):
                return {
                    "status": "error", "mode": "mock", "script": script,
                    "message": "--report requires both --stage and --spec to generate metrics",
                }
            me = _load_mock_eda()
            report_info = me.generate_report(stage, spec, report)
            if report_info.get("status") != "ok":
                return {
                    "status": "error", "mode": "mock", "script": script,
                    "message": f"mock report generation failed: {report_info.get('message')}",
                    "report_info": report_info,
                }
            if report not in created:
                created.append(report)
        return {
            "status": "mock",
            "mode": "mock",
            "tool": tool,
            "script": script,
            "log": str(log),
            "produced": created,
            "missing": [],
            "report": report_info,
            "note": "SIMULATED run — synthetic in-range metrics for flow validation, NOT real PPA.",
        }

    # Resolve the tool binary unless we were told to stub outright.
    binary = None
    if not stub:
        em = _load_env_manager()
        cfg = Path(config) if config else em.DEFAULT_CONFIG_FILE
        binary = em.get_tool_binary(tool, cfg)

    # ---- Stub mode: no tool / explicit --stub -------------------------------
    if stub or binary is None:
        reason = "explicit --stub" if stub else f"'{tool}' not configured/available"
        log.write_text(
            f"# STUB run — {reason}\n# script: {script}\n# {_now()}\n"
            f"# Configure the tool with core/env/env_manager.py to run for real.\n",
            encoding="utf-8",
        )
        created = _write_stub_outputs(expect_outputs, script, reason)
        return {
            "status": "stub",
            "mode": "stub",
            "reason": reason,
            "tool": tool,
            "script": script,
            "log": str(log),
            "produced": created,
            "missing": [],
            "note": "No EDA tool invoked. Placeholder outputs created; metrics will read as missing downstream.",
        }

    # ---- Real execution -----------------------------------------------------
    cmd = [binary, *DEFAULT_TOOL_ARGS, "-files", str(script_path)]
    try:
        with open(log, "w", encoding="utf-8") as logf:
            logf.write(f"# run-eda-script :: {_now()}\n# cmd: {' '.join(cmd)}\n\n")
            logf.flush()
            proc = subprocess.run(
                cmd,
                stdout=logf,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
            )
        returncode = proc.returncode
    except subprocess.TimeoutExpired:
        return {
            "status": "failed", "mode": "run", "tool": tool, "binary": binary,
            "script": script, "log": str(log),
            "message": f"Tool execution exceeded timeout ({timeout}s)",
        }
    except OSError as e:
        return {
            "status": "error", "mode": "run", "tool": tool, "binary": binary,
            "script": script, "message": f"Failed to launch tool: {e}",
        }

    produced = [o for o in expect_outputs if Path(o).exists()]
    missing = [o for o in expect_outputs if not Path(o).exists()]

    # Success requires a clean exit AND all declared outputs present.
    if returncode == 0 and not missing:
        status = "ok"
    else:
        status = "failed"

    return {
        "status": status,
        "mode": "run",
        "tool": tool,
        "binary": binary,
        "script": script,
        "returncode": returncode,
        "log": str(log),
        "produced": produced,
        "missing": missing,
    }


def main():
    parser = argparse.ArgumentParser(description="Run a Tcl script in an EDA tool and collect outputs.")
    parser.add_argument("--script", required=True, help="Path to the Tcl script to execute")
    parser.add_argument("--expect-output", action="append", default=[], dest="expect_outputs",
                        metavar="PATH", help="A file the script should produce (repeatable). Used to verify success.")
    parser.add_argument("--log", default=None, help="Log file path (default: <script>.log)")
    parser.add_argument("--tool", default="innovus", help="EDA tool name (default: innovus)")
    parser.add_argument("--config", default=None, help="env.json path (default: machine-level)")
    parser.add_argument("--stub", action="store_true", help="Force stub mode (don't invoke the tool; no metrics)")
    parser.add_argument("--mock", action="store_true",
                        help="Force SIMULATION mode: SIMULATED placeholder outputs + (with --report) parseable in-range metrics")
    parser.add_argument("--report", default=None,
                        help="(mock) Path to write a parseable SIMULATED metric report (requires --stage + --spec)")
    parser.add_argument("--stage", default=None, help="(mock) Stage name for the report header + metric selection")
    parser.add_argument("--spec", default=None, help="(mock) Stage spec yaml providing the metrics list + targets")
    parser.add_argument("--timeout", type=float, default=None, help="Max seconds before killing the tool")
    args = parser.parse_args()

    result = run(
        args.script, args.expect_outputs, args.log,
        args.tool, args.config, args.stub, args.timeout,
        mock=args.mock, report=args.report, stage=args.stage, spec=args.spec,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    # Exit non-zero on hard errors / failures so callers can branch on it.
    sys.exit(0 if result["status"] in ("ok", "stub", "mock") else 1)


if __name__ == "__main__":
    main()
