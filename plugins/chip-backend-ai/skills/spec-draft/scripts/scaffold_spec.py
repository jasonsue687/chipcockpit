#!/usr/bin/env python3
"""spec-draft / scaffold_spec.py — write spec skeletons from the templates.

OPTIONAL helper for the spec-draft playbook. It does NOT make the PPA-budget
decomposition judgement (that is the main agent's job in SKILL.md Step 4) — it
only writes a starting `spec/global_spec.yaml` + per-stage `spec/stages/<stage>.yaml`
skeleton (seeded from templates/{global,stage}_spec_template.yaml) so the agent
fills concrete numbers instead of hand-rolling YAML from scratch.

It is deterministic and invokes no EDA tool.

CLI:
    scaffold_spec.py --workspace <ws> --project <name> --goal "<human goal>" \
        [--stages a,b,c] [--technology <node>] [--force]

Behaviour:
    - reads the two templates next to ${CLAUDE_PLUGIN_ROOT}/templates/
    - writes <ws>/spec/global_spec.yaml (project_name, human_goal, technology,
      stages list filled; numeric PPA targets left at template defaults for the
      agent to refine)
    - writes <ws>/spec/stages/<stage>.yaml for each stage (stage name + a
      single empty metric stub + empty parameters, for the agent to fill)
    - refuses to overwrite existing files unless --force

All output is a single JSON object on stdout
(status: ok|error, global: <path>, stages: {name: path}).
"""

import argparse
import json
import sys
from pathlib import Path

import yaml

# This file lives at skills/spec-draft/scripts/scaffold_spec.py
PLUGIN_ROOT = Path(__file__).resolve().parents[3]
TEMPLATES = PLUGIN_ROOT / "templates"
GLOBAL_TMPL = TEMPLATES / "global_spec_template.yaml"
STAGE_TMPL = TEMPLATES / "stage_spec_template.yaml"

# Default full 9-stage pipeline (import → tapeout) per flow_definition.yaml.
DEFAULT_STAGES = [
    "import", "floorplan", "powerplan", "placement", "cts",
    "route", "timing_eco", "signoff", "tapeout",
]


def _load_template(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"template not found: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _dump(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def build_global(project: str, goal: str, technology: str,
                 stages: list[str]) -> dict:
    g = _load_template(GLOBAL_TMPL)
    g["project_name"] = project
    g["human_goal"] = goal
    g.setdefault("global_constraints", {})
    if technology:
        g["global_constraints"]["technology"] = technology
    g["stages"] = list(stages)
    return g


def build_stage(stage: str) -> dict:
    s = _load_template(STAGE_TMPL)
    s["stage"] = stage
    # leave a single metric stub + empty parameters for the agent to fill;
    # the template already provides the shape.
    return s


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Write spec skeletons from the templates (spec-draft helper).")
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--project", required=True, help="project / block name")
    ap.add_argument("--goal", required=True, help="human goal text (verbatim)")
    ap.add_argument("--stages", default=None,
                    help="comma-separated stage list (default: full 9-stage pipeline)")
    ap.add_argument("--technology", default="", help="technology node, e.g. tsmc_n5")
    ap.add_argument("--force", action="store_true",
                    help="overwrite existing spec files")
    args = ap.parse_args(argv)

    stages = (
        [s.strip() for s in args.stages.split(",") if s.strip()]
        if args.stages else list(DEFAULT_STAGES)
    )
    if not stages:
        print(json.dumps({"status": "error", "error": "empty --stages"}))
        return 2

    ws = Path(args.workspace)
    global_path = ws / "spec" / "global_spec.yaml"
    stage_paths = {st: ws / "spec" / "stages" / f"{st}.yaml" for st in stages}

    if not args.force:
        existing = [str(p) for p in [global_path, *stage_paths.values()] if p.exists()]
        if existing:
            print(json.dumps({
                "status": "error",
                "error": "spec files already exist; pass --force to overwrite",
                "existing": existing,
            }, ensure_ascii=False))
            return 1

    try:
        _dump(global_path, build_global(args.project, args.goal,
                                        args.technology, stages))
        for st, p in stage_paths.items():
            _dump(p, build_stage(st))
    except (OSError, FileNotFoundError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}))
        return 2

    print(json.dumps({
        "status": "ok",
        "global": str(global_path),
        "stages": {st: str(p) for st, p in stage_paths.items()},
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
