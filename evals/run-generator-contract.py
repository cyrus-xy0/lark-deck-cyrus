#!/usr/bin/env python3
"""Smoke-test the P0 generator wrapper contract.

This check verifies that the productized wrapper, not just the local renderer,
can create a task and emit every fixed handoff artifact:

  deck.json, index.html, texts.md, FEEDBACK.md, assets-manifest.yaml,
  journey artifacts, editable zip
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
GENERATOR = REPO / "server/generator.py"
REQUEST = REPO / "server/examples/brief-request.json"
os.environ.setdefault("CYRUS_MAGIC_DRY_RUN", "1")
os.environ.setdefault("CYRUS_PUBLISH_TARGET", "magic-page")
os.environ.setdefault("GENERATOR_VISUAL_AUDIT", "0")
REQUIRED = [
    "deck.json",
    "index.html",
    "texts.md",
    "FEEDBACK.md",
    "AUDIT_REPORT.md",
    "audit-report.json",
    "assets-manifest.yaml",
    "pitch-rehearsal.json",
    "PITCH_REHEARSAL.md",
    "cloud-publish.json",
    "CLOUD_PUBLISH.md",
    "journey.json",
    "JOURNEY.md",
    "quality-insights.json",
]
ZIP_REQUIRED = [
    "index.html",
    "texts.md",
    "assets-manifest.yaml",
    "FEEDBACK.md",
    "AUDIT_REPORT.md",
    "audit-report.json",
    "deck.json",
    "pitch-rehearsal.json",
    "PITCH_REHEARSAL.md",
    "journey.json",
    "JOURNEY.md",
    "quality-insights.json",
]


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        source_path = Path(td) / "customer-notes.md"
        source_path.write_text("# 门店 SOP 试点\n\n客户希望把巡店问题、SOP 知识和整改任务形成闭环。\n", encoding="utf-8")
        request_path = Path(td) / "request-with-source.json"
        request_path.write_text(
            json.dumps(
                {
                    "brief": {
                        "title": "带素材的门店 SOP pitch",
                        "customer_name": "示例客户",
                        "industry": "消费零售",
                        "audience": "COO 和运营负责人",
                        "objective": "确认一个门店 SOP 试点",
                        "product_scope": ["飞书 AI", "知识库", "任务"],
                    },
                    "sources": [str(source_path)],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        source_proc = subprocess.run(
            ["python3", str(GENERATOR), "create", "--request", str(request_path), "--plan-only"],
            cwd=REPO,
            text=True,
            capture_output=True,
        )
        if source_proc.returncode != 0:
            print(source_proc.stdout)
            print(source_proc.stderr, file=sys.stderr)
            return source_proc.returncode
        source_task = json.loads(source_proc.stdout)
        source_output = Path(source_task["output_dir"])
        source_input = Path(source_task["input_dir"])
        if source_task.get("status") != "awaiting_outline_confirmation" or source_task.get("source") != "materials+brief":
            print(json.dumps(source_task, ensure_ascii=False, indent=2), file=sys.stderr)
            return 1
        for path in [
            source_output / "DESIGN_PLAN.md",
            source_input / "runtime-library" / "source-dossier.json",
            source_input / "runtime-library" / "SOURCE_DOSSIER.md",
            source_input / "runtime-library" / "knowledge.json",
            source_input / "runtime-library" / "materials.json",
            source_input / "runtime-library" / "slides.json",
        ]:
            if not path.exists():
                print(f"source parser artifact missing: {path}", file=sys.stderr)
                return 1
        source_outline = json.loads((source_input / "outline.json").read_text(encoding="utf-8"))
        if not any(ref.get("provider") == "upload-parser" for ref in source_outline.get("knowledge_refs", [])):
            print("outline did not include upload-parser knowledge refs", file=sys.stderr)
            return 1
        source_path.unlink()
        source_confirm_proc = subprocess.run(
            ["python3", str(GENERATOR), "confirm-outline", source_task["id"]],
            cwd=REPO,
            text=True,
            capture_output=True,
        )
        if source_confirm_proc.returncode != 0:
            print(source_confirm_proc.stdout)
            print(source_confirm_proc.stderr, file=sys.stderr)
            return source_confirm_proc.returncode
        source_confirmed = json.loads(source_confirm_proc.stdout)
        if source_confirmed.get("status") != "awaiting_rehearsal_decision":
            print(json.dumps(source_confirmed, ensure_ascii=False, indent=2), file=sys.stderr)
            return 1
        if source_confirmed.get("source_dossier", {}).get("knowledge_items") != 1:
            print("confirmed source task lost parsed knowledge items", file=sys.stderr)
            return 1
        if any("source not found" in warning for warning in source_confirmed.get("warnings", [])):
            print("confirmed source task re-parsed the deleted upload instead of reusing runtime-library", file=sys.stderr)
            return 1

        missing_request_path = Path(td) / "request-with-missing-source.json"
        missing_request_path.write_text(
            json.dumps(
                {
                    "brief": {
                        "title": "缺素材路径仍继续",
                        "customer_name": "示例客户",
                        "industry": "消费零售",
                        "audience": "COO 和运营负责人",
                        "objective": "确认一个门店 SOP 试点",
                        "product_scope": ["飞书 AI", "知识库", "任务"],
                    },
                    "sources": [str(Path(td) / "missing.pdf")],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        missing_proc = subprocess.run(
            ["python3", str(GENERATOR), "create", "--request", str(missing_request_path), "--plan-only"],
            cwd=REPO,
            text=True,
            capture_output=True,
        )
        if missing_proc.returncode != 0:
            print(missing_proc.stdout)
            print(missing_proc.stderr, file=sys.stderr)
            return missing_proc.returncode
        missing_task = json.loads(missing_proc.stdout)
        if missing_task.get("status") != "awaiting_outline_confirmation":
            print(json.dumps(missing_task, ensure_ascii=False, indent=2), file=sys.stderr)
            return 1
        if not any("素材/来源需确认" in warning for warning in missing_task.get("warnings", [])):
            print("missing source was not surfaced as a non-blocking warning", file=sys.stderr)
            return 1

    proc = subprocess.run(
        ["python3", str(GENERATOR), "create", "--request", str(REQUEST), "--plan-only"],
        cwd=REPO,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
        return proc.returncode

    task = json.loads(proc.stdout)
    if task.get("status") != "awaiting_outline_confirmation":
        print(json.dumps(task, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    output_dir = Path(task["output_dir"])
    if not (output_dir / "DESIGN_PLAN.md").exists():
        print("design plan was not written", file=sys.stderr)
        return 1

    confirm_proc = subprocess.run(
        ["python3", str(GENERATOR), "confirm-outline", task["id"]],
        cwd=REPO,
        text=True,
        capture_output=True,
    )
    if confirm_proc.returncode != 0:
        print(confirm_proc.stdout)
        print(confirm_proc.stderr, file=sys.stderr)
        return confirm_proc.returncode
    task = json.loads(confirm_proc.stdout)
    if task.get("status") != "awaiting_rehearsal_decision":
        print(json.dumps(task, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    if task.get("artifacts", {}).get("magic_page_url"):
        print("deck was published before rehearsal confirmation", file=sys.stderr)
        return 1

    output_dir = Path(task["output_dir"])
    missing = [name for name in REQUIRED if not (output_dir / name).exists()]
    zip_paths = sorted(output_dir.glob("*.zip"))
    if not zip_paths:
        missing.append("editable zip")
    if missing:
        print(f"missing generator artifacts: {', '.join(missing)}", file=sys.stderr)
        return 1

    zip_path = zip_paths[0]
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        missing_in_zip = [name for name in ZIP_REQUIRED if name not in names]
        has_assets = any(name.startswith("assets/") and not name.endswith("/") for name in names)
    if missing_in_zip or not has_assets:
        print(f"bad editable zip: {zip_path}", file=sys.stderr)
        if missing_in_zip:
            print(f"  missing: {', '.join(missing_in_zip)}", file=sys.stderr)
        if not has_assets:
            print("  missing asset files under assets/", file=sys.stderr)
        return 1

    accept_proc = subprocess.run(
        ["python3", str(GENERATOR), "accept-rehearsal", task["id"]],
        cwd=REPO,
        text=True,
        capture_output=True,
    )
    if accept_proc.returncode != 0:
        print(accept_proc.stdout)
        print(accept_proc.stderr, file=sys.stderr)
        return accept_proc.returncode
    accepted_task = json.loads(accept_proc.stdout)
    if accepted_task.get("status") != "awaiting_deck_confirmation":
        print(json.dumps(accepted_task, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    if not accepted_task.get("artifacts", {}).get("magic_page_url", "").startswith("https://magic.solutionsuite.cn/dryrun/"):
        print("accepted task magic_page_url missing Magic Page dry-run link", file=sys.stderr)
        return 1
    for name in ["magic-page-publish.json", "MAGIC_PAGE_PUBLISH.md"]:
        if not (Path(accepted_task["output_dir"]) / name).exists():
            print(f"accepted task missing publish artifact: {name}", file=sys.stderr)
            return 1

    with tempfile.TemporaryDirectory() as td:
        patch_path = Path(td) / "edit.json"
        patch_path.write_text(
            json.dumps(
                {
                    "updates": {"title": "连锁零售 AI 知识库 pitch v2"},
                    "client_events": [
                        {"type": "global_edit", "active_key": "cover", "detail": {"field": "deck-title"}},
                        {"type": "save", "active_key": "cover", "detail": {"count": 2}},
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        edit_proc = subprocess.run(
            [
                "python3",
                str(GENERATOR),
                "edit",
                task["id"],
                "--patch",
                str(patch_path),
                "--base-url",
                "http://127.0.0.1:8765",
            ],
            cwd=REPO,
            text=True,
            capture_output=True,
        )
    if edit_proc.returncode != 0:
        print(edit_proc.stdout)
        print(edit_proc.stderr, file=sys.stderr)
        return edit_proc.returncode

    edited_task = json.loads(edit_proc.stdout)
    if edited_task.get("status") != "awaiting_rehearsal_decision":
        print(json.dumps(edited_task, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    if edited_task.get("parent_task_id") != task["id"] or edited_task.get("version") != 1:
        print("edited task is missing parent/version metadata", file=sys.stderr)
        return 1
    edited_deck = json.loads((Path(edited_task["output_dir"]) / "deck.json").read_text(encoding="utf-8"))
    if edited_deck["deck"]["title"] != "连锁零售 AI 知识库 pitch v2":
        print("edited deck title did not update", file=sys.stderr)
        return 1
    if edited_task.get("artifacts", {}).get("magic_page_url"):
        print("edited task was published before rehearsal confirmation", file=sys.stderr)
        return 1
    edited_output_dir = Path(edited_task["output_dir"])
    journey = json.loads((edited_output_dir / "journey.json").read_text(encoding="utf-8"))
    insights = json.loads((edited_output_dir / "quality-insights.json").read_text(encoding="utf-8"))
    if not journey.get("edit_sessions") or not insights.get("recommendations"):
        print("edited task missing journey learning signals", file=sys.stderr)
        return 1
    if insights.get("action_counts", {}).get("global_edit") != 1:
        print("edited task did not preserve sanitized client edit events", file=sys.stderr)
        return 1

    sys.path.insert(0, str(REPO / "server"))
    import generator  # noqa: PLC0415

    status_page = generator.render_status_page(edited_task["id"]).decode("utf-8")
    edit_page = generator.render_edit_page(edited_task["id"]).decode("utf-8")
    journey_page = generator.render_journey_page(edited_task["id"]).decode("utf-8")
    expected_status = ["验收报告", "Pitch 预演", "等待确认预演", "版本", "用户旅程", "精调信号", edited_task["id"]]
    expected_editor = ["轻量编辑", "全局信息", "素材库", "插入已有 slide", "保存并生成新版本", "slide-editor"]
    if (
        any(phrase not in status_page for phrase in expected_status)
        or any(phrase not in edit_page for phrase in expected_editor)
        or "对下一次生成的改进建议" not in journey_page
    ):
        print("status/edit HTML pages did not render expected content", file=sys.stderr)
        return 1
    if not generator.slide_library_items():
        print("local slide library is empty", file=sys.stderr)
        return 1

    print(output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
