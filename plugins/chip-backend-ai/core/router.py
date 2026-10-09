#!/usr/bin/env python3
"""
core/router.py — Progressive Disclosure Router for chip-backend-ai

This module is the central dispatch layer. It can be called as a CLI tool
by hooks or commands to route a user query to the correct skill:

  list_expert_topics  — Level 1: scan expert_base/ index
  read_expert_doc     — Level 2: load specific expert doc
  search_eda_command  — Look up a Tcl command in processed_eda/ JSON
  read_eda_concept    — Explain a PD/EDA concept

Usage (CLI):
  python core/router.py list-topics
  python core/router.py read-doc --file example-floorplan-tips.md
  python core/router.py search-cmd --tool innovus --command place_opt
  python core/router.py explain --concept CTS

All output is JSON to stdout. Errors are JSON on stderr with exit code 1.
"""

import json
import re
import sys
import argparse
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

PLUGIN_ROOT = Path(__file__).parent.parent
EXPERT_BASE = PLUGIN_ROOT / 'knowledge' / 'expert_base'
PROCESSED_EDA = PLUGIN_ROOT / 'knowledge' / 'processed_eda'


def ok(data: dict) -> None:
    """Print JSON result and exit 0."""
    print(json.dumps(data, indent=2, ensure_ascii=False))
    sys.exit(0)


def err(message: str, code: int = 1) -> None:
    """Print JSON error to stderr and exit with error code."""
    print(json.dumps({'error': message}), file=sys.stderr)
    sys.exit(code)


# ---------------------------------------------------------------------------
# Level 1: List Expert Topics
# ---------------------------------------------------------------------------

def list_expert_topics() -> dict:
    """
    Scan knowledge/expert_base/ and return a lightweight topic index.
    Progressive disclosure Level 1: titles + summaries only.
    """
    if not EXPERT_BASE.exists():
        err(
            f"Expert base directory not found: {EXPERT_BASE}. "
            "Create knowledge/expert_base/ and add Markdown files."
        )

    md_files = sorted(EXPERT_BASE.rglob('*.md'))

    if not md_files:
        return {
            'expert_topics': [],
            'total': 0,
            'hint': 'No expert documents found. Add Markdown files to knowledge/expert_base/.',
        }

    topics = []
    for md_file in md_files:
        try:
            lines = md_file.read_text(encoding='utf-8').splitlines()
        except OSError as e:
            print(f"[WARN] Could not read {md_file.name}: {e}", file=sys.stderr)
            continue

        # Extract title: first line starting with "# "
        title = md_file.stem  # fallback
        summary = ''
        tags = []

        for line in lines:
            stripped = line.strip()
            if stripped.startswith('# ') and title == md_file.stem:
                title = stripped[2:].strip()
            elif stripped.startswith('> Topic:'):
                # Extract topic metadata if present
                pass
            elif stripped.startswith('> Tags:'):
                tag_str = stripped[7:].strip()
                tags = [t.strip() for t in tag_str.split(',') if t.strip()]
            elif stripped and not stripped.startswith('#') and not stripped.startswith('>'):
                if not summary:
                    # First real content line
                    summary = stripped[:100] + ('...' if len(stripped) > 100 else '')

        # Relative path from expert_base root
        rel_path = str(md_file.relative_to(EXPERT_BASE))

        topics.append({
            'file': rel_path,
            'title': title,
            'summary': summary,
            'tags': tags,
        })

    return {
        'expert_topics': topics,
        'total': len(topics),
        'hint': "Use 'read-expert-doc --file <filename>' to load full content of a document.",
    }


# ---------------------------------------------------------------------------
# Level 2: Read Expert Doc
# ---------------------------------------------------------------------------

def read_expert_doc(filename: str) -> dict:
    """
    Load and return the full content of a specific expert Markdown file.
    Progressive disclosure Level 2: full content on demand.
    """
    # Security: prevent path traversal
    if '..' in filename or filename.startswith('/') or filename.startswith('~'):
        err(f"Invalid filename '{filename}'. Only filenames within knowledge/expert_base/ are allowed.")

    if not filename.endswith('.md'):
        err(f"Invalid file extension. Only .md files are supported. Got: '{filename}'")

    target = EXPERT_BASE / filename

    if not target.exists():
        # Attempt case-insensitive search
        candidates = [f for f in EXPERT_BASE.rglob('*.md') if f.name.lower() == filename.lower()]
        if candidates:
            target = candidates[0]
            print(f"[INFO] Case-insensitive match: {target.name}", file=sys.stderr)
        else:
            available = [str(f.relative_to(EXPERT_BASE)) for f in sorted(EXPERT_BASE.rglob('*.md'))]
            err(
                f"Document '{filename}' not found in knowledge/expert_base/. "
                f"Available files: {available}"
            )

    try:
        content = target.read_text(encoding='utf-8')
    except OSError as e:
        err(f"Could not read '{filename}': {e}")

    if not content.strip():
        err(f"Document '{filename}' exists but is empty.")

    return {
        'file': filename,
        'content': content,
        'source': f"knowledge/expert_base/{filename}",
        'hint': "To search for EDA commands mentioned here, use 'search-eda-command --tool <tool> --command <name>'",
    }


# ---------------------------------------------------------------------------
# EDA Command Search
# ---------------------------------------------------------------------------

def search_eda_command(tool_name: str, command_name: str) -> dict:
    """
    Search for a Tcl command in the preprocessed EDA JSON database.
    Returns exact match or prefix-based suggestions.
    """
    tool_name = tool_name.lower().strip()
    command_name = command_name.lower().strip()

    json_path = PROCESSED_EDA / f"{tool_name}.json"

    if not json_path.exists():
        err(
            f"Database for '{tool_name}' not found at {json_path}. "
            "Run parsers/pdf_to_structured.py to generate it first."
        )

    try:
        commands = json.loads(json_path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as e:
        err(f"Database file '{json_path}' is malformed: {e}. Re-run parsers/pdf_to_structured.py.")

    if not isinstance(commands, list) or not commands:
        err(f"Database for '{tool_name}' is empty. Ensure the parser ran successfully.")

    # Build lookup index
    cmd_index = {entry['command'].lower(): entry for entry in commands if 'command' in entry}

    # 1. Exact match (case-insensitive)
    if command_name in cmd_index:
        return {
            'match_type': 'exact',
            'tool': tool_name,
            'result': cmd_index[command_name],
        }

    # 2. Prefix match: command_name is a prefix of known commands OR vice versa
    prefix_matches = [
        name for name in cmd_index
        if name.startswith(command_name) or command_name.startswith(name)
    ]

    if prefix_matches:
        return {
            'match_type': 'prefix_suggestions',
            'tool': tool_name,
            'query': command_name,
            'suggestions': sorted(prefix_matches),
            'hint': f"Use 'search-eda-command --tool {tool_name} --command <exact_name>' for full details.",
        }

    # 3. No match
    return {
        'match_type': 'not_found',
        'tool': tool_name,
        'query': command_name,
        'total_commands': len(cmd_index),
        'hint': (
            f"No command matching '{command_name}' in {tool_name} database "
            f"({len(cmd_index)} commands). Check spelling or use 'list-topics' to browse."
        ),
    }


# ---------------------------------------------------------------------------
# EDA Concept Explanation (routing helper)
# ---------------------------------------------------------------------------

CONCEPT_ALIASES = {
    'cts': 'clock tree synthesis',
    'cto': 'clock tree optimization',
    'pnr': 'place and route',
    'p&r': 'place and route',
    'drc': 'design rule check',
    'lvs': 'layout versus schematic',
    'eco': 'engineering change order',
    'ir': 'ir drop',
    'sta': 'static timing analysis',
    'hold': 'hold violation',
    'setup': 'setup violation',
    'cts': 'clock tree synthesis',
    'filler': 'filler cell insertion',
}


def read_eda_concept(concept: str) -> dict:
    """
    Route a conceptual query to expert_base if possible,
    otherwise return a structured explanation scaffold.
    """
    normalized = concept.lower().strip()
    # Resolve aliases
    normalized = CONCEPT_ALIASES.get(normalized, normalized)

    # Search expert base for matching files
    matches = []
    if EXPERT_BASE.exists():
        for md_file in EXPERT_BASE.rglob('*.md'):
            content = ''
            try:
                content = md_file.read_text(encoding='utf-8').lower()
            except OSError:
                continue
            # Match if concept appears in title or tags
            first_lines = content[:500]
            if normalized in first_lines or normalized.replace(' ', '-') in md_file.stem:
                matches.append(str(md_file.relative_to(EXPERT_BASE)))

    if matches:
        return {
            'match_type': 'expert_base',
            'concept': concept,
            'matching_docs': matches,
            'hint': f"Use 'read-expert-doc --file {matches[0]}' to load the full document.",
        }

    # No expert doc found — return a structured scaffold for LLM to fill
    return {
        'match_type': 'scaffold',
        'concept': concept,
        'explanation_template': {
            'definition': f"[Explain what '{concept}' means in chip physical design]",
            'why_it_matters': "[Impact on timing, power, area, or routability]",
            'key_parameters': "[Important thresholds, settings, or metrics]",
            'common_issues': "[What goes wrong and why]",
            'related_commands': "[Suggest 1-3 EDA Tcl commands to explore]",
            'expert_tip': "[One actionable best practice]",
        },
        'hint': (
            f"No expert document found for '{concept}'. "
            "Add a Markdown file to knowledge/expert_base/ to provide curated guidance."
        ),
    }


# ---------------------------------------------------------------------------
# Parse EDA Report → eval_result
# ---------------------------------------------------------------------------

# Heuristic regex library for extracting a metric's actual value from a raw
# Innovus/PrimeTime report. Each metric name maps to ordered alternatives;
# the first match wins. Group 1 must capture the number (slack may be negative).
# Report formats vary — a metric in the stage spec can carry its own `pattern:`
# to override these defaults. Patterns are matched case-insensitively.
METRIC_PATTERNS: dict[str, list[str]] = {
    "wns_ns": [r"WNS\s*\(ns\)\s*[:=]?\s*(-?[0-9.]+)",
               r"worst\s+negative\s+slack\s*[:=]?\s*(-?[0-9.]+)"],
    "tns_ns": [r"TNS\s*\(ns\)\s*[:=]?\s*(-?[0-9.]+)",
               r"total\s+negative\s+slack\s*[:=]?\s*(-?[0-9.]+)"],
    "hold_wns_ns": [r"hold\s+WNS\s*\(ns\)\s*[:=]?\s*(-?[0-9.]+)",
                    r"hold\s+worst\s+negative\s+slack\s*[:=]?\s*(-?[0-9.]+)"],
    # More specific keyword first: a stray "Core Density" must not shadow utilization.
    "utilization": [r"utilization\s*[:=]?\s*([0-9.]+)",
                    r"(?:total\s+)?density\s*[:=]?\s*([0-9.]+)"],
    "congestion_hotspot": [r"(?:total\s+)?overflow\s*[:=]?\s*([0-9.]+)",
                           r"H\s*overflow\s*[:=]?\s*([0-9.]+)"],
    "macro_channel_width_um": [r"channel\s+width\s*(?:\(um\))?\s*[:=]?\s*([0-9.]+)"],
    "power_grid_ir_drop": [r"(?:worst|max)\s+IR\s*(?:drop)?\s*(?:\(mV\))?\s*[:=]?\s*([0-9.]+)"],
    "drc_violations": [r"(?:total\s+)?violations?\s*[:=]?\s*([0-9]+)",
                       r"([0-9]+)\s+viol"],
    "total_power_mw": [r"total\s+power\s*(?:\(mW\))?\s*[:=]?\s*([0-9.]+)"],
    "global_skew_ps": [r"global\s+skew\s*(?:\(ps\))?\s*[:=]?\s*([0-9.]+)"],
    "max_insertion_delay_ps": [r"(?:max|maximum)\s+insertion\s+delay\s*(?:\(ps\))?\s*[:=]?\s*([0-9.]+)"],
}


def _extract_metric(text: str, name: str, override: Optional[str] = None) -> Optional[float]:
    """Return the first numeric value matching a metric's pattern(s), or None."""
    patterns = [override] if override else METRIC_PATTERNS.get(name, [])
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1))
            except (ValueError, IndexError):
                continue
    return None


def _status_for(actual: Optional[float], target: dict) -> str:
    """Compare an actual value against a {min, max} target.

    pass    — within [min, max] (either bound may be null = unconstrained)
    fail    — outside a bound
    missing — could not extract the value from the report
    """
    if actual is None:
        return "missing"
    mn, mx = target.get("min"), target.get("max")
    if mn is not None and actual < mn:
        return "fail"
    if mx is not None and actual > mx:
        return "fail"
    return "pass"


def parse_eda_report(
    report_paths: list[str],
    spec_path: str,
    stage: str,
    run_id: str,
    spec_version: str,
    output_path: Optional[str] = None,
    simulated: bool = False,
) -> dict:
    """Parse raw EDA report(s) into a structured eval_result.

    Reads the metric targets from a stage spec (its `metrics:` list), extracts
    each metric's actual value from the concatenated report text, compares to
    the target, and assembles an eval_result dict matching
    templates/eval_result_template.yaml. Deterministic; no EDA tool required.
    """
    try:
        import yaml
    except ImportError:
        err("PyYAML is required for parse-report. Install with: pip install pyyaml")

    spec_file = Path(spec_path)
    if not spec_file.exists():
        err(f"Stage spec not found: {spec_path}")
    try:
        spec = yaml.safe_load(spec_file.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        err(f"Stage spec '{spec_path}' is malformed: {e}")

    metrics_spec = spec.get("metrics") or []
    if not metrics_spec:
        err(f"Stage spec '{spec_path}' has no 'metrics' to evaluate.")

    # Concatenate all report files into one searchable blob.
    text = ""
    for rp in report_paths:
        p = Path(rp)
        if not p.exists():
            err(f"Report file not found: {rp}")
        text += p.read_text(encoding="utf-8", errors="replace") + "\n"

    results = []
    for m in metrics_spec:
        name = m.get("name")
        if not name:
            continue
        target = m.get("target") or {}
        actual = _extract_metric(text, name, m.get("pattern"))
        results.append({
            "name": name,
            "target": {"min": target.get("min"), "max": target.get("max")},
            "actual": actual,
            "status": _status_for(actual, target),
        })

    statuses = {r["status"] for r in results}
    if "fail" in statuses:
        overall, recommendation = "fail", "retry"
    elif "missing" in statuses:
        overall, recommendation = "partial", "escalate"
    else:
        overall, recommendation = "pass", "proceed"

    failed = [r["name"] for r in results if r["status"] == "fail"]
    missing = [r["name"] for r in results if r["status"] == "missing"]

    eval_result = {
        "stage": stage,
        "run_id": run_id,
        "spec_version": spec_version,
        "overall": overall,
        "metrics": results,
        "recommendation": recommendation,
        "retry_context": ({"failed_metrics": failed} if failed else None),
        "escalation_reason": (
            f"metrics not found in report(s): {missing}" if missing else None
        ),
        "generated_by": "parse-eda-report",
    }

    # When the upstream report was produced by the SIMULATION (mock) path,
    # carry a loud `simulated: true` flag into the eval_result so nothing
    # downstream mistakes these synthetic numbers for real signoff PPA.
    if simulated:
        eval_result["simulated"] = True

    if output_path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            yaml.dump(eval_result, default_flow_style=False, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        eval_result["_written_to"] = str(out)

    return eval_result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description='chip-backend-ai progressive disclosure router',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest='action', required=True)

    # list-topics
    sub.add_parser('list-topics', help='Level 1: List all expert knowledge topics.')

    # read-doc
    rd = sub.add_parser('read-doc', help='Level 2: Read full expert document.')
    rd.add_argument('--file', '-f', required=True, help='Markdown filename in expert_base/')

    # search-cmd
    sc = sub.add_parser('search-cmd', help='Search EDA command in processed JSON database.')
    sc.add_argument('--tool', '-t', required=True, help='EDA tool name (e.g., innovus, genus)')
    sc.add_argument('--cmd-name', '-c', required=True, dest='cmd_name',
                    help='Tcl command name to search')

    # explain
    ex = sub.add_parser('explain', help='Explain an EDA/PD concept.')
    ex.add_argument('--concept', required=True, help='Concept to explain (e.g., CTS, IR drop)')

    # parse-report
    pr = sub.add_parser('parse-report', help='Parse EDA report(s) into a structured eval_result.')
    pr.add_argument('--report', '-r', action='append', required=True,
                    help='Path to a raw EDA report (.rpt). Repeatable for multiple reports.')
    pr.add_argument('--spec', required=True, help='Stage spec YAML (provides metric names + targets)')
    pr.add_argument('--stage', required=True, help='Stage name (for the eval_result header)')
    pr.add_argument('--run-id', required=True, dest='run_id', help='Run ID (e.g., run_001)')
    pr.add_argument('--spec-version', default='v1', dest='spec_version', help='Spec version')
    pr.add_argument('--output', '-o', default=None,
                    help='Write eval_result.yaml here (default: print JSON to stdout)')
    pr.add_argument('--simulated', action='store_true',
                    help='Mark the eval_result with simulated:true (report came from the mock/SIMULATION path, not real PPA)')

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.action == 'list-topics':
        ok(list_expert_topics())
    elif args.action == 'read-doc':
        ok(read_expert_doc(args.file))
    elif args.action == 'search-cmd':
        ok(search_eda_command(args.tool, args.cmd_name))
    elif args.action == 'explain':
        ok(read_eda_concept(args.concept))
    elif args.action == 'parse-report':
        ok(parse_eda_report(
            args.report, args.spec, args.stage, args.run_id,
            args.spec_version, args.output, args.simulated,
        ))
    else:
        err(f"Unknown action: {args.action}")


if __name__ == '__main__':
    main()
