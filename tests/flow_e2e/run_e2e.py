#!/usr/bin/env python3
"""End-to-end flow harness — FULL FLOW import → tapeout.

Drives the flow engine from the *import* stage all the way to *tapeout* in
SIMULATION mode (no real EDA tool), runs the loop until flow_loader returns
`flow_complete`, and asserts ALL 8 quality gates PASS and every step is done.
The import-head version_check step runs first via a deterministic special-case
branch — no render/mock — so the recipe is 42 steps total.

    1. create a fresh workspace under tests/flow_e2e/runs/ws_<UTC>/
    2. copy fixtures into  <ws>/inputs/  and  <ws>/spec/
    3. flow_loader.py start  (snapshot recipe + init progress)
    4. loop flow_loader.py next until action == flow_complete:
         action=run, decision step (step has a `decisions:` field)
             → skills/<ref>/scripts/gen_decisions.py → decisions.yaml
             → render the step's `template` (with --decisions) to <ws>/.../<step>.tcl
             → run_eda_script.py --mock (+ --report/--stage/--spec if a .rpt output)
         action=run, executor=run-eda-script (mechanical)
             → render the step's `template` (if any), then run_eda_script.py --mock
         action=run, executor=version-check  (import-head, FIRST step)
             → skills/version-check/scripts/version_check.py --input <each
               required input> --out <ws>/<version_check_rpt> (deterministic;
               no render/mock). Asserts status == ok (CONSISTENT).
         action=run, executor=parse-eda-report
             → router.py parse-report --simulated against the gate report + spec
         action=await_human
             → SIMULATED auto-resolve: flow_loader.py resolve-human, then continue
             (covers floorplan.confirm_macro, signoff.waiver_review,
              tapeout.final_checklist — the terminal human step before completion)
         then flow_loader.py mark <step> done
       The NORMAL terminal condition is action == flow_complete (tapeout has NO
       gate; after final_checklist resolves, next returns flow_complete). A
       safety max-iteration cap guards against an infinite loop.
    5. print flow_loader status + ALL eval_result.yaml files; assert:
         (1) all 8 gates overall==pass + simulated==true,
         (2) the driver's final action == flow_complete,
         (3) status shows ALL 42 steps done (done == total, percent == 100.0).
       Print a loud "FULL FLOW COMPLETE: 42/42 steps done, 8/8 gates pass"
       banner on success; exit nonzero with a clear message on any failure.

Exit 0 on success, nonzero otherwise.

Everything it touches is loudly labeled SIMULATED — this validates flow plumbing
and gate logic, NOT real PPA.
"""

import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
PLUGIN_ROOT = HERE.parent.parent / "plugins" / "chip-backend-ai"
FIXTURES = HERE / "fixtures"
RUNS = HERE / "runs"

FLOW_DEF = PLUGIN_ROOT / "templates" / "flow_definition.yaml"
TEMPLATES_DIR = PLUGIN_ROOT / "templates"
SKILLS_DIR = PLUGIN_ROOT / "skills"
FLOW_LOADER = PLUGIN_ROOT / "core" / "workflow" / "flow_loader.py"
RENDER_TCL = PLUGIN_ROOT / "skills" / "render-tcl" / "scripts" / "render_tcl.py"
RUN_EDA = PLUGIN_ROOT / "skills" / "run-eda-script" / "scripts" / "run_eda_script.py"
VERSION_CHECK = PLUGIN_ROOT / "skills" / "version-check" / "scripts" / "version_check.py"
ROUTER = PLUGIN_ROOT / "core" / "router.py"

# M8 = full flow: the harness now drives all the way to flow_complete (no
# STOP-at-gate early-exit). tapeout has NO gate, so the terminal condition is
# action == flow_complete after the final human step (tapeout.final_checklist).

# Total number of steps in the recipe; the run must finish with every one done.
# DERIVED from the flow definition so it self-updates when steps are added/removed
# (e.g. the per-stage human-confirm gates) — never hardcode this count.
_FLOW_DEF_DOC = yaml.safe_load(FLOW_DEF.read_text(encoding="utf-8"))
EXPECTED_TOTAL_STEPS = sum(len(s.get("steps", [])) for s in _FLOW_DEF_DOC.get("stages", []))

# The 8 gates we assert PASS at the end (one per gated stage; tapeout has none).
ASSERT_GATES = [
    ("import", "stages/import/eval_result.yaml"),
    ("floorplan", "stages/floorplan/eval_result.yaml"),
    ("powerplan", "stages/powerplan/eval_result.yaml"),
    ("placement", "stages/placement/eval_result.yaml"),
    ("cts", "stages/cts/eval_result.yaml"),
    ("route", "stages/route/eval_result.yaml"),
    ("timing_eco", "stages/timing_eco/eval_result.yaml"),
    ("signoff", "stages/signoff/eval_result.yaml"),
]

# Decision steps may take the *upstream* stage's gate eval as a diagnostic hint
# (retry loop). Maps the stage being run → the upstream stage whose eval to feed.
# (signoff/tapeout are zero-decision, so they never consult these, but the map
# stays complete for symmetry / future retry paths.)
UPSTREAM_STAGE = {
    "floorplan": "import",
    "powerplan": "floorplan",
    "placement": "powerplan",
    "cts": "placement",
    "route": "cts",
    "timing_eco": "route",
    "signoff": "timing_eco",
    "tapeout": "signoff",
}

PY = sys.executable or "python3"


def run_cli(argv: list[str]) -> subprocess.CompletedProcess:
    """Run a subprocess, echo it, and return the completed process."""
    print(f"  $ {' '.join(str(a) for a in argv)}")
    return subprocess.run(argv, capture_output=True, text=True)


def run_json(argv: list[str]) -> dict:
    """Run a CLI that prints a single JSON object on stdout; return it."""
    proc = run_cli(argv)
    if proc.returncode != 0 and not proc.stdout.strip():
        sys.exit(f"FAIL: command errored (rc={proc.returncode}):\n{proc.stderr}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        sys.exit(f"FAIL: expected JSON on stdout, got:\n{proc.stdout}\n{proc.stderr}")


def make_workspace() -> Path:
    """Create a fresh, minimal workspace and copy fixtures into it."""
    RUNS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    ws = RUNS / f"ws_{stamp}"
    # Minimal layout (workspace.py-compatible subset; flow_loader pre-creates the rest).
    (ws / "inputs").mkdir(parents=True)
    (ws / "spec" / "stages").mkdir(parents=True)
    (ws / "state").mkdir(parents=True)
    (ws / "stages").mkdir(parents=True)
    (ws / "checkpoints").mkdir(parents=True)

    # Copy fixtures: inputs/ and spec/ (incl. spec/stages/).
    for f in (FIXTURES / "inputs").iterdir():
        shutil.copy2(f, ws / "inputs" / f.name)
    shutil.copy2(FIXTURES / "spec" / "global_spec.yaml", ws / "spec" / "global_spec.yaml")
    for f in (FIXTURES / "spec" / "stages").iterdir():
        shutil.copy2(f, ws / "spec" / "stages" / f.name)
    return ws


def stage_spec_path(ws: Path, stage: str) -> Path:
    return ws / "spec" / "stages" / f"{stage}.yaml"


def gen_decisions(ws: Path, stage: str, step: str, ref: str, decisions_rel: str) -> Path:
    """Run skills/<ref>/scripts/gen_decisions.py to produce a step's decisions.yaml.

    The decision skill emits a deterministic baseline so the flow runs unattended
    (the SKILL.md playbook is where a live AI improves on it). Returns the path
    to the written decisions.yaml.
    """
    gen = SKILLS_DIR / ref / "scripts" / "gen_decisions.py"
    if not gen.exists():
        sys.exit(f"FAIL: decision skill '{ref}' has no gen_decisions.py at {gen}")
    out_dec = ws / decisions_rel

    argv = [
        PY, str(gen),
        "--workspace", str(ws),
        "--step", f"{stage}.{step}",
        "--spec", str(stage_spec_path(ws, stage)),
        "--out", str(out_dec),
    ]
    # Feed the upstream stage gate eval back as a diagnostic hint when present.
    upstream_stage = UPSTREAM_STAGE.get(stage)
    if upstream_stage:
        upstream_eval = ws / "stages" / upstream_stage / "eval_result.yaml"
        if upstream_eval.exists():
            argv += ["--upstream-eval", str(upstream_eval)]

    result = run_json(argv)
    if result.get("status") != "ok":
        sys.exit(f"FAIL: gen_decisions for {stage}.{step} ({ref}): {json.dumps(result, indent=2)}")
    return out_dec


def render_step_tcl(ws: Path, stage: str, step: str, template_rel: str,
                    decisions_path: Path | None = None) -> Path:
    """Render a step's golden template into <ws>/stages/<stage>/scripts/<step>.tcl.

    Supplies workspace-derived file paths via --var (highest precedence) on top
    of the stage spec's top-level scalars + parameters, plus an optional
    --decisions file (params fill {{placeholders}}, fragments fill `### @inject:`).
    """
    template = TEMPLATES_DIR / template_rel
    out_tcl = ws / "stages" / stage / "scripts" / f"{step}.tcl"
    report_dir = ws / "stages" / stage / "reports"
    artifact_dir = ws / "stages" / stage / "artifacts"
    report_dir.mkdir(parents=True, exist_ok=True)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    # Concrete paths the templates reference that aren't design decisions.
    # report_dir / artifact_dir are the canonical per-stage output dirs; templates
    # write reports to {{report_dir}}/<f> and DEF/DB artifacts to {{artifact_dir}}/<f>.
    var_pairs = [
        f"netlist={ws / 'inputs' / 'netlist.v'}",
        f"lef={ws / 'inputs' / 'tech.lef'}",
        f"lib={ws / 'inputs' / 'cells.lib'}",
        f"sdc={ws / 'inputs' / 'constraints.sdc'}",
        f"lib_search_path={ws / 'inputs'}",
        f"report_dir={report_dir}",
        f"artifact_dir={artifact_dir}",
    ]

    argv = [
        PY, str(RENDER_TCL),
        "--template", str(template),
        "--out", str(out_tcl),
        "--spec", str(stage_spec_path(ws, stage)),
    ]
    if decisions_path is not None:
        argv += ["--decisions", str(decisions_path)]
    for v in var_pairs:
        argv += ["--var", v]

    result = run_json(argv)
    if result.get("status") != "ok":
        sys.exit(f"FAIL: render-tcl for {stage}.{step}: {json.dumps(result, indent=2)}")
    return out_tcl


def run_eda_step(ws: Path, stage: str, step: str, action: dict, tcl: Path) -> dict:
    """Execute a run-eda-script step in --mock mode (SIMULATED)."""
    outputs = action.get("outputs", []) or []
    log = ws / "stages" / stage / "logs" / f"{step}.log"
    log.parent.mkdir(parents=True, exist_ok=True)

    argv = [PY, str(RUN_EDA), "--mock", "--script", str(tcl), "--log", str(log)]
    rpt_output = None
    for o in outputs:
        out_path = ws / o["path"]
        argv += ["--expect-output", str(out_path)]
        if o["path"].endswith(".rpt"):
            rpt_output = out_path

    # If this step produces a .rpt, also generate parseable SIMULATED metrics
    # into it (so the downstream gate can extract values and PASS).
    if rpt_output is not None:
        argv += [
            "--report", str(rpt_output),
            "--stage", stage,
            "--spec", str(stage_spec_path(ws, stage)),
        ]

    result = run_json(argv)
    if result.get("status") != "mock":
        sys.exit(f"FAIL: run-eda-script (mock) for {stage}.{step}: {json.dumps(result, indent=2)}")
    return result


def run_version_check(ws: Path, stage: str, step: str, action: dict) -> dict:
    """Run skills/version-check for the import-head version_check step.

    Deterministic, no render/mock (mirrors the parse-eda-report special-case):
    feed every required input file and write the declared version_check.rpt
    output. The SIMULATED fixtures all carry a matching `release:` marker, so the
    check is CONSISTENT and exits 0.
    """
    out_rpt = None
    for o in action.get("outputs", []) or []:
        if o["path"].endswith(".rpt"):
            out_rpt = ws / o["path"]
            break
    if out_rpt is None:
        sys.exit(f"FAIL: version_check {stage}.{step} has no .rpt output to write")

    argv = [PY, str(VERSION_CHECK), "--out", str(out_rpt)]
    for inp in action.get("inputs", []) or []:
        argv += ["--input", str(ws / inp["path"])]

    result = run_json(argv)
    if result.get("status") != "ok":
        sys.exit(f"FAIL: version-check for {stage}.{step}: {json.dumps(result, indent=2)}")
    return result


def run_gate(ws: Path, stage: str, step: str, step_def: dict, action: dict) -> dict:
    """Run parse-eda-report (router) for a gate step; return the eval_result."""
    report_rel = step_def.get("report")
    if not report_rel:
        # Fall back to the first required .rpt input if `report:` wasn't declared.
        for inp in action.get("inputs", []) or []:
            if inp["path"].endswith(".rpt"):
                report_rel = inp["path"]
                break
    if not report_rel:
        sys.exit(f"FAIL: gate {stage}.{step} has no report to parse")

    out_eval = None
    for o in action.get("outputs", []) or []:
        if o["path"].endswith("eval_result.yaml"):
            out_eval = ws / o["path"]
            break

    argv = [
        PY, str(ROUTER), "parse-report",
        "--report", str(ws / report_rel),
        "--spec", str(stage_spec_path(ws, stage)),
        "--stage", stage,
        "--run-id", "run_001",
        "--spec-version", "v1",
        # The whole harness runs in mock mode → every report is SIMULATED.
        "--simulated",
    ]
    if out_eval is not None:
        argv += ["--output", str(out_eval)]

    # router.py `ok()` prints the eval_result dict directly to stdout (no
    # status/data wrapper); `err()` prints {"error": ...} to stderr + rc!=0
    # (handled by run_json). So the parsed JSON IS the eval_result.
    return run_json(argv)


def step_def_for(flow_def: dict, step_id: str) -> dict:
    for stage in flow_def.get("stages", []):
        for step in stage.get("steps", []):
            if f"{stage['id']}.{step['id']}" == step_id:
                return step
    return {}


# Human steps the run must auto-resolve before it can reach flow_complete.
# DERIVED from the flow definition (every executor.type == human step) so new
# per-stage confirm gates are asserted automatically — never hardcode this set.
EXPECTED_HUMAN_STEPS = {
    f"{s['id']}.{st['id']}"
    for s in _FLOW_DEF_DOC.get("stages", [])
    for st in s.get("steps", [])
    if st.get("executor", {}).get("type") == "human"
}


def main() -> int:
    print("=== FULL FLOW import → tapeout e2e (SIMULATION mode) ===")
    print("=== drive flow_loader.next until action == flow_complete ===")
    flow_def = yaml.safe_load(FLOW_DEF.read_text(encoding="utf-8"))

    ws = make_workspace()
    print(f"workspace: {ws}")

    # start the flow
    run_json([PY, str(FLOW_LOADER), "start", "--workspace", str(ws), "--flow", str(FLOW_DEF)])

    # Safety cap: ~48 steps + human gates; generous headroom for retries without hanging.
    max_iters = 200
    final_action = None
    resolved_humans: set[str] = set()
    for _ in range(max_iters):
        action = run_json([PY, str(FLOW_LOADER), "next", "--workspace", str(ws)])
        act = action.get("action")
        step_id = action.get("step_id")
        print(f"-> next: action={act} step={step_id}")

        if act == "flow_complete":
            # NORMAL terminal condition — the whole recipe is done.
            final_action = act
            break
        if act in ("blocked", "blocked_inputs"):
            sys.exit(f"FAIL: flow blocked: {json.dumps(action, indent=2)}")

        if act == "await_human":
            # SIMULATION: never hard-exit on a human gate — auto-resolve and continue.
            print(f"# SIMULATED auto-resolve: human gate {step_id}")
            run_json([PY, str(FLOW_LOADER), "resolve-human", "--workspace", str(ws),
                      "--step", step_id, "--note", "SIMULATED auto-resolve"])
            resolved_humans.add(step_id)
            continue

        if act != "run":
            sys.exit(f"FAIL: unexpected action: {json.dumps(action, indent=2)}")

        stage = action["stage"]
        step = step_id.split(".", 1)[1]
        sdef = step_def_for(flow_def, step_id)
        ref = action.get("executor", {}).get("ref")
        decisions_rel = sdef.get("decisions")

        if decisions_rel:
            # ---- AI decision step (gen → render → run) --------------------
            template_rel = sdef.get("template")
            if not template_rel:
                sys.exit(f"FAIL: decision step {step_id} has 'decisions' but no 'template'")
            dec_path = gen_decisions(ws, stage, step, ref, decisions_rel)
            tcl = render_step_tcl(ws, stage, step, template_rel, decisions_path=dec_path)
            run_eda_step(ws, stage, step, action, tcl)
        elif ref == "run-eda-script":
            template_rel = sdef.get("template")
            if template_rel:
                tcl = render_step_tcl(ws, stage, step, template_rel)
            else:
                # No template declared: write a tiny SIMULATED placeholder script.
                tcl = ws / "stages" / stage / "scripts" / f"{step}.tcl"
                tcl.parent.mkdir(parents=True, exist_ok=True)
                tcl.write_text(f"# SIMULATED placeholder script for {step} (no template)\n")
            run_eda_step(ws, stage, step, action, tcl)
        elif ref == "version-check":
            vc = run_version_check(ws, stage, step, action)
            print(f"   version-check status={vc.get('status')} release={vc.get('release')}")
        elif ref == "parse-eda-report":
            ev = run_gate(ws, stage, step, sdef, action)
            print(f"   gate eval overall={ev.get('overall')} simulated={ev.get('simulated')}")
        else:
            sys.exit(f"FAIL: unknown executor ref '{ref}' for {step_id}")

        run_json([PY, str(FLOW_LOADER), "mark", "--workspace", str(ws),
                  "--step", step_id, "--status", "done"])
    else:
        sys.exit(f"FAIL: max iterations ({max_iters}) hit without reaching flow_complete")

    # ---- assert (3): the driver's final action == flow_complete -------------
    if final_action != "flow_complete":
        sys.exit(f"FAIL: flow did not reach flow_complete (final action = {final_action})")

    # ---- verify all 3 human steps auto-resolved ----------------------------
    missing_humans = EXPECTED_HUMAN_STEPS - resolved_humans
    if missing_humans:
        sys.exit(f"FAIL: expected human gates were never auto-resolved: {sorted(missing_humans)}")
    print(f"\n=== human gates auto-resolved: {sorted(resolved_humans)} ===")

    # ---- report ------------------------------------------------------------
    print("\n=== flow_loader status ===")
    status = run_json([PY, str(FLOW_LOADER), "status", "--workspace", str(ws)])
    print(json.dumps(status, ensure_ascii=False, indent=2))

    # ---- assert (1): all 8 gates overall==pass + simulated==true ------------
    all_pass = True
    for stage, eval_rel in ASSERT_GATES:
        eval_path = ws / eval_rel
        print(f"\n=== {stage} eval_result.yaml ({eval_path}) ===")
        if not eval_path.exists():
            sys.exit(f"FAIL: {stage} eval_result.yaml was not written")
        eval_text = eval_path.read_text(encoding="utf-8")
        print(eval_text)
        ev = yaml.safe_load(eval_text)
        overall = ev.get("overall")
        simulated = ev.get("simulated")
        print(f"--- {stage}_eval overall == 'pass' (got: {overall}); simulated == True (got: {simulated}) ---")
        if overall != "pass" or simulated is not True:
            all_pass = False

    if not all_pass:
        sys.exit("FAIL: one or more gates did not pass (or was not marked simulated)")

    # ---- assert (3): every step done (done == total, percent == 100) --------
    total = status.get("total_steps")
    done = status.get("done")
    percent = status.get("percent")
    if total != EXPECTED_TOTAL_STEPS:
        sys.exit(f"FAIL: expected {EXPECTED_TOTAL_STEPS} total steps, recipe has {total}")
    if done != total or percent != 100.0:
        not_done = [s["step_id"] for s in status.get("steps", []) if s["status"] not in ("done", "skipped")]
        sys.exit(f"FAIL: not all steps done ({done}/{total}, {percent}%). Not done: {not_done}")

    # ---- success banner -----------------------------------------------------
    print("\n" + "=" * 64)
    print(f"FULL FLOW COMPLETE: {done}/{total} steps done, {len(ASSERT_GATES)}/{len(ASSERT_GATES)} gates pass")
    print("=" * 64)
    print("import → floorplan → powerplan → placement → cts → route → "
          "timing_eco → signoff → tapeout ran end-to-end to flow_complete")
    print(f"all {len(ASSERT_GATES)} gates overall == pass + simulated == true; all "
          f"{len(EXPECTED_HUMAN_STEPS)} human steps {sorted(resolved_humans)} "
          "auto-resolved (SIMULATION).")
    print(f"(workspace kept at {ws} for inspection)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
