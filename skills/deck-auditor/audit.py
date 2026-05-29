#!/usr/bin/env python3
"""Cyrus quality gate for rendered H5 decks.

This wraps the H5 check-only validator and adds the Cyrus-level acceptance
shape expected by the lark-deck-cyrus controller: verdict, routing, reuse
assessment, and ingestion handoff. It does not modify the input deck.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
CHECK_ONLY = REPO / "skills/deck-renderer/assets/check-only.sh"
VALIDATE_DECK = REPO / "skills/deck-renderer/deck-json/validate-deck.py"


def run(cmd: list[str], log_path: Path | None = None) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(cmd, cwd=REPO, text=True, capture_output=True)
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            "$ " + " ".join(shlex.quote(part) for part in cmd) + "\n\n"
            + "## stdout\n\n" + (proc.stdout or "")
            + "\n## stderr\n\n" + (proc.stderr or ""),
            encoding="utf-8",
        )
    return proc


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_h5_counts(report_text: str) -> tuple[int, int]:
    match = re.search(r"总计\*\*:.*?error\s+(\d+)\s+条.*?warn\s+(\d+)\s+条", report_text, re.S)
    if match:
        return int(match.group(1)), int(match.group(2))
    errors = len(re.findall(r"^- ✗ ", report_text, flags=re.M))
    warns = len(re.findall(r"^- ! ", report_text, flags=re.M))
    return errors, warns


def classify_routing(report_text: str) -> dict[str, list[str]]:
    renderer_codes = ["R-OVERFLOW", "R-OVERLAP", "R-VIS", "R06", "R20", "L1", "L2", "L4", "R10", "R12", "R47", "R48", "R-CSSVAR", "R-BULLET-DASH", "T00", "T01", "T02", "T03", "R-FEEDBACK", "R-DOM", "R-KEY"]
    planner_codes = ["R-HIERARCHY", "R-ECHO", "R-LANG"]
    routing = {"deck-renderer": [], "deck-planner": [], "deck-ingestor": []}
    for code in renderer_codes:
        if code in report_text:
            routing["deck-renderer"].append(code)
    for code in planner_codes:
        if code in report_text:
            routing["deck-planner"].append(code)
    return {key: sorted(set(value)) for key, value in routing.items() if value}


def sidecar_status(html: Path, deck_json: Path | None) -> dict[str, bool]:
    base = html.parent
    return {
        "index_html": html.exists(),
        "deck_json": bool(deck_json and deck_json.exists()),
        "texts_md": (base / "texts.md").exists(),
        "feedback_md": (base / "FEEDBACK.md").exists(),
    }


def talk_readiness(deck_json: Path | None) -> dict[str, Any]:
    if not deck_json or not deck_json.exists():
        return {"ok": False, "reason": "deck.json missing; narrative arc cannot be inspected"}
    deck = read_json(deck_json)
    slides = [slide for slide in deck.get("slides", []) if isinstance(slide, dict) and not slide.get("_disabled")]
    keys = [str(slide.get("key") or "") for slide in slides]
    has_open = bool(slides and slides[0].get("layout") == "cover")
    has_close = bool(slides and slides[-1].get("layout") == "end")
    has_notes = sum(1 for slide in slides if str(slide.get("notes") or "").strip())
    ok = len(slides) >= 3 and has_open and has_close and has_notes >= max(1, len(slides) // 2)
    return {
        "ok": ok,
        "slide_count": len(slides),
        "has_cover": has_open,
        "has_close": has_close,
        "slides_with_notes": has_notes,
        "slide_keys": keys,
        "reason": "" if ok else "deck arc needs cover/end and notes on at least half the slides",
    }


def _walk_text(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        parts: list[str] = []
        for item in value.values():
            parts.extend(_walk_text(item))
        return parts
    if isinstance(value, list):
        parts = []
        for item in value:
            parts.extend(_walk_text(item))
        return parts
    return []


def _matches_signal(text_lower: str, term: str) -> bool:
    needle = term.lower()
    if re.fullmatch(r"[a-z0-9][a-z0-9+-]*", needle):
        return re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", text_lower) is not None
    return needle in text_lower


def _signal_hits(text_lower: str, terms: list[str]) -> list[str]:
    return [term for term in terms if _matches_signal(text_lower, term)]


def _slide_signature(slide: dict[str, Any]) -> str:
    layout = str(slide.get("layout") or "")
    variant = str(slide.get("variant") or slide.get("style") or "")
    data = slide.get("data") if isinstance(slide.get("data"), dict) else {}
    data_variant = str(data.get("variant") or data.get("type") or "")
    return f"{layout}/{variant or data_variant}".strip("/")


def design_readiness(deck_json: Path | None) -> dict[str, Any]:
    """Cyrus semantic/visual-readiness gate for high-stakes enterprise AI decks.

    H5 validation catches broken DOM, typography, overflow, and screenshots.
    It cannot tell whether a manufacturing AI deck is just a rotation of safe
    card/table/process templates. This gate keeps the Zhongji-style lesson as
    executable policy: similar decks need concrete scenes and web-native visual
    anchors before they are considered ready to publish or ingest.
    """
    if not deck_json or not deck_json.exists():
        return {"ok": True, "applied": False, "reason": "deck.json missing; design-readiness gate skipped"}

    deck = read_json(deck_json)
    slides = [slide for slide in deck.get("slides", []) if isinstance(slide, dict) and not slide.get("_disabled")]
    text_blob = "\n".join(_walk_text(deck))
    manufacturing_core_terms = [
        "中际旭创",
        "innolight",
        "npi",
        "光模块",
        "高端制造",
        "制造业",
        "工厂",
        "产线",
        "车间",
        "良率",
        "mes",
        "plm",
    ]
    manufacturing_context_terms = [
        "质量异常",
        "供应链",
        "工程师",
    ]
    ai_terms = [
        "数字员工",
        "智能体",
        "大模型",
        "人工智能",
        "agent",
        "agents",
        "ai",
        "aigc",
        "genai",
        "llm",
    ]
    text_lower = text_blob.lower()
    manufacturing_hits = _signal_hits(text_lower, manufacturing_core_terms)
    manufacturing_context_hits = _signal_hits(text_lower, manufacturing_context_terms)
    ai_hits = _signal_hits(text_lower, ai_terms)
    signals = manufacturing_hits + manufacturing_context_hits + ai_hits
    manufacturing_signal = bool(manufacturing_hits)
    ai_signal = bool(ai_hits)
    applied = manufacturing_signal and ai_signal and len(slides) >= 8
    if not applied:
        return {
            "ok": True,
            "applied": False,
            "reason": "enterprise-manufacturing AI signals not strong enough for this specialized gate",
            "signals": signals,
        }

    body_slides = [
        slide
        for slide in slides
        if str(slide.get("layout") or "") not in {"cover", "agenda", "end"}
    ]
    generic_signatures = {
        "content/3up",
        "content/matrix",
        "content/blocks",
        "flow/process",
        "flow/timeline",
        "stats/row",
        "table",
        "arch-stack",
        "logo-wall",
    }
    rich_layouts = {"image-text", "raw", "replica", "iframe-embed"}
    rich_signatures = {
        "content/story-case",
        "content/before-after",
        "content/2col",
        "stats/hero",
        "stats/waterfall",
        "flow/swim",
        "flow/tree",
    }
    scene_keywords = [
        "的一天",
        "案例",
        "陪练",
        "仪表盘",
        "dashboard",
        "console",
        "雷达",
        "demo",
        "原型",
        "工作台",
        "战情室",
        "复盘助手",
        "异常闭环",
        "review panel",
        "scorecard",
    ]

    rich_visual_slides: list[str] = []
    scene_anchor_slides: list[str] = []
    generic_run = 0
    max_generic_run = 0
    signatures: list[str] = []
    for slide in body_slides:
        key = str(slide.get("key") or slide.get("slide_key") or "")
        layout = str(slide.get("layout") or "")
        signature = _slide_signature(slide)
        signatures.append(signature)
        if layout in rich_layouts or signature in rich_signatures:
            rich_visual_slides.append(key or signature)
        slide_text = "\n".join(_walk_text(slide)).lower()
        if any(keyword.lower() in slide_text for keyword in scene_keywords):
            scene_anchor_slides.append(key or signature)
        if signature in generic_signatures or layout in generic_signatures:
            generic_run += 1
            max_generic_run = max(max_generic_run, generic_run)
        elif layout in {"section", "quote"}:
            generic_run = 0
        else:
            generic_run = 0

    blockers: list[str] = []
    if len(rich_visual_slides) < 2:
        blockers.append("enterprise AI deck needs at least 2 concrete visual-anchor slides: story-case, 2col mock, image-text, iframe/raw prototype, hero stats, swim/tree, or dashboard-like page")
    if max_generic_run > 3:
        blockers.append(f"too many consecutive generic schema pages ({max_generic_run}); insert a scene/prototype/case/quote/section breath page")
    if not scene_anchor_slides:
        blockers.append("missing a named business scene or artifact: protagonist workday, case, dashboard, radar, prototype, review panel, or anomaly-closure page")

    return {
        "ok": not blockers,
        "applied": True,
        "reason": "ready" if not blockers else "enterprise AI design gate failed",
        "signals": signals,
        "slide_count": len(slides),
        "body_slide_count": len(body_slides),
        "rich_visual_slides": rich_visual_slides,
        "scene_anchor_slides": scene_anchor_slides,
        "max_generic_run": max_generic_run,
        "signatures": signatures,
        "blockers": blockers,
    }


def interaction_readiness(deck_json: Path | None) -> dict[str, Any]:
    """Catch fake controls in generated deck artifacts.

    Visual validation proves a slide is readable, but not that an affordance is
    honest. If a page draws tabs/segmented controls in a product mock, the H5
    artifact should either wire them with the runtime data-tab-* contract or
    explicitly declare them static.
    """
    if not deck_json or not deck_json.exists():
        return {"ok": True, "applied": False, "reason": "deck.json missing; interaction-readiness gate skipped"}

    deck = read_json(deck_json)
    slides = [slide for slide in deck.get("slides", []) if isinstance(slide, dict) and not slide.get("_disabled")]
    blockers: list[str] = []
    inspected: list[str] = []
    tab_class_re = re.compile(r'class=["\'][^"\']*\b[a-z0-9_-]*tabs?[a-z0-9_-]*\b[^"\']*["\']', re.I)
    tab_role_re = re.compile(r'role=["\']tab(?:list)?["\']', re.I)

    for slide in slides:
        key = str(slide.get("key") or slide.get("slide_key") or f"slide-{len(inspected) + 1}")
        blob = "\n".join(_walk_text(slide))
        has_tab_shape = len(tab_class_re.findall(blob)) >= 2 or bool(tab_role_re.search(blob))
        if not has_tab_shape:
            continue
        inspected.append(key)
        lowered = blob.lower()
        if "data-tab-target" in lowered or "data-static-tabs" in lowered:
            continue
        blockers.append(
            f"{key}: tab-like UI is static; add data-tab-group/data-tab-target/data-tab-panel, or mark data-static-tabs with a reason"
        )

    return {
        "ok": not blockers,
        "applied": bool(inspected),
        "reason": "ready" if not blockers else "interaction affordance gate failed",
        "inspected_slides": inspected,
        "blockers": blockers,
    }


def build_markdown(payload: dict[str, Any]) -> str:
    h5 = payload["h5_checkonly_summary"]
    lines = [
        f"H5 CHECK-ONLY: {h5['status']}, {h5['errors']} errors / {h5['warnings']} warns. Cyrus verdict: {payload['verdict']}.",
        "",
        "# Cyrus Audit Report",
        "",
        "## H5 check-only summary",
        "",
        f"- flags: {', '.join(h5['flags']) or 'default'}",
        f"- report: `{h5['report_path']}`",
        f"- exit_code: {h5['exit_code']}",
        f"- visual_requested: {h5.get('visual_requested')}",
        f"- visual_unavailable: {h5.get('visual_unavailable')}",
        "",
        "## Structure and delivery",
    ]
    for key, value in payload["sidecars"].items():
        lines.append(f"- {key}: {'yes' if value else 'no'}")
    talk = payload["talk_readiness"]
    lines.extend([
        "",
        "## Talk readiness",
        "",
        f"- ok: {talk.get('ok')}",
        f"- slide_count: {talk.get('slide_count', 0)}",
        f"- reason: {talk.get('reason') or 'ready'}",
        "",
        "## Design readiness",
        "",
    ])
    design = payload.get("design_readiness", {})
    lines.extend([
        f"- applied: {design.get('applied')}",
        f"- ok: {design.get('ok')}",
        f"- reason: {design.get('reason') or 'ready'}",
        f"- rich_visual_slides: {len(design.get('rich_visual_slides') or [])}",
        f"- scene_anchor_slides: {len(design.get('scene_anchor_slides') or [])}",
        f"- max_generic_run: {design.get('max_generic_run', 0)}",
    ])
    for blocker in design.get("blockers") or []:
        lines.append(f"- design_blocker: {blocker}")
    interaction = payload.get("interaction_readiness", {})
    lines.extend([
        "",
        "## Interaction readiness",
        "",
        f"- applied: {interaction.get('applied')}",
        f"- ok: {interaction.get('ok')}",
        f"- reason: {interaction.get('reason') or 'ready'}",
        f"- inspected_slides: {len(interaction.get('inspected_slides') or [])}",
    ])
    for blocker in interaction.get("blockers") or []:
        lines.append(f"- interaction_blocker: {blocker}")
    lines.extend([
        "",
        "## Routing",
    ])
    if payload["routing"]:
        for skill, codes in payload["routing"].items():
            lines.append(f"- `{skill}`: {', '.join(codes)}")
    else:
        lines.append("- no blockers routed")
    lines.extend([
        "",
        "## Reuse assessment",
        "",
        f"- knowledge_candidate: {payload['reuse_assessment']['knowledge_candidate']}",
        f"- presentation_candidate: {payload['reuse_assessment']['presentation_candidate']}",
        f"- reason: {payload['reuse_assessment']['reason']}",
        "",
        "## Ingestion handoff",
        "",
        f"- ready: {payload['ingestion_handoff']['ready']}",
        f"- reason: {payload['ingestion_handoff']['reason']}",
    ])
    for item in payload["blockers"]:
        lines.append(f"- blocker: {item}")
    lines.append("")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("html", type=Path)
    parser.add_argument("--deck-json", type=Path)
    parser.add_argument("--report", type=Path, help="Cyrus audit markdown path")
    parser.add_argument("--json-report", type=Path, help="Structured audit JSON path")
    parser.add_argument("--h5-report", type=Path, help="Underlying H5 check-only markdown path")
    parser.add_argument("--log", type=Path)
    parser.add_argument("--strict", action="store_true", default=True)
    parser.add_argument("--no-strict", action="store_false", dest="strict")
    parser.add_argument("--visual", action="store_true")
    parser.add_argument("--no-visual", action="store_true")
    parser.add_argument("--gate", choices=["ingest"], help="Run a specialized H5 gate")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    html = args.html.resolve()
    deck_json = args.deck_json.resolve() if args.deck_json else None
    report = args.report or (html.parent / "AUDIT_REPORT.md")
    json_report = args.json_report or (html.parent / "audit-report.json")
    h5_report = args.h5_report or (html.parent / "H5_CHECKONLY_REPORT.md")

    cmd = ["bash", str(CHECK_ONLY), str(html)]
    flags: list[str] = []
    if args.gate:
        cmd.extend(["--gate", args.gate])
        flags.append(f"gate:{args.gate}")
    elif args.strict:
        cmd.append("--strict")
        flags.append("strict")
    if args.visual and not args.no_visual:
        cmd.append("--visual")
        flags.append("visual")
    cmd.extend(["--report", str(h5_report)])
    h5_proc = run(cmd, args.log)
    h5_text = h5_report.read_text(encoding="utf-8") if h5_report.exists() else (h5_proc.stdout + h5_proc.stderr)
    errors, warns = parse_h5_counts(h5_text)
    visual_requested = bool(args.visual and not args.no_visual)
    visual_unavailable = visual_requested and "visual checks could not run" in h5_text

    deck_validation = {"ok": True, "exit_code": 0, "message": ""}
    if deck_json and deck_json.exists():
        proc = run([sys.executable, str(VALIDATE_DECK), str(deck_json), "--strict"])
        deck_validation = {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "message": (proc.stdout + proc.stderr).strip(),
        }
    elif deck_json:
        deck_validation = {"ok": False, "exit_code": 2, "message": f"deck.json not found: {deck_json}"}

    sidecars = sidecar_status(html, deck_json)
    talk = talk_readiness(deck_json)
    design = design_readiness(deck_json)
    interaction = interaction_readiness(deck_json)
    blockers: list[str] = []
    if h5_proc.returncode != 0:
        blockers.append("H5 check-only failed")
    if visual_unavailable:
        blockers.append("Visual audit requested but did not run")
    if not deck_validation["ok"]:
        blockers.append("DeckJSON validation failed")
    if deck_json and not talk["ok"]:
        blockers.append("Talk-readiness inspection failed")
    if deck_json and not design["ok"]:
        blockers.append("Enterprise AI design-readiness inspection failed")
    if deck_json and not interaction["ok"]:
        blockers.append("Interaction affordance inspection failed")

    if h5_proc.returncode == 0 and not visual_unavailable and deck_validation["ok"] and (not deck_json or (talk["ok"] and design["ok"] and interaction["ok"])):
        verdict = "pass"
    elif h5_proc.returncode != 0 or visual_unavailable:
        routing = classify_routing(h5_text)
        verdict = "replan-required" if routing.get("deck-planner") and not routing.get("deck-renderer") else "rerender-required"
    elif not deck_validation["ok"]:
        verdict = "rerender-required"
    else:
        verdict = "replan-required"
    routing = classify_routing(h5_text)
    if not design["ok"]:
        routing.setdefault("deck-planner", []).append("C-DESIGN-SCENE")
        routing.setdefault("deck-renderer", []).append("C-DESIGN-VISUAL")
        routing = {key: sorted(set(value)) for key, value in routing.items() if value}
    if not interaction["ok"]:
        routing.setdefault("deck-planner", []).append("C-INTERACTION-AFFORDANCE")
        routing.setdefault("deck-renderer", []).append("C-INTERACTION-WIRE")
        routing = {key: sorted(set(value)) for key, value in routing.items() if value}

    payload = {
        "h5_checkonly_summary": {
            "status": "PASS" if h5_proc.returncode == 0 and not visual_unavailable else "FAIL",
            "errors": errors,
            "warnings": warns,
            "flags": flags,
            "exit_code": h5_proc.returncode,
            "report_path": str(h5_report),
            "visual_requested": visual_requested,
            "visual_unavailable": visual_unavailable,
        },
        "deck_validation": deck_validation,
        "sidecars": sidecars,
        "talk_readiness": talk,
        "design_readiness": design,
        "interaction_readiness": interaction,
        "verdict": verdict,
        "blockers": blockers,
        "warnings": (
            ([] if warns == 0 else [f"H5 check-only reported {warns} warning(s)"])
            + (["Visual audit could not run in this environment"] if visual_unavailable else [])
        ),
        "routing": routing,
        "reuse_assessment": {
            "knowledge_candidate": verdict == "pass",
            "presentation_candidate": verdict == "pass",
            "reason": "auditor passed" if verdict == "pass" else "blocked until audit verdict is pass",
        },
        "ingestion_handoff": {
            "ready": verdict == "pass",
            "reason": "ready for user-confirmed ingestion" if verdict == "pass" else "do not ingest failed deck/material candidates",
            "deck_json": str(deck_json) if deck_json else "",
            "html": str(html),
            "target_skill": "deck-ingestor",
        },
        "validation": {
            "schema": "skills/lark-deck-cyrus/schema/audit-report.schema.json",
            "validated": False,
        },
    }
    write_json(json_report, payload)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(build_markdown(payload), encoding="utf-8")
    print(report)
    return 0 if verdict == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
