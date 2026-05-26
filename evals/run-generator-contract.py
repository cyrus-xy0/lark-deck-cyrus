#!/usr/bin/env python3
"""Smoke-test the P0 generator wrapper contract.

This check verifies that the productized wrapper, not just the local renderer,
can create a task and emit every fixed handoff artifact:

  deck.json, index.html, texts.md, FEEDBACK.md, assets-manifest.yaml,
  journey artifacts, editable zip
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
GENERATOR = REPO / "server/generator.py"
REQUEST = REPO / "server/examples/brief-request.json"
REQUIRED = [
    "deck.json",
    "index.html",
    "texts.md",
    "FEEDBACK.md",
    "assets-manifest.yaml",
    "journey.json",
    "JOURNEY.md",
    "quality-insights.json",
]
ZIP_REQUIRED = [
    "index.html",
    "texts.md",
    "assets-manifest.yaml",
    "FEEDBACK.md",
    "deck.json",
    "journey.json",
    "JOURNEY.md",
    "quality-insights.json",
]


def main() -> int:
    proc = subprocess.run(
        ["python3", str(GENERATOR), "create", "--request", str(REQUEST)],
        cwd=REPO,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
        return proc.returncode

    task = json.loads(proc.stdout)
    if task.get("status") != "succeeded":
        print(json.dumps(task, ensure_ascii=False, indent=2), file=sys.stderr)
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
    if edited_task.get("status") != "succeeded":
        print(json.dumps(edited_task, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    if edited_task.get("parent_task_id") != task["id"] or edited_task.get("version") != 1:
        print("edited task is missing parent/version metadata", file=sys.stderr)
        return 1
    edited_deck = json.loads((Path(edited_task["output_dir"]) / "deck.json").read_text(encoding="utf-8"))
    if edited_deck["deck"]["title"] != "连锁零售 AI 知识库 pitch v2":
        print("edited deck title did not update", file=sys.stderr)
        return 1
    if not edited_task.get("artifacts", {}).get("preview_url", "").startswith("http://127.0.0.1:8765/decks/"):
        print("edited task preview_url missing base URL", file=sys.stderr)
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
    expected_status = ["Validator 报告", "版本", "用户旅程", "精调信号", edited_task["id"]]
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
