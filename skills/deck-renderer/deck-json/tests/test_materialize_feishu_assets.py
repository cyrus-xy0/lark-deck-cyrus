"""Regression tests for Feishu/Lark file URL materialization."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "materialize-feishu-assets.py"

spec = importlib.util.spec_from_file_location("materialize_feishu_assets", SCRIPT)
materializer = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(materializer)


class MaterializeFeishuAssetsTest(unittest.TestCase):
    def test_extracts_file_tokens_from_supported_lark_hosts(self) -> None:
        self.assertEqual(
            materializer.token_from_feishu_file_url("https://feishu.cn/file/Idn3bLLiroZU78xxN7jcCJown2b"),
            "Idn3bLLiroZU78xxN7jcCJown2b",
        )
        self.assertEqual(
            materializer.token_from_feishu_file_url(
                "https://bytedance.larkoffice.com/file/AbC_123-def?from=doc"
            ),
            "AbC_123-def",
        )
        self.assertEqual(materializer.token_from_feishu_file_url("https://example.com/file/AbC_123"), "")

    def test_rewrites_nested_deck_strings_by_token(self) -> None:
        deck = {
            "assets": {
                "scenes": {
                    "map": "https://feishu.cn/file/Idn3bLLiroZU78xxN7jcCJown2b?from=doc"
                }
            },
            "slides": [
                {
                    "key": "scene",
                    "data": {
                        "src": "https://bytedance.larkoffice.com/file/AbC123",
                        "caption": "source https://example.com/file/not-lark",
                    },
                }
            ],
        }
        urls = materializer.find_feishu_file_urls(deck)
        self.assertEqual(len(urls), 2)

        rewritten = materializer.rewrite_feishu_file_urls(
            deck,
            {
                "Idn3bLLiroZU78xxN7jcCJown2b": "assets/source-media/map.png",
                "AbC123": "assets/source-media/source.png",
            },
        )
        self.assertEqual(rewritten["assets"]["scenes"]["map"], "assets/source-media/map.png")
        self.assertEqual(rewritten["slides"][0]["data"]["src"], "assets/source-media/source.png")
        self.assertIn("https://example.com/file/not-lark", rewritten["slides"][0]["data"]["caption"])

    def test_cli_dry_run_reports_materialized_urls_without_lark_cli(self) -> None:
        with tempfile.TemporaryDirectory(prefix="materialize-feishu-test-") as td:
            root = Path(td)
            deck_path = root / "deck.json"
            report_path = root / "asset-materialization.json"
            md_path = root / "ASSET_MATERIALIZATION.md"
            deck_path.write_text(
                json.dumps(
                    {
                        "version": "1.0",
                        "deck": {"title": "Asset Test"},
                        "slides": [
                            {
                                "key": "scene",
                                "layout": "content",
                                "data": {"visual": "https://feishu.cn/file/Idn3bLLiroZU78xxN7jcCJown2b"},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            proc = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    str(deck_path),
                    str(root),
                    "--report",
                    str(report_path),
                    "--markdown",
                    str(md_path),
                    "--dry-run",
                    "--fail-on-unresolved",
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertTrue(report["ok"])
            self.assertEqual(report["summary"]["materialized"], 1)
            self.assertTrue(md_path.exists())

    def test_cli_no_urls_keeps_user_facing_markdown_absent(self) -> None:
        with tempfile.TemporaryDirectory(prefix="materialize-feishu-empty-") as td:
            root = Path(td)
            deck_path = root / "deck.json"
            md_path = root / "ASSET_MATERIALIZATION.md"
            deck_path.write_text(
                json.dumps({"version": "1.0", "deck": {"title": "No Assets"}, "slides": []}),
                encoding="utf-8",
            )

            proc = subprocess.run(
                [sys.executable, str(SCRIPT), str(deck_path), str(root), "--markdown", str(md_path)],
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            self.assertFalse(md_path.exists())

    def test_materialize_token_uses_relative_lark_output_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="materialize-feishu-cwd-") as td:
            root = Path(td)
            destination = root / "assets" / "source-media" / "asset.png"
            calls = []
            original = materializer.run_lark_cli

            def fake_run(cmd, cwd=None):
                calls.append((cmd, cwd))
                self.assertEqual(cwd, destination.parent)
                self.assertIn("--output", cmd)
                output_value = cmd[cmd.index("--output") + 1]
                self.assertEqual(output_value, destination.name)
                self.assertFalse(Path(output_value).is_absolute())
                destination.write_bytes(b"\x89PNG\r\n\x1a\nmini")
                return subprocess.CompletedProcess(cmd, 0, "ok", "")

            materializer.run_lark_cli = fake_run
            try:
                result = materializer.materialize_token("AbC123", destination, "user")
            finally:
                materializer.run_lark_cli = original

            self.assertTrue(result["ok"])
            self.assertEqual(result["method"], "media-preview")
            self.assertEqual(len(calls), 1)

    def test_unique_asset_path_keeps_token_when_hint_repeats(self) -> None:
        with tempfile.TemporaryDirectory(prefix="materialize-feishu-unique-") as td:
            root = Path(td)
            first = materializer.unique_asset_path(root, "TokenOne123456", "same source title")
            first.write_bytes(b"existing")
            second = materializer.unique_asset_path(root, "TokenTwo123456", "same source title")

            self.assertNotEqual(first.name, second.name)
            self.assertIn("TokenOne123", first.name)
            self.assertIn("TokenTwo123", second.name)


if __name__ == "__main__":
    unittest.main()
