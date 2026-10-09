#!/usr/bin/env python3
"""Simulate a passing stage result for end-to-end flow debugging.

While real EDA tool integration is pending, stage sub-agents (floorplan, cts,
route, timing-eco) call this helper instead of invoking Innovus/Genus. It reads
the stage spec, picks plausible ``actual`` values within each metric's target
range, and writes a full pass result set to the run directory so the
orchestrator can progress through the state machine.

Generated files:
    <run_dir>/_meta.yaml          — with ``simulated: true`` marker
    <run_dir>/eval_result.yaml    — overall: pass, every metric status: pass
    <run_dir>/artifacts/<stage>.tcl
    <run_dir>/reports/<stage>_stub.rpt
    <workspace>/checkpoints/post_<stage>_<run_id>.def  (empty placeholder)

Replace each agent's simulator call with real EDA execution + report parsing
once the tool wrapper is in place.
"""
from __future__ import annotations


import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml


def pick_actual(target):
    """Return a plausible ``actual`` that sits inside the target range.

    The goal is only to mark the metric as pass — values don't need to be
    realistic, just inside bounds. Handles open-ended ranges and None.
    """
    if target is None:
        return 0
    if not isinstance(target, dict):
        return target  # scalar target — echo it back

    lo = target.get("min")
    hi = target.get("max")

    if lo is not None and hi is not None:
        return round((lo + hi) / 2, 4)
    if hi is not None:
        # Stay 30% below the cap, handle negatives gracefully
        return round(hi - abs(hi) * 0.3, 4) if hi != 0 else -0.1
    if lo is not None:
        return round(lo + abs(lo) * 0.1, 4) if lo != 0 else 0.1
    return 0


def pick_fail_actual(target):
    """Return an ``actual`` that deliberately violates the target (for fail sim).

    Overshoots ``max`` or undershoots ``min`` by ~20% (with a floor of 0.1 so
    metrics whose target is 0 still move out of range). When the target has no
    bounds at all, returns None — the orchestrator should still see status:fail.
    """
    if target is None or not isinstance(target, dict):
        return None
    lo = target.get("min")
    hi = target.get("max")
    if hi is not None:
        return round(hi + max(abs(hi) * 0.2, 0.1), 4)
    if lo is not None:
        return round(lo - max(abs(lo) * 0.2, 0.1), 4)
    return None


def simulate(
    workspace: Path,
    stage: str,
    run_dir: Path,
    spec_version: str,
    parent_run: str | None = None,
    force_fail: bool = False,
    fail_metrics: list[str] | None = None,
    recommendation: str | None = None,
    escalation_reason: str | None = None,
) -> tuple[dict, dict]:
    """Generate _meta.yaml + eval_result.yaml + stub artifacts.

    Default behavior: every metric passes, overall=pass, recommendation=proceed.

    Failure injection (for exercising retry/rollback/revise_spec paths):
        * ``force_fail=True`` — every metric fails
        * ``fail_metrics=["clock_skew", ...]`` — only these fail, the rest pass
        * ``recommendation`` — override the recommendation string (default:
            proceed on pass, retry on fail). Pass ``rollback`` to test cross-
            stage rollback or ``escalate`` to test budget-exhaust paths.
        * ``escalation_reason`` — free-form text attached when
            recommendation=escalate.

    Returns the two YAML dicts so the caller can log/echo them.
    """
    fail_metrics = set(fail_metrics or [])

    stage_spec_path = workspace / "spec" / "stages" / f"{stage}.yaml"
    if stage_spec_path.exists():
        stage_spec = yaml.safe_load(stage_spec_path.read_text()) or {}
    else:
        # Tolerate missing spec (e.g. on-demand stages like timing_eco) —
        # produce a minimal stub instead of failing the whole flow.
        stage_spec = {}
    metrics_spec = stage_spec.get("metrics") or []

    eval_metrics = []
    failed_names = []
    for m in metrics_spec:
        name = m.get("name") or "unnamed_metric"
        target = m.get("target")
        should_fail = force_fail or (name in fail_metrics)
        if should_fail:
            actual = pick_fail_actual(target)
            status = "fail"
            failed_names.append(name)
        else:
            actual = pick_actual(target)
            status = "pass"
        eval_metrics.append(
            {
                "name": name,
                "target": target,
                "actual": actual,
                "status": status,
            }
        )

    # Make sure at least one metric exists so the eval file isn't empty.
    if not eval_metrics:
        stub_status = "fail" if force_fail else "pass"
        if stub_status == "fail":
            failed_names.append("simulated_stub")
        eval_metrics.append(
            {
                "name": "simulated_stub",
                "target": {"min": None, "max": None},
                "actual": None if force_fail else 0,
                "status": stub_status,
            }
        )

    overall = "fail" if failed_names else "pass"

    if recommendation is None:
        recommendation = "retry" if overall == "fail" else "proceed"

    retry_context = None
    if overall == "fail" and recommendation == "retry":
        retry_context = {
            "failed_metrics": failed_names,
            "hint": (
                "Simulated failure for flow debugging. In a real run the agent "
                "would propose parameter adjustments (e.g. tighten target_skew, "
                "increase utilization margin) based on the violated metrics."
            ),
        }

    run_id = run_dir.name
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    checkpoint_rel = f"checkpoints/post_{stage}_{run_id}.def"

    meta = {
        "agent": f"{stage}_agent",
        "stage": stage,
        "run_id": run_id,
        "timestamp": now,
        "spec_version": spec_version,
        "parent_run": parent_run,
        "status": "completed" if overall != "fail" else "failed",
        "checkpoint": checkpoint_rel if overall != "fail" else None,
        "simulated": True,
    }

    eval_result = {
        "stage": stage,
        "run_id": run_id,
        "spec_version": spec_version,
        "overall": overall,
        "metrics": eval_metrics,
        "recommendation": recommendation,
        "retry_context": retry_context,
        "escalation_reason": escalation_reason if recommendation == "escalate" else None,
        "simulated": True,
        "note": (
            "SIMULATED result — EDA tools not invoked; values are synthetic stubs for flow debugging."
            + (f" Failure injected via force_fail={force_fail} fail_metrics={sorted(fail_metrics) or '[]'}." if overall == "fail" else "")
        ),
    }

    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "artifacts").mkdir(exist_ok=True)
    (run_dir / "reports").mkdir(exist_ok=True)

    (run_dir / "_meta.yaml").write_text(
        yaml.dump(meta, default_flow_style=False, allow_unicode=True, sort_keys=False)
    )
    (run_dir / "eval_result.yaml").write_text(
        yaml.dump(eval_result, default_flow_style=False, allow_unicode=True, sort_keys=False)
    )
    (run_dir / "artifacts" / f"{stage}.tcl").write_text(
        f"# SIMULATED {stage} Tcl script\n"
        f"# Placeholder — EDA tools not invoked during flow debugging.\n"
        f"# Replace with real script once {stage}-agent wraps Innovus/Genus.\n"
    )
    (run_dir / "reports" / f"{stage}_stub.rpt").write_text(
        f"# SIMULATED {stage} report\n"
        f"# Metrics in eval_result.yaml are synthetic — regenerate from real\n"
        f"# EDA reports once tool integration is wired.\n"
    )

    # Only emit a checkpoint placeholder when the run passes — failed runs
    # shouldn't leave downstream stages a valid handoff artifact.
    if overall != "fail":
        ckpt_path = workspace / checkpoint_rel
        ckpt_path.parent.mkdir(parents=True, exist_ok=True)
        if not ckpt_path.exists():
            ckpt_path.write_text(
                f"# SIMULATED checkpoint for {stage} {run_id}\n"
                f"# No actual DEF/DB data — placeholder for flow debugging.\n"
            )

    return meta, eval_result


def main():
    parser = argparse.ArgumentParser(
        description="Simulate a stage result (flow debug helper). "
        "Defaults to a fully-passing run; use --force-fail / --fail-metric "
        "to exercise retry / rollback / revise_spec paths."
    )
    parser.add_argument("--workspace", required=True, help="Workspace root path")
    parser.add_argument("--stage", required=True, help="Stage name (floorplan/cts/route/timing_eco)")
    parser.add_argument("--run-dir", required=True, help="Run directory (e.g. stages/floorplan/run_001)")
    parser.add_argument("--spec-version", required=True, help="Current spec version (e.g. v1)")
    parser.add_argument("--parent-run", default=None, help="Parent run id (for rollback), optional")
    parser.add_argument(
        "--force-fail",
        action="store_true",
        help="Mark every metric as fail (sets overall=fail).",
    )
    parser.add_argument(
        "--fail-metric",
        action="append",
        default=[],
        metavar="NAME",
        help="Mark a specific metric as fail (repeatable). Other metrics still pass.",
    )
    parser.add_argument(
        "--recommendation",
        choices=["proceed", "retry", "rollback", "escalate"],
        default=None,
        help="Override the recommendation field (default: proceed on pass, retry on fail).",
    )
    parser.add_argument(
        "--escalation-reason",
        default=None,
        help="Free-form text attached to eval_result when recommendation=escalate.",
    )
    args = parser.parse_args()

    try:
        meta, ev = simulate(
            Path(args.workspace),
            args.stage,
            Path(args.run_dir),
            args.spec_version,
            args.parent_run,
            force_fail=args.force_fail,
            fail_metrics=args.fail_metric,
            recommendation=args.recommendation,
            escalation_reason=args.escalation_reason,
        )
    except FileNotFoundError as e:
        print(json.dumps({"status": "error", "message": str(e)}))
        sys.exit(2)

    print(
        json.dumps(
            {
                "status": "ok",
                "simulated": True,
                "run_dir": str(args.run_dir),
                "meta": meta,
                "eval_result": ev,
            },
            default=str,
        )
    )


if __name__ == "__main__":
    main()
