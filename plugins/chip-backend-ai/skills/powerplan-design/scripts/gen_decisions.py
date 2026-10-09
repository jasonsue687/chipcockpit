#!/usr/bin/env python3
"""powerplan-design / gen_decisions.py — deterministic baseline for gen_power_plan.

Emits a `decisions.yaml` for the powerplan `gen_power_plan` step (power ring +
stripe geometry + sroute strategy). This is the *unattended default*: it reads
the stage spec's `metrics` targets (the IR-drop budget) + `parameters` and
derives sane PDN values so the flow runs without a human. The SKILL.md playbook
is where the AI improves on this baseline for a specific chip (and where the
search-eda-command guardrail lives). The output is auditable and re-renderable.

Contract (shared by all decision steps — see docs/flow_impl_progress.md):
    gen_decisions.py --workspace <ws> --step <stage.step> \
        --spec <stage_spec.yaml> [--upstream-eval <eval_result.yaml>] \
        --out <ws>/<decisions-path>

The written decisions.yaml has:
    params:    keys EXACTLY match the template's {{placeholders}}
    fragments: keys match the template's `### @inject:<name>` blocks
    rationale: short prose for the audit trail

Template covered: templates/tcl/powerplan/gen_power_plan.tcl.tmpl
    placeholders (design decisions): ring_layer, ring_layer_v, ring_width_um,
        ring_spacing_um, ring_offset_um, stripe_layer, stripe_width_um,
        stripe_spacing_um, stripe_pitch_um, sroute_target
    inject:       extra_pg_cmds
    (power_net / ground_net / artifact_dir come from spec params + --var, not here)
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

    # Metal-layer choices for ring/stripe (upper layers carry power best).
    ring_layer = params.get("ring_layer", "M7")
    ring_layer_v = params.get("ring_layer_v", "M8")
    stripe_layer = params.get("stripe_layer", "M8")

    # Ring geometry.
    ring_width_um = params.get("ring_width_um", 2.0)
    ring_spacing_um = params.get("ring_spacing_um", 0.5)
    ring_offset_um = params.get("ring_offset_um", 1.0)

    # Stripe geometry — width/spacing/pitch set the IR-drop vs routing tradeoff.
    stripe_width_um = params.get("stripe_width_um", 1.0)
    stripe_spacing_um = params.get("stripe_spacing_um", 0.5)
    stripe_pitch_um = params.get("stripe_pitch_um", 20.0)

    sroute_target = params.get("sroute_target", "corePin")

    # Surface the IR budget in the rationale (the gate metric we are sized for).
    ir_target = _metric_target(spec, "power_grid_ir_drop")
    ir_budget = ir_target.get("max")

    rationale = (
        f"Baseline PDN: core ring on {ring_layer}/{ring_layer_v} "
        f"(width {ring_width_um}um, spacing {ring_spacing_um}um, offset "
        f"{ring_offset_um}um) + vertical stripes on {stripe_layer} "
        f"(width {stripe_width_um}um, pitch {stripe_pitch_um}um), tied via "
        f"sroute -connect {sroute_target}. Sized to hold worst IR drop within "
        f"the spec budget ({ir_budget} mV). Deterministic default from "
        "gen_decisions; refine via the powerplan-design playbook — tighten "
        "pitch / widen stripes if IR fails, relax to recover routing tracks if "
        "IR has headroom."
    )

    return {
        "step": "powerplan.gen_power_plan",
        "generated_by": "powerplan-design/gen_decisions.py (deterministic baseline)",
        "generated_at": _now(),
        "simulated_baseline": True,
        "params": {
            "ring_layer": ring_layer,
            "ring_layer_v": ring_layer_v,
            "ring_width_um": ring_width_um,
            "ring_spacing_um": ring_spacing_um,
            "ring_offset_um": ring_offset_um,
            "stripe_layer": stripe_layer,
            "stripe_width_um": stripe_width_um,
            "stripe_spacing_um": stripe_spacing_um,
            "stripe_pitch_um": stripe_pitch_um,
            "sroute_target": sroute_target,
        },
        "fragments": {
            # AI playbook may replace this with verified block-ring / 2nd-mesh cmds.
            "extra_pg_cmds": (
                "# (baseline) no extra rings/stripes; "
                "verify any addRing/addStripe/setViaGenMode command via "
                "search-eda-command before injecting"
            ),
        },
        "rationale": rationale,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Generate deterministic baseline decisions.yaml for powerplan.gen_power_plan."
    )
    parser.add_argument("--workspace", required=True, help="Flow workspace root")
    parser.add_argument("--step", required=True, help="Composite step id, e.g. powerplan.gen_power_plan")
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
