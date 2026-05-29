#!/usr/bin/env python3
"""Import deck-renderer shared assets into the configured Feishu/Lark Base.

The import preserves the renderer relationship:

- 素材ID == DeckJSON引用Key == asset-index item id
- 本地路径 points at the canonical repo asset path
- 素材附件 mirrors the same file so Base owns a copy of the resource
- 调用示例 includes asset_ref / local_path for downstream renderer lookup
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[1]
CONFIG = REPO / "config" / "base-library.json"
INDEX = REPO / "skills" / "deck-renderer" / "assets" / "shared" / "asset-index.generated.json"

TARGET_COLLECTIONS = {
    "bytedance-products",
    "clientlogo",
    "digital_employee_avatars_50",
    "mydigitalemployee",
    "feishu-products",
    "third-party-logos",
}

CATEGORY_BY_COLLECTION = {
    "bytedance-products": "用户logo",
    "clientlogo": "用户logo",
    "digital_employee_avatars_50": "数字人头像",
    "mydigitalemployee": "数字人头像",
    "feishu-products": "飞书icon",
    "third-party-logos": "用户logo",
}

USAGE_BY_COLLECTION = {
    "bytedance-products": ["cover-logo", "icon"],
    "clientlogo": ["cover-logo"],
    "digital_employee_avatars_50": ["avatar"],
    "mydigitalemployee": ["avatar"],
    "feishu-products": ["cover-logo", "icon"],
    "third-party-logos": ["cover-logo", "icon"],
}

PAGE_TYPES_BY_COLLECTION = {
    "bytedance-products": ["cover", "content-2col"],
    "clientlogo": ["cover"],
    "digital_employee_avatars_50": ["content-2col", "content-3up"],
    "mydigitalemployee": ["content-2col", "content-3up"],
    "feishu-products": ["cover", "content-2col"],
    "third-party-logos": ["content-2col", "content-3up"],
}

PRODUCTS_BY_COLLECTION = {
    "bytedance-products": ["通用"],
    "clientlogo": ["飞书"],
    "digital_employee_avatars_50": ["通用"],
    "mydigitalemployee": ["通用"],
    "feishu-products": ["飞书"],
    "third-party-logos": ["通用"],
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def repo_rel(path: Path) -> str:
    return path.resolve().relative_to(REPO).as_posix()


def run_lark(args: list[str], *, dry_run: bool = False) -> dict[str, Any]:
    if dry_run:
        return {"dry_run": True, "argv": ["lark-cli", "base", *args]}
    proc = subprocess.run(
        ["lark-cli", "base", *args],
        cwd=REPO,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"lark-cli returned non-JSON output: {proc.stdout}") from exc


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


def existing_records(base_token: str, table_id: str, identity: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    offset = 0
    while True:
        payload = run_lark(
            [
                "+record-list",
                "--format",
                "json",
                "--limit",
                "200",
                "--offset",
                str(offset),
                "--field-id",
                "素材ID",
                "--field-id",
                "素材附件",
                "--as",
                identity,
                "--base-token",
                base_token,
                "--table-id",
                table_id,
            ]
        )
        rows = rows_from_payload(payload)
        for row in rows:
            asset_id = str(row.get("素材ID") or "")
            if asset_id:
                out[asset_id] = row
        if not payload.get("data", {}).get("has_more"):
            break
        if not rows:
            break
        offset += len(rows)
    return out


def size_label(size_bytes: int) -> str:
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes} B"


def item_local_path(item: dict[str, Any]) -> str:
    path = str(item["path"])
    if path.startswith("assets/shared/"):
        return f"skills/deck-renderer/{path}"
    if path.startswith("shared/"):
        return f"skills/deck-renderer/assets/{path}"
    return f"skills/deck-renderer/assets/shared/{path}"


def fields_for_item(item: dict[str, Any], verified_at: str) -> dict[str, Any]:
    collection = str(item["collection"])
    asset_id = str(item["id"])
    display_name = str(item["display_name"])
    local_path = item_local_path(item)
    category = CATEGORY_BY_COLLECTION.get(collection, "图片")
    tags = [
        "shared-assets",
        collection,
        str(item.get("kind") or ""),
        category,
        display_name,
    ]
    tags.extend(str(tag) for tag in item.get("tags", []) if tag)
    tags = list(dict.fromkeys(tag for tag in tags if tag))
    call_example = {
        "asset_ref": asset_id,
        "deckjson_ref": f"asset:{asset_id}",
        "local_path": local_path,
        "shared_path": item.get("path"),
        "collection": collection,
    }
    fields: dict[str, Any] = {
        "素材ID": asset_id,
        "素材名称": display_name,
        "素材类别": category,
        "渲染用途": USAGE_BY_COLLECTION.get(collection, ["decoration"]),
        "适用场景ID": "shared-assets",
        "适合页型": PAGE_TYPES_BY_COLLECTION.get(collection, ["content-2col"]),
        "行业": ["通用"],
        "客户": display_name if collection == "clientlogo" else "",
        "产品组合": PRODUCTS_BY_COLLECTION.get(collection, ["通用"]),
        "DeckJSON引用Key": asset_id,
        "组件Key": "",
        "Renderer加载方式": "attachment",
        "HTML渲染方式": "img",
        "资源URL": "",
        "本地路径": local_path,
        "MIME": item.get("mime") or "",
        "尺寸/时长": size_label(int(item.get("size_bytes") or 0)),
        "可直接渲染": True,
        "质量状态": "可复用",
        "权限状态": "internal",
        "摘要": f"Shared renderer asset from {collection}; local path and attachment mirror the same file.",
        "标签": ", ".join(tags),
        "调用示例": json.dumps(call_example, ensure_ascii=False, sort_keys=True),
        "SHA256": item.get("sha256") or "",
        "来源": local_path,
        "贡献者": "lark-deck-cyrus",
        "最后校验时间": verified_at,
    }
    return {key: value for key, value in fields.items() if value not in ("", [], None)}


def batch_create(
    rows: list[dict[str, Any]],
    *,
    base_token: str,
    table_id: str,
    identity: str,
    dry_run: bool,
) -> list[str]:
    if not rows:
        return []
    fields = list(rows[0].keys())
    body = {"fields": fields, "rows": [[row.get(field) for field in fields] for row in rows]}
    if dry_run:
        return [f"dry-run-{idx}" for idx, _row in enumerate(rows)]
    tmp_dir = REPO / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", dir=tmp_dir, delete=False) as fh:
        json.dump(body, fh, ensure_ascii=False)
        body_path = Path(fh.name)
    try:
        payload = run_lark(
            [
                "+record-batch-create",
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
    record_ids = payload.get("data", {}).get("record_id_list", [])
    if len(record_ids) != len(rows):
        raise RuntimeError(f"batch create returned {len(record_ids)} record ids for {len(rows)} rows")
    return [str(record_id) for record_id in record_ids]


def update_record(
    row: dict[str, Any],
    record_id: str,
    *,
    base_token: str,
    table_id: str,
    identity: str,
    dry_run: bool,
) -> None:
    if dry_run:
        return
    run_lark(
        [
            "+record-upsert",
            "--record-id",
            record_id,
            "--json",
            json.dumps(row, ensure_ascii=False),
            "--as",
            identity,
            "--base-token",
            base_token,
            "--table-id",
            table_id,
        ]
    )


def upload_attachment(
    file_path: Path,
    record_id: str,
    *,
    base_token: str,
    table_id: str,
    attachment_field: str,
    identity: str,
    dry_run: bool,
) -> dict[str, Any]:
    if dry_run:
        return {"dry_run": True, "record_id": record_id, "file": repo_rel(file_path)}
    return run_lark(
        [
            "+record-upload-attachment",
            "--record-id",
            record_id,
            "--field-id",
            attachment_field,
            "--file",
            repo_rel(file_path),
            "--as",
            identity,
            "--base-token",
            base_token,
            "--table-id",
            table_id,
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument("--index", type=Path, default=INDEX)
    parser.add_argument("--as", dest="identity", choices=["user", "bot"], default="user")
    parser.add_argument("--upload-attachments", action="store_true")
    parser.add_argument("--force-upload", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--report", type=Path, default=REPO / "tmp" / "shared-assets-base-import-report.json")
    args = parser.parse_args(argv)

    config = read_json(args.config)
    table_cfg = config["tables"]["assets"]
    base_token = config["base_token"]
    table_id = table_cfg["id"]
    attachment_field = table_cfg.get("attachment_field_id") or "素材附件"
    verified_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    index = read_json(args.index)
    items = [
        item
        for item in index.get("items", [])
        if item.get("collection") in TARGET_COLLECTIONS
    ]
    items.sort(key=lambda item: (str(item.get("collection")), str(item.get("display_name")), str(item.get("id"))))
    if args.limit:
        items = items[: args.limit]

    existing = existing_records(base_token, table_id, args.identity) if not args.dry_run else {}
    created: list[dict[str, Any]] = []
    updated: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    attachment_uploads: list[dict[str, Any]] = []

    new_rows: list[dict[str, Any]] = []
    new_items: list[dict[str, Any]] = []
    record_ids_by_asset: dict[str, str] = {}

    for item in items:
        asset_id = str(item["id"])
        fields = fields_for_item(item, verified_at)
        existing_row = existing.get(asset_id)
        if existing_row:
            record_id = str(existing_row["_record_id"])
            update_record(fields, record_id, base_token=base_token, table_id=table_id, identity=args.identity, dry_run=args.dry_run)
            record_ids_by_asset[asset_id] = record_id
            updated.append({"asset_id": asset_id, "record_id": record_id, "collection": item["collection"]})
        else:
            new_rows.append(fields)
            new_items.append(item)

    for start in range(0, len(new_rows), 200):
        rows = new_rows[start : start + 200]
        chunk_items = new_items[start : start + 200]
        record_ids = batch_create(rows, base_token=base_token, table_id=table_id, identity=args.identity, dry_run=args.dry_run)
        for item, record_id in zip(chunk_items, record_ids):
            asset_id = str(item["id"])
            record_ids_by_asset[asset_id] = record_id
            created.append({"asset_id": asset_id, "record_id": record_id, "collection": item["collection"]})

    existing_after_create = existing
    for item in items:
        asset_id = str(item["id"])
        record_id = record_ids_by_asset.get(asset_id)
        if not record_id:
            skipped.append({"asset_id": asset_id, "reason": "missing record id after create/update"})
            continue
        existing_row = existing_after_create.get(asset_id, {})
        existing_attachments = existing_row.get("素材附件") or []
        if args.upload_attachments and existing_attachments and not args.force_upload:
            skipped.append({"asset_id": asset_id, "record_id": record_id, "reason": "attachment already present"})
            continue
        if not args.upload_attachments:
            continue
        file_path = REPO / item_local_path(item)
        if not file_path.is_file():
            skipped.append({"asset_id": asset_id, "record_id": record_id, "reason": f"file not found: {repo_rel(file_path)}"})
            continue
        try:
            result = upload_attachment(
                file_path,
                record_id,
                base_token=base_token,
                table_id=table_id,
                attachment_field=attachment_field,
                identity=args.identity,
                dry_run=args.dry_run,
            )
            attachment_uploads.append({"asset_id": asset_id, "record_id": record_id, "file": repo_rel(file_path), "ok": True, "result": result})
        except Exception as exc:  # noqa: BLE001 - report per asset and continue
            attachment_uploads.append({"asset_id": asset_id, "record_id": record_id, "file": repo_rel(file_path), "ok": False, "error": str(exc)})

    summary = {
        "ok": all(item.get("ok", True) for item in attachment_uploads),
        "dry_run": args.dry_run,
        "total_items": len(items),
        "created": len(created),
        "updated": len(updated),
        "attachment_uploads": sum(1 for item in attachment_uploads if item.get("ok")),
        "attachment_failures": sum(1 for item in attachment_uploads if not item.get("ok")),
        "skipped": len(skipped),
        "collections": {},
    }
    for item in items:
        collection = str(item.get("collection"))
        summary["collections"][collection] = int(summary["collections"].get(collection, 0)) + 1
    report = {
        "summary": summary,
        "created": created,
        "updated": updated,
        "attachment_uploads": attachment_uploads,
        "skipped": skipped,
    }
    if args.report:
        report_path = args.report if args.report.is_absolute() else REPO / args.report
        write_json(report_path, report)
        report["report_path"] = repo_rel(report_path)
    print(json.dumps({"summary": summary, "report_path": report.get("report_path")}, ensure_ascii=False, indent=2))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
