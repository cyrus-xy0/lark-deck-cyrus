#!/usr/bin/env python3
"""Minimal server-side generator wrapper for lark-deck-cyrus.

This is the productized P0 path around the existing local skills:

  Sources -> parser -> Outline -> user confirm -> renderer -> auditor
  -> pitch rehearsal gate -> publish -> user revise/ingest decision -> ingestion

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
COMPILE_OUTLINE = REPO / "skills/deck-renderer/deck-json/compile-outline.py"
MATERIALIZE_ASSETS = REPO / "skills/deck-renderer/deck-json/materialize-feishu-assets.py"
RENDERER = REPO / "skills/deck-renderer/deck-json/render-deck.py"
CHECK_ONLY = REPO / "skills/deck-renderer/assets/check-only.sh"
AUDITOR = REPO / "skills/deck-auditor/audit.py"
PACKAGE = REPO / "skills/deck-renderer/assets/package-deliverable.sh"
INLINE_ASSETS = REPO / "skills/deck-renderer/assets/inline-assets.py"
UPLOAD_PARSER = REPO / "skills/upload-parser/parse.py"
CONTRACT_VALIDATOR = REPO / "skills/lark-deck-cyrus/schema/validate-contract.py"
SOURCE_DOSSIER_SCHEMA = REPO / "skills/lark-deck-cyrus/schema/source-dossier.schema.json"
PITCH_SIMULATOR = REPO / "skills/pitch-simulator/simulate-pitch.py"
PITCH_REHEARSAL_VALIDATOR = REPO / "skills/pitch-simulator/validate-rehearsal.py"
DECK_INGESTOR = REPO / "skills/deck-ingestor/ingest.py"
BASE_LIBRARY = REPO / "scripts/base_library.py"
DEFAULT_TOS_UPLOADER = Path("/Users/bytedance/.codex/skills/upload-file-to-tos/upload.js")
DEFAULT_MAGIC_PAGE_PUBLISHER = Path("/Users/bytedance/.codex/skills/publish-magic-page/publish.js")
DEFAULT_MAGIC_DOC_CREATOR = Path("/Users/bytedance/.codex/skills/generate-magic-doc/scripts/create_magic_doc.mjs")
DEFAULT_MAGIC_BASE_URL = "https://magic.solutionsuite.cn"

REQUIRED_OUTPUTS = [
    "deck.json",
    "index.html",
    "texts.md",
    "FEEDBACK.md",
    "AUDIT_REPORT.md",
    "audit-report.json",
    "assets-manifest.yaml",
    "pitch-rehearsal.json",
    "PITCH_REHEARSAL.md",
    "journey.json",
    "JOURNEY.md",
    "quality-insights.json",
    "cloud-publish.json",
    "CLOUD_PUBLISH.md",
]

HIDDEN_OUTPUT_ARTIFACTS = {
    "outline.json",
    "source-dossier.json",
    "SOURCE_DOSSIER.md",
    "compile-report.json",
    "asset-materialization.json",
    "audit-report.json",
    "audit-report.md",
    "cloud-publish.json",
    "magic-doc-publish.json",
    "magic-page-publish.json",
    "magic-publish.json",
    "FINAL_SOURCE_DOSSIER.json",
    "pitch-rehearsal.json",
    "rehearsal-gate.json",
    "journey.json",
    "quality-insights.json",
}

TEXT_LEAF_SKIP_KEYS = {"title", "icon", "img", "image", "src", "url", "href", "company_logo"}


class FlowPaused(Exception):
    """Internal sentinel for non-failure pauses that still need task persistence."""


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


def task_audit_passed(output_dir: Path) -> bool:
    report = output_dir / "audit-report.json"
    if report.exists():
        try:
            payload = read_json(report)
        except Exception:
            payload = {}
        verdict = str(payload.get("verdict") or payload.get("cyrus_verdict") or payload.get("status") or "").lower()
        if verdict == "pass":
            return True
    md = output_dir / "AUDIT_REPORT.md"
    if md.exists():
        first = md.read_text(encoding="utf-8", errors="ignore").splitlines()[:5]
        joined = " ".join(first).lower()
        return "cyrus verdict: pass" in joined or "verdict: pass" in joined
    return False


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


def text_items(value: Any) -> list[str]:
    """Normalize already-authored phrases without splitting Chinese punctuation."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    return [str(value).strip()] if str(value).strip() else []


def walk_text(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        parts: list[str] = []
        for item in value.values():
            parts.extend(walk_text(item))
        return parts
    if isinstance(value, list):
        parts = []
        for item in value:
            parts.extend(walk_text(item))
        return parts
    return []


def brief_value(brief: dict[str, Any], *keys: str, default: str = "") -> str:
    for key in keys:
        value = brief.get(key)
        if value:
            return str(value).strip()
    return default


def base_identity() -> str:
    return os.environ.get("LARK_LIBRARY_AS", "user")


def use_base_library() -> bool:
    raw = os.environ.get("GENERATOR_USE_BASE_LIBRARY")
    if raw is None:
        return True
    return raw.lower() not in {"0", "false", "no", "local"}


def sync_base_assets() -> bool:
    raw = os.environ.get("GENERATOR_SYNC_BASE_ASSETS")
    if raw is None:
        return True
    return raw.lower() not in {"0", "false", "no", "local"}


def inline_delivery_html() -> bool:
    raw = os.environ.get("GENERATOR_INLINE_HTML")
    if raw is None:
        return True
    return raw.lower() not in {"0", "false", "no", "linked"}


def publish_magic_enabled() -> bool:
    raw = os.environ.get("CYRUS_PUBLISH_MAGIC")
    if raw is None:
        return True
    return raw.lower() not in {"0", "false", "no", "local", "file"}


def default_publish_target() -> str:
    if not publish_magic_enabled():
        return "none"
    raw = os.environ.get("CYRUS_PUBLISH_TARGET") or os.environ.get("CYRUS_CLOUD_TARGET") or "magic-page"
    target = raw.strip().lower()
    return target if target in {"magic-page", "magic-doc", "none"} else "magic-page"


def publish_magic_doc_enabled() -> bool:
    raw = os.environ.get("CYRUS_PUBLISH_MAGIC_DOC")
    if raw is None:
        return default_publish_target() == "magic-doc"
    return raw.lower() not in {"0", "false", "no", "local", "file"}


def magic_dry_run() -> bool:
    raw = os.environ.get("CYRUS_MAGIC_DRY_RUN") or os.environ.get("MAGIC_DRY_RUN")
    return str(raw).lower() in {"1", "true", "yes", "mock"}


def visual_audit_enabled() -> bool:
    raw = os.environ.get("GENERATOR_VISUAL_AUDIT")
    if raw is None:
        return True
    return raw.lower() not in {"0", "false", "no", "skip", "off"}


def require_brief_clarification(request: dict[str, Any]) -> bool:
    return bool(request.get("require_brief_confirmation") or request.get("require_brief_clarification"))


def success_like_status(status: str) -> bool:
    return status in {
        "succeeded",
        "visual_unverified",
        "awaiting_outline_confirmation",
        "awaiting_brief_clarification",
        "awaiting_rehearsal_decision",
        "awaiting_deck_confirmation",
        "completed_without_ingestion",
    }


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
        "auditor_exists": AUDITOR.exists(),
        "h5_check_only_exists": CHECK_ONLY.exists(),
        "base_library": {
            "enabled": use_base_library(),
            "sync_assets": sync_base_assets(),
            "identity": base_identity(),
        },
        "cloud_publish": {
            "target": default_publish_target(),
            "enabled": default_publish_target() != "none",
            "dry_run": magic_dry_run(),
            "magic_page_publisher": str(DEFAULT_MAGIC_PAGE_PUBLISHER),
            "magic_doc_publisher": str(DEFAULT_MAGIC_DOC_CREATOR),
        },
        "output_contract": REQUIRED_OUTPUTS + ["editable zip", "AUDIT_REPORT.md", "task.json"],
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


def critical_brief_questions(brief: dict[str, Any]) -> list[str]:
    checks = [
        ("customer_name", "客户是谁?"),
        ("industry", "客户所属行业和最关键的业务时刻是什么?"),
        ("audience", "这份 deck 讲给谁,他们要做什么决策?"),
        ("objective", "讲完后希望客户确认的下一步是什么?"),
        ("product_scope", "本次要重点讲哪些飞书产品或能力边界?"),
    ]
    return [question for key, question in checks if not brief.get(key)]


def layout_label(slide: dict[str, Any]) -> str:
    candidate = slide.get("layout_candidate") if isinstance(slide.get("layout_candidate"), dict) else {}
    layout = str(candidate.get("layout") or "content")
    variant = str(candidate.get("variant") or "")
    return f"{layout}/{variant}" if variant else layout


def infer_hero_slide(slide: dict[str, Any]) -> bool:
    candidate = slide.get("layout_candidate") if isinstance(slide.get("layout_candidate"), dict) else {}
    layout = str(candidate.get("layout") or "")
    variant = str(candidate.get("variant") or "")
    role = str(slide.get("role") or "")
    assets = normalize_list(slide.get("assets")) or normalize_list(slide.get("asset_need"))
    if role in {"cover", "closing", "demo"}:
        return True
    if layout in {"cover", "end", "quote", "image-text", "iframe-embed", "replica", "raw"}:
        return True
    if layout == "stats" and variant in {"hero", "waterfall"}:
        return True
    return layout == "content" and variant == "2col" and bool(assets)


def density_budget_for_slide(slide: dict[str, Any]) -> str:
    candidate = slide.get("layout_candidate") if isinstance(slide.get("layout_candidate"), dict) else {}
    layout = str(candidate.get("layout") or "")
    variant = str(candidate.get("variant") or "")
    beats = normalize_list(slide.get("content_beats"))
    proof = normalize_list(slide.get("proof_needed")) or normalize_list(slide.get("evidence"))
    assets = normalize_list(slide.get("asset_need")) or normalize_list(slide.get("assets"))
    if layout == "cover":
        return "标题 1 个,副信息 2-3 个,可放客户/飞书品牌锚点;不叠加论证内容。"
    if layout == "end":
        return "收束句 1 个,next step / 联系信息 1 组;不新增论点。"
    if layout == "agenda":
        return f"{max(len(beats), 3)} 个章节以内,每项 1 行短句。"
    if layout == "table":
        rows = max(len(beats), len(proof), 4)
        return f"{min(rows, 7)} 行 x 3-4 列以内,每格短语化,保留来源/口径列。"
    if layout == "arch-stack":
        layers = max(min(len(beats), 5), 3)
        return f"{layers} 层架构,每层 2-5 个模块;只保留能解释因果链的模块。"
    if layout == "flow":
        steps = max(min(len(beats), 6), 3)
        return f"{steps} 个阶段/节点,每节点标题 + 1 句输出物;避免流程说明过长。"
    if layout == "stats":
        return "3-4 个指标或 1 个主指标 + 2-3 个辅助指标;无真实数据时只写口径。"
    if layout == "logo-wall":
        return "8-16 个 logo / 素材位以内,必须区分客户证据与相邻启发。"
    if layout == "content" and variant == "3up":
        return "3 张卡,每卡标题 + 1-2 句;可加 1 条 pullquote 或原则带。"
    if layout == "content" and variant == "2col":
        return "左侧 3-5 条判断,右侧 1 个主图/demo/mock;图文主次必须明确。"
    if layout == "content" and variant == "matrix":
        return "2x2 或 3x2 矩阵,每格 1 个判断 + 1 个证据/动作。"
    if layout == "content" and variant == "story-case":
        return "案例 1 个,按背景/冲突/动作/结果四段;结果无证据时写价值方向。"
    if layout == "quote":
        return "主句 1 个,解释 1-2 句;只作为节奏页或观点页。"
    if layout in {"iframe-embed", "raw", "replica"}:
        return "保留 1 个核心画面/交互,旁注不超过 3 条;复杂性放进素材说明。"
    return "3-5 个信息块以内,每块只承载 1 个判断或动作。"


def content_completion_for_slide(slide: dict[str, Any]) -> str:
    title = str(slide.get("title") or "本页")
    beats = normalize_list(slide.get("content_beats"))
    proof = normalize_list(slide.get("proof_needed")) or normalize_list(slide.get("evidence"))
    assets = normalize_list(slide.get("asset_need")) or normalize_list(slide.get("assets"))
    parts = [f"围绕“{title}”把原始材料压缩成可讲短句"]
    if beats:
        parts.append("保留 " + "、".join(beats[:4]) + (" 等内容节拍" if len(beats) > 4 else " 作为内容节拍"))
    if proof:
        parts.append("补齐/标注证据: " + "、".join(proof[:3]))
    if assets:
        parts.append("素材优先级: " + "、".join(assets[:3]))
    parts.append("缺失事实进入 open questions,不在页面里硬补数字")
    return "；".join(parts) + "。"


def fact_boundary_for_slide(slide: dict[str, Any]) -> str:
    role = str(slide.get("role") or "")
    risks = text_items(slide.get("risk")) or text_items(slide.get("risk_flags"))
    proof = text_items(slide.get("proof_needed")) or text_items(slide.get("evidence"))
    if risks:
        return "；".join(risks)
    if proof:
        return "可以表达为基于已列证据方向的规划判断;未拿到来源前不写成客户已验证事实。"
    if role in {"cover", "agenda", "closing"}:
        return "只做标题、议程或收束,不新增业务事实。"
    return "缺少客户事实时只写成假设或待验证判断,不补 ROI、百分比或具名案例。"


def design_spec_for_slide(slide: dict[str, Any]) -> dict[str, Any]:
    title = str(slide.get("title") or "页面")
    role = str(slide.get("role") or "context")
    message = str(slide.get("message") or title)
    key_idea = str(slide.get("key_idea") or message)
    beats = normalize_list(slide.get("content_beats"))
    proof = normalize_list(slide.get("proof_needed")) or normalize_list(slide.get("evidence"))
    assets = normalize_list(slide.get("asset_need")) or normalize_list(slide.get("assets"))
    risk = fact_boundary_for_slide(slide)
    hero = bool(slide.get("hero"))
    hierarchy = {
        "a": message,
        "b": " / ".join(beats[:3]) if beats else key_idea,
        "c": " / ".join((proof or assets)[:3]) if (proof or assets) else "证据缺口需在页面注脚或 open questions 中保留。",
        "d": risk,
    }
    return {
        "q0_role": f"{role} 页: {title}",
        "q1_memory": message,
        "q2_hierarchy": hierarchy,
        "q3_mood": "飞书深色商务科技感;判断要咨询式、短句化,视觉锚点服务业务因果。",
        "q4_tradeoff": risk,
        "six_dimensions": [
            f"密度: {slide.get('density_budget') or density_budget_for_slide(slide)}",
            f"层级: A 档是“{hierarchy['a']}”,B 档是支撑节拍,C 档是证据/素材。",
            f"证据: {hierarchy['c']}",
            "节奏: " + ("作为 Hero / 视觉锚点页,要让观众短暂停顿。" if hero else "作为承接页,优先保证扫描效率和页间递进。"),
            "语言: 中文短句,避免行业领先、全面赋能等空泛表达。",
            "用途: 服务现场讲解和用户确认,确认后才交给 renderer 生产 H5。",
        ],
    }


def enrich_slide_plan(slide: dict[str, Any]) -> dict[str, Any]:
    """Fill required deck-planner talk-intent fields for generated outlines."""
    out = copy.deepcopy(slide)
    message = str(out.get("message") or out.get("title") or "本页需要支撑整体 pitch 主线。")
    title = str(out.get("title") or out.get("key") or "页面")
    role = str(out.get("role") or "context")
    assets = normalize_list(out.get("assets"))
    evidence = normalize_list(out.get("evidence"))
    risks = text_items(out.get("risk_flags"))
    out.setdefault("key_idea", message)
    out.setdefault("emphasis", f"让客户在这一页明确理解: {message}")
    out.setdefault("talk_track", f"讲这一页时先点题“{title}”,再用业务语境解释为什么它会影响下一步决策。")
    out.setdefault("proof_needed", evidence)
    out.setdefault("asset_need", assets)
    out.setdefault("risk", risks)
    if role not in {"cover", "closing"} and not out["risk"]:
        out["risk"] = ["缺少客户事实时,只能作为待验证判断。"]
    out.setdefault("hero", infer_hero_slide(out))
    out.setdefault("density_budget", density_budget_for_slide(out))
    out.setdefault("content_completion", content_completion_for_slide(out))
    out.setdefault("fact_boundary", fact_boundary_for_slide(out))
    out.setdefault("design_spec", design_spec_for_slide(out))
    return out


def outline_slide_notes(slide: dict[str, Any]) -> str:
    lines: list[str] = []
    for label, key in [
        ("role", "role"),
        ("message", "message"),
        ("key_idea", "key_idea"),
        ("emphasis", "emphasis"),
        ("talk_track", "talk_track"),
        ("visual_intent", "visual_intent"),
        ("density_budget", "density_budget"),
        ("content_completion", "content_completion"),
        ("fact_boundary", "fact_boundary"),
    ]:
        value = slide.get(key)
        if isinstance(value, str) and value.strip():
            lines.append(f"{label}: {value.strip()}")
    if isinstance(slide.get("hero"), bool):
        lines.append(f"hero: {'yes' if slide.get('hero') else 'no'}")
    spec = slide.get("design_spec") if isinstance(slide.get("design_spec"), dict) else {}
    if spec:
        hierarchy = spec.get("q2_hierarchy") if isinstance(spec.get("q2_hierarchy"), dict) else {}
        lines.append("design_spec:")
        for key in ["q0_role", "q1_memory", "q3_mood", "q4_tradeoff"]:
            if isinstance(spec.get(key), str) and spec.get(key).strip():
                lines.append(f"  {key}: {spec[key].strip()}")
        if hierarchy:
            lines.append(
                "  q2_hierarchy: "
                + " / ".join(f"{tier.upper()}={hierarchy.get(tier)}" for tier in ["a", "b", "c", "d"] if hierarchy.get(tier))
            )
    for label, key in [
        ("proof_needed", "proof_needed"),
        ("asset_need", "asset_need"),
        ("risk", "risk"),
        ("evidence", "evidence"),
        ("risk_flags", "risk_flags"),
    ]:
        items = normalize_list(slide.get(key))
        if items:
            lines.append(f"{label}: " + " / ".join(items))
    for label, key in [
        ("source_refs", "source_refs"),
        ("knowledge_refs", "knowledge_refs"),
        ("material_refs", "material_refs"),
    ]:
        refs = slide.get(key) if isinstance(slide.get(key), list) else []
        rendered = []
        for ref in refs[:8]:
            if not isinstance(ref, dict):
                continue
            parts = [
                str(ref.get("source_type") or "").strip(),
                str(ref.get("source") or "").strip(),
                str(ref.get("slide_key") or ref.get("material_id") or ref.get("knowledge_id") or "").strip(),
            ]
            text = " | ".join(part for part in parts if part)
            if text:
                rendered.append(text)
        if rendered:
            lines.append(f"{label}: " + " / ".join(rendered))
    return "\n".join(lines)


def process_reinvention_slides(title: str, customer: str, business_moment: str) -> list[dict[str, Any]]:
    """Canonical six-page outline for AI workflow/process reinvention decks."""
    subject = customer if customer != "目标客户" else "组织"
    return [
        {
            "key": "cover",
            "title": title,
            "role": "cover",
            "message": "不是把 AI 塞进旧流程,而是让工件、数据流、颗粒度和角色全部被重新定义。",
            "layout_candidate": {"layout": "cover"},
            "assets": ["customer-logo"],
            "talk_track": "开场直接把讨论从工具升级到流程物理层:我们不是优化一份材料,而是在重写材料背后的工作方式。",
        },
        {
            "key": "old-world-dead-end",
            "title": "看起来在运转,实际上是一条断头路",
            "role": "pain",
            "message": "旧流程每一环看起来都有人在管,但材料是终点、知识是孤岛、人是唯一连接器。",
            "content_beats": [
                "知识库是死库存:文件存在,但等于不可用。",
                "复盘是幸存者偏差:样本靠记忆,问题反复出现。",
                "质量是黑盒:少量抽查之外,客户真实反应沉底。",
                "绩效是猜谜:评价依赖印象,缺少可追溯证据。",
            ],
            "layout_candidate": {"layout": "content", "variant": "matrix"},
            "visual_intent": "四象限证据页,每个象限都是一个旧流程症状,共同支撑“断头路”判断。",
            "evidence": ["共享盘文件命名、复盘记录、质检抽查样本、人员评价口径。"],
            "risk_flags": ["不要把通用症状写成特定客户已发生事实,除非用户提供证据。"],
        },
        {
            "key": "physical-layer-leap",
            "title": "整个故事的奇点,只有一件事:把 PPT 换成 HTML",
            "role": "insight",
            "message": "AI 能不能介入业务流程,首先是物理问题:载体决定 AI 能不能读、拆、重组和回流。",
            "content_beats": [
                "本质:二进制黑盒 -> 结构化文本。",
                "AI 视角:整体存取 -> 可解析、可拆解、可重组。",
                "最小单位:文件 -> 一句话、一个观点、一张图。",
                "检索方式:文件名 -> 语义。",
                "流动方式:搬运 -> 引用、继承、改写。",
            ],
            "layout_candidate": {"layout": "table"},
            "visual_intent": "PPT 与 HTML 两栏对照,强调这是载体物理性质变化,不是单纯换格式。",
            "evidence": ["HTML deck 源码、DeckJSON、texts.md、可编辑文本颗粒度。"],
            "risk_flags": ["不要把“HTML 一定优于 PPT”绝对化;结论限定在 AI 可解析和可回流的流程场景。"],
        },
        {
            "key": "reporting-flywheel",
            "title": "当汇报不再是终点,而是燃料",
            "role": "solution",
            "message": "每一场汇报既消耗知识,也生产知识;既是动作终点,也是下一次动作起点。",
            "content_beats": ["生成", "汇报", "质检", "入库", "反哺"],
            "layout_candidate": {"layout": "flow", "variant": "process"},
            "visual_intent": "五步闭环飞轮:生成 -> 汇报 -> 质检 -> 入库 -> 反哺。",
            "evidence": ["录音豆逐字稿、质量分、知识库片段、每次微调留痕。"],
            "risk_flags": ["若没有真实录音/质检能力证据,写成目标流程和待验证机制。"],
        },
        {
            "key": "four-reversals",
            "title": "流程重塑,本质上是四个反转",
            "role": "insight",
            "message": "流程重塑不是给每个环节加 AI,而是让工件、数据、颗粒度和人的角色发生反转。",
            "content_beats": [
                "工件反转:死文件 -> 活资产。",
                "数据反转:单向归档 -> 双向喂养。",
                "颗粒度反转:文件级 -> 片段级。",
                "角色反转:内容生产者 -> 判断提供者。",
            ],
            "layout_candidate": {"layout": "content", "variant": "matrix"},
            "visual_intent": "四象限范式页,每格都是 from -> to + 一句解释。",
            "evidence": ["工件可检索性、入库回流、片段级引用、人工微调留痕。"],
            "risk_flags": ["只做一两个反转时,不能宣称完成流程重塑。"],
        },
        {
            "key": "self-evolving-process",
            "title": "当流程开始自己进化",
            "role": "closing",
            "message": f"{subject}的目标不是上线一套系统,而是让{business_moment}具备自我进化能力。",
            "content_beats": [
                "每一次执行都在喂养下一次执行。",
                "每一次微调都在改写流程本身。",
                "每一个个体的进步,都自动变成组织的进步。",
            ],
            "layout_candidate": {"layout": "quote"},
            "visual_intent": "收束为一页大句子,从系统能力回到人的价值密度。",
            "evidence": ["流程执行日志、知识回流记录、个人修改如何成为组织资产。"],
            "risk_flags": ["结尾应是愿景判断,不要包装成已实现事实。"],
        },
    ]


def is_enterprise_manufacturing_ai_brief(
    industry: str,
    business_moment: str,
    core_tension: str,
    product_scope: list[str],
    solution_angle: str,
) -> bool:
    text = " ".join([industry, business_moment, core_tension, solution_angle, *product_scope]).lower()
    manufacturing_terms = ["制造", "工厂", "产线", "车间", "质量", "异常", "npi", "mes", "plm", "供应链", "光模块"]
    ai_terms = ["ai", "agent", "智能体", "数字员工", "大模型", "人工智能"]
    workflow_terms = ["飞书", "base", "任务", "知识", "bot", "多维表格", "工作流"]
    return any(term in text for term in manufacturing_terms) and (
        any(term in text for term in ai_terms) or any(term in text for term in workflow_terms)
    )


def strengthen_enterprise_manufacturing_outline(slides: list[dict[str, Any]], business_moment: str) -> None:
    """Add concrete scene/prototype anchors before the H5 renderer handoff."""
    for slide in slides:
        key = slide.get("key")
        if key == "role-lens":
            slide.update(
                {
                    "title": "工程师的一天:从异常发现到纠正动作",
                    "role": "insight",
                    "message": f"把{business_moment}变成一个可追踪工作台,让工程师、督导和 IT 都看到同一条异常闭环。",
                    "content_beats": ["工程师发现异常", "督导确认责任与时限", "IT 守住权限和系统边界"],
                    "layout_candidate": {"layout": "content", "variant": "2col"},
                    "visual_intent": "左侧讲角色路径,右侧用质量异常闭环工作台/看板 mock 承载证据、责任人和下一步动作。",
                    "assets": ["quality-workbench-mock"],
                    "risk_flags": ["这是待验证的工作台原型,不写成客户已上线事实。"],
                }
            )
        elif key == "adjacent-proof":
            slide.update(
                {
                    "title": "一次质量异常闭环案例",
                    "role": "evidence",
                    "message": "用一个假设案例页说明从异常、证据、纠正动作到复盘沉淀的完整链路,避免只讲产品模块。",
                    "content_beats": ["异常进入统一入口", "AI 汇总 8D / 巡检 / 邮件证据", "负责人和时限写入任务", "复盘沉淀为下一次预警"],
                    "layout_candidate": {"layout": "content", "variant": "story-case"},
                    "visual_intent": "案例页采用 pain / conflict / solution / value 结构,配一个工厂质量 review panel 示意图。",
                    "assets": ["quality-review-panel"],
                    "risk_flags": ["案例是场景化演示,需要用户补充真实异常样本后才能当客户事实。"],
                }
            )


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
    source_dossier = brief.get("source_dossier") if isinstance(brief.get("source_dossier"), dict) else {}
    source_knowledge = list(source_dossier.get("knowledge_layer") or [])[:8]
    source_materials = list(source_dossier.get("material_layer") or [])[:8]
    source_slides = list(source_dossier.get("slide_layer") or [])[:6]
    source_needs_confirmation = list((source_dossier.get("confidence") or {}).get("needs_confirmation") or [])
    source_knowledge_refs = [
        {
            "source": "user-provided",
            "provider": "upload-parser",
            "title": item.get("title") or item.get("id") or "用户素材知识",
            "summary": str(item.get("content") or "")[:300],
            "cache_path": ((item.get("provenance") or {}).get("source") or ""),
            "used_for": "来自用户上传/链接素材,优先作为 planner 的事实和证据线索。",
        }
        for item in source_knowledge
        if isinstance(item, dict)
    ]
    source_dossier_refs: list[dict[str, Any]] = []
    for item in source_knowledge:
        if not isinstance(item, dict):
            continue
        provenance = item.get("provenance") if isinstance(item.get("provenance"), dict) else {}
        source_dossier_refs.append({
            "source": str(provenance.get("source") or ""),
            "runtime_source": str(provenance.get("runtime_source") or ""),
            "source_type": "knowledge",
            "page": provenance.get("page") or "",
            "slide_key": str(provenance.get("slide_key") or ""),
            "knowledge_id": str(item.get("id") or ""),
            "confidence": str(item.get("confidence") or ""),
            "used_for": "作为 planner 的用户素材事实和证据线索。",
        })
    for item in source_materials:
        if not isinstance(item, dict):
            continue
        provenance = item.get("provenance") if isinstance(item.get("provenance"), dict) else {}
        source_dossier_refs.append({
            "source": str(provenance.get("source") or item.get("path") or ""),
            "runtime_source": str(provenance.get("runtime_source") or item.get("path") or ""),
            "source_type": "material",
            "material_id": str(item.get("id") or ""),
            "path": str(item.get("path") or ""),
            "used_for": "作为 renderer 的用户素材候选。",
        })
    for item in source_slides:
        if not isinstance(item, dict):
            continue
        source_dossier_refs.append({
            "source": str(item.get("source") or ""),
            "runtime_source": str(item.get("runtime_source") or ""),
            "source_type": "slide",
            "page": item.get("page") or "",
            "slide_key": str(item.get("slide_key") or ""),
            "used_for": "保留上传材料的原始页序和讲法线索。",
        })
    source_dossier_refs = [
        ref for idx, ref in enumerate(source_dossier_refs)
        if ref.get("source") and ref not in source_dossier_refs[:idx]
    ]
    source_material_asset_ids = [
        slugify(str(item.get("id") or f"user-material-{idx}"), f"user-material-{idx}")
        for idx, item in enumerate(source_materials, 1)
        if isinstance(item, dict)
    ]
    enterprise_manufacturing = is_enterprise_manufacturing_ai_brief(
        industry,
        business_moment,
        core_tension,
        product_scope,
        solution_angle,
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

    if recipe.get("id") == "process-reinvention":
        slides = process_reinvention_slides(title, customer, business_moment)
        solution_angle = "把静态材料升级为可解析、可拆解、可回流的活工件,让每一次执行反哺下一次执行。"
        core_tension = "旧流程的材料、录音、复盘和评价都停在死工件里,无法自动回流为下一次行动。"
        pain_points = [
            {
                "name": "死工件",
                "why_now": "AI 要介入流程,必须先能读取和拆解流程产物。",
                "impact": "材料归档后无法被语义检索、引用、继承和改写。",
                "evidence_level": "public-pattern",
                "evidence_needed": "需要用户补充旧材料、归档方式和复盘记录。",
            },
            {
                "name": "断头路",
                "why_now": "组织希望流程越跑越强,而不是每次从零开始。",
                "impact": "汇报、录音和复盘没有回流,知识增长依赖个人记忆。",
                "evidence_level": "hypothesis",
                "evidence_needed": "需要用户确认每次执行后哪些数据会沉淀或丢失。",
            },
        ]
    else:
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
                "key": "agenda",
                "title": "讨论路径",
                "role": "agenda",
                "message": "先对齐业务断点,再看闭环方案、相邻证据、试点口径和下一步。",
                "content_beats": ["业务断点", "工作流闭环", "角色关切", "相邻证据", "试点路径"],
                "layout_candidate": {"layout": "agenda"},
                "assets": [],
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
                "key": "role-lens",
                "title": "不同角色关心什么",
                "role": "insight",
                "message": "同一套试点要同时回答业务、使用、技术三类问题。",
                "content_beats": ["业务负责人要看到推进价值", "一线负责人要确认操作负担", "技术负责人要判断边界和权限"],
                "layout_candidate": {"layout": "content", "variant": "3up"},
                "assets": [],
                "risk_flags": ["若真实参会角色不同,这一页需要按用户补充调整。"],
            },
            {
                "key": "adjacent-proof",
                "title": "用户素材与相邻场景",
                "role": "evidence",
                "message": "优先使用用户素材作为证据,再用素材库中的相邻行业页做讲法参考。",
                "content_beats": [str(item.get("title") or item.get("slide_key") or "用户素材")[:20] for item in source_slides][:3]
                or ["连锁零售", "餐饮茶饮", "投资机构"],
                "layout_candidate": {"layout": "logo-wall"},
                "assets": [*source_material_asset_ids[:3], "adjacent-logo-wall"] if source_material_asset_ids else ["adjacent-logo-wall"],
                "source_refs": source_dossier_refs[:8],
                "knowledge_refs": [ref for ref in source_dossier_refs if ref.get("source_type") == "knowledge"][:5],
                "material_refs": [ref for ref in source_dossier_refs if ref.get("source_type") == "material"][:5],
                "risk_flags": ["用户素材中的推断必须保留来源;相邻素材只作启发,不能替代客户事实。"],
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
        if enterprise_manufacturing:
            strengthen_enterprise_manufacturing_outline(slides, business_moment)
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
        "knowledge_refs": [*source_knowledge_refs, *base_knowledge_refs(industry, business_moment, product_scope)],
        "source_dossier_refs": source_dossier_refs,
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
                "id": "adjacent-logo-wall",
                "type": "logo",
                "need": "云端素材库或本地素材池中的相邻行业 logo wall,用于提示可检索素材而不是客户背书。",
                "query": f"{industry} 相邻客户 logo wall",
                "preferred_source": "feishu-base",
                "fallback": "使用本地素材池中已存在且可追溯的 logo;若缺失则删除该页。",
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
            *(
                [
                    {
                        "id": "quality-workbench-mock",
                        "type": "image",
                        "need": "质量异常闭环工作台或看板原型图,用于说明工程师/督导/IT 共用同一事实面板。",
                        "query": "制造 质量异常 工作台 review panel",
                        "preferred_source": "generated",
                        "fallback": "用 H5 原生 2col mock 表达,并标注为待验证原型。",
                        "required": False,
                    },
                    {
                        "id": "quality-review-panel",
                        "type": "image",
                        "need": "工厂质量异常 review panel / 复盘面板示意图,用于案例页的视觉锚点。",
                        "query": "质量异常 8D 巡检 邮件 复盘 看板",
                        "preferred_source": "generated",
                        "fallback": "用 story-case 的结构化案例视觉表达,不伪造真实客户截图。",
                        "required": False,
                    },
                ]
                if enterprise_manufacturing
                else []
            ),
            *[
                {
                    "id": slugify(str(item.get("id") or f"user-material-{idx}"), f"user-material-{idx}"),
                    "type": str(item.get("type") or "other") if str(item.get("type") or "other") in {"image", "video", "icon", "logo", "avatar", "demo", "data", "other"} else "other",
                    "need": "用户上传/链接素材,优先用于填充页面或支撑证据。",
                    "query": str(item.get("path") or ""),
                    "preferred_source": "user-provided",
                    "source_material_id": str(item.get("id") or ""),
                    "resolved_path": str(item.get("path") or ""),
                    "permission_status": str((item.get("provenance") or {}).get("permission_status") or "needs_review"),
                    "provenance": item.get("provenance") if isinstance(item.get("provenance"), dict) else {},
                    "fallback": "无法读取时只保留来源说明,不伪造素材。",
                    "required": False,
                }
                for idx, item in enumerate(source_materials, 1)
                if isinstance(item, dict)
            ],
        ],
        "open_questions": [*source_needs_confirmation, *high_value_questions(brief)],
        "claim_discipline": {
            "unsupported_claims": ["不能声明客户已经实现的百分比提升或具名访谈结论。"],
            "needs_user_confirmation": [*source_needs_confirmation, *high_value_questions(brief)]
            or ["试点范围、指标口径和客户版本边界。"],
        },
        "handoff": {
            "target_skill": "deck-renderer",
            "deckjson_strategy": "direct",
            "notes": "generator wrapper 生成确定性初稿;真实客户交付前应补齐 open questions。",
        },
    }


def outline_uses_recipe(outline: dict[str, Any], recipe_id: str) -> bool:
    refs = outline.get("recipe_refs") if isinstance(outline.get("recipe_refs"), list) else []
    return any(isinstance(ref, dict) and ref.get("id") == recipe_id for ref in refs)


def process_reinvention_deck(outline: dict[str, Any]) -> dict[str, Any]:
    brief = outline["brief"]
    scene = outline["scene"]
    title = brief["title"]
    slug = slugify(title)
    slides = (outline.get("outline") or {}).get("slides") or []
    outline_by_key = {str(slide.get("key")): slide for slide in slides if isinstance(slide, dict)}
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
                    "author": "飞书 · 流程重塑",
                    "date": f"{scene['industry']} · {compact_date()}",
                },
            },
            {
                "key": "old-world-dead-end",
                "layout": "content",
                "variant": "matrix",
                "accent": "orange",
                "data": {
                    "title": "看起来在运转,实际上是一条断头路",
                    "axes": {
                        "y": {"name": "回流能力", "high_label": "活", "low_label": "死"},
                        "x": {"name": "人工依赖", "high_label": "高", "low_label": "低"},
                    },
                    "quadrants": {
                        "tl": {"title": "知识库是死库存", "items": ["PPT 被放进共享盘", "文件存在但不可用"]},
                        "tr": {"title": "复盘是幸存者偏差", "items": ["样本靠记忆", "同类错误继续发生"]},
                        "bl": {"title": "质量是黑盒", "items": ["少量抽查", "客户真实反应沉底"]},
                        "br": {"title": "绩效是猜谜", "items": ["评价依赖印象", "缺少可追溯证据"]},
                    },
                },
            },
            {
                "key": "physical-layer-leap",
                "layout": "table",
                "accent": "blue",
                "data": {
                    "title": "AI 介入流程,首先是个物理问题",
                    "headers": ["维度", "PPT 旧世界", "HTML 新世界"],
                    "rows": [
                        ["本质", "二进制黑盒", "结构化文本"],
                        ["AI 视角", "只能整体存取", "可解析、可拆解、可重组"],
                        ["最小单位", "一个文件", "一句话 / 一个观点 / 一张图"],
                        ["检索方式", "靠文件名", "靠语义"],
                        ["是否可流动", "否,只能被搬运", "是,可引用、继承、改写"],
                    ],
                    "footnote": "载体换了,AI 才有介入流程的物理可能。",
                },
            },
            {
                "key": "reporting-flywheel",
                "layout": "flow",
                "variant": "process",
                "accent": "teal",
                "data": {
                    "title": "当汇报不再是终点,而是燃料",
                    "cols": 5,
                    "steps": [
                        {"num": "01", "title": "生成", "body": "AI 基于库内素材组装初稿,售前在初稿上微调。"},
                        {"num": "02", "title": "汇报", "body": "售前对客户讲,录音豆记录现场语境和客户反馈。"},
                        {"num": "03", "title": "质检", "body": "自动评估表达质量、关键问题应答和可追溯质量分。"},
                        {"num": "04", "title": "入库", "body": "逐字稿结构化沉淀为可检索的售前案例片段。"},
                        {"num": "05", "title": "反哺", "body": "入库内容成为下一次生成素材,每次微调都留痕。"},
                    ],
                },
            },
            {
                "key": "four-reversals",
                "layout": "content",
                "variant": "matrix",
                "accent": "blue",
                "data": {
                    "title": "流程重塑,本质上是四个反转",
                    "axes": {
                        "y": {"name": "组织资产化", "high_label": "资产", "low_label": "文件"},
                        "x": {"name": "流程可生长", "high_label": "生长", "low_label": "静态"},
                    },
                    "quadrants": {
                        "tl": {"title": "工件反转", "items": ["死文件 -> 活资产", "能被检索、引用、重组"]},
                        "tr": {"title": "数据反转", "items": ["单向归档 -> 双向喂养", "归档即燃料"]},
                        "bl": {"title": "颗粒度反转", "items": ["文件级 -> 片段级", "一句话也能被复用"]},
                        "br": {"title": "角色反转", "items": ["内容生产者 -> 判断提供者", "人的价值密度被重新定义"]},
                    },
                },
            },
            {
                "key": "self-evolving-process",
                "layout": "quote",
                "accent": "blue",
                "decor": ["blue-glow"],
                "data": {
                    "title": "当流程开始自己进化",
                    "quote": {
                        "lead": "AI 没有替代任何人。但每个人,",
                        "accent": "都不一样了",
                        "tail": "。",
                    },
                    "attribution": "飞书 · 让 AI 在组织里真正生长",
                },
            },
        ],
    }
    for slide in deck["slides"]:
        plan = outline_by_key.get(str(slide.get("key") or ""))
        if not plan:
            continue
        notes = outline_slide_notes(plan)
        if notes:
            slide["notes"] = notes
    return deck


def outline_to_deck(outline: dict[str, Any]) -> dict[str, Any]:
    if outline_uses_recipe(outline, "process-reinvention"):
        return process_reinvention_deck(outline)

    brief = outline["brief"]
    scene = outline["scene"]
    thesis = outline["thesis"]
    customer = "目标客户"
    title = brief["title"]
    slug = slugify(title)
    outline_slides = outline.get("outline", {}).get("slides", [])
    solution_plan = next((slide for slide in outline_slides if slide.get("key") == "solution-loop"), {})
    product_scope = solution_plan.get("content_beats") or ["飞书 AI", "多维表格", "知识库", "任务"]
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
                "key": "agenda",
                "layout": "agenda",
                "accent": "blue",
                "data": {
                    "items": [
                        {"title_zh": "业务断点"},
                        {"title_zh": "飞书工作流闭环"},
                        {"title_zh": "角色关切"},
                        {"title_zh": "相邻素材与证据"},
                        {"title_zh": "试点指标与路径"},
                        {"title_zh": "下一步确认"},
                    ]
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
                "key": "role-lens",
                "layout": "content",
                "variant": "3up",
                "accent": "blue",
                "data": {
                    "title": "一套试点,要同时回答三类关切",
                    "cards": [
                        {
                            "num": "01",
                            "icon": "trending-up",
                            "title_zh": "业务负责人",
                            "body": "关心为什么现在要做、是否能推动当前业务时刻,以及下一步投入是否可控。",
                            "footer_label": "VALUE · URGENCY",
                        },
                        {
                            "num": "02",
                            "icon": "users",
                            "title_zh": "一线 / 运营负责人",
                            "body": "关心入口是否简单、动作是否真的闭环,以及知识维护会不会变成额外负担。",
                            "footer_label": "ADOPTION · WORKFLOW",
                        },
                        {
                            "num": "03",
                            "icon": "check-circle",
                            "title_zh": "技术 / 实施负责人",
                            "body": "关心权限、数据来源、系统边界和上线节奏,避免试点变成大规模改造。",
                            "footer_label": "SECURITY · SCOPE",
                        },
                    ],
                    "body_blocks": [
                        {
                            "type": "pullquote",
                            "text": "先把角色关切说清楚,后面的方案才不会变成单向产品宣讲。",
                            "tone": "default",
                        }
                    ],
                },
            },
            {
                "key": "adjacent-proof",
                "layout": "logo-wall",
                "accent": "blue",
                "data": {
                    "title": "素材库里先找相邻场景,不把它写成客户事实",
                    "lede": "这些 logo 仅用于提示可检索素材方向;正式客户背书、案例数字和截图必须由用户或授权记录确认。",
                    "industries": [
                        {
                            "name": "连锁零售 / 餐饮茶饮",
                            "logos": ["瑞幸咖啡", "霸王茶姬", "茶百道", "益禾堂"],
                        },
                        {
                            "name": "投资机构 / 复杂协同",
                            "logos": ["IDG资本", "KKR", "PAG", "CPE源峰"],
                        },
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
    outline_by_key = {str(slide.get("key")): slide for slide in outline_slides if isinstance(slide, dict)}
    for slide in deck["slides"]:
        plan = outline_by_key.get(str(slide.get("key") or ""))
        if not plan:
            continue
        notes = outline_slide_notes(plan)
        if notes:
            slide["notes"] = notes
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


def validate_source_dossier_file(path: Path, log_path: Path) -> None:
    proc = run_command(
        [
            "python3",
            str(CONTRACT_VALIDATOR),
            "--schema",
            str(SOURCE_DOSSIER_SCHEMA),
            "--instance",
            str(path),
        ],
        log_path,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"source dossier contract validation failed: {path}")


def find_source_dossier(input_dir: Path, output_dir: Path) -> Path | None:
    for path in [
        input_dir / "runtime-library" / "source-dossier.json",
        input_dir / "source-dossier.json",
        output_dir / "source-dossier.json",
    ]:
        if path.exists():
            return path
    return None


def materialize_deck_assets(
    *,
    task: dict[str, Any],
    input_dir: Path,
    output_dir: Path,
    log_dir: Path,
    journey: dict[str, Any],
) -> None:
    deck_path = output_dir / "deck.json"
    if not deck_path.exists() or not MATERIALIZE_ASSETS.exists():
        return
    cmd = [
        "python3",
        str(MATERIALIZE_ASSETS),
        str(deck_path),
        str(output_dir),
        "--report",
        str(log_dir / "asset-materialization.json"),
        "--markdown",
        str(output_dir / "ASSET_MATERIALIZATION.md"),
        "--fail-on-unresolved",
    ]
    source_dossier = find_source_dossier(input_dir, output_dir)
    if source_dossier:
        cmd.extend(["--source-dossier", str(source_dossier)])
    materialize_log = log_dir / "asset-materialization.txt"
    proc = run_command(cmd, materialize_log)
    task["logs"]["asset_materialization"] = str(materialize_log)
    report_path = log_dir / "asset-materialization.json"
    summary: dict[str, Any] = {}
    if report_path.exists():
        try:
            report = read_json(report_path)
            if isinstance(report.get("summary"), dict):
                summary = report["summary"]
        except Exception:
            summary = {}
    if proc.returncode != 0:
        append_journey_event(
            journey,
            "asset_materialization_failed",
            "system",
            "飞书/Lark 文件素材未能在渲染前落成本地资产。",
            {"exit": proc.returncode, **summary},
        )
        raise RuntimeError("asset materialization failed")
    append_journey_event(
        journey,
        "assets_materialized",
        "system",
        "已检查并落地 DeckJSON 中的飞书/Lark 文件素材。",
        summary,
    )


def source_candidates_from_value(value: Any) -> list[str]:
    if value in (None, "", [], {}):
        return []
    if isinstance(value, dict):
        out: list[str] = []
        for key in ["path", "url", "href", "file", "local_path", "localPath", "download_url", "downloadUrl"]:
            if value.get(key):
                out.extend(source_candidates_from_value(value[key]))
        return out
    if isinstance(value, list):
        out = []
        for item in value:
            out.extend(source_candidates_from_value(item))
        return out
    text = str(value).strip()
    if not text or text.lower() in {"无", "none", "no", "n/a", "na", "null"}:
        return []
    urls = re.findall(r"https?://[^\s,，;；]+", text)
    if urls:
        return urls
    parts = re.split(r"[\n,，;；]+", text)
    return [part.strip() for part in parts if part.strip() and part.strip().lower() not in {"无", "none", "no"}]


def request_sources(request: dict[str, Any]) -> list[str]:
    brief = request.get("brief") if isinstance(request.get("brief"), dict) else {}
    values: list[Any] = []
    for key in ["sources", "source_files", "sourceFiles", "materials", "uploads", "attachments", "files"]:
        if request.get(key):
            values.append(request[key])
    for key in ["attachments", "sources", "source_files", "sourceFiles", "materials", "uploads", "files"]:
        if brief.get(key):
            values.append(brief[key])
    seen: set[str] = set()
    sources: list[str] = []
    for value in values:
        for item in source_candidates_from_value(value):
            if item not in seen:
                seen.add(item)
                sources.append(item)
    return sources


def brief_text_for_parser(brief: dict[str, Any]) -> str:
    if not brief:
        return ""
    compact = {
        key: brief.get(key)
        for key in [
            "title",
            "customer_name",
            "industry",
            "audience",
            "objective",
            "product_scope",
            "business_moment",
            "core_tension",
        ]
        if brief.get(key)
    }
    return json.dumps(compact or brief, ensure_ascii=False)


def cache_runtime_sources(sources: list[str], library_dir: Path) -> list[dict[str, Any]]:
    cached: list[dict[str, Any]] = []
    source_dir = library_dir / "sources"
    for source in sources:
        if re.match(r"https?://", source):
            cached.append({"source": source, "kind": "url", "cached": False})
            continue
        path = Path(source)
        if not path.is_absolute():
            path = (REPO / path).resolve()
        if not path.exists() or not path.is_file():
            cached.append({"source": source, "kind": "file", "cached": False, "reason": "not-found"})
            continue
        digest = hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:10]
        target = source_dir / f"{digest}-{path.name}"
        source_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        cached.append({"source": str(path), "kind": "file", "cached": True, "cache_path": str(target)})
    return cached


def write_runtime_library(input_dir: Path, dossier: dict[str, Any], sources: list[str]) -> dict[str, Any]:
    library_dir = input_dir / "runtime-library"
    library_dir.mkdir(parents=True, exist_ok=True)
    knowledge = dossier.get("knowledge_layer") or []
    materials = dossier.get("material_layer") or []
    slides = dossier.get("slide_layer") or []
    write_json(library_dir / "source-dossier.json", dossier)
    write_json(library_dir / "knowledge.json", {"items": knowledge})
    write_json(library_dir / "materials.json", {"items": materials})
    write_json(library_dir / "slides.json", {"items": slides})
    manifest = {
        "created_at": now_iso(),
        "mode": "agent-runtime-temp",
        "sources": sources,
        "source_cache": cache_runtime_sources(sources, library_dir),
        "knowledge_count": len(knowledge),
        "material_count": len(materials),
        "slide_count": len(slides),
    }
    write_json(library_dir / "manifest.json", manifest)
    return {"path": str(library_dir), **manifest}


def source_confirmation_items(dossier: dict[str, Any]) -> list[str]:
    confidence = dossier.get("confidence") if isinstance(dossier.get("confidence"), dict) else {}
    items = confidence.get("needs_confirmation") if isinstance(confidence.get("needs_confirmation"), list) else []
    return [str(item).strip() for item in items if str(item).strip()]


def add_source_warnings(task: dict[str, Any], dossier: dict[str, Any], journey: dict[str, Any]) -> None:
    items = source_confirmation_items(dossier)
    if not items:
        return
    task.setdefault("warnings", [])
    for item in items:
        warning = f"素材/来源需确认,已继续流程: {item}"
        if warning not in task["warnings"]:
            task["warnings"].append(warning)
    append_journey_event(
        journey,
        "source_confirmation_recorded",
        "system",
        "上传素材存在缺失或不可解析项,已明文记录并继续进入 planner。",
        {"items": items[:20]},
    )


def auditor_visual_flag() -> str:
    return "--visual" if visual_audit_enabled() else "--no-visual"


def visual_audit_unverified(output_dir: Path) -> bool:
    if not visual_audit_enabled():
        return False
    report_path = output_dir / "audit-report.json"
    payload: dict[str, Any] = {}
    if report_path.exists():
        try:
            payload = read_json(report_path)
        except Exception:
            payload = {}
    h5 = payload.get("h5_checkonly_summary") if isinstance(payload.get("h5_checkonly_summary"), dict) else {}
    flags = h5.get("flags") if isinstance(h5.get("flags"), list) else []
    if "visual" not in flags:
        return True
    h5_report = output_dir / "H5_CHECKONLY_REPORT.md"
    h5_text = h5_report.read_text(encoding="utf-8", errors="ignore") if h5_report.exists() else ""
    visual_failed_markers = [
        "visual checks could not run",
        "BrowserType.launch",
        "TargetClosedError",
        "unable to launch",
    ]
    return any(marker in h5_text for marker in visual_failed_markers)


def visual_audit_verified(output_dir: Path) -> bool:
    return visual_audit_enabled() and not visual_audit_unverified(output_dir)


def attach_source_dossier_to_brief(brief: dict[str, Any], dossier: dict[str, Any], runtime_library: dict[str, Any]) -> dict[str, Any]:
    enriched = copy.deepcopy(brief)
    enriched["source_dossier"] = dossier
    enriched["runtime_library"] = runtime_library
    enriched["source_knowledge_count"] = len(dossier.get("knowledge_layer") or [])
    enriched["source_material_count"] = len(dossier.get("material_layer") or [])
    enriched["source_slide_count"] = len(dossier.get("slide_layer") or [])
    return enriched


def run_upload_parser(
    request: dict[str, Any],
    *,
    task_id: str,
    input_dir: Path,
    output_dir: Path,
    log_dir: Path,
    journey: dict[str, Any],
    task: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    brief = request.get("brief") if isinstance(request.get("brief"), dict) else {}
    existing_dossier = request.get("source_dossier")
    if not isinstance(existing_dossier, dict):
        existing_dossier = brief.get("source_dossier") if isinstance(brief.get("source_dossier"), dict) else None
    if existing_dossier:
        sources = request_sources(request)
        runtime_library = write_runtime_library(input_dir, existing_dossier, sources)
        validate_source_dossier_file(
            Path(runtime_library["path"]) / "source-dossier.json",
            log_dir / "source-dossier-contract.txt",
        )
        enriched_request = copy.deepcopy(request)
        enriched_request["brief"] = attach_source_dossier_to_brief(brief, existing_dossier, runtime_library)
        enriched_request["source_dossier"] = existing_dossier
        enriched_request["runtime_library"] = runtime_library
        task["source_dossier"] = {
            "sources": len(sources),
            "knowledge_items": len(existing_dossier.get("knowledge_layer") or []),
            "material_items": len(existing_dossier.get("material_layer") or []),
            "slide_items": len(existing_dossier.get("slide_layer") or []),
            "runtime_library": runtime_library["path"],
            "reused": True,
        }
        if task.get("source") in {"brief", "outline"} and sources:
            task["source"] = "materials+brief"
        append_journey_event(
            journey,
            "upload_parser_reused",
            "system",
            "复用已确认 outline 之前生成的 source dossier 和 runtime 临时库,不重新解析上传物。",
            task["source_dossier"],
        )
        return enriched_request, existing_dossier

    sources = request_sources(request)
    if not sources:
        return request, None
    if not UPLOAD_PARSER.exists():
        raise RuntimeError(f"upload parser missing: {UPLOAD_PARSER}")

    parser_dir = output_dir / "source-parser"
    parser_log = log_dir / "upload-parser.txt"
    proc = run_command(
        [
            "python3",
            str(UPLOAD_PARSER),
            *sources,
            "--brief",
            brief_text_for_parser(brief),
            "--output-dir",
            str(parser_dir),
            "--task-id",
            task_id,
            "--allow-missing",
        ],
        parser_log,
    )
    task["logs"]["upload_parser"] = str(parser_log)
    if proc.returncode != 0:
        dossier_path = parser_dir / "source-dossier.json"
        if not dossier_path.exists():
            append_journey_event(journey, "upload_parser_failed", "system", "上传素材解析失败。", {"exit": proc.returncode})
            raise RuntimeError("upload parser failed")
        task.setdefault("warnings", []).append("upload-parser 返回非 0,但已读取 source-dossier 并继续流程。")
    dossier_path = parser_dir / "source-dossier.json"
    if not dossier_path.exists():
        raise RuntimeError("upload parser did not write source-dossier.json")
    validate_source_dossier_file(dossier_path, log_dir / "source-dossier-contract.txt")
    dossier = read_json(dossier_path)
    add_source_warnings(task, dossier, journey)
    runtime_library = write_runtime_library(input_dir, dossier, sources)
    report_path = parser_dir / "SOURCE_DOSSIER.md"
    if report_path.exists():
        shutil.copy2(report_path, Path(runtime_library["path"]) / "SOURCE_DOSSIER.md")

    enriched_request = copy.deepcopy(request)
    enriched_request["brief"] = attach_source_dossier_to_brief(brief, dossier, runtime_library)
    enriched_request["source_dossier"] = dossier
    enriched_request["runtime_library"] = runtime_library
    task["source_dossier"] = {
        "sources": len(sources),
        "knowledge_items": len(dossier.get("knowledge_layer") or []),
        "material_items": len(dossier.get("material_layer") or []),
        "slide_items": len(dossier.get("slide_layer") or []),
        "runtime_library": runtime_library["path"],
    }
    if task.get("source") == "brief":
        task["source"] = "materials+brief"
    append_journey_event(
        journey,
        "upload_parsed",
        "system",
        "已调用 upload-parser,并在本轮 run 内创建 agent runtime 临时知识/素材库。",
        task["source_dossier"],
    )
    return enriched_request, dossier


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


def library_usage_summary(outline: dict[str, Any]) -> dict[str, Any]:
    knowledge_refs = outline.get("knowledge_refs") or []
    sources = {ref.get("source") for ref in knowledge_refs if isinstance(ref, dict)}
    if "feishu-base" in sources:
        return {
            "mode": "cloud",
            "message": "已优先使用云端知识库/素材库检索结果。",
            "needs_user_action": False,
        }
    if use_base_library():
        return {
            "mode": "local-fallback",
            "message": "已优先尝试云端知识库/素材库,但未命中或当前身份无权限;本轮使用本地缓存继续生成。",
            "needs_user_action": False,
        }
    return {
        "mode": "local-configured",
        "message": "当前配置为本地缓存模式,未访问云端知识库/素材库。",
        "needs_user_action": False,
    }


def outline_review_markdown(outline: dict[str, Any]) -> str:
    brief = outline.get("brief") or {}
    scene = outline.get("scene") or {}
    slides = (outline.get("outline") or {}).get("slides") or []
    library = library_usage_summary(outline)
    source_refs = outline.get("source_dossier_refs") if isinstance(outline.get("source_dossier_refs"), list) else []
    knowledge_refs = outline.get("knowledge_refs") if isinstance(outline.get("knowledge_refs"), list) else []
    source_labels: list[str] = []
    for ref in [*source_refs[:4], *knowledge_refs[:4]]:
        if not isinstance(ref, dict):
            continue
        label = str(ref.get("title") or ref.get("source") or ref.get("query") or ref.get("cache_path") or "").strip()
        if label and label not in source_labels:
            source_labels.append(label)
    lines = [
        f"# {brief.get('title', 'deck')} H5 Deck 设计方案",
        "",
        f"受众：{brief.get('audience', '')}",
        f"目标：{brief.get('objective', '')}",
        f"行业 / 场景：{scene.get('industry', '')} · {scene.get('business_moment', '')}",
        f"云端库状态：{library['message']}",
        "同步说明：确认时系统会把本文中的受控字段回写到 `input/outline.json`,再交给 renderer。请保留表格和 P1/P2 小节结构。",
    ]
    if source_labels:
        lines.append(f"来源线索：{'；'.join(source_labels[:6])}")
    lines.extend(
        [
            "",
            "## 叙事弧",
            "",
            (outline.get("outline") or {}).get("arc", ""),
            "",
            "## 逐页方案表",
            "",
            "| 页码 | Key | 角色 | 唯一重点 | Layout / Path | Hero | 密度预算 |",
            "|-|-|-|-|-|-|-|",
        ]
    )
    for index, slide in enumerate(slides, start=1):
        density = str(slide.get("density_budget") or density_budget_for_slide(slide)).replace("\n", " ")
        lines.append(
            "| "
            + " | ".join(
                [
                    str(index),
                    str(slide.get("key", "")),
                    str(slide.get("role", "")),
                    str(slide.get("message", "")),
                    f"`{layout_label(slide)}`",
                    "是" if slide.get("hero") else "否",
                    density,
                ]
            )
            + " |"
        )
    lines.extend(["", "## 页级设计 Spec", ""])
    for index, slide in enumerate(slides, start=1):
        spec = slide.get("design_spec") if isinstance(slide.get("design_spec"), dict) else design_spec_for_slide(slide)
        hierarchy = spec.get("q2_hierarchy") if isinstance(spec.get("q2_hierarchy"), dict) else {}
        lines.extend(
            [
                f"### P{index} {slide.get('title', '')}",
                "",
                f"- Q0：{spec.get('q0_role', '')}",
                f"- Q1：{spec.get('q1_memory', '')}",
                f"- Q2：A 档={hierarchy.get('a', '')}；B 档={hierarchy.get('b', '')}；C 档={hierarchy.get('c', '')}"
                + (f"；D 档={hierarchy.get('d', '')}" if hierarchy.get("d") else ""),
                f"- Q3：{spec.get('q3_mood', '')}",
                f"- Q4：{spec.get('q4_tradeoff', '')}",
            ]
        )
        dimensions = spec.get("six_dimensions") if isinstance(spec.get("six_dimensions"), list) else []
        if dimensions:
            lines.append("- 六维：" + "；".join(str(item) for item in dimensions))
        if slide.get("visual_intent"):
            lines.append(f"- 视觉意图：{slide.get('visual_intent')}")
        lines.append("")
    lines.extend(["## 内容补全计划", ""])
    for index, slide in enumerate(slides, start=1):
        lines.append(f"- P{index}：{slide.get('content_completion') or content_completion_for_slide(slide)}")
    lines.append("")
    lines.extend(["## 事实边界", ""])
    claim_discipline = outline.get("claim_discipline") if isinstance(outline.get("claim_discipline"), dict) else {}
    unsupported = text_items(claim_discipline.get("unsupported_claims"))
    confirmations = text_items(claim_discipline.get("needs_user_confirmation"))
    if unsupported:
        lines.append("- 不支持直接声称：" + "；".join(unsupported))
    if confirmations:
        lines.append("- 需要用户确认：" + "；".join(confirmations))
    for index, slide in enumerate(slides, start=1):
        boundary = slide.get("fact_boundary") or fact_boundary_for_slide(slide)
        lines.append(f"- P{index}：{boundary}")
    lines.append("")
    questions = outline.get("open_questions") or []
    if questions:
        lines.extend(["## 需要确认", ""])
        lines.extend(f"- {item}" for item in questions)
        lines.append("")
    lines.extend(
        [
            "## 下一步",
            "",
            "请确认这个大纲框架后再生成 deckhtml。确认后系统会渲染 H5、运行验收、生成 pitch 预演；成稿还会再等你确认后才入库。",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def clean_design_plan_value(value: str) -> str:
    text = value.strip()
    text = re.sub(r"^`(.+)`$", r"\1", text)
    text = re.sub(r"^\*\*(.+)\*\*$", r"\1", text)
    return html.unescape(text).strip()


def markdown_table_cells(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return []
    cells = [clean_design_plan_value(cell) for cell in stripped.strip("|").split("|")]
    if not cells or all(re.fullmatch(r":?-{1,}:?", cell.replace(" ", "")) for cell in cells):
        return []
    return cells


def parse_page_number(value: str) -> int | None:
    match = re.search(r"(\d+)", value)
    return int(match.group(1)) if match else None


def parse_design_plan_bool(value: str) -> bool | None:
    token = clean_design_plan_value(value).lower()
    if token in {"是", "yes", "y", "true", "1", "hero"}:
        return True
    if token in {"否", "no", "n", "false", "0", "普通"}:
        return False
    return None


def parse_layout_path(value: str) -> tuple[str, str | None] | None:
    text = clean_design_plan_value(value)
    if not text:
        return None
    parts = [part.strip() for part in text.split("/", 1)]
    layout = parts[0]
    if not layout:
        return None
    variant = parts[1] if len(parts) > 1 and parts[1] else None
    return layout, variant


def add_design_plan_change(changes: list[dict[str, str]], path: str, before: Any, after: Any) -> None:
    if before == after:
        return
    changes.append({"path": path, "before": str(before or ""), "after": str(after or "")})


def set_design_plan_field(target: dict[str, Any], key: str, value: Any, path: str, changes: list[dict[str, str]]) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return False
    before = target.get(key)
    if before == value:
        return False
    target[key] = value
    add_design_plan_change(changes, path, before, value)
    return True


def split_design_plan_items(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"\s*；\s*", value) if item.strip()]


def section_lines(lines: list[str], heading: str) -> list[str]:
    start: int | None = None
    for index, line in enumerate(lines):
        if line.strip() == f"## {heading}":
            start = index + 1
            break
    if start is None:
        return []
    end = len(lines)
    for index in range(start, len(lines)):
        if lines[index].startswith("## "):
            end = index
            break
    return lines[start:end]


def slide_by_index_or_key(slides: list[dict[str, Any]], page: int | None, key: str = "") -> tuple[int | None, dict[str, Any] | None]:
    if key:
        for index, slide in enumerate(slides):
            if str(slide.get("key") or "") == key:
                return index, slide
    if page is not None and 1 <= page <= len(slides):
        return page - 1, slides[page - 1]
    return None, None


def apply_design_plan_table(
    outline: dict[str, Any],
    lines: list[str],
    changes: list[dict[str, str]],
    warnings: list[str],
) -> set[int]:
    slides = (outline.get("outline") or {}).get("slides")
    if not isinstance(slides, list):
        return set()
    message_changed: set[int] = set()
    rows = section_lines(lines, "逐页方案表")
    for line in rows:
        cells = markdown_table_cells(line)
        if not cells or cells[0] in {"页码", "Page"}:
            continue
        page = parse_page_number(cells[0])
        has_key_column = len(cells) >= 7
        key = cells[1] if has_key_column else ""
        role_i, message_i, layout_i, hero_i, density_i = (2, 3, 4, 5, 6) if has_key_column else (1, 2, 3, 4, 5)
        slide_index, slide = slide_by_index_or_key(slides, page, key if has_key_column else "")
        if slide is None or slide_index is None:
            warnings.append(f"无法匹配逐页方案表行: {line.strip()}")
            continue
        if role_i < len(cells):
            set_design_plan_field(slide, "role", cells[role_i], f"outline.slides[{slide_index}].role", changes)
        if message_i < len(cells):
            if set_design_plan_field(slide, "message", cells[message_i], f"outline.slides[{slide_index}].message", changes):
                message_changed.add(slide_index)
        if layout_i < len(cells):
            parsed_layout = parse_layout_path(cells[layout_i])
            if parsed_layout:
                layout, variant = parsed_layout
                candidate = slide.setdefault("layout_candidate", {})
                if isinstance(candidate, dict):
                    set_design_plan_field(candidate, "layout", layout, f"outline.slides[{slide_index}].layout_candidate.layout", changes)
                    if variant:
                        set_design_plan_field(candidate, "variant", variant, f"outline.slides[{slide_index}].layout_candidate.variant", changes)
                    elif "variant" in candidate:
                        before = candidate.pop("variant")
                        add_design_plan_change(changes, f"outline.slides[{slide_index}].layout_candidate.variant", before, "")
        if hero_i < len(cells):
            hero = parse_design_plan_bool(cells[hero_i])
            if hero is not None:
                set_design_plan_field(slide, "hero", hero, f"outline.slides[{slide_index}].hero", changes)
        if density_i < len(cells):
            set_design_plan_field(slide, "density_budget", cells[density_i], f"outline.slides[{slide_index}].density_budget", changes)
    return message_changed


def apply_design_plan_specs(
    outline: dict[str, Any],
    lines: list[str],
    changes: list[dict[str, str]],
    warnings: list[str],
    message_changed: set[int],
) -> None:
    slides = (outline.get("outline") or {}).get("slides")
    if not isinstance(slides, list):
        return
    spec_lines = section_lines(lines, "页级设计 Spec")
    current_index: int | None = None
    for raw in spec_lines:
        line = raw.strip()
        header = re.match(r"^###\s+P(\d+)\s+(.+?)\s*$", line)
        if header:
            page = int(header.group(1))
            slide_index, slide = slide_by_index_or_key(slides, page)
            current_index = slide_index
            if slide is None or slide_index is None:
                warnings.append(f"无法匹配页级设计小节: {line}")
                continue
            set_design_plan_field(slide, "title", clean_design_plan_value(header.group(2)), f"outline.slides[{slide_index}].title", changes)
            continue
        if current_index is None or current_index >= len(slides):
            continue
        slide = slides[current_index]
        spec = slide.setdefault("design_spec", {})
        if not isinstance(spec, dict):
            spec = {}
            slide["design_spec"] = spec
        body = re.sub(r"^-\s*", "", line)
        for label, key in [("Q0", "q0_role"), ("Q1", "q1_memory"), ("Q3", "q3_mood"), ("Q4", "q4_tradeoff")]:
            prefix = f"{label}："
            if body.startswith(prefix):
                value = clean_design_plan_value(body[len(prefix):])
                changed = set_design_plan_field(spec, key, value, f"outline.slides[{current_index}].design_spec.{key}", changes)
                if label == "Q1" and changed:
                    set_design_plan_field(slide, "key_idea", value, f"outline.slides[{current_index}].key_idea", changes)
                    if current_index not in message_changed:
                        set_design_plan_field(slide, "message", value, f"outline.slides[{current_index}].message", changes)
                break
        if body.startswith("Q2："):
            hierarchy = spec.setdefault("q2_hierarchy", {})
            if not isinstance(hierarchy, dict):
                hierarchy = {}
                spec["q2_hierarchy"] = hierarchy
            rest = body[len("Q2："):]
            for item in split_design_plan_items(rest):
                match = re.match(r"([ABCDabcd])\s*档\s*=\s*(.+)", item)
                if not match:
                    continue
                tier = match.group(1).lower()
                value = clean_design_plan_value(match.group(2))
                set_design_plan_field(hierarchy, tier, value, f"outline.slides[{current_index}].design_spec.q2_hierarchy.{tier}", changes)
        elif body.startswith("六维："):
            dims = split_design_plan_items(body[len("六维："):])
            if dims:
                before = spec.get("six_dimensions")
                if before != dims:
                    spec["six_dimensions"] = dims
                    add_design_plan_change(changes, f"outline.slides[{current_index}].design_spec.six_dimensions", before, dims)
        elif body.startswith("视觉意图："):
            value = clean_design_plan_value(body[len("视觉意图："):])
            set_design_plan_field(slide, "visual_intent", value, f"outline.slides[{current_index}].visual_intent", changes)


def apply_design_plan_list_section(
    outline: dict[str, Any],
    lines: list[str],
    heading: str,
    target_key: str,
    changes: list[dict[str, str]],
    warnings: list[str],
) -> None:
    slides = (outline.get("outline") or {}).get("slides")
    if not isinstance(slides, list):
        return
    for raw in section_lines(lines, heading):
        line = raw.strip()
        match = re.match(r"^-\s*P(\d+)\s*[：:]\s*(.+?)\s*$", line)
        if not match:
            continue
        page = int(match.group(1))
        slide_index, slide = slide_by_index_or_key(slides, page)
        if slide is None or slide_index is None:
            warnings.append(f"无法匹配{heading}行: {line}")
            continue
        value = clean_design_plan_value(match.group(2))
        changed = set_design_plan_field(slide, target_key, value, f"outline.slides[{slide_index}].{target_key}", changes)
        if target_key == "fact_boundary" and changed:
            before = slide.get("risk")
            risk = [value]
            if before != risk:
                slide["risk"] = risk
                add_design_plan_change(changes, f"outline.slides[{slide_index}].risk", before, risk)


def apply_design_plan_claims(outline: dict[str, Any], lines: list[str], changes: list[dict[str, str]]) -> None:
    claim_discipline = outline.setdefault("claim_discipline", {})
    if not isinstance(claim_discipline, dict):
        claim_discipline = {}
        outline["claim_discipline"] = claim_discipline
    questions: list[str] = []
    in_questions = False
    for raw in lines:
        line = raw.strip()
        if line == "## 需要确认":
            in_questions = True
            continue
        if line.startswith("## ") and line != "## 需要确认":
            in_questions = False
        if line.startswith("- 不支持直接声称："):
            value = split_design_plan_items(line[len("- 不支持直接声称："):])
            before = claim_discipline.get("unsupported_claims")
            if before != value:
                claim_discipline["unsupported_claims"] = value
                add_design_plan_change(changes, "claim_discipline.unsupported_claims", before, value)
        elif line.startswith("- 需要用户确认："):
            value = split_design_plan_items(line[len("- 需要用户确认："):])
            before = claim_discipline.get("needs_user_confirmation")
            if before != value:
                claim_discipline["needs_user_confirmation"] = value
                add_design_plan_change(changes, "claim_discipline.needs_user_confirmation", before, value)
        elif in_questions and line.startswith("- "):
            item = clean_design_plan_value(line[2:])
            if item:
                questions.append(item)
    if questions:
        before = outline.get("open_questions")
        if before != questions:
            outline["open_questions"] = questions
            add_design_plan_change(changes, "open_questions", before, questions)


def apply_design_plan_markdown(outline: dict[str, Any], design_plan_text: str) -> tuple[dict[str, Any], dict[str, Any]]:
    updated = copy.deepcopy(outline)
    lines = design_plan_text.splitlines()
    changes: list[dict[str, str]] = []
    warnings: list[str] = []
    brief = updated.setdefault("brief", {})
    scene = updated.setdefault("scene", {})
    plan = updated.setdefault("outline", {})

    for raw in lines:
        line = raw.strip()
        if line.startswith("# ") and line.endswith(" H5 Deck 设计方案"):
            title = line[2: -len(" H5 Deck 设计方案")].strip()
            set_design_plan_field(brief, "title", title, "brief.title", changes)
        elif line.startswith("受众："):
            set_design_plan_field(brief, "audience", line[len("受众："):], "brief.audience", changes)
        elif line.startswith("目标："):
            set_design_plan_field(brief, "objective", line[len("目标："):], "brief.objective", changes)
        elif line.startswith("行业 / 场景："):
            rest = line[len("行业 / 场景："):]
            parts = [part.strip() for part in rest.split("·", 1)]
            if parts:
                set_design_plan_field(scene, "industry", parts[0], "scene.industry", changes)
            if len(parts) > 1:
                set_design_plan_field(scene, "business_moment", parts[1], "scene.business_moment", changes)

    arc = "\n".join(line.strip() for line in section_lines(lines, "叙事弧") if line.strip())
    if arc:
        set_design_plan_field(plan, "arc", arc, "outline.arc", changes)

    message_changed = apply_design_plan_table(updated, lines, changes, warnings)
    apply_design_plan_specs(updated, lines, changes, warnings, message_changed)
    apply_design_plan_list_section(updated, lines, "内容补全计划", "content_completion", changes, warnings)
    apply_design_plan_list_section(updated, lines, "事实边界", "fact_boundary", changes, warnings)
    apply_design_plan_claims(updated, lines, changes)

    return updated, {
        "checked": True,
        "change_count": len(changes),
        "changes": changes,
        "warnings": warnings,
    }


def design_plan_sync_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Design Plan Sync",
        "",
        f"- checked: {report.get('checked', False)}",
        f"- changes: {report.get('change_count', 0)}",
    ]
    warnings = report.get("warnings") if isinstance(report.get("warnings"), list) else []
    if warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {item}" for item in warnings)
    changes = report.get("changes") if isinstance(report.get("changes"), list) else []
    if changes:
        lines.extend(["", "## Applied Changes", ""])
        for item in changes[:80]:
            lines.append(f"- `{item.get('path')}`: {item.get('before')} -> {item.get('after')}")
    return "\n".join(lines).strip() + "\n"


def sync_design_plan_to_outline(task_id: str, outline: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    task_dir = RUNS_DIR / task_id
    design_plan_path = task_dir / "output" / "DESIGN_PLAN.md"
    if not design_plan_path.exists():
        return outline, {"checked": False, "change_count": 0, "changes": [], "warnings": ["DESIGN_PLAN.md not found"]}
    updated, report = apply_design_plan_markdown(outline, design_plan_path.read_text(encoding="utf-8"))
    write_json(task_dir / "input" / "design-plan-sync.json", report)
    (task_dir / "output" / "DESIGN_PLAN_SYNC.md").write_text(design_plan_sync_markdown(report), encoding="utf-8")
    return updated, report


STANDARD_OUTLINE_LAYOUTS = {
    "cover",
    "agenda",
    "section",
    "content",
    "stats",
    "chart",
    "image-text",
    "table",
    "logo-wall",
    "arch-stack",
    "flow",
    "quote",
    "end",
}

STANDARD_OUTLINE_VARIANTS = {
    "content": {"3up", "2col", "blocks", "matrix", "before-after", "story-case"},
    "stats": {"row", "hero", "waterfall"},
    "chart": {"bar", "line", "donut"},
    "flow": {"timeline", "process", "tree", "swim"},
}

RISKY_OUTLINE_LAYOUTS = {"raw", "replica", "iframe-embed"}
RISKY_OUTLINE_TERMS = [
    "raw",
    "replica",
    "iframe",
    "iframe-embed",
    "lifted",
    "foreign lift",
    "bespoke html",
    "custom html",
    "手写html",
    "手写 html",
    "自定义html",
    "自定义 html",
    "外部html",
    "外部 html",
    "原生拼接",
    "旧页复刻",
    "逐像素复刻",
]


def outline_slides(outline: dict[str, Any]) -> list[dict[str, Any]]:
    slides = (outline.get("outline") or {}).get("slides")
    return [slide for slide in slides if isinstance(slide, dict)] if isinstance(slides, list) else []


def outline_confirmation_reasons(outline: dict[str, Any], request: dict[str, Any]) -> list[str]:
    """Return reasons a design plan should pause before renderer handoff."""
    reasons: list[str] = []
    if request.get("plan_only") or request.get("require_outline_confirmation"):
        reasons.append("request explicitly asks for plan-only/outline confirmation")

    for index, slide in enumerate(outline_slides(outline), start=1):
        key = str(slide.get("key") or f"p{index}")
        candidate = slide.get("layout_candidate") if isinstance(slide.get("layout_candidate"), dict) else {}
        layout = str(candidate.get("layout") or slide.get("layout") or "").strip()
        variant = str(candidate.get("variant") or slide.get("variant") or "").strip()

        if layout in RISKY_OUTLINE_LAYOUTS:
            reasons.append(f"{key}: layout {layout} needs user confirmation before renderer")
        elif layout and layout not in STANDARD_OUTLINE_LAYOUTS:
            reasons.append(f"{key}: layout {layout} is outside the default renderer schema")
        elif variant and layout in STANDARD_OUTLINE_VARIANTS and variant not in STANDARD_OUTLINE_VARIANTS[layout]:
            reasons.append(f"{key}: variant {layout}/{variant} is outside the default renderer schema")

        for marker in ["requires_confirmation", "needs_confirmation", "requires_user_confirmation", "bespoke", "foreign_lift"]:
            if slide.get(marker) or candidate.get(marker):
                reasons.append(f"{key}: {marker} is set")
                break

        text_blob = " ".join(str(item).lower() for item in walk_text({
            "title": slide.get("title", ""),
            "visual_intent": slide.get("visual_intent", ""),
            "content_completion": slide.get("content_completion", ""),
            "layout_candidate": candidate,
        }))
        if any(term in text_blob for term in RISKY_OUTLINE_TERMS):
            reasons.append(f"{key}: design notes mention raw/replica/iframe/lift-style work")

    return reasons[:12]


def create_planned_or_run_task(
    request: dict[str, Any],
    *,
    task_id: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    """Create the design plan, then auto-handoff low-risk outlines to renderer."""
    task = create_outline_task(request, task_id=task_id, base_url=base_url)
    if task.get("status") != "awaiting_outline_confirmation":
        return task

    task_dir = RUNS_DIR / task["id"]
    outline_path = task_dir / "input" / "outline.json"
    outline = read_json(outline_path) if outline_path.exists() else {}
    reasons = outline_confirmation_reasons(outline, request)
    force = bool(request.get("auto_confirm_outline") and (
        not reasons or request.get("allow_skip_outline_confirmation")
    ))
    should_auto_handoff = not request.get("plan_only") and (not reasons or force)

    task["outline_confirmation_policy"] = {
        "auto_handoff": bool(should_auto_handoff),
        "reasons": reasons,
    }
    if reasons and not should_auto_handoff:
        task["confirmation_reasons"] = reasons
        save_task(task_dir, task)
        return task
    if reasons and force:
        task.setdefault("warnings", []).append(
            "outline contains risky renderer handoff signals but auto-confirm was explicitly allowed: "
            + "；".join(reasons)
        )
        save_task(task_dir, task)

    return confirm_outline_task(task["id"], base_url=base_url)


def output_artifacts(task_id: str, output_dir: Path, base_url: str | None = None) -> dict[str, str]:
    artifacts: dict[str, str] = {}
    root = base_url.rstrip("/") if base_url else ""
    for path in sorted(output_dir.iterdir()):
        if path.is_file():
            if path.name == "index.html" or path.suffix == ".zip" or path.name in HIDDEN_OUTPUT_ARTIFACTS:
                continue
            artifacts[path.name] = f"{root}/decks/{task_id}/files/{path.name}" if root else str(path)
    cloud_url = ""
    app_url = ""
    doc_url = ""
    cloud_path = output_dir / "cloud-publish.json"
    if cloud_path.exists():
        try:
            cloud = read_json(cloud_path)
            if cloud.get("ok"):
                app_url = str(cloud.get("app_url") or "")
                doc_url = str(cloud.get("doc_url") or "")
                cloud_url = app_url or doc_url
        except Exception:
            cloud_url = ""
    magic_doc_path = output_dir / "magic-doc-publish.json"
    if not cloud_url and magic_doc_path.exists():
        try:
            magic_doc = read_json(magic_doc_path)
            if magic_doc.get("ok") and magic_doc.get("doc_url"):
                doc_url = str(magic_doc["doc_url"])
                cloud_url = doc_url
        except Exception:
            cloud_url = ""
    if not cloud_url:
        legacy_magic_path = output_dir / "magic-publish.json"
        if legacy_magic_path.exists():
            try:
                legacy_magic = read_json(legacy_magic_path)
                if legacy_magic.get("ok") and legacy_magic.get("url"):
                    cloud_url = str(legacy_magic["url"])
            except Exception:
                cloud_url = ""
    if base_url:
        artifacts["status_url"] = f"{root}/decks/{task_id}/status"
        artifacts["editor_url"] = f"{root}/decks/{task_id}/edit"
    else:
        artifacts["status_url"] = ""
        artifacts["editor_url"] = ""
    artifacts["cloud_url"] = cloud_url
    artifacts["app_url"] = app_url
    artifacts["magic_page_url"] = app_url
    artifacts["magic_doc_url"] = doc_url
    artifacts["miaobi_doc_url"] = doc_url
    artifacts["doc_url"] = doc_url
    artifacts["magic_url"] = cloud_url
    artifacts["miaobi_url"] = cloud_url
    artifacts["preview_url"] = cloud_url
    artifacts["edit_url"] = artifacts.get("editor_url", "")
    artifacts["download_url"] = ""
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
    .awaiting_outline_confirmation, .awaiting_brief_clarification, .awaiting_rehearsal_decision, .awaiting_deck_confirmation, .visual_unverified {{ background: #eaf1ff; color: #1457d9; }}
    .completed_without_ingestion {{ background: #eef6f1; color: #236b3a; }}
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
        ("飞书妙笔页面", "magic_page_url"),
        ("云端发布入口", "cloud_url"),
        ("需求澄清", "BRIEF_CLARIFICATION.md"),
        ("设计确认稿", "DESIGN_PLAN.md"),
        ("素材落地报告", "ASSET_MATERIALIZATION.md"),
        ("验收报告", "AUDIT_REPORT.md"),
        ("Pitch 预演", "PITCH_REHEARSAL.md"),
        ("预演门禁", "REHEARSAL_GATE.md"),
        ("云端发布报告", "CLOUD_PUBLISH.md"),
        ("妙笔页面发布报告", "MAGIC_PAGE_PUBLISH.md"),
        ("legacy 妙笔文档发布报告", "MAGIC_DOC_PUBLISH.md"),
        ("最终解析", "FINAL_SOURCE_DOSSIER.md"),
        ("入库报告", "INGESTION_REPORT.md"),
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
    preferred = ["auditor", "auditor_inline", "render", "outline_validator", "package"]
    for key in preferred:
        path = logs.get(key)
        if path and Path(path).exists():
            text = Path(path).read_text(encoding="utf-8", errors="replace")
            return text[-max_chars:]
    return ""


def render_status_page(task_id: str) -> bytes:
    task = load_task(task_id)
    status = html.escape(str(task.get("status") or "unknown"))
    badge_class = status if status in {
        "succeeded",
        "failed",
        "running",
        "visual_unverified",
        "awaiting_brief_clarification",
        "awaiting_outline_confirmation",
        "awaiting_rehearsal_decision",
        "awaiting_deck_confirmation",
        "completed_without_ingestion",
    } else "running"
    logs = task.get("logs") or {}
    log_rows = "".join(
        f"<li><code>{html.escape(name)}</code>: {html.escape(str(path))}</li>"
        for name, path in sorted(logs.items())
    )
    error = task.get("error")
    output_dir = Path(task.get("output_dir", ""))
    report_text = ""
    report = output_dir / "AUDIT_REPORT.md"
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
    deck_exists = (output_dir / "deck.json").exists()
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
    warning_rows = "".join(f"<li>{html.escape(str(item))}</li>" for item in (task.get("warnings") or []))
    confirmation_panel = ""
    if task.get("status") == "awaiting_outline_confirmation":
        design_plan = output_dir / "DESIGN_PLAN.md"
        outline_text = html.escape(design_plan.read_text(encoding="utf-8")[:18000]) if design_plan.exists() else ""
        confirmation_panel = f"""
<section class="panel">
  <h2>等待确认设计方案</h2>
  <p class="muted">planner 已输出当前框架与页级设计方案。确认后才会生成 deckhtml。</p>
  <div class="actions">
    <button type="button" onclick="confirmOutline()">确认方案并生成</button>
  </div>
  {f'<pre>{outline_text}</pre>' if outline_text else ''}
</section>
<script>
async function confirmOutline() {{
  const response = await fetch('/decks/{html.escape(task_id)}/confirm-outline', {{ method: 'POST' }});
  const body = await response.json();
  if (body.id) window.location.href = '/decks/' + body.id + '/status';
  else alert(JSON.stringify(body));
}}
</script>
"""
    elif task.get("status") == "awaiting_rehearsal_decision":
        rehearsal = output_dir / "PITCH_REHEARSAL.md"
        rehearsal_text = html.escape(rehearsal.read_text(encoding="utf-8")[:14000]) if rehearsal.exists() else ""
        confirmation_panel = f"""
<section class="panel">
  <h2>等待确认预演</h2>
  <p class="muted">deckhtml 已生成并完成 pitch simulator 预演。你可以按反馈回到规划确认环节,也可以暂不修改;暂不修改后才会发布云端页面并进入入库确认。</p>
  <div class="actions">
    <button type="button" onclick="acceptRehearsal()">不用修改,进入入库确认</button>
    <button class="secondary" type="button" onclick="reviseFromRehearsal()">按预演反馈重做大纲</button>
  </div>
  {f'<pre>{rehearsal_text}</pre>' if rehearsal_text else ''}
</section>
<script>
async function acceptRehearsal() {{
  const response = await fetch('/decks/{html.escape(task_id)}/accept-rehearsal', {{ method: 'POST' }});
  const body = await response.json();
  if (body.id) window.location.href = '/decks/' + body.id + '/status';
  else alert(JSON.stringify(body));
}}
async function reviseFromRehearsal() {{
  const response = await fetch('/decks/{html.escape(task_id)}/revise-from-rehearsal', {{ method: 'POST' }});
  const body = await response.json();
  if (body.id) window.location.href = '/decks/' + body.id + '/status';
  else alert(JSON.stringify(body));
}}
</script>
"""
    elif task.get("status") == "awaiting_deck_confirmation":
        confirmation_panel = f"""
<section class="panel">
  <h2>等待确认入库</h2>
  <p class="muted">当前成稿已通过预演确认,并已发布到妙笔。确认入库后会使用已发布的妙笔 deckhtml,再调用解析器丰富知识/素材,并优先写入云端知识库和素材库;若当前 user 身份无权限,会明文记录并落到本地候选库。</p>
  <div class="actions">
    <button type="button" onclick="confirmDeck()">确认入库</button>
    <button class="secondary" type="button" onclick="skipIngest()">不入库,结束</button>
  </div>
</section>
<script>
async function confirmDeck() {{
  const response = await fetch('/decks/{html.escape(task_id)}/confirm-deck', {{ method: 'POST' }});
  const body = await response.json();
  if (body.id) window.location.href = '/decks/' + body.id + '/status';
  else alert(JSON.stringify(body));
}}
async function skipIngest() {{
  const response = await fetch('/decks/{html.escape(task_id)}/skip-ingest', {{ method: 'POST' }});
  const body = await response.json();
  if (body.id) window.location.href = '/decks/' + body.id + '/status';
  else alert(JSON.stringify(body));
}}
</script>
"""
    body = f"""
<section class="panel">
  <div class="grid">
    <div class="metric"><div class="label">Task</div><div class="value"><code>{html.escape(task_id)}</code></div></div>
    <div class="metric"><div class="label">Status</div><div class="value"><span class="badge {badge_class}">{status}</span></div></div>
    <div class="metric"><div class="label">Source</div><div class="value">{html.escape(str(task.get("source", "")))}</div></div>
    <div class="metric"><div class="label">Updated</div><div class="value">{html.escape(str(task.get("updated_at", "")))}</div></div>
  </div>
  {f'<h2>失败原因</h2><pre>{html.escape(str(error))}</pre>' if error else ''}
  {f'<h2>提示</h2><ul>{warning_rows}</ul>' if warning_rows else ''}
</section>
{confirmation_panel}
<section class="panel">
  <h2>产物</h2>
  {artifact_links(task)}
  <div class="actions">
    {f'<a href="/decks/{html.escape(task_id)}/edit"><button>打开轻量编辑</button></a>' if deck_exists else ''}
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
{f'<section class="panel"><h2>验收报告</h2><pre>{report_text}</pre></section>' if report_text else ''}
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
    if new_task.get("status") in {"succeeded", "awaiting_rehearsal_decision", "awaiting_deck_confirmation"}:
        append_journey_event(journey, "edited_result_ready", "system", "精调后的新版本已可预览、编辑、预演和下载。")
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
        require_deck_confirmation=True,
    )
    new_task_dir = RUNS_DIR / new_task_id
    write_json(new_task_dir / "input" / "edit.json", payload)
    new_task["parent_task_id"] = task_id
    new_task["version"] = version
    new_task["edit_source"] = "deck_json"
    update_edit_journey(task, new_task, payload, source_deck, edited_deck, diff, client_events)
    save_task(new_task_dir, new_task)
    return new_task


def create_outline_task(
    request: dict[str, Any],
    *,
    task_id: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    brief = request.get("brief") or {}
    if not isinstance(brief, dict):
        raise ValueError("request.brief must be an object when provided")
    source = "outline" if request.get("outline") else "brief"
    title_source = brief_value(brief, "customer_name", "title", "brief", default="deck")
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
        "warnings": [],
        "confirmation_required": "outline",
    }
    save_task(task_dir, task)
    write_json(input_dir / "request.raw.json", request)
    journey = new_journey(task, request, source)

    try:
        request, _dossier = run_upload_parser(
            request,
            task_id=task_id,
            input_dir=input_dir,
            output_dir=output_dir,
            log_dir=log_dir,
            journey=journey,
            task=task,
        )
        brief = request.get("brief") or {}
        write_json(input_dir / "request.json", request)
        missing_critical = critical_brief_questions(brief)
        if missing_critical and require_brief_clarification(request) and not request.get("allow_assumptions"):
            task["status"] = "awaiting_brief_clarification"
            task["confirmation_required"] = "brief"
            task["brief_questions"] = missing_critical
            (output_dir / "BRIEF_CLARIFICATION.md").write_text(
                "# Brief Clarification\n\n"
                + "\n".join(f"- {item}" for item in missing_critical)
                + "\n",
                encoding="utf-8",
            )
            task["artifacts"].update(output_artifacts(task_id, output_dir, base_url=base_url))
            append_journey_event(
                journey,
                "awaiting_brief_clarification",
                "system",
                "缺少关键 pitch 背景,已暂停在 planner 前等待用户补充。",
                {"questions": missing_critical},
            )
            write_journey_artifacts(output_dir, journey)
            save_task(task_dir, task)
            return task
        if missing_critical:
            task.setdefault("warnings", []).append(
                "缺少关键 pitch 背景,已按合理假设继续: " + "；".join(missing_critical)
            )
            append_journey_event(
                journey,
                "brief_assumptions_recorded",
                "system",
                "缺少部分 pitch 背景,未阻塞流程;问题已进入 outline 的 open questions。",
                {"questions": missing_critical},
            )
        if request.get("outline"):
            outline = request["outline"]
            append_journey_event(journey, "outline_loaded", "system", "使用请求中提供的 outline,等待用户确认。")
        else:
            outline = brief_to_outline(brief)
            append_journey_event(
                journey,
                "outline_created",
                "system",
                "根据 brief 生成 outline,在渲染前暂停等待用户确认。",
                {"open_questions": len(outline.get("open_questions") or [])},
            )
        write_json(input_dir / "outline.json", outline)
        (output_dir / "DESIGN_PLAN.md").write_text(outline_review_markdown(outline), encoding="utf-8")

        outline_log = log_dir / "outline-validator.txt"
        proc = run_command(["python3", str(OUTLINE_VALIDATOR), str(input_dir / "outline.json")], outline_log)
        task["logs"]["outline_validator"] = str(outline_log)
        if proc.returncode != 0:
            append_journey_event(journey, "outline_validation_failed", "system", "outline validator 未通过。", {"exit": proc.returncode})
            raise RuntimeError("outline validation failed")
        append_journey_event(journey, "outline_validated", "system", "outline validator 通过。")

        library = library_usage_summary(outline)
        task["library"] = library
        if library["mode"] != "cloud":
            task["warnings"].append(library["message"])
        task["status"] = "awaiting_outline_confirmation"
        task["artifacts"].update(output_artifacts(task_id, output_dir, base_url=base_url))
        append_journey_event(journey, "awaiting_outline_confirmation", "system", "已暂停在 planner 后,等待用户确认大纲框架。")
    except Exception as exc:  # noqa: BLE001
        task["status"] = "failed"
        task["error"] = str(exc)
        task["artifacts"].update(output_artifacts(task_id, output_dir, base_url=base_url))
        append_journey_event(journey, "task_failed", "system", "大纲任务失败。", {"error": str(exc)})
        if not (input_dir / "request.json").exists():
            write_json(input_dir / "request.json", request)
    try:
        write_journey_artifacts(output_dir, journey)
    except Exception:
        pass
    save_task(task_dir, task)
    return task


def confirm_outline_task(task_id: str, *, base_url: str | None = None) -> dict[str, Any]:
    task = load_task(task_id)
    request_path = RUNS_DIR / task_id / "input" / "request.json"
    outline_path = RUNS_DIR / task_id / "input" / "outline.json"
    if not request_path.exists() or not outline_path.exists():
        raise FileNotFoundError(f"outline task not found: {task_id}")
    request = read_json(request_path)
    outline, sync_report = sync_design_plan_to_outline(task_id, read_json(outline_path))
    write_json(outline_path, outline)
    request["outline"] = outline
    request["outline_confirmed"] = True
    request["deck_confirmation_required"] = True
    return create_or_run_task(
        request,
        task_id=task_id,
        base_url=base_url,
        metadata={
            "outline_confirmed": True,
            "confirmation_history": [
                {
                    "stage": "outline",
                    "confirmed_at": now_iso(),
                    "previous_status": task.get("status", ""),
                }
            ],
            "design_plan_sync": {
                "checked": sync_report.get("checked", False),
                "change_count": sync_report.get("change_count", 0),
                "warnings": sync_report.get("warnings", []),
            },
        },
        require_deck_confirmation=True,
    )


def build_ingest_metadata(task: dict[str, Any]) -> dict[str, Any]:
    input_dir = Path(task.get("input_dir", ""))
    request = read_json(input_dir / "request.json") if (input_dir / "request.json").exists() else {}
    brief = request.get("brief") if isinstance(request.get("brief"), dict) else {}
    outline = read_json(input_dir / "outline.json") if (input_dir / "outline.json").exists() else {}
    scene = outline.get("scene") or {}
    title = brief_value(brief, "title", "customer_name", default=(outline.get("brief") or {}).get("title", "deck"))
    return {
        "title": title,
        "industry": normalize_list(brief.get("industry") or scene.get("industry")) or ["待标注"],
        "product": normalize_list(brief.get("product_scope")) or ["飞书"],
        "deck_type": normalize_list(brief.get("deck_type")) or ["客户pitch"],
        "source_level": "internal-draft",
        "permission_status": "needs_review",
        "contributor": str(task.get("created_by") or base_identity() or "gtm"),
        "contributed_at": now_iso(),
    }


def normalize_magic_base_url(value: str | None) -> str:
    raw = str(value or DEFAULT_MAGIC_BASE_URL).strip().rstrip("/")
    if not raw:
        raw = DEFAULT_MAGIC_BASE_URL
    return raw if raw.startswith(("http://", "https://")) else f"https://{raw}"


def request_publish_target(request: dict[str, Any]) -> str:
    delivery = request.get("delivery") if isinstance(request.get("delivery"), dict) else {}
    raw = (
        request.get("publish_target")
        or request.get("cloud_target")
        or delivery.get("publish_target")
        or delivery.get("cloud_target")
        or delivery.get("target")
        or default_publish_target()
    )
    target = str(raw).strip().lower()
    return target if target in {"magic-page", "magic-doc", "none"} else "magic-page"


def write_cloud_publish_report(output_dir: Path, payload: dict[str, Any]) -> None:
    write_json(output_dir / "cloud-publish.json", payload)
    url = payload.get("app_url") or payload.get("doc_url") or ""
    lines = [
        "# Cloud Publish",
        "",
        f"- target: {payload.get('target')}",
        f"- enabled: {payload.get('enabled')}",
        f"- ok: {payload.get('ok')}",
        f"- dry_run: {payload.get('dry_run')}",
        f"- url: {url}",
        f"- app_url: {payload.get('app_url') or ''}",
        f"- doc_url: {payload.get('doc_url') or ''}",
        f"- app_id: {payload.get('app_id') or ''}",
        f"- reason: {payload.get('reason') or ''}",
        "",
    ]
    (output_dir / "CLOUD_PUBLISH.md").write_text("\n".join(lines), encoding="utf-8")


def write_pending_cloud_publish_report(output_dir: Path, request: dict[str, Any]) -> dict[str, Any]:
    target = request_publish_target(request)
    if target == "none":
        payload = {
            "target": "none",
            "enabled": False,
            "ok": True,
            "dry_run": False,
            "app_url": "",
            "doc_url": "",
            "app_id": "",
            "reason": "disabled",
        }
    else:
        payload = {
            "target": target,
            "enabled": False,
            "ok": False,
            "dry_run": False,
            "app_url": "",
            "doc_url": "",
            "app_id": "",
            "reason": "awaiting-rehearsal-confirmation",
        }
    write_cloud_publish_report(output_dir, payload)
    return payload


def cloud_publish_ready(output_dir: Path) -> bool:
    cloud_path = output_dir / "cloud-publish.json"
    if not cloud_path.exists():
        return False
    try:
        payload = read_json(cloud_path)
    except Exception:
        return False
    if payload.get("target") == "none" and payload.get("ok"):
        return True
    return bool(payload.get("enabled") and payload.get("ok") and (payload.get("app_url") or payload.get("doc_url")))


def magic_page_publish_config(request: dict[str, Any]) -> dict[str, Any]:
    magic = request.get("magic") if isinstance(request.get("magic"), dict) else {}
    magic_page = request.get("magic_page") if isinstance(request.get("magic_page"), dict) else {}
    delivery = request.get("delivery") if isinstance(request.get("delivery"), dict) else {}
    delivery_magic = delivery.get("magic") if isinstance(delivery.get("magic"), dict) else {}
    delivery_magic_page = delivery.get("magic_page") if isinstance(delivery.get("magic_page"), dict) else {}
    config = {**magic, **delivery_magic, **magic_page, **delivery_magic_page}
    return {
        "enabled": request_publish_target(request) == "magic-page" and str(config.get("enabled", "true")).lower() not in {"0", "false", "no"},
        "dry_run": magic_dry_run() or str(config.get("dry_run", "")).lower() in {"1", "true", "yes", "mock"},
        "script": str(config.get("script") or os.environ.get("CYRUS_MAGIC_PAGE_PUBLISHER") or DEFAULT_MAGIC_PAGE_PUBLISHER),
        "base_url": normalize_magic_base_url(str(config.get("base_url") or config.get("magic_base_url") or os.environ.get("MAGIC_BASE_URL") or "")),
        "open_source": str(config.get("open_source", "")).lower() in {"1", "true", "yes"},
    }


def parse_magic_page_stdout(stdout: str) -> dict[str, Any]:
    result: dict[str, Any] = {"app_url": "", "app_id": "", "urls": {}}
    urls: dict[str, str] = {}
    label_to_key = {
        "Independent Page": "html_box",
        "Dashboard Plugin": "dashboard",
        "Feishu Sidebar": "panel",
        "Feishu Tab": "tab",
    }
    for line in stdout.splitlines():
        if ":" not in line:
            continue
        label, value = line.split(":", 1)
        label = label.strip()
        value = value.strip()
        if not value:
            continue
        if label == "App ID":
            result["app_id"] = value
        elif label in label_to_key:
            urls[label_to_key[label]] = value
            if label == "Independent Page":
                result["app_url"] = value
    result["urls"] = urls
    return result


def write_magic_page_publish_report(output_dir: Path, payload: dict[str, Any]) -> None:
    write_json(output_dir / "magic-page-publish.json", payload)
    lines = [
        "# Feishu/Miaobi Magic Page Publish",
        "",
        f"- enabled: {payload.get('enabled')}",
        f"- ok: {payload.get('ok')}",
        f"- dry_run: {payload.get('dry_run')}",
        f"- app_url: {payload.get('app_url') or ''}",
        f"- app_id: {payload.get('app_id') or ''}",
        f"- base_url: {payload.get('base_url') or ''}",
        f"- reason: {payload.get('reason') or ''}",
        "",
    ]
    (output_dir / "MAGIC_PAGE_PUBLISH.md").write_text("\n".join(lines), encoding="utf-8")


def publish_deck_to_magic_page(task: dict[str, Any], request: dict[str, Any], deck: dict[str, Any], *, log_dir: Path) -> dict[str, Any]:
    output_dir = Path(task.get("output_dir", ""))
    config = magic_page_publish_config(request)
    title = ((deck.get("deck") or {}).get("title") or (request.get("brief") or {}).get("title") or str(task.get("id") or "deck")).strip()
    if not config["enabled"]:
        payload = {"target": "magic-page", "enabled": False, "ok": False, "dry_run": False, "app_url": "", "doc_url": "", "app_id": "", "reason": "disabled"}
        write_magic_page_publish_report(output_dir, payload)
        return payload

    if config["dry_run"]:
        token = "dryrun-" + hashlib.sha1(f"{task.get('id')}:{title}".encode("utf-8")).hexdigest()[:16]
        payload = {
            "target": "magic-page",
            "enabled": True,
            "ok": True,
            "dry_run": True,
            "app_url": f"{config['base_url']}/dryrun/{token}",
            "doc_url": "",
            "app_id": token,
            "base_url": config["base_url"],
            "reason": "dry-run",
        }
        write_magic_page_publish_report(output_dir, payload)
        return payload

    script = Path(config["script"])
    html_path = output_dir / "index.html"
    if not script.exists():
        payload = {"target": "magic-page", "enabled": True, "ok": False, "dry_run": False, "app_url": "", "doc_url": "", "app_id": "", "base_url": config["base_url"], "reason": f"Magic Page publisher not found: {script}"}
        write_magic_page_publish_report(output_dir, payload)
        return payload

    cmd = ["node", str(script), "publish", str(html_path), "--title", title, "--base-url", config["base_url"]]
    if config["open_source"]:
        cmd.append("--open-source")
    log = log_dir / "magic-page-publish.txt"
    proc = run_command(cmd, log)
    task.setdefault("logs", {})["magic_page_publish"] = str(log)
    parsed = parse_magic_page_stdout(proc.stdout)
    ok = proc.returncode == 0 and bool(parsed["app_url"])
    payload = {
        "target": "magic-page",
        "enabled": True,
        "ok": ok,
        "dry_run": False,
        "app_url": parsed["app_url"],
        "doc_url": "",
        "app_id": parsed["app_id"],
        "base_url": config["base_url"],
        "urls": parsed["urls"],
        "reason": "" if ok else (proc.stderr.strip() or proc.stdout.strip() or "publish failed"),
    }
    write_magic_page_publish_report(output_dir, payload)
    return payload


def magic_doc_publish_config(request: dict[str, Any]) -> dict[str, Any]:
    magic = request.get("magic") if isinstance(request.get("magic"), dict) else {}
    magic_doc = request.get("magic_doc") if isinstance(request.get("magic_doc"), dict) else {}
    delivery = request.get("delivery") if isinstance(request.get("delivery"), dict) else {}
    delivery_magic = delivery.get("magic") if isinstance(delivery.get("magic"), dict) else {}
    delivery_magic_doc = delivery.get("magic_doc") if isinstance(delivery.get("magic_doc"), dict) else {}
    config = {**magic, **delivery_magic, **magic_doc, **delivery_magic_doc}
    return {
        "enabled": request_publish_target(request) == "magic-doc" and publish_magic_enabled() and str(config.get("enabled", "true")).lower() not in {"0", "false", "no"},
        "dry_run": magic_dry_run() or str(config.get("dry_run", "")).lower() in {"1", "true", "yes", "mock"},
        "script": str(config.get("script") or os.environ.get("CYRUS_MAGIC_DOC_CREATOR") or DEFAULT_MAGIC_DOC_CREATOR),
        "doc_token": str(config.get("doc_token") or config.get("docToken") or os.environ.get("CYRUS_MAGIC_DOC_TOKEN") or ""),
        "identity": str(config.get("as") or config.get("identity") or os.environ.get("CYRUS_MAGIC_DOC_AS") or "user"),
        "summary": str(config.get("summary") or ""),
    }


def parse_magic_doc_stdout(stdout: str) -> dict[str, str]:
    try:
        data = json.loads(stdout)
        return {
            "doc_url": str(data.get("doc_url") or ""),
            "doc_token": str(data.get("doc_token") or ""),
            "html_box_block_id": str(data.get("html_box_block_id") or ""),
            "identity": str(data.get("identity") or ""),
        }
    except Exception:
        match = re.search(r"https?://\S+", stdout)
        return {"doc_url": match.group(0).rstrip() if match else "", "doc_token": "", "html_box_block_id": "", "identity": ""}


def write_magic_doc_publish_report(output_dir: Path, payload: dict[str, Any]) -> None:
    write_json(output_dir / "magic-doc-publish.json", payload)
    lines = [
        "# Feishu Magic Doc Publish",
        "",
        f"- enabled: {payload.get('enabled')}",
        f"- ok: {payload.get('ok')}",
        f"- dry_run: {payload.get('dry_run')}",
        f"- doc_url: {payload.get('doc_url') or ''}",
        f"- doc_token: {payload.get('doc_token') or ''}",
        f"- html_box_block_id: {payload.get('html_box_block_id') or ''}",
        f"- identity: {payload.get('identity') or ''}",
        f"- reason: {payload.get('reason') or ''}",
        "",
    ]
    (output_dir / "MAGIC_DOC_PUBLISH.md").write_text("\n".join(lines), encoding="utf-8")


def publish_deck_to_magic_doc(task: dict[str, Any], request: dict[str, Any], deck: dict[str, Any], *, log_dir: Path) -> dict[str, Any]:
    output_dir = Path(task.get("output_dir", ""))
    config = magic_doc_publish_config(request)
    title = ((deck.get("deck") or {}).get("title") or (request.get("brief") or {}).get("title") or str(task.get("id") or "deck")).strip()
    summary = config["summary"] or f"这是一份「{title}」HTML Deck,已直接嵌入飞书妙笔文档供在线查看。"
    if not config["enabled"]:
        payload = {"enabled": False, "ok": False, "dry_run": False, "doc_url": "", "doc_token": "", "html_box_block_id": "", "identity": "", "reason": "disabled"}
        write_magic_doc_publish_report(output_dir, payload)
        return payload

    if config["dry_run"]:
        token = "dryrun" + hashlib.sha1(f"{task.get('id')}:{title}".encode("utf-8")).hexdigest()[:16]
        payload = {
            "enabled": True,
            "ok": True,
            "dry_run": True,
            "doc_url": f"https://bytedance.larkoffice.com/docx/{token}",
            "doc_token": token,
            "html_box_block_id": "dryrun-html-box",
            "identity": config["identity"],
            "reason": "dry-run",
        }
        write_magic_doc_publish_report(output_dir, payload)
        return payload

    script = Path(config["script"])
    html_path = output_dir / "index.html"
    if not script.exists():
        payload = {"enabled": True, "ok": False, "dry_run": False, "doc_url": "", "doc_token": "", "html_box_block_id": "", "identity": config["identity"], "reason": f"Magic doc creator not found: {script}"}
        write_magic_doc_publish_report(output_dir, payload)
        return payload

    cmd = ["node", str(script), "--html", str(html_path)]
    if config["doc_token"]:
        cmd.extend(["--doc-token", config["doc_token"]])
    else:
        cmd.extend(["--title", title, "--summary", summary])
    if config["identity"]:
        cmd.extend(["--as", config["identity"]])
    log = log_dir / "magic-doc-publish.txt"
    proc = run_command(cmd, log)
    task.setdefault("logs", {})["magic_doc_publish"] = str(log)
    parsed = parse_magic_doc_stdout(proc.stdout)
    ok = proc.returncode == 0 and bool(parsed["doc_url"])
    payload = {
        "enabled": True,
        "ok": ok,
        "dry_run": False,
        "doc_url": parsed["doc_url"],
        "doc_token": parsed["doc_token"] or config["doc_token"],
        "html_box_block_id": parsed["html_box_block_id"],
        "identity": parsed["identity"] or config["identity"],
        "reason": "" if ok else (proc.stderr.strip() or proc.stdout.strip() or "publish failed"),
    }
    write_magic_doc_publish_report(output_dir, payload)
    return payload


def publish_deck_to_cloud(task: dict[str, Any], request: dict[str, Any], deck: dict[str, Any], *, log_dir: Path) -> dict[str, Any]:
    output_dir = Path(task.get("output_dir", ""))
    target = request_publish_target(request)
    if target == "none":
        payload = {"target": "none", "enabled": False, "ok": True, "dry_run": False, "app_url": "", "doc_url": "", "app_id": "", "reason": "disabled"}
        write_cloud_publish_report(output_dir, payload)
        return payload
    if target == "magic-doc":
        payload = publish_deck_to_magic_doc(task, request, deck, log_dir=log_dir)
        payload.setdefault("target", "magic-doc")
        payload.setdefault("app_url", "")
        payload.setdefault("app_id", "")
        write_cloud_publish_report(output_dir, payload)
        return payload
    payload = publish_deck_to_magic_page(task, request, deck, log_dir=log_dir)
    payload.setdefault("target", "magic-page")
    write_cloud_publish_report(output_dir, payload)
    return payload


def tos_upload_config(request: dict[str, Any]) -> dict[str, Any]:
    ingestion = request.get("ingestion") if isinstance(request.get("ingestion"), dict) else {}
    tos = request.get("tos") if isinstance(request.get("tos"), dict) else {}
    tos = {**tos, **(ingestion.get("tos") if isinstance(ingestion.get("tos"), dict) else {})}
    requested = bool(
        tos.get("enabled")
        or tos.get("upload")
        or request.get("upload_to_tos")
        or os.environ.get("CYRUS_UPLOAD_TOS", "").lower() in {"1", "true", "yes"}
    )
    return {
        "requested": requested,
        "key": str(tos.get("key") or os.environ.get("CYRUS_TOS_KEY") or ""),
        "base_url": str(tos.get("base_url") or tos.get("magic_base_url") or os.environ.get("MAGIC_BASE_URL") or ""),
        "script": str(tos.get("script") or os.environ.get("CYRUS_TOS_UPLOADER") or DEFAULT_TOS_UPLOADER),
    }


def write_tos_report(output_dir: Path, payload: dict[str, Any]) -> None:
    write_json(output_dir / "tos-upload.json", payload)
    lines = [
        "# TOS Upload",
        "",
        f"- requested: {payload.get('requested')}",
        f"- ok: {payload.get('ok')}",
        f"- url: {payload.get('url') or ''}",
        f"- reason: {payload.get('reason') or ''}",
        "",
    ]
    (output_dir / "TOS_UPLOAD.md").write_text("\n".join(lines), encoding="utf-8")


def upload_deck_to_tos(task: dict[str, Any], request: dict[str, Any], *, log_dir: Path) -> dict[str, Any]:
    output_dir = Path(task.get("output_dir", ""))
    config = tos_upload_config(request)
    if not config["requested"]:
        payload = {"requested": False, "ok": True, "url": "", "reason": "not-requested"}
        write_tos_report(output_dir, payload)
        return payload
    html_path = output_dir / "index.html"
    script = Path(config["script"])
    if not script.exists():
        payload = {
            "requested": True,
            "ok": False,
            "url": "",
            "reason": f"TOS uploader not found: {script}",
        }
        write_tos_report(output_dir, payload)
        return payload
    cmd = ["node", str(script), str(html_path), "-q"]
    if config["key"]:
        cmd.extend(["--key", config["key"]])
    if config["base_url"]:
        cmd.extend(["--base-url", config["base_url"]])
    log = log_dir / "tos-upload.txt"
    proc = run_command(cmd, log)
    task.setdefault("logs", {})["tos_upload"] = str(log)
    url = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    payload = {
        "requested": True,
        "ok": proc.returncode == 0 and bool(url),
        "url": url,
        "reason": "" if proc.returncode == 0 and url else (proc.stderr.strip() or proc.stdout.strip() or "upload failed"),
        "key": config["key"],
    }
    write_tos_report(output_dir, payload)
    return payload


def parse_final_deck_for_ingestion(task: dict[str, Any], *, log_dir: Path) -> dict[str, Any]:
    output_dir = Path(task.get("output_dir", ""))
    if not UPLOAD_PARSER.exists():
        return {"ok": False, "reason": f"upload parser missing: {UPLOAD_PARSER}"}
    html_path = output_dir / "index.html"
    if not html_path.exists():
        return {"ok": False, "reason": "index.html not found"}
    final_dir = output_dir / "ingestion-parser"
    log = log_dir / "ingestion-parser.txt"
    proc = run_command(
        [
            "python3",
            str(UPLOAD_PARSER),
            str(html_path),
            "--brief",
            "final deckhtml ingestion parse",
            "--output-dir",
            str(final_dir),
            "--task-id",
            str(task.get("id") or ""),
        ],
        log,
    )
    task.setdefault("logs", {})["ingestion_parser"] = str(log)
    if proc.returncode != 0:
        return {"ok": False, "reason": "final deck parser failed"}
    dossier_path = final_dir / "source-dossier.json"
    if not dossier_path.exists():
        return {"ok": False, "reason": "final deck parser did not write source-dossier.json"}
    try:
        validate_source_dossier_file(dossier_path, log_dir / "final-source-dossier-contract.txt")
    except RuntimeError as exc:
        return {"ok": False, "reason": str(exc)}
    report_path = final_dir / "SOURCE_DOSSIER.md"
    if dossier_path.exists():
        shutil.copy2(dossier_path, output_dir / "FINAL_SOURCE_DOSSIER.json")
    if report_path.exists():
        shutil.copy2(report_path, output_dir / "FINAL_SOURCE_DOSSIER.md")
    dossier = read_json(dossier_path) if dossier_path.exists() else {}
    return {
        "ok": True,
        "dossier": str(output_dir / "FINAL_SOURCE_DOSSIER.json"),
        "knowledge_items": len(dossier.get("knowledge_layer") or []),
        "material_items": len(dossier.get("material_layer") or []),
        "slide_items": len(dossier.get("slide_layer") or []),
    }


def ingest_confirmed_deck(task: dict[str, Any], *, base_url: str | None = None) -> dict[str, Any]:
    task_id = str(task["id"])
    task_dir = RUNS_DIR / task_id
    output_dir = Path(task["output_dir"])
    log_dir = task_dir / "logs"
    request_path = task_dir / "input" / "request.json"
    request = read_json(request_path) if request_path.exists() else {}
    metadata = build_ingest_metadata(task)
    task.setdefault("ingestion", {})
    parser_result = parse_final_deck_for_ingestion(task, log_dir=log_dir)
    task["ingestion"]["final_deck_parser"] = parser_result
    if not parser_result.get("ok"):
        task.setdefault("warnings", []).append(f"最终 deckhtml 解析器未能完成: {parser_result.get('reason')}")
    tos_result = upload_deck_to_tos(task, request, log_dir=log_dir)
    task["ingestion"]["tos_upload"] = tos_result
    if tos_result.get("requested") and not tos_result.get("ok"):
        task.setdefault("warnings", []).append(f"TOS 上传失败或未配置,继续执行知识库/素材库入库: {tos_result.get('reason')}")
    base_cmd = [
        "python3",
        str(DECK_INGESTOR),
        "--task-id",
        task_id,
        "--title",
        metadata["title"],
        "--source-level",
        metadata["source_level"],
        "--permission-status",
        metadata["permission_status"],
        "--contributor",
        metadata["contributor"],
        "--contributed-at",
        metadata["contributed_at"],
        "--base-as",
        base_identity(),
    ]
    for industry in metadata["industry"]:
        base_cmd.extend(["--industry", industry])
    for product in metadata["product"]:
        base_cmd.extend(["--product", product])
    for deck_type in metadata["deck_type"]:
        base_cmd.extend(["--deck-type", deck_type])

    task.setdefault("warnings", [])
    cloud_log = log_dir / "ingest-base.txt"
    proc = run_command([*base_cmd, "--write-base"], cloud_log)
    task["logs"]["ingest_base"] = str(cloud_log)
    task["ingestion"].update({"attempted_cloud": True, "cloud_ok": proc.returncode == 0, "fallback_local": False})
    if proc.returncode != 0:
        warning = "云端知识库/素材库写入失败,已改用本地候选库完成入库;请检查当前 user 身份对 Base 的权限。"
        task["warnings"].append(warning)
        local_log = log_dir / "ingest-local-fallback.txt"
        local_proc = run_command(base_cmd, local_log)
        task["logs"]["ingest_local_fallback"] = str(local_log)
        task["ingestion"]["fallback_local"] = True
        if local_proc.returncode != 0:
            task["status"] = "failed"
            task["error"] = "deck ingestion failed"
            return task

    task["status"] = "succeeded"
    task["confirmation_required"] = ""
    task["artifacts"].update(output_artifacts(task_id, output_dir, base_url=base_url))
    return task


def confirm_deck_task(task_id: str, *, base_url: str | None = None) -> dict[str, Any]:
    task = load_task(task_id)
    task_dir = RUNS_DIR / task_id
    output_dir = Path(task.get("output_dir", ""))
    if task.get("status") != "awaiting_deck_confirmation":
        raise RuntimeError("deck confirmation is only allowed after rehearsal is accepted")
    if not task_audit_passed(output_dir):
        raise RuntimeError("deck-auditor pass verdict is required before ingestion")
    if visual_audit_enabled() and not visual_audit_verified(output_dir):
        raise RuntimeError("visual audit pass is required before ingestion")
    journey = load_journey_for_task(task) or new_journey(task, {}, str(task.get("source") or "unknown"))
    append_journey_event(journey, "deck_confirmed", "user", "用户确认 deckhtml 可以入库。")
    task = ingest_confirmed_deck(task, base_url=base_url)
    if task.get("status") == "succeeded":
        append_journey_event(journey, "ingested", "system", "已按知识库/素材库优先写云端,失败则本地兜底的策略完成入库。", task.get("ingestion", {}))
    else:
        append_journey_event(journey, "ingestion_failed", "system", "deck 入库失败。", {"error": task.get("error")})
    try:
        write_journey_artifacts(output_dir, journey)
    except Exception:
        pass
    task["artifacts"].update(output_artifacts(task_id, output_dir, base_url=base_url))
    save_task(task_dir, task)
    return task


def accept_rehearsal_task(task_id: str, *, base_url: str | None = None) -> dict[str, Any]:
    task = load_task(task_id)
    task_dir = RUNS_DIR / task_id
    output_dir = Path(task.get("output_dir", ""))
    journey = load_journey_for_task(task) or new_journey(task, {}, str(task.get("source") or "unknown"))
    append_journey_event(journey, "rehearsal_accepted", "user", "用户确认本轮 pitch simulator 反馈暂不改稿,进入是否入库确认。")
    if not cloud_publish_ready(output_dir):
        request_path = task_dir / "input" / "request.json"
        deck_path = output_dir / "deck.json"
        request = read_json(request_path) if request_path.exists() else {}
        deck = read_json(deck_path) if deck_path.exists() else {}
        cloud_publish = publish_deck_to_cloud(task, request, deck, log_dir=task_dir / "logs")
        task["cloud_publish"] = cloud_publish
        if cloud_publish.get("target") == "magic-page":
            task["magic_page_publish"] = cloud_publish
        elif cloud_publish.get("target") == "magic-doc":
            task["magic_doc_publish"] = cloud_publish
        if cloud_publish.get("ok") and cloud_publish.get("enabled"):
            cloud_url = cloud_publish.get("app_url") or cloud_publish.get("doc_url") or ""
            task.setdefault("artifacts", {})["cloud_url"] = cloud_url
            task.setdefault("artifacts", {})["magic_url"] = cloud_url
            task.setdefault("artifacts", {})["miaobi_url"] = cloud_url
            task.setdefault("artifacts", {})["preview_url"] = cloud_url
            if cloud_publish.get("app_url"):
                task.setdefault("artifacts", {})["magic_page_url"] = cloud_publish.get("app_url", "")
                task.setdefault("artifacts", {})["app_url"] = cloud_publish.get("app_url", "")
            if cloud_publish.get("doc_url"):
                task.setdefault("artifacts", {})["magic_doc_url"] = cloud_publish.get("doc_url", "")
                task.setdefault("artifacts", {})["miaobi_doc_url"] = cloud_publish.get("doc_url", "")
                task.setdefault("artifacts", {})["doc_url"] = cloud_publish.get("doc_url", "")
            append_journey_event(
                journey,
                "cloud_published_after_rehearsal_acceptance",
                "system",
                "用户接受预演风险后,已发布为云端妙笔 HTML 页面或所选 legacy 文档模式。",
                {"url": cloud_url, "target": cloud_publish.get("target", ""), "dry_run": cloud_publish.get("dry_run", False)},
            )
        elif cloud_publish.get("ok") and not cloud_publish.get("enabled"):
            append_journey_event(journey, "cloud_publish_disabled", "system", "本轮按配置跳过妙笔云端发布。", {"target": cloud_publish.get("target", "")})
        elif cloud_publish.get("enabled"):
            append_journey_event(journey, "cloud_publish_failed_after_rehearsal_acceptance", "system", "妙笔云端页面发布失败。", {"reason": cloud_publish.get("reason", "")})
            raise RuntimeError("cloud publish failed: " + str(cloud_publish.get("reason") or "unknown"))
    task["status"] = "awaiting_deck_confirmation"
    task["confirmation_required"] = "ingestion"
    task["updated_at"] = now_iso()
    task["artifacts"].update(output_artifacts(task_id, output_dir, base_url=base_url))
    append_journey_event(journey, "awaiting_deck_confirmation", "system", "等待用户确认是否把最终 deckhtml 入库。")
    write_journey_artifacts(output_dir, journey)
    save_task(task_dir, task)
    return task


def summarize_revision_queue(rehearsal: dict[str, Any]) -> list[str]:
    items = []
    for item in rehearsal.get("revision_queue") or []:
        if not isinstance(item, dict):
            continue
        target = item.get("target") or "deck-level"
        change = item.get("change") or item.get("issue") or ""
        if change:
            items.append(f"{target}: {change}")
    return items[:8]


def matches_gate_signal(text_lower: str, term: str) -> bool:
    needle = term.lower()
    if re.fullmatch(r"[a-z0-9][a-z0-9+-]*", needle):
        return re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", text_lower) is not None
    return needle in text_lower


def gate_signal_hits(text_lower: str, terms: list[str]) -> list[str]:
    return [term for term in terms if matches_gate_signal(text_lower, term)]


def rehearsal_gate_context(outline: dict[str, Any], deck: dict[str, Any]) -> tuple[bool, list[str]]:
    text = "\n".join(walk_text({"outline": outline, "deck": deck}))
    lower = text.lower()
    manufacturing_core_terms = ["中际旭创", "innolight", "npi", "光模块", "高端制造", "制造业", "工厂", "产线", "车间", "良率", "mes", "plm"]
    manufacturing_context_terms = ["质量异常", "供应链", "工程师"]
    ai_terms = ["agent", "agents", "ai", "aigc", "genai", "llm", "数字员工", "智能体", "大模型", "人工智能"]
    manufacturing_hits = gate_signal_hits(lower, manufacturing_core_terms)
    manufacturing_context_hits = gate_signal_hits(lower, manufacturing_context_terms)
    ai_hits = gate_signal_hits(lower, ai_terms)
    return bool(manufacturing_hits and ai_hits), manufacturing_hits + manufacturing_context_hits + ai_hits


def evaluate_rehearsal_gate(rehearsal: dict[str, Any], outline: dict[str, Any], deck: dict[str, Any]) -> dict[str, Any]:
    applied, signals = rehearsal_gate_context(outline, deck)
    scores = rehearsal.get("deck_arc", {}).get("scores", {}) if isinstance(rehearsal.get("deck_arc"), dict) else {}
    outcome = rehearsal.get("outcome_forecast", {}) if isinstance(rehearsal.get("outcome_forecast"), dict) else {}
    revision_queue = rehearsal.get("revision_queue") if isinstance(rehearsal.get("revision_queue"), list) else []
    blockers: list[str] = []
    trust = int(scores.get("trust") or 0)
    primary = str(outcome.get("primary_outcome") or "")
    confidence = str(outcome.get("confidence") or "")
    if applied:
        if primary in {"request-more-material", "defer", "reject"} and confidence in {"medium", "high"}:
            blockers.append(f"pitch simulator forecast is {primary} ({confidence}); publish should wait for replan or evidence")
        if trust < 58:
            blockers.append(f"trust score is {trust}/100; high-stakes manufacturing AI decks need evidence before cloud publish")
        p0_items = [item for item in revision_queue if isinstance(item, dict) and str(item.get("priority") or "").upper() == "P0"]
        evidence_p0 = [item for item in p0_items if str(item.get("owner") or "").lower() in {"evidence", "deck"}]
        if evidence_p0 and trust < 65:
            blockers.append(f"{len(evidence_p0)} P0 rehearsal item(s) require evidence/deck changes before publishing")
    return {
        "ok": not blockers,
        "applied": applied,
        "signals": signals,
        "primary_outcome": primary,
        "confidence": confidence,
        "trust": trust,
        "blockers": blockers,
        "reason": "ready" if not blockers else "rehearsal gate failed",
    }


def write_rehearsal_gate_report(output_dir: Path, payload: dict[str, Any]) -> None:
    write_json(output_dir / "rehearsal-gate.json", payload)
    lines = [
        "# Rehearsal Gate",
        "",
        f"- applied: {payload.get('applied')}",
        f"- ok: {payload.get('ok')}",
        f"- primary_outcome: {payload.get('primary_outcome') or ''}",
        f"- confidence: {payload.get('confidence') or ''}",
        f"- trust: {payload.get('trust', '')}",
        f"- reason: {payload.get('reason') or ''}",
        "",
    ]
    blockers = payload.get("blockers") if isinstance(payload.get("blockers"), list) else []
    if blockers:
        lines.append("## Blockers")
        lines.append("")
        for blocker in blockers:
            lines.append(f"- {blocker}")
        lines.append("")
    (output_dir / "REHEARSAL_GATE.md").write_text("\n".join(lines), encoding="utf-8")


def revise_from_rehearsal_task(task_id: str, *, base_url: str | None = None) -> dict[str, Any]:
    task = load_task(task_id)
    task_dir = RUNS_DIR / task_id
    input_dir = task_dir / "input"
    output_dir = Path(task.get("output_dir", ""))
    request_path = input_dir / "request.json"
    outline_path = input_dir / "outline.json"
    rehearsal_path = output_dir / "pitch-rehearsal.json"
    if not request_path.exists() or not outline_path.exists() or not rehearsal_path.exists():
        raise FileNotFoundError(f"rehearsal revision inputs not found: {task_id}")
    request = read_json(request_path)
    outline = read_json(outline_path)
    rehearsal = read_json(rehearsal_path)
    revision_items = summarize_revision_queue(rehearsal)
    outline["simulator_feedback"] = {
        "source_task_id": task_id,
        "accepted_for_replan_at": now_iso(),
        "revision_queue": rehearsal.get("revision_queue") or [],
        "outcome_forecast": rehearsal.get("outcome_forecast") or {},
    }
    outline.setdefault("open_questions", [])
    for item in revision_items:
        note = f"来自 pitch simulator 的待确认改稿建议: {item}"
        if note not in outline["open_questions"]:
            outline["open_questions"].append(note)
    outline.setdefault("claim_discipline", {}).setdefault("needs_user_confirmation", [])
    for item in revision_items:
        note = f"是否采纳 simulator 建议: {item}"
        if note not in outline["claim_discipline"]["needs_user_confirmation"]:
            outline["claim_discipline"]["needs_user_confirmation"].append(note)
    brief = request.get("brief") if isinstance(request.get("brief"), dict) else {}
    brief["rehearsal_feedback"] = revision_items
    new_request = {**request, "brief": brief, "outline": outline}
    new_task_id, version = next_version_id(task_id)
    new_task = create_outline_task(new_request, task_id=new_task_id, base_url=base_url)
    new_task["parent_task_id"] = task_id
    new_task["version"] = version
    new_task["source"] = "rehearsal-feedback"
    new_task["rehearsal_source_task_id"] = task_id
    new_task["updated_at"] = now_iso()
    new_task_dir = RUNS_DIR / new_task_id
    new_output_dir = Path(new_task["output_dir"])
    journey = load_journey_for_task(new_task) or new_journey(new_task, new_request, "rehearsal-feedback")
    append_journey_event(journey, "rehearsal_revision_requested", "user", "用户选择按 pitch simulator 反馈回到规划确认环节。", {"source_task_id": task_id})
    write_journey_artifacts(new_output_dir, journey)
    save_task(new_task_dir, new_task)
    return new_task


def skip_ingestion_task(task_id: str, *, base_url: str | None = None) -> dict[str, Any]:
    task = load_task(task_id)
    task_dir = RUNS_DIR / task_id
    output_dir = Path(task.get("output_dir", ""))
    journey = load_journey_for_task(task) or new_journey(task, {}, str(task.get("source") or "unknown"))
    task["status"] = "completed_without_ingestion"
    task["confirmation_required"] = ""
    task["updated_at"] = now_iso()
    task["ingestion"] = {"skipped": True, "reason": "user-declined"}
    task["artifacts"].update(output_artifacts(task_id, output_dir, base_url=base_url))
    append_journey_event(journey, "ingestion_skipped", "user", "用户选择不入库,流程结束。")
    write_journey_artifacts(output_dir, journey)
    save_task(task_dir, task)
    return task


def create_or_run_task(
    request: dict[str, Any],
    *,
    task_id: str | None = None,
    base_url: str | None = None,
    metadata: dict[str, Any] | None = None,
    require_deck_confirmation: bool = False,
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
    preserve_existing_run = bool(metadata and metadata.get("outline_confirmed"))
    if task_dir.exists() and not preserve_existing_run:
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
        "warnings": [],
    }
    if metadata:
        task.update(metadata)
    save_task(task_dir, task)
    write_json(input_dir / "request.raw.json", request)
    journey = new_journey(task, request, source)

    try:
        request, _dossier = run_upload_parser(
            request,
            task_id=task_id,
            input_dir=input_dir,
            output_dir=output_dir,
            log_dir=log_dir,
            journey=journey,
            task=task,
        )
        brief = request.get("brief") or {}
        write_json(input_dir / "request.json", request)
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
        library = library_usage_summary(outline)
        task["library"] = library
        if library["mode"] != "cloud":
            task["warnings"].append(library["message"])

        outline_log = log_dir / "outline-validator.txt"
        proc = run_command(["python3", str(OUTLINE_VALIDATOR), str(input_dir / "outline.json")], outline_log)
        task["logs"]["outline_validator"] = str(outline_log)
        if proc.returncode != 0:
            append_journey_event(journey, "outline_validation_failed", "system", "outline validator 未通过。", {"exit": proc.returncode})
            raise RuntimeError("outline validation failed")
        append_journey_event(journey, "outline_validated", "system", "outline validator 通过。")

        if request.get("deck_json"):
            deck = request["deck_json"]
            append_journey_event(
                journey,
                "deckjson_loaded",
                "system",
                "使用请求中提供的 DeckJSON 作为源文件。",
                {"slide_count": len(deck.get("slides", [])) if isinstance(deck, dict) else 0},
            )
            write_json(output_dir / "deck.json", deck)
        else:
            compile_log = log_dir / "compile-outline.txt"
            proc = run_command(
                [
                    "python3",
                    str(COMPILE_OUTLINE),
                    str(input_dir / "outline.json"),
                    str(output_dir / "deck.json"),
                    "--report",
                    str(output_dir / "compile-report.json"),
                    "--author",
                    "lark-deck-cyrus generator",
                    "--cover-date",
                    compact_date(),
                    "--customer-slug",
                    slugify(str(title_source)),
                ],
                compile_log,
            )
            task["logs"]["compile_outline"] = str(compile_log)
            if proc.returncode != 0:
                append_journey_event(journey, "deckjson_compile_failed", "system", "确认后的 outline 编译 DeckJSON 失败。", {"exit": proc.returncode})
                raise RuntimeError("outline compile failed")
            deck = read_json(output_dir / "deck.json")
            append_journey_event(
                journey,
                "deckjson_compiled",
                "system",
                "使用 deck-renderer 的 compile-outline.py 将确认后的 outline 编译为 DeckJSON。",
                {"slide_count": len(deck.get("slides", [])) if isinstance(deck, dict) else 0},
            )

        materialize_deck_assets(
            task=task,
            input_dir=input_dir,
            output_dir=output_dir,
            log_dir=log_dir,
            journey=journey,
        )
        deck = read_json(output_dir / "deck.json")

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

        validator_report = output_dir / "AUDIT_REPORT.md"
        check_log = log_dir / "auditor.txt"
        proc = run_command(
            [
                "python3",
                str(AUDITOR),
                str(output_dir / "index.html"),
                "--deck-json",
                str(output_dir / "deck.json"),
                auditor_visual_flag(),
                "--report",
                str(validator_report),
                "--json-report",
                str(output_dir / "audit-report.json"),
                "--h5-report",
                str(output_dir / "H5_CHECKONLY_REPORT.md"),
            ],
            check_log,
        )
        task["logs"]["auditor"] = str(check_log)
        task["artifacts"]["AUDIT_REPORT.md"] = str(validator_report)
        if proc.returncode != 0:
            if visual_audit_unverified(output_dir):
                task["status"] = "visual_unverified"
                task["confirmation_required"] = "visual_audit"
                task.setdefault("warnings", []).append("视觉审计未能在当前环境运行,已暂停发布/预演/入库;请在可运行浏览器的环境重跑 auditor --visual。")
                task["artifacts"].update(output_artifacts(task_id, output_dir, base_url=base_url))
                append_journey_event(
                    journey,
                    "visual_audit_unverified",
                    "system",
                    "deck-auditor 的视觉审计未能运行,不进入发布、预演或入库 handoff。",
                    {"h5_report": str(output_dir / "H5_CHECKONLY_REPORT.md")},
                )
                write_journey_artifacts(output_dir, journey)
                raise FlowPaused()
            append_journey_event(journey, "audit_failed", "system", "deck-auditor 验收未通过。", {"exit": proc.returncode})
            rerender_log = log_dir / "render-retry.txt"
            append_journey_event(journey, "rerender_requested", "system", "质量验收发现问题,自动回到 renderer 重渲染一次。")
            rerender_proc = run_command(render_cmd, rerender_log)
            task["logs"]["render_retry"] = str(rerender_log)
            if rerender_proc.returncode != 0:
                append_journey_event(journey, "rerender_failed", "system", "自动重渲染失败。", {"exit": rerender_proc.returncode})
                raise RuntimeError("rerender failed after audit issue")
            retry_report = output_dir / "AUDIT_REPORT.md"
            retry_log = log_dir / "auditor-retry.txt"
            proc = run_command(
                [
                    "python3",
                    str(AUDITOR),
                    str(output_dir / "index.html"),
                    "--deck-json",
                    str(output_dir / "deck.json"),
                    auditor_visual_flag(),
                    "--report",
                    str(retry_report),
                    "--json-report",
                    str(output_dir / "audit-report.json"),
                    "--h5-report",
                    str(output_dir / "H5_CHECKONLY_REPORT.md"),
                ],
                retry_log,
            )
            task["logs"]["auditor_retry"] = str(retry_log)
            if proc.returncode != 0:
                append_journey_event(journey, "audit_failed_after_rerender", "system", "重渲染后 deck-auditor 仍未通过。", {"exit": proc.returncode})
                raise RuntimeError("deck-auditor failed under strict gate")
            append_journey_event(journey, "rerendered_after_quality_gate", "system", "重渲染后 deck-auditor 通过。")
        append_journey_event(journey, "audited", "system", "deck-auditor 验收通过。")

        if inline_delivery_html():
            inline_log = log_dir / "inline-assets.txt"
            proc = run_command(["python3", str(INLINE_ASSETS), str(output_dir / "index.html"), "--out", str(output_dir / "index.html")], inline_log)
            task["logs"]["inline_assets"] = str(inline_log)
            if proc.returncode != 0:
                append_journey_event(journey, "inline_failed", "system", "HTML 资产内联失败。", {"exit": proc.returncode})
                raise RuntimeError("inline-assets failed")
            append_journey_event(
                journey,
                "html_inlined",
                "system",
                "已把 CSS/JS/图片内联到 index.html,对齐原版 H5 的单文件交付习惯。",
                {"size_kb": round((output_dir / "index.html").stat().st_size / 1024, 1)},
            )
            inline_check_log = log_dir / "auditor-inline.txt"
            proc = run_command(
                [
                    "python3",
                    str(AUDITOR),
                    str(output_dir / "index.html"),
                    "--deck-json",
                    str(output_dir / "deck.json"),
                    auditor_visual_flag(),
                    "--report",
                    str(validator_report),
                    "--json-report",
                    str(output_dir / "audit-report.json"),
                    "--h5-report",
                    str(output_dir / "H5_CHECKONLY_REPORT.md"),
                ],
                inline_check_log,
            )
            task["logs"]["auditor_inline"] = str(inline_check_log)
            if proc.returncode != 0:
                if visual_audit_unverified(output_dir):
                    task["status"] = "visual_unverified"
                    task["confirmation_required"] = "visual_audit"
                    task.setdefault("warnings", []).append("视觉审计未能在当前环境运行,已暂停发布/预演/入库;请在可运行浏览器的环境重跑 auditor --visual。")
                    task["artifacts"].update(output_artifacts(task_id, output_dir, base_url=base_url))
                    append_journey_event(
                        journey,
                        "visual_audit_unverified",
                        "system",
                        "inline 后 deck-auditor 的视觉审计未能运行,不进入发布、预演或入库 handoff。",
                        {"h5_report": str(output_dir / "H5_CHECKONLY_REPORT.md")},
                    )
                    write_journey_artifacts(output_dir, journey)
                    raise FlowPaused()
                append_journey_event(journey, "inline_audit_failed", "system", "inline 后 deck-auditor 未通过。", {"exit": proc.returncode})
                raise RuntimeError("inline deck-auditor failed under strict gate")
            append_journey_event(journey, "inline_audited", "system", "inline 后 deck-auditor 通过。")
        if visual_audit_unverified(output_dir):
            task["status"] = "visual_unverified"
            task["confirmation_required"] = "visual_audit"
            task.setdefault("warnings", []).append("视觉审计未能在当前环境运行,已暂停发布/预演/入库;请在可运行浏览器的环境重跑 auditor --visual。")
            task["artifacts"].update(output_artifacts(task_id, output_dir, base_url=base_url))
            append_journey_event(
                journey,
                "visual_audit_unverified",
                "system",
                "deck-auditor 的视觉审计未能运行,不进入发布、预演或入库 handoff。",
                {"h5_report": str(output_dir / "H5_CHECKONLY_REPORT.md")},
            )
            write_journey_artifacts(output_dir, journey)
            raise FlowPaused()

        rehearsal_log = log_dir / "pitch-rehearsal.txt"
        proc = run_command(
            [
                "python3",
                str(PITCH_SIMULATOR),
                "--outline",
                str(input_dir / "outline.json"),
                "--deck-json",
                str(output_dir / "deck.json"),
                "--html",
                str(output_dir / "index.html"),
                "--out-json",
                str(output_dir / "pitch-rehearsal.json"),
                "--out-md",
                str(output_dir / "PITCH_REHEARSAL.md"),
            ],
            rehearsal_log,
        )
        task["logs"]["pitch_rehearsal"] = str(rehearsal_log)
        if proc.returncode != 0:
            append_journey_event(journey, "pitch_rehearsal_failed", "system", "pitch-simulator 未能生成预演。", {"exit": proc.returncode})
            raise RuntimeError("pitch rehearsal failed")
        rehearsal_validate_log = log_dir / "pitch-rehearsal-validator.txt"
        proc = run_command(["python3", str(PITCH_REHEARSAL_VALIDATOR), str(output_dir / "pitch-rehearsal.json")], rehearsal_validate_log)
        task["logs"]["pitch_rehearsal_validator"] = str(rehearsal_validate_log)
        if proc.returncode != 0:
            append_journey_event(journey, "pitch_rehearsal_validation_failed", "system", "pitch rehearsal validator 未通过。", {"exit": proc.returncode})
            raise RuntimeError("pitch rehearsal validation failed")
        rehearsal_payload = read_json(output_dir / "pitch-rehearsal.json")
        gate_payload = evaluate_rehearsal_gate(rehearsal_payload, outline, deck)
        write_rehearsal_gate_report(output_dir, gate_payload)
        task["rehearsal_gate"] = gate_payload
        append_journey_event(journey, "pitch_rehearsed", "system", "已在发布前生成 pitch rehearsal 和异议/改稿队列。", {"gate": gate_payload})
        if not gate_payload.get("ok"):
            task["status"] = "awaiting_rehearsal_decision"
            task["confirmation_required"] = "rehearsal"
            task.setdefault("warnings", []).append("预演门禁未通过,已暂停云端发布;建议先按 P0 反馈补证据或回到 planner/renderer。")
            task["artifacts"].update(output_artifacts(task_id, output_dir, base_url=base_url))
            append_journey_event(journey, "rehearsal_gate_blocked_publish", "system", "预演门禁未通过,本轮不自动发布云端页面。", gate_payload)
            upsert_journey_version(journey, task, deck)
            write_journey_artifacts(output_dir, journey)
            raise FlowPaused()

        cloud_publish = write_pending_cloud_publish_report(output_dir, request)
        task["cloud_publish"] = cloud_publish
        append_journey_event(
            journey,
            "cloud_publish_pending",
            "system",
            "deckhtml 与 pitch rehearsal 已准备好;等待用户确认是否按预演反馈修改后再发布云端页面。",
            {"target": cloud_publish.get("target", ""), "reason": cloud_publish.get("reason", "")},
        )
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

        if require_deck_confirmation or request.get("deck_confirmation_required"):
            task["status"] = "awaiting_rehearsal_decision"
            task["confirmation_required"] = "rehearsal"
            append_journey_event(journey, "awaiting_rehearsal_decision", "system", "deckhtml 已生成并完成预演,等待用户判断是否按模拟反馈修改。")
        else:
            task["status"] = "succeeded"
        task["artifacts"].update(output_artifacts(task_id, output_dir, base_url=base_url))
        append_journey_event(journey, "result_ready", "system", "用户可通过状态页、妙笔云端 HTML 页面和预演报告拿到结果。")
    except FlowPaused:
        pass
    except Exception as exc:  # noqa: BLE001 - task wrapper should persist any failure.
        task["status"] = "failed"
        task["error"] = str(exc)
        task["artifacts"].update(output_artifacts(task_id, output_dir, base_url=base_url))
        append_journey_event(journey, "task_failed", "system", "任务失败,原因已写入 task.json。", {"error": str(exc)})
        if not (input_dir / "request.json").exists():
            write_json(input_dir / "request.json", request)
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
                payload = self.read_body_json()
                if payload.get("deck_json") or payload.get("outline_confirmed"):
                    task = create_or_run_task(
                        payload,
                        base_url=self.base_url(),
                        require_deck_confirmation=bool(payload.get("deck_confirmation_required")),
                    )
                else:
                    task = create_planned_or_run_task(payload, base_url=self.base_url())
                self.send_json(201 if success_like_status(task["status"]) else 500, task)
                return
            if len(parts) == 3 and parts[0] == "decks" and parts[2] == "confirm-outline":
                task = confirm_outline_task(parts[1], base_url=self.base_url())
                self.send_json(200 if success_like_status(task["status"]) else 500, task)
                return
            if len(parts) == 3 and parts[0] == "decks" and parts[2] == "accept-rehearsal":
                task = accept_rehearsal_task(parts[1], base_url=self.base_url())
                self.send_json(200 if success_like_status(task["status"]) else 500, task)
                return
            if len(parts) == 3 and parts[0] == "decks" and parts[2] == "revise-from-rehearsal":
                task = revise_from_rehearsal_task(parts[1], base_url=self.base_url())
                self.send_json(200 if success_like_status(task["status"]) else 500, task)
                return
            if len(parts) == 3 and parts[0] == "decks" and parts[2] == "confirm-deck":
                task = confirm_deck_task(parts[1], base_url=self.base_url())
                self.send_json(200 if success_like_status(task["status"]) else 500, task)
                return
            if len(parts) == 3 and parts[0] == "decks" and parts[2] == "skip-ingest":
                task = skip_ingestion_task(parts[1], base_url=self.base_url())
                self.send_json(200 if success_like_status(task["status"]) else 500, task)
                return
            if len(parts) == 3 and parts[0] == "decks" and parts[2] == "regenerate":
                task_id = parts[1]
                request_path = RUNS_DIR / task_id / "input" / "request.json"
                outline_path = RUNS_DIR / task_id / "input" / "outline.json"
                if not request_path.exists():
                    self.send_json(404, {"error": "task not found", "id": task_id})
                    return
                payload = read_json(request_path)
                if outline_path.exists():
                    outline, sync_report = sync_design_plan_to_outline(task_id, read_json(outline_path))
                    write_json(outline_path, outline)
                    payload["outline"] = outline
                    payload["design_plan_sync"] = {
                        "checked": sync_report.get("checked", False),
                        "change_count": sync_report.get("change_count", 0),
                        "warnings": sync_report.get("warnings", []),
                    }
                payload["outline_confirmed"] = True
                task = create_or_run_task(payload, task_id=task_id, base_url=self.base_url(), require_deck_confirmation=True)
                self.send_json(200 if success_like_status(task["status"]) else 500, task)
                return
            if len(parts) == 3 and parts[0] == "decks" and parts[2] in {"edits", "edit"}:
                task_id = parts[1]
                task = edit_task(task_id, self.read_body_json(), base_url=self.base_url())
                self.send_json(201 if success_like_status(task["status"]) else 500, task)
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
    if args.plan_only:
        request["plan_only"] = True
    if args.auto_confirm_outline:
        request["auto_confirm_outline"] = True
        if args.allow_skip_outline_confirmation:
            request["allow_skip_outline_confirmation"] = True
    if args.plan_only and not request.get("deck_json"):
        task = create_outline_task(request, base_url=args.base_url)
    elif not request.get("deck_json") and not request.get("outline_confirmed"):
        task = create_planned_or_run_task(request, base_url=args.base_url)
    else:
        task = create_or_run_task(request, base_url=args.base_url, require_deck_confirmation=args.require_deck_confirmation)
    print(json.dumps(task, ensure_ascii=False, indent=2))
    return 0 if success_like_status(task["status"]) else 1


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
    outline_path = RUNS_DIR / args.task_id / "input" / "outline.json"
    if not request_path.exists():
        raise SystemExit(f"task not found: {args.task_id}")
    request = read_json(request_path)
    if outline_path.exists():
        outline, sync_report = sync_design_plan_to_outline(args.task_id, read_json(outline_path))
        write_json(outline_path, outline)
        request["outline"] = outline
        request["design_plan_sync"] = {
            "checked": sync_report.get("checked", False),
            "change_count": sync_report.get("change_count", 0),
            "warnings": sync_report.get("warnings", []),
        }
    request["outline_confirmed"] = True
    task = create_or_run_task(request, task_id=args.task_id, base_url=args.base_url, require_deck_confirmation=True)
    print(json.dumps(task, ensure_ascii=False, indent=2))
    return 0 if success_like_status(task["status"]) else 1


def cmd_edit(args: argparse.Namespace) -> int:
    payload = read_json(args.patch)
    task = edit_task(args.task_id, payload, base_url=args.base_url)
    print(json.dumps(task, ensure_ascii=False, indent=2))
    return 0 if success_like_status(task["status"]) else 1


def cmd_confirm_outline(args: argparse.Namespace) -> int:
    task = confirm_outline_task(args.task_id, base_url=args.base_url)
    print(json.dumps(task, ensure_ascii=False, indent=2))
    return 0 if success_like_status(task["status"]) else 1


def cmd_accept_rehearsal(args: argparse.Namespace) -> int:
    task = accept_rehearsal_task(args.task_id, base_url=args.base_url)
    print(json.dumps(task, ensure_ascii=False, indent=2))
    return 0 if success_like_status(task["status"]) else 1


def cmd_revise_from_rehearsal(args: argparse.Namespace) -> int:
    task = revise_from_rehearsal_task(args.task_id, base_url=args.base_url)
    print(json.dumps(task, ensure_ascii=False, indent=2))
    return 0 if success_like_status(task["status"]) else 1


def cmd_confirm_deck(args: argparse.Namespace) -> int:
    task = confirm_deck_task(args.task_id, base_url=args.base_url)
    print(json.dumps(task, ensure_ascii=False, indent=2))
    return 0 if success_like_status(task["status"]) else 1


def cmd_skip_ingest(args: argparse.Namespace) -> int:
    task = skip_ingestion_task(args.task_id, base_url=args.base_url)
    print(json.dumps(task, ensure_ascii=False, indent=2))
    return 0 if success_like_status(task["status"]) else 1


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
    create.add_argument("--plan-only", action="store_true", help="stop after planner even if the outline is low-risk")
    create.add_argument("--auto-confirm-outline", action="store_true", help="request renderer handoff after planner when policy allows it")
    create.add_argument("--allow-skip-outline-confirmation", action="store_true", help="allow --auto-confirm-outline to force risky handoff non-interactively")
    create.add_argument("--require-deck-confirmation", action="store_true", help="wait for user deck confirmation before ingestion")
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

    confirm_outline = sub.add_parser("confirm-outline", help="confirm a planned outline and render deckhtml")
    confirm_outline.add_argument("task_id")
    confirm_outline.add_argument("--base-url", help="external base URL used to populate preview/edit links")
    confirm_outline.set_defaults(func=cmd_confirm_outline)

    accept_rehearsal = sub.add_parser("accept-rehearsal", help="accept pitch rehearsal feedback and move to ingestion confirmation")
    accept_rehearsal.add_argument("task_id")
    accept_rehearsal.add_argument("--base-url", help="external base URL used to populate preview/edit links")
    accept_rehearsal.set_defaults(func=cmd_accept_rehearsal)

    revise_rehearsal = sub.add_parser("revise-from-rehearsal", help="turn pitch rehearsal feedback into a new outline confirmation task")
    revise_rehearsal.add_argument("task_id")
    revise_rehearsal.add_argument("--base-url", help="external base URL used to populate preview/edit links")
    revise_rehearsal.set_defaults(func=cmd_revise_from_rehearsal)

    confirm_deck = sub.add_parser("confirm-deck", help="confirm rendered deckhtml and ingest it")
    confirm_deck.add_argument("task_id")
    confirm_deck.add_argument("--base-url", help="external base URL used to populate preview/edit links")
    confirm_deck.set_defaults(func=cmd_confirm_deck)

    skip_ingest = sub.add_parser("skip-ingest", help="finish a deck task without writing ingestion records")
    skip_ingest.add_argument("task_id")
    skip_ingest.add_argument("--base-url", help="external base URL used to populate preview/edit links")
    skip_ingest.set_defaults(func=cmd_skip_ingest)

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
