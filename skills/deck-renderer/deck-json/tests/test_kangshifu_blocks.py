"""Kangshifu lecture blocks validate and render to stable HTML hooks."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
DECK_JSON = HERE.parent
VALIDATE = DECK_JSON / "validate-deck.py"
RENDER = DECK_JSON / "render-deck.py"
EXAMPLE = DECK_JSON / "examples" / "kangshifu-blocks.json"


class KangshifuBlocksTest(unittest.TestCase):
    def test_example_validates(self):
        proc = subprocess.run(
            [sys.executable, str(VALIDATE), str(EXAMPLE)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_example_renders_expected_block_hooks(self):
        with tempfile.TemporaryDirectory(prefix="kangshifu-blocks-") as td:
            out_dir = Path(td)
            proc = subprocess.run(
                [
                    sys.executable,
                    str(RENDER),
                    str(EXAMPLE),
                    str(out_dir),
                    "--offline-cache",
                    "--skip-copy-assets",
                    "--skip-validate-html",
                    "--skip-texts",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            html = (out_dir / "index.html").read_text(encoding="utf-8")
            self.assertIn('class="formula-band', html)
            self.assertIn('class="friction-grid', html)
            self.assertIn('class="flywheel-loop', html)


if __name__ == "__main__":
    unittest.main()
