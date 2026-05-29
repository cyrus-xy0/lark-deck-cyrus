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
CONTRACT_VALIDATOR = REPO / "skills" / "lark-deck-cyrus" / "schema" / "validate-contract.py"
CONTRACT_SCHEMA_DIR = REPO / "skills" / "lark-deck-cyrus" / "schema"


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
            "audit-report.json",
            "pitch-rehearsal.json",
            "PITCH_REHEARSAL.md",
            "PIPELINE_REPORT.md",
        ]
        missing = [name for name in required if not (run_dir / "output" / name).exists()]
        if missing:
            print("missing pipeline outputs: " + ", ".join(missing), file=sys.stderr)
            return 1
        contract_pairs = [
            (CONTRACT_SCHEMA_DIR / "audit-report.schema.json", run_dir / "output" / "audit-report.json"),
        ]
        for schema, instance in contract_pairs:
            proc = subprocess.run(
                [sys.executable, str(CONTRACT_VALIDATOR), "--schema", str(schema), "--instance", str(instance)],
                cwd=REPO,
                text=True,
                capture_output=True,
            )
            if proc.returncode != 0:
                print(proc.stdout)
                print(proc.stderr, file=sys.stderr)
                return proc.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
