#!/usr/bin/env python3
"""route-drc-repair / gen_decisions.py — deterministic baseline for drc_repair.

Emits a `decisions.yaml` for the route `drc_repair` step (which DRC / antenna
violations to fix and HOW — ECO search & repair, redundant via insertion). This
is the *unattended default*: it reads the stage spec's `metrics` target (the DRC
budget) + `parameters` and derives sane repair settings so the flow runs without
a human. The SKILL.md playbook is where the AI improves on this baseline for a
specific chip (and where the search-eda-command guardrail lives), including the
iterative verify → targeted repair → re-verify diagnostic loop.

Contract (shared by all decision steps — see docs/flow_impl_progress.md):
    gen_decisions.py --workspace <ws> --step <stage.step> \
        --spec <stage_spec.yaml> [--upstream-eval <eval_result.yaml>] \
        --out <ws>/<decisions-path>

The written decisions.yaml has:
    params:    keys EXACTLY match the template's {{placeholders}}
    fragments: keys match the template's `### @inject:<name>` blocks
    rationale: short prose for the audit trail

Template covered: templates/tcl/route/drc_repair.tcl.tmpl
    placeholders (design decisions): drc_report_limit, antenna_fix_mode,
        antenna_diode_cell, via_in_pin, redundant_via_effort
    inject:       drc_repair_cmds
    (report_dir / artifact_dir come from --var, not here)
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

    # The DRC budget (gate metric) frames how aggressively we repair.
    drc_target = _metric_target(spec, "drc_violations")
    drc_budget = drc_target.get("max")

    # Report enough violations to diagnose; default generous so nothing is hidden.
    drc_report_limit = params.get("drc_report_limit", 1000)

    # Antenna fix during repair + the diode cell to insert.
    antenna_fix_mode = params.get("antenna_fix_mode", "true")
    antenna_diode_cell = params.get("antenna_diode_cell", "ANTENNA")

    # Redundant (double) via insertion for yield/EM after DRC-clean.
    via_in_pin = params.get("via_in_pin", "true")
    redundant_via_effort = params.get("redundant_via", params.get("redundant_via_effort", 2))

    rationale = (
        f"Baseline DRC/antenna repair: verify_drc (limit {drc_report_limit}), ECO "
        f"search & repair (ecoRoute -fix_drc), antenna fix={antenna_fix_mode} with "
        f"diode '{antenna_diode_cell}', redundant via insertion "
        f"(via_in_pin={via_in_pin}, effort {redundant_via_effort}); DRC gate budget "
        f"{drc_budget} (target clean). Deterministic default from gen_decisions; "
        "refine via the route-drc-repair playbook — run the verify → targeted "
        "repair → re-verify loop, classify shorts vs spacing vs antenna, and verify "
        "any editDelete/ecoRoute/addVias command via search-eda-command before injecting."
    )

    return {
        "step": "route.drc_repair",
        "generated_by": "route-drc-repair/gen_decisions.py (deterministic baseline)",
        "generated_at": _now(),
        "simulated_baseline": True,
        "params": {
            "drc_report_limit": drc_report_limit,
            "antenna_fix_mode": antenna_fix_mode,
            "antenna_diode_cell": antenna_diode_cell,
            "via_in_pin": via_in_pin,
            "redundant_via_effort": redundant_via_effort,
        },
        "fragments": {
            # AI playbook may replace with verified targeted repair commands.
            "drc_repair_cmds": (
                "# (baseline) rely on ecoRoute -fix_drc + addVias; "
                "verify any editDelete/ecoRoute/setNanoRouteMode/addVias command "
                "via search-eda-command before injecting"
            ),
        },
        "rationale": rationale,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Generate deterministic baseline decisions.yaml for route.drc_repair."
    )
    parser.add_argument("--workspace", required=True, help="Flow workspace root")
    parser.add_argument("--step", required=True, help="Composite step id, e.g. route.drc_repair")
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
