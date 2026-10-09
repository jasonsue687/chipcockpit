#!/usr/bin/env python3
"""render-tcl — deterministic Tcl template renderer for flow execution steps.

This is the generic *rendering* primitive behind the flow engine's "自动执行"
(auto-exec) and "AI 决策" steps. Given a golden template
(templates/tcl/<stage>/<step>.tcl.tmpl) it fills `{{name}}` placeholders from a
merged context and injects AI-authored Tcl fragments at `### @inject:<block>`
markers, producing a concrete `<step>.tcl` ready for run-eda-script.

It is deliberately *dumb*: it carries NO judgement. The values come from (in
increasing precedence):
    1. stage spec top-level scalars  (e.g. technology, top_module)
    2. stage spec `parameters`       (per-stage guidance values)
    3. decisions `params`            (what the AI decided for THIS chip)
    4. --var k=v pairs               (explicit overrides at call time)

Injection: a line `### @inject:<blockname>` is replaced with the text from the
decisions file's `fragments.<blockname>` (multi-line Tcl the AI wrote). If no
such fragment exists, the marker is replaced with a `# (no fragment ...)`
comment so the emitted Tcl never carries a stray `### @inject:` directive.

Guardrail: if any `{{...}}` placeholder remains unfilled after substitution, we
refuse to emit the Tcl and exit nonzero with the list of unfilled names — never
write a Tcl with raw `{{...}}` that would crash the tool with a cryptic error.

CLI:
    render_tcl.py --template <tmpl> --out <step.tcl> \
        [--decisions <decisions.yaml>] [--spec <stage_spec.yaml>] \
        [--workspace <ws> --stage <stage>] [--var k=v ...]

When both --workspace and --stage are given, 7 workspace-derived path vars
(report_dir, artifact_dir, netlist, lef, lib, sdc, lib_search_path) are
auto-injected at a precedence above decisions.params but below explicit --var.

All output is a single JSON object on stdout.
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

# {{ placeholder }} — captures the inner name, tolerant of surrounding spaces.
PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z0-9_.]+)\s*\}\}")
# A whole line that is just an injection directive (leading whitespace kept).
INJECT_RE = re.compile(r"^([ \t]*)###\s*@inject:\s*([A-Za-z0-9_.\-]+)\s*$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_yaml(path: str | None) -> dict:
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {path}")
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    return data or {}


def build_context(
    spec: dict,
    decisions: dict,
    var_pairs: list[str],
    workspace_vars: dict | None = None,
) -> dict:
    """Merge sources into a flat string-keyed context (later sources win).

    Precedence (low → high): spec top-level scalars → spec.parameters →
    decisions.params → workspace-derived path vars → --var pairs.
    """
    ctx: dict[str, object] = {}

    # 1. spec top-level scalars only (skip nested dict/list structure).
    for k, v in (spec or {}).items():
        if isinstance(v, (str, int, float, bool)) or v is None:
            ctx[k] = v

    # 2. stage spec parameters.
    params = (spec or {}).get("parameters") or {}
    if isinstance(params, dict):
        ctx.update(params)

    # 3. decisions.params (what the AI decided for this chip).
    dparams = (decisions or {}).get("params") or {}
    if isinstance(dparams, dict):
        ctx.update(dparams)

    # 4. workspace-derived path vars (auto-filled from --workspace/--stage).
    if workspace_vars:
        ctx.update(workspace_vars)

    # 5. explicit --var overrides.
    for pair in var_pairs:
        if "=" not in pair:
            raise ValueError(f"--var expects k=v, got: {pair!r}")
        key, val = pair.split("=", 1)
        ctx[key.strip()] = val

    return ctx


def _render_injections(template_text: str, fragments: dict) -> tuple[str, list[str]]:
    """Replace `### @inject:<block>` lines with fragment text (or a comment)."""
    injected: list[str] = []
    out_lines: list[str] = []
    for line in template_text.splitlines():
        m = INJECT_RE.match(line)
        if not m:
            out_lines.append(line)
            continue
        indent, block = m.group(1), m.group(2)
        frag = fragments.get(block) if isinstance(fragments, dict) else None
        if frag is None:
            out_lines.append(f"{indent}# (no fragment '{block}' supplied; nothing injected)")
        else:
            out_lines.append(f"{indent}### >>> injected fragment '{block}'")
            for frag_line in str(frag).splitlines():
                out_lines.append(f"{indent}{frag_line}" if frag_line else frag_line)
            out_lines.append(f"{indent}### <<< end fragment '{block}'")
            injected.append(block)
    return "\n".join(out_lines) + ("\n" if template_text.endswith("\n") else ""), injected


def _substitute(text: str, ctx: dict) -> tuple[str, list[str], list[str]]:
    """Replace {{name}} with ctx[name]. Returns (text, filled, unfilled)."""
    filled: list[str] = []
    unfilled: list[str] = []

    def repl(match: re.Match) -> str:
        name = match.group(1)
        if name in ctx and ctx[name] is not None:
            if name not in filled:
                filled.append(name)
            return str(ctx[name])
        if name not in unfilled:
            unfilled.append(name)
        return match.group(0)  # leave intact so we can detect/report it

    return PLACEHOLDER_RE.sub(repl, text), filled, unfilled


def _workspace_path_vars(workspace: str | None, stage: str | None) -> dict | None:
    """Derive the 7 workspace path vars (mirrors tests/flow_e2e/run_e2e.py).

    Only when BOTH --workspace and --stage are given. report_dir/artifact_dir are
    created (mkdir parents, exist_ok) since templates write into them.
    """
    if not (workspace and stage):
        return None
    ws = Path(workspace)
    report_dir = ws / "stages" / stage / "reports"
    artifact_dir = ws / "stages" / stage / "artifacts"
    report_dir.mkdir(parents=True, exist_ok=True)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    return {
        "report_dir": str(report_dir),
        "artifact_dir": str(artifact_dir),
        "netlist": str(ws / "inputs" / "netlist.v"),
        "lef": str(ws / "inputs" / "tech.lef"),
        "lib": str(ws / "inputs" / "cells.lib"),
        "sdc": str(ws / "inputs" / "constraints.sdc"),
        "lib_search_path": str(ws / "inputs"),
    }


def render(
    template: str,
    out: str,
    decisions_path: str | None,
    spec_path: str | None,
    var_pairs: list[str],
    workspace: str | None = None,
    stage: str | None = None,
) -> dict:
    tmpl_path = Path(template)
    if not tmpl_path.exists():
        return {"status": "error", "message": f"Template not found: {template}"}

    try:
        spec = _load_yaml(spec_path)
        decisions = _load_yaml(decisions_path)
    except FileNotFoundError as e:
        return {"status": "error", "message": str(e)}

    workspace_vars = _workspace_path_vars(workspace, stage)

    try:
        ctx = build_context(spec, decisions, var_pairs, workspace_vars)
    except ValueError as e:
        return {"status": "error", "message": str(e)}

    fragments = (decisions or {}).get("fragments") or {}
    template_text = tmpl_path.read_text(encoding="utf-8")

    # 1. inject fragments first (so injected Tcl can itself carry placeholders),
    rendered, injected_blocks = _render_injections(template_text, fragments)
    # 2. then substitute scalar placeholders everywhere.
    rendered, filled, unfilled = _substitute(rendered, ctx)

    if unfilled:
        # Guardrail: never emit a Tcl with raw {{...}}.
        return {
            "status": "error",
            "message": "unfilled placeholders remain; refusing to emit Tcl",
            "template": str(tmpl_path),
            "out": str(out),
            "unfilled_vars": unfilled,
            "filled_vars": filled,
        }

    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        f"# Rendered by render-tcl from {tmpl_path.name} at {_now()}\n"
        f"# Source template: {tmpl_path}\n"
        f"# DO NOT hand-edit — re-render from the template + decisions instead.\n"
    )
    out_path.write_text(header + rendered, encoding="utf-8")

    return {
        "status": "ok",
        "template": str(tmpl_path),
        "out": str(out_path),
        "filled_vars": filled,
        "injected_blocks": injected_blocks,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Render a Tcl template (placeholders + injected fragments) into a concrete script."
    )
    parser.add_argument("--template", required=True, help="Path to the .tcl.tmpl golden template")
    parser.add_argument("--out", required=True, help="Path to write the rendered .tcl")
    parser.add_argument("--decisions", default=None, help="decisions.yaml (params + fragments)")
    parser.add_argument("--spec", default=None, help="stage spec yaml (top-level scalars + parameters)")
    parser.add_argument("--workspace", default=None,
                        help="Flow workspace; with --stage, auto-injects 7 path vars (report_dir, "
                             "artifact_dir, netlist, lef, lib, sdc, lib_search_path)")
    parser.add_argument("--stage", default=None,
                        help="Stage name; with --workspace, auto-injects the 7 workspace path vars")
    parser.add_argument("--var", action="append", default=[], dest="var_pairs",
                        metavar="k=v", help="Explicit context override (repeatable, highest precedence)")
    args = parser.parse_args()

    result = render(args.template, args.out, args.decisions, args.spec, args.var_pairs,
                    workspace=args.workspace, stage=args.stage)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result["status"] == "ok" else 1)


if __name__ == "__main__":
    main()
