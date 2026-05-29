"""iframe-embed prototype contract checks."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
DECK_JSON = HERE.parent
VALIDATE = DECK_JSON / "validate-deck.py"


def deck_with_src(src: str, **data_overrides):
    data = {
        "title": "Taste Radar demo",
        "src": src,
        "iframe_title": "Taste Radar demo",
        "hint": "可点击演示",
        "prototype_kind": "dashboard",
        "interaction": "clickable",
    }
    data.update(data_overrides)
    return {
        "version": "1.0",
        "deck": {"title": "Iframe contract test"},
        "slides": [
            {
                "key": "taste-radar-demo",
                "layout": "iframe-embed",
                "motion_policy": "iframe-native",
                "data": data,
            }
        ],
    }


class IframeContractTest(unittest.TestCase):
    def run_validator(self, root: Path, payload: dict) -> tuple[int, str]:
        path = root / "deck.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(VALIDATE), str(path)],
            capture_output=True,
            text=True,
        )
        return proc.returncode, proc.stdout + proc.stderr

    def test_local_packaged_prototype_validates(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            proto = root / "prototypes" / "taste-radar" / "index.html"
            proto.parent.mkdir(parents=True)
            proto.write_text("<!doctype html><title>demo</title>", encoding="utf-8")
            rc, log = self.run_validator(root, deck_with_src("prototypes/taste-radar/index.html"))
            self.assertEqual(rc, 0, log)

    def test_file_url_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            rc, log = self.run_validator(Path(td), deck_with_src("file:///Users/me/demo.html"))
            self.assertNotEqual(rc, 0)
            self.assertIn("file://", log)

    def test_remote_url_requires_explicit_allow_remote(self):
        with tempfile.TemporaryDirectory() as td:
            rc, log = self.run_validator(Path(td), deck_with_src("https://example.com/demo.html"))
            self.assertNotEqual(rc, 0)
            self.assertIn("allow_remote:true", log)

    def test_missing_local_prototype_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            rc, log = self.run_validator(Path(td), deck_with_src("prototypes/missing/index.html"))
            self.assertNotEqual(rc, 0)
            self.assertIn("does not exist", log)

    def test_parent_directory_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            outside = root.parent / f"demo-outside-{root.name}.html"
            outside.write_text("<!doctype html>", encoding="utf-8")
            rc, log = self.run_validator(root, deck_with_src(f"../{outside.name}"))
            outside.unlink(missing_ok=True)
            self.assertNotEqual(rc, 0)
            self.assertIn("escapes the deck folder", log)

    def test_iframe_native_motion_requires_embed_surface(self):
        with tempfile.TemporaryDirectory() as td:
            payload = {
                "version": "1.0",
                "deck": {"title": "Motion mismatch"},
                "slides": [
                    {
                        "key": "ordinary-content",
                        "layout": "content",
                        "variant": "3up",
                        "motion_policy": "iframe-native",
                        "data": {
                            "title": "普通内容页",
                            "cards": [
                                {"title": "A", "body": "内容"},
                                {"title": "B", "body": "内容"},
                                {"title": "C", "body": "内容"},
                            ],
                        },
                    }
                ],
            }
            rc, log = self.run_validator(Path(td), payload)
            self.assertNotEqual(rc, 0)
            self.assertIn("iframe-native motion_policy", log)


if __name__ == "__main__":
    unittest.main()
