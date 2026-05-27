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
    renderer_codes = ["R-OVERFLOW", "R-OVERLAP", "R-VIS", "R06", "R20", "L1", "L2", "L4", "R10", "R12", "R47", "R48", "T00", "T01", "T02", "T03", "R-FEEDBACK", "R-DOM", "R-KEY"]
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
    blockers: list[str] = []
    if h5_proc.returncode != 0:
        blockers.append("H5 check-only failed")
    if not deck_validation["ok"]:
        blockers.append("DeckJSON validation failed")
    if deck_json and not talk["ok"]:
        blockers.append("Talk-readiness inspection failed")

    if h5_proc.returncode == 0 and deck_validation["ok"] and (not deck_json or talk["ok"]):
        verdict = "pass"
    elif h5_proc.returncode != 0:
        routing = classify_routing(h5_text)
        verdict = "replan-required" if routing.get("deck-planner") and not routing.get("deck-renderer") else "rerender-required"
    elif not deck_validation["ok"]:
        verdict = "rerender-required"
    else:
        verdict = "replan-required"
    routing = classify_routing(h5_text)

    payload = {
        "h5_checkonly_summary": {
            "status": "PASS" if h5_proc.returncode == 0 else "FAIL",
            "errors": errors,
            "warnings": warns,
            "flags": flags,
            "exit_code": h5_proc.returncode,
            "report_path": str(h5_report),
        },
        "deck_validation": deck_validation,
        "sidecars": sidecars,
        "talk_readiness": talk,
        "verdict": verdict,
        "blockers": blockers,
        "warnings": [] if warns == 0 else [f"H5 check-only reported {warns} warning(s)"],
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
        },
    }
    write_json(json_report, payload)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(build_markdown(payload), encoding="utf-8")
    print(report)
    return 0 if verdict == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
