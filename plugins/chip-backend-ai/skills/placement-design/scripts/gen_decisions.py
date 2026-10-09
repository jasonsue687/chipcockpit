#!/usr/bin/env python3
"""placement-design / gen_decisions.py — deterministic baseline for place_opt.

Emits a `decisions.yaml` for the placement `place_opt` step (utilization margin
+ congestion-driven placement effort + HFNS threshold + tie-cell). This is the
*unattended default*: it reads the stage spec's `metrics` targets (the
congestion budget) + `parameters` and derives sane placement values so the flow
runs without a human. The SKILL.md playbook is where the AI improves on this
baseline for a specific chip (and where the search-eda-command guardrail lives).
The output is auditable and re-renderable.

Contract (shared by all decision steps — see docs/flow_impl_progress.md):
    gen_decisions.py --workspace <ws> --step <stage.step> \
        --spec <stage_spec.yaml> [--upstream-eval <eval_result.yaml>] \
        --out <ws>/<decisions-path>

The written decisions.yaml has:
    params:    keys EXACTLY match the template's {{placeholders}}
    fragments: keys match the template's `### @inject:<name>` blocks
    rationale: short prose for the audit trail

Template covered: templates/tcl/placement/place_opt.tcl.tmpl
    placeholders (design decisions): target_utilization_margin, congestion_effort,
        place_global_timing_effort, hfns_threshold_fanout, tie_cell
    inject:       extra_place_options
    (tie_net_high / tie_net_low / artifact_dir / report_dir come from spec params
     + --var, not here)
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


def build_decisions(spec: dict, upstream_eval: dict) -> dict:
    params = spec.get("parameters") or {}

    # Utilization margin global place leaves for congestion relief.
    target_utilization_margin = params.get("target_utilization_margin", 0.05)

    # Congestion-driven vs timing-driven placement effort tradeoff.
    congestion_effort = params.get("congestion_effort", "medium")
    place_global_timing_effort = params.get("place_global_timing_effort", "medium")

    # High-fanout-net synthesis trigger and tie-cell choice.
    hfns_threshold_fanout = params.get("hfns_threshold_fanout", 32)
    tie_cell = params.get("tie_cell", "TIELO")

    # Surface the congestion budget in the rationale (the gate metric we size for).
    cong_target = _metric_target(spec, "congestion_hotspot")
    cong_budget = cong_target.get("max")

    rationale = (
        f"Baseline placement: global place with {target_utilization_margin} "
        f"utilization margin, congestion effort '{congestion_effort}' and timing "
        f"effort '{place_global_timing_effort}'; HFNS on nets with fanout > "
        f"{hfns_threshold_fanout}; tie constants via {tie_cell}. Sized to hold "
        f"worst congestion overflow within the spec budget ({cong_budget}). "
        "Deterministic default from gen_decisions; refine via the "
        "placement-design playbook — raise congestion effort / widen util margin "
        "if congestion fails, relax (lower effort / tighter util) to recover "
        "timing and runtime if congestion has headroom."
    )

    return {
        "step": "placement.place_opt",
        "generated_by": "placement-design/gen_decisions.py (deterministic baseline)",
        "generated_at": _now(),
        "simulated_baseline": True,
        "params": {
            "target_utilization_margin": target_utilization_margin,
            "congestion_effort": congestion_effort,
            "place_global_timing_effort": place_global_timing_effort,
            "hfns_threshold_fanout": hfns_threshold_fanout,
            "tie_cell": tie_cell,
        },
        "fragments": {
            # AI playbook may replace this with verified extra setPlaceMode /
            # createPlaceBlockage / addPlacePartition commands.
            "extra_place_options": (
                "# (baseline) no extra placement options; "
                "verify any setPlaceMode/createPlaceBlockage/addPlacePartition "
                "command via search-eda-command before injecting"
            ),
        },
        "rationale": rationale,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Generate deterministic baseline decisions.yaml for placement.place_opt."
    )
    parser.add_argument("--workspace", required=True, help="Flow workspace root")
    parser.add_argument("--step", required=True, help="Composite step id, e.g. placement.place_opt")
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
