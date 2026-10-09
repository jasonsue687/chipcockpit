#!/usr/bin/env python3
"""cts-design / gen_decisions.py — deterministic baseline for gen_cts_spec.

Emits a `decisions.yaml` for the cts `gen_cts_spec` step (target skew + clock-net
NDR + clock buffer/inverter leaf cells + skew group + max fanout). This is the
*unattended default*: it reads the stage spec's `metrics` targets (the skew and
insertion-delay budgets) + `parameters` and derives sane CTS spec values so the
flow runs without a human. The SKILL.md playbook is where the AI improves on this
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

Template covered: templates/tcl/cts/gen_cts_spec.tcl.tmpl
    placeholders (design decisions): target_skew_ps, target_max_trans_ps, max_fanout,
        ndr_name, ndr_spacing_mult, ndr_width_mult, clock_buffer_cell,
        clock_inverter_cell, use_inverters, skew_group
    inject:       extra_ccopt_props
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


def build_decisions(spec: dict, upstream_eval: dict) -> dict:
    params = spec.get("parameters") or {}

    # Skew / insertion-delay budgets (gate metrics) frame the CTS targets.
    skew_target = _metric_target(spec, "global_skew_ps")
    skew_budget = skew_target.get("max")
    insertion_target = _metric_target(spec, "max_insertion_delay_ps")
    insertion_budget = insertion_target.get("max")

    # Target skew: aim comfortably under the skew gate budget when present,
    # else fall back to the spec parameter.
    if skew_budget is not None:
        target_skew_ps = params.get("target_skew_ps", round(float(skew_budget) * 0.75, 2))
    else:
        target_skew_ps = params.get("target_skew_ps", 50)

    # DRV transition target (max_tran on clock nets).
    target_max_trans_ps = params.get("target_max_trans_ps", 100)

    # Max fanout per clock buffer (smaller → flatter tree, lower skew, more cells).
    max_fanout = params.get("max_fanout", 32)

    # Non-default routing rule for clock nets (wider + spaced → lower variation).
    ndr_name = params.get("ndr_name", "CTS_2W2S")
    ndr_spacing_mult = params.get("ndr_spacing_mult", 2)
    ndr_width_mult = params.get("ndr_width_mult", 2)

    # Clock-tree leaf cells (buffer + inverter) and whether to use inverters.
    clock_buffer_cell = params.get("clock_buffer_cell", "CLKBUF")
    clock_inverter_cell = params.get("clock_inverter_cell", "CLKINV")
    use_inverters = params.get("use_inverters", "true")

    # Skew group balancing this clock domain together.
    skew_group = params.get("skew_group", "main_clk_group")

    rationale = (
        f"Baseline CTS spec: target skew {target_skew_ps}ps (sized under the skew "
        f"gate budget {skew_budget}ps), clock-net NDR '{ndr_name}' "
        f"({ndr_width_mult}x width / {ndr_spacing_mult}x spacing), leaf cells "
        f"{clock_buffer_cell}/{clock_inverter_cell} (use_inverters={use_inverters}), "
        f"max fanout {max_fanout} per buffer, skew group '{skew_group}'; "
        f"max insertion-delay budget {insertion_budget}ps. "
        "Deterministic default from gen_decisions; refine via the cts-design "
        "playbook — tighten target skew / NDR or lower max_fanout if skew fails, "
        "trade insertion delay vs skew, and add exclude pins / extra skew groups "
        "for I/O or gated clocks."
    )

    return {
        "step": "cts.gen_cts_spec",
        "generated_by": "cts-design/gen_decisions.py (deterministic baseline)",
        "generated_at": _now(),
        "simulated_baseline": True,
        "params": {
            "target_skew_ps": target_skew_ps,
            "target_max_trans_ps": target_max_trans_ps,
            "max_fanout": max_fanout,
            "ndr_name": ndr_name,
            "ndr_spacing_mult": ndr_spacing_mult,
            "ndr_width_mult": ndr_width_mult,
            "clock_buffer_cell": clock_buffer_cell,
            "clock_inverter_cell": clock_inverter_cell,
            "use_inverters": use_inverters,
            "skew_group": skew_group,
        },
        "fragments": {
            # AI playbook may replace this with verified extra set_ccopt_property /
            # create_ccopt_skew_group / exclude-pin commands.
            "extra_ccopt_props": (
                "# (baseline) no extra ccopt properties; "
                "verify any set_ccopt_property/create_ccopt_skew_group command "
                "via search-eda-command before injecting"
            ),
        },
        "rationale": rationale,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Generate deterministic baseline decisions.yaml for cts.gen_cts_spec."
    )
    parser.add_argument("--workspace", required=True, help="Flow workspace root")
    parser.add_argument("--step", required=True, help="Composite step id, e.g. cts.gen_cts_spec")
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
