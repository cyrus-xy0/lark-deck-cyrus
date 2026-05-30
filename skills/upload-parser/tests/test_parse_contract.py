"""Contract tests for upload-parser handoff artifacts."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]
PARSER = REPO / "skills" / "upload-parser" / "parse.py"
VALIDATOR = REPO / "skills" / "lark-deck-cyrus" / "schema" / "validate-contract.py"
SCHEMA = REPO / "skills" / "lark-deck-cyrus" / "schema" / "source-dossier.schema.json"
SAMPLE_HTML = REPO / "skills" / "deck-renderer" / "examples" / "sample-deck.html"


class UploadParserContractTest(unittest.TestCase):
    def test_html_dossier_validates_and_preserves_dependencies(self) -> None:
        with tempfile.TemporaryDirectory(prefix="upload-parser-html-") as td:
            out = Path(td)
            proc = subprocess.run(
                [
                    sys.executable,
                    str(PARSER),
                    str(SAMPLE_HTML),
                    "--brief",
                    "基于旧 HTML deck 生成新提案",
                    "--output-dir",
                    str(out),
                ],
                cwd=REPO,
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            dossier_path = out / "source-dossier.json"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(VALIDATOR),
                    "--schema",
                    str(SCHEMA),
                    "--instance",
                    str(dossier_path),
                ],
                cwd=REPO,
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            dossier = json.loads(dossier_path.read_text(encoding="utf-8"))
            self.assertGreaterEqual(len(dossier["knowledge_layer"]), 1)
            self.assertGreaterEqual(len(dossier["slide_layer"]), 1)
            html_assets = dossier["source_inventory"][0]["html_assets"]
            self.assertIn("../assets/feishu-deck.js", html_assets["scripts"])
            material_paths = {item["path"] for item in dossier["material_layer"]}
            self.assertIn("../assets/feishu-deck.js", material_paths)
            self.assertIn("../assets/feishu-deck.css", material_paths)


if __name__ == "__main__":
    unittest.main()
