#!/usr/bin/env python3
"""Minimal server-side generator wrapper for lark-deck-cyrus.

This is the productized P0 path around the existing local skills:

  Brief -> Outline -> DeckJSON -> renderer -> validator -> editable zip

It intentionally uses only the Python standard library so it can run anywhere
the current repo already runs.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import html
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import slide_library
import pitch_recipes


REPO = Path(__file__).resolve().parents[1]
RUNS_DIR = REPO / "runs"
OUTLINE_VALIDATOR = REPO / "skills/deck-planner/validate-outline.py"
RENDERER = REPO / "skills/deck-renderer/deck-json/render-deck.py"
CHECK_ONLY = REPO / "skills/deck-renderer/assets/check-only.sh"
PACKAGE = REPO / "skills/deck-renderer/assets/package-deliverable.sh"
BASE_LIBRARY = REPO / "scripts/base_library.py"

REQUIRED_OUTPUTS = [
    "deck.json",
    "index.html",
    "texts.md",
    "FEEDBACK.md",
    "assets-manifest.yaml",
    "journey.json",
    "JOURNEY.md",
    "quality-insights.json",
]

TEXT_LEAF_SKIP_KEYS = {"title", "icon", "img", "image", "src", "url", "href", "company_logo"}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def compact_date() -> str:
    return datetime.now().strftime("%Y.%m.%d")


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def slugify(value: str, fallback: str = "deck") -> str:
    raw = (value or "").strip().lower()
    raw = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
    if not raw or not raw[0].isalpha():
        digest = hashlib.sha1((value or fallback).encode("utf-8")).hexdigest()[:8]
        raw = f"{fallback}-{digest}"
    return raw[:48].strip("-")


def normalize_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            parts.extend(normalize_list(item))
        return parts
    if isinstance(value, str):
        parts = re.split(r"[,;，；、\n]+", value)
        return [p.strip() for p in parts if p.strip()]
    return [str(value).strip()]


def brief_value(brief: dict[str, Any], *keys: str, default: str = "") -> str:
    for key in keys:
        value = brief.get(key)
        if value:
            return str(value).strip()
    return default


def base_identity() -> str:
    return os.environ.get("LARK_LIBRARY_AS", "user")


def use_base_library() -> bool:
    return os.environ.get("GENERATOR_USE_BASE_LIBRARY", "").lower() in {"1", "true", "yes"}


def sync_base_assets() -> bool:
    return os.environ.get("GENERATOR_SYNC_BASE_ASSETS", "").lower() in {"1", "true", "yes"}


def health_payload() -> dict[str, Any]:
    gate = slide_library.validate_library(include_candidates=False)
    p3 = pitch_recipes.validate()
    return {
        "ok": True,
        "service": "lark-deck-generator",
        "time": now_iso(),
        "runs_dir": str(RUNS_DIR),
        "renderer": str(RENDERER),
        "renderer_exists": RENDERER.exists(),
        "validator_exists": CHECK_ONLY.exists(),
        "base_library": {
            "enabled": use_base_library(),
            "sync_assets": sync_base_assets(),
            "identity": base_identity(),
        },
        "output_contract": REQUIRED_OUTPUTS + ["editable zip", "validator-report.md", "task.json"],
        "library": {
            "business_entries": gate["entries"],
            "gate_ok": gate["ok"],
            "design_kit": str(slide_library.DESIGN_KIT),
        },
        "recipes": {
            "ok": p3["ok"],
            "recipes": p3["recipes"],
            "industries": p3["industries"],
            "product_modules": p3["product_modules"],
        },
    }


def query_base_library(command: str, keyword: str, limit: int = 5) -> list[dict[str, Any]]:
    proc = subprocess.run(
        [
            sys.executable,
            str(BASE_LIBRARY),
            "--as",
            base_identity(),
            command,
            keyword,
            "--limit",
            str(limit),
            "--format",
            "json",
        ],
        cwd=REPO,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Base library query failed: {command} {keyword}\n{proc.stderr or proc.stdout}")
    return json.loads(proc.stdout)


def local_knowledge_refs(industry: str, business_moment: str, product_scope: list[str]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    text = " ".join([industry, business_moment, *product_scope]).lower()
    try:
        pack = pitch_recipes.select_industry_pack({"industry": industry, "business_moment": business_moment})
    except Exception:
        pack = {}
    if pack:
        refs.append(
            {
                "source": "local-cache",
                "query": f"行业包 {pack.get('name')}",
                "title": f"行业包 · {pack.get('name')}",
                "cache_path": pack.get("_path", ""),
                "summary": "本地 P3 行业知识包,等待进入 Base 知识库正式表。",
                "used_for": "作为业务时刻、关键角色、核心痛点、证据建议和推荐页型参考；不得把通用行业知识写成客户事实。",
            }
        )
    retail = REPO / "knowledge/industries/retail-consumer.md"
    if retail.exists() and any(term in text for term in ["消费零售", "零售", "餐饮", "retail", "consumer"]):
        refs.append(
            {
                "source": "local-cache",
                "query": "消费零售 连锁餐饮 行业包",
                "title": "行业包 · 消费零售 / 连锁餐饮",
                "cache_path": "knowledge/industries/retail-consumer.md",
                "used_for": "作为场景痛点、证据纪律和推荐页型参考；不得把通用行业知识写成客户事实。",
            }
        )
    if not refs and (REPO / "knowledge/README.md").exists():
        refs.append(
            {
                "source": "local-cache",
                "query": "知识库 使用说明",
                "title": "知识库使用说明",
                "cache_path": "knowledge/README.md",
                "used_for": "作为生成链路的知识来源纪律参考；缺少行业包时保留待确认问题。",
            }
        )
    return refs


def base_knowledge_refs(industry: str, business_moment: str, product_scope: list[str]) -> list[dict[str, Any]]:
    fallback_refs = local_knowledge_refs(industry, business_moment, product_scope)
    if not use_base_library():
        return fallback_refs

    keyword_candidates = [
        " ".join([industry, business_moment, *product_scope]).strip(),
        industry,
        business_moment,
        *product_scope[:2],
        "行业包",
    ]
    rows: list[dict[str, Any]] = []
    seen_records: set[str] = set()
    for keyword in [k for k in keyword_candidates if k]:
        try:
            found_rows = query_base_library("search-knowledge", keyword, limit=3)
        except Exception:
            return fallback_refs
        for row in found_rows:
            record_id = str(row.get("_record_id") or row.get("文档ID") or row.get("标题") or "")
            if record_id in seen_records:
                continue
            seen_records.add(record_id)
            rows.append(row)
            if len(rows) >= 3:
                break
        if len(rows) >= 3:
            break
    refs = []
    for row in rows:
        refs.append(
            {
                "source": "feishu-base",
                "table": "知识库",
                "record_id": row.get("_record_id", ""),
                "doc_id": row.get("文档ID", ""),
                "title": row.get("标题", ""),
                "cache_path": row.get("本地路径", ""),
                "summary": row.get("摘要", ""),
                "used_for": "作为场景痛点、证据纪律和素材计划参考；不得把通用知识写成客户事实。",
            }
        )
    return refs or fallback_refs


def high_value_questions(brief: dict[str, Any]) -> list[str]:
    checks = [
        ("customer_name", "客户是谁,是否需要使用客户 logo 或已有案例?"),
        ("industry", "客户所属行业和最关键的业务时刻是什么?"),
        ("audience", "这份 deck 讲给谁,他们要做什么决策?"),
        ("objective", "讲完后希望客户确认的下一步是什么?"),
        ("product_scope", "本次要重点讲哪些飞书产品或能力边界?"),
        ("attachments", "是否有可引用的附件、截图、客户材料或公开来源?"),
    ]
    questions = [q for key, q in checks if not brief.get(key)]
    return questions[:5]


def enrich_slide_plan(slide: dict[str, Any]) -> dict[str, Any]:
    """Fill required deck-planner talk-intent fields for generated outlines."""
    out = copy.deepcopy(slide)
    message = str(out.get("message") or out.get("title") or "本页需要支撑整体 pitch 主线。")
    title = str(out.get("title") or out.get("key") or "页面")
    role = str(out.get("role") or "context")
    assets = normalize_list(out.get("assets"))
    evidence = normalize_list(out.get("evidence"))
    risks = normalize_list(out.get("risk_flags"))
    out.setdefault("key_idea", message)
    out.setdefault("emphasis", f"让客户在这一页明确理解: {message}")
    out.setdefault("talk_track", f"讲这一页时先点题“{title}”,再用业务语境解释为什么它会影响下一步决策。")
    out.setdefault("proof_needed", evidence)
    out.setdefault("asset_need", assets)
    out.setdefault("risk", risks)
    if role not in {"cover", "closing"} and not out["risk"]:
        out["risk"] = ["缺少客户事实时,只能作为待验证判断。"]
    return out


def brief_to_outline(brief: dict[str, Any]) -> dict[str, Any]:
    pitch_plan = pitch_recipes.plan_pitch(brief)
    recipe = pitch_plan["recipe"]
    industry_pack = pitch_plan["industry"]
    product_refs = pitch_plan["products"]
    library_suggestions = pitch_plan["library_suggestions"]
    title = brief_value(brief, "title", "brief", default="客户 pitch deck")
    customer = brief_value(brief, "customer_name", "customer", default="目标客户")
    industry = brief_value(brief, "industry", default=industry_pack["name"])
    audience = brief_value(
        brief,
        "audience",
        "target_audience",
        default="、".join(industry_pack.get("key_roles", [])[:2]) or "客户业务负责人和项目推动者",
    )
    objective = brief_value(brief, "objective", default="推动客户确认下一步试点")
    success_metric = brief_value(brief, "success_metric", default="确认试点场景、负责人和时间表")
    product_scope = normalize_list(brief.get("product_scope")) or [item["name"] for item in product_refs[:3]] or ["飞书 AI", "多维表格", "知识库", "任务闭环"]
    business_moment = brief_value(
        brief,
        "business_moment",
        default=(industry_pack.get("business_moments") or ["方案共创和试点决策"])[0],
    )
    core_tension = brief_value(
        brief,
        "core_tension",
        default=";".join(industry_pack.get("core_pains", [])[:2]) or "业务目标明确,但流程、知识、数据和复盘尚未形成可追踪闭环",
    )
    solution_angle = brief_value(
        brief,
        "solution_angle",
        default=(product_refs[0]["narrative"] if product_refs else "用飞书把入口、任务、知识和数据连成可试点、可复盘的工作流"),
    )

    industry_pains = industry_pack.get("core_pains", []) or []
    evidence_suggestions = industry_pack.get("evidence_suggestions", []) or []
    pain_points = []
    for idx, pain in enumerate(industry_pains[:2]):
        evidence = evidence_suggestions[idx] if idx < len(evidence_suggestions) else "真实流程、截图、表格或会议材料"
        pain_points.append(
            {
                "name": pain[:18],
                "why_now": f"{business_moment}阶段,这个问题会直接影响推进节奏。",
                "impact": pain,
                "evidence_level": "hypothesis",
                "evidence_needed": f"需要用户补充{evidence}。",
            }
        )
    while len(pain_points) < 2:
        pain_points.append(
            {
                "name": "流程断点",
                "why_now": "业务节奏加快后,靠人工同步很难持续追踪动作。",
                "impact": "团队容易停留在沟通完成,但责任、异常和复盘没有闭环。",
                "evidence_level": "hypothesis",
                "evidence_needed": "需要用户补充真实流程、截图、表格或会议材料。",
            }
        )

    slides = [
        {
            "key": "cover",
            "title": title,
            "role": "cover",
            "message": f"面向{customer}的{industry}方案。",
            "layout_candidate": {"layout": "cover"},
            "assets": ["customer-logo"],
        },
        {
            "key": "business-gap",
            "title": "业务断点",
            "role": "pain",
            "message": core_tension,
            "content_beats": [p["name"] for p in pain_points],
            "layout_candidate": {"layout": "content", "variant": "before-after"},
            "assets": [],
            "risk_flags": ["缺少客户提供证据时,不得写成已验证事实。"],
        },
        {
            "key": "solution-loop",
            "title": "飞书工作流闭环",
            "role": "solution",
            "message": solution_angle,
            "content_beats": product_scope,
            "layout_candidate": {"layout": "arch-stack"},
            "assets": ["product-icons"],
        },
        {
            "key": "pilot-metrics",
            "title": "试点指标",
            "role": "evidence",
            "message": "先定义验证口径,不提前承诺结果。",
            "layout_candidate": {"layout": "stats", "variant": "row"},
            "assets": ["pilot-data"],
        },
        {
            "key": "pilot-path",
            "title": "试点路径",
            "role": "roadmap",
            "message": "从一个具体场景开始,跑完闭环后再扩展。",
            "layout_candidate": {"layout": "flow", "variant": "timeline"},
            "assets": [],
        },
        {
            "key": "next-step",
            "title": "下一步",
            "role": "closing",
            "message": success_metric,
            "layout_candidate": {"layout": "end"},
            "assets": [],
        },
    ]
    slides = [enrich_slide_plan(slide) for slide in slides]

    return {
        "version": "1.0",
        "brief": {
            "title": title,
            "audience": audience,
            "requester_context": brief_value(brief, "requester_context", default="generator wrapper"),
            "objective": objective,
            "success_metric": success_metric,
            "delivery_mode": brief_value(brief, "delivery_mode", default="feishu-bot"),
            "constraints": ["默认中文", "不能编造客户数据", "缺证据时写成待确认问题", f"使用 recipe: {recipe['name']}"],
        },
        "scene": {
            "industry": industry,
            "segment": brief_value(brief, "segment", default=""),
            "user_role": audience,
            "business_moment": business_moment,
            "core_tension": core_tension,
            "confidence": "low" if high_value_questions(brief) else "medium",
        },
        "thesis": {
            "one_sentence": f"{customer}可以先围绕一个{business_moment}场景,验证{solution_angle}。",
            "pain_points": pain_points,
            "solution_angle": solution_angle,
            "differentiation": "从单页功能展示升级为可验证、可复盘、可扩展的业务闭环。",
        },
        "knowledge_refs": base_knowledge_refs(industry, business_moment, product_scope),
        "recipe_refs": [
            {
                "id": recipe["id"],
                "name": recipe["name"],
                "path": recipe.get("path", ""),
                "used_for": "决定 pitch 叙事结构、必问问题、推荐页型和素材检索策略。",
                "narrative_arc": recipe.get("narrative_arc", []),
                "recommended_layouts": recipe.get("recommended_layouts", []),
            }
        ],
        "library_suggestions": library_suggestions,
        "product_module_refs": [
            {
                "id": item["id"],
                "name": item["name"],
                "narrative": item["narrative"],
                "proof_suggestions": item.get("proof_suggestions", []),
                "recommended_layouts": item.get("recommended_layouts", []),
            }
            for item in product_refs
        ],
        "template_backlog_seed": pitch_plan.get("template_backlog_seed", []),
        "outline": {
            "arc": " -> ".join(recipe.get("narrative_arc", [])) or "客户场景 -> 业务断点 -> 飞书闭环 -> 试点指标 -> 试点路径 -> 下一步",
            "slides": slides,
        },
        "asset_plan": [
            {
                "id": "customer-logo",
                "type": "logo",
                "need": "客户官方 logo",
                "query": customer,
                "preferred_source": "feishu-base",
                "fallback": "缺失时不伪造商标,只使用文字客户名。",
                "required": False,
            },
            {
                "id": "product-icons",
                "type": "icon",
                "need": "飞书产品标识或能力 icon",
                "query": "、".join(product_scope),
                "preferred_source": "feishu-base",
                "fallback": "使用文字 pill,不手绘商标。",
                "required": False,
            },
            {
                "id": "pilot-data",
                "type": "data",
                "need": "试点指标口径和基线数据",
                "preferred_source": "user-provided",
                "fallback": "只写指标定义和待确认项。",
                "required": False,
            },
        ],
        "open_questions": high_value_questions(brief),
        "claim_discipline": {
            "unsupported_claims": ["不能声明客户已经实现的百分比提升或具名访谈结论。"],
            "needs_user_confirmation": high_value_questions(brief)
            or ["试点范围、指标口径和客户版本边界。"],
        },
        "handoff": {
            "target_skill": "deck-renderer",
            "deckjson_strategy": "direct",
            "notes": "generator wrapper 生成确定性初稿;真实客户交付前应补齐 open questions。",
        },
    }


def outline_to_deck(outline: dict[str, Any]) -> dict[str, Any]:
    brief = outline["brief"]
    scene = outline["scene"]
    thesis = outline["thesis"]
    customer = "目标客户"
    title = brief["title"]
    slug = slugify(title)
    product_scope = outline["outline"]["slides"][2].get("content_beats") or ["飞书 AI", "多维表格", "知识库", "任务"]
    product_scope = product_scope[:4]

    before_items = [p["impact"] for p in thesis.get("pain_points", [])][:3]
    while len(before_items) < 3:
        before_items.append("关键动作和复盘信息分散,推进依赖人工提醒。")
    after_items = [
        "入口统一到飞书消息 / bot / 表单。",
        "动作进入任务、表格或知识库,责任和状态可追踪。",
        "复盘沉淀为下一次可复用的知识和页面。",
    ]

    deck = {
        "version": "1.0",
        "deck": {
            "title": title,
            "author": "lark-deck-cyrus generator",
            "date": compact_date(),
            "presentation_date": today(),
            "customer_slug": slug,
            "language": "zh-only",
            "mode": "rewrite",
        },
        "slides": [
            {
                "key": "cover",
                "layout": "cover",
                "data": {
                    "title": title,
                    "author": "方案初稿",
                    "date": f"{scene['industry']} · {compact_date()}",
                },
            },
            {
                "key": "business-gap",
                "layout": "content",
                "variant": "before-after",
                "accent": "orange",
                "data": {
                    "title": "这份方案先解决一个问题:业务动作能否闭环",
                    "before": {"tag": "现状 · 分散推进", "items": before_items},
                    "pivot": {"caption": "飞书工作流"},
                    "after": {"tag": "目标 · 可追踪闭环", "items": after_items},
                },
            },
            {
                "key": "solution-loop",
                "layout": "arch-stack",
                "accent": "blue",
                "data": {
                    "title": "用飞书把入口、能力、对象和治理连成一条链",
                    "layers": [
                        {"name": {"title": "业务入口", "sub": "GTM / 客户"}, "modules": ["飞书 bot", "表单", "群聊", "移动端"]},
                        {"name": {"title": "产品能力", "sub": "重点范围"}, "modules": product_scope},
                        {"name": {"title": "业务对象", "sub": "可追踪"}, "modules": ["任务", "知识", "数据", "复盘"]},
                        {"name": {"title": "治理底座", "sub": "可交付"}, "modules": ["权限", "来源", "版本", "看板"]},
                    ],
                },
            },
            {
                "key": "pilot-metrics",
                "layout": "stats",
                "variant": "row",
                "accent": "teal",
                "data": {
                    "title": "试点先看口径,不提前承诺效果",
                    "cols": [
                        {"icon": "target", "num": "1", "unit": "个", "label": "先选一个具体业务场景"},
                        {"icon": "users", "num": "N", "unit": "人", "label": "试点角色和范围由客户确认"},
                        {"icon": "clipboard-check", "num": "3", "unit": "类", "label": "跟踪动作、异常、复盘沉淀"},
                    ],
                    "footnote": "所有结果数字需试点后由客户数据确认。",
                },
            },
            {
                "key": "pilot-path",
                "layout": "flow",
                "variant": "timeline",
                "accent": "blue",
                "data": {
                    "title": "四步把初稿推进到可验证试点",
                    "cols": 4,
                    "nodes": [
                        {"when": "D1", "what": "确认场景", "desc": "补齐客户、受众、目标和材料边界。"},
                        {"when": "D2-3", "what": "接入素材", "desc": "整理 logo、流程截图、知识和指标口径。"},
                        {"when": "D4-7", "what": "试跑闭环", "desc": "用一个真实流程验证入口、任务和反馈。"},
                        {"when": "D8+", "what": "复盘扩展", "desc": "根据证据决定扩展、改版或入库复用。"},
                    ],
                },
            },
            {
                "key": "next-step",
                "layout": "end",
                "data": {"title": "下一步", "slogan": brief.get("success_metric") or "确认试点场景、素材和负责人"},
            },
        ],
    }
    if customer != "目标客户":
        deck["notes"] = f"Customer: {customer}"
    return deck


def run_command(cmd: list[str], log_path: Path, cwd: Path = REPO) -> subprocess.CompletedProcess[str]:
    started = time.time()
    proc = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)
    elapsed = time.time() - started
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        "$ " + " ".join(cmd) + "\n"
        + f"# exit={proc.returncode} elapsed={elapsed:.2f}s\n\n"
        + "## stdout\n"
        + proc.stdout
        + "\n## stderr\n"
        + proc.stderr,
        encoding="utf-8",
    )
    return proc


def delivery_name(deck: dict[str, Any]) -> str:
    meta = deck.get("deck", {})
    slug = meta.get("customer_slug") or slugify(meta.get("title", "deck"))
    date = meta.get("presentation_date") or today()
    return f"lark-{slug}-{date}"


def unique_generated_task_id(title_source: str) -> str:
    base = f"generator-{datetime.now():%Y%m%d-%H%M%S-%f}-{slugify(str(title_source))}"
    candidate = base
    suffix = 1
    while (RUNS_DIR / candidate).exists():
        suffix += 1
        candidate = f"{base}-{suffix:02d}"
    return candidate


def write_feedback(output_dir: Path, outline: dict[str, Any], deck: dict[str, Any], source: str) -> None:
    meta = deck.get("deck", {})
    questions = outline.get("open_questions") or []
    question_lines = "\n".join(f"- [ ] {q}" for q in questions) if questions else "- 无;本次输入已足够生成初稿。"
    recipe_refs = outline.get("recipe_refs") or []
    recipe_lines = "\n".join(
        f"- {ref.get('name')} (`{ref.get('id')}`): {ref.get('used_for')}"
        for ref in recipe_refs
    ) or "- 无"
    library_suggestions = outline.get("library_suggestions") or []
    library_lines = "\n".join(
        f"- `{item.get('id')}` · {item.get('title')} · {item.get('layout')}{('/' + item.get('variant')) if item.get('variant') else ''}: {item.get('reason')}"
        for item in library_suggestions
    ) or "- 暂无;需要补充更多 seed 或放宽检索条件。"
    backlog = outline.get("template_backlog_seed") or []
    backlog_lines = "\n".join(f"- [ ] {item}" for item in backlog) or "- [ ] 暂无新增模板需求。"
    content = f"""# Run feedback · {meta.get('title', 'deck')}

生成时间: {now_iso()}
来源: {source}
产物: DeckJSON-first HTML deck, {len(deck.get('slides', []))} slides

## 关键决策(本 run 实际发生的判断)

### 1. 使用 DeckJSON-first 生成
- **决策**: 先生成 `outline.json` 和 `deck.json`,再由 renderer 生成 `index.html`。
- **为什么**: 服务端链路需要稳定校验、可重渲染和可版本化,不能把 HTML 当源文件。
- **你的看法**:
  - [ ] 对
  - [ ] 应改成其他生成路径
  - [ ] 备注:

### 2. 缺证据的内容降级为待确认
- **决策**: 未提供客户数据或附件时,只写试点指标口径和待确认项。
- **为什么**: 产品规则禁止编造客户数据、具名引语或已实现效果。
- **你的看法**:
  - [ ] 对
  - [ ] 应补充真实证据后增强页面
  - [ ] 备注:

### 3. 固定产物已按服务端任务输出
- **决策**: 本次任务输出 `deck.json`、`index.html`、`texts.md`、`FEEDBACK.md`、`assets-manifest.yaml` 和可编辑 zip。
- **为什么**: GTM / Bot / Web 都需要同一套交付契约,方便预览、编辑、下载和追踪失败原因。
- **你的看法**:
  - [ ] 对
  - [ ] 需要增加其他产物
  - [ ] 备注:

## 本次没解决的小毛病

{question_lines}

## Recipe 和素材建议

### 使用的 pitch recipe

{recipe_lines}

### 推荐可复用 slide

{library_lines}

## 模板 backlog seed

{backlog_lines}

## 你的额外建议

-

---

累计 >=3 条值得反馈的(打钩 / 备注 / 自填),把这个文件发给 skill 维护者整合到下一版。
"""
    (output_dir / "FEEDBACK.md").write_text(content, encoding="utf-8")


def output_artifacts(task_id: str, output_dir: Path, base_url: str | None = None) -> dict[str, str]:
    artifacts: dict[str, str] = {}
    for path in sorted(output_dir.iterdir()):
        if path.is_file():
            artifacts[path.name] = str(path)
    zip_files = sorted(output_dir.glob("*.zip"))
    preview = output_dir / "index.html"
    editable = zip_files[0] if zip_files else output_dir / "deck-editable.zip"
    if base_url:
        root = base_url.rstrip("/")
        artifacts["preview_url"] = f"{root}/decks/{task_id}/files/index.html"
        artifacts["edit_url"] = f"{root}/decks/{task_id}/files/{editable.name}"
        artifacts["download_url"] = artifacts["edit_url"]
    else:
        artifacts["preview_url"] = preview.resolve().as_uri() if preview.exists() else ""
        artifacts["edit_url"] = editable.resolve().as_uri() if editable.exists() else ""
        artifacts["download_url"] = artifacts["edit_url"]
    return artifacts


def assert_required_outputs(output_dir: Path) -> list[str]:
    missing = [name for name in REQUIRED_OUTPUTS if not (output_dir / name).exists()]
    if not list(output_dir.glob("*.zip")):
        missing.append("editable zip")
    return missing


def journey_event(stage: str, actor: str, summary: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "at": now_iso(),
        "stage": stage,
        "actor": actor,
        "summary": summary,
        "data": data or {},
    }


def append_journey_event(journey: dict[str, Any], stage: str, actor: str, summary: str, data: dict[str, Any] | None = None) -> None:
    journey.setdefault("events", []).append(journey_event(stage, actor, summary, data))


def task_version_summary(task: dict[str, Any], deck: dict[str, Any] | None = None) -> dict[str, Any]:
    meta = (deck or {}).get("deck", {}) if isinstance(deck, dict) else {}
    slides = (deck or {}).get("slides", []) if isinstance(deck, dict) else []
    return {
        "id": task.get("id", ""),
        "status": task.get("status", ""),
        "version": task.get("version", 0),
        "source": task.get("source", ""),
        "parent_task_id": task.get("parent_task_id", ""),
        "created_at": task.get("created_at", ""),
        "updated_at": task.get("updated_at", ""),
        "title": meta.get("title", ""),
        "slide_count": len(slides) if isinstance(slides, list) else 0,
        "output_dir": task.get("output_dir", ""),
    }


def upsert_journey_version(journey: dict[str, Any], task: dict[str, Any], deck: dict[str, Any] | None = None) -> None:
    versions = journey.setdefault("versions", [])
    item = task_version_summary(task, deck)
    for index, existing in enumerate(versions):
        if existing.get("id") == item["id"]:
            versions[index] = item
            return
    versions.append(item)


def new_journey(task: dict[str, Any], request: dict[str, Any], source: str) -> dict[str, Any]:
    brief = request.get("brief") if isinstance(request.get("brief"), dict) else {}
    deck_json = request.get("deck_json") if isinstance(request.get("deck_json"), dict) else {}
    title = (
        deck_json.get("deck", {}).get("title")
        if deck_json
        else brief_value(brief, "title", "brief", "customer_name", default="deck")
    )
    journey = {
        "schema": "lark-deck-journey/v1",
        "trace_id": base_task_id(str(task.get("id", ""))),
        "task_id": task.get("id", ""),
        "root_task_id": base_task_id(str(task.get("id", ""))),
        "title": title,
        "source": source,
        "created_at": task.get("created_at") or now_iso(),
        "updated_at": now_iso(),
        "versions": [],
        "events": [],
        "edit_sessions": [],
        "insights": {},
    }
    append_journey_event(
        journey,
        "request_received",
        "user",
        "收到生成请求,开始创建 deck 任务。",
        {
            "source": source,
            "brief_fields": sorted(brief.keys()),
            "has_outline": bool(request.get("outline")),
            "has_deck_json": bool(request.get("deck_json")),
        },
    )
    history = request.get("interaction_history")
    if isinstance(history, list):
        for item in history[-100:]:
            if not isinstance(item, dict):
                continue
            data = item.get("data") if isinstance(item.get("data"), dict) else {}
            append_journey_event(
                journey,
                str(item.get("stage") or "interaction"),
                str(item.get("actor") or "user"),
                str(item.get("summary") or "入口交互事件。")[:240],
                data,
            )
    return journey


def editable_text_leaf(key: str, value: str) -> bool:
    if not value.strip():
        return False
    if key in TEXT_LEAF_SKIP_KEYS:
        return False
    if re.match(r"^https?://", value):
        return False
    return True


def collect_text_leaf_map(node: Any, path: tuple[Any, ...] = ()) -> dict[tuple[Any, ...], str]:
    refs: dict[tuple[Any, ...], str] = {}
    if isinstance(node, list):
        for index, item in enumerate(node):
            next_path = (*path, index)
            if isinstance(item, str) and editable_text_leaf(str(index), item):
                refs[next_path] = item
            else:
                refs.update(collect_text_leaf_map(item, next_path))
    elif isinstance(node, dict):
        for key, value in node.items():
            next_path = (*path, key)
            if isinstance(value, str) and editable_text_leaf(str(key), value):
                refs[next_path] = value
            else:
                refs.update(collect_text_leaf_map(value, next_path))
    return refs


def slide_map(deck: dict[str, Any]) -> dict[str, dict[str, Any]]:
    slides = deck.get("slides") if isinstance(deck.get("slides"), list) else []
    return {str(slide.get("key")): slide for slide in slides if isinstance(slide, dict) and slide.get("key")}


def sanitize_client_events(events: Any, limit: int = 200) -> list[dict[str, Any]]:
    if not isinstance(events, list):
        return []
    safe_events: list[dict[str, Any]] = []
    allowed_detail_keys = {
        "field",
        "slide_key",
        "from",
        "to",
        "layout",
        "variant",
        "source",
        "count",
        "library_title",
        "action",
    }
    for event in events[-limit:]:
        if not isinstance(event, dict):
            continue
        detail = event.get("detail") if isinstance(event.get("detail"), dict) else {}
        safe_detail = {
            key: value
            for key, value in detail.items()
            if key in allowed_detail_keys and isinstance(value, (str, int, float, bool, type(None)))
        }
        safe_events.append(
            {
                "at": str(event.get("at") or "")[:40],
                "type": str(event.get("type") or "unknown")[:80],
                "active_key": str(event.get("active_key") or event.get("activeKey") or "")[:80],
                "detail": safe_detail,
            }
        )
    return safe_events


def summarize_deck_changes(before: dict[str, Any], after: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    before_meta = before.get("deck") if isinstance(before.get("deck"), dict) else {}
    after_meta = after.get("deck") if isinstance(after.get("deck"), dict) else {}
    meta_fields = sorted(set(before_meta) | set(after_meta))
    meta_changes = [
        {"field": key, "before_present": key in before_meta, "after_present": key in after_meta}
        for key in meta_fields
        if before_meta.get(key) != after_meta.get(key)
    ]

    before_slides = slide_map(before)
    after_slides = slide_map(after)
    before_order = list(before_slides.keys())
    after_order = list(after_slides.keys())
    common_before = [key for key in before_order if key in after_slides]
    common_after = [key for key in after_order if key in before_slides]
    added = [key for key in after_order if key not in before_slides]
    deleted = [key for key in before_order if key not in after_slides]

    layout_changes: list[dict[str, Any]] = []
    slide_text_changes: list[dict[str, Any]] = []
    changed_slide_keys: set[str] = set()
    changed_text_leaves = 0
    title_changes = 0
    for key in common_after:
        before_slide = before_slides[key]
        after_slide = after_slides[key]
        before_layout = (before_slide.get("layout"), before_slide.get("variant"))
        after_layout = (after_slide.get("layout"), after_slide.get("variant"))
        if before_layout != after_layout:
            layout_changes.append(
                {
                    "slide_key": key,
                    "from": "/".join(str(part) for part in before_layout if part),
                    "to": "/".join(str(part) for part in after_layout if part),
                }
            )
            changed_slide_keys.add(key)

        before_data = before_slide.get("data") if isinstance(before_slide.get("data"), dict) else {}
        after_data = after_slide.get("data") if isinstance(after_slide.get("data"), dict) else {}
        title_changed = before_data.get("title") != after_data.get("title")
        if title_changed:
            title_changes += 1
            changed_slide_keys.add(key)
        before_texts = collect_text_leaf_map(before_data)
        after_texts = collect_text_leaf_map(after_data)
        text_paths = set(before_texts) | set(after_texts)
        changed_here = sum(1 for path in text_paths if before_texts.get(path) != after_texts.get(path))
        if changed_here or title_changed:
            changed_text_leaves += changed_here
            changed_slide_keys.add(key)
            slide_text_changes.append(
                {
                    "slide_key": key,
                    "title_changed": title_changed,
                    "changed_text_leaves": changed_here,
                }
            )

    structured_payload = [key for key in ["updates", "slide_updates", "delete_slide_keys", "slide_order", "insert_slides"] if payload.get(key)]
    return {
        "meta_changes": meta_changes,
        "slides_added": added,
        "slides_deleted": deleted,
        "slides_reordered": common_before != common_after,
        "layout_changes": layout_changes,
        "slide_text_changes": slide_text_changes[:80],
        "structured_payload": structured_payload,
        "totals": {
            "meta_changes": len(meta_changes),
            "slides_added": len(added),
            "slides_deleted": len(deleted),
            "slides_reordered": 1 if common_before != common_after else 0,
            "layout_changes": len(layout_changes),
            "title_changes": title_changes,
            "changed_text_leaves": changed_text_leaves,
            "changed_slide_count": len(changed_slide_keys),
        },
    }


def derive_quality_insights(journey: dict[str, Any]) -> dict[str, Any]:
    sessions = journey.get("edit_sessions") if isinstance(journey.get("edit_sessions"), list) else []
    event_counts: Counter[str] = Counter()
    totals: Counter[str] = Counter()
    for session in sessions:
        for event in session.get("client_events") or []:
            event_counts[str(event.get("type") or "unknown")] += 1
        diff_totals = ((session.get("diff") or {}).get("totals") or {}) if isinstance(session, dict) else {}
        for key, value in diff_totals.items():
            if isinstance(value, (int, float)):
                totals[key] += int(value)

    recommendations: list[str] = []
    hints: list[str] = []
    if totals["meta_changes"] >= 1 or event_counts["global_edit"] >= 1:
        recommendations.append("生成前补齐标题、客户名、logo 和交付日期,减少首屏全局信息返工。")
        hints.append("brief intake should ask for deck title, customer slug/logo, and delivery date before rendering")
    if totals["slides_deleted"] >= 1:
        recommendations.append("首版页数或页面相关性偏宽,下一轮 recipe 应更严格筛掉弱页面。")
        hints.append("tighten outline relevance scoring and avoid low-evidence slides")
    if totals["slides_reordered"] >= 1 or event_counts["move_slide"] >= 1:
        recommendations.append("用户调整过叙事顺序,应把最终页序回写为该场景的推荐 pitch arc。")
        hints.append("learn final slide order as preferred narrative arc for similar briefs")
    if totals["slides_added"] >= 1 or event_counts["insert_library_slide"] >= 1:
        recommendations.append("首版遗漏了可复用素材,生成前应更早检索 Business Library。")
        hints.append("search reusable slide library before drafting DeckJSON")
    if totals["changed_text_leaves"] >= 6 or event_counts["text_edit"] >= 3:
        recommendations.append("用户做了较多文案精修,需要提升行业措辞、证据表达和页面密度匹配。")
        hints.append("adapt copy tone and content density from saved user edits")
    if totals["layout_changes"] >= 1:
        recommendations.append("用户调整过 layout/variant,说明 layout selector 需要吸收该场景偏好。")
        hints.append("update layout selection heuristics from final edited version")
    if not recommendations:
        recommendations.append("暂无明显精调压力;当前生成路径可作为同类 brief 的基线样本。")
        hints.append("baseline sample: no major user tuning detected")

    friction_score = min(
        100,
        len(sessions) * 12
        + totals["changed_text_leaves"] * 2
        + totals["slides_reordered"] * 8
        + totals["slides_added"] * 10
        + totals["slides_deleted"] * 10
        + totals["layout_changes"] * 8,
    )
    return {
        "schema": "lark-deck-quality-insights/v1",
        "trace_id": journey.get("trace_id", ""),
        "task_id": journey.get("task_id", ""),
        "version_count": len(journey.get("versions") or []),
        "edit_session_count": len(sessions),
        "friction_score": friction_score,
        "action_counts": dict(sorted(event_counts.items())),
        "change_totals": dict(sorted(totals.items())),
        "recommendations": recommendations,
        "next_generation_hints": hints,
    }


def render_journey_markdown(journey: dict[str, Any], insights: dict[str, Any]) -> str:
    versions = journey.get("versions") or []
    events = journey.get("events") or []
    sessions = journey.get("edit_sessions") or []
    version_lines = "\n".join(
        f"- v{item.get('version', 0)} · `{item.get('id', '')}` · {item.get('status', '')} · {item.get('slide_count', 0)} slides"
        for item in versions
    ) or "- 暂无版本记录。"
    event_lines = "\n".join(
        f"- {event.get('at', '')} · **{event.get('actor', '')}/{event.get('stage', '')}**: {event.get('summary', '')}"
        for event in events[-80:]
    ) or "- 暂无事件。"
    session_lines = []
    for session in sessions:
        diff_totals = ((session.get("diff") or {}).get("totals") or {}) if isinstance(session, dict) else {}
        session_lines.append(
            "- "
            f"{session.get('at', '')} · `{session.get('from_task_id', '')}` -> `{session.get('to_task_id', '')}` · "
            f"{len(session.get('client_events') or [])} client events · "
            f"{diff_totals.get('changed_slide_count', 0)} slides touched · "
            f"{diff_totals.get('changed_text_leaves', 0)} text leaves changed"
        )
    recommendation_lines = "\n".join(f"- {item}" for item in insights.get("recommendations") or [])
    action_counts = insights.get("action_counts") or {}
    action_lines = "\n".join(f"- `{key}`: {value}" for key, value in action_counts.items()) or "- 暂无编辑器动作。"
    change_totals = insights.get("change_totals") or {}
    change_lines = "\n".join(f"- `{key}`: {value}" for key, value in change_totals.items()) or "- 暂无版本 diff。"
    return f"""# 用户旅程 · {journey.get('title', 'deck')}

Trace: `{journey.get('trace_id', '')}`
当前任务: `{journey.get('task_id', '')}`
更新时间: {journey.get('updated_at', '')}

## 版本链路

{version_lines}

## 过程事件

{event_lines}

## 精调会话

{chr(10).join(session_lines) if session_lines else "- 暂无精调会话。"}

## 精调信号

Friction score: **{insights.get('friction_score', 0)} / 100**

### 编辑器动作

{action_lines}

### 版本差异

{change_lines}

## 对下一次生成的改进建议

{recommendation_lines}
"""


def write_journey_artifacts(output_dir: Path, journey: dict[str, Any]) -> dict[str, Any]:
    journey["updated_at"] = now_iso()
    insights = derive_quality_insights(journey)
    journey["insights"] = insights
    write_json(output_dir / "journey.json", journey)
    write_json(output_dir / "quality-insights.json", insights)
    (output_dir / "JOURNEY.md").write_text(render_journey_markdown(journey, insights), encoding="utf-8")
    return insights


def load_journey_for_task(task: dict[str, Any]) -> dict[str, Any] | None:
    output_dir = Path(task.get("output_dir", ""))
    path = output_dir / "journey.json"
    if not path.exists():
        return None
    try:
        return read_json(path)
    except Exception:
        return None


def append_learning_event(task: dict[str, Any], journey: dict[str, Any], insights: dict[str, Any]) -> None:
    learning_dir = RUNS_DIR / "_learning"
    learning_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "at": now_iso(),
        "trace_id": journey.get("trace_id", ""),
        "task_id": task.get("id", ""),
        "status": task.get("status", ""),
        "version": task.get("version", 0),
        "friction_score": insights.get("friction_score", 0),
        "recommendations": insights.get("recommendations", []),
        "next_generation_hints": insights.get("next_generation_hints", []),
    }
    with (learning_dir / "generation-learning.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def html_page(title: str, body: str) -> bytes:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{ color-scheme: light; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    body {{ margin: 0; background: #f6f8fb; color: #202733; }}
    main {{ max-width: 1040px; margin: 0 auto; padding: 32px 20px 56px; }}
    header {{ background: #eaf1ff; border-bottom: 1px solid #d8e2f3; }}
    header .inner {{ max-width: 1040px; margin: 0 auto; padding: 24px 20px; }}
    h1 {{ margin: 0; font-size: 28px; line-height: 1.25; color: #1457d9; }}
    h2 {{ margin: 28px 0 12px; font-size: 18px; }}
    a {{ color: #1457d9; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .panel {{ background: #fff; border: 1px solid #d9dee8; border-radius: 8px; padding: 18px; margin-top: 18px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }}
    .metric {{ background: #f8fafc; border: 1px solid #e1e6ef; border-radius: 8px; padding: 12px; }}
    .label {{ color: #657186; font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }}
    .value {{ margin-top: 6px; font-weight: 650; word-break: break-word; }}
    .badge {{ display: inline-flex; align-items: center; border-radius: 999px; padding: 4px 10px; font-size: 13px; font-weight: 650; }}
    .succeeded {{ background: #e9f8ef; color: #137333; }}
    .failed {{ background: #fdeaea; color: #b42318; }}
    .running {{ background: #fff6db; color: #8a5a00; }}
    pre {{ white-space: pre-wrap; overflow-wrap: anywhere; background: #0f172a; color: #e5e7eb; border-radius: 8px; padding: 14px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    th, td {{ border-bottom: 1px solid #e1e6ef; padding: 10px 8px; text-align: left; vertical-align: top; }}
    textarea {{ width: 100%; min-height: 160px; box-sizing: border-box; border: 1px solid #cfd7e6; border-radius: 8px; padding: 12px; font: 13px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace; resize: vertical; }}
    input, select {{ width: 100%; box-sizing: border-box; border: 1px solid #cfd7e6; border-radius: 8px; padding: 10px; font: inherit; background: #fff; }}
    button {{ border: 0; border-radius: 8px; padding: 10px 14px; background: #1457d9; color: white; font-weight: 650; cursor: pointer; }}
    button.secondary {{ background: #e8edf6; color: #202733; }}
    button.danger {{ background: #b42318; }}
    button.ghost {{ background: transparent; color: #1457d9; border: 1px solid #c7d4ee; }}
    .actions {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 14px; }}
    .muted {{ color: #657186; }}
    .toolbar {{ position: sticky; top: 0; z-index: 2; display: flex; justify-content: space-between; gap: 16px; align-items: center; background: rgba(246,248,251,.96); border-bottom: 1px solid #d9dee8; padding: 12px 0; margin-bottom: 12px; }}
    .editor-layout {{ display: grid; grid-template-columns: 300px 1fr; gap: 16px; align-items: start; }}
    .sidebar {{ position: sticky; top: 64px; }}
    .slide-list {{ display: grid; gap: 8px; margin: 0; padding: 0; list-style: none; }}
    .slide-tab {{ display: grid; grid-template-columns: 1fr auto; gap: 8px; align-items: center; padding: 10px; border: 1px solid #d9dee8; border-radius: 8px; background: #fff; cursor: pointer; }}
    .slide-tab.active {{ border-color: #1457d9; box-shadow: 0 0 0 2px rgba(20,87,217,.12); }}
    .slide-card {{ display: grid; gap: 12px; border: 1px solid #d9dee8; border-radius: 8px; background: #fff; padding: 14px; margin-bottom: 12px; }}
    .slide-card[hidden] {{ display: none; }}
    .slide-head {{ display: grid; grid-template-columns: 1fr auto; gap: 12px; align-items: center; }}
    .row {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }}
    .json-panel textarea {{ min-height: 360px; }}
    .toast {{ display: none; margin-top: 12px; }}
    .toast.show {{ display: block; }}
    @media (max-width: 860px) {{
      .editor-layout {{ grid-template-columns: 1fr; }}
      .sidebar, .toolbar {{ position: static; }}
      .row {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <header><div class="inner"><h1>{html.escape(title)}</h1></div></header>
  <main>{body}</main>
</body>
</html>
""".encode("utf-8")


def artifact_links(task: dict[str, Any]) -> str:
    artifacts = task.get("artifacts") or {}
    rows = []
    for label, key in [
        ("预览", "preview_url"),
        ("编辑包", "edit_url"),
        ("下载包", "download_url"),
        ("Validator 报告", "validator-report.md"),
        ("用户旅程", "JOURNEY.md"),
        ("质量洞察", "quality-insights.json"),
    ]:
        value = artifacts.get(key)
        if value:
            rows.append(f'<li><a href="{html.escape(value)}">{html.escape(label)}</a></li>')
    return "<ul>" + "".join(rows) + "</ul>" if rows else '<p class="muted">暂无产物链接。</p>'


def safe_json_for_script(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


def slide_title(slide: dict[str, Any]) -> str:
    data = slide.get("data") if isinstance(slide.get("data"), dict) else {}
    for key in ["title", "slogan", "quote", "lede"]:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return str(slide.get("key") or slide.get("layout") or "slide")


def slide_library_items(limit: int = 36) -> list[dict[str, Any]]:
    return slide_library.search_slides(limit=limit)


def task_versions(task_id: str) -> list[dict[str, Any]]:
    base = base_task_id(task_id)
    candidates = [RUNS_DIR / base, *sorted(RUNS_DIR.glob(f"{base}-v[0-9][0-9][0-9]"))]
    versions: list[dict[str, Any]] = []
    for path in candidates:
        task_path = path / "task.json"
        if not task_path.exists():
            continue
        try:
            task = read_json(task_path)
        except Exception:
            continue
        versions.append(
            {
                "id": task.get("id", path.name),
                "status": task.get("status", ""),
                "version": task.get("version", 0),
                "updated_at": task.get("updated_at", ""),
                "preview_url": (task.get("artifacts") or {}).get("preview_url", ""),
            }
        )
    return versions


def log_tail(task: dict[str, Any], max_chars: int = 12000) -> str:
    logs = task.get("logs") or {}
    preferred = ["check_only", "render", "outline_validator", "package"]
    for key in preferred:
        path = logs.get(key)
        if path and Path(path).exists():
            text = Path(path).read_text(encoding="utf-8", errors="replace")
            return text[-max_chars:]
    return ""


def render_status_page(task_id: str) -> bytes:
    task = load_task(task_id)
    status = html.escape(str(task.get("status") or "unknown"))
    badge_class = status if status in {"succeeded", "failed", "running"} else "running"
    logs = task.get("logs") or {}
    log_rows = "".join(
        f"<li><code>{html.escape(name)}</code>: {html.escape(str(path))}</li>"
        for name, path in sorted(logs.items())
    )
    error = task.get("error")
    output_dir = Path(task.get("output_dir", ""))
    report_text = ""
    report = output_dir / "validator-report.md"
    if report.exists():
        report_text = html.escape(report.read_text(encoding="utf-8")[:12000])
    versions = task_versions(task_id)
    version_rows = []
    for item in versions:
        preview = str(item.get("preview_url", ""))
        preview_link = f'<a href="{html.escape(preview)}">预览</a>' if preview else ""
        version_rows.append(
            "<tr>"
            f"<td><a href=\"/decks/{html.escape(str(item['id']))}/status\"><code>{html.escape(str(item['id']))}</code></a></td>"
            f"<td>{html.escape(str(item.get('version') or 'base'))}</td>"
            f"<td>{html.escape(str(item.get('status', '')))}</td>"
            f"<td>{html.escape(str(item.get('updated_at', '')))}</td>"
            f"<td>{preview_link}</td>"
            "</tr>"
        )
    version_rows_html = "".join(version_rows)
    insights_path = output_dir / "quality-insights.json"
    journey_summary = ""
    if insights_path.exists():
        try:
            insights = read_json(insights_path)
            recommendation_rows = "".join(
                f"<li>{html.escape(str(item))}</li>"
                for item in (insights.get("recommendations") or [])[:5]
            )
            action_counts = insights.get("action_counts") or {}
            action_rows = "".join(
                f"<tr><td><code>{html.escape(str(key))}</code></td><td>{html.escape(str(value))}</td></tr>"
                for key, value in sorted(action_counts.items())
            )
            journey_summary = f"""
<section class="panel">
  <h2>用户旅程</h2>
  <div class="grid">
    <div class="metric"><div class="label">Friction</div><div class="value">{html.escape(str(insights.get("friction_score", 0)))} / 100</div></div>
    <div class="metric"><div class="label">Edit sessions</div><div class="value">{html.escape(str(insights.get("edit_session_count", 0)))}</div></div>
    <div class="metric"><div class="label">Versions</div><div class="value">{html.escape(str(insights.get("version_count", len(versions))))}</div></div>
  </div>
  <h2>精调信号</h2>
  {f'<table><thead><tr><th>动作</th><th>次数</th></tr></thead><tbody>{action_rows}</tbody></table>' if action_rows else '<p class="muted">暂无编辑器动作。</p>'}
  <h2>改进建议</h2>
  {f'<ul>{recommendation_rows}</ul>' if recommendation_rows else '<p class="muted">暂无建议。</p>'}
  <div class="actions">
    <a href="/decks/{html.escape(task_id)}/journey"><button class="secondary" type="button">查看完整旅程</button></a>
    <a href="/decks/{html.escape(task_id)}/insights"><button class="secondary" type="button">查看质量洞察 JSON</button></a>
  </div>
</section>
"""
        except Exception:
            journey_summary = ""
    failure_log = html.escape(log_tail(task)) if error else ""
    body = f"""
<section class="panel">
  <div class="grid">
    <div class="metric"><div class="label">Task</div><div class="value"><code>{html.escape(task_id)}</code></div></div>
    <div class="metric"><div class="label">Status</div><div class="value"><span class="badge {badge_class}">{status}</span></div></div>
    <div class="metric"><div class="label">Source</div><div class="value">{html.escape(str(task.get("source", "")))}</div></div>
    <div class="metric"><div class="label">Updated</div><div class="value">{html.escape(str(task.get("updated_at", "")))}</div></div>
  </div>
  {f'<h2>失败原因</h2><pre>{html.escape(str(error))}</pre>' if error else ''}
</section>
<section class="panel">
  <h2>产物</h2>
  {artifact_links(task)}
  <div class="actions">
    <a href="/decks/{html.escape(task_id)}/edit"><button>打开轻量编辑</button></a>
    <a href="/decks/{html.escape(task_id)}"><button class="secondary">查看 JSON 状态</button></a>
  </div>
</section>
<section class="panel">
  <h2>版本</h2>
  {f'<table><thead><tr><th>任务</th><th>版本</th><th>状态</th><th>更新时间</th><th>预览</th></tr></thead><tbody>{version_rows_html}</tbody></table>' if version_rows_html else '<p class="muted">暂无版本记录。</p>'}
</section>
{journey_summary}
<section class="panel">
  <h2>日志</h2>
  {"<ul>" + log_rows + "</ul>" if log_rows else '<p class="muted">暂无日志。</p>'}
</section>
{f'<section class="panel"><h2>Validator 报告</h2><pre>{report_text}</pre></section>' if report_text else ''}
{f'<section class="panel"><h2>失败日志</h2><pre>{failure_log}</pre></section>' if failure_log else ''}
"""
    return html_page(f"Deck Task · {task_id}", body)


def render_edit_page(task_id: str) -> bytes:
    task = load_task(task_id)
    deck_path = Path(task["output_dir"]) / "deck.json"
    if not deck_path.exists():
        raise FileNotFoundError("deck.json")
    deck = read_json(deck_path)
    preview_url = (task.get("artifacts") or {}).get("preview_url", "")
    deck_payload = safe_json_for_script(deck)
    library_payload = safe_json_for_script(slide_library_items())
    task_id_js = safe_json_for_script(task_id)
    title = html.escape(str(deck.get("deck", {}).get("title", "")))
    customer_slug = html.escape(str(deck.get("deck", {}).get("customer_slug", "")))
    logo_value = html.escape(str(((deck.get("assets") or {}).get("logos") or {}).get("customer", "")))
    body = f"""
<div class="toolbar">
  <div>
    <strong>轻量编辑</strong>
    <div class="muted">保存会生成新版本，不覆盖当前任务。</div>
  </div>
  <div class="actions">
    <button onclick="saveDeck()">保存并生成新版本</button>
    <a href="/decks/{html.escape(task_id)}/status"><button class="secondary" type="button">状态页</button></a>
    {f'<a href="{html.escape(preview_url)}"><button class="secondary" type="button">预览当前版</button></a>' if preview_url else ''}
  </div>
</div>

<section class="panel">
  <h2>全局信息</h2>
  <div class="row">
    <label>
      <span class="label">Deck 标题</span>
      <input id="deck-title" value="{title}">
    </label>
    <label>
      <span class="label">客户名 / 文件标识</span>
      <input id="customer-name" value="{customer_slug}">
    </label>
  </div>
  <label>
    <span class="label">客户 logo 路径或 URL</span>
    <input id="customer-logo" value="{logo_value}" placeholder="例如 https://.../logo.png 或 shared/clientlogo/customer.png">
  </label>
</section>

<div class="editor-layout">
  <aside class="sidebar">
    <section class="panel">
      <h2>页面</h2>
      <ul id="slide-list" class="slide-list"></ul>
    </section>
    <section class="panel">
      <h2>素材库</h2>
      <input id="library-query" placeholder="按行业、产品、价值主张搜索" oninput="renderLibrary()">
      <select id="library-layout" onchange="renderLibrary()">
        <option value="">全部 layout</option>
        <option value="content">content</option>
        <option value="flow">flow</option>
        <option value="stats">stats</option>
        <option value="arch-stack">arch-stack</option>
      </select>
      <select id="library-select" onchange="renderLibraryPreview()"></select>
      <div id="library-preview" class="muted"></div>
      <div class="actions">
        <button class="secondary" onclick="insertLibrarySlide()">插入已有 slide</button>
      </div>
      <p class="muted">当前读取本地 Business Library；后续可替换为飞书 Base 检索。</p>
    </section>
  </aside>
  <section id="slide-editor"></section>
</div>

<section class="panel json-panel">
  <details>
    <summary>高级 DeckJSON</summary>
    <p class="muted">用于排查或批量编辑；保存前会以这里的 JSON 为准。</p>
    <div class="actions">
      <button class="secondary" onclick="refreshJson()">从表单同步到 JSON</button>
      <button class="secondary" onclick="loadJson()">从 JSON 载入表单</button>
    </div>
    <textarea id="deck-json"></textarea>
  </details>
</section>

<pre id="result" class="toast"></pre>

<script type="application/json" id="deck-source">{deck_payload}</script>
<script type="application/json" id="library-source">{library_payload}</script>
<script>
let deck = JSON.parse(document.getElementById('deck-source').textContent);
const library = JSON.parse(document.getElementById('library-source').textContent);
let activeKey = (deck.slides && deck.slides[0] && deck.slides[0].key) || '';
let editEvents = [];
let formEditTimer = null;

function recordEditEvent(type, detail = {{}}) {{
  editEvents.push({{
    at: new Date().toISOString(),
    type,
    active_key: activeKey,
    detail
  }});
  if (editEvents.length > 200) editEvents.shift();
}}

function closestSlideKey(el) {{
  const card = el && el.closest ? el.closest('.slide-card') : null;
  return (card && card.dataset.key) || activeKey || '';
}}

function esc(value) {{
  return String(value ?? '').replace(/[&<>"']/g, ch => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[ch]));
}}

function slugify(value) {{
  const raw = String(value || '').trim().toLowerCase();
  const ascii = raw.replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  if (ascii && /^[a-z]/.test(ascii)) return ascii.slice(0, 48);
  let hash = 0;
  for (let i = 0; i < raw.length; i += 1) hash = ((hash << 5) - hash + raw.charCodeAt(i)) >>> 0;
  return 'customer-' + hash.toString(16).slice(0, 8);
}}

function getAt(obj, path) {{
  return path.reduce((node, key) => node && node[key], obj);
}}

function setAt(obj, path, value) {{
  let node = obj;
  for (let i = 0; i < path.length - 1; i += 1) node = node[path[i]];
  node[path[path.length - 1]] = value;
}}

function editableTextLeaf(key, value) {{
  if (typeof value !== 'string' || !value.trim()) return false;
  if (key === 'title' || key === 'icon' || key === 'img' || key === 'image' || key === 'src' || key === 'url' || key === 'href' || key === 'company_logo') return false;
  if (/^https?:\\/\\//.test(value)) return false;
  return true;
}}

function collectTextRefs(node, path = []) {{
  const refs = [];
  if (!node || typeof node !== 'object') return refs;
  if (Array.isArray(node)) {{
    node.forEach((item, index) => {{
      if (typeof item === 'string' && editableTextLeaf(String(index), item)) refs.push({{ path: [...path, index], text: item }});
      else refs.push(...collectTextRefs(item, [...path, index]));
    }});
    return refs;
  }}
  Object.entries(node).forEach(([key, value]) => {{
    if (typeof value === 'string' && editableTextLeaf(key, value)) refs.push({{ path: [...path, key], text: value }});
    else refs.push(...collectTextRefs(value, [...path, key]));
  }});
  return refs;
}}

function slideLabel(slide, index) {{
  const data = slide.data || {{}};
  return data.title || data.slogan || data.quote || slide.key || ('slide-' + (index + 1));
}}

function syncGlobal() {{
  deck.deck = deck.deck || {{}};
  deck.deck.title = document.getElementById('deck-title').value.trim() || deck.deck.title || 'Untitled deck';
  deck.deck.customer_slug = slugify(document.getElementById('customer-name').value || deck.deck.customer_slug || deck.deck.title);
  const logo = document.getElementById('customer-logo').value.trim();
  if (logo) {{
    deck.assets = deck.assets || {{}};
    deck.assets.logos = deck.assets.logos || {{}};
    deck.assets.logos.customer = logo;
  }}
  const cover = (deck.slides || []).find(s => s.layout === 'cover');
  if (cover) {{
    cover.data = cover.data || {{}};
    cover.data.title = deck.deck.title;
  }}
}}

function syncSlides() {{
  document.querySelectorAll('.slide-card').forEach(card => {{
    const slide = (deck.slides || []).find(item => item.key === card.dataset.key);
    if (!slide) return;
    slide.data = slide.data || {{}};
    const title = card.querySelector('.slide-title').value.trim();
    if (title) slide.data.title = title;
    const refs = JSON.parse(card.dataset.refs || '[]');
    const lines = card.querySelector('.slide-body').value.split('\\n');
    refs.forEach((ref, index) => {{
      if (index < lines.length) setAt(slide.data, ref.path, lines[index].trim());
    }});
  }});
}}

function syncFromForm() {{
  syncGlobal();
  syncSlides();
}}

function renderLibrary() {{
  const select = document.getElementById('library-select');
  const query = document.getElementById('library-query').value.trim().toLowerCase();
  const layout = document.getElementById('library-layout').value;
  const rows = library
    .map((item, index) => ({{...item, index}}))
    .filter(item => !layout || item.layout === layout)
    .filter(item => {{
      if (!query) return true;
      return JSON.stringify(item).toLowerCase().includes(query);
    }});
  select.innerHTML = rows.map(item => (
    `<option value="${{item.index}}">${{esc(item.title)}} · ${{esc(item.layout)}}${{item.variant ? '/' + esc(item.variant) : ''}}</option>`
  )).join('');
  if (!select.innerHTML) select.innerHTML = '<option value="">无匹配素材</option>';
  renderLibraryPreview();
}}

function renderLibraryPreview() {{
  const select = document.getElementById('library-select');
  const item = library[Number(select.value)];
  const root = document.getElementById('library-preview');
  if (!item) {{
    root.textContent = '没有匹配的可插入 slide。';
    return;
  }}
  root.innerHTML = `
    <p>${{esc(item.insert_suggestion || '')}}</p>
    ${{item.thumbnail ? `<img src="/${{esc(item.thumbnail)}}" alt="" style="width:100%;max-height:120px;object-fit:cover;border:1px solid #d9dee8;border-radius:8px">` : ''}}
  `;
}}

function renderSlideList() {{
  const list = document.getElementById('slide-list');
  list.innerHTML = (deck.slides || []).map((slide, index) => `
    <li class="slide-tab ${{slide.key === activeKey ? 'active' : ''}}" onclick="setActive('${{esc(slide.key)}}')">
      <span>${{index + 1}}. ${{esc(slideLabel(slide, index))}}</span>
      <code>${{esc(slide.layout)}}${{slide.variant ? '/' + esc(slide.variant) : ''}}</code>
    </li>
  `).join('');
}}

function renderSlides() {{
  const root = document.getElementById('slide-editor');
  root.innerHTML = (deck.slides || []).map((slide, index) => {{
    const refs = collectTextRefs(slide.data || {{}});
    const body = refs.map(ref => ref.text).join('\\n');
    return `
      <article class="slide-card" data-key="${{esc(slide.key)}}" data-refs="${{esc(JSON.stringify(refs))}}" ${{slide.key === activeKey ? '' : 'hidden'}}>
        <div class="slide-head">
          <div>
            <div class="label">页面 ${{index + 1}} · <code>${{esc(slide.key)}}</code> · ${{esc(slide.layout)}}${{slide.variant ? '/' + esc(slide.variant) : ''}}</div>
            <strong>${{esc(slideLabel(slide, index))}}</strong>
          </div>
          <div class="actions">
            <button class="ghost" onclick="moveSlide('${{esc(slide.key)}}', -1)">上移</button>
            <button class="ghost" onclick="moveSlide('${{esc(slide.key)}}', 1)">下移</button>
            <button class="ghost" onclick="markReusable('${{esc(slide.key)}}')">标记复用</button>
            <button class="danger" onclick="deleteSlide('${{esc(slide.key)}}')">删除</button>
          </div>
        </div>
        <label>
          <span class="label">页面标题</span>
          <input class="slide-title" value="${{esc((slide.data || {{}}).title || '')}}">
        </label>
        <label>
          <span class="label">正文</span>
          <textarea class="slide-body" placeholder="当前页面没有可直接编辑的正文文本。">${{esc(body)}}</textarea>
        </label>
      </article>
    `;
  }}).join('');
}}

function render() {{
  document.getElementById('deck-title').value = (deck.deck && deck.deck.title) || '';
  document.getElementById('customer-name').value = (deck.deck && deck.deck.customer_slug) || '';
  document.getElementById('customer-logo').value = (((deck.assets || {{}}).logos || {{}}).customer) || '';
  renderLibrary();
  renderSlideList();
  renderSlides();
  refreshJson();
}}

function setActive(key) {{
  syncFromForm();
  recordEditEvent('select_slide', {{slide_key: key}});
  activeKey = key;
  renderSlideList();
  renderSlides();
}}

function moveSlide(key, delta) {{
  syncFromForm();
  const slides = deck.slides || [];
  const index = slides.findIndex(slide => slide.key === key);
  const next = index + delta;
  if (index < 0 || next < 0 || next >= slides.length) return;
  const [item] = slides.splice(index, 1);
  slides.splice(next, 0, item);
  recordEditEvent('move_slide', {{slide_key: key, from: index + 1, to: next + 1}});
  activeKey = key;
  render();
}}

function deleteSlide(key) {{
  syncFromForm();
  if ((deck.slides || []).length <= 1) {{
    alert('至少保留一页。');
    return;
  }}
  deck.slides = deck.slides.filter(slide => slide.key !== key);
  recordEditEvent('delete_slide', {{slide_key: key}});
  activeKey = (deck.slides[0] && deck.slides[0].key) || '';
  render();
}}

function uniqueKey(base) {{
  const existing = new Set((deck.slides || []).map(slide => slide.key));
  let key = slugify(base || 'library-slide');
  let i = 1;
  while (existing.has(key)) {{
    i += 1;
    key = slugify(base || 'library-slide') + '-' + i;
  }}
  return key;
}}

function insertLibrarySlide() {{
  syncFromForm();
  const selected = document.getElementById('library-select').value;
  if (selected === '') return;
  const item = library[Number(selected)];
  if (!item) return;
  const slide = JSON.parse(JSON.stringify(item.slide));
  slide.key = uniqueKey(slide.key);
  const slides = deck.slides || (deck.slides = []);
  const activeIndex = slides.findIndex(existing => existing.key === activeKey);
  slides.splice(activeIndex >= 0 ? activeIndex + 1 : slides.length, 0, slide);
  recordEditEvent('insert_library_slide', {{
    slide_key: slide.key,
    layout: slide.layout || '',
    variant: slide.variant || '',
    library_title: item.title || ''
  }});
  activeKey = slide.key;
  render();
}}

async function markReusable(key) {{
  syncFromForm();
  const slide = (deck.slides || []).find(item => item.key === key);
  if (!slide) return;
  recordEditEvent('mark_reusable', {{slide_key: key}});
  const result = document.getElementById('result');
  result.classList.add('show');
  result.textContent = 'Marking...';
  const response = await fetch('/library/candidates', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{
      task_id: {task_id_js},
      slide_key: key,
      title: slideLabel(slide, (deck.slides || []).findIndex(item => item.key === key)),
      industry: ['待标注'],
      product: ['待标注'],
      customer_stage: ['待标注'],
      deck_type: ['待标注'],
      value_prop: [slideLabel(slide, 0)],
      tag: ['值得复用', '待审核']
    }})
  }});
  const body = await response.json();
  result.textContent = JSON.stringify(body, null, 2);
  if (!response.ok) alert('候选入库失败,请看页面底部结果。');
}}

function refreshJson() {{
  syncGlobal();
  document.getElementById('deck-json').value = JSON.stringify(deck, null, 2);
}}

function loadJson() {{
  deck = JSON.parse(document.getElementById('deck-json').value);
  recordEditEvent('load_json', {{source: 'advanced-json'}});
  activeKey = (deck.slides && deck.slides[0] && deck.slides[0].key) || '';
  render();
}}

async function saveDeck() {{
  syncFromForm();
  refreshJson();
  recordEditEvent('save', {{count: editEvents.length + 1}});
  const result = document.getElementById('result');
  result.classList.add('show');
  result.textContent = 'Saving...';
  const response = await fetch('/decks/' + {task_id_js} + '/edits', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{deck_json: deck, client_events: editEvents}})
  }});
  const body = await response.json();
  result.textContent = JSON.stringify(body, null, 2);
  if (body.id) {{
    const a = document.createElement('a');
    a.href = '/decks/' + body.id + '/status';
    a.textContent = '打开新版本状态页';
    result.after(a);
  }}
}}

document.addEventListener('input', event => {{
  const target = event.target;
  if (!target || !target.id && !target.classList) return;
  let field = '';
  if (target.id === 'deck-title' || target.id === 'customer-name' || target.id === 'customer-logo') field = target.id;
  if (target.classList && target.classList.contains('slide-title')) field = 'slide-title';
  if (target.classList && target.classList.contains('slide-body')) field = 'slide-body';
  if (!field) return;
  clearTimeout(formEditTimer);
  formEditTimer = setTimeout(() => {{
    recordEditEvent(field === 'slide-body' ? 'text_edit' : 'global_edit', {{
      field,
      slide_key: closestSlideKey(target)
    }});
  }}, 700);
}}, true);

render();
</script>
"""
    return html_page(f"Edit Deck · {task_id}", body)


def render_journey_page(task_id: str) -> bytes:
    task = load_task(task_id)
    output_dir = Path(task.get("output_dir", ""))
    journey_path = output_dir / "JOURNEY.md"
    insights_path = output_dir / "quality-insights.json"
    if not journey_path.exists():
        raise FileNotFoundError("JOURNEY.md")
    journey_text = html.escape(journey_path.read_text(encoding="utf-8"))
    insights_text = ""
    if insights_path.exists():
        insights_text = html.escape(json.dumps(read_json(insights_path), ensure_ascii=False, indent=2))
    body = f"""
<section class="panel">
  <div class="actions">
    <a href="/decks/{html.escape(task_id)}/status"><button class="secondary" type="button">返回状态页</button></a>
    <a href="/decks/{html.escape(task_id)}/edit"><button type="button">继续轻量编辑</button></a>
  </div>
</section>
<section class="panel">
  <h2>用户旅程</h2>
  <pre>{journey_text}</pre>
</section>
{f'<section class="panel"><h2>质量洞察 JSON</h2><pre>{insights_text}</pre></section>' if insights_text else ''}
"""
    return html_page(f"Journey · {task_id}", body)


def task_paths(task_id: str) -> tuple[Path, Path, Path, Path]:
    task_dir = RUNS_DIR / task_id
    input_dir = task_dir / "input"
    output_dir = task_dir / "output"
    log_dir = task_dir / "logs"
    return task_dir, input_dir, output_dir, log_dir


def save_task(task_dir: Path, task: dict[str, Any]) -> None:
    task["updated_at"] = now_iso()
    write_json(task_dir / "task.json", task)


def load_task(task_id: str) -> dict[str, Any]:
    task_path = RUNS_DIR / task_id / "task.json"
    if not task_path.exists():
        raise FileNotFoundError(task_id)
    return read_json(task_path)


def deep_merge(target: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            deep_merge(target[key], value)
        else:
            target[key] = value
    return target


def apply_edit_payload(deck: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("deck_json"):
        edited = copy.deepcopy(payload["deck_json"])
    else:
        edited = copy.deepcopy(deck)

    updates = payload.get("updates") or {}
    if not isinstance(updates, dict):
        raise ValueError("updates must be an object")
    meta = edited.setdefault("deck", {})
    for key in ["title", "author", "date", "presentation_date", "customer_slug", "language", "mode", "title_style", "logo_position"]:
        if key in updates:
            meta[key] = updates[key]
    if "logo" in updates:
        edited.setdefault("assets", {}).setdefault("logos", {})["customer"] = updates["logo"]

    slides = edited.setdefault("slides", [])
    delete_keys = set(normalize_list(payload.get("delete_slide_keys")))
    if delete_keys:
        slides[:] = [slide for slide in slides if slide.get("key") not in delete_keys]

    slide_by_key = {slide.get("key"): slide for slide in slides if slide.get("key")}
    for patch in payload.get("slide_updates") or []:
        if not isinstance(patch, dict) or not patch.get("key"):
            raise ValueError("each slide update must include key")
        slide = slide_by_key.get(patch["key"])
        if not slide:
            raise ValueError(f"slide not found: {patch['key']}")
        deep_merge(slide, {k: v for k, v in patch.items() if k != "key"})

    insert_slides = payload.get("insert_slides") or []
    if not isinstance(insert_slides, list):
        raise ValueError("insert_slides must be an array")
    existing = {slide.get("key") for slide in slides}
    for slide in insert_slides:
        if not isinstance(slide, dict) or not slide.get("key"):
            raise ValueError("each inserted slide must include key")
        if slide["key"] in existing:
            raise ValueError(f"duplicate inserted slide key: {slide['key']}")
        slides.append(copy.deepcopy(slide))
        existing.add(slide["key"])

    order = normalize_list(payload.get("slide_order"))
    if order:
        by_key = {slide.get("key"): slide for slide in slides if slide.get("key")}
        missing = [key for key in order if key not in by_key]
        if missing:
            raise ValueError("slide_order references missing keys: " + ", ".join(missing))
        ordered = [by_key[key] for key in order]
        ordered_keys = set(order)
        ordered.extend(slide for slide in slides if slide.get("key") not in ordered_keys)
        edited["slides"] = ordered

    return edited


def base_task_id(task_id: str) -> str:
    return re.sub(r"-v\d{3}$", "", task_id)


def next_version_id(task_id: str) -> tuple[str, int]:
    base = base_task_id(task_id)
    max_version = 0
    for path in RUNS_DIR.glob(f"{base}-v[0-9][0-9][0-9]"):
        match = re.search(r"-v(\d{3})$", path.name)
        if match:
            max_version = max(max_version, int(match.group(1)))
    version = max_version + 1
    return f"{base}-v{version:03d}", version


def update_edit_journey(
    parent_task: dict[str, Any],
    new_task: dict[str, Any],
    payload: dict[str, Any],
    before_deck: dict[str, Any],
    after_deck: dict[str, Any],
    diff: dict[str, Any],
    client_events: list[dict[str, Any]],
) -> None:
    parent_journey = load_journey_for_task(parent_task)
    if parent_journey:
        journey = copy.deepcopy(parent_journey)
    else:
        journey = new_journey(parent_task, {"deck_json": before_deck}, str(parent_task.get("source") or "unknown"))
        upsert_journey_version(journey, parent_task, before_deck)

    journey["task_id"] = new_task.get("id", "")
    journey["title"] = (after_deck.get("deck") or {}).get("title") or journey.get("title", "")
    journey["source"] = "edit"
    session = {
        "at": now_iso(),
        "from_task_id": parent_task.get("id", ""),
        "to_task_id": new_task.get("id", ""),
        "version": new_task.get("version", 0),
        "status": new_task.get("status", ""),
        "client_events": client_events,
        "diff": diff,
        "payload_shape": sorted(key for key, value in payload.items() if key != "deck_json" and value not in (None, "", [], {})),
    }
    journey.setdefault("edit_sessions", []).append(session)
    append_journey_event(
        journey,
        "edit_received",
        "user",
        "用户保存了一轮精调,系统创建新版本并重新渲染。",
        {
            "from_task_id": parent_task.get("id", ""),
            "to_task_id": new_task.get("id", ""),
            "client_event_count": len(client_events),
            "changed_slide_count": (diff.get("totals") or {}).get("changed_slide_count", 0),
        },
    )
    append_journey_event(
        journey,
        "edit_analyzed",
        "system",
        "已分析版本差异和编辑器动作,生成下一轮质量改进信号。",
        {"diff_totals": diff.get("totals", {})},
    )
    if new_task.get("status") == "succeeded":
        append_journey_event(journey, "edited_result_ready", "system", "精调后的新版本已可预览、编辑和下载。")
    else:
        append_journey_event(journey, "edited_result_failed", "system", "精调后的新版本生成失败。", {"error": new_task.get("error")})

    upsert_journey_version(journey, parent_task, before_deck)
    upsert_journey_version(journey, new_task, after_deck)
    insights = write_journey_artifacts(Path(new_task["output_dir"]), journey)
    append_learning_event(new_task, journey, insights)


def edit_task(task_id: str, payload: dict[str, Any], *, base_url: str | None = None) -> dict[str, Any]:
    task = load_task(task_id)
    task_dir = RUNS_DIR / task_id
    deck_path = Path(task["output_dir"]) / "deck.json"
    if not deck_path.exists():
        raise FileNotFoundError(f"deck.json not found for task: {task_id}")

    source_deck = read_json(deck_path)
    edited_deck = apply_edit_payload(source_deck, payload)
    diff = summarize_deck_changes(source_deck, edited_deck, payload)
    client_events = sanitize_client_events(payload.get("client_events"))
    request_path = task_dir / "input" / "request.json"
    original_request = read_json(request_path) if request_path.exists() else {}
    outline_path = task_dir / "input" / "outline.json"
    if outline_path.exists():
        outline = read_json(outline_path)
    else:
        outline = original_request.get("outline") or brief_to_outline(original_request.get("brief") or {})

    new_task_id, version = next_version_id(task_id)
    new_request = {
        "brief": original_request.get("brief", {}),
        "outline": outline,
        "deck_json": edited_deck,
    }
    new_task = create_or_run_task(
        new_request,
        task_id=new_task_id,
        base_url=base_url,
        metadata={"parent_task_id": task_id, "version": version, "edit_source": "deck_json"},
    )
    new_task_dir = RUNS_DIR / new_task_id
    write_json(new_task_dir / "input" / "edit.json", payload)
    new_task["parent_task_id"] = task_id
    new_task["version"] = version
    new_task["edit_source"] = "deck_json"
    update_edit_journey(task, new_task, payload, source_deck, edited_deck, diff, client_events)
    save_task(new_task_dir, new_task)
    return new_task


def create_or_run_task(
    request: dict[str, Any],
    *,
    task_id: str | None = None,
    base_url: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    brief = request.get("brief") or {}
    if not isinstance(brief, dict):
        raise ValueError("request.brief must be an object when provided")

    source = "deck_json" if request.get("deck_json") else "outline" if request.get("outline") else "brief"
    title_source = (
        (request.get("deck_json") or {}).get("deck", {}).get("title")
        if isinstance(request.get("deck_json"), dict)
        else brief_value(brief, "customer_name", "title", "brief", default="deck")
    )
    task_id = task_id or unique_generated_task_id(str(title_source))
    task_dir, input_dir, output_dir, log_dir = task_paths(task_id)
    if task_dir.exists():
        shutil.rmtree(task_dir)
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    task = {
        "id": task_id,
        "status": "running",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "source": source,
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "logs": {},
        "artifacts": {},
        "error": None,
    }
    if metadata:
        task.update(metadata)
    save_task(task_dir, task)
    write_json(input_dir / "request.json", request)
    journey = new_journey(task, request, source)

    try:
        if request.get("outline"):
            outline = request["outline"]
            append_journey_event(journey, "outline_loaded", "system", "使用请求中提供的 outline。")
        else:
            outline = brief_to_outline(brief)
            append_journey_event(
                journey,
                "outline_created",
                "system",
                "根据 brief 生成保守 outline,并记录开放问题。",
                {"open_questions": len(outline.get("open_questions") or [])},
            )
        write_json(input_dir / "outline.json", outline)

        if request.get("deck_json"):
            deck = request["deck_json"]
            append_journey_event(
                journey,
                "deckjson_loaded",
                "system",
                "使用请求中提供的 DeckJSON 作为源文件。",
                {"slide_count": len(deck.get("slides", [])) if isinstance(deck, dict) else 0},
            )
        else:
            deck = outline_to_deck(outline)
            append_journey_event(
                journey,
                "deckjson_created",
                "system",
                "将 outline 编译为 DeckJSON 初稿。",
                {"slide_count": len(deck.get("slides", [])) if isinstance(deck, dict) else 0},
            )
        write_json(output_dir / "deck.json", deck)

        outline_log = log_dir / "outline-validator.txt"
        proc = run_command(["python3", str(OUTLINE_VALIDATOR), str(input_dir / "outline.json")], outline_log)
        task["logs"]["outline_validator"] = str(outline_log)
        if proc.returncode != 0:
            append_journey_event(journey, "outline_validation_failed", "system", "outline validator 未通过。", {"exit": proc.returncode})
            raise RuntimeError("outline validation failed")
        append_journey_event(journey, "outline_validated", "system", "outline validator 通过。")

        render_log = log_dir / "render.txt"
        render_cmd = ["python3", str(RENDERER), str(output_dir / "deck.json"), str(output_dir), "--shared=copy"]
        if not sync_base_assets():
            render_cmd.append("--offline-cache")
        proc = run_command(render_cmd, render_log)
        task["logs"]["render"] = str(render_log)
        if proc.returncode != 0:
            append_journey_event(journey, "render_failed", "system", "DeckJSON 渲染 HTML 失败。", {"exit": proc.returncode})
            raise RuntimeError("render failed")
        append_journey_event(journey, "rendered", "system", "DeckJSON 已渲染为 HTML / texts.md / assets。")

        write_feedback(output_dir, outline, deck, source)
        append_journey_event(journey, "feedback_written", "system", "写入 FEEDBACK.md,保留本轮判断和待改进项。")

        validator_report = output_dir / "validator-report.md"
        check_log = log_dir / "check-only.txt"
        proc = run_command(
            ["bash", str(CHECK_ONLY), str(output_dir / "index.html"), "--strict", "--report", str(validator_report)],
            check_log,
        )
        task["logs"]["check_only"] = str(check_log)
        task["artifacts"]["validator-report.md"] = str(validator_report)
        if proc.returncode != 0:
            append_journey_event(journey, "strict_validation_failed", "system", "HTML strict validator 未通过。", {"exit": proc.returncode})
            raise RuntimeError("validator failed under --strict")
        append_journey_event(journey, "strict_validated", "system", "HTML strict validator 通过。")
        upsert_journey_version(journey, task, deck)
        write_journey_artifacts(output_dir, journey)

        zip_name = delivery_name(deck)
        package_log = log_dir / "package.txt"
        proc = run_command(["bash", str(PACKAGE), str(output_dir), "--name", zip_name], package_log)
        task["logs"]["package"] = str(package_log)
        if proc.returncode != 0:
            append_journey_event(journey, "package_failed", "system", "可编辑 zip 打包失败。", {"exit": proc.returncode})
            raise RuntimeError("editable zip packaging failed")
        append_journey_event(journey, "packaged", "system", "可编辑 zip 已生成。", {"zip_name": zip_name})

        missing = assert_required_outputs(output_dir)
        if missing:
            append_journey_event(journey, "output_contract_failed", "system", "固定交付契约缺少产物。", {"missing": missing})
            raise RuntimeError("missing required outputs: " + ", ".join(missing))

        task["status"] = "succeeded"
        task["artifacts"].update(output_artifacts(task_id, output_dir, base_url=base_url))
        append_journey_event(journey, "result_ready", "system", "用户可通过状态页、预览链接、编辑器和下载包拿到结果。")
    except Exception as exc:  # noqa: BLE001 - task wrapper should persist any failure.
        task["status"] = "failed"
        task["error"] = str(exc)
        task["artifacts"].update(output_artifacts(task_id, output_dir, base_url=base_url))
        append_journey_event(journey, "task_failed", "system", "任务失败,原因已写入 task.json。", {"error": str(exc)})
    try:
        deck_for_summary = read_json(output_dir / "deck.json") if (output_dir / "deck.json").exists() else None
        upsert_journey_version(journey, task, deck_for_summary)
        insights = write_journey_artifacts(output_dir, journey)
        if not (metadata and metadata.get("parent_task_id")):
            append_learning_event(task, journey, insights)
    except Exception:
        pass
    save_task(task_dir, task)
    return task


def load_request_file(path: Path) -> dict[str, Any]:
    data = read_json(path)
    if "deck" in data and "slides" in data:
        return {"deck_json": data}
    return data


class GeneratorHandler(BaseHTTPRequestHandler):
    server_version = "lark-deck-generator/0.1"

    def base_url(self) -> str:
        host, port = self.server.server_address[:2]
        host_s = "127.0.0.1" if host in ("", "0.0.0.0") else host
        return f"http://{host_s}:{port}"

    def send_json(self, status: int, body: dict[str, Any]) -> None:
        payload = json.dumps(body, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def send_html(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_body_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API.
        parsed = urlparse(self.path)
        parts = [unquote(p) for p in parsed.path.strip("/").split("/") if p]
        if parsed.path == "/health":
            self.send_json(200, health_payload())
            return
        if parts == ["library", "slides"]:
            query = parse_qs(parsed.query)
            item = lambda key: (query.get(key) or [""])[0]
            rows = slide_library.search_slides(
                query=item("query") or item("q"),
                industry=item("industry"),
                product=item("product"),
                customer_stage=item("customer_stage") or item("customer-stage"),
                deck_type=item("deck_type") or item("deck-type"),
                value_prop=item("value_prop") or item("value-prop"),
                layout=item("layout"),
                include_candidates=item("include_candidates").lower() in {"1", "true", "yes"},
                limit=int(item("limit") or "20"),
            )
            self.send_json(200, {"items": rows})
            return
        if parts == ["library", "gate"]:
            gate = slide_library.validate_library()
            self.send_json(200 if gate["ok"] else 500, gate)
            return
        if parts == ["library", "design-kit"]:
            self.send_json(200, slide_library.load_design_kit())
            return
        if parts == ["recipes", "validate"]:
            result = pitch_recipes.validate()
            self.send_json(200 if result["ok"] else 500, result)
            return
        if len(parts) >= 2 and parts[0] == "library":
            root = (REPO / "library").resolve()
            target = (REPO / Path(*parts)).resolve()
            if not target.is_file() or not target.is_relative_to(root):
                self.send_json(404, {"error": "library file not found"})
                return
            content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            raw = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        if len(parts) == 3 and parts[0] == "decks" and parts[2] == "status":
            try:
                self.send_html(200, render_status_page(parts[1]))
            except FileNotFoundError:
                self.send_json(404, {"error": "task not found", "id": parts[1]})
            return
        if len(parts) == 3 and parts[0] == "decks" and parts[2] == "edit":
            try:
                self.send_html(200, render_edit_page(parts[1]))
            except FileNotFoundError:
                self.send_json(404, {"error": "deck not found", "id": parts[1]})
            return
        if len(parts) == 3 and parts[0] == "decks" and parts[2] == "journey":
            try:
                self.send_html(200, render_journey_page(parts[1]))
            except FileNotFoundError:
                self.send_json(404, {"error": "journey not found", "id": parts[1]})
            return
        if len(parts) == 3 and parts[0] == "decks" and parts[2] == "insights":
            try:
                task = load_task(parts[1])
                insights = read_json(Path(task["output_dir"]) / "quality-insights.json")
                self.send_json(200, insights)
            except FileNotFoundError:
                self.send_json(404, {"error": "insights not found", "id": parts[1]})
            return
        if len(parts) == 2 and parts[0] == "decks":
            try:
                self.send_json(200, load_task(parts[1]))
            except FileNotFoundError:
                self.send_json(404, {"error": "task not found", "id": parts[1]})
            return
        if len(parts) >= 4 and parts[0] == "decks" and parts[2] == "files":
            task_id = parts[1]
            rel = Path(*parts[3:])
            output_dir = RUNS_DIR / task_id / "output"
            target = (output_dir / rel).resolve()
            if not target.is_file() or not target.is_relative_to(output_dir.resolve()):
                self.send_json(404, {"error": "file not found"})
                return
            content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            raw = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        self.send_json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API.
        parsed = urlparse(self.path)
        parts = [unquote(p) for p in parsed.path.strip("/").split("/") if p]
        try:
            if parts == ["decks"]:
                task = create_or_run_task(self.read_body_json(), base_url=self.base_url())
                self.send_json(201 if task["status"] == "succeeded" else 500, task)
                return
            if len(parts) == 3 and parts[0] == "decks" and parts[2] == "regenerate":
                task_id = parts[1]
                request_path = RUNS_DIR / task_id / "input" / "request.json"
                if not request_path.exists():
                    self.send_json(404, {"error": "task not found", "id": task_id})
                    return
                task = create_or_run_task(read_json(request_path), task_id=task_id, base_url=self.base_url())
                self.send_json(200 if task["status"] == "succeeded" else 500, task)
                return
            if len(parts) == 3 and parts[0] == "decks" and parts[2] in {"edits", "edit"}:
                task_id = parts[1]
                task = edit_task(task_id, self.read_body_json(), base_url=self.base_url())
                self.send_json(201 if task["status"] == "succeeded" else 500, task)
                return
            if parts == ["library", "candidates"]:
                payload = self.read_body_json()
                result = slide_library.mark_reuse_candidate(
                    str(payload.get("task_id") or payload.get("taskId") or ""),
                    str(payload.get("slide_key") or payload.get("slideKey") or ""),
                    payload,
                )
                has_errors = any(issue["severity"] == "error" for issue in result.get("issues", []))
                self.send_json(400 if has_errors else 201, result)
                return
            if parts == ["library", "ppt-uploads"]:
                payload = self.read_body_json()
                ppt_path = Path(str(payload.get("ppt_path") or payload.get("pptPath") or ""))
                result = slide_library.register_ppt_upload(
                    ppt_path,
                    payload,
                    pages=[int(item) for item in (payload.get("pages") or [])],
                )
                self.send_json(201 if result.get("ok") else 400, result)
                return
            if parts == ["recipes", "plan"]:
                self.send_json(200, pitch_recipes.plan_pitch(self.read_body_json()))
                return
            if len(parts) == 4 and parts[0] == "library" and parts[1] == "candidates" and parts[3] == "approve":
                payload = self.read_body_json()
                result = slide_library.approve_candidate(
                    parts[2],
                    reviewer=str(payload.get("reviewer") or "maintainer"),
                    source_level=str(payload.get("source_level") or "internal-approved"),
                    thumbnail=str(payload.get("thumbnail") or ""),
                )
                self.send_json(200 if result.get("ok") else 400, result)
                return
        except Exception as exc:  # noqa: BLE001
            self.send_json(400, {"error": str(exc)})
            return
        self.send_json(404, {"error": "not found"})

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("[generator] " + (fmt % args) + "\n")


def cmd_create(args: argparse.Namespace) -> int:
    if args.request:
        request = load_request_file(args.request)
    elif args.deck_json:
        request = {"deck_json": read_json(args.deck_json)}
        if args.brief:
            request["brief"] = read_json(args.brief)
    elif args.brief:
        request = {"brief": read_json(args.brief)}
    else:
        raise SystemExit("create requires --request, --deck-json, or --brief")
    task = create_or_run_task(request, base_url=args.base_url)
    print(json.dumps(task, ensure_ascii=False, indent=2))
    return 0 if task["status"] == "succeeded" else 1


def cmd_status(args: argparse.Namespace) -> int:
    print(json.dumps(load_task(args.task_id), ensure_ascii=False, indent=2))
    return 0


def cmd_journey(args: argparse.Namespace) -> int:
    task = load_task(args.task_id)
    output_dir = Path(task["output_dir"])
    if args.json:
        print(json.dumps(read_json(output_dir / "journey.json"), ensure_ascii=False, indent=2))
    else:
        print((output_dir / "JOURNEY.md").read_text(encoding="utf-8"))
    return 0


def cmd_regenerate(args: argparse.Namespace) -> int:
    request_path = RUNS_DIR / args.task_id / "input" / "request.json"
    if not request_path.exists():
        raise SystemExit(f"task not found: {args.task_id}")
    task = create_or_run_task(read_json(request_path), task_id=args.task_id, base_url=args.base_url)
    print(json.dumps(task, ensure_ascii=False, indent=2))
    return 0 if task["status"] == "succeeded" else 1


def cmd_edit(args: argparse.Namespace) -> int:
    payload = read_json(args.patch)
    task = edit_task(args.task_id, payload, base_url=args.base_url)
    print(json.dumps(task, ensure_ascii=False, indent=2))
    return 0 if task["status"] == "succeeded" else 1


def cmd_serve(args: argparse.Namespace) -> int:
    httpd = ThreadingHTTPServer((args.host, args.port), GeneratorHandler)
    host, port = httpd.server_address[:2]
    print(f"generator listening on http://{host}:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", help="create and run a deck generation task")
    create.add_argument("--request", type=Path, help="JSON request with brief, outline, and/or deck_json")
    create.add_argument("--brief", type=Path, help="brief JSON; used when no request is supplied")
    create.add_argument("--deck-json", type=Path, help="DeckJSON source; skips deterministic brief planner")
    create.add_argument("--base-url", help="external base URL used to populate preview/edit links")
    create.set_defaults(func=cmd_create)

    status = sub.add_parser("status", help="print task status JSON")
    status.add_argument("task_id")
    status.set_defaults(func=cmd_status)

    journey = sub.add_parser("journey", help="print task user journey")
    journey.add_argument("task_id")
    journey.add_argument("--json", action="store_true", help="print journey.json instead of JOURNEY.md")
    journey.set_defaults(func=cmd_journey)

    regen = sub.add_parser("regenerate", help="rerun an existing task from input/request.json")
    regen.add_argument("task_id")
    regen.add_argument("--base-url", help="external base URL used to populate preview/edit links")
    regen.set_defaults(func=cmd_regenerate)

    edit = sub.add_parser("edit", help="create a new version from a DeckJSON edit payload")
    edit.add_argument("task_id")
    edit.add_argument("--patch", required=True, type=Path, help="JSON payload with deck_json or structured updates")
    edit.add_argument("--base-url", help="external base URL used to populate preview/edit links")
    edit.set_defaults(func=cmd_edit)

    serve = sub.add_parser("serve", help="run the HTTP wrapper")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
