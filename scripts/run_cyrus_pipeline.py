#!/usr/bin/env python3
"""Run the confirmed lark-deck-cyrus generation pipeline for one run folder.

This is the deterministic "after user confirms outline" path:

  preflight -> compile outline -> render HTML -> strict audit
  -> pitch rehearsal -> package editable zip -> Feishu Magic Doc publish
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
CHECK_ONLY = REPO / "skills/deck-renderer/assets/check-only.sh"
PITCH_SIMULATOR = REPO / "skills/pitch-simulator/simulate-pitch.py"
PITCH_VALIDATOR = REPO / "skills/pitch-simulator/validate-rehearsal.py"
PACKAGE = REPO / "skills/deck-renderer/assets/package-deliverable.sh"
DEFAULT_MAGIC_DOC_CREATOR = Path("/Users/bytedance/.codex/skills/generate-magic-doc/scripts/create_magic_doc.mjs")

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
        lines.append("- Visual audit could not launch Chromium in this environment. The deck was not marked as a content failure, but a full projector check still needs a browser-capable environment.")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


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


def run_magic_doc_publish(
    args: argparse.Namespace,
    output_dir: Path,
    title: str,
    task_id: str,
    log_path: Path,
) -> subprocess.CompletedProcess[str]:
    if args.no_magic or args.no_magic_doc:
        payload = {"enabled": False, "ok": False, "dry_run": False, "doc_url": "", "doc_token": "", "html_box_block_id": "", "identity": "", "reason": "disabled"}
        write_magic_doc_publish_report(output_dir, payload)
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
        write_magic_doc_publish_report(output_dir, payload)
        log_path.write_text(f"dry-run magic doc url: {url}\n", encoding="utf-8")
        return subprocess.CompletedProcess(["magic-doc-publish"], 0, url + "\n", "")

    script = Path(args.magic_doc_script or os.environ.get("CYRUS_MAGIC_DOC_CREATOR") or DEFAULT_MAGIC_DOC_CREATOR)
    if not script.exists():
        reason = f"Magic doc creator not found: {script}"
        payload = {"enabled": True, "ok": False, "dry_run": False, "doc_url": "", "doc_token": "", "html_box_block_id": "", "identity": identity, "reason": reason}
        write_magic_doc_publish_report(output_dir, payload)
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
    write_magic_doc_publish_report(output_dir, payload)
    return proc if ok else subprocess.CompletedProcess(cmd, proc.returncode or 1, proc.stdout, proc.stderr)

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path, help="Run directory containing input/outline.json and output/")
    parser.add_argument("--author", default="飞书企业 AI")
    parser.add_argument("--cover-date", default=str(date.today()))
    parser.add_argument("--customer-slug")
    parser.add_argument("--meeting-type", default="solution-pitch", choices=sorted(MEETING_TYPES))
    parser.add_argument("--no-visual", action="store_true", help="Skip Playwright visual audit")
    parser.add_argument("--inline", action="store_true", help="Render final HTML in single-file inline mode")
    parser.add_argument("--offline-cache", action="store_true", help="Skip live Base asset sync and use local package cache")
    parser.add_argument("--no-magic", action="store_true", help="Legacy alias for --no-magic-doc")
    parser.add_argument("--magic-dry-run", action="store_true", help="Legacy alias for --magic-doc-dry-run")
    parser.add_argument("--no-magic-doc", action="store_true", help="Do not publish the final HTML deck into a Feishu Magic Doc")
    parser.add_argument("--magic-doc-dry-run", action="store_true", help="Write a deterministic Feishu Magic Doc dry-run URL without publishing")
    parser.add_argument("--magic-doc-script", default="", help="Path to generate-magic-doc create_magic_doc.mjs")
    parser.add_argument("--magic-doc-token", default="", help="Existing Feishu Docx token to append the HTML Box into")
    parser.add_argument("--magic-doc-as", default="", help="lark-cli identity for document creation/insertion: user or bot")
    parser.add_argument("--magic-doc-summary", default="", help="One-line introduction inserted above the HTML Box")
    parser.add_argument("--skip-package", action="store_true")
    return parser.parse_args(argv)


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
                "bash",
                str(CHECK_ONLY),
                str(html_path),
                "--strict",
                *(["--visual"] if not args.no_visual else []),
                "--report",
                str(audit_path),
            ],
        ),
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
    if not args.skip_package:
        commands.append(
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
        artifacts = {
            "index.html": html_path,
            "deck.json": deck_path,
            "texts.md": output_dir / "texts.md",
            "FEEDBACK.md": feedback_path,
            "audit": audit_path,
            "pitch": rehearsal_md,
            "magic_doc": output_dir / "MAGIC_DOC_PUBLISH.md",
            "pipeline": pipeline_report,
        }
        write_report(pipeline_report, steps, artifacts)
        if proc.returncode != 0:
            print(f"{name} failed; see {log_dir / f'{name}.log'}", file=sys.stderr)
            return proc.returncode

    magic_proc = run_magic_doc_publish(args, output_dir, title, run_dir.name, log_dir / "magic-doc-publish.log")
    steps.append({"name": "magic-doc-publish", "returncode": magic_proc.returncode, "log": log_dir / "magic-doc-publish.log"})
    artifacts = {
        "index.html": html_path,
        "deck.json": deck_path,
        "texts.md": output_dir / "texts.md",
        "FEEDBACK.md": feedback_path,
        "audit": audit_path,
        "pitch": rehearsal_md,
        "magic_doc": output_dir / "MAGIC_DOC_PUBLISH.md",
        "pipeline": pipeline_report,
    }
    write_report(pipeline_report, steps, artifacts)
    if magic_proc.returncode != 0:
        print(f"magic-doc-publish failed; see {log_dir / 'magic-doc-publish.log'}", file=sys.stderr)
        return magic_proc.returncode

    print(pipeline_report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
