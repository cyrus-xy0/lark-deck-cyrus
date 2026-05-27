#!/usr/bin/env python3
"""Contract smoke test for scripts/run_cyrus_pipeline.py."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
PIPELINE = REPO / "scripts" / "run_cyrus_pipeline.py"
OUTLINE = REPO / "skills" / "deck-planner" / "examples" / "retail-agent-outline.json"


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="cyrus-pipeline-test-") as td:
        run_dir = Path(td) / "runs" / "retail-agent-demo"
        (run_dir / "input").mkdir(parents=True)
        shutil.copy(OUTLINE, run_dir / "input" / "outline.json")
        proc = subprocess.run(
            [
                sys.executable,
                str(PIPELINE),
                str(run_dir),
                "--no-visual",
                "--offline-cache",
                "--no-magic",
                "--skip-package",
                "--meeting-type",
                "poc-kickoff",
            ],
            cwd=REPO,
            text=True,
            capture_output=True,
        )
        if proc.returncode != 0:
            print(proc.stdout)
            print(proc.stderr, file=sys.stderr)
            return proc.returncode
        required = [
            "index.html",
            "deck.json",
            "texts.md",
            "FEEDBACK.md",
            "AUDIT_REPORT.md",
            "pitch-rehearsal.json",
            "PITCH_REHEARSAL.md",
            "PIPELINE_REPORT.md",
        ]
        missing = [name for name in required if not (run_dir / "output" / name).exists()]
        if missing:
            print("missing pipeline outputs: " + ", ".join(missing), file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
