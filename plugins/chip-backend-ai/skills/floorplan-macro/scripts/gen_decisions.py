#!/usr/bin/env python3
"""floorplan-macro / gen_decisions.py — deterministic baseline for macro steps.

Covers BOTH floorplan AI-decision steps that concern macros (they share one
playbook because halo/blockage is tightly coupled to macro placement):
    - floorplan.macro_placement  (location / orientation / channel width)
    - floorplan.add_blockage     (halo / placement blockage / voltage areas)

It branches on --step to emit the right params/fragments for each template.
This is the *unattended default*: it reads the stage spec's `metrics` targets +
`parameters` and derives sane values so the flow runs without a human. The
SKILL.md playbook is where the AI improves on this baseline for a specific chip
(and where the search-eda-command guardrail lives).

Contract (shared by all decision steps — see docs/flow_impl_progress.md):
    gen_decisions.py --workspace <ws> --step <stage.step> \
        --spec <stage_spec.yaml> [--upstream-eval <eval_result.yaml>] \
        --out <ws>/<decisions-path>

Templates covered:
    macro_placement.tcl.tmpl  placeholders: macro_channel_width_um, macro_orientation
                              inject:       macro_placement_cmds
    add_blockage.tcl.tmpl     placeholders: halo_um, blockage_type
                              inject:       blockage_cmds
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


def _metric_target(spec: dict, name: str) -> dict:
    for m in spec.get("metrics", []) or []:
        if m.get("name") == name:
            return m.get("target") or {}
    return {}


def _decisions_macro_placement(spec: dict, upstream_eval: dict) -> dict:
    params = spec.get("parameters") or {}

    # Channel width must clear the gate's minimum; prefer the spec parameter,
    # else use the metric min (bumped slightly) so the gate has headroom.
    chan_target = _metric_target(spec, "macro_channel_width_um")
    macro_channel_width_um = params.get("macro_channel_width_um")
    if macro_channel_width_um is None:
        mn = chan_target.get("min")
        macro_channel_width_um = round(float(mn) * 2.0, 4) if mn is not None else 4.0

    macro_orientation = params.get("macro_orientation", "R0")

    rationale = (
        f"Baseline macro placement: concurrent auto-place with min channel "
        f"{macro_channel_width_um}um (>= gate min {chan_target.get('min')}) and "
        f"default orientation {macro_orientation}. Deterministic default; the "
        "floorplan-macro playbook should place macros by dataflow, orient pins "
        "toward consumers, and widen channels where routing demands."
    )

    return {
        "step": "floorplan.macro_placement",
        "generated_by": "floorplan-macro/gen_decisions.py (deterministic baseline)",
        "generated_at": _now(),
        "simulated_baseline": True,
        "params": {
            "macro_channel_width_um": macro_channel_width_um,
            "macro_orientation": macro_orientation,
        },
        "fragments": {
            # AI playbook may replace with explicit placeInstance / orientation cmds.
            "macro_placement_cmds": (
                "# (baseline) rely on concurrent auto macro placement; "
                "verify any placeInstance/place_design option via search-eda-command before injecting"
            ),
        },
        "rationale": rationale,
    }


def _decisions_add_blockage(spec: dict, upstream_eval: dict) -> dict:
    params = spec.get("parameters") or {}

    halo_um = params.get("halo_um", 3.0)
    blockage_type = params.get("blockage_type", "soft")

    rationale = (
        f"Baseline halo/blockage: {halo_um}um keep-out halo around all macros "
        f"plus a {blockage_type} placement blockage. Deterministic default; the "
        "floorplan-macro playbook should add corner/edge blockages and voltage "
        "areas per the power intent and macro pin sides."
    )

    return {
        "step": "floorplan.add_blockage",
        "generated_by": "floorplan-macro/gen_decisions.py (deterministic baseline)",
        "generated_at": _now(),
        "simulated_baseline": True,
        "params": {
            "halo_um": halo_um,
            "blockage_type": blockage_type,
        },
        "fragments": {
            # AI playbook may replace with explicit createPlaceBlockage / voltage areas.
            "blockage_cmds": (
                "# (baseline) no extra blockages/voltage areas; "
                "verify any createPlaceBlockage/createVoltageArea command via search-eda-command before injecting"
            ),
        },
        "rationale": rationale,
    }


def build_decisions(step: str, spec: dict, upstream_eval: dict) -> dict:
    # Branch on the bare step id (tolerate "stage.step" composite form).
    bare = step.split(".", 1)[1] if "." in step else step
    if bare == "macro_placement":
        return _decisions_macro_placement(spec, upstream_eval)
    if bare == "add_blockage":
        return _decisions_add_blockage(spec, upstream_eval)
    raise ValueError(
        f"floorplan-macro covers macro_placement / add_blockage, not '{step}'"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Generate deterministic baseline decisions.yaml for floorplan macro_placement / add_blockage."
    )
    parser.add_argument("--workspace", required=True, help="Flow workspace root")
    parser.add_argument("--step", required=True,
                        help="Composite step id, e.g. floorplan.macro_placement or floorplan.add_blockage")
    parser.add_argument("--spec", required=True, help="Stage spec yaml (metrics + parameters)")
    parser.add_argument("--upstream-eval", default=None, dest="upstream_eval",
                        help="Optional upstream eval_result.yaml (diagnostic retry loop)")
    parser.add_argument("--out", required=True, help="Path to write decisions.yaml")
    args = parser.parse_args()

    try:
        spec = _load_yaml(args.spec)
        upstream_eval = _load_yaml(args.upstream_eval)
        decisions = build_decisions(args.step, spec, upstream_eval)
    except FileNotFoundError as e:
        print(json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False, indent=2))
        sys.exit(1)
    except ValueError as e:
        print(json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False, indent=2))
        sys.exit(1)

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
