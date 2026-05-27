#!/usr/bin/env python3
"""Smoke-test P3 recipe / industry / product-module contract."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "server"))
os.environ.setdefault("CYRUS_MAGIC_DRY_RUN", "1")

import generator  # noqa: E402
import pitch_recipes  # noqa: E402
import slide_library  # noqa: E402


CASES = [
    ("给零售客户做首访 pitch", "消费零售", "客户pitch", "first-visit-pitch"),
    ("制造质量异常 POC 方案介绍", "制造", "POC方案", "poc-solution"),
    ("SaaS 客服知识库复盘续约", "SaaS", "复盘续约", "renewal-review"),
    ("教育行业案例包", "教育", "案例包", "industry-case-pack"),
    ("金融客户竞品替代方案", "金融", "竞品替代方案", "competitive-replacement"),
]


def main() -> int:
    p3 = pitch_recipes.validate()
    if not p3["ok"]:
        print("P3 knowledge validation failed", file=sys.stderr)
        print(json.dumps(p3, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1

    gate = slide_library.validate_library(include_candidates=False)
    if not gate["ok"] or gate["entries"] < 15:
        print("slide library is not ready for recipe suggestions", file=sys.stderr)
        print(json.dumps(gate, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1

    for brief_text, industry, deck_type, expected_recipe in CASES:
        plan = pitch_recipes.plan_pitch(
            {
                "title": brief_text,
                "brief": brief_text,
                "industry": industry,
                "deck_type": deck_type,
                "product_scope": ["飞书AI", "知识问答", "飞书Base"],
            }
        )
        if plan["recipe"]["id"] != expected_recipe:
            print(f"wrong recipe for {brief_text}: {plan['recipe']['id']}", file=sys.stderr)
            return 1
        if not plan["library_suggestions"]:
            print(f"no library suggestions for {brief_text}", file=sys.stderr)
            return 1

    task = generator.create_or_run_task(
        {
            "brief": {
                "title": "制造质量异常 POC 方案介绍",
                "customer_name": "示例制造客户",
                "industry": "制造",
                "audience": "质量负责人、IT 和工厂运营负责人",
                "objective": "确认一个质量异常进入四周试点",
                "deck_type": "POC方案",
                "business_moment": "质量异常复盘",
                "product_scope": ["知识问答", "飞书Base", "飞书任务"],
            }
        }
    )
    if task.get("status") != "succeeded":
        print("generator task failed", file=sys.stderr)
        print(json.dumps(task, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1

    output_dir = Path(task["output_dir"])
    outline = json.loads((Path(task["input_dir"]) / "outline.json").read_text(encoding="utf-8"))
    if not outline.get("recipe_refs") or outline["recipe_refs"][0]["id"] != "poc-solution":
        print("outline missing recipe_refs", file=sys.stderr)
        return 1
    if not outline.get("library_suggestions"):
        print("outline missing library_suggestions", file=sys.stderr)
        return 1
    if not outline.get("product_module_refs"):
        print("outline missing product_module_refs", file=sys.stderr)
        return 1
    feedback = (output_dir / "FEEDBACK.md").read_text(encoding="utf-8")
    for phrase in ["Recipe 和素材建议", "推荐可复用 slide", "模板 backlog seed"]:
        if phrase not in feedback:
            print(f"feedback missing {phrase}", file=sys.stderr)
            return 1

    print(task["id"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
