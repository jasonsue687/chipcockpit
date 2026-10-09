#!/usr/bin/env python3
"""version-check — deterministic release-consistency check for flow inputs.

Verifies that the external design+library inputs (netlist · SDC · lib · LEF/PDK)
all come from the SAME release/version BEFORE the EDA flow starts. This is the
deterministic "版本一致" half of 前置就绪 at the import head — the "inputs present"
half is flow_loader's blocked_inputs, and "tools ready" is env_manager. It does
NOT invoke any EDA tool: it just scans each input file's header for a release
marker, compares them, and writes a report.

A release marker is a header line (scanned in the first ~10 lines) of the form:
    # release: <id>      // release: <id>      release: <id>
    # version: <id>      // version: <id>      version: <id>
i.e. a `release:`/`version:` field, optionally behind a `#` or `//` comment. The
token after the colon is taken as the file's release id. A file with no marker
is recorded as `missing` and treated as a mismatch.

CLI:
    version_check.py --input <path> [--input <path> ...] --out <report_path> \
        [--expected-release <id>]

Behaviour:
    - all inputs share one release (and == --expected-release if given)
        → write CONSISTENT report, JSON status "ok", exit 0
    - any input differs / is missing a marker (or != --expected-release)
        → write MISMATCH report listing per-file releases, JSON status
          "mismatch", exit nonzero

All output is a single JSON object on stdout
(status: ok|mismatch|error, releases: {file: id|null}, report: <path>).
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# How many leading lines of each file to scan for a release marker.
HEADER_LINES = 10

# `# release: <id>` / `// version: <id>` / `/* release: <id> */` / bare `release: <id>`.
# Optional leading `#`, `//`, or `/*` comment prefix (Liberty .lib files use
# `/* ... */` block comments), then release|version, then the id token (first run
# of non-space chars after the colon). A trailing `*/` (if present) is not part
# of the id because `*/` contains no leading whitespace separator — but to be safe
# the id token also stops at `*` so `/* release: X */` yields `X`, not `X */`.
MARKER_RE = re.compile(
    r"^\s*(?:#|//|/\*)?\s*(?:release|version)\s*:\s*([^\s,;*]+)",
    re.IGNORECASE,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def extract_release(path: Path) -> str | None:
    """Scan the first HEADER_LINES lines of `path` for a release marker.

    Returns the release id (first match wins) or None if no marker is found.
    """
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for _, line in zip(range(HEADER_LINES), fh):
                m = MARKER_RE.match(line)
                if m:
                    return m.group(1)
    except OSError:
        return None
    return None


def build_report(releases: dict[str, str | None], status: str,
                 common: str | None, expected: str | None,
                 missing: list[str], odd: list[str]) -> str:
    """Render the human-readable .rpt body."""
    result = "CONSISTENT" if status == "ok" else "MISMATCH"
    lines = [
        "# version_check report  (SIMULATED flow uses synthetic markers)",
        "# generated_by: version-check",
        f"# generated_at: {_now()}",
        "",
        f"RESULT: {result}",
    ]
    if expected is not None:
        lines.append(f"EXPECTED_RELEASE: {expected}")
    if status == "ok":
        lines.append(f"RELEASE: {common}")
    lines.append("")
    lines.append("FILES:")
    for path, rel in releases.items():
        lines.append(f"  {path} -> release={rel if rel is not None else '<missing>'}")
    if status != "ok":
        lines.append("")
        if missing:
            lines.append("MISSING_MARKER:")
            for p in missing:
                lines.append(f"  {p}")
        if odd:
            ref = expected if expected is not None else common
            lines.append(f"INCONSISTENT (expected release={ref}):")
            for p in odd:
                lines.append(f"  {p} -> release={releases[p]}")
        lines.append("")
        lines.append("ACTION: replace inputs so all come from the SAME release "
                     "before starting the flow.")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Deterministic release-consistency check for flow inputs.")
    ap.add_argument("--input", action="append", default=[], metavar="PATH",
                    help="An input file to check (repeatable).")
    ap.add_argument("--out", required=True, metavar="PATH",
                    help="Where to write the version_check report.")
    ap.add_argument("--expected-release", default=None, metavar="ID",
                    help="If given, require every input to equal this release.")
    args = ap.parse_args(argv)

    if not args.input:
        print(json.dumps({"status": "error",
                          "error": "no --input given"}))
        return 2

    expected = args.expected_release
    releases: dict[str, str | None] = {}
    for raw in args.input:
        p = Path(raw)
        if not p.exists():
            print(json.dumps({"status": "error",
                              "error": f"input not found: {raw}"}))
            return 2
        releases[str(p)] = extract_release(p)

    missing = [p for p, r in releases.items() if r is None]
    present = {p: r for p, r in releases.items() if r is not None}

    # Determine the reference release: explicit --expected-release wins, else the
    # most common one among the present markers (ties: first-seen).
    if expected is not None:
        common: str | None = expected
    elif present:
        counts: dict[str, int] = {}
        order: list[str] = []
        for r in present.values():
            if r not in counts:
                order.append(r)
            counts[r] = counts.get(r, 0) + 1
        common = max(order, key=lambda r: counts[r])
    else:
        common = None

    odd = [p for p, r in present.items() if r != common]

    status = "ok" if (not missing and not odd and common is not None) else "mismatch"

    report = build_report(releases, status, common, expected, missing, odd)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")

    summary = {
        "status": status,
        "release": common if status == "ok" else None,
        "releases": releases,
        "report": str(out_path),
    }
    if status != "ok":
        summary["missing_marker"] = missing
        summary["inconsistent"] = odd
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if status == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
