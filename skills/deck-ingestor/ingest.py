#!/usr/bin/env python3
"""Create concrete reuse records from a rendered Cyrus task.

This script is the executable bridge behind the deck-ingestor skill:

- local mode writes review candidates through server/slide_library.py
- --write-base additionally writes knowledge records and material/asset records
  to the configured live Feishu/Lark Base through scripts/base_library.py
- --ppt-library registers a user-selected PPT/PPTX as selectable Slide-library
  candidates without converting it yet. Slide Library remains local-only for now.

Base writes use the configured Base and current lark-cli user identity. The
caller can fall back to local candidates when that identity has no cloud access.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
RUNS = REPO / "runs"
BASE_LIBRARY = REPO / "scripts" / "base_library.py"
sys.path.insert(0, str(REPO / "server"))

import slide_library  # noqa: E402


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def audit_passed(output_dir: Path) -> bool:
    report = output_dir / "audit-report.json"
    if report.exists():
        try:
            payload = read_json(report)
        except Exception:
            payload = {}
        verdict = str(payload.get("verdict") or payload.get("cyrus_verdict") or "").lower()
        status = str(payload.get("status") or "").lower()
        if verdict == "pass" or status == "pass":
            return True
    md = output_dir / "AUDIT_REPORT.md"
    if md.exists():
        first = md.read_text(encoding="utf-8", errors="ignore").splitlines()[:5]
        joined = " ".join(first).lower()
        return "cyrus verdict: pass" in joined or "verdict: pass" in joined
    return False


def task_dirs(task_id: str) -> tuple[Path, Path]:
    task_dir = RUNS / task_id
    output_dir = task_dir / "output"
    if not (output_dir / "deck.json").exists():
        raise SystemExit(f"deck-ingestor: deck.json not found for task {task_id}")
    return task_dir, output_dir


def normalize_list(values: list[str] | None, default: list[str]) -> list[str]:
    out: list[str] = []
    for value in values or []:
        for part in str(value).replace("，", ",").replace("、", ",").split(","):
            part = part.strip()
            if part:
                out.append(part)
    return out or default


def slide_summary(slide: dict[str, Any]) -> str:
    values: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, str):
            if value.strip():
                values.append(value.strip())
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)

    walk(slide.get("data") or {})
    return " ".join(values)[:240]


def selected_slide_keys(deck: dict[str, Any], requested: list[str]) -> list[str]:
    if requested:
        return requested
    keys = []
    for slide in deck.get("slides", []):
        if not isinstance(slide, dict):
            continue
        if slide.get("layout") in {"cover", "end", "raw", "replica"}:
            continue
        key = slide.get("key")
        if key:
            keys.append(str(key))
    return keys


def write_base_knowledge(
    *,
    task_id: str,
    slide_key: str,
    slide: dict[str, Any],
    metadata: dict[str, Any],
    identity: str,
    dry_run: bool,
) -> dict[str, Any]:
    doc_id = f"slide-{task_id}-{slide_key}"[:96]
    asset_id = f"slidefrag-{task_id}-{slide_key}"[:96]
    source_deck = f"runs/{task_id}/output/deck.json"
    content = json.dumps(
        {
            "task_id": task_id,
            "slide_key": slide_key,
            "layout": slide.get("layout"),
            "variant": slide.get("variant", ""),
            "asset_id": asset_id,
            "slide": slide,
            "provenance": source_deck,
        },
        ensure_ascii=False,
        indent=2,
    )
    cmd = [
        sys.executable,
        str(BASE_LIBRARY),
        "--as",
        identity,
        "create-knowledge",
        "--doc-id",
        doc_id,
        "--title",
        metadata.get("title") or slide_library.slide_title(slide),
        "--type",
        "slide-candidate",
        "--local-path",
        f"runs/{task_id}/output/deck.json#{slide_key}",
        "--content",
        content,
        "--summary",
        slide_summary(slide),
        "--source-level",
        metadata.get("source_level") or "internal-draft",
        "--industry",
        ",".join(normalize_list(metadata.get("industry"), ["待标注"])),
        "--slide-key",
        slide_key,
        "--related-asset-id",
        asset_id,
        "--source-deck",
        source_deck,
        "--source-ppt",
        metadata.get("source_ppt") or "",
        "--source-page",
        str(metadata.get("source_page") or ""),
        "--permission-status",
        metadata.get("permission_status") or "needs_review",
        "--contributor",
        metadata.get("contributor") or metadata.get("owner") or "gtm",
        "--contributed-at",
        metadata.get("contributed_at") or "",
    ]
    for product in normalize_list(metadata.get("product"), []):
        cmd.extend(["--product", product])
    for scene in normalize_list(metadata.get("deck_type"), []):
        cmd.extend(["--scene", scene])
    if dry_run:
        cmd.append("--dry-run")
    proc = subprocess.run(cmd, cwd=REPO, text=True, capture_output=True)
    if proc.returncode != 0:
        return {
            "type": "knowledge",
            "ok": False,
            "slide_key": slide_key,
            "stderr": proc.stderr.strip(),
            "stdout": proc.stdout.strip(),
        }
    return {"type": "knowledge", "ok": True, "slide_key": slide_key, "result": json.loads(proc.stdout)}


def write_base_asset_record(
    *,
    task_id: str,
    slide_key: str,
    slide: dict[str, Any],
    metadata: dict[str, Any],
    identity: str,
    dry_run: bool,
) -> dict[str, Any]:
    payload = json.dumps(slide, ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    knowledge_id = f"slide-{task_id}-{slide_key}"[:96]
    source_deck = f"runs/{task_id}/output/deck.json"
    cmd = [
        sys.executable,
        str(BASE_LIBRARY),
        "--as",
        identity,
        "create-asset-record",
        "--asset-id",
        f"slidefrag-{task_id}-{slide_key}"[:96],
        "--display-name",
        metadata.get("title") or slide_library.slide_title(slide),
        "--kind",
        "deckjson-slide",
        "--collection",
        "deck-ingest",
        "--format",
        "json",
        "--mime",
        "application/json",
        "--local-path",
        f"runs/{task_id}/output/deck.json#{slide_key}",
        "--size-kb",
        f"{len(payload.encode('utf-8')) / 1024:.1f}",
        "--sha256",
        digest,
        "--usage",
        f"{slide.get('layout')}{('/' + str(slide.get('variant'))) if slide.get('variant') else ''} reusable slide fragment",
        "--slide-key",
        slide_key,
        "--related-knowledge-id",
        knowledge_id,
        "--source-deck",
        source_deck,
        "--source-ppt",
        metadata.get("source_ppt") or "",
        "--source-page",
        str(metadata.get("source_page") or ""),
        "--permission-status",
        metadata.get("permission_status") or "needs_review",
        "--contributor",
        metadata.get("contributor") or metadata.get("owner") or "gtm",
        "--contributed-at",
        metadata.get("contributed_at") or "",
    ]
    for industry in normalize_list(metadata.get("industry"), []):
        cmd.extend(["--industry", industry])
    for product in normalize_list(metadata.get("product"), []):
        cmd.extend(["--product", product])
    for scene in normalize_list(metadata.get("deck_type"), []):
        cmd.extend(["--scene", scene])
    for tag in normalize_list(metadata.get("tags"), ["needs-review"]):
        cmd.extend(["--tags", tag])
    for tag in [str(slide.get("layout") or ""), str(slide.get("variant") or "")]:
        if tag:
            cmd.extend(["--tags", tag])
    if dry_run:
        cmd.append("--dry-run")
    proc = subprocess.run(cmd, cwd=REPO, text=True, capture_output=True)
    if proc.returncode != 0:
        return {
            "type": "asset",
            "ok": False,
            "slide_key": slide_key,
            "stderr": proc.stderr.strip(),
            "stdout": proc.stdout.strip(),
        }
    return {"type": "asset", "ok": True, "slide_key": slide_key, "result": json.loads(proc.stdout)}


def report_md(manifest: dict[str, Any]) -> str:
    lines = [
        "# Ingestion Report",
        "",
        f"- task_id: `{manifest['task_id']}`",
        f"- local_candidates: {len(manifest['local_candidates'])}",
        f"- base_writes: {len(manifest['base_writes'])}",
        "",
        "## Local candidates",
    ]
    for item in manifest["local_candidates"]:
        entry = item.get("entry", {})
        lines.append(f"- `{entry.get('id', '')}` · {entry.get('title', '')} · {item.get('path', '')}")
    if manifest["base_writes"]:
        lines.extend(["", "## Base writes"])
        for item in manifest["base_writes"]:
            status = "ok" if item.get("ok") else "failed"
            lines.append(f"- `{item.get('slide_key')}` · {item.get('type', 'record')} · {status}")
            if not item.get("ok"):
                lines.append(f"  - {item.get('stderr') or item.get('stdout')}")
    if manifest["skipped"]:
        lines.extend(["", "## Skipped"])
        for item in manifest["skipped"]:
            lines.append(f"- `{item.get('slide_key')}` · {item.get('reason')}")
    lines.append("")
    return "\n".join(lines)


def register_ppt_library(args: argparse.Namespace) -> int:
    metadata = {
        "title": args.title,
        "summary": args.summary,
        "thumbnail": args.thumbnail,
        "industry": normalize_list(args.industry, ["待标注"]),
        "product": normalize_list(args.product, ["待标注"]),
        "customer_stage": normalize_list(args.customer_stage, ["待标注"]),
        "deck_type": normalize_list(args.deck_type, ["用户自选 PPT"]),
        "value_prop": normalize_list(args.value_prop, []),
        "tags": normalize_list(args.tag, ["ppt-upload", "needs-review"]),
        "source_level": args.source_level,
        "owner": args.owner,
        "reviewer": args.reviewer,
        "contributor": args.contributor or args.owner or "gtm",
        "contributed_at": args.contributed_at or now_iso(),
        "permission_status": args.permission_status,
    }
    result = slide_library.register_ppt_upload(args.ppt_library, metadata, pages=args.ppt_page)
    manifest: dict[str, Any] = {
        "source": result["source"],
        "slide_count": result["slide_count"],
        "local_candidates": result["registered"],
        "base_writes": [],
        "skipped": result.get("skipped", []),
    }
    if args.write_base:
        manifest["skipped"].append({
            "slide_key": "ppt-library",
            "reason": "--ppt-library is local-only; select/decompose pages before writing knowledge/assets to Base",
        })
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") and all(item.get("ok", True) for item in manifest["base_writes"]) else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--task-id")
    ap.add_argument("--ppt-library", type=Path, help="register a user-selected PPT/PPTX into the Slide library as selectable candidates")
    ap.add_argument("--ppt-page", action="append", type=int, default=[], help="1-based PPT page to register; repeatable. Defaults to all pages.")
    ap.add_argument("--slide-key", action="append", default=[], help="slide key to ingest; repeatable. Defaults to all reusable non-cover slides.")
    ap.add_argument("--title")
    ap.add_argument("--industry", action="append", default=[])
    ap.add_argument("--product", action="append", default=[])
    ap.add_argument("--customer-stage", action="append", default=[])
    ap.add_argument("--deck-type", action="append", default=[])
    ap.add_argument("--value-prop", action="append", default=[])
    ap.add_argument("--tag", action="append", default=[])
    ap.add_argument("--source-level", default="internal-draft")
    ap.add_argument("--owner", default="gtm")
    ap.add_argument("--reviewer", default="")
    ap.add_argument("--contributor", default="")
    ap.add_argument("--contributed-at", default="")
    ap.add_argument("--summary", default="")
    ap.add_argument("--thumbnail", default="")
    ap.add_argument("--permission-status", default="needs_review")
    ap.add_argument("--write-base", action="store_true", help="also write knowledge and slide-fragment asset records to live Base; Slide Library remains local-only")
    ap.add_argument("--base-as", choices=["user", "bot"], default="user")
    ap.add_argument("--dry-run-base", action="store_true")
    ap.add_argument("--allow-unaudited", action="store_true", help="bypass the default deck-auditor pass requirement; intended only for local fixture/debug use")
    args = ap.parse_args(argv)
    if args.ppt_library:
        return register_ppt_library(args)
    if not args.task_id:
        raise SystemExit("deck-ingestor: --task-id is required unless --ppt-library is used")

    _task_dir, output_dir = task_dirs(args.task_id)
    if not args.allow_unaudited and not audit_passed(output_dir):
        raise SystemExit("deck-ingestor: deck-auditor pass verdict is required before ingestion")
    deck = read_json(output_dir / "deck.json")
    slides_by_key = {str(slide.get("key")): slide for slide in deck.get("slides", []) if isinstance(slide, dict)}
    metadata = {
        "title": args.title,
        "industry": normalize_list(args.industry, ["待标注"]),
        "product": normalize_list(args.product, ["待标注"]),
        "customer_stage": normalize_list(args.customer_stage, ["待标注"]),
        "deck_type": normalize_list(args.deck_type, ["待标注"]),
        "value_prop": normalize_list(args.value_prop, []),
        "tags": normalize_list(args.tag, ["needs-review"]),
        "source_level": args.source_level,
        "owner": args.owner,
        "reviewer": args.reviewer,
        "contributor": args.contributor or args.owner or "gtm",
        "contributed_at": args.contributed_at or now_iso(),
        "thumbnail": args.thumbnail,
        "permission_status": args.permission_status,
    }

    manifest: dict[str, Any] = {
        "task_id": args.task_id,
        "source": str((output_dir / "deck.json").relative_to(REPO)),
        "local_candidates": [],
        "knowledge_records": [],
        "asset_records": [],
        "slide_records": [],
        "base_writes": [],
        "skipped": [],
    }

    for slide_key in selected_slide_keys(deck, args.slide_key):
        slide = slides_by_key.get(slide_key)
        if not slide:
            manifest["skipped"].append({"slide_key": slide_key, "reason": "slide key not found"})
            continue
        local = slide_library.mark_reuse_candidate(args.task_id, slide_key, metadata)
        manifest["local_candidates"].append(local)
        manifest["slide_records"].append({
            "type": "slide",
            "mode": "local",
            "ok": not any(issue.get("severity") == "error" for issue in local.get("issues", [])),
            "slide_key": slide_key,
            "path": local.get("path", ""),
        })
        if args.write_base:
            knowledge_write = write_base_knowledge(
                task_id=args.task_id,
                slide_key=slide_key,
                slide=slide,
                metadata=metadata,
                identity=args.base_as,
                dry_run=args.dry_run_base,
            )
            asset_write = write_base_asset_record(
                task_id=args.task_id,
                slide_key=slide_key,
                slide=slide,
                metadata=metadata,
                identity=args.base_as,
                dry_run=args.dry_run_base,
            )
            manifest["knowledge_records"].append(knowledge_write)
            manifest["asset_records"].append(asset_write)
            manifest["base_writes"].extend([knowledge_write, asset_write])

    manifest_path = output_dir / "ingestion-manifest.json"
    report_path = output_dir / "INGESTION_REPORT.md"
    write_json(manifest_path, manifest)
    report_path.write_text(report_md(manifest), encoding="utf-8")
    print(json.dumps({"manifest": str(manifest_path), "report": str(report_path), **manifest}, ensure_ascii=False, indent=2))
    return 0 if all(item.get("ok", True) for item in manifest["base_writes"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
