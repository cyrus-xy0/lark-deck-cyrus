"""Smoke tests for deck-renderer utility scripts restored from feishu-deck-h5."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]
ASSETS = REPO / "skills" / "deck-renderer" / "assets"


class UtilityScriptTests(unittest.TestCase):
    def test_inline_assets_inlines_css_relative_images(self) -> None:
        with tempfile.TemporaryDirectory(prefix="inline-assets-test-") as td:
            root = Path(td)
            asset_dir = root / "assets"
            asset_dir.mkdir()
            (asset_dir / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\nmini")
            (asset_dir / "deck.css").write_text(
                '.brand { background-image: url("logo.png"); }',
                encoding="utf-8",
            )
            (asset_dir / "deck.js").write_text("window.__deckTest = true;", encoding="utf-8")
            src = root / "index.html"
            src.write_text(
                """<!doctype html>
<html><head><link rel="stylesheet" href="assets/deck.css"></head>
<body><img src="assets/logo.png"><script src="assets/deck.js"></script></body></html>
""",
                encoding="utf-8",
            )
            out = root / "inline.html"
            proc = subprocess.run(
                ["python3", str(ASSETS / "inline-assets.py"), str(src), "--out", str(out)],
                cwd=REPO,
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            html = out.read_text(encoding="utf-8")
            self.assertIn('<meta name="fs-deck-mode" content="inline">', html)
            self.assertIn('<style data-source="framework"', html)
            self.assertIn('<script data-source="framework"', html)
            self.assertNotIn('href="assets/deck.css"', html)
            self.assertNotIn('src="assets/deck.js"', html)
            self.assertGreaterEqual(html.count("data:image/png;base64,"), 2)

    def test_deck_edit_sets_text_leaf(self) -> None:
        with tempfile.TemporaryDirectory(prefix="deck-edit-test-") as td:
            html_path = Path(td) / "deck.html"
            html_path.write_text(
                '<div class="slide-frame"><div class="slide" data-layout="cover" '
                'data-screen-label="01 Cover" data-slide-key="cover">'
                '<h1 data-text-id="slide-01.title">Old</h1></div></div>',
                encoding="utf-8",
            )
            proc = subprocess.run(
                [
                    "python3",
                    str(ASSETS / "deck-edit.py"),
                    str(html_path),
                    "--set",
                    "slide-01.title",
                    "New",
                    "--no-backup",
                ],
                cwd=REPO,
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            self.assertIn(">New<", html_path.read_text(encoding="utf-8"))

    def test_deck_manage_updates_slide_attrs_and_order(self) -> None:
        with tempfile.TemporaryDirectory(prefix="deck-manage-test-") as td:
            html_path = Path(td) / "deck.html"
            html_path.write_text(
                '<div class="deck">'
                '<div class="slide-frame"><div class="slide" data-layout="cover" '
                'data-screen-label="01 Cover" data-slide-key="cover"><p>A</p></div></div>'
                '<div class="slide-frame"><div class="slide" data-layout="quote" '
                'data-screen-label="02 Quote" data-slide-key="quote"><p>B</p></div></div>'
                '</div>',
                encoding="utf-8",
            )
            proc = subprocess.run(
                [
                    "python3",
                    str(ASSETS / "deck-manage.py"),
                    str(html_path),
                    "--slide",
                    "1",
                    "--accent",
                    "teal",
                    "--no-backup",
                ],
                cwd=REPO,
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            self.assertIn('data-accent="teal"', html_path.read_text(encoding="utf-8"))

            proc = subprocess.run(
                [
                    "python3",
                    str(ASSETS / "deck-manage.py"),
                    str(html_path),
                    "--move-slide",
                    "2",
                    "1",
                    "--no-backup",
                ],
                cwd=REPO,
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            html = html_path.read_text(encoding="utf-8")
            self.assertLess(html.index('data-slide-key="quote"'), html.index('data-slide-key="cover"'))

    def test_deck_screenshot_map(self) -> None:
        with tempfile.TemporaryDirectory(prefix="deck-screenshot-test-") as td:
            html_path = Path(td) / "deck.html"
            out_dir = Path(td) / "shots"
            html_path.write_text(
                '<div class="slide-frame"><div class="slide" data-layout="cover" '
                'data-screen-label="01 Cover" data-slide-key="cover">'
                '<p data-text-id="slide-01.title">Title</p></div></div>',
                encoding="utf-8",
            )
            proc = subprocess.run(
                ["python3", str(ASSETS / "deck-screenshot.py"), str(html_path), "--out", str(out_dir), "--map"],
                cwd=REPO,
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            self.assertIn("slide-01.title", (out_dir / "slide-map.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
