#!/usr/bin/env python3
"""Ingest FuQiang/feishu-slide-library into the configured Base."""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import re
import subprocess
import tempfile
from collections import defaultdict
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import quote


REPO = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPO / "config" / "base-library.json"
DEFAULT_LIBRARY_ROOT = REPO / "tmp" / "feishu-slide-library"
DEFAULT_REPORT = REPO / "tmp" / "feishu-slide-library-base-ingest-report.json"
GITHUB_REPO = "https://github.com/FuQiang/feishu-slide-library"
GITHUB_RAW = "https://raw.githubusercontent.com/FuQiang/feishu-slide-library/main"
MEDIA_EXTS = {".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp", ".mp4", ".mov", ".mp3", ".wav"}
FRAMEWORK_EXTS = {".css", ".js"}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def repo_rel(path: Path) -> str:
    return path.resolve().relative_to(REPO).as_posix()


def library_rel(path: Path, library_root: Path) -> str:
    return path.resolve().relative_to(library_root.resolve()).as_posix()



def blob_url(rel_path: str) -> str:
    return f"{GITHUB_REPO}/blob/main/{quote(rel_path, safe='/')}"


def tree_url(rel_path: str) -> str:
    return f"{GITHUB_REPO}/tree/main/{quote(rel_path, safe='/')}"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(*parts: str) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(part.encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()


def slugify(value: str) -> str:
    value = re.sub(r"[^a-z0-9._-]+", "-", value.strip().lower())
    value = re.sub(r"-{2,}", "-", value).strip("-")
    return value or hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def stable_id(prefix: str, raw: str, max_len: int = 96) -> str:
    slug = slugify(raw)
    candidate = f"{prefix}-{slug}"
    if len(candidate) <= max_len:
        return candidate
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    keep = max_len - len(prefix) - len(digest) - 2
    return f"{prefix}-{slug[:keep].rstrip('-')}-{digest}"


def compact_join(values: list[str], limit: int = 40) -> str:
    out: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in out:
            out.append(text)
    return ", ".join(out[:limit])


def truncate(text: str, max_chars: int = 18000) -> str:
    return text if len(text) <= max_chars else text[: max_chars - 40].rstrip() + "\n\n[已截断，详见来源文档URL]"


def as_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()]


def parse_simple_scalar(value: str) -> Any:
    value = value.strip()
    if value == "[]":
        return []
    if value in {"true", "false"}:
        return value == "true"
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    return value


def fallback_yaml_load(path: Path, error: str) -> dict[str, Any]:
    data: dict[str, Any] = {"_yaml_parse_warning": error}
    current_list_key: str | None = None
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        stripped = raw_line.strip()
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        if indent == 0 and ":" in stripped:
            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip()
            if not value:
                data[key] = []
                current_list_key = key
            else:
                data[key] = parse_simple_scalar(value)
                current_list_key = None
        elif current_list_key and stripped.startswith("- "):
            data.setdefault(current_list_key, []).append(parse_simple_scalar(stripped[2:]))
        elif current_list_key and ":" not in stripped:
            data.setdefault(current_list_key, []).append(parse_simple_scalar(stripped))
    return data


@lru_cache(maxsize=None)
def yaml_load(path: Path) -> dict[str, Any]:
    code = "require 'yaml'; require 'json'; puts JSON.generate(YAML.load_file(ARGV[0]))"
    proc = subprocess.run(
        ["ruby", "-e", code, str(path)],
        cwd=REPO,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        return fallback_yaml_load(path, proc.stderr.strip())
    data = json.loads(proc.stdout)
    return data if isinstance(data, dict) else {}


def run_lark(args: list[str], *, dry_run: bool = False, timeout: int = 60, attempts: int = 2) -> dict[str, Any]:
    if dry_run:
        return {"dry_run": True, "argv": ["lark-cli", "base", *args]}
    last_error = ""
    for attempt in range(1, attempts + 1):
        try:
            proc = subprocess.run(
                ["lark-cli", "base", *args],
                cwd=REPO,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            last_error = f"lark-cli base {' '.join(args[:2])} timed out after {timeout}s (attempt {attempt}/{attempts})"
            continue
        if proc.returncode == 0:
            return json.loads(proc.stdout)
        last_error = proc.stderr.strip() or proc.stdout.strip()
        break
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


def existing_records(
    *,
    base_token: str,
    table_id: str,
    identity: str,
    id_field: str,
    extra_fields: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    offset = 0
    while True:
        cli_args = [
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
        for field in [id_field, *(extra_fields or [])]:
            cli_args.extend(["--field-id", field])
        payload = run_lark(cli_args)
        rows = rows_from_payload(payload)
        for row in rows:
            row_id = str(row.get(id_field) or "")
            if row_id:
                out[row_id] = row
        if not payload.get("data", {}).get("has_more") or not rows:
            break
        offset += len(rows)
    return out


def batch_create(rows: list[dict[str, Any]], *, base_token: str, table_id: str, identity: str, dry_run: bool) -> list[str]:
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
            ],
            dry_run=dry_run,
        )
    finally:
        body_path.unlink(missing_ok=True)
    record_ids = payload.get("data", {}).get("record_id_list", [])
    if len(record_ids) != len(rows):
        raise RuntimeError(f"batch create returned {len(record_ids)} record ids for {len(rows)} rows")
    return [str(record_id) for record_id in record_ids]


def update_record(row: dict[str, Any], record_id: str, *, base_token: str, table_id: str, identity: str, dry_run: bool) -> None:
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


def size_label(size_bytes: int) -> str:
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / 1024 / 1024:.2f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes} B"


def map_industries(*values: Any) -> list[str]:
    text = " ".join(item for value in values for item in as_list(value)).lower()
    checks = [
        ("金融投资", ["金融", "证券", "银行", "保险", "基金", "投资", "finance", "financial", "capital"]),
        ("连锁门店", ["连锁", "门店", "store", "franchise"]),
        ("零售消费", ["零售", "消费", "餐饮", "茶饮", "食品", "美妆", "酒店", "服饰", "retail", "consumer", "restaurant", "hotel"]),
        ("制造供应链", ["制造", "供应链", "工厂", "工业", "医药", "药", "汽车", "manufacturing", "supply", "pharma", "healthcare"]),
        ("企业服务", ["企业服务", "saas", "tob", "to b", "enterprise", "software"]),
    ]
    out = [option for option, needles in checks if any(needle in text for needle in needles)]
    return out or ["通用"]


def map_products(*values: Any) -> list[str]:
    text = " ".join(item for value in values for item in as_list(value)).lower()
    out = ["飞书"]
    for option, needles in [
        ("多维表格", ["多维", "base", "bitable"]),
        ("知识库", ["知识库", "知识管理", "knowledge", "wiki"]),
        ("飞书会议", ["会议", "minutes", "meeting"]),
        ("Aily", ["aily"]),
        ("妙搭", ["妙搭", "miaoda"]),
    ]:
        if any(needle in text for needle in needles):
            out.append(option)
    return list(dict.fromkeys(out))


def map_audience(*values: Any) -> list[str]:
    text = " ".join(item for value in values for item in as_list(value)).lower()
    checks = [
        ("CEO/一号位", ["ceo", "一号位", "老板", "董事长", "总经理"]),
        ("IT负责人", ["it", "cio", "技术", "信息化"]),
        ("HR/组织负责人", ["hr", "人事", "组织", "人才"]),
        ("财务/采购", ["财务", "采购", "cfo", "预算"]),
        ("一线管理者", ["一线", "店长", "区域", "主管"]),
        ("业务负责人", ["业务", "增长", "运营", "销售", "负责人"]),
    ]
    out = [option for option, needles in checks if any(needle in text for needle in needles)]
    return out or ["通用"]


def map_goals(*values: Any) -> list[str]:
    text = " ".join(item for value in values for item in as_list(value)).lower()
    checks = [
        ("知识沉淀", ["知识", "经验", "沉淀", "knowledge"]),
        ("流程提效", ["流程", "提效", "自动化", "process", "workflow"]),
        ("降本增效", ["效率", "成本", "ai", "agent", "数字员工"]),
        ("组织协同", ["协同", "组织", "沟通", "团队", "collaboration"]),
        ("增长转化", ["增长", "销售", "营销", "转化", "growth", "sales"]),
        ("风控合规", ["风控", "合规", "审计", "risk", "compliance"]),
        ("体验升级", ["体验", "客户", "服务", "experience"]),
    ]
    out = [option for option, needles in checks if any(needle in text for needle in needles)]
    return out or ["组织协同"]


def map_page_types(role: str, title: str = "") -> list[str]:
    text = f"{role} {title}".lower()
    checks = [
        ("cover", ["cover", "封面"]),
        ("agenda", ["agenda", "目录"]),
        ("section", ["section", "章节"]),
        ("case-story", ["case", "story", "案例", "客户"]),
        ("quote", ["quote", "金句"]),
        ("timeline", ["timeline", "时间线"]),
        ("process", ["process", "flow", "流程"]),
        ("table", ["table", "matrix", "表格", "矩阵"]),
        ("end", ["closing", "end", "结束"]),
        ("content-3up", ["three", "3", "framework", "三"]),
    ]
    for option, needles in checks:
        if any(needle in text for needle in needles):
            return [option]
    return ["content-2col"]


def map_knowledge_type(meta: dict[str, Any], title: str, *, deck_level: bool = False) -> str:
    if deck_level:
        return "讲法经验"
    text = " ".join(
        [title, str(meta.get("id") or ""), str(meta.get("role") or ""), compact_join(as_list(meta.get("topic"))), compact_join(as_list(meta.get("mentioned_customers")))]
    ).lower()
    if "lark-case" in text or as_list(meta.get("mentioned_customers")):
        return "客户案例"
    if any(token in text for token in ["异议", "objection"]):
        return "异议处理"
    if any(token in text for token in ["指标", "metric", "数据口径"]):
        return "指标口径"
    if any(token in text for token in ["风险", "risk"]):
        return "风险提醒"
    if any(token in text for token in ["痛点", "挑战", "问题"]):
        return "场景痛点"
    if any(token in text for token in ["产品", "能力", "功能", "ai", "base", "知识库", "会议"]):
        return "产品能力"
    return "讲法经验"


def permission_from_confidentiality(value: str) -> str:
    text = value.lower()
    if "public" in text:
        return "public"
    if "share" in text or "approved" in text:
        return "approved"
    if "restricted" in text or "confidential" in text:
        return "restricted"
    return "internal"


def mime_for(path: Path) -> str:
    if path.suffix.lower() == ".md":
        return "text/markdown"
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def render_method(path: Path, *, kind: str) -> str:
    suffix = path.suffix.lower()
    if kind == "slide":
        return "component-json"
    if kind == "deck_html":
        return "iframe"
    if suffix in {".mp4", ".mov"}:
        return "video"
    if suffix in {".mp3", ".wav"}:
        return "audio"
    if suffix == ".css":
        return "css-token"
    if suffix == ".js":
        return "component-json"
    return "img"


def usage_for(path: Path, *, kind: str, rel_path: str) -> list[str]:
    suffix = path.suffix.lower()
    text = rel_path.lower()
    if kind in {"slide", "deck_html"} or suffix in {".css", ".js"}:
        return ["component"]
    if suffix in {".mp4", ".mov"}:
        return ["video"]
    if suffix in {".mp3", ".wav"}:
        return ["audio"]
    if "logo" in text or "clientlogo" in text:
        return ["cover-logo"]
    if "bg" in text or "background" in text:
        return ["background"]
    if "mockup" in text or "demo" in text:
        return ["mockup"]
    return ["hero-image"]


def asset_category(path: Path, *, kind: str) -> str:
    suffix = path.suffix.lower()
    if kind == "slide":
        return "整页Slide"
    if kind == "deck_html":
        return "页面模板"
    if suffix in {".css", ".js"}:
        return "代码片段"
    if suffix in {".mp4", ".mov"}:
        return "视频"
    if suffix in {".mp3", ".wav"}:
        return "音频"
    return "图片"


def clean_fields(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if value not in (None, "", [])}


def slide_asset_id(slide_id: str) -> str:
    return stable_id("slib-slide", slide_id)


def slide_knowledge_id(slide_id: str) -> str:
    return stable_id("slib-know-slide", slide_id)


def deck_asset_id(deck_id: str) -> str:
    return stable_id("slib-deckhtml", deck_id)


def deck_knowledge_id(deck_id: str) -> str:
    return stable_id("slib-know-deck", deck_id)


def media_asset_id(sha: str) -> str:
    return f"slib-media-{sha[:12]}"


def slide_rows(slide_dir: Path, library_root: Path, verified_at: str, deck_has_html: set[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    meta_path = slide_dir / "meta.yaml"
    text_path = slide_dir / "text.md"
    meta = yaml_load(meta_path)
    text = text_path.read_text(encoding="utf-8") if text_path.exists() else ""
    slide_id = str(meta.get("id") or slide_dir.name)
    title = str(meta.get("title") or slide_id)
    role = str(meta.get("role") or "")
    scenarios = as_list(meta.get("scenarios"))
    topics = as_list(meta.get("topic"))
    value_props = as_list(meta.get("value_props"))
    customers = as_list(meta.get("mentioned_customers"))
    source_deck = str(meta.get("source_deck") or meta.get("canonical_source", {}).get("deck_id") or "")
    confidentiality = str(meta.get("confidentiality") or "internal")
    contributor = compact_join(as_list(meta.get("contributors")) or as_list(meta.get("created_by")) or ["FuQiang/feishu-slide-library"])
    rel_dir = library_rel(slide_dir, library_root)
    rel_text = library_rel(text_path, library_root) if text_path.exists() else f"{rel_dir}/text.md"
    rel_meta = library_rel(meta_path, library_root)
    sid = slide_asset_id(slide_id)
    kid = slide_knowledge_id(slide_id)
    linked_assets = [sid]
    if source_deck and source_deck in deck_has_html:
        linked_assets.append(deck_asset_id(source_deck))
    tags = ["slide-library", "slide", slide_id, role, str(meta.get("reuse") or ""), str(meta.get("family_id") or ""), str(meta.get("group_id") or ""), confidentiality, source_deck, *topics, *value_props, *customers]
    knowledge = clean_fields(
        {
            "知识ID": kid,
            "知识标题": title,
            "知识类型": map_knowledge_type(meta, title),
            "适用场景ID": compact_join(scenarios or [str(meta.get("group_id") or ""), source_deck]),
            "Brief关键词": compact_join([title, role, *topics, *value_props, *customers, source_deck]),
            "行业": map_industries(meta.get("industry_scope"), topics, customers, source_deck),
            "业务场景": compact_join(scenarios or topics or [str(meta.get("group_label") or "")]),
            "受众角色": map_audience(title, topics, scenarios),
            "决策目标": map_goals(title, topics, value_props, scenarios),
            "产品组合": map_products(title, topics, value_props, text),
            "正文/要点": truncate(text),
            "推荐讲法": truncate(str(meta.get("summary") or title), 4000),
            "适合页型": map_page_types(role, title),
            "证据/来源": truncate(json.dumps({"library": "FuQiang/feishu-slide-library", "slide_id": slide_id, "source_deck": source_deck, "canonical_source": meta.get("canonical_source") or {}, "version": meta.get("version"), "meta": blob_url(rel_meta), "text": blob_url(rel_text)}, ensure_ascii=False, sort_keys=True), 8000),
            "不适用条件": "未完成人工复核的高度定制页，二次使用前需核对客户/日期/保密级别。",
            "关联素材ID": compact_join(linked_assets),
            "来源文档URL": blob_url(rel_text),
            "可信度": "high" if confidentiality in {"client-shareable", "public"} else "medium",
            "状态": "可复用" if confidentiality != "restricted" else "需验证",
            "标签": compact_join(tags),
            "SHA256": sha256_text(json.dumps(meta, ensure_ascii=False, sort_keys=True), text),
            "贡献者": contributor,
            "最近验证时间": verified_at,
        }
    )
    call_example = {"library": "FuQiang/feishu-slide-library", "kind": "slide_fragment", "knowledge_id": kid, "slide_id": slide_id, "source_deck": source_deck, "deckjson_ref": sid, "source_text_url": blob_url(rel_text), "source_meta_url": blob_url(rel_meta), "local_text_path": repo_rel(text_path) if text_path.exists() else "", "renderer": {"load": "local-path", "render_as": "component-json"}}
    asset = clean_fields(
        {
            "素材ID": sid,
            "素材名称": title,
            "素材类别": "整页Slide",
            "渲染用途": ["component"],
            "适用场景ID": knowledge.get("适用场景ID"),
            "适合页型": knowledge.get("适合页型"),
            "行业": knowledge.get("行业"),
            "客户": compact_join(customers) or "通用",
            "产品组合": knowledge.get("产品组合"),
            "DeckJSON引用Key": sid,
            "组件Key": f"slide-library/{slide_id}",
            "Renderer加载方式": "local-path",
            "HTML渲染方式": "component-json",
            "本地路径": repo_rel(text_path) if text_path.exists() else repo_rel(slide_dir),
            "MIME": "text/markdown",
            "尺寸/时长": size_label(text_path.stat().st_size) if text_path.exists() else "0 B",
            "可直接渲染": False,
            "质量状态": "可复用",
            "权限状态": permission_from_confidentiality(confidentiality),
            "摘要": truncate(str(meta.get("summary") or title), 4000),
            "标签": compact_join(tags),
            "调用示例": json.dumps(call_example, ensure_ascii=False, sort_keys=True),
            "SHA256": knowledge.get("SHA256"),
            "来源": tree_url(rel_dir),
            "贡献者": contributor,
            "最后校验时间": verified_at,
        }
    )
    return knowledge, asset


def deck_rows(deck_dir: Path, library_root: Path, verified_at: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    meta_path = deck_dir / "deck.yaml"
    outline_path = deck_dir / "outline.md"
    source_path = deck_dir / "source.html"
    meta = yaml_load(meta_path)
    outline = outline_path.read_text(encoding="utf-8") if outline_path.exists() else ""
    deck_id = str(meta.get("deck_id") or deck_dir.name)
    title = str(meta.get("title") or deck_id)
    customers = as_list(meta.get("customers"))
    rel_dir = library_rel(deck_dir, library_root)
    rel_meta = library_rel(meta_path, library_root)
    rel_outline = library_rel(outline_path, library_root) if outline_path.exists() else f"{rel_dir}/outline.md"
    kid = deck_knowledge_id(deck_id)
    did = deck_asset_id(deck_id)
    tags = ["slide-library", "deck", deck_id, str(meta.get("deck_type") or ""), str(meta.get("deck_date") or ""), str(meta.get("team") or ""), str(meta.get("confidentiality") or ""), *customers]
    knowledge = clean_fields(
        {
            "知识ID": kid,
            "知识标题": title,
            "知识类型": "讲法经验",
            "适用场景ID": deck_id,
            "Brief关键词": compact_join([title, deck_id, *customers, str(meta.get("industry") or ""), str(meta.get("subindustry") or "")]),
            "行业": map_industries(meta.get("industry"), meta.get("subindustry"), customers),
            "业务场景": compact_join([str(meta.get("deck_type") or ""), str(meta.get("industry") or ""), str(meta.get("subindustry") or "")]),
            "受众角色": map_audience(title, meta.get("audience_level"), meta.get("notes")),
            "决策目标": map_goals(title, outline, meta.get("notes")),
            "产品组合": map_products(title, outline, meta.get("notes")),
            "正文/要点": truncate(outline or json.dumps(meta, ensure_ascii=False, indent=2), 18000),
            "推荐讲法": truncate(f"按 outline.md 作为 deck 叙事骨架复用；source.html 可作为 renderer 参考。客户/行业/场景见证据字段。\n\n{outline}", 6000),
            "适合页型": ["cover", "section", "content-2col", "case-story"],
            "证据/来源": truncate(json.dumps({"library": "FuQiang/feishu-slide-library", "deck_id": deck_id, "deck_yaml": blob_url(rel_meta), "outline": blob_url(rel_outline), "source_html": blob_url(f"{rel_dir}/source.html") if source_path.exists() else "", "source_file": meta.get("source_file") or ""}, ensure_ascii=False, sort_keys=True), 8000),
            "不适用条件": "直接复用前需确认客户授权、行业上下文和日期有效性。",
            "关联素材ID": did if source_path.exists() else "",
            "来源文档URL": blob_url(rel_outline),
            "可信度": "medium",
            "状态": "可复用" if source_path.exists() else "需验证",
            "标签": compact_join(tags),
            "SHA256": sha256_text(json.dumps(meta, ensure_ascii=False, sort_keys=True), outline),
            "贡献者": compact_join(as_list(meta.get("submitted_by")) or as_list(meta.get("ingested_by")) or ["FuQiang/feishu-slide-library"]),
            "最近验证时间": verified_at,
        }
    )
    if not source_path.exists():
        return knowledge, None
    rel_source = library_rel(source_path, library_root)
    call_example = {"library": "FuQiang/feishu-slide-library", "kind": "deck_source_html", "knowledge_id": kid, "deck_id": deck_id, "deckjson_ref": did, "source_url": blob_url(rel_source), "outline_url": blob_url(rel_outline), "local_path": repo_rel(source_path), "renderer": {"load": "local-path", "render_as": "iframe_or_parse_reference"}}
    asset = clean_fields(
        {
            "素材ID": did,
            "素材名称": f"{title} source.html",
            "素材类别": "页面模板",
            "渲染用途": ["component"],
            "适用场景ID": deck_id,
            "适合页型": ["cover", "section", "content-2col", "case-story"],
            "行业": knowledge.get("行业"),
            "客户": compact_join(customers) or "通用",
            "产品组合": knowledge.get("产品组合"),
            "DeckJSON引用Key": did,
            "组件Key": f"slide-library/decks/{deck_id}/source",
            "Renderer加载方式": "local-path",
            "HTML渲染方式": "iframe",
            "本地路径": repo_rel(source_path),
            "MIME": "text/html",
            "尺寸/时长": size_label(source_path.stat().st_size),
            "可直接渲染": True,
            "质量状态": "可复用",
            "权限状态": permission_from_confidentiality(str(meta.get("confidentiality") or "internal")),
            "摘要": f"Old slide library deck source HTML for {deck_id}; linked to knowledge {kid}.",
            "标签": compact_join(tags),
            "调用示例": json.dumps(call_example, ensure_ascii=False, sort_keys=True),
            "SHA256": sha256_file(source_path),
            "来源": blob_url(rel_source),
            "贡献者": knowledge.get("贡献者"),
            "最后校验时间": verified_at,
        }
    )
    return knowledge, asset


def collect_media_assets(library_root: Path, verified_at: str, existing_sha_to_asset: dict[str, str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, str]]:
    grouped: dict[str, list[Path]] = defaultdict(list)
    for path in library_root.rglob("*"):
        if not path.is_file() or (path.suffix.lower() not in MEDIA_EXTS and path.suffix.lower() not in FRAMEWORK_EXTS):
            continue
        rel = library_rel(path, library_root)
        if rel.startswith(("viewer/", "presentations/")):
            continue
        if not (rel.startswith("assets/") or rel.startswith("decks/")):
            continue
        if rel.startswith("decks/") and "/assets/" not in rel and "/source_package/" not in rel:
            continue
        grouped[sha256_file(path)].append(path)

    new_assets: list[dict[str, Any]] = []
    linked_existing: list[dict[str, Any]] = []
    path_to_asset_id: dict[str, str] = {}
    for sha, paths in sorted(grouped.items(), key=lambda item: library_rel(item[1][0], library_root)):
        primary = sorted(paths, key=lambda p: library_rel(p, library_root))[0]
        rel = library_rel(primary, library_root)
        deck_id = rel.split("/")[1] if rel.startswith("decks/") and "/" in rel else ""
        knowledge_id = deck_knowledge_id(deck_id) if deck_id else ""
        existing_asset_id = existing_sha_to_asset.get(sha)
        aid = existing_asset_id or media_asset_id(sha)
        for path in paths:
            path_to_asset_id[library_rel(path, library_root)] = aid
        if existing_asset_id:
            linked_existing.append({"asset_id": existing_asset_id, "sha256": sha, "source_paths": [library_rel(path, library_root) for path in paths], "linked_knowledge_id": knowledge_id})
            continue
        category = asset_category(primary, kind="media")
        call_example = {"library": "FuQiang/feishu-slide-library", "kind": "media", "knowledge_id": knowledge_id, "deck_id": deck_id, "deckjson_ref": aid, "source_url": blob_url(rel), "local_path": repo_rel(primary), "source_paths": [library_rel(path, library_root) for path in paths], "renderer": {"load": "local-path", "render_as": render_method(primary, kind="media")}}
        tags = ["slide-library", "media", category, deck_id, primary.suffix.lower().lstrip("."), *[part for part in rel.split("/") if part in {"framework", "shared", "assets", "source_package"}]]
        new_assets.append(
            clean_fields(
                {
                    "素材ID": aid,
                    "素材名称": primary.stem,
                    "素材类别": category,
                    "渲染用途": usage_for(primary, kind="media", rel_path=rel),
                    "适用场景ID": deck_id or "slide-library-shared",
                    "适合页型": ["cover", "content-2col"] if "logo" in rel.lower() else ["content-2col"],
                    "行业": map_industries(rel),
                    "客户": primary.stem if "clientlogo" in rel else "通用",
                    "产品组合": map_products(rel),
                    "DeckJSON引用Key": aid,
                    "组件Key": f"slide-library/media/{sha[:12]}",
                    "Renderer加载方式": "local-path",
                    "HTML渲染方式": render_method(primary, kind="media"),
                    "本地路径": repo_rel(primary),
                    "MIME": mime_for(primary),
                    "尺寸/时长": size_label(primary.stat().st_size),
                    "可直接渲染": primary.suffix.lower() not in FRAMEWORK_EXTS,
                    "质量状态": "可复用",
                    "权限状态": "internal",
                    "摘要": f"Slide library media resource; {len(paths)} path(s) share this SHA256.",
                    "标签": compact_join(tags),
                    "调用示例": json.dumps(call_example, ensure_ascii=False, sort_keys=True),
                    "SHA256": sha,
                    "来源": blob_url(rel),
                    "贡献者": "FuQiang/feishu-slide-library",
                    "最后校验时间": verified_at,
                }
            )
        )
    return new_assets, linked_existing, path_to_asset_id


REF_RE = re.compile(r"""(?:src|href)=["']([^"']+)["']|url\(["']?([^"')]+)["']?\)""", re.IGNORECASE)


def collect_deck_dependencies(library_root: Path, path_to_asset_id: dict[str, str]) -> dict[str, list[dict[str, str]]]:
    deps_by_deck: dict[str, list[dict[str, str]]] = {}
    for source_path in sorted((library_root / "decks").glob("*/source.html")):
        deck_dir = source_path.parent
        deck_id = str(yaml_load(deck_dir / "deck.yaml").get("deck_id") or deck_dir.name)
        seen: set[str] = set()
        deps: list[dict[str, str]] = []
        html = source_path.read_text(encoding="utf-8", errors="ignore")
        for match in REF_RE.finditer(html):
            ref = (match.group(1) or match.group(2) or "").strip()
            if not ref or ref.startswith(("http://", "https://", "data:", "#", "mailto:", "javascript:")):
                continue
            ref = ref.split("#", 1)[0].split("?", 1)[0]
            candidate = (deck_dir / ref).resolve()
            try:
                rel = library_rel(candidate, library_root)
            except ValueError:
                continue
            asset_id = path_to_asset_id.get(rel)
            if not asset_id or rel in seen:
                continue
            seen.add(rel)
            deps.append({"asset_id": asset_id, "path": rel})
        if deps:
            deps_by_deck[deck_id] = deps
    return deps_by_deck


def attach_deck_dependencies(knowledge_rows: list[dict[str, Any]], asset_rows: list[dict[str, Any]], deps_by_deck: dict[str, list[dict[str, str]]]) -> None:
    knowledge_by_id = {str(row.get("知识ID")): row for row in knowledge_rows}
    for row in asset_rows:
        raw_example = row.get("调用示例")
        if not raw_example:
            continue
        try:
            call_example = json.loads(str(raw_example))
        except json.JSONDecodeError:
            continue
        if call_example.get("kind") != "deck_source_html":
            continue
        deck_id = str(call_example.get("deck_id") or "")
        deps = deps_by_deck.get(deck_id, [])
        if not deps:
            continue
        call_example["dependencies"] = deps
        call_example["dependency_count"] = len(deps)
        row["调用示例"] = json.dumps(call_example, ensure_ascii=False, sort_keys=True)
        row["摘要"] = f"{row.get('摘要', '')} Dependencies: {len(deps)} linked media/framework asset(s).".strip()
        knowledge = knowledge_by_id.get(deck_knowledge_id(deck_id))
        if knowledge:
            linked_ids = [deck_asset_id(deck_id), *[dep["asset_id"] for dep in deps]]
            knowledge["关联素材ID"] = compact_join(linked_ids, limit=160)


def upsert_rows(rows: list[dict[str, Any]], *, existing: dict[str, dict[str, Any]], id_field: str, base_token: str, table_id: str, identity: str, dry_run: bool) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    created: list[dict[str, Any]] = []
    updated: list[dict[str, Any]] = []
    new_rows: list[dict[str, Any]] = []
    new_ids: list[str] = []
    for row in rows:
        row_id = str(row[id_field])
        existing_row = existing.get(row_id)
        if existing_row:
            record_id = str(existing_row["_record_id"])
            update_record(row, record_id, base_token=base_token, table_id=table_id, identity=identity, dry_run=dry_run)
            updated.append({id_field: row_id, "record_id": record_id})
        else:
            new_rows.append(row)
            new_ids.append(row_id)
    for start in range(0, len(new_rows), 200):
        chunk = new_rows[start : start + 200]
        chunk_ids = new_ids[start : start + 200]
        record_ids = batch_create(chunk, base_token=base_token, table_id=table_id, identity=identity, dry_run=dry_run)
        for row_id, record_id in zip(chunk_ids, record_ids):
            created.append({id_field: row_id, "record_id": record_id})
    return created, updated


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--library-root", type=Path, default=DEFAULT_LIBRARY_ROOT)
    parser.add_argument("--as", dest="identity", choices=["user", "bot"], default="user")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit-slides", type=int, default=0)
    parser.add_argument("--limit-decks", type=int, default=0)
    parser.add_argument("--limit-media", type=int, default=0)
    parser.add_argument("--dependency-only", action="store_true")
    parser.add_argument("--asset-dependencies-only", action="store_true")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)

    config = read_json(args.config)
    base_token = str(config["base_token"])
    knowledge_table = config["tables"]["knowledge"]["id"]
    assets_table = config["tables"]["assets"]["id"]
    library_root = args.library_root.resolve()
    verified_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not library_root.is_dir():
        raise SystemExit(f"library root not found: {library_root}")

    deck_dirs = sorted(path for path in (library_root / "decks").iterdir() if (path / "deck.yaml").is_file())
    slide_dirs = sorted(path for path in (library_root / "slides").iterdir() if (path / "meta.yaml").is_file())
    if args.limit_decks:
        deck_dirs = deck_dirs[: args.limit_decks]
    if args.limit_slides:
        slide_dirs = slide_dirs[: args.limit_slides]
    if args.dependency_only:
        slide_dirs = []
    deck_has_html = {str(yaml_load(path / "deck.yaml").get("deck_id") or path.name) for path in deck_dirs if (path / "source.html").is_file()}

    knowledge_rows: list[dict[str, Any]] = []
    asset_rows: list[dict[str, Any]] = []
    for deck_dir in deck_dirs:
        knowledge, asset = deck_rows(deck_dir, library_root, verified_at)
        knowledge_rows.append(knowledge)
        if asset:
            asset_rows.append(asset)
    if not args.dependency_only:
        for slide_dir in slide_dirs:
            knowledge, asset = slide_rows(slide_dir, library_root, verified_at, deck_has_html)
            knowledge_rows.append(knowledge)
            asset_rows.append(asset)

    existing_assets = {} if args.dry_run else existing_records(base_token=base_token, table_id=assets_table, identity=args.identity, id_field="素材ID", extra_fields=["SHA256", "素材附件"])
    existing_sha_to_asset = {str(row.get("SHA256")): str(row.get("素材ID")) for row in existing_assets.values() if row.get("SHA256") and row.get("素材ID")}
    media_rows, linked_existing_media, media_path_to_asset_id = collect_media_assets(library_root, verified_at, existing_sha_to_asset)
    if args.limit_media:
        media_rows = media_rows[: args.limit_media]
    if not args.dependency_only:
        asset_rows.extend(media_rows)
    deps_by_deck = collect_deck_dependencies(library_root, media_path_to_asset_id)
    attach_deck_dependencies(knowledge_rows, asset_rows, deps_by_deck)
    if args.asset_dependencies_only:
        knowledge_rows = []

    existing_knowledge = {} if (args.dry_run or args.asset_dependencies_only) else existing_records(base_token=base_token, table_id=knowledge_table, identity=args.identity, id_field="知识ID", extra_fields=["知识标题"])
    if args.dry_run:
        knowledge_created = [{"知识ID": row["知识ID"], "record_id": "dry-run"} for row in knowledge_rows]
        knowledge_updated: list[dict[str, Any]] = []
        asset_created = [{"素材ID": row["素材ID"], "record_id": "dry-run"} for row in asset_rows]
        asset_updated: list[dict[str, Any]] = []
    else:
        knowledge_created, knowledge_updated = upsert_rows(rows=knowledge_rows, existing=existing_knowledge, id_field="知识ID", base_token=base_token, table_id=knowledge_table, identity=args.identity, dry_run=False)
        asset_created, asset_updated = upsert_rows(rows=asset_rows, existing=existing_assets, id_field="素材ID", base_token=base_token, table_id=assets_table, identity=args.identity, dry_run=False)

    summary = {
        "ok": True,
        "dry_run": args.dry_run,
        "library_root": repo_rel(library_root),
        "slides_parsed": len(slide_dirs),
        "decks_parsed": len(deck_dirs),
        "knowledge_rows": len(knowledge_rows),
        "knowledge_created": len(knowledge_created),
        "knowledge_updated": len(knowledge_updated),
        "asset_rows": len(asset_rows),
        "asset_created": len(asset_created),
        "asset_updated": len(asset_updated),
        "media_asset_rows": len(media_rows),
        "media_linked_to_existing_by_sha": len(linked_existing_media),
        "deck_dependency_maps": len(deps_by_deck),
        "deck_dependency_links": sum(len(deps) for deps in deps_by_deck.values()),
        "base_token": base_token,
        "knowledge_table": knowledge_table,
        "assets_table": assets_table,
        "verified_at": verified_at,
    }
    report = {
        "summary": summary,
        "knowledge_created": knowledge_created,
        "knowledge_updated": knowledge_updated,
        "asset_created": asset_created,
        "asset_updated": asset_updated,
        "linked_existing_media": linked_existing_media,
        "deck_dependencies_sample": list(deps_by_deck.items())[:3],
        "sample_knowledge": knowledge_rows[:3],
        "sample_assets": asset_rows[:3],
    }
    report_path = args.report if args.report.is_absolute() else REPO / args.report
    write_json(report_path, report)
    print(json.dumps({"summary": summary, "report_path": repo_rel(report_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
