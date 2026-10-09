#!/usr/bin/env python3
"""timing-eco-design / gen_decisions.py — deterministic baseline for fix_strategy.

Emits a `decisions.yaml` for the timing_eco `fix_strategy` step (which timing
paths to fix and HOW — buffer insertion, gate resize / Vt-swap, useful skew,
local reroute, plus setup vs hold vs DRV tradeoffs). This is the *unattended
default*: it reads the stage spec's `metrics` targets (the WNS / TNS / hold slack
floors) + `parameters` and derives sane ECO settings so the flow runs without a
human. The SKILL.md playbook is where the AI improves on this baseline for a
specific chip (reading the signoff_sta timing report to pick paths and means, and
where the search-eda-command guardrail lives). The output is auditable and
re-renderable, and the step PRODUCES an ECO change-list artifact (eco.changes),
NOT a .def.

Contract (shared by all decision steps — see docs/flow_impl_progress.md):
    gen_decisions.py --workspace <ws> --step <stage.step> \
        --spec <stage_spec.yaml> [--upstream-eval <eval_result.yaml>] \
        --out <ws>/<decisions-path>

The written decisions.yaml has:
    params:    keys EXACTLY match the template's {{placeholders}}
    fragments: keys match the template's `### @inject:<name>` blocks
    rationale: short prose for the audit trail

Template covered: templates/tcl/timing_eco/fix_strategy.tcl.tmpl
    placeholders (design decisions): allow_setup_degrade, hold_target_slack_ns,
        setup_target_slack_ns, fix_drv, resize_enable, setup_buffer_cell,
        hold_buffer_cell, useful_skew_enable, setup_fix_effort, hold_fix_effort,
        max_buffer_count
    inject:       eco_ops
    (artifact_dir comes from --var; eco_route_mode is an apply_eco mechanical
     param sourced from the spec, not a fix_strategy decision)
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


def _is_negative_floor(target: dict) -> bool:
    """True if the slack floor (target.min) is negative — i.e. the gate tolerates
    some negative slack, signalling a chip that still needs real setup/hold work."""
    mn = target.get("min")
    try:
        return mn is not None and float(mn) < 0
    except (TypeError, ValueError):
        return False


def build_decisions(spec: dict, upstream_eval: dict) -> dict:
    params = spec.get("parameters") or {}

    # Slack floors (gate metrics) frame how hard the ECO needs to push.
    wns_target = _metric_target(spec, "wns_ns")
    tns_target = _metric_target(spec, "tns_ns")
    hold_target = _metric_target(spec, "hold_wns_ns")

    # If WNS/TNS floors are negative the chip still has setup debt → push effort
    # to high (unless the spec explicitly pins it).
    setup_pressure = _is_negative_floor(wns_target) or _is_negative_floor(tns_target)
    hold_pressure = _is_negative_floor(hold_target)

    setup_fix_effort = params.get(
        "setup_fix_effort", "high" if setup_pressure else "medium"
    )
    hold_fix_effort = params.get(
        "hold_fix_effort", "high" if (hold_pressure or setup_pressure) else "medium"
    )

    # ECO scale ceiling (guard against area/power blow-up).
    max_buffer_count = params.get("max_buffer_count", 5000)

    # Useful skew: borrow time across launch/capture instead of hard-buffering.
    useful_skew_enable = params.get("useful_skew_enable", "true")

    # ECO repair cells: setup repeater/buffer + hold delay cell.
    setup_buffer_cell = params.get("setup_buffer_cell", "BUFX4")
    hold_buffer_cell = params.get("hold_buffer_cell", "DLYX1")

    # Allow gate resize / Vt-swap on critical paths.
    resize_enable = params.get("resize_enable", "true")

    # Tolerate bounded setup/TNS degrade while fixing hold (hold must be clean).
    allow_setup_degrade = params.get("allow_setup_degrade", "true")

    # Repair target slacks (leave OCV/SI margin — don't close to exactly 0).
    hold_target_slack_ns = params.get("hold_target_slack_ns", 0.05)
    setup_target_slack_ns = params.get("setup_target_slack_ns", 0.0)

    # Sweep DRV (max_tran/max_cap/max_fanout) alongside the timing ECO.
    fix_drv = params.get("fix_drv", "true")

    rationale = (
        f"Baseline timing ECO: setup effort {setup_fix_effort} / hold effort "
        f"{hold_fix_effort} (setup_pressure={setup_pressure}, "
        f"hold_pressure={hold_pressure} from the WNS/TNS/hold slack floors); "
        f"repair via buffer insertion ({setup_buffer_cell} setup / "
        f"{hold_buffer_cell} hold), gate resize/Vt-swap (resize_enable="
        f"{resize_enable}) and useful skew (useful_skew_enable={useful_skew_enable}); "
        f"allow_setup_degrade={allow_setup_degrade} so hold closes while setup "
        f"iterates; target slacks hold {hold_target_slack_ns}ns / setup "
        f"{setup_target_slack_ns}ns leave OCV/SI margin; ECO capped at "
        f"{max_buffer_count} buffers; fix_drv={fix_drv}. Deterministic default "
        "from gen_decisions; refine via the timing-eco-design playbook — read the "
        "signoff_sta timing.rpt to pick the worst path groups, choose buffer vs "
        "resize vs useful skew vs reroute per gap, and verify any "
        "size_cell/insertRepeater/setUsefulSkewMode command via search-eda-command "
        "before injecting."
    )

    return {
        "step": "timing_eco.fix_strategy",
        "generated_by": "timing-eco-design/gen_decisions.py (deterministic baseline)",
        "generated_at": _now(),
        "simulated_baseline": True,
        "params": {
            "setup_fix_effort": setup_fix_effort,
            "hold_fix_effort": hold_fix_effort,
            "max_buffer_count": max_buffer_count,
            "useful_skew_enable": useful_skew_enable,
            "setup_buffer_cell": setup_buffer_cell,
            "hold_buffer_cell": hold_buffer_cell,
            "resize_enable": resize_enable,
            "allow_setup_degrade": allow_setup_degrade,
            "hold_target_slack_ns": hold_target_slack_ns,
            "setup_target_slack_ns": setup_target_slack_ns,
            "fix_drv": fix_drv,
        },
        "fragments": {
            # AI playbook may replace this with verified targeted ECO ops
            # (size_cell / insertRepeater / setUsefulSkewMode per path group).
            "eco_ops": (
                "# (baseline) rely on optDesign -setup/-hold + setEcoMode; "
                "verify any size_cell/insertRepeater/setUsefulSkewMode/ecoRoute "
                "command via search-eda-command before injecting"
            ),
        },
        "rationale": rationale,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Generate deterministic baseline decisions.yaml for timing_eco.fix_strategy."
    )
    parser.add_argument("--workspace", required=True, help="Flow workspace root")
    parser.add_argument("--step", required=True, help="Composite step id, e.g. timing_eco.fix_strategy")
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
