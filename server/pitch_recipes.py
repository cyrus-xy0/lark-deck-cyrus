#!/usr/bin/env python3
"""P3 pitch recipe and industry knowledge selector."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import slide_library


REPO = Path(__file__).resolve().parents[1]
RECIPES_DIR = REPO / "knowledge/recipes"
INDUSTRIES_DIR = REPO / "knowledge/industries"
PRODUCT_MODULES = REPO / "knowledge/product-modules.json"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_list(value: Any) -> list[str]:
    return slide_library.normalize_list(value)


def text_blob(*values: Any) -> str:
    parts: list[str] = []
    for value in values:
        if isinstance(value, dict):
            parts.extend(str(v) for v in value.values())
        elif isinstance(value, list):
            parts.extend(str(v) for v in value)
        elif value:
            parts.append(str(value))
    return " ".join(parts).lower()


def load_recipes() -> list[dict[str, Any]]:
    recipes = []
    for path in sorted(RECIPES_DIR.glob("*.json")):
        recipe = read_json(path)
        recipe["_path"] = path.relative_to(REPO).as_posix()
        recipes.append(recipe)
    return recipes


def load_industry_packs() -> list[dict[str, Any]]:
    packs = []
    for path in sorted(INDUSTRIES_DIR.glob("*.json")):
        pack = read_json(path)
        pack["_path"] = path.relative_to(REPO).as_posix()
        packs.append(pack)
    return packs


def load_product_modules() -> dict[str, Any]:
    if PRODUCT_MODULES.exists():
        return read_json(PRODUCT_MODULES)
    return {"version": "1.0", "modules": []}


def score_tokens(blob: str, tokens: list[str]) -> int:
    score = 0
    for token in tokens:
        token_l = str(token).lower()
        if token_l and token_l in blob:
            score += 1
    return score


def select_recipe(brief: dict[str, Any]) -> dict[str, Any]:
    blob = text_blob(
        brief.get("deck_type"),
        brief.get("objective"),
        brief.get("business_moment"),
        brief.get("title"),
        brief.get("brief"),
    )
    best: tuple[int, dict[str, Any] | None] = (-1, None)
    for recipe in load_recipes():
        score = score_tokens(blob, normalize_list(recipe.get("triggers")))
        score += score_tokens(blob, normalize_list(recipe.get("deck_type"))) * 2
        if score > best[0]:
            best = (score, recipe)
    recipes = load_recipes()
    if best[0] <= 0:
        return next((recipe for recipe in recipes if recipe.get("id") == "first-visit-pitch"), recipes[0])
    return best[1] or recipes[0]


def select_industry_pack(brief: dict[str, Any]) -> dict[str, Any]:
    blob = text_blob(brief.get("industry"), brief.get("business_moment"), brief.get("title"), brief.get("brief"))
    best: tuple[int, dict[str, Any] | None] = (-1, None)
    for pack in load_industry_packs():
        tokens = normalize_list(pack.get("aliases") or pack.get("industry"))
        score = score_tokens(blob, tokens)
        if score > best[0]:
            best = (score, pack)
    packs = load_industry_packs()
    if best[0] <= 0:
        return next((pack for pack in packs if pack.get("id") == "horizontal-collaboration"), packs[0])
    return best[1] or packs[0]


def product_refs(brief: dict[str, Any]) -> list[dict[str, Any]]:
    modules = load_product_modules().get("modules", [])
    blob = text_blob(brief.get("product_scope"), brief.get("title"), brief.get("brief"))
    matched = []
    for module in modules:
        tokens = normalize_list(module.get("aliases") or module.get("name"))
        if score_tokens(blob, tokens):
            matched.append(module)
    if not matched:
        matched = modules[:3]
    return matched[:6]


def library_suggestions(recipe: dict[str, Any], industry_pack: dict[str, Any], brief: dict[str, Any], limit: int = 8) -> list[dict[str, Any]]:
    industry = str(brief.get("industry") or (industry_pack.get("industry") or ["通用"])[0])
    products = normalize_list(brief.get("product_scope")) or ["飞书"]
    suggestions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for query in recipe.get("library_queries", []):
        rows = slide_library.search_slides(
            query=query.get("query", ""),
            industry=query.get("industry", industry),
            product=query.get("product", products[0] if products else ""),
            customer_stage=query.get("customer_stage", ""),
            deck_type=query.get("deck_type", ""),
            value_prop=query.get("value_prop", ""),
            layout=query.get("layout", ""),
            limit=query.get("limit", 3),
        )
        if not rows:
            rows = slide_library.search_slides(
                query=query.get("query", ""),
                industry=query.get("industry", industry),
                layout=query.get("layout", ""),
                limit=query.get("limit", 3),
            )
        if not rows:
            rows = slide_library.search_slides(
                query=query.get("query", ""),
                layout=query.get("layout", ""),
                limit=query.get("limit", 3),
            )
        for row in rows:
            row_id = str(row.get("id"))
            if row_id in seen:
                continue
            seen.add(row_id)
            suggestions.append(
                {
                    "id": row.get("id"),
                    "title": row.get("title"),
                    "layout": row.get("layout"),
                    "variant": row.get("variant", ""),
                    "thumbnail": row.get("thumbnail", ""),
                    "source": row.get("source", {}),
                    "reason": query.get("reason", "匹配当前 recipe 的推荐页面。"),
                    "insert_suggestion": row.get("insert_suggestion"),
                }
            )
            if len(suggestions) >= limit:
                return suggestions
    return suggestions


def plan_pitch(brief: dict[str, Any]) -> dict[str, Any]:
    recipe = select_recipe(brief)
    industry_pack = select_industry_pack(brief)
    products = product_refs(brief)
    suggestions = library_suggestions(recipe, industry_pack, brief)
    return {
        "recipe": {
            "id": recipe["id"],
            "name": recipe["name"],
            "path": recipe.get("_path"),
            "deck_type": recipe.get("deck_type", []),
            "narrative_arc": recipe.get("narrative_arc", []),
            "required_questions": recipe.get("required_questions", [])[:5],
            "recommended_layouts": recipe.get("recommended_layouts", []),
        },
        "industry": {
            "id": industry_pack["id"],
            "name": industry_pack["name"],
            "path": industry_pack.get("_path"),
            "business_moments": industry_pack.get("business_moments", []),
            "key_roles": industry_pack.get("key_roles", []),
            "core_pains": industry_pack.get("core_pains", []),
            "evidence_suggestions": industry_pack.get("evidence_suggestions", []),
            "recommended_layouts": industry_pack.get("recommended_layouts", []),
        },
        "products": products,
        "library_suggestions": suggestions,
        "template_backlog_seed": recipe.get("template_backlog_seed", []),
    }


def validate() -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    recipes = load_recipes()
    packs = load_industry_packs()
    if len(recipes) < 5:
        issues.append({"code": "P3-RECIPES", "message": "expected at least 5 recipes"})
    if len(packs) < 7:
        issues.append({"code": "P3-INDUSTRIES", "message": "expected at least 7 industry packs"})
    for recipe in recipes:
        for key in ["id", "name", "deck_type", "narrative_arc", "required_questions", "recommended_layouts", "library_queries"]:
            if not recipe.get(key):
                issues.append({"code": "P3-RECIPE-FIELD", "message": f"{recipe.get('id')} missing {key}"})
    for pack in packs:
        for key in ["id", "name", "aliases", "business_moments", "key_roles", "core_pains", "evidence_suggestions", "recommended_layouts"]:
            if not pack.get(key):
                issues.append({"code": "P3-INDUSTRY-FIELD", "message": f"{pack.get('id')} missing {key}"})
    modules = load_product_modules().get("modules", [])
    if len(modules) < 7:
        issues.append({"code": "P3-PRODUCTS", "message": "expected at least 7 product modules"})
    return {"ok": not issues, "recipes": len(recipes), "industries": len(packs), "product_modules": len(modules), "issues": issues}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="select recipe, industry pack, product modules, and library suggestions")
    plan.add_argument("--brief-json", type=Path)
    plan.add_argument("--brief", default="")
    plan.add_argument("--industry", default="")
    plan.add_argument("--deck-type", default="")
    plan.add_argument("--product-scope", default="")

    sub.add_parser("validate", help="validate P3 knowledge assets")
    args = parser.parse_args(argv)

    if args.command == "plan":
        if args.brief_json:
            brief = read_json(args.brief_json).get("brief", read_json(args.brief_json))
        else:
            brief = {
                "brief": args.brief,
                "title": args.brief,
                "industry": args.industry,
                "deck_type": args.deck_type,
                "product_scope": args.product_scope,
            }
        print(json.dumps(plan_pitch(brief), ensure_ascii=False, indent=2))
        return 0
    if args.command == "validate":
        result = validate()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1
    raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
