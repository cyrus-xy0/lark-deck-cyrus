"""Smoke tests for pitch-simulator CLI normalization and schema output."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]
SIMULATOR = REPO / "skills" / "pitch-simulator" / "simulate-pitch.py"
VALIDATOR = REPO / "skills" / "pitch-simulator" / "validate-rehearsal.py"
OUTLINE = REPO / "skills" / "deck-planner" / "examples" / "retail-agent-outline.json"


class PitchSimulatorCliTest(unittest.TestCase):
    def test_chinese_meeting_type_alias_validates(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pitch-sim-test-") as td:
            out_json = Path(td) / "pitch-rehearsal.json"
            out_md = Path(td) / "PITCH_REHEARSAL.md"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(SIMULATOR),
                    "--outline",
                    str(OUTLINE),
                    "--out-json",
                    str(out_json),
                    "--out-md",
                    str(out_md),
                    "--meeting-type",
                    "POC 启动提案",
                ],
                cwd=REPO,
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            data = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertEqual(data["meeting"]["meeting_type"], "poc-kickoff")

            proc = subprocess.run(
                [sys.executable, str(VALIDATOR), str(out_json)],
                cwd=REPO,
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)


if __name__ == "__main__":
    unittest.main()
