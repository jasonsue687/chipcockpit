#!/usr/bin/env python3
"""floorplan-plan / gen_decisions.py — deterministic baseline for gen_floorplan.

Emits a `decisions.yaml` for the floorplan `gen_floorplan` step (die/core size,
aspect ratio, target utilization). This is the *unattended default*: it reads
the stage spec's `metrics` targets + `parameters` and derives sane values so the
flow runs without a human. The SKILL.md playbook is where the AI improves on
this baseline for a specific chip (and where the search-eda-command guardrail
lives). The output is auditable and re-renderable.

Contract (shared by all decision steps — see docs/flow_impl_progress.md):
    gen_decisions.py --workspace <ws> --step <stage.step> \
        --spec <stage_spec.yaml> [--upstream-eval <eval_result.yaml>] \
        --out <ws>/<decisions-path>

The written decisions.yaml has:
    params:    keys EXACTLY match the template's {{placeholders}}
    fragments: keys match the template's `### @inject:<name>` blocks
    rationale: short prose for the audit trail

Template covered: templates/tcl/floorplan/gen_floorplan.tcl.tmpl
    placeholders: aspect_ratio, target_utilization, core_to_io_margin_um
    inject:       extra_floorplan_options
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


def _mid_of_band(target: dict, fallback: float) -> float:
    """Pick the midpoint of a [min, max] band; fall back if either is open."""
    mn, mx = target.get("min"), target.get("max")
    if mn is not None and mx is not None:
        return round((float(mn) + float(mx)) / 2.0, 4)
    if mn is not None:
        return float(mn)
    if mx is not None:
        return float(mx)
    return fallback


def build_decisions(spec: dict, upstream_eval: dict) -> dict:
    params = spec.get("parameters") or {}

    # Target utilization: prefer the spec parameter; else center the metric band.
    util_target = _metric_target(spec, "utilization")
    target_utilization = params.get("target_utilization")
    if target_utilization is None:
        target_utilization = _mid_of_band(util_target, 0.70)

    aspect_ratio = params.get("aspect_ratio", 1.0)
    core_to_io_margin_um = params.get("core_to_io_margin_um", 5.0)

    rationale = (
        f"Baseline floorplan: square core (aspect={aspect_ratio}) sized to "
        f"target utilization {target_utilization} (within the spec utilization "
        f"band), with a {core_to_io_margin_um}um core-to-IO margin. "
        "Deterministic default from gen_decisions; refine via the floorplan-plan "
        "playbook for this chip's dataflow/macro mix."
    )

    return {
        "step": "floorplan.gen_floorplan",
        "generated_by": "floorplan-plan/gen_decisions.py (deterministic baseline)",
        "generated_at": _now(),
        "simulated_baseline": True,
        "params": {
            "aspect_ratio": aspect_ratio,
            "target_utilization": target_utilization,
            "core_to_io_margin_um": core_to_io_margin_um,
        },
        "fragments": {
            # AI playbook may replace this with chip-specific floorplan tuning.
            "extra_floorplan_options": (
                "# (baseline) no extra floorplan options; "
                "verify any added command via search-eda-command before injecting"
            ),
        },
        "rationale": rationale,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Generate deterministic baseline decisions.yaml for floorplan.gen_floorplan."
    )
    parser.add_argument("--workspace", required=True, help="Flow workspace root")
    parser.add_argument("--step", required=True, help="Composite step id, e.g. floorplan.gen_floorplan")
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
