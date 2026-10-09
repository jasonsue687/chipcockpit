#!/usr/bin/env python3
"""Convenience entry point for the local chip-flow dashboard."""
from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = REPO_ROOT / "plugins" / "chip-backend-ai" / "core" / "workflow"
sys.path.insert(0, str(WORKFLOW_DIR))

from dashboard_server import main  # noqa: E402


if __name__ == "__main__":
    main()
