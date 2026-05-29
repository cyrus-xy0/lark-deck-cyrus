#!/usr/bin/env python3
"""Smoke-test the P2 local slide library contract."""

from __future__ import annotations

import copy
import sys
import os
import tempfile
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "server"))
os.environ.setdefault("CYRUS_MAGIC_DRY_RUN", "1")
os.environ.setdefault("GENERATOR_VISUAL_AUDIT", "0")

import generator  # noqa: E402
import slide_library  # noqa: E402


def has_error(issues: list[dict[str, str]]) -> bool:
    return any(issue.get("severity") == "error" for issue in issues)


def assert_candidate_duplicate_rule() -> bool:
    seed = slide_library.load_business_entries(include_candidates=False)[0]
    seen_ids: set[str] = set()
    seen_approved_slide_keys: set[str] = set()
    seen_candidate_slide_refs: set[str] = set()
    seen_candidate_slide_keys: set[str] = set()
    entries = []
    for idx, deck_ref in enumerate(["runs/a/output/deck.json", "runs/b/output/deck.json"], start=1):
        row = copy.deepcopy(seed)
        row["id"] = f"candidate-duplicate-rule-{idx}"
        row["status"] = "candidate"
        row["source"]["level"] = "internal-draft"
        row["source"]["deck"] = deck_ref
        row["source"]["slide_key"] = "shared-semantic-key"
        row["slide"]["key"] = "shared-semantic-key"
        entries.append(row)
    issues = []
    for row in entries:
        issues.extend(slide_library.validate_entry(
            row,
            seen_ids=seen_ids,
            seen_slide_keys=seen_approved_slide_keys,
            seen_candidate_slide_refs=seen_candidate_slide_refs,
            seen_candidate_slide_keys=seen_candidate_slide_keys,
        ))
    return not any(issue.get("severity") == "error" for issue in issues)


def main() -> int:
    gate = slide_library.validate_library(include_candidates=False)
    if not gate["ok"] or gate["entries"] < 15:
        print("slide library gate failed or seed library is too small", file=sys.stderr)
        print(gate, file=sys.stderr)
        return 1
    if not assert_candidate_duplicate_rule():
        print("candidate duplicate slide-key rule rejected cross-source candidates", file=sys.stderr)
        return 1

    rows = slide_library.search_slides(query="飞书", industry="消费零售", limit=5)
    if not rows:
        print("slide library search returned no rows", file=sys.stderr)
        return 1
    for row in rows:
        for key in ["thumbnail", "insert_suggestion", "slide", "layout", "source"]:
            if not row.get(key):
                print(f"search row missing {key}", file=sys.stderr)
                print(row, file=sys.stderr)
                return 1

    with tempfile.TemporaryDirectory() as td:
        old_candidates = slide_library.CANDIDATES_DIR
        old_business = slide_library.BUSINESS_LIBRARY
        try:
            slide_library.CANDIDATES_DIR = Path(td) / "candidates"
            slide_library.BUSINESS_LIBRARY = Path(td) / "slides"
            task = generator.create_or_run_task(
                {
                    "brief": {
                        "title": "P2 slide library candidate smoke",
                        "customer_name": "示例客户",
                        "industry": "消费零售",
                        "audience": "GTM",
                        "objective": "验证候选入库",
                        "product_scope": ["飞书AI", "多维表格", "知识问答"],
                    }
                }
            )
            if task.get("status") != "succeeded":
                print("generator task for candidate failed", file=sys.stderr)
                print(task, file=sys.stderr)
                return 1
            result = slide_library.mark_reuse_candidate(
                task["id"],
                "business-gap",
                {
                    "thumbnail": "library/business/thumbnails/arch-stack.svg",
                    "industry": ["消费零售"],
                    "product": ["飞书AI"],
                    "customer_stage": ["首访"],
                    "deck_type": ["客户pitch"],
                    "value_prop": ["业务闭环"],
                    "tags": ["值得复用", "候选"],
                },
            )
            approved = slide_library.approve_candidate(result["entry"]["id"], reviewer="maintainer")
            if not approved["ok"]:
                print("candidate approval failed", file=sys.stderr)
                print(approved, file=sys.stderr)
                return 1
            approved_rows = slide_library.search_slides(query="业务闭环", include_candidates=False)
            if not approved_rows:
                print("approved candidate was not searchable", file=sys.stderr)
                return 1
        finally:
            slide_library.CANDIDATES_DIR = old_candidates
            slide_library.BUSINESS_LIBRARY = old_business
    if has_error(result["issues"]):
        print("candidate gate produced errors", file=sys.stderr)
        print(result, file=sys.stderr)
        return 1

    print(rows[0]["id"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
