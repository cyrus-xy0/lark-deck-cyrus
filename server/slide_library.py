#!/usr/bin/env python3
"""Local P2 slide library provider.

This module is the first productized boundary between the generator/editor and
reusable team assets. Feishu Base remains the long-term source of truth; this
local library gives CI, demos, and offline workers a deterministic gate/search
contract.

Reuse is intentionally split into two layers:

- knowledge candidates: "讲什么" assets for deck-planner, such as scenario,
  key idea, proof strategy, objections, and talk track.
- presentation candidates: "怎么呈现" assets for deck-renderer, such as
  DeckJSON fragments, layout choices, thumbnails, and reusable visual patterns.

A generated slide can be strong in one layer and weak in the other; ingest must
judge them separately rather than treating a slide as a single reusable unit.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


REPO = Path(__file__).resolve().parents[1]
BUSINESS_LIBRARY = REPO / "library/business/slides"
CANDIDATES_DIR = REPO / "library/business/candidates"
PPT_UPLOADS_DIR = REPO / "library/business/uploads"
PPT_UPLOAD_THUMBNAILS_DIR = REPO / "library/business/thumbnails/uploads"
KNOWLEDGE_CANDIDATES_DIR = REPO / "library/knowledge/candidates"
PRESENTATION_CANDIDATES_DIR = REPO / "library/presentation/candidates"
DESIGN_KIT = REPO / "library/design-kit/manifest.json"
EXAMPLE_DECKS = REPO / "skills/deck-renderer/deck-json/examples"
RUNS_DIR = REPO / "runs"

ALLOWED_SOURCE_LEVELS = {
    "synthetic",
    "public-pattern",
    "internal-draft",
    "internal-approved",
    "customer-approved",
}
APPROVED_STATUSES = {"approved", "candidate", "rejected"}
REQUIRED_ENTRY_KEYS = [
    "id",
    "title",
    "status",
    "thumbnail",
    "tags",
    "industry",
    "product",
    "customer_stage",
    "deck_type",
    "value_prop",
    "layout",
    "source",
    "slide",
]
SENSITIVE_PATTERNS = [
    ("email", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)),
    ("phone", re.compile(r"(?<!\d)(?:1[3-9]\d{9}|\+?\d[\d -]{8,}\d)(?!\d)")),
    ("sensitive-word", re.compile(r"(客户机密|严格保密|未公开|身份证|银行卡|NDA|confidential)", re.I)),
]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def repo_rel(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO).as_posix()
    except ValueError:
        return str(resolved)


def normalize_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(normalize_list(item))
        return list(dict.fromkeys(out))
    return [part.strip() for part in re.split(r"[,;，；、\n]+", str(value)) if part.strip()]


def text_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(text_values(item))
        return out
    if isinstance(value, dict):
        out: list[str] = []
        for item in value.values():
            out.extend(text_values(item))
        return out
    return []


def slide_title(slide: dict[str, Any]) -> str:
    data = slide.get("data") if isinstance(slide.get("data"), dict) else {}
    for key in ["title", "slogan", "quote", "lede"]:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return str(slide.get("key") or slide.get("layout") or "slide")


def slide_text(slide: dict[str, Any]) -> str:
    return "\n".join(text_values(slide.get("data") or {})).strip()


def parse_notes(notes: Any) -> dict[str, list[str]]:
    if not isinstance(notes, str):
        return {}
    parsed: dict[str, list[str]] = {}
    for raw in notes.splitlines():
        if ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        key = key.strip()
        values = [item.strip() for item in value.split(" / ") if item.strip()]
        if key and values:
            parsed[key] = values
    return parsed


def load_design_kit() -> dict[str, Any]:
    if not DESIGN_KIT.exists():
        return {"version": "1.0", "items": []}
    return read_json(DESIGN_KIT)


def load_business_entries(include_candidates: bool = False) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    roots = [BUSINESS_LIBRARY]
    if include_candidates:
        roots.extend([CANDIDATES_DIR, PPT_UPLOADS_DIR])
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.glob("*.json")):
            entry = read_json(path)
            entry["_path"] = repo_rel(path)
            entries.append(entry)
    return entries


def fallback_example_entries(limit: int = 36) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for source in sorted(EXAMPLE_DECKS.glob("*.json")):
        try:
            deck = read_json(source)
        except Exception:
            continue
        for slide in deck.get("slides", []):
            if not isinstance(slide, dict) or slide.get("layout") in {"cover", "end", "raw", "replica"}:
                continue
            entry = {
                "id": f"example-{source.stem}-{slide.get('key')}",
                "title": slide_title(slide),
                "status": "candidate",
                "thumbnail": "",
                "tags": ["example", str(slide.get("layout", "")), str(slide.get("variant", ""))],
                "industry": ["通用"],
                "product": ["飞书"],
                "customer_stage": ["首访", "POC"],
                "deck_type": ["客户 pitch"],
                "value_prop": normalize_list(slide_title(slide)),
                "layout": slide.get("layout"),
                "variant": slide.get("variant", ""),
                "source": {
                    "level": "synthetic",
                    "deck": repo_rel(source),
                    "slide_key": slide.get("key"),
                    "owner": "lark-deck-cyrus",
                },
                "slide": slide,
            }
            entries.append(entry)
            if len(entries) >= limit:
                return entries
    return entries


def library_entries(include_candidates: bool = False, fallback: bool = True) -> list[dict[str, Any]]:
    entries = load_business_entries(include_candidates=include_candidates)
    if entries or not fallback:
        return entries
    return fallback_example_entries()


def entry_terms(entry: dict[str, Any]) -> str:
    fields = [
        entry.get("id"),
        entry.get("title"),
        entry.get("layout"),
        entry.get("variant"),
        entry.get("thumbnail"),
        entry.get("source", {}).get("deck") if isinstance(entry.get("source"), dict) else "",
        slide_text(entry.get("slide") or {}),
    ]
    for key in ["tags", "industry", "product", "customer_stage", "deck_type", "value_prop"]:
        fields.extend(normalize_list(entry.get(key)))
    return " ".join(str(item) for item in fields if item).lower()


def validate_entry(entry: dict[str, Any], *, seen_ids: set[str], seen_slide_keys: set[str]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    for key in REQUIRED_ENTRY_KEYS:
        if entry.get(key) in (None, "", []):
            issues.append({"severity": "error", "code": "LIB-MISSING-FIELD", "message": f"missing {key}"})

    entry_id = str(entry.get("id", ""))
    if entry_id in seen_ids:
        issues.append({"severity": "error", "code": "LIB-DUPLICATE-ID", "message": entry_id})
    seen_ids.add(entry_id)

    status = entry.get("status")
    if status not in APPROVED_STATUSES:
        issues.append({"severity": "error", "code": "LIB-STATUS", "message": f"invalid status: {status}"})

    source = entry.get("source") if isinstance(entry.get("source"), dict) else {}
    level = source.get("level")
    if level not in ALLOWED_SOURCE_LEVELS:
        issues.append({"severity": "error", "code": "LIB-SOURCE-LEVEL", "message": f"invalid source level: {level}"})
    for key in ["deck", "slide_key", "owner"]:
        if not source.get(key):
            issues.append({"severity": "error", "code": "LIB-SOURCE", "message": f"source.{key} is required"})

    slide = entry.get("slide") if isinstance(entry.get("slide"), dict) else {}
    slide_key = str(slide.get("key") or source.get("slide_key") or "")
    if not slide_key:
        issues.append({"severity": "error", "code": "LIB-SLIDE-KEY", "message": "slide key is required"})
    elif slide_key in seen_slide_keys:
        issues.append({"severity": "error", "code": "LIB-DUPLICATE-SLIDE-KEY", "message": slide_key})
    seen_slide_keys.add(slide_key)

    if entry.get("layout") != slide.get("layout"):
        issues.append({"severity": "error", "code": "LIB-LAYOUT-MISMATCH", "message": "entry.layout must match slide.layout"})

    thumbnail = str(entry.get("thumbnail") or "")
    if thumbnail and not (REPO / thumbnail).exists():
        issues.append({"severity": "error", "code": "LIB-THUMBNAIL", "message": f"thumbnail not found: {thumbnail}"})

    if not slide_text(slide):
        issues.append({"severity": "error", "code": "LIB-TEXT", "message": "slide text is empty"})

    haystack = " ".join(
        [
            str(entry.get("title") or ""),
            " ".join(normalize_list(entry.get("tags"))),
            " ".join(normalize_list(entry.get("industry"))),
            " ".join(normalize_list(entry.get("product"))),
            slide_text(slide),
        ]
    ).lower()
    for code, pattern in SENSITIVE_PATTERNS:
        if pattern.search(haystack):
            issues.append({"severity": "error", "code": "LIB-SENSITIVE", "message": f"sensitive pattern matched: {code}"})

    if status == "approved" and level in {"internal-draft"}:
        issues.append({"severity": "error", "code": "LIB-APPROVAL", "message": "approved entries cannot use internal-draft source level"})

    return issues


def validate_library(include_candidates: bool = True) -> dict[str, Any]:
    entries = library_entries(include_candidates=include_candidates, fallback=False)
    seen_ids: set[str] = set()
    seen_slide_keys: set[str] = set()
    results = []
    ok = True
    for entry in entries:
        issues = validate_entry(entry, seen_ids=seen_ids, seen_slide_keys=seen_slide_keys)
        if any(issue["severity"] == "error" for issue in issues):
            ok = False
        results.append({"id": entry.get("id"), "path": entry.get("_path"), "issues": issues})
    return {"ok": ok, "entries": len(entries), "results": results}


def matches_filter(entry: dict[str, Any], key: str, value: str | None) -> bool:
    if not value:
        return True
    if key == "layout":
        return str(entry.get("layout", "")).lower() == value.lower()
    needle = value.lower()
    return any(needle in item.lower() for item in normalize_list(entry.get(key)))


def search_slides(
    *,
    query: str = "",
    industry: str = "",
    product: str = "",
    customer_stage: str = "",
    deck_type: str = "",
    value_prop: str = "",
    layout: str = "",
    include_candidates: bool = False,
    limit: int = 20,
) -> list[dict[str, Any]]:
    query_terms = [term.lower() for term in normalize_list(query)]
    filters = {
        "industry": industry,
        "product": product,
        "customer_stage": customer_stage,
        "deck_type": deck_type,
        "value_prop": value_prop,
        "layout": layout,
    }
    matched: list[dict[str, Any]] = []
    for entry in library_entries(include_candidates=include_candidates):
        if entry.get("status") == "rejected":
            continue
        if any(not matches_filter(entry, key, value) for key, value in filters.items()):
            continue
        terms = entry_terms(entry)
        if query_terms and not all(term in terms for term in query_terms):
            continue
        matched.append(summarize_entry(entry))
        if len(matched) >= limit:
            break
    return matched


def summarize_entry(entry: dict[str, Any]) -> dict[str, Any]:
    slide = entry.get("slide") or {}
    layout = entry.get("layout") or slide.get("layout")
    variant = entry.get("variant") or slide.get("variant", "")
    return {
        "id": entry.get("id"),
        "title": entry.get("title") or slide_title(slide),
        "status": entry.get("status"),
        "thumbnail": entry.get("thumbnail", ""),
        "tags": normalize_list(entry.get("tags")),
        "industry": normalize_list(entry.get("industry")),
        "product": normalize_list(entry.get("product")),
        "customer_stage": normalize_list(entry.get("customer_stage")),
        "deck_type": normalize_list(entry.get("deck_type")),
        "value_prop": normalize_list(entry.get("value_prop")),
        "layout": layout,
        "variant": variant,
        "source": entry.get("source", {}),
        "text": slide_text(slide)[:500],
        "insert_suggestion": f"插入为 {layout}{('/' + variant) if variant else ''},再替换客户事实和指标。",
        "slide": slide,
    }


def outline_slide_for_task(task_id: str, slide_key: str) -> dict[str, Any]:
    outline_path = RUNS_DIR / task_id / "input/outline.json"
    if not outline_path.exists():
        return {}
    try:
        outline = read_json(outline_path)
    except Exception:
        return {}
    slides = ((outline.get("outline") or {}).get("slides") or [])
    if not isinstance(slides, list):
        return {}
    return next((item for item in slides if isinstance(item, dict) and item.get("key") == slide_key), {})


def first_note_or_plan(notes: dict[str, list[str]], outline_slide: dict[str, Any], key: str, fallback: str = "") -> str:
    value = outline_slide.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    values = notes.get(key) or []
    return values[0] if values else fallback


def list_note_or_plan(notes: dict[str, list[str]], outline_slide: dict[str, Any], key: str, fallback_keys: list[str] | None = None) -> list[str]:
    value = outline_slide.get(key)
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    values = notes.get(key) or []
    if values:
        return values
    for fallback_key in fallback_keys or []:
        fallback = outline_slide.get(fallback_key)
        if isinstance(fallback, list):
            return [str(item).strip() for item in fallback if str(item).strip()]
        fallback_values = notes.get(fallback_key) or []
        if fallback_values:
            return fallback_values
    return []


def assess_reuse_layers(slide: dict[str, Any], metadata: dict[str, Any], outline_slide: dict[str, Any] | None = None) -> dict[str, Any]:
    outline_slide = outline_slide or {}
    notes = parse_notes(slide.get("notes"))
    text = slide_text(slide)
    title = metadata.get("title") or slide_title(slide)
    layout = str(slide.get("layout") or "")
    sensitive = []
    haystack = " ".join([title, text, str(slide.get("notes") or "")])
    for code, pattern in SENSITIVE_PATTERNS:
        if pattern.search(haystack):
            sensitive.append(code)

    key_idea = first_note_or_plan(notes, outline_slide, "key_idea", text or title)
    talk_track = first_note_or_plan(notes, outline_slide, "talk_track")
    proof_needed = list_note_or_plan(notes, outline_slide, "proof_needed", ["evidence"])
    risk = list_note_or_plan(notes, outline_slide, "risk", ["risk_flags"])
    knowledge_ok = bool(key_idea and (talk_track or proof_needed or risk)) and not sensitive

    presentation_ok = bool(layout and layout not in {"raw", "replica"} and slide.get("data")) and not sensitive
    return {
        "knowledge": {
            "verdict": "candidate" if knowledge_ok else "not-suitable",
            "reason": (
                "contains reusable pitch intent for planner"
                if knowledge_ok
                else "missing talk intent or contains sensitive content"
            ),
            "feeds": "deck-planner",
        },
        "presentation": {
            "verdict": "candidate" if presentation_ok else "not-suitable",
            "reason": (
                "contains reusable DeckJSON layout/data pattern for renderer"
                if presentation_ok
                else "layout/data is not reusable or contains sensitive content"
            ),
            "feeds": "deck-renderer",
        },
        "sensitive_matches": sensitive,
    }


def split_candidate_payloads(
    *,
    entry_id: str,
    task_id: str,
    slide_key: str,
    slide: dict[str, Any],
    metadata: dict[str, Any],
    outline_slide: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    title = metadata.get("title") or slide_title(slide)
    outline_slide = outline_slide or {}
    notes = parse_notes(slide.get("notes"))
    assessment = assess_reuse_layers(slide, metadata, outline_slide)
    base_source = {
        "level": metadata.get("source_level") or "internal-draft",
        "deck": f"runs/{task_id}/output/deck.json",
        "slide_key": slide_key,
        "owner": metadata.get("owner") or "gtm",
        "reviewer": metadata.get("reviewer", ""),
        "contributor": metadata.get("contributor") or metadata.get("owner") or "gtm",
        "contributed_at": metadata.get("contributed_at") or now_iso(),
    }
    knowledge = {
        "version": "1.0",
        "id": f"know-{entry_id}",
        "status": "candidate",
        "title": title,
        "feeds": "deck-planner",
        "industry": normalize_list(metadata.get("industry") or ["待标注"]),
        "product": normalize_list(metadata.get("product") or ["待标注"]),
        "customer_stage": normalize_list(metadata.get("customer_stage") or ["待标注"]),
        "deck_type": normalize_list(metadata.get("deck_type") or ["待标注"]),
        "planning_unit": {
            "message": first_note_or_plan(notes, outline_slide, "message", slide_text(slide) or title),
            "key_idea": first_note_or_plan(notes, outline_slide, "key_idea", slide_text(slide) or title),
            "emphasis": first_note_or_plan(notes, outline_slide, "emphasis"),
            "talk_track": first_note_or_plan(notes, outline_slide, "talk_track"),
            "proof_needed": list_note_or_plan(notes, outline_slide, "proof_needed", ["evidence"]),
            "asset_need": list_note_or_plan(notes, outline_slide, "asset_need"),
            "risk": list_note_or_plan(notes, outline_slide, "risk", ["risk_flags"]),
        },
        "source": base_source,
        "assessment": assessment["knowledge"],
    }
    presentation = {
        "version": "1.0",
        "id": f"present-{entry_id}",
        "status": "candidate",
        "title": title,
        "feeds": "deck-renderer",
        "thumbnail": metadata.get("thumbnail") or "library/business/thumbnails/pending.svg",
        "tags": normalize_list(metadata.get("tags") or metadata.get("tag") or ["needs-review"]),
        "layout": slide.get("layout"),
        "variant": slide.get("variant", ""),
        "renderer_unit": {
            "slide": slide,
            "insert_suggestion": f"插入为 {slide.get('layout')}{('/' + str(slide.get('variant'))) if slide.get('variant') else ''},再替换客户事实和指标。",
        },
        "source": base_source,
        "assessment": assessment["presentation"],
    }
    return {"knowledge": knowledge, "presentation": presentation}


def mark_reuse_candidate(task_id: str, slide_key: str, metadata: dict[str, Any]) -> dict[str, Any]:
    deck_path = RUNS_DIR / task_id / "output/deck.json"
    if not deck_path.exists():
        raise FileNotFoundError(f"deck.json not found for task: {task_id}")
    deck = read_json(deck_path)
    slide = next((item for item in deck.get("slides", []) if item.get("key") == slide_key), None)
    if not slide:
        raise ValueError(f"slide not found: {slide_key}")
    outline_slide = outline_slide_for_task(task_id, slide_key)

    entry_id = re.sub(r"[^a-z0-9-]+", "-", f"candidate-{task_id}-{slide_key}".lower()).strip("-")[:96]
    entry = {
        "version": "1.0",
        "id": entry_id,
        "title": metadata.get("title") or slide_title(slide),
        "status": "candidate",
        "thumbnail": metadata.get("thumbnail") or "library/business/thumbnails/pending.svg",
        "tags": normalize_list(metadata.get("tags") or metadata.get("tag") or ["needs-review"]),
        "industry": normalize_list(metadata.get("industry") or ["待标注"]),
        "product": normalize_list(metadata.get("product") or ["待标注"]),
        "customer_stage": normalize_list(metadata.get("customer_stage") or ["待标注"]),
        "deck_type": normalize_list(metadata.get("deck_type") or ["待标注"]),
        "value_prop": normalize_list(metadata.get("value_prop") or slide_title(slide)),
        "layout": slide.get("layout"),
        "variant": slide.get("variant", ""),
        "source": {
            "level": metadata.get("source_level") or "internal-draft",
            "deck": f"runs/{task_id}/output/deck.json",
            "slide_key": slide_key,
            "owner": metadata.get("owner") or "gtm",
            "reviewer": metadata.get("reviewer", ""),
            "contributor": metadata.get("contributor") or metadata.get("owner") or "gtm",
            "contributed_at": metadata.get("contributed_at") or now_iso(),
        },
        "slide": slide,
    }
    target = CANDIDATES_DIR / f"{entry_id}.json"
    write_json(target, entry)
    split_payloads = split_candidate_payloads(
        entry_id=entry_id,
        task_id=task_id,
        slide_key=slide_key,
        slide=slide,
        metadata=metadata,
        outline_slide=outline_slide,
    )
    split_paths: dict[str, str] = {}
    if split_payloads["knowledge"]["assessment"]["verdict"] == "candidate":
        target_knowledge = KNOWLEDGE_CANDIDATES_DIR / f"{split_payloads['knowledge']['id']}.json"
        write_json(target_knowledge, split_payloads["knowledge"])
        split_paths["knowledge"] = repo_rel(target_knowledge)
    if split_payloads["presentation"]["assessment"]["verdict"] == "candidate":
        target_presentation = PRESENTATION_CANDIDATES_DIR / f"{split_payloads['presentation']['id']}.json"
        write_json(target_presentation, split_payloads["presentation"])
        split_paths["presentation"] = repo_rel(target_presentation)
    check = validate_entry(entry, seen_ids=set(), seen_slide_keys=set())
    return {
        "path": repo_rel(target),
        "entry": summarize_entry(entry),
        "issues": check,
        "split_assessment": assess_reuse_layers(slide, metadata, outline_slide),
        "split_candidate_paths": split_paths,
    }


def candidate_file(candidate_id: str) -> Path:
    safe = Path(candidate_id).name.removesuffix(".json")
    path = CANDIDATES_DIR / f"{safe}.json"
    if path.exists():
        return path
    direct = Path(candidate_id)
    if direct.exists():
        return direct
    raise FileNotFoundError(candidate_id)


def approve_candidate(
    candidate_id: str,
    *,
    reviewer: str,
    source_level: str = "internal-approved",
    thumbnail: str = "",
) -> dict[str, Any]:
    source_path = candidate_file(candidate_id)
    entry = read_json(source_path)
    if thumbnail:
        entry["thumbnail"] = thumbnail
    if str(entry.get("thumbnail", "")).endswith("pending.svg"):
        raise ValueError("approved candidates need a final thumbnail")
    entry["status"] = "approved"
    entry.setdefault("source", {})["level"] = source_level
    entry["source"]["reviewer"] = reviewer
    entry["source"]["approved_at"] = now_iso()
    if entry["id"].startswith("candidate-"):
        entry["id"] = "biz-" + entry["id"].removeprefix("candidate-")

    issues = validate_entry(entry, seen_ids=set(), seen_slide_keys=set())
    if any(issue["severity"] == "error" for issue in issues):
        return {"ok": False, "entry": summarize_entry(entry), "issues": issues}

    target = BUSINESS_LIBRARY / f"{entry['id']}.json"
    write_json(target, entry)
    source_path.unlink()
    return {"ok": True, "path": repo_rel(target), "entry": summarize_entry(entry), "issues": issues}


def pptx_slide_count(path: Path) -> int:
    if path.suffix.lower() != ".pptx":
        return 1
    try:
        with zipfile.ZipFile(path) as zf:
            slides = [
                name for name in zf.namelist()
                if re.match(r"ppt/slides/slide\d+\.xml$", name)
            ]
    except zipfile.BadZipFile:
        return 1
    return max(1, len(slides))


def pptx_slide_texts(path: Path) -> dict[int, list[str]]:
    if path.suffix.lower() != ".pptx":
        return {}
    out: dict[int, list[str]] = {}
    try:
        with zipfile.ZipFile(path) as zf:
            slide_names = sorted(
                [name for name in zf.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", name)],
                key=lambda item: int(re.search(r"slide(\d+)\.xml$", item).group(1)),
            )
            for name in slide_names:
                page = int(re.search(r"slide(\d+)\.xml$", name).group(1))
                try:
                    root = ET.fromstring(zf.read(name))
                except ET.ParseError:
                    out[page] = []
                    continue
                texts = []
                for el in root.iter():
                    if (el.tag.endswith("}t") or el.tag == "t") and el.text and el.text.strip():
                        texts.append(el.text.strip())
                out[page] = texts
    except zipfile.BadZipFile:
        return {}
    return out


def wrap_svg_lines(text: str, max_chars: int = 28, max_lines: int = 5) -> list[str]:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []
    lines: list[str] = []
    current = ""
    for char in normalized:
        current += char
        if len(current) >= max_chars:
            lines.append(current)
            current = ""
        if len(lines) >= max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    return lines[:max_lines]


def write_ppt_upload_thumbnail(
    *,
    entry_id: str,
    title: str,
    page: int,
    total: int,
    texts: list[str],
) -> str:
    PPT_UPLOAD_THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)
    target = PPT_UPLOAD_THUMBNAILS_DIR / f"{entry_id}.svg"
    preview = " · ".join(texts[:8]) or "待解析 PPT 页面"
    title_lines = wrap_svg_lines(title, max_chars=24, max_lines=2)
    preview_lines = wrap_svg_lines(preview, max_chars=30, max_lines=4)
    title_tspans = "\n".join(
        f'<text x="40" y="{82 + i * 34}" fill="#fff" font-size="28" font-weight="700">{html.escape(line)}</text>'
        for i, line in enumerate(title_lines)
    )
    preview_y = 180
    preview_tspans = "\n".join(
        f'<text x="40" y="{preview_y + i * 30}" fill="rgba(255,255,255,0.72)" font-size="22">{html.escape(line)}</text>'
        for i, line in enumerate(preview_lines)
    )
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#111B3D"/>
      <stop offset="0.55" stop-color="#0B1024"/>
      <stop offset="1" stop-color="#123D45"/>
    </linearGradient>
  </defs>
  <rect width="640" height="360" fill="url(#bg)"/>
  <circle cx="560" cy="66" r="92" fill="#33D6C0" opacity="0.18"/>
  <circle cx="82" cy="310" r="120" fill="#3C7FFF" opacity="0.16"/>
  <rect x="24" y="24" width="592" height="312" rx="18" fill="none" stroke="rgba(255,255,255,0.16)"/>
  <text x="40" y="48" fill="#33D6C0" font-size="18" font-weight="700">PPT LIBRARY · P{page:02d}/{total:02d}</text>
  {title_tspans}
  {preview_tspans}
  <text x="40" y="318" fill="rgba(255,255,255,0.48)" font-size="18">registered local candidate · needs review</text>
</svg>
'''
    target.write_text(svg, encoding="utf-8")
    return repo_rel(target)


def register_ppt_upload(
    ppt_path: Path,
    metadata: dict[str, Any],
    *,
    pages: list[int] | None = None,
) -> dict[str, Any]:
    """Register a user-selected PPT/PPTX as slide-library selectable entries.

    This does not convert PPT pages to H5. It preserves the PPT as a source
    artifact and creates placeholder replica slide records so GTM users can
    search/select pages for later recognizer/renderer processing.
    """
    if not ppt_path.exists() or not ppt_path.is_file():
        raise FileNotFoundError(str(ppt_path))
    suffix = ppt_path.suffix.lower()
    if suffix not in {".ppt", ".pptx"}:
        raise ValueError("register-ppt expects a .ppt or .pptx file")

    digest = hashlib.sha256(ppt_path.read_bytes()).hexdigest()[:16]
    title = metadata.get("title") or ppt_path.stem
    total = pptx_slide_count(ppt_path)
    selected_pages = pages or list(range(1, total + 1))
    rel_ppt = repo_rel(ppt_path) if ppt_path.resolve().is_relative_to(REPO) else str(ppt_path.resolve())
    safe_title = re.sub(r"[^a-z0-9-]+", "-", title.lower()).strip("-") or "ppt-upload"
    entries = []
    issues_by_entry = []
    texts_by_page = pptx_slide_texts(ppt_path)
    contributed_at = metadata.get("contributed_at") or now_iso()
    for page in selected_pages:
        if page < 1 or page > total:
            issues_by_entry.append({
                "page": page,
                "issues": [{"severity": "error", "code": "LIB-PPT-PAGE", "message": f"page {page} outside 1..{total}"}],
            })
            continue
        slide_key = f"ppt-{digest}-p{page:03d}"
        entry_id = re.sub(r"[^a-z0-9-]+", "-", f"upload-{safe_title}-{digest}-p{page:03d}").strip("-")[:96]
        summary = metadata.get("summary") or f"用户上传 PPT 自选页 {page}/{total}: {title}"
        thumbnail = metadata.get("thumbnail") or write_ppt_upload_thumbnail(
            entry_id=entry_id,
            title=f"{title} · P{page:02d}",
            page=page,
            total=total,
            texts=texts_by_page.get(page, []),
        )
        entry = {
            "version": "1.0",
            "id": entry_id,
            "title": f"{title} · P{page:02d}",
            "status": "candidate",
            "thumbnail": thumbnail,
            "tags": normalize_list(metadata.get("tags") or metadata.get("tag") or ["ppt-upload", "needs-review"]),
            "industry": normalize_list(metadata.get("industry") or ["待标注"]),
            "product": normalize_list(metadata.get("product") or ["待标注"]),
            "customer_stage": normalize_list(metadata.get("customer_stage") or ["待标注"]),
            "deck_type": normalize_list(metadata.get("deck_type") or ["用户自选 PPT"]),
            "value_prop": normalize_list(metadata.get("value_prop") or title),
            "layout": "replica",
            "variant": "",
            "source": {
                "level": metadata.get("source_level") or "internal-draft",
                "deck": rel_ppt,
                "ppt": rel_ppt,
                "slide_key": slide_key,
                "page": page,
                "owner": metadata.get("owner") or "gtm",
                "reviewer": metadata.get("reviewer", ""),
                "contributor": metadata.get("contributor") or metadata.get("owner") or "gtm",
                "contributed_at": contributed_at,
                "uploaded_at": contributed_at,
            },
            "permission_status": metadata.get("permission_status") or "needs_review",
            "slide": {
                "key": slide_key,
                "layout": "replica",
                "data": {
                    "page_image": thumbnail,
                    "alt": summary,
                    "source_page": page,
                },
                "notes": f"message: {summary}",
            },
        }
        target = PPT_UPLOADS_DIR / f"{entry_id}.json"
        write_json(target, entry)
        issues = validate_entry(entry, seen_ids=set(), seen_slide_keys=set())
        entries.append({"path": repo_rel(target), "entry": summarize_entry(entry), "issues": issues})
    return {
        "ok": not any(any(issue["severity"] == "error" for issue in item.get("issues", [])) for item in entries + issues_by_entry),
        "source": rel_ppt,
        "slide_count": total,
        "registered": entries,
        "skipped": issues_by_entry,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    search = sub.add_parser("search", help="search reusable business slides")
    search.add_argument("--query", default="")
    search.add_argument("--industry", default="")
    search.add_argument("--product", default="")
    search.add_argument("--customer-stage", default="")
    search.add_argument("--deck-type", default="")
    search.add_argument("--value-prop", default="")
    search.add_argument("--layout", default="")
    search.add_argument("--include-candidates", action="store_true")
    search.add_argument("--limit", type=int, default=20)

    validate = sub.add_parser("validate", help="run slide library gate")
    validate.add_argument("--approved-only", action="store_true")

    mark = sub.add_parser("mark-reuse", help="create a review candidate from a generated task")
    mark.add_argument("--task-id", required=True)
    mark.add_argument("--slide-key", required=True)
    mark.add_argument("--title")
    mark.add_argument("--industry", action="append", default=[])
    mark.add_argument("--product", action="append", default=[])
    mark.add_argument("--customer-stage", action="append", default=[])
    mark.add_argument("--deck-type", action="append", default=[])
    mark.add_argument("--value-prop", action="append", default=[])
    mark.add_argument("--tag", action="append", default=[])
    mark.add_argument("--source-level", default="internal-draft")
    mark.add_argument("--owner", default="gtm")
    mark.add_argument("--reviewer", default="")
    mark.add_argument("--contributor", default="")
    mark.add_argument("--contributed-at", default="")

    approve = sub.add_parser("approve-candidate", help="approve a review candidate into the business slide library")
    approve.add_argument("candidate_id")
    approve.add_argument("--reviewer", required=True)
    approve.add_argument("--source-level", default="internal-approved", choices=sorted(ALLOWED_SOURCE_LEVELS - {"internal-draft"}))
    approve.add_argument("--thumbnail", default="", help="final thumbnail path; required if candidate still uses pending.svg")

    upload = sub.add_parser("register-ppt", help="register a user-uploaded PPT/PPTX as selectable slide-library candidates")
    upload.add_argument("ppt_path", type=Path)
    upload.add_argument("--page", action="append", type=int, default=[], help="1-based slide page to register; repeatable. Defaults to all pages.")
    upload.add_argument("--title")
    upload.add_argument("--summary", default="")
    upload.add_argument("--thumbnail", default="")
    upload.add_argument("--industry", action="append", default=[])
    upload.add_argument("--product", action="append", default=[])
    upload.add_argument("--customer-stage", action="append", default=[])
    upload.add_argument("--deck-type", action="append", default=[])
    upload.add_argument("--value-prop", action="append", default=[])
    upload.add_argument("--tag", action="append", default=[])
    upload.add_argument("--source-level", default="internal-draft")
    upload.add_argument("--owner", default="gtm")
    upload.add_argument("--reviewer", default="")
    upload.add_argument("--contributor", default="")
    upload.add_argument("--contributed-at", default="")
    upload.add_argument("--permission-status", default="needs_review")

    args = parser.parse_args(argv)
    if args.command == "search":
        rows = search_slides(
            query=args.query,
            industry=args.industry,
            product=args.product,
            customer_stage=args.customer_stage,
            deck_type=args.deck_type,
            value_prop=args.value_prop,
            layout=args.layout,
            include_candidates=args.include_candidates,
            limit=args.limit,
        )
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    if args.command == "validate":
        result = validate_library(include_candidates=not args.approved_only)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1
    if args.command == "mark-reuse":
        result = mark_reuse_candidate(
            args.task_id,
            args.slide_key,
            {
                "title": args.title,
                "industry": args.industry,
                "product": args.product,
                "customer_stage": args.customer_stage,
                "deck_type": args.deck_type,
                "value_prop": args.value_prop,
                "tags": args.tag,
                "source_level": args.source_level,
                "owner": args.owner,
                "reviewer": args.reviewer,
                "contributor": args.contributor or args.owner or "gtm",
                "contributed_at": args.contributed_at or now_iso(),
            },
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if not any(issue["severity"] == "error" for issue in result["issues"]) else 1
    if args.command == "approve-candidate":
        result = approve_candidate(
            args.candidate_id,
            reviewer=args.reviewer,
            source_level=args.source_level,
            thumbnail=args.thumbnail,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1
    if args.command == "register-ppt":
        result = register_ppt_upload(
            args.ppt_path,
            {
                "title": args.title,
                "summary": args.summary,
                "thumbnail": args.thumbnail,
                "industry": args.industry,
                "product": args.product,
                "customer_stage": args.customer_stage,
                "deck_type": args.deck_type,
                "value_prop": args.value_prop,
                "tags": args.tag,
                "source_level": args.source_level,
                "owner": args.owner,
                "reviewer": args.reviewer,
                "contributor": args.contributor or args.owner or "gtm",
                "contributed_at": args.contributed_at or now_iso(),
                "permission_status": args.permission_status,
            },
            pages=args.page,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1
    raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
