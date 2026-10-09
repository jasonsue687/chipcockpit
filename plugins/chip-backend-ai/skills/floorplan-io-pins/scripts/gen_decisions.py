#!/usr/bin/env python3
"""floorplan-io-pins / gen_decisions.py — deterministic baseline for place_io_pins.

Emits a `decisions.yaml` for the floorplan `place_io_pins` step (IO pin
placement / layer / spacing / grouping). This is the *unattended default*: it
reads the stage spec's `parameters` and derives sane values so the flow runs
without a human. The SKILL.md playbook is where the AI improves on this baseline
for a specific chip (and where the search-eda-command guardrail lives).

Contract (shared by all decision steps — see docs/flow_impl_progress.md):
    gen_decisions.py --workspace <ws> --step <stage.step> \
        --spec <stage_spec.yaml> [--upstream-eval <eval_result.yaml>] \
        --out <ws>/<decisions-path>

Template covered: templates/tcl/floorplan/place_io_pins.tcl.tmpl
    placeholders: pin_layer_h, pin_layer_v, pin_spacing_um, pin_side
    inject:       io_pin_assignments
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_yaml(path: str | None) -> dict:
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {path}")
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def build_decisions(spec: dict, upstream_eval: dict) -> dict:
    params = spec.get("parameters") or {}

    pin_layer_h = params.get("pin_layer_h", "M3")
    pin_layer_v = params.get("pin_layer_v", "M4")
    pin_spacing_um = params.get("pin_spacing_um", 0.5)
    pin_side = params.get("pin_side", "Left")

    rationale = (
        f"Baseline IO pins: even spread on {pin_layer_h} (horizontal edges) / "
        f"{pin_layer_v} (vertical edges) with {pin_spacing_um}um spacing on the "
        f"{pin_side} side. Deterministic default from gen_decisions; the "
        "floorplan-io-pins playbook should group buses, align pins to the "
        "consuming block, and balance pin congestion per side."
    )

    return {
        "step": "floorplan.place_io_pins",
        "generated_by": "floorplan-io-pins/gen_decisions.py (deterministic baseline)",
        "generated_at": _now(),
        "simulated_baseline": True,
        "params": {
            "pin_layer_h": pin_layer_h,
            "pin_layer_v": pin_layer_v,
            "pin_spacing_um": pin_spacing_um,
            "pin_side": pin_side,
        },
        "fragments": {
            # AI playbook may replace this with per-bus / per-group editPin calls.
            "io_pin_assignments": (
                "# (baseline) no explicit per-group pin assignments; "
                "verify any editPin/assignIoPins command via search-eda-command before injecting"
            ),
        },
        "rationale": rationale,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Generate deterministic baseline decisions.yaml for floorplan.place_io_pins."
    )
    parser.add_argument("--workspace", required=True, help="Flow workspace root")
    parser.add_argument("--step", required=True, help="Composite step id, e.g. floorplan.place_io_pins")
    parser.add_argument("--spec", required=True, help="Stage spec yaml (metrics + parameters)")
    parser.add_argument("--upstream-eval", default=None, dest="upstream_eval",
                        help="Optional upstream eval_result.yaml (diagnostic retry loop)")
    parser.add_argument("--out", required=True, help="Path to write decisions.yaml")
    args = parser.parse_args()

    try:
        spec = _load_yaml(args.spec)
        upstream_eval = _load_yaml(args.upstream_eval)
    except FileNotFoundError as e:
        print(json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False, indent=2))
        sys.exit(1)

    decisions = build_decisions(spec, upstream_eval)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        yaml.dump(decisions, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    print(json.dumps({
        "status": "ok",
        "step": args.step,
        "out": str(out),
        "params": list(decisions["params"].keys()),
        "fragments": list(decisions["fragments"].keys()),
    }, ensure_ascii=False, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
