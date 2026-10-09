#!/usr/bin/env python3
"""Minimal unit test for skills/version-check/scripts/version_check.py.

Exercises the three core paths — consistent / mismatch / missing-marker — by
calling the script's main() in-process against tiny synthetic input files in a
temp dir, and asserts status + exit code. Prints PASS/FAIL per case and an
overall result. Runnable standalone:

    python3 tests/flow_e2e/test_version_check.py
"""

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VC_PATH = (REPO_ROOT / "plugins" / "chip-backend-ai" / "skills" /
           "version-check" / "scripts" / "version_check.py")


def _load_module():
    spec = importlib.util.spec_from_file_location("version_check", VC_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write(d: Path, name: str, header: str | None) -> Path:
    p = d / name
    body = "" if header is None else header + "\n"
    p.write_text(body + "content line\n", encoding="utf-8")
    return p


def _run(vc, inputs, out, expected=None):
    """Call main() capturing the printed JSON summary and the exit code."""
    import io
    from contextlib import redirect_stdout

    argv = []
    for i in inputs:
        argv += ["--input", str(i)]
    argv += ["--out", str(out)]
    if expected is not None:
        argv += ["--expected-release", expected]

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = vc.main(argv)
    summary = json.loads(buf.getvalue().strip().splitlines()[-1])
    return rc, summary


def main() -> int:
    vc = _load_module()
    results: list[tuple[str, bool, str]] = []

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        out = d / "version_check.rpt"

        # 1) consistent: all share release r1 → status ok, rc 0
        a = _write(d, "netlist.v", "# release: r1")
        b = _write(d, "cells.lib", "// release: r1")
        c = _write(d, "tech.lef", "release: r1")
        rc, s = _run(vc, [a, b, c], out)
        ok = rc == 0 and s["status"] == "ok" and s["release"] == "r1"
        results.append(("consistent", ok, f"rc={rc} status={s['status']} release={s.get('release')}"))

        # 2) mismatch: one file differs → status mismatch, rc nonzero
        c2 = _write(d, "tech.lef", "release: r2")
        rc, s = _run(vc, [a, b, c2], out)
        ok = rc != 0 and s["status"] == "mismatch" and str(c2) in s.get("inconsistent", [])
        results.append(("mismatch", ok, f"rc={rc} status={s['status']} inconsistent={s.get('inconsistent')}"))

        # 3) missing-marker: one file has no marker → status mismatch, listed missing
        nomark = _write(d, "constraints.sdc", None)
        rc, s = _run(vc, [a, b, nomark], out)
        ok = rc != 0 and s["status"] == "mismatch" and str(nomark) in s.get("missing_marker", [])
        results.append(("missing-marker", ok, f"rc={rc} status={s['status']} missing={s.get('missing_marker')}"))

        # 4) expected-release mismatch: all r1 but expect r9 → mismatch
        rc, s = _run(vc, [a, b], out, expected="r9")
        ok = rc != 0 and s["status"] == "mismatch"
        results.append(("expected-release-mismatch", ok, f"rc={rc} status={s['status']}"))

    all_ok = True
    for name, ok, detail in results:
        tag = "PASS" if ok else "FAIL"
        if not ok:
            all_ok = False
        print(f"[{tag}] {name}: {detail}")

    print("\nPASS" if all_ok else "\nFAIL")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
