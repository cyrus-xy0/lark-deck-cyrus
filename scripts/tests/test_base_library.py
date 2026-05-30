"""Regression tests for Base/local library retrieval behavior."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "base_library.py"

spec = importlib.util.spec_from_file_location("base_library", SCRIPT)
base_library = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(base_library)


class BaseLibraryFallbackTest(unittest.TestCase):
    def test_auto_mode_empty_cloud_results_fall_back_to_local_knowledge(self) -> None:
        config = base_library.load_config()
        original_can_try_base = base_library.can_try_base
        original_search_records = base_library.search_records
        original_library_mode = base_library.library_mode
        try:
            base_library.can_try_base = lambda _config: True
            base_library.search_records = lambda *_args, **_kwargs: []
            base_library.library_mode = lambda _config: "auto"
            rows = base_library.search_with_fallback(config, "knowledge", "制造 质量", "user", 1)
        finally:
            base_library.can_try_base = original_can_try_base
            base_library.search_records = original_search_records
            base_library.library_mode = original_library_mode

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["文档ID"], "manufacturing")

    def test_forced_base_mode_keeps_empty_cloud_results(self) -> None:
        config = base_library.load_config()
        original_can_try_base = base_library.can_try_base
        original_search_records = base_library.search_records
        original_library_mode = base_library.library_mode
        try:
            base_library.can_try_base = lambda _config: True
            base_library.search_records = lambda *_args, **_kwargs: []
            base_library.library_mode = lambda _config: "base"
            rows = base_library.search_with_fallback(config, "knowledge", "制造 质量", "user", 1)
        finally:
            base_library.can_try_base = original_can_try_base
            base_library.search_records = original_search_records
            base_library.library_mode = original_library_mode

        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
