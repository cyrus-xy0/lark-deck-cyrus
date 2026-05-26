#!/usr/bin/env python3
"""Library provider for deck assets and planning knowledge.

Default mode is auto: try the configured Feishu/Lark Base when available, then
fall back to the local package cache. This keeps external GitHub installs
usable without private Base access while preserving the live Base path for
internal workers.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPO / "config" / "base-library.json"
SKIP_INDEX_NAMES = {"README.md", "asset-index.schema.json", "asset-index.generated.json"}


def load_config(path: Path | None = None) -> dict[str, Any]:
    config_path = path or Path(os.environ.get("LARK_LIBRARY_CONFIG", DEFAULT_CONFIG))
    if not config_path.is_absolute():
        config_path = REPO / config_path
    data = json.loads(config_path.read_text(encoding="utf-8"))
    if os.environ.get("LARK_LIBRARY_BASE_TOKEN"):
        data["base_token"] = os.environ["LARK_LIBRARY_BASE_TOKEN"]
    return data


def library_mode(config: dict[str, Any]) -> str:
    mode = os.environ.get("LARK_LIBRARY_MODE") or config.get("mode") or "auto"
    mode = str(mode).strip().lower()
    return mode if mode in {"auto", "base", "local"} else "auto"


def can_try_base(config: dict[str, Any]) -> bool:
    if library_mode(config) == "local":
        return False
    if not config.get("base_token"):
        return False
    return shutil.which("lark-cli") is not None


def repo_rel(path: Path) -> str:
    return path.resolve().relative_to(REPO).as_posix()


def field_value(record: dict[str, Any], name: str, default: Any = None) -> Any:
    return record.get(name, default)


def scalar(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, list):
        if not value:
            return default
        first = value[0]
        if isinstance(first, dict):
            return str(first.get("name") or first.get("text") or first.get("id") or default)
        return str(first)
    return str(value)


def list_value(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        out = []
        for item in value:
            if isinstance(item, dict):
                out.append(str(item.get("name") or item.get("text") or item.get("id") or ""))
            else:
                out.append(str(item))
        return [item for item in out if item]
    return [str(value)]


def tags(value: Any) -> list[str]:
    if isinstance(value, list):
        raw = list_value(value)
    else:
        raw = [part.strip() for part in str(value or "").split(",") if part.strip()]
    return list(dict.fromkeys(raw))


def run_lark(config: dict[str, Any], table: str, args: list[str], identity: str) -> dict[str, Any]:
    table_cfg = config["tables"][table]
    cmd = [
        "lark-cli",
        "base",
        *args,
        "--as",
        identity,
        "--base-token",
        config["base_token"],
        "--table-id",
        table_cfg["id"],
    ]
    proc = subprocess.run(cmd, cwd=REPO, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise SystemExit(f"base_library: command failed\n{' '.join(cmd)}\n{proc.stderr or proc.stdout}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"base_library: lark-cli returned non-JSON output:\n{proc.stdout}") from exc


def rows_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data", {})
    fields = data.get("fields", [])
    rows = data.get("data", [])
    record_ids = data.get("record_id_list", [])
    out = []
    for idx, row in enumerate(rows):
        item = {field: value for field, value in zip(fields, row)}
        if idx < len(record_ids):
            item["_record_id"] = record_ids[idx]
        out.append(item)
    return out


def list_records(config: dict[str, Any], table: str, identity: str, fields: list[str] | None = None) -> list[dict[str, Any]]:
    table_cfg = config["tables"][table]
    selected = fields or table_cfg["fields"]
    offset = 0
    all_rows: list[dict[str, Any]] = []
    while True:
        args = ["+record-list", "--format", "json", "--limit", "200", "--offset", str(offset)]
        for field in selected:
            args.extend(["--field-id", field])
        payload = run_lark(config, table, args, identity)
        rows = rows_from_payload(payload)
        all_rows.extend(rows)
        if not payload.get("data", {}).get("has_more"):
            break
        offset += len(rows)
        if not rows:
            break
    return all_rows


def search_records(config: dict[str, Any], table: str, keyword: str, identity: str, limit: int) -> list[dict[str, Any]]:
    if not keyword.strip():
        raise SystemExit("base_library: search keyword cannot be empty")
    table_cfg = config["tables"][table]
    body = {
        "keyword": keyword,
        "search_fields": table_cfg["search_fields"],
        "select_fields": table_cfg["fields"],
        "limit": limit,
        "offset": 0,
    }
    payload = run_lark(config, table, ["+record-search", "--format", "json", "--json", json.dumps(body, ensure_ascii=False)], identity)
    return rows_from_payload(payload)


def local_asset_rows(config: dict[str, Any], keyword: str, limit: int) -> list[dict[str, Any]]:
    index_path = REPO / config["local_cache"]["asset_index"]
    if not index_path.exists():
        return []
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    terms = [part.lower() for part in keyword.split() if part.strip()]
    if not terms:
        return []
    rows = []
    for item in payload.get("items", []):
        haystack = " ".join(
            [
                str(item.get("id", "")),
                str(item.get("display_name", "")),
                str(item.get("kind", "")),
                str(item.get("collection", "")),
                str(item.get("path", "")),
                " ".join(str(tag) for tag in item.get("tags", [])),
            ]
        ).lower()
        if all(term in haystack for term in terms) or any(term in haystack for term in terms):
            rel_path = "skills/deck-renderer/" + str(item.get("path", ""))
            rows.append(
                {
                    "素材ID": item.get("id", ""),
                    "显示名称": item.get("display_name", ""),
                    "类型": item.get("kind", ""),
                    "集合": item.get("collection", ""),
                    "格式": Path(str(item.get("path", ""))).suffix.lstrip("."),
                    "MIME": item.get("mime", ""),
                    "本地路径": rel_path,
                    "大小KB": round(int(item.get("size_bytes") or 0) / 1024, 1),
                    "SHA256": item.get("sha256", ""),
                    "标签": item.get("tags", []),
                    "适用场景": "local package cache",
                    "附件": [],
                }
            )
            if len(rows) >= limit:
                break
    return rows


def title_from_text(path: Path, text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#"):
            return line.lstrip("#").strip() or path.stem
    return path.stem.replace("-", " ")


def local_knowledge_rows(config: dict[str, Any], keyword: str, limit: int) -> list[dict[str, Any]]:
    roots = [REPO / config["local_cache"].get("knowledge", "knowledge")]
    if os.environ.get("LARK_LIBRARY_INCLUDE_BASE_CACHE", "").lower() in {"1", "true", "yes"}:
        roots.append(REPO / config["local_cache"].get("base_knowledge", ".base-cache/knowledge"))
    terms = [part.lower() for part in keyword.split() if part.strip()]
    if not terms:
        return []
    rows = []
    seen: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in {".md", ".json", ".txt"}:
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            haystack = f"{path.as_posix()}\n{text}".lower()
            if not (all(term in haystack for term in terms) or any(term in haystack for term in terms)):
                continue
            rel = repo_rel(path)
            summary = " ".join(text.replace("\n", " ").split())[:240]
            rows.append(
                {
                    "文档ID": path.stem,
                    "标题": title_from_text(path, text),
                    "类型": "local-cache",
                    "本地路径": rel,
                    "内容": text[:2000],
                    "摘要": summary,
                    "来源等级": "local-cache",
                    "关联行业": rel,
                    "字数": len(text),
                    "SHA256": "",
                    "附件": [],
                }
            )
            if len(rows) >= limit:
                return rows
    return rows


def search_with_fallback(config: dict[str, Any], table: str, keyword: str, identity: str, limit: int) -> list[dict[str, Any]]:
    if can_try_base(config):
        try:
            return search_records(config, table, keyword, identity, limit)
        except SystemExit:
            if library_mode(config) == "base":
                raise
    elif library_mode(config) == "base":
        raise SystemExit("base_library: live Base mode requested, but base_token or lark-cli is missing")

    if table == "assets":
        return local_asset_rows(config, keyword, limit)
    return local_knowledge_rows(config, keyword, limit)


def attachment_list(record: dict[str, Any]) -> list[dict[str, Any]]:
    value = record.get("附件") or []
    return value if isinstance(value, list) else []


def download_attachment(
    config: dict[str, Any],
    table: str,
    record: dict[str, Any],
    output_path: Path,
    identity: str,
    overwrite: bool,
) -> bool:
    attachments = attachment_list(record)
    if not attachments:
        return False
    token = attachments[0].get("file_token")
    if not token:
        return False
    size = attachments[0].get("size")
    if output_path.exists() and not overwrite and (not size or output_path.stat().st_size == int(size)):
        return False
    output_path.parent.mkdir(parents=True, exist_ok=True)
    args = [
        "+record-download-attachment",
        "--record-id",
        record["_record_id"],
        "--file-token",
        str(token),
        "--output",
        repo_rel(output_path),
        "--overwrite",
    ]
    run_lark(config, table, args, identity)
    return True


def shared_asset_records(config: dict[str, Any], identity: str) -> list[dict[str, Any]]:
    rows = list_records(config, "assets", identity)
    return [
        row
        for row in rows
        if scalar(row.get("本地路径")).startswith("skills/deck-renderer/assets/shared/")
        and Path(scalar(row.get("本地路径"))).name not in SKIP_INDEX_NAMES
    ]


def normalize_shared_asset_path(path: str) -> str:
    return path


def sync_shared_assets(config: dict[str, Any], identity: str, overwrite: bool, quiet: bool) -> dict[str, int]:
    if not can_try_base(config):
        if library_mode(config) == "base":
            raise SystemExit("base_library: live Base mode requested, but base_token or lark-cli is missing")
        if not quiet:
            print(json.dumps({"records": 0, "downloaded": 0, "skipped": 0, "mode": "local-cache"}, ensure_ascii=False, indent=2))
        return {"records": 0, "downloaded": 0, "skipped": 0}
    records = shared_asset_records(config, identity)
    downloaded = 0
    skipped = 0
    for row in records:
        target = REPO / normalize_shared_asset_path(scalar(row.get("本地路径")))
        if download_attachment(config, "assets", row, target, identity, overwrite):
            downloaded += 1
        else:
            skipped += 1
    if not quiet:
        print(json.dumps({"records": len(records), "downloaded": downloaded, "skipped": skipped}, ensure_ascii=False, indent=2))
    return {"records": len(records), "downloaded": downloaded, "skipped": skipped}


def asset_index_from_base(config: dict[str, Any], identity: str) -> dict[str, Any]:
    items = []
    for row in shared_asset_records(config, identity):
        full_path = normalize_shared_asset_path(scalar(row.get("本地路径")))
        rel_path = full_path.removeprefix("skills/deck-renderer/")
        attachments = attachment_list(row)
        size_bytes = int(attachments[0].get("size", 0)) if attachments else int(float(row.get("大小KB") or 0) * 1024)
        items.append(
            {
                "collection": scalar(row.get("集合"), "root"),
                "display_name": scalar(row.get("显示名称")),
                "id": scalar(row.get("素材ID")),
                "kind": scalar(row.get("类型"), "other"),
                "mime": scalar(row.get("MIME"), "application/octet-stream"),
                "path": rel_path,
                "sha256": scalar(row.get("SHA256")),
                "size_bytes": size_bytes,
                "tags": tags(row.get("标签")),
            }
        )
    items.sort(key=lambda item: item["id"])
    return {"version": "1.0", "root": "assets/shared", "source": "feishu-base", "items": items}


def write_asset_index(config: dict[str, Any], identity: str, output: Path | None, check: bool) -> int:
    out = output or (REPO / config["local_cache"]["asset_index"])
    if not out.is_absolute():
        out = REPO / out
    if not can_try_base(config):
        if library_mode(config) == "base":
            raise SystemExit("base_library: live Base mode requested, but base_token or lark-cli is missing")
        if check:
            if out.exists():
                print(f"asset index present in local package cache: {repo_rel(out)}")
                return 0
            print(f"asset index missing from local package cache: {repo_rel(out)}", file=sys.stderr)
            return 1
        print(f"using local package cache; did not rewrite {repo_rel(out)}")
        return 0
    rendered = json.dumps(asset_index_from_base(config, identity), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if check:
        current = out.read_text(encoding="utf-8") if out.exists() else ""
        if current != rendered:
            print(f"asset index is stale against Base: {repo_rel(out)}", file=sys.stderr)
            return 1
        print(f"asset index OK against Base: {repo_rel(out)}")
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(rendered, encoding="utf-8")
    print(f"wrote {repo_rel(out)} ({len(json.loads(rendered)['items'])} Base assets)")
    return 0


def print_records(rows: list[dict[str, Any]], table: str, fmt: str) -> None:
    if fmt == "json":
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    for row in rows:
        if table == "assets":
            attachments = attachment_list(row)
            print(
                f"- {scalar(row.get('素材ID'))} | {scalar(row.get('显示名称'))} | "
                f"{scalar(row.get('类型'))}/{scalar(row.get('格式'))} | {scalar(row.get('集合'))} | "
                f"{scalar(row.get('本地路径'))} | attachments={len(attachments)}"
            )
        else:
            print(
                f"- {scalar(row.get('文档ID'))} | {scalar(row.get('标题'))} | "
                f"{scalar(row.get('类型'))} | {scalar(row.get('关联行业'))} | {scalar(row.get('本地路径'))}\n"
                f"  {scalar(row.get('摘要'))}"
            )


def sync_knowledge_cache(config: dict[str, Any], identity: str, overwrite: bool, quiet: bool) -> dict[str, int]:
    if not can_try_base(config):
        if library_mode(config) == "base":
            raise SystemExit("base_library: live Base mode requested, but base_token or lark-cli is missing")
        if not quiet:
            print(json.dumps({"records": 0, "downloaded": 0, "skipped": 0, "mode": "local-cache"}, ensure_ascii=False, indent=2))
        return {"records": 0, "downloaded": 0, "skipped": 0}
    records = list_records(config, "knowledge", identity)
    cache_root = REPO / config["local_cache"].get("base_knowledge", ".base-cache/knowledge")
    downloaded = 0
    skipped = 0
    for row in records:
        local_path = scalar(row.get("本地路径")) or f"{scalar(row.get('文档ID'))}.md"
        target = cache_root / local_path
        if download_attachment(config, "knowledge", row, target, identity, overwrite):
            downloaded += 1
        else:
            skipped += 1
    if not quiet:
        print(json.dumps({"records": len(records), "downloaded": downloaded, "skipped": skipped}, ensure_ascii=False, indent=2))
    return {"records": len(records), "downloaded": downloaded, "skipped": skipped}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="config/base-library.json override")
    parser.add_argument("--as", dest="identity", choices=["user", "bot"], default=os.environ.get("LARK_LIBRARY_AS", "user"))
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("search-assets", help="search assets from live Base or local package cache")
    p.add_argument("keyword")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--format", choices=["markdown", "json"], default="markdown")

    p = sub.add_parser("search-knowledge", help="search knowledge from live Base or local package cache")
    p.add_argument("keyword")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--format", choices=["markdown", "json"], default="markdown")

    p = sub.add_parser("sync-shared-assets", help="sync Base shared asset attachments into the local cache copy")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--export-index", action="store_true", help="also regenerate asset-index.generated.json from Base")

    p = sub.add_parser("sync-knowledge-cache", help="sync Base knowledge attachments into .base-cache/knowledge")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--quiet", action="store_true")

    p = sub.add_parser("export-asset-index", help="write asset-index.generated.json from Base records")
    p.add_argument("--output", type=Path)
    p.add_argument("--check", action="store_true")

    args = parser.parse_args(argv)
    config = load_config(args.config)

    if args.command == "search-assets":
        print_records(search_with_fallback(config, "assets", args.keyword, args.identity, args.limit), "assets", args.format)
        return 0
    if args.command == "search-knowledge":
        print_records(search_with_fallback(config, "knowledge", args.keyword, args.identity, args.limit), "knowledge", args.format)
        return 0
    if args.command == "sync-shared-assets":
        sync_shared_assets(config, args.identity, args.overwrite, args.quiet)
        if args.export_index:
            return write_asset_index(config, args.identity, None, False)
        return 0
    if args.command == "sync-knowledge-cache":
        sync_knowledge_cache(config, args.identity, args.overwrite, args.quiet)
        return 0
    if args.command == "export-asset-index":
        return write_asset_index(config, args.identity, args.output, args.check)
    raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
