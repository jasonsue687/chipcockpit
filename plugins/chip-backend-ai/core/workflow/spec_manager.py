#!/usr/bin/env python3
"""Spec versioning, archival, and validation for chip backend design flows.

Manages the spec/ directory:
    spec/
    ├── global_spec.yaml          # Current active global spec
    ├── stages/
    │   ├── floorplan.yaml        # Per-stage specs
    │   ├── cts.yaml
    │   └── route.yaml
    └── history/                  # Archived spec versions (append-only)
        ├── global_spec_v1.yaml
        └── global_spec_v2.yaml
"""
from __future__ import annotations


import argparse
import json
import re
import sys
from pathlib import Path

import yaml

# Required fields in global spec
GLOBAL_SPEC_REQUIRED = [
    "project_name",
    "spec_version",
    "target_ppa",
    "stages",
    "termination_criteria",
]

# Required fields in stage spec
STAGE_SPEC_REQUIRED = [
    "stage",
    "spec_version",
    "metrics",
]


def save_spec(
    workspace: str | Path,
    spec: dict,
    spec_type: str = "global",
    stage: str | None = None,
) -> Path:
    """Write a spec to disk.

    Args:
        workspace: Workspace root path.
        spec: Spec content as dict.
        spec_type: "global" or "stage".
        stage: Stage name, required when spec_type="stage".

    Returns:
        Path to the written spec file.
    """
    workspace = Path(workspace)

    if spec_type == "global":
        target = workspace / "spec" / "global_spec.yaml"
    elif spec_type == "stage":
        if stage is None:
            raise ValueError("stage is required when spec_type='stage'")
        target = workspace / "spec" / "stages" / f"{stage}.yaml"
        target.parent.mkdir(parents=True, exist_ok=True)
    else:
        raise ValueError(f"Unknown spec_type: {spec_type}")

    with open(target, "w") as f:
        yaml.dump(spec, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    return target


def read_spec(
    workspace: str | Path,
    spec_type: str = "global",
    stage: str | None = None,
) -> dict | None:
    """Load a spec from disk.

    Returns None if the spec file does not exist.
    """
    workspace = Path(workspace)

    if spec_type == "global":
        target = workspace / "spec" / "global_spec.yaml"
    elif spec_type == "stage":
        if stage is None:
            raise ValueError("stage is required when spec_type='stage'")
        target = workspace / "spec" / "stages" / f"{stage}.yaml"
    else:
        raise ValueError(f"Unknown spec_type: {spec_type}")

    if not target.exists():
        return None

    with open(target) as f:
        return yaml.safe_load(f)


def archive_spec(workspace: str | Path) -> str:
    """Archive the current global spec and increment the version.

    Moves global_spec.yaml to history/global_spec_vN.yaml.

    Returns:
        The new spec version string (e.g., "v3").
    """
    workspace = Path(workspace)
    current_file = workspace / "spec" / "global_spec.yaml"
    history_dir = workspace / "spec" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)

    if not current_file.exists():
        raise FileNotFoundError(f"No current spec to archive: {current_file}")

    # Determine current version
    current_spec = read_spec(workspace, "global")
    current_version = current_spec.get("spec_version", "v1") if current_spec else "v1"
    version_num = int(re.search(r"\d+", current_version).group()) if re.search(r"\d+", current_version) else 1

    # Archive with current version number
    archive_name = f"global_spec_v{version_num}.yaml"
    archive_path = history_dir / archive_name

    # Avoid overwriting existing archives
    if archive_path.exists():
        counter = 1
        while archive_path.exists():
            archive_name = f"global_spec_v{version_num}_{counter}.yaml"
            archive_path = history_dir / archive_name
            counter += 1

    current_file.rename(archive_path)

    # Return the next version
    new_version = f"v{version_num + 1}"
    return new_version


def get_spec_version(workspace: str | Path) -> str | None:
    """Get the current spec version string from global_spec.yaml."""
    spec = read_spec(workspace, "global")
    if spec is None:
        return None
    return spec.get("spec_version")


def validate_spec(spec: dict, spec_type: str = "global") -> dict:
    """Validate a spec dict against required fields.

    Returns:
        Dict with "valid" (bool) and "errors" (list of strings).
    """
    required = GLOBAL_SPEC_REQUIRED if spec_type == "global" else STAGE_SPEC_REQUIRED
    errors = []

    for field in required:
        if field not in spec:
            errors.append(f"Missing required field: {field}")

    if spec_type == "global":
        # Validate target_ppa structure
        ppa = spec.get("target_ppa", {})
        if ppa and not isinstance(ppa, dict):
            errors.append("target_ppa must be a dict")

        # Validate stages is a list
        stages = spec.get("stages")
        if stages is not None and not isinstance(stages, list):
            errors.append("stages must be a list")

    if spec_type == "stage":
        # Validate metrics structure
        metrics = spec.get("metrics", [])
        if not isinstance(metrics, list):
            errors.append("metrics must be a list")
        else:
            for i, m in enumerate(metrics):
                if "name" not in m:
                    errors.append(f"metrics[{i}]: missing 'name'")
                if "target" not in m:
                    errors.append(f"metrics[{i}]: missing 'target'")

    return {"valid": len(errors) == 0, "errors": errors}


def list_history(workspace: str | Path) -> list[str]:
    """List all archived spec versions in history/."""
    workspace = Path(workspace)
    history_dir = workspace / "spec" / "history"

    if not history_dir.exists():
        return []

    return sorted(f.name for f in history_dir.iterdir() if f.suffix in (".yaml", ".yml"))


def main():
    parser = argparse.ArgumentParser(description="Spec management operations")
    sub = parser.add_subparsers(dest="command")

    # read
    p_read = sub.add_parser("read", help="Read a spec")
    p_read.add_argument("--workspace", required=True)
    p_read.add_argument("--type", default="global", choices=["global", "stage"])
    p_read.add_argument("--stage", default=None)

    # version
    p_ver = sub.add_parser("version", help="Get current spec version")
    p_ver.add_argument("--workspace", required=True)

    # archive
    p_archive = sub.add_parser("archive", help="Archive current spec")
    p_archive.add_argument("--workspace", required=True)

    # validate
    p_val = sub.add_parser("validate", help="Validate a spec file")
    p_val.add_argument("--file", required=True, help="Path to spec YAML file")
    p_val.add_argument("--type", default="global", choices=["global", "stage"])

    # history
    p_hist = sub.add_parser("history", help="List archived specs")
    p_hist.add_argument("--workspace", required=True)

    args = parser.parse_args()

    if args.command == "read":
        spec = read_spec(args.workspace, args.type, args.stage)
        if spec is None:
            print(json.dumps({"status": "not_found"}))
        else:
            print(json.dumps(spec, ensure_ascii=False, indent=2))

    elif args.command == "version":
        ver = get_spec_version(args.workspace)
        print(json.dumps({"spec_version": ver}))

    elif args.command == "archive":
        new_ver = archive_spec(args.workspace)
        print(json.dumps({"status": "ok", "new_version": new_ver}))

    elif args.command == "validate":
        with open(args.file) as f:
            spec = yaml.safe_load(f)
        result = validate_spec(spec, args.type)
        print(json.dumps(result))

    elif args.command == "history":
        versions = list_history(args.workspace)
        print(json.dumps(versions))

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
