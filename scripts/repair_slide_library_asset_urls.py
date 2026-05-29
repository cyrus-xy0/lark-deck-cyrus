#!/usr/bin/env python3
"""Repair slide-library asset records that used unauthenticated GitHub raw URLs.

The FuQiang/feishu-slide-library repo can be cloned in the workspace, but raw
GitHub links may return 404 without the user's GitHub credentials. Renderer
records should therefore use the checked-out local path as the primary loading
contract, while provenance stays in 来源/本地路径.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[1]
CONFIG = REPO / "config" / "base-library.json"
BAD_URL_MARKERS = (
    "raw.githubusercontent.com/FuQiang/feishu-slide-library",
    "github.com/FuQiang/feishu-slide-library/raw",
)
LOCAL_PATH_CALL_EXAMPLE = json.dumps(
    {
        "asset_ref_field": "DeckJSON引用Key",
        "local_path_field": "本地路径",
        "renderer": {
            "load": "local-path",
            "render_as_field": "HTML渲染方式",
        },
        "source_note": "GitHub raw URLs are intentionally not used for slide-library assets because they can return 404 without authenticated GitHub access.",
    },
    ensure_ascii=False,
    sort_keys=True,
)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def repo_rel(path: Path) -> str:
    return path.resolve().relative_to(REPO).as_posix()


def run_lark(args: list[str], *, dry_run: bool = False, attempts: int = 4) -> dict[str, Any]:
    if dry_run:
        return {"dry_run": True, "argv": ["lark-cli", "base", *args]}
    last_error = ""
    for attempt in range(1, attempts + 1):
        proc = subprocess.run(
            ["lark-cli", "base", *args],
            cwd=REPO,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=90,
        )
        if proc.returncode == 0:
            return json.loads(proc.stdout)
        last_error = proc.stderr.strip() or proc.stdout.strip()
        if "limited" not in last_error.lower() or attempt == attempts:
            break
        time.sleep(2 * attempt)
    raise RuntimeError(last_error)


def rows_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data", {})
    fields = data.get("fields", [])
    rows = data.get("data", [])
    record_ids = data.get("record_id_list", [])
    out: list[dict[str, Any]] = []
    for idx, row in enumerate(rows):
        item = {field: value for field, value in zip(fields, row)}
        if idx < len(record_ids):
            item["_record_id"] = record_ids[idx]
        out.append(item)
    return out


def list_asset_rows(base_token: str, table_id: str, identity: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    fields = ["素材ID", "资源URL", "本地路径", "Renderer加载方式", "调用示例"]
    while True:
        args = [
            "+record-list",
            "--format",
            "json",
            "--limit",
            "200",
            "--offset",
            str(offset),
            "--as",
            identity,
            "--base-token",
            base_token,
            "--table-id",
            table_id,
        ]
        for field in fields:
            args.extend(["--field-id", field])
        payload = run_lark(args)
        chunk = rows_from_payload(payload)
        rows.extend(chunk)
        if not payload.get("data", {}).get("has_more") or not chunk:
            break
        offset += len(chunk)
    return rows


def normalized_url(value: Any) -> str:
    if isinstance(value, list):
        return " ".join(str(item.get("link") or item.get("text") or item) if isinstance(item, dict) else str(item) for item in value)
    return str(value or "")


def local_path_exists(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    path = Path(text)
    if not path.is_absolute():
        path = REPO / path
    return path.is_file()


def find_bad_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    repairable: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for row in rows:
        asset_id = str(row.get("素材ID") or "")
        url = normalized_url(row.get("资源URL"))
        if not asset_id.startswith("slib-"):
            continue
        if not any(marker in url for marker in BAD_URL_MARKERS):
            continue
        if not local_path_exists(row.get("本地路径")):
            skipped.append(
                {
                    "record_id": row.get("_record_id"),
                    "asset_id": asset_id,
                    "url": url,
                    "local_path": row.get("本地路径"),
                    "reason": "local path missing",
                }
            )
            continue
        repairable.append(
            {
                "record_id": row["_record_id"],
                "asset_id": asset_id,
                "url": url,
                "local_path": row.get("本地路径"),
                "renderer_loading": row.get("Renderer加载方式"),
            }
        )
    return repairable, skipped


def find_bad_call_example_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    repairable: list[dict[str, Any]] = []
    for row in rows:
        asset_id = str(row.get("素材ID") or "")
        call_example = str(row.get("调用示例") or "")
        if not asset_id.startswith("slib-"):
            continue
        if not any(marker in call_example for marker in BAD_URL_MARKERS) and "cloud-url" not in call_example:
            continue
        if not local_path_exists(row.get("本地路径")):
            continue
        repairable.append(
            {
                "record_id": row["_record_id"],
                "asset_id": asset_id,
                "local_path": row.get("本地路径"),
            }
        )
    return repairable


def batch_update(record_ids: list[str], *, patch: dict[str, Any], base_token: str, table_id: str, identity: str, dry_run: bool) -> dict[str, Any]:
    body = {
        "record_id_list": record_ids,
        "patch": patch,
    }
    if dry_run:
        return {"dry_run": True, "records": len(record_ids), "patch": body["patch"]}
    tmp_dir = REPO / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", dir=tmp_dir, delete=False) as fh:
        json.dump(body, fh, ensure_ascii=False)
        body_path = Path(fh.name)
    try:
        return run_lark(
            [
                "+record-batch-update",
                "--json",
                f"@{repo_rel(body_path)}",
                "--as",
                identity,
                "--base-token",
                base_token,
                "--table-id",
                table_id,
            ]
        )
    finally:
        body_path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument("--as", dest="identity", choices=["user", "bot"], default="user")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--sleep", type=float, default=0.5)
    parser.add_argument("--report", type=Path, default=REPO / "tmp" / "slide-library-url-repair-report.json")
    args = parser.parse_args(argv)

    config = read_json(args.config)
    base_token = str(config["base_token"])
    table_id = str(config["tables"]["assets"]["id"])
    rows = list_asset_rows(base_token, table_id, args.identity)
    repairable, skipped = find_bad_rows(rows)
    call_example_repairable = find_bad_call_example_rows(rows)
    updated: list[dict[str, Any]] = []
    call_example_updated: list[dict[str, Any]] = []
    url_patch = {"资源URL": "", "Renderer加载方式": "local-path"}
    batch_size = max(1, min(args.batch_size, 200))
    for start in range(0, len(repairable), batch_size):
        chunk = repairable[start : start + batch_size]
        record_ids = [str(item["record_id"]) for item in chunk]
        result = batch_update(record_ids, patch=url_patch, base_token=base_token, table_id=table_id, identity=args.identity, dry_run=args.dry_run)
        updated.append({"count": len(record_ids), "record_ids": record_ids, "result": result})
        if args.sleep and not args.dry_run:
            time.sleep(args.sleep)
    call_example_patch = {"调用示例": LOCAL_PATH_CALL_EXAMPLE}
    for start in range(0, len(call_example_repairable), batch_size):
        chunk = call_example_repairable[start : start + batch_size]
        record_ids = [str(item["record_id"]) for item in chunk]
        result = batch_update(record_ids, patch=call_example_patch, base_token=base_token, table_id=table_id, identity=args.identity, dry_run=args.dry_run)
        call_example_updated.append({"count": len(record_ids), "record_ids": record_ids, "result": result})
        if args.sleep and not args.dry_run:
            time.sleep(args.sleep)

    summary = {
        "ok": True,
        "dry_run": args.dry_run,
        "scanned": len(rows),
        "repairable": len(repairable),
        "updated": sum(item["count"] for item in updated),
        "call_example_repairable": len(call_example_repairable),
        "call_example_updated": sum(item["count"] for item in call_example_updated),
        "skipped": len(skipped),
        "patch": url_patch,
        "call_example_patch": call_example_patch,
    }
    report = {
        "summary": summary,
        "repairable_sample": repairable[:20],
        "skipped": skipped,
        "updated_batches": updated,
        "call_example_repairable_sample": call_example_repairable[:20],
        "call_example_updated_batches": call_example_updated,
    }
    report_path = args.report if args.report.is_absolute() else REPO / args.report
    write_json(report_path, report)
    print(json.dumps({"summary": summary, "report_path": repo_rel(report_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
