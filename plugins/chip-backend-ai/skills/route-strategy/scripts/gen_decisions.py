#!/usr/bin/env python3
"""route-strategy / gen_decisions.py — deterministic baseline for route steps.

Covers BOTH route AI-decision steps that concern routing strategy (they share one
playbook because layer/NDR/shield choices in global route constrain the NanoRoute
options + post-route effort in detail route):
    - route.global_route  (layer assignment / clock-&-critical-net NDR / shielding)
    - route.detail_route   (NanoRoute options / post-route optimization effort)

It branches on --step to emit the right params/fragments for each template. This
is the *unattended default*: it reads the stage spec's `metrics` targets +
`parameters` and derives sane values so the flow runs without a human. The
SKILL.md playbook is where the AI improves on this baseline for a specific chip
(and where the search-eda-command guardrail lives).

Contract (shared by all decision steps — see docs/flow_impl_progress.md):
    gen_decisions.py --workspace <ws> --step <stage.step> \
        --spec <stage_spec.yaml> [--upstream-eval <eval_result.yaml>] \
        --out <ws>/<decisions-path>

The written decisions.yaml has:
    params:    keys EXACTLY match the template's {{placeholders}}
    fragments: keys match the template's `### @inject:<name>` blocks
    rationale: short prose for the audit trail

Templates covered:
    global_route.tcl.tmpl  placeholders: route_top_layer, route_bottom_layer,
                              ndr_name, ndr_spacing_mult, ndr_width_mult,
                              timing_driven, si_driven
                            inject:       critical_net_route_cmds
    detail_route.tcl.tmpl  placeholders: timing_driven, si_driven,
                              droute_end_iteration, route_with_eco,
                              postroute_opt_effort
                            inject:       nanoroute_opts
    (artifact_dir comes from --var, not here)
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


def _decisions_global_route(spec: dict, upstream_eval: dict) -> dict:
    params = spec.get("parameters") or {}

    # Routing layer window: keep global route inside the routable metal stack.
    route_top_layer = params.get("route_top_layer", "M7")
    route_bottom_layer = params.get("route_bottom_layer", "M1")

    # Clock / critical-net non-default routing rule (wider + spaced → low xtalk).
    ndr_name = params.get("ndr_name", "ROUTE_2W2S")
    ndr_spacing_mult = params.get("ndr_spacing_mult", 2)
    ndr_width_mult = params.get("ndr_width_mult", 2)

    # Timing- / SI-driven global routing on by default (closes timing, limits xtalk).
    timing_driven = params.get("timing_driven", "true")
    si_driven = params.get("si_driven", "true")

    # Nets that warrant NDR + shielding (clock / async / analog).
    shield_nets = params.get("shield_nets", "clk")
    critical_net_layers = params.get("critical_net_layers", "M5 M6")

    rationale = (
        f"Baseline global route: layer window {route_bottom_layer}..{route_top_layer}, "
        f"clock/critical-net NDR '{ndr_name}' ({ndr_width_mult}x width / "
        f"{ndr_spacing_mult}x spacing) preferred on layers '{critical_net_layers}', "
        f"shield nets '{shield_nets}', timing_driven={timing_driven}, "
        f"si_driven={si_driven}. Deterministic default from gen_decisions; refine "
        "via the route-strategy playbook — assign clock/critical nets to upper "
        "layers, widen/shield by congestion + crosstalk, and verify every NDR / "
        "shield command via search-eda-command before injecting."
    )

    return {
        "step": "route.global_route",
        "generated_by": "route-strategy/gen_decisions.py (deterministic baseline)",
        "generated_at": _now(),
        "simulated_baseline": True,
        "params": {
            "route_top_layer": route_top_layer,
            "route_bottom_layer": route_bottom_layer,
            "ndr_name": ndr_name,
            "ndr_spacing_mult": ndr_spacing_mult,
            "ndr_width_mult": ndr_width_mult,
            "timing_driven": timing_driven,
            "si_driven": si_driven,
        },
        "fragments": {
            # AI playbook may replace with verified setAttribute/addRouteShield etc.
            "critical_net_route_cmds": (
                f"# (baseline) NDR '{ndr_name}' + timing/SI-driven route on critical "
                f"& clock nets (e.g. layers {critical_net_layers}, shield {shield_nets}); "
                "verify any setAttribute/setNdrLayerRule/addRouteShield command "
                "via search-eda-command before injecting"
            ),
        },
        "rationale": rationale,
    }


def _decisions_detail_route(spec: dict, upstream_eval: dict) -> dict:
    params = spec.get("parameters") or {}

    # Keep timing-/SI-driven on through detail route as well.
    timing_driven = params.get("timing_driven", "true")
    si_driven = params.get("si_driven", "true")

    # NanoRoute effort: detail-route iteration budget + post-route opt level.
    droute_end_iteration = params.get("droute_end_iteration", params.get("nanoroute_effort", 5))
    route_with_eco = params.get("route_with_eco", "false")
    postroute_opt_effort = params.get("postroute_opt_level", params.get("postroute_opt_effort", "high"))

    rationale = (
        f"Baseline detail route: NanoRoute drouteEndIteration={droute_end_iteration}, "
        f"route_with_eco={route_with_eco}, timing_driven={timing_driven}, "
        f"si_driven={si_driven}, post-route opt effort '{postroute_opt_effort}'. "
        "Deterministic default from gen_decisions; refine via the route-strategy "
        "playbook — raise iterations/effort where DRC or timing residue remains, "
        "and verify any extra setNanoRouteMode option via search-eda-command "
        "before injecting."
    )

    return {
        "step": "route.detail_route",
        "generated_by": "route-strategy/gen_decisions.py (deterministic baseline)",
        "generated_at": _now(),
        "simulated_baseline": True,
        "params": {
            "timing_driven": timing_driven,
            "si_driven": si_driven,
            "droute_end_iteration": droute_end_iteration,
            "route_with_eco": route_with_eco,
            "postroute_opt_effort": postroute_opt_effort,
        },
        "fragments": {
            # AI playbook may replace with verified extra setNanoRouteMode options.
            "nanoroute_opts": (
                "# (baseline) no extra NanoRoute options; "
                "verify any setNanoRouteMode option (e.g. -routeWithLithoDriven / "
                "-drouteFixAntenna) via search-eda-command before injecting"
            ),
        },
        "rationale": rationale,
    }


def build_decisions(step: str, spec: dict, upstream_eval: dict) -> dict:
    # Branch on the bare step id (tolerate "stage.step" composite form).
    bare = step.split(".", 1)[1] if "." in step else step
    if bare == "global_route":
        return _decisions_global_route(spec, upstream_eval)
    if bare == "detail_route":
        return _decisions_detail_route(spec, upstream_eval)
    raise ValueError(
        f"route-strategy covers global_route / detail_route, not '{step}'"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Generate deterministic baseline decisions.yaml for route global_route / detail_route."
    )
    parser.add_argument("--workspace", required=True, help="Flow workspace root")
    parser.add_argument("--step", required=True,
                        help="Composite step id, e.g. route.global_route or route.detail_route")
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
