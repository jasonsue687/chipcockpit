#!/usr/bin/env python3
"""mock_eda — synthetic, clearly-labeled EDA report generator for flow validation.

Real EDA tools (Innovus) are not always available. The honest *stub* in
run-eda-script produces placeholder output with NO metrics, so every
parse-eda-report gate honestly reads `missing → partial` and never passes —
which is correct, but blocks end-to-end flow validation.

This module is the *separate, explicitly-labeled* simulation path. Given a stage
spec's `metrics` list, it picks an in-range `actual` for each metric (reusing
stage_simulator.pick_actual) and writes a report whose lines match the
METRIC_PATTERNS regexes in core/router.py, so parse-eda-report extracts them and
the gate PASSes — in SIMULATION mode.

Every report it writes starts with a loud SIMULATED banner. These are synthetic
values for flow validation, NOT real PPA. Never reuse this path to fabricate
unlabeled numbers.
"""

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml


def _plugin_root() -> Path:
    # core/sim/mock_eda.py → plugin root is two parents up from core/.
    return Path(__file__).resolve().parents[2]


def _load_stage_simulator():
    """Load core/workflow/stage_simulator.py by path to reuse pick_actual."""
    sim_path = _plugin_root() / "core" / "workflow" / "stage_simulator.py"
    spec = importlib.util.spec_from_file_location("stage_simulator", sim_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# Map each metric name (as declared in a stage spec) to a function that renders
# a report line matching the corresponding METRIC_PATTERNS regex in router.py.
# `v` is the picked in-range actual value.
LINE_FORMATTERS = {
    "wns_ns": lambda v: f"WNS (ns) = {v}",
    "tns_ns": lambda v: f"TNS (ns) = {v}",
    "hold_wns_ns": lambda v: f"hold WNS (ns) = {v}",
    "utilization": lambda v: f"utilization = {v}",
    "congestion_hotspot": lambda v: f"total overflow = {v}",
    "macro_channel_width_um": lambda v: f"channel width (um) = {v}",
    "power_grid_ir_drop": lambda v: f"worst IR drop (mV) = {v}",
    "drc_violations": lambda v: f"total violations = {int(round(float(v)))}",
    "total_power_mw": lambda v: f"total power (mW) = {v}",
    "global_skew_ps": lambda v: f"global skew (ps) = {v}",
    "max_insertion_delay_ps": lambda v: f"max insertion delay (ps) = {v}",
}


def _format_line(name: str, value) -> str | None:
    """Render a parseable report line for a known metric, else None."""
    fmt = LINE_FORMATTERS.get(name)
    if fmt is None:
        return None
    try:
        return fmt(value)
    except (TypeError, ValueError):
        return None


def generate_report(stage: str, spec_path, out_path, run_id: str = "run_001") -> dict:
    """Write a SIMULATED, parseable report for a stage's spec metrics.

    Reads the stage spec at ``spec_path``, picks an in-range ``actual`` for each
    metric via stage_simulator.pick_actual, and writes lines matching
    METRIC_PATTERNS so parse-eda-report extracts them. Returns a summary dict.
    """
    spec_path = Path(spec_path)
    out_path = Path(out_path)

    if not spec_path.exists():
        return {"status": "error", "message": f"Stage spec not found: {spec_path}"}

    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8")) or {}
    metrics_spec = spec.get("metrics") or []

    sim = _load_stage_simulator()

    lines = [
        f"# SIMULATED EDA report — synthetic values for flow validation, "
        f"NOT real PPA. stage={stage} run={run_id}",
        f"# generated_by=mock_eda at {_now()}",
        f"# spec={spec_path}",
        "",
    ]

    emitted: list[dict] = []
    unmapped: list[str] = []
    for m in metrics_spec:
        name = m.get("name")
        if not name:
            continue
        target = m.get("target")
        value = sim.pick_actual(target)
        line = _format_line(name, value)
        if line is None:
            unmapped.append(name)
            lines.append(f"# (metric '{name}' has no mock line formatter; left absent)")
            continue
        lines.append(line)
        emitted.append({"name": name, "actual": value})

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return {
        "status": "ok",
        "simulated": True,
        "stage": stage,
        "run_id": run_id,
        "report": str(out_path),
        "emitted_metrics": emitted,
        "unmapped_metrics": unmapped,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Generate a SIMULATED, parseable EDA report from a stage spec's metrics."
    )
    parser.add_argument("--stage", required=True, help="Stage name (for the report header)")
    parser.add_argument("--spec", required=True, help="Stage spec yaml (provides metrics + targets)")
    parser.add_argument("--out", required=True, help="Path to write the simulated report")
    parser.add_argument("--run-id", default="run_001", dest="run_id", help="Run ID (default: run_001)")
    args = parser.parse_args()

    result = generate_report(args.stage, args.spec, args.out, args.run_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result["status"] == "ok" else 1)


if __name__ == "__main__":
    main()
