#!/usr/bin/env python3
"""Library provider for deck assets, planning knowledge, and local slide reuse.

Default mode is auto: try the configured Feishu/Lark Base when available, then
fall back to the local package cache. This keeps external GitHub installs
usable without private Base access while preserving the live Base path for
internal workers. Base currently stores only knowledge and material assets;
the Slide Library remains local-only for whole-page selection/reuse.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
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
    for table_key, env_key in {
        "assets": "LARK_LIBRARY_ASSETS_TABLE_ID",
        "knowledge": "LARK_LIBRARY_KNOWLEDGE_TABLE_ID",
    }.items():
        table_cfg = data.get("tables", {}).get(table_key, {})
        config_env_key = table_cfg.get("env_table_id")
        value = os.environ.get(env_key) or (os.environ.get(config_env_key) if config_env_key else "")
        if value and table_key in data.get("tables", {}):
            data["tables"][table_key]["id"] = value
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
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO).as_posix()
    except ValueError:
        return resolved.as_posix()


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


def scalar_any(record: dict[str, Any], *names: str, default: str = "") -> str:
    for name in names:
        value = record.get(name)
        if value is None or value == []:
            continue
        rendered = scalar(value)
        if rendered:
            return rendered
    return default


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


def split_terms(value: Any) -> list[str]:
    raw: list[str] = []
    for item in list_value(value):
        raw.extend(part.strip() for part in re.split(r"[,，、/|]", item) if part.strip())
    return [item for item in dict.fromkeys(raw) if item and item != "待标注"]


def join_tags(values: list[Any]) -> str:
    out: list[str] = []
    for value in values:
        out.extend(split_terms(value))
    return ", ".join(out)


def table_field_names(config: dict[str, Any], table: str) -> set[str]:
    return set(config.get("tables", {}).get(table, {}).get("fields", []))


def table_has(config: dict[str, Any], table: str, field: str) -> bool:
    return field in table_field_names(config, table)


def configured_fields(config: dict[str, Any], table: str, fields: dict[str, Any]) -> dict[str, Any]:
    names = table_field_names(config, table)
    if not names:
        return fields
    out: dict[str, Any] = {}
    for key, value in fields.items():
        if key not in names:
            continue
        if value is None or value == "" or value == []:
            continue
        out[key] = value
    return out


def source_text(*parts: Any) -> str:
    rendered = [str(part).strip() for part in parts if str(part or "").strip()]
    return " | ".join(rendered)


def mapped_industries(value: Any) -> list[str]:
    mapped: list[str] = []
    for term in split_terms(value):
        low = term.lower()
        if any(key in term for key in ["连锁", "门店"]):
            mapped.append("连锁门店")
        elif any(key in term for key in ["零售", "消费", "餐饮"]):
            mapped.append("零售消费")
        elif any(key in term for key in ["金融", "投资", "银行", "保险", "证券"]):
            mapped.append("金融投资")
        elif any(key in term for key in ["制造", "供应链", "工厂"]):
            mapped.append("制造供应链")
        elif any(key in term for key in ["企业服务", "saas", "SaaS", "软件", "互联网"]) or "enterprise" in low:
            mapped.append("企业服务")
        elif "通用" in term:
            mapped.append("通用")
    return list(dict.fromkeys(mapped or ["通用"]))


def mapped_products(value: Any) -> list[str]:
    mapped: list[str] = []
    for term in split_terms(value):
        low = term.lower()
        if "aily" in low:
            mapped.append("Aily")
        elif "妙搭" in term or "miaoda" in low:
            mapped.append("妙搭")
        elif "多维" in term or "base" in low:
            mapped.append("多维表格")
        elif "知识库" in term or "wiki" in low:
            mapped.append("知识库")
        elif "会议" in term or "meeting" in low:
            mapped.append("飞书会议")
        elif "飞书" in term or "lark" in low or "feishu" in low:
            mapped.append("飞书")
    return list(dict.fromkeys(mapped))


def mapped_scenes(value: Any) -> list[str]:
    mapped: list[str] = []
    for term in split_terms(value):
        low = term.lower()
        if "知识" in term or "ai" in low:
            mapped.append("AI知识库")
        elif "协同" in term or "办公" in term:
            mapped.append("协同办公")
        elif "门店" in term or "运营" in term:
            mapped.append("门店运营")
        elif "项目" in term:
            mapped.append("项目管理")
        elif "客户" in term or "案例" in term:
            mapped.append("客户案例")
        elif "品牌" in term:
            mapped.append("品牌规范")
    return list(dict.fromkeys(mapped))


def mapped_knowledge_type(value: str) -> str:
    low = str(value or "").strip().lower()
    allowed = {"idea", "case-story", "objection", "metric", "qa", "lesson", "prompt", "feedback"}
    if low in allowed:
        return low
    if any(key in low for key in ["case", "story", "客户", "案例"]):
        return "case-story"
    if any(key in low for key in ["objection", "异议", "风险"]):
        return "objection"
    if any(key in low for key in ["metric", "数据", "指标"]):
        return "metric"
    if "qa" in low or "q&a" in low or "问答" in low:
        return "qa"
    if "lesson" in low or "复盘" in low:
        return "lesson"
    if "prompt" in low:
        return "prompt"
    if "feedback" in low or "反馈" in low:
        return "feedback"
    return "idea"


def mapped_asset_type(kind: str, fmt: str, path: str) -> str:
    raw = " ".join([kind or "", fmt or "", Path(path or "").suffix.lstrip(".")]).lower()
    if "logo" in raw:
        return "logo"
    if "video" in raw or raw.endswith("mp4") or raw.endswith("mov"):
        return "video"
    if "demo" in raw:
        return "demo"
    if "template" in raw:
        return "template"
    if "code" in raw:
        return "code"
    if "deckjson" in raw or "deck-json" in raw or "json" in raw:
        return "deck-json"
    if "html" in raw:
        return "html-deck"
    if "ppt" in raw:
        return "ppt"
    if "pdf" in raw:
        return "pdf"
    return "image" if any(key in raw for key in ["image", "icon", "avatar", "png", "jpg", "jpeg", "svg", "webp"]) else "image"


def mapped_credibility(value: str) -> str:
    low = str(value or "").lower()
    if any(key in low for key in ["high", "official", "verified", "approved", "public"]):
        return "high"
    if any(key in low for key in ["low", "draft", "unverified", "needs"]):
        return "low"
    return "medium"


def mapped_knowledge_status(value: str) -> str:
    low = str(value or "").lower()
    if any(key in low for key in ["disable", "forbid", "禁用"]):
        return "禁用"
    if any(key in low for key in ["verify", "验证"]):
        return "需验证"
    if any(key in low for key in ["approved", "reusable", "pass", "可复用"]):
        return "可复用"
    return "待整理"


def mapped_asset_status(value: str) -> str:
    low = str(value or "").lower()
    if any(key in low for key in ["disable", "forbid", "禁用"]):
        return "禁用"
    if any(key in low for key in ["redo", "fail", "重做"]):
        return "需重做"
    if any(key in low for key in ["approved", "reusable", "pass", "可复用"]):
        return "可复用"
    return "待审核"


def slugify_id(*values: str) -> str:
    raw = "-".join(value for value in values if value).lower()
    slug = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
    return slug[:96] or "asset"


def row_path(row: dict[str, Any]) -> str:
    return scalar_any(row, "本地路径", "相对路径", "云端URL")


def collection_from_row(row: dict[str, Any], rel_path: str) -> str:
    raw = scalar_any(row, "集合", "所属目录", default="")
    if raw.startswith(("skills/feishu-deck-h5/assets/shared/", "skills/deck-renderer/assets/shared/", "assets/shared/")):
        parts = Path(rel_path).parts
        return parts[2] if len(parts) > 2 else "root"
    return raw or "root"


def run_lark(config: dict[str, Any], table: str, args: list[str], identity: str) -> dict[str, Any]:
    table_cfg = config["tables"][table]
    if not table_cfg.get("id"):
        raise SystemExit(
            f"base_library: table '{table}' has no configured table id. "
            f"Set {table_cfg.get('env_table_id') or 'the table id in config/base-library.json'}."
        )
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


def local_slide_rows(config: dict[str, Any], keyword: str, limit: int) -> list[dict[str, Any]]:
    roots = [
        REPO / "library/business/slides",
        REPO / "library/business/candidates",
        REPO / "library/business/uploads",
    ]
    terms = [part.lower() for part in keyword.split() if part.strip()]
    if not terms:
        return []
    rows: list[dict[str, Any]] = []

    def walk_text(value: Any) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            out: list[str] = []
            for item in value:
                out.extend(walk_text(item))
            return out
        if isinstance(value, dict):
            out: list[str] = []
            for item in value.values():
                out.extend(walk_text(item))
            return out
        return []

    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.glob("*.json")):
            try:
                entry = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            slide = entry.get("slide") if isinstance(entry.get("slide"), dict) else {}
            source = entry.get("source") if isinstance(entry.get("source"), dict) else {}
            haystack = " ".join(
                str(item)
                for item in [
                    entry.get("id"),
                    entry.get("title"),
                    entry.get("layout"),
                    entry.get("variant"),
                    source.get("deck"),
                    source.get("ppt"),
                    source.get("slide_key"),
                    " ".join(list_value(entry.get("tags"))),
                    " ".join(list_value(entry.get("industry"))),
                    " ".join(list_value(entry.get("product"))),
                    " ".join(walk_text(slide.get("data") or {})),
                ]
                if item
            ).lower()
            if not (all(term in haystack for term in terms) or any(term in haystack for term in terms)):
                continue
            rows.append(
                {
                    "SlideID": entry.get("id", path.stem),
                    "标题": entry.get("title", ""),
                    "SlideKey": slide.get("key") or source.get("slide_key") or "",
                    "Layout": entry.get("layout") or slide.get("layout") or "",
                    "Variant": entry.get("variant") or slide.get("variant", ""),
                    "状态": entry.get("status", "candidate"),
                    "DeckJSON": json.dumps(slide, ensure_ascii=False, sort_keys=True),
                    "HTML片段": entry.get("html_fragment", ""),
                    "缩略图": entry.get("thumbnail", ""),
                    "来源Deck": source.get("deck", ""),
                    "来源PPT": source.get("ppt", ""),
                    "来源页码": source.get("page", ""),
                    "知识记录ID": entry.get("knowledge_record_id", ""),
                    "素材记录ID": entry.get("asset_record_id", ""),
                    "标签": list_value(entry.get("tags")),
                    "行业": list_value(entry.get("industry")),
                    "产品": list_value(entry.get("product")),
                    "客户阶段": list_value(entry.get("customer_stage")),
                    "摘要": " ".join(walk_text(slide.get("data") or {}))[:240],
                    "权限状态": entry.get("permission_status", "needs_review"),
                }
            )
            if len(rows) >= limit:
                return rows
    return rows


def search_with_fallback(config: dict[str, Any], table: str, keyword: str, identity: str, limit: int) -> list[dict[str, Any]]:
    if table == "slides":
        return local_slide_rows(config, keyword, limit)
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


def require_base_write(config: dict[str, Any]) -> None:
    if not can_try_base(config):
        raise SystemExit(
            "base_library: write requested, but live Base is unavailable. "
            "Set LARK_LIBRARY_BASE_TOKEN, install/configure lark-cli, and use "
            "LARK_LIBRARY_MODE=base if you want writes to fail fast."
        )


def parse_json_arg(value: str) -> dict[str, Any]:
    stripped = value.strip()
    if stripped.startswith("{"):
        data = json.loads(stripped)
    else:
        path = Path(value)
        if not path.exists():
            raise SystemExit("base_library: --json must be a JSON object string or an existing file path")
        data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit("base_library: --json must be a JSON object")
    return data


def create_record(
    config: dict[str, Any],
    table: str,
    fields: dict[str, Any],
    identity: str,
    record_id: str = "",
    dry_run: bool = False,
) -> dict[str, Any]:
    if table not in config.get("tables", {}):
        known = ", ".join(sorted(config.get("tables", {}).keys()))
        raise SystemExit(f"base_library: unknown table '{table}' (known: {known})")
    if dry_run:
        return {
            "dry_run": True,
            "table": table,
            "table_id": config["tables"][table]["id"],
            "fields": fields,
        }
    require_base_write(config)
    args = ["+record-upsert", "--format", "json", "--json", json.dumps(fields, ensure_ascii=False)]
    if record_id:
        args.extend(["--record-id", record_id])
    return run_lark(config, table, args, identity)


def create_knowledge_fields(args: argparse.Namespace, config: dict[str, Any]) -> dict[str, Any]:
    content = args.content
    if args.content_file:
        content = Path(args.content_file).read_text(encoding="utf-8")
    if table_has(config, "knowledge", "知识标题"):
        fields = {
            "知识标题": args.title,
            "知识类型": mapped_knowledge_type(args.type),
            "正文/要点": content,
            "摘要": args.summary or content[:240],
            "可信度": mapped_credibility(args.source_level),
            "行业": mapped_industries(args.industry),
            "场景": mapped_scenes(args.scene),
            "客户": args.customer,
            "产品": mapped_products(args.product),
            "沉淀状态": mapped_knowledge_status(args.permission_status),
            "来源": source_text(args.source_deck, args.source_ppt, args.source_page, args.local_path),
            "标签": join_tags([args.type, f"slide:{args.slide_key}", f"asset:{args.related_asset_id}"]),
            "适用页面": args.slide_key or args.source_page,
            "关联SlideKey": args.slide_key,
            "关联素材ID": args.related_asset_id,
            "来源Deck": args.source_deck,
            "来源PPT": args.source_ppt,
            "来源页码": args.source_page,
            "权限状态": args.permission_status,
            "本地路径": args.local_path,
            "字数": len(content),
            "SHA256": args.sha256,
        }
        return configured_fields(config, "knowledge", fields)
    return {
        "文档ID": args.doc_id,
        "标题": args.title,
        "类型": args.type,
        "本地路径": args.local_path,
        "内容": content,
        "摘要": args.summary or content[:240],
        "来源等级": args.source_level,
        "关联行业": args.industry,
        "关联SlideKey": args.slide_key,
        "关联素材ID": args.related_asset_id,
        "来源Deck": args.source_deck,
        "来源PPT": args.source_ppt,
        "来源页码": args.source_page,
        "权限状态": args.permission_status,
        "字数": len(content),
        "SHA256": args.sha256,
    }


def create_asset_fields(args: argparse.Namespace, config: dict[str, Any]) -> dict[str, Any]:
    if table_has(config, "assets", "素材标题"):
        asset_type = mapped_asset_type(args.kind, args.format, args.local_path)
        fields = {
            "素材标题": args.display_name,
            "素材类型": asset_type,
            "产品": mapped_products(args.product),
            "行业": mapped_industries(args.industry),
            "场景": mapped_scenes(args.scene),
            "客户": args.customer,
            "云端URL": args.local_path if str(args.local_path).startswith(("http://", "https://")) else "",
            "质量状态": mapped_asset_status(args.permission_status),
            "相对路径": "" if str(args.local_path).startswith(("http://", "https://")) else args.local_path,
            "适用页面": args.slide_key or args.source_page,
            "DriveFileToken": args.drive_file_token,
            "所属目录": args.collection,
            "文件大小KB": args.size_kb,
            "来源": source_text(args.source_deck, args.source_ppt, args.source_page, args.local_path),
            "摘要": args.usage,
            "移动端可用": asset_type in {"image", "logo", "html-deck", "deck-json"},
            "标签": join_tags([args.tags, args.collection, f"slide:{args.slide_key}", f"knowledge:{args.related_knowledge_id}"]),
            "SHA256": args.sha256,
            "关联SlideKey": args.slide_key,
            "关联知识ID": args.related_knowledge_id,
            "来源Deck": args.source_deck,
            "来源PPT": args.source_ppt,
            "来源页码": args.source_page,
            "权限状态": args.permission_status,
            "素材ID": args.asset_id,
            "显示名称": args.display_name,
            "类型": args.kind,
            "集合": args.collection,
            "格式": args.format,
            "MIME": args.mime,
            "本地路径": args.local_path,
            "大小KB": args.size_kb,
            "适用场景": args.usage,
        }
        return configured_fields(config, "assets", fields)
    return {
        "素材ID": args.asset_id,
        "显示名称": args.display_name,
        "类型": args.kind,
        "集合": args.collection,
        "格式": args.format,
        "MIME": args.mime,
        "本地路径": args.local_path,
        "大小KB": args.size_kb,
        "SHA256": args.sha256,
        "标签": args.tags,
        "适用场景": args.usage,
        "关联SlideKey": args.slide_key,
        "关联知识ID": args.related_knowledge_id,
        "来源Deck": args.source_deck,
        "来源PPT": args.source_ppt,
        "来源页码": args.source_page,
        "权限状态": args.permission_status,
    }


def attachment_list(record: dict[str, Any]) -> list[dict[str, Any]]:
    value = record.get("附件") or record.get("素材附件") or []
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
        if normalize_shared_asset_path(row_path(row)).startswith("skills/deck-renderer/assets/shared/")
        and Path(normalize_shared_asset_path(row_path(row))).name not in SKIP_INDEX_NAMES
    ]


def normalize_shared_asset_path(path: str) -> str:
    if path.startswith("skills/feishu-deck-h5/assets/shared/"):
        return path.replace("skills/feishu-deck-h5/assets/shared/", "skills/deck-renderer/assets/shared/", 1)
    if path.startswith("assets/shared/"):
        return f"skills/deck-renderer/{path}"
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
        target = REPO / normalize_shared_asset_path(row_path(row))
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
        full_path = normalize_shared_asset_path(row_path(row))
        rel_path = full_path.removeprefix("skills/deck-renderer/")
        attachments = attachment_list(row)
        size_kb = scalar_any(row, "大小KB", "文件大小KB", default="0")
        size_bytes = int(attachments[0].get("size", 0)) if attachments else int(float(size_kb or 0) * 1024)
        display_name = scalar_any(row, "显示名称", "素材标题", default=Path(rel_path).stem)
        collection = collection_from_row(row, rel_path)
        item_id = scalar_any(row, "素材ID") or slugify_id(collection, display_name, scalar_any(row, "SHA256")[:12])
        kind = scalar_any(row, "类型", "素材类型", default="other")
        mime = scalar_any(row, "MIME") or mimetypes.guess_type(rel_path)[0] or "application/octet-stream"
        items.append(
            {
                "collection": collection,
                "display_name": display_name,
                "id": item_id,
                "kind": kind,
                "mime": mime,
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


def doctor(config: dict[str, Any], identity: str, probe: bool) -> int:
    result: dict[str, Any] = {
        "mode": library_mode(config),
        "lark_cli": bool(shutil.which("lark-cli")),
        "base_token": bool(config.get("base_token")),
        "can_try_base": can_try_base(config),
        "slide_library": "local-only",
        "tables": {},
    }
    for table in ["knowledge", "assets"]:
        table_cfg = config.get("tables", {}).get(table, {})
        result["tables"][table] = {
            "id": table_cfg.get("id", ""),
            "name": table_cfg.get("name", table),
            "fields": table_cfg.get("fields", []),
            "search_fields": table_cfg.get("search_fields", []),
        }
        if probe and can_try_base(config):
            try:
                list_records(config, table, identity, fields=table_cfg.get("fields", [])[:1])
                result["tables"][table]["probe"] = {"ok": True}
            except SystemExit as exc:
                result["tables"][table]["probe"] = {"ok": False, "error": str(exc)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if library_mode(config) == "base" and not result["can_try_base"]:
        return 1
    if probe and result["can_try_base"]:
        probes = [item.get("probe", {}).get("ok", True) for item in result["tables"].values()]
        return 0 if all(probes) else 1
    return 0


def print_records(rows: list[dict[str, Any]], table: str, fmt: str) -> None:
    if fmt == "json":
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    for row in rows:
        if table == "assets":
            attachments = attachment_list(row)
            asset_id = scalar_any(row, "素材ID", "素材标题")
            title = scalar_any(row, "显示名称", "素材标题")
            kind = scalar_any(row, "类型", "素材类型")
            fmt_value = scalar_any(row, "格式", "所属目录")
            collection = scalar_any(row, "集合", "产品", "行业")
            path = row_path(row)
            print(
                f"- {asset_id} | {title} | "
                f"{kind}/{fmt_value} | {collection} | "
                f"{path} | attachments={len(attachments)}"
            )
        elif table == "knowledge":
            doc_id = scalar_any(row, "文档ID", "知识标题")
            title = scalar_any(row, "标题", "知识标题")
            kind = scalar_any(row, "类型", "知识类型")
            industry = scalar_any(row, "关联行业", "行业", "场景")
            path = scalar_any(row, "本地路径", "来源", "适用页面")
            print(
                f"- {doc_id} | {title} | "
                f"{kind} | {industry} | {path}\n"
                f"  {scalar(row.get('摘要'))}"
            )
        else:
            print(
                f"- {scalar(row.get('SlideID'))} | {scalar(row.get('标题'))} | "
                f"{scalar(row.get('Layout'))}/{scalar(row.get('Variant'))} | "
                f"key={scalar(row.get('SlideKey'))} | ppt={scalar(row.get('来源PPT'))} | "
                f"{scalar(row.get('摘要'))}"
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
        local_path = scalar_any(row, "本地路径", "适用页面") or f"{scalar_any(row, '文档ID', '知识标题')}.md"
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

    p = sub.add_parser("search-slides", help="search reusable slides from the local Slide Library")
    p.add_argument("keyword")
    p.add_argument("--limit", type=int, default=20)
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

    p = sub.add_parser("doctor", help="show live Base readiness and configured two-table schema")
    p.add_argument("--probe", action="store_true", help="call lark-cli to verify table access when Base credentials are present")

    p = sub.add_parser("create-record", help="create/update a live Base record in any configured table")
    p.add_argument("table", help="configured table key, e.g. assets or knowledge")
    p.add_argument("--json", required=True, help="JSON object string or path")
    p.add_argument("--record-id", default="", help="update an existing record instead of creating")
    p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("create-knowledge", help="create/update a knowledge-library Base record")
    p.add_argument("--doc-id", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--type", default="deck-ingest")
    p.add_argument("--local-path", default="")
    p.add_argument("--content", default="")
    p.add_argument("--content-file")
    p.add_argument("--summary", default="")
    p.add_argument("--source-level", default="internal-draft")
    p.add_argument("--industry", default="")
    p.add_argument("--product", action="append", default=[])
    p.add_argument("--scene", action="append", default=[])
    p.add_argument("--customer", default="")
    p.add_argument("--slide-key", default="")
    p.add_argument("--related-asset-id", default="")
    p.add_argument("--source-deck", default="")
    p.add_argument("--source-ppt", default="")
    p.add_argument("--source-page", default="")
    p.add_argument("--permission-status", default="needs_review")
    p.add_argument("--sha256", default="")
    p.add_argument("--record-id", default="")
    p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("create-asset-record", help="create/update an asset-library Base metadata record")
    p.add_argument("--asset-id", required=True)
    p.add_argument("--display-name", required=True)
    p.add_argument("--kind", default="other")
    p.add_argument("--collection", default="deck-ingest")
    p.add_argument("--format", default="")
    p.add_argument("--mime", default="")
    p.add_argument("--local-path", default="")
    p.add_argument("--size-kb", default="")
    p.add_argument("--sha256", default="")
    p.add_argument("--tags", action="append", default=[])
    p.add_argument("--usage", default="")
    p.add_argument("--industry", action="append", default=[])
    p.add_argument("--product", action="append", default=[])
    p.add_argument("--scene", action="append", default=[])
    p.add_argument("--customer", default="")
    p.add_argument("--drive-file-token", default="")
    p.add_argument("--slide-key", default="")
    p.add_argument("--related-knowledge-id", default="")
    p.add_argument("--source-deck", default="")
    p.add_argument("--source-ppt", default="")
    p.add_argument("--source-page", default="")
    p.add_argument("--permission-status", default="needs_review")
    p.add_argument("--record-id", default="")
    p.add_argument("--dry-run", action="store_true")

    args = parser.parse_args(argv)
    config = load_config(args.config)

    if args.command == "search-assets":
        print_records(search_with_fallback(config, "assets", args.keyword, args.identity, args.limit), "assets", args.format)
        return 0
    if args.command == "search-knowledge":
        print_records(search_with_fallback(config, "knowledge", args.keyword, args.identity, args.limit), "knowledge", args.format)
        return 0
    if args.command == "search-slides":
        print_records(search_with_fallback(config, "slides", args.keyword, args.identity, args.limit), "slides", args.format)
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
    if args.command == "doctor":
        return doctor(config, args.identity, args.probe)
    if args.command == "create-record":
        payload = create_record(
            config,
            args.table,
            parse_json_arg(args.json),
            args.identity,
            record_id=args.record_id,
            dry_run=args.dry_run,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if args.command == "create-knowledge":
        payload = create_record(
            config,
            "knowledge",
            create_knowledge_fields(args, config),
            args.identity,
            record_id=args.record_id,
            dry_run=args.dry_run,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if args.command == "create-asset-record":
        payload = create_record(
            config,
            "assets",
            create_asset_fields(args, config),
            args.identity,
            record_id=args.record_id,
            dry_run=args.dry_run,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
