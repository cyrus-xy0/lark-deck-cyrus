#!/usr/bin/env python3
"""Run the confirmed lark-deck-cyrus generation pipeline for one run folder.

This is the deterministic "after user confirms outline" path:

  preflight -> compile outline -> render HTML -> strict audit -> pitch rehearsal
  -> publish standalone Feishu/Miaobi Magic Page
  -> package editable zip
  -> PIPELINE_REPORT.md

The default is linked-mode HTML with local assets and local package-cache
assets. Inline single-file delivery is opt-in because it has a different
validator surface and must pass its own post-inline audit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import sys
from datetime import date
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
PREFLIGHT = REPO / "skills/deck-renderer/assets/preflight.sh"
COMPILE_OUTLINE = REPO / "skills/deck-renderer/deck-json/compile-outline.py"
RENDER_DECK = REPO / "skills/deck-renderer/deck-json/render-deck.py"
AUDITOR = REPO / "skills/deck-auditor/audit.py"
PITCH_SIMULATOR = REPO / "skills/pitch-simulator/simulate-pitch.py"
PITCH_VALIDATOR = REPO / "skills/pitch-simulator/validate-rehearsal.py"
PACKAGE = REPO / "skills/deck-renderer/assets/package-deliverable.sh"
DEFAULT_MAGIC_PAGE_PUBLISHER = Path("/Users/bytedance/.codex/skills/publish-magic-page/publish.js")
DEFAULT_MAGIC_DOC_CREATOR = Path("/Users/bytedance/.codex/skills/generate-magic-doc/scripts/create_magic_doc.mjs")
DEFAULT_MAGIC_BASE_URL = "https://magic.solutionsuite.cn"

MEETING_TYPES = {
    "first-meeting",
    "solution-pitch",
    "poc-kickoff",
    "renewal",
    "investor-pitch",
    "internal-alignment",
    "review",
    "unknown",
    "POC 启动提案",
    "POC启动提案",
    "试点启动",
}


def run(cmd: list[str], log_path: Path) -> subprocess.CompletedProcess[str]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(cmd, cwd=REPO, text=True, capture_output=True)
    log_path.write_text(
        "$ " + " ".join(shlex.quote(part) for part in cmd) + "\n\n"
        + "## stdout\n\n" + (proc.stdout or "")
        + "\n## stderr\n\n" + (proc.stderr or ""),
        encoding="utf-8",
    )
    return proc


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def first_text(*values: object, fallback: str = "") -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback


def write_report(path: Path, rows: list[dict[str, object]], artifacts: dict[str, Path]) -> None:
    lines = ["# Cyrus Pipeline Report", ""]
    ok = all(row["returncode"] == 0 for row in rows)
    lines.append(f"- status: {'PASS' if ok else 'FAIL'}")
    lines.append("")
    lines.append("## Steps")
    lines.append("")
    for row in rows:
        mark = "PASS" if row["returncode"] == 0 else "FAIL"
        lines.append(f"- {mark} `{row['name']}` rc={row['returncode']} log=`{row['log']}`")
    lines.append("")
    lines.append("## Artifacts")
    lines.append("")
    for name, artifact in artifacts.items():
        if artifact.exists():
            lines.append(f"- `{name}`: `{artifact}`")
    lines.append("")
    audit = artifacts.get("audit")
    if audit and audit.exists() and "visual checks could not run" in audit.read_text(encoding="utf-8"):
        lines.append("## Environment Warning")
        lines.append("")
        lines.append("- Visual audit could not launch Chromium in this environment. Visual delivery is blocked when `--visual` is requested; rerun in a browser-capable environment or explicitly use `--no-visual` for a non-delivery dry run.")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def normalize_magic_base_url(value: str | None) -> str:
    raw = str(value or DEFAULT_MAGIC_BASE_URL).strip().rstrip("/")
    if not raw:
        raw = DEFAULT_MAGIC_BASE_URL
    return raw if raw.startswith(("http://", "https://")) else f"https://{raw}"


def write_cloud_publish_report(output_dir: Path, payload: dict[str, object]) -> None:
    (output_dir / "cloud-publish.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
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


def _walk_text(value: object) -> list[str]:
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


def rehearsal_gate_context(outline_path: Path, deck_path: Path) -> tuple[bool, list[str]]:
    text = ""
    for path in [outline_path, deck_path]:
        if path.exists():
            text += "\n" + "\n".join(_walk_text(read_json(path)))
    lower = text.lower()
    manufacturing_terms = ["中际旭创", "innolight", "npi", "光模块", "高端制造", "制造业", "质量异常", "供应链"]
    ai_terms = ["agent", "ai", "数字员工", "智能体"]
    signals = [term for term in manufacturing_terms + ai_terms if term.lower() in lower]
    return any(term.lower() in lower for term in manufacturing_terms) and any(term.lower() in lower for term in ai_terms), signals


def evaluate_rehearsal_gate(rehearsal_path: Path, outline_path: Path, deck_path: Path) -> dict[str, object]:
    applied, signals = rehearsal_gate_context(outline_path, deck_path)
    if not rehearsal_path.exists():
        return {"ok": False, "applied": applied, "signals": signals, "reason": "pitch-rehearsal.json missing", "blockers": ["pitch rehearsal did not run"]}
    rehearsal = read_json(rehearsal_path)
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


def write_rehearsal_gate_report(output_dir: Path, payload: dict[str, object]) -> None:
    (output_dir / "rehearsal-gate.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
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


def cloud_publish_disabled(output_dir: Path, log_path: Path, reason: str) -> subprocess.CompletedProcess[str]:
    payload = {
        "target": "none",
        "enabled": False,
        "ok": True,
        "dry_run": False,
        "app_url": "",
        "doc_url": "",
        "app_id": "",
        "reason": reason,
    }
    write_cloud_publish_report(output_dir, payload)
    log_path.write_text(f"cloud publish disabled: {reason}\n", encoding="utf-8")
    return subprocess.CompletedProcess(["cloud-publish"], 0, "", "")


def magic_page_dry_run(args: argparse.Namespace) -> bool:
    raw = (
        os.environ.get("CYRUS_MAGIC_PAGE_DRY_RUN")
        or os.environ.get("CYRUS_MAGIC_DRY_RUN")
        or os.environ.get("MAGIC_DRY_RUN")
    )
    return args.magic_page_dry_run or args.magic_dry_run or str(raw).lower() in {"1", "true", "yes", "mock"}


def parse_magic_page_stdout(stdout: str) -> dict[str, object]:
    result: dict[str, object] = {"app_url": "", "app_id": "", "urls": {}}
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


def write_magic_page_publish_report(output_dir: Path, payload: dict[str, object]) -> None:
    (output_dir / "magic-page-publish.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
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


def run_magic_page_publish(
    args: argparse.Namespace,
    output_dir: Path,
    title: str,
    task_id: str,
    log_path: Path,
) -> subprocess.CompletedProcess[str]:
    base_url = normalize_magic_base_url(args.magic_base_url or os.environ.get("MAGIC_BASE_URL"))
    if magic_page_dry_run(args):
        token = "dryrun-" + hashlib.sha1(f"{task_id}:{title}".encode("utf-8")).hexdigest()[:16]
        url = f"{base_url}/dryrun/{token}"
        payload = {
            "target": "magic-page",
            "enabled": True,
            "ok": True,
            "dry_run": True,
            "app_url": url,
            "doc_url": "",
            "app_id": token,
            "base_url": base_url,
            "reason": "dry-run",
        }
        write_magic_page_publish_report(output_dir, payload)
        write_cloud_publish_report(output_dir, payload)
        log_path.write_text(f"dry-run magic page url: {url}\n", encoding="utf-8")
        return subprocess.CompletedProcess(["magic-page-publish"], 0, url + "\n", "")

    script = Path(args.magic_page_script or os.environ.get("CYRUS_MAGIC_PAGE_PUBLISHER") or DEFAULT_MAGIC_PAGE_PUBLISHER)
    if not script.exists():
        reason = f"Magic Page publisher not found: {script}"
        payload = {
            "target": "magic-page",
            "enabled": True,
            "ok": False,
            "dry_run": False,
            "app_url": "",
            "doc_url": "",
            "app_id": "",
            "base_url": base_url,
            "reason": reason,
        }
        write_magic_page_publish_report(output_dir, payload)
        write_cloud_publish_report(output_dir, payload)
        log_path.write_text(reason + "\n", encoding="utf-8")
        return subprocess.CompletedProcess(["magic-page-publish"], 1, "", reason)

    cmd = ["node", str(script), "publish", str(output_dir / "index.html"), "--title", title, "--base-url", base_url]
    if args.magic_page_open_source:
        cmd.append("--open-source")
    proc = run(cmd, log_path)
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
        "base_url": base_url,
        "urls": parsed["urls"],
        "reason": "" if ok else (proc.stderr.strip() or proc.stdout.strip() or "publish failed"),
    }
    write_magic_page_publish_report(output_dir, payload)
    write_cloud_publish_report(output_dir, payload)
    return proc if ok else subprocess.CompletedProcess(cmd, proc.returncode or 1, proc.stdout, proc.stderr)


def magic_doc_dry_run(args: argparse.Namespace) -> bool:
    raw = os.environ.get("CYRUS_MAGIC_DOC_DRY_RUN") or os.environ.get("CYRUS_MAGIC_DRY_RUN") or os.environ.get("MAGIC_DRY_RUN")
    return args.magic_doc_dry_run or args.magic_dry_run or str(raw).lower() in {"1", "true", "yes", "mock"}


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
        import re

        match = re.search(r"https?://\S+", stdout)
        return {"doc_url": match.group(0).rstrip() if match else "", "doc_token": "", "html_box_block_id": "", "identity": ""}


def write_magic_doc_publish_report(output_dir: Path, payload: dict[str, object]) -> None:
    (output_dir / "magic-doc-publish.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
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


def finalize_magic_doc_publish(output_dir: Path, payload: dict[str, object]) -> None:
    payload.setdefault("target", "magic-doc")
    payload.setdefault("app_url", "")
    payload.setdefault("app_id", "")
    write_magic_doc_publish_report(output_dir, payload)
    write_cloud_publish_report(output_dir, payload)


def run_magic_doc_publish(
    args: argparse.Namespace,
    output_dir: Path,
    title: str,
    task_id: str,
    log_path: Path,
) -> subprocess.CompletedProcess[str]:
    if args.no_magic or args.no_magic_doc:
        payload = {"enabled": False, "ok": False, "dry_run": False, "doc_url": "", "doc_token": "", "html_box_block_id": "", "identity": "", "reason": "disabled"}
        finalize_magic_doc_publish(output_dir, payload)
        log_path.write_text("magic doc publish disabled\n", encoding="utf-8")
        return subprocess.CompletedProcess(["magic-doc-publish"], 0, "", "")
    identity = args.magic_doc_as or os.environ.get("CYRUS_MAGIC_DOC_AS") or "user"
    if magic_doc_dry_run(args):
        token = "dryrun" + hashlib.sha1(f"{task_id}:{title}".encode("utf-8")).hexdigest()[:16]
        url = f"https://bytedance.larkoffice.com/docx/{token}"
        payload = {
            "enabled": True,
            "ok": True,
            "dry_run": True,
            "doc_url": url,
            "doc_token": token,
            "html_box_block_id": "dryrun-html-box",
            "identity": identity,
            "reason": "dry-run",
        }
        finalize_magic_doc_publish(output_dir, payload)
        log_path.write_text(f"dry-run magic doc url: {url}\n", encoding="utf-8")
        return subprocess.CompletedProcess(["magic-doc-publish"], 0, url + "\n", "")

    script = Path(args.magic_doc_script or os.environ.get("CYRUS_MAGIC_DOC_CREATOR") or DEFAULT_MAGIC_DOC_CREATOR)
    if not script.exists():
        reason = f"Magic doc creator not found: {script}"
        payload = {"enabled": True, "ok": False, "dry_run": False, "doc_url": "", "doc_token": "", "html_box_block_id": "", "identity": identity, "reason": reason}
        finalize_magic_doc_publish(output_dir, payload)
        log_path.write_text(reason + "\n", encoding="utf-8")
        return subprocess.CompletedProcess(["magic-doc-publish"], 1, "", reason)

    summary = args.magic_doc_summary or f"这是一份「{title}」HTML Deck,已直接嵌入飞书妙笔文档供在线查看。"
    cmd = ["node", str(script), "--html", str(output_dir / "index.html")]
    if args.magic_doc_token:
        cmd.extend(["--doc-token", args.magic_doc_token])
    else:
        cmd.extend(["--title", title, "--summary", summary])
    if identity:
        cmd.extend(["--as", identity])
    proc = run(cmd, log_path)
    parsed = parse_magic_doc_stdout(proc.stdout)
    ok = proc.returncode == 0 and bool(parsed["doc_url"])
    payload = {
        "enabled": True,
        "ok": ok,
        "dry_run": False,
        "doc_url": parsed["doc_url"],
        "doc_token": parsed["doc_token"] or args.magic_doc_token,
        "html_box_block_id": parsed["html_box_block_id"],
        "identity": parsed["identity"] or identity,
        "reason": "" if ok else (proc.stderr.strip() or proc.stdout.strip() or "publish failed"),
    }
    finalize_magic_doc_publish(output_dir, payload)
    return proc if ok else subprocess.CompletedProcess(cmd, proc.returncode or 1, proc.stdout, proc.stderr)


def run_cloud_publish(
    args: argparse.Namespace,
    output_dir: Path,
    title: str,
    task_id: str,
    log_path: Path,
) -> subprocess.CompletedProcess[str]:
    if args.no_magic or args.no_magic_doc or args.publish_target == "none":
        return cloud_publish_disabled(output_dir, log_path, "disabled")
    if args.publish_target == "magic-doc":
        return run_magic_doc_publish(args, output_dir, title, task_id, log_path)
    return run_magic_page_publish(args, output_dir, title, task_id, log_path)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    publish_default = os.environ.get("CYRUS_PUBLISH_TARGET") or os.environ.get("CYRUS_CLOUD_TARGET") or "magic-page"
    if publish_default not in {"magic-page", "magic-doc", "none"}:
        publish_default = "magic-page"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path, help="Run directory containing input/outline.json and output/")
    parser.add_argument("--author", default="飞书企业 AI")
    parser.add_argument("--cover-date", default=str(date.today()))
    parser.add_argument("--customer-slug")
    parser.add_argument("--meeting-type", default="solution-pitch", choices=sorted(MEETING_TYPES))
    parser.add_argument("--no-visual", action="store_true", help="Skip Playwright visual audit")
    parser.add_argument("--inline", action="store_true", help="Render final HTML in single-file inline mode")
    parser.add_argument("--offline-cache", action="store_true", help="Skip live Base asset sync and use local package cache")
    parser.add_argument("--publish-target", default=publish_default, choices=["magic-page", "magic-doc", "none"], help="Cloud delivery target; default is standalone Magic Page")
    parser.add_argument("--no-magic", action="store_true", help="Legacy alias for --publish-target none")
    parser.add_argument("--magic-dry-run", action="store_true", help="Legacy alias for the selected Magic publish dry-run")
    parser.add_argument("--no-magic-doc", action="store_true", help="Legacy alias for --publish-target none")
    parser.add_argument("--magic-page-dry-run", action="store_true", help="Write a deterministic Magic Page dry-run URL without publishing")
    parser.add_argument("--magic-page-script", default="", help="Path to publish-magic-page publish.js")
    parser.add_argument("--magic-page-open-source", action="store_true", help="Mark the published Magic Page as open-source")
    parser.add_argument("--magic-base-url", default="", help="Magic service base URL; defaults to MAGIC_BASE_URL or built-in service URL")
    parser.add_argument("--magic-doc-dry-run", action="store_true", help="Write a deterministic Feishu Magic Doc dry-run URL without publishing")
    parser.add_argument("--magic-doc-script", default="", help="Path to generate-magic-doc create_magic_doc.mjs")
    parser.add_argument("--magic-doc-token", default="", help="Existing Feishu Docx token to append the HTML Box into")
    parser.add_argument("--magic-doc-as", default="", help="lark-cli identity for document creation/insertion: user or bot")
    parser.add_argument("--magic-doc-summary", default="", help="One-line introduction inserted above the HTML Box")
    parser.add_argument("--allow-rehearsal-risk", action="store_true", help="Record rehearsal gate failures but do not block cloud publish")
    parser.add_argument("--skip-package", action="store_true")
    args = parser.parse_args(argv)
    if args.no_magic or args.no_magic_doc:
        args.publish_target = "none"
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    run_dir = args.run_dir.resolve()
    input_dir = run_dir / "input"
    output_dir = run_dir / "output"
    log_dir = run_dir / "logs"
    outline_path = input_dir / "outline.json"
    deck_path = output_dir / "deck.json"
    compile_report = output_dir / "compile-report.json"
    feedback_path = output_dir / "FEEDBACK.md"
    html_path = output_dir / "index.html"
    audit_path = output_dir / "AUDIT_REPORT.md"
    rehearsal_json = output_dir / "pitch-rehearsal.json"
    rehearsal_md = output_dir / "PITCH_REHEARSAL.md"
    pipeline_report = output_dir / "PIPELINE_REPORT.md"

    if not outline_path.exists():
        print(f"outline not found: {outline_path}", file=sys.stderr)
        return 2
    output_dir.mkdir(parents=True, exist_ok=True)
    outline = read_json(outline_path)
    brief = outline.get("brief", {}) if isinstance(outline.get("brief"), dict) else {}
    title = first_text(brief.get("title"), fallback="未命名 Deck")
    audience = first_text(brief.get("audience"), fallback="目标客户团队")
    objective = first_text(brief.get("objective"), fallback="确认下一步")
    next_step = first_text(brief.get("success_metric"), fallback="确认试点范围和负责人")
    customer_slug = args.customer_slug or run_dir.name

    steps: list[dict[str, object]] = []

    def artifacts() -> dict[str, Path]:
        return {
            "index.html": html_path,
            "deck.json": deck_path,
            "texts.md": output_dir / "texts.md",
            "FEEDBACK.md": feedback_path,
            "audit": audit_path,
            "pitch": rehearsal_md,
            "rehearsal_gate": output_dir / "REHEARSAL_GATE.md",
            "cloud_publish": output_dir / "CLOUD_PUBLISH.md",
            "magic_page": output_dir / "MAGIC_PAGE_PUBLISH.md",
            "magic_doc_legacy": output_dir / "MAGIC_DOC_PUBLISH.md",
            "pipeline": pipeline_report,
        }

    commands = [
        ("preflight", ["bash", str(PREFLIGHT)]),
        (
            "compile-outline",
            [
                sys.executable,
                str(COMPILE_OUTLINE),
                str(outline_path),
                str(deck_path),
                "--report",
                str(compile_report),
                "--feedback",
                str(feedback_path),
                "--author",
                args.author,
                "--cover-date",
                args.cover_date,
                "--customer-slug",
                customer_slug,
            ],
        ),
        (
            "render",
            [
                sys.executable,
                str(RENDER_DECK),
                str(deck_path),
                str(output_dir),
                "--shared=copy",
                *(["--offline-cache"] if args.offline_cache else []),
                *(["--inline"] if args.inline else []),
            ],
        ),
        (
            "audit",
            [
                sys.executable,
                str(AUDITOR),
                str(html_path),
                "--deck-json",
                str(deck_path),
                *(["--no-visual"] if args.no_visual else ["--visual"]),
                "--report",
                str(audit_path),
                "--json-report",
                str(output_dir / "audit-report.json"),
                "--h5-report",
                str(output_dir / "H5_CHECKONLY_REPORT.md"),
            ],
        ),
    ]
    pre_publish_commands = [
        (
            "pitch-rehearsal",
            [
                sys.executable,
                str(PITCH_SIMULATOR),
                "--outline",
                str(outline_path),
                "--deck-json",
                str(deck_path),
                "--html",
                str(html_path),
                "--out-json",
                str(rehearsal_json),
                "--out-md",
                str(rehearsal_md),
                "--title",
                title,
                "--audience",
                audience,
                "--objective",
                objective,
                "--success-next-step",
                next_step,
                "--meeting-type",
                args.meeting_type,
            ],
        ),
        ("validate-rehearsal", [sys.executable, str(PITCH_VALIDATOR), str(rehearsal_json)]),
    ]
    post_publish_commands = []
    if not args.skip_package:
        post_publish_commands.append(
            (
                "package",
                [
                    "bash",
                    str(PACKAGE),
                    str(output_dir),
                    "--name",
                    f"{customer_slug}-html-deck",
                ],
            )
        )

    for name, cmd in commands:
        proc = run(cmd, log_dir / f"{name}.log")
        steps.append({"name": name, "returncode": proc.returncode, "log": log_dir / f"{name}.log"})
        write_report(pipeline_report, steps, artifacts())
        if proc.returncode != 0:
            print(f"{name} failed; see {log_dir / f'{name}.log'}", file=sys.stderr)
            return proc.returncode

    for name, cmd in pre_publish_commands:
        proc = run(cmd, log_dir / f"{name}.log")
        steps.append({"name": name, "returncode": proc.returncode, "log": log_dir / f"{name}.log"})
        write_report(pipeline_report, steps, artifacts())
        if proc.returncode != 0:
            print(f"{name} failed; see {log_dir / f'{name}.log'}", file=sys.stderr)
            return proc.returncode

    gate_payload = evaluate_rehearsal_gate(rehearsal_json, outline_path, deck_path)
    if args.allow_rehearsal_risk:
        gate_payload["bypassed"] = True
    write_rehearsal_gate_report(output_dir, gate_payload)
    gate_rc = 0 if gate_payload.get("ok") or args.allow_rehearsal_risk else 1
    steps.append({"name": "rehearsal-gate", "returncode": gate_rc, "log": output_dir / "REHEARSAL_GATE.md"})
    write_report(pipeline_report, steps, artifacts())
    if gate_rc != 0:
        print(f"rehearsal-gate failed; see {output_dir / 'REHEARSAL_GATE.md'}", file=sys.stderr)
        return gate_rc

    publish_log = log_dir / "cloud-publish.log"
    publish_proc = run_cloud_publish(args, output_dir, title, run_dir.name, publish_log)
    steps.append({"name": "cloud-publish", "returncode": publish_proc.returncode, "log": publish_log})
    write_report(pipeline_report, steps, artifacts())
    if publish_proc.returncode != 0:
        print(f"cloud-publish failed; see {publish_log}", file=sys.stderr)
        return publish_proc.returncode

    for name, cmd in post_publish_commands:
        proc = run(cmd, log_dir / f"{name}.log")
        steps.append({"name": name, "returncode": proc.returncode, "log": log_dir / f"{name}.log"})
        write_report(pipeline_report, steps, artifacts())
        if proc.returncode != 0:
            print(f"{name} failed; see {log_dir / f'{name}.log'}", file=sys.stderr)
            return proc.returncode

    print(pipeline_report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
