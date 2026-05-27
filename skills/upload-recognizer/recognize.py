#!/usr/bin/env python3
"""Create a Cyrus source dossier from uploaded materials.

The recognizer is intentionally conservative: it inventories files, extracts
plain text and provenance where the standard library can do so safely, and
hands structured knowledge/material/slide layers to planner, renderer, and
ingestor. It does not decide the final deck outline and does not write Base.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import zipfile
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "server"))

import slide_library  # noqa: E402


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
VIDEO_EXTS = {".mp4", ".mov", ".webm", ".m4v"}
DOC_EXTS = {".pdf", ".ppt", ".pptx", ".html", ".htm", ".md", ".txt", ".json"}


def now_slug() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def repo_rel(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO).as_posix()
    except ValueError:
        return str(resolved)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize_list(values: list[str] | None) -> list[str]:
    out: list[str] = []
    for value in values or []:
        for part in str(value).replace("，", ",").replace("、", ",").split(","):
            part = part.strip()
            if part:
                out.append(part)
    return list(dict.fromkeys(out))


def pdf_page_count(path: Path) -> int:
    try:
        raw = path.read_bytes()
    except OSError:
        return 0
    count = len(re.findall(rb"/Type\s*/Page\b", raw))
    return max(1, count)


def xml_texts(raw: bytes) -> list[str]:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return []
    texts: list[str] = []
    for el in root.iter():
        if el.tag.endswith("}t") or el.tag == "t":
            if el.text and el.text.strip():
                texts.append(el.text.strip())
    return texts


def pptx_slides(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    slides: list[dict[str, Any]] = []
    media: list[str] = []
    with zipfile.ZipFile(path) as zf:
        slide_names = sorted(
            [name for name in zf.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", name)],
            key=lambda item: int(re.search(r"slide(\d+)\.xml$", item).group(1)),
        )
        media = sorted(name for name in zf.namelist() if name.startswith("ppt/media/"))
        for idx, name in enumerate(slide_names, 1):
            texts = xml_texts(zf.read(name))
            title = next((text for text in texts if text), f"Slide {idx}")
            slides.append({
                "page": idx,
                "title": title[:120],
                "text": "\n".join(texts),
                "text_items": texts,
                "source_node": name,
            })
    return slides, media


class SlideHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.stack: list[dict[str, Any]] = []
        self.slides: list[dict[str, Any]] = []
        self.images: list[str] = []
        self.scripts: list[str] = []
        self.stylesheets: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {k: v or "" for k, v in attrs}
        if tag == "img" and attr.get("src"):
            self.images.append(attr["src"])
        if tag == "script" and attr.get("src"):
            self.scripts.append(attr["src"])
        if tag == "link" and attr.get("rel", "").lower() == "stylesheet" and attr.get("href"):
            self.stylesheets.append(attr["href"])
        classes = set(attr.get("class", "").split())
        is_slide = tag in {"section", "div", "article"} and ("slide" in classes or attr.get("data-slide-key"))
        if is_slide:
            self.stack.append({
                "tag": tag,
                "depth": 1,
                "key": attr.get("data-slide-key", ""),
                "layout": attr.get("data-layout", ""),
                "screen_label": attr.get("data-screen-label", ""),
                "texts": [],
            })
        elif self.stack:
            self.stack[-1]["depth"] += 1

    def handle_endtag(self, tag: str) -> None:
        if not self.stack:
            return
        self.stack[-1]["depth"] -= 1
        if self.stack[-1]["depth"] <= 0:
            slide = self.stack.pop()
            texts = [text for text in slide.pop("texts") if text]
            slide["title"] = texts[0][:120] if texts else slide.get("key") or "slide"
            slide["text"] = "\n".join(texts)
            slide["text_items"] = texts
            slide["page"] = len(self.slides) + 1
            self.slides.append(slide)

    def handle_data(self, data: str) -> None:
        if not self.stack:
            return
        text = html.unescape(re.sub(r"\s+", " ", data)).strip()
        if text:
            self.stack[-1]["texts"].append(text)


def inspect_html(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    parser = SlideHTMLParser()
    parser.feed(path.read_text(encoding="utf-8", errors="ignore"))
    return parser.slides, {
        "images": sorted(set(parser.images)),
        "scripts": sorted(set(parser.scripts)),
        "stylesheets": sorted(set(parser.stylesheets)),
    }


def inspect_text(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    title = next((line.lstrip("#").strip() for line in text.splitlines() if line.strip()), path.stem)
    return [{"page": 1, "title": title[:120], "text": text[:5000], "text_items": [text[:5000]]}]


TEXT_SKIP_KEYS = {
    "src",
    "image",
    "video",
    "poster",
    "thumbnail",
    "page_image",
    "href",
    "fit",
    "position",
    "type",
    "tone",
    "icon",
    "decor",
    "layout",
    "variant",
}


def collect_text_values(value: Any, key: str = "") -> list[str]:
    texts: list[str] = []
    if key in TEXT_SKIP_KEYS:
        return texts
    if isinstance(value, str):
        text = re.sub(r"\s+", " ", value).strip()
        if key == "accent" and text.lower() in {"blue", "teal", "orange", "green", "red", "purple", "gray", "dark"}:
            return texts
        if text:
            texts.append(text)
    elif isinstance(value, list):
        for item in value:
            texts.extend(collect_text_values(item, key))
    elif isinstance(value, dict):
        for item_key, item in value.items():
            texts.extend(collect_text_values(item, str(item_key)))
    return texts


def collect_media_refs(value: Any) -> list[str]:
    refs: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"src", "image", "video", "poster", "thumbnail", "page_image", "href"} and isinstance(item, str):
                if Path(item).suffix.lower() in IMAGE_EXTS | VIDEO_EXTS | {".html", ".htm"}:
                    refs.append(item)
            refs.extend(collect_media_refs(item))
    elif isinstance(value, list):
        for item in value:
            refs.extend(collect_media_refs(item))
    return refs


def inspect_json(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return inspect_text(path), []
    if not isinstance(data, dict) or not isinstance(data.get("slides"), list):
        return inspect_text(path), []
    slides: list[dict[str, Any]] = []
    media: list[str] = []
    for idx, slide in enumerate(data.get("slides") or [], 1):
        if not isinstance(slide, dict):
            continue
        payload = slide.get("data") if isinstance(slide.get("data"), dict) else slide
        texts = list(dict.fromkeys(collect_text_values(payload)))[:80]
        media.extend(collect_media_refs(payload))
        title = (
            slide.get("screen_label")
            or (payload.get("title") if isinstance(payload, dict) else "")
            or slide.get("key")
            or f"Slide {idx}"
        )
        slides.append({
            "page": idx,
            "key": str(slide.get("key") or f"{path.stem}-p{idx:03d}"),
            "title": str(title)[:120],
            "layout": str(slide.get("layout") or ""),
            "variant": str(slide.get("variant") or ""),
            "text": "\n".join(texts),
            "text_items": texts,
        })
    return slides, sorted(set(media))


def inventory_path(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    base: dict[str, Any] = {
        "path": repo_rel(path),
        "name": path.name,
        "type": "directory" if path.is_dir() else suffix.lstrip(".") or "file",
        "exists": path.exists(),
    }
    if not path.exists():
        return {**base, "error": "not found"}
    if path.is_file():
        base.update({"size_bytes": path.stat().st_size, "sha256": sha256(path)})
    if path.is_dir():
        children = sorted(p for p in path.rglob("*") if p.is_file())
        base["file_count"] = len(children)
        base["children"] = [repo_rel(p) for p in children[:200]]
        base["media"] = [repo_rel(p) for p in children if p.suffix.lower() in IMAGE_EXTS | VIDEO_EXTS][:200]
        return base
    if suffix == ".pptx":
        slides, media = pptx_slides(path)
        return {**base, "slide_count": len(slides), "slides": slides, "media": media}
    if suffix == ".ppt":
        return {**base, "slide_count": 1, "slides": [{"page": 1, "title": path.stem, "text": "", "text_items": []}]}
    if suffix == ".pdf":
        return {**base, "page_count": pdf_page_count(path), "slides": []}
    if suffix in {".html", ".htm"}:
        slides, assets = inspect_html(path)
        return {**base, "slide_count": len(slides), "slides": slides, "html_assets": assets}
    if suffix == ".json":
        slides, media = inspect_json(path)
        return {**base, "slide_count": len(slides), "slides": slides, "media": media}
    if suffix in {".md", ".txt"}:
        return {**base, "slides": inspect_text(path)}
    if suffix in IMAGE_EXTS:
        return {**base, "material_kind": "image"}
    if suffix in VIDEO_EXTS:
        return {**base, "material_kind": "video"}
    return base


def inventory_source(source: str) -> dict[str, Any]:
    if re.match(r"https?://", source):
        return {"path": source, "name": source.rsplit("/", 1)[-1], "type": "url", "exists": True}
    return inventory_path(Path(source))


def build_layers(inventory: list[dict[str, Any]], brief: str) -> dict[str, Any]:
    knowledge_items: list[dict[str, Any]] = []
    material_items: list[dict[str, Any]] = []
    slide_items: list[dict[str, Any]] = []
    for src in inventory:
        source_path = src.get("path", "")
        for idx, slide in enumerate(src.get("slides") or [], 1):
            text = str(slide.get("text") or "")
            slide_key = str(slide.get("key") or f"{Path(str(source_path)).stem or 'source'}-p{idx:03d}")
            if text:
                knowledge_items.append({
                    "id": f"know-{slide_key}",
                    "title": slide.get("title") or slide_key,
                    "content": text[:2000],
                    "provenance": {"source": source_path, "page": slide.get("page", idx), "slide_key": slide_key},
                    "confidence": "extracted-text",
                })
            slide_items.append({
                "slide_key": slide_key,
                "title": slide.get("title") or slide_key,
                "source": source_path,
                "page": slide.get("page", idx),
                "layout_hint": slide.get("layout", ""),
                "text_summary": text[:500],
            })
        for item in src.get("media") or []:
            material_items.append({
                "id": f"media-{hashlib.sha1(str(item).encode()).hexdigest()[:10]}",
                "type": Path(str(item)).suffix.lower().lstrip(".") or "media",
                "path": item,
                "provenance": {"source": source_path},
            })
        if src.get("material_kind"):
            material_items.append({
                "id": f"asset-{hashlib.sha1(str(source_path).encode()).hexdigest()[:10]}",
                "type": src.get("material_kind"),
                "path": source_path,
                "provenance": {"source": source_path},
            })
    needs_confirmation = []
    if not any(item.get("content") for item in knowledge_items) and brief:
        needs_confirmation.append("source text could not be extracted; planner should rely on brief and ask for proof.")
    return {
        "knowledge_layer": knowledge_items,
        "material_layer": material_items,
        "slide_layer": slide_items,
        "confidence": {"needs_confirmation": needs_confirmation},
    }


def render_markdown(dossier: dict[str, Any]) -> str:
    lines = [
        "# Source Dossier",
        "",
        f"- brief: {dossier.get('brief') or '(empty)'}",
        f"- sources: {len(dossier.get('source_inventory') or [])}",
        f"- knowledge_items: {len(dossier.get('knowledge_layer') or [])}",
        f"- material_items: {len(dossier.get('material_layer') or [])}",
        f"- slide_items: {len(dossier.get('slide_layer') or [])}",
        "",
        "## Sources",
    ]
    for src in dossier.get("source_inventory") or []:
        count = src.get("slide_count") or src.get("page_count") or src.get("file_count") or ""
        lines.append(f"- `{src.get('path')}` · {src.get('type')} {count}")
    if dossier.get("confidence", {}).get("needs_confirmation"):
        lines.extend(["", "## Needs Confirmation"])
        lines.extend(f"- {item}" for item in dossier["confidence"]["needs_confirmation"])
    if dossier.get("ppt_library_uploads"):
        lines.extend(["", "## PPT Library Uploads"])
        for item in dossier["ppt_library_uploads"]:
            lines.append(f"- `{item.get('source')}` · registered={len(item.get('registered') or [])}")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("sources", nargs="+", help="source files, folders, or URLs")
    ap.add_argument("--brief", default="")
    ap.add_argument("--output-dir", type=Path)
    ap.add_argument("--task-id", default="")
    ap.add_argument("--register-ppt-library", action="store_true")
    ap.add_argument("--page", action="append", type=int, default=[])
    ap.add_argument("--title", default="")
    ap.add_argument("--industry", action="append", default=[])
    ap.add_argument("--product", action="append", default=[])
    ap.add_argument("--tag", action="append", default=[])
    args = ap.parse_args(argv)

    task_id = args.task_id or f"recognizer-{now_slug()}"
    out_dir = args.output_dir or (REPO / "runs" / task_id / "output")
    if not out_dir.is_absolute():
        out_dir = REPO / out_dir

    inventory = [inventory_source(source) for source in args.sources]
    layers = build_layers(inventory, args.brief)
    ppt_uploads = []
    if args.register_ppt_library:
        for source in args.sources:
            path = Path(source)
            if path.suffix.lower() not in {".ppt", ".pptx"} or not path.exists():
                continue
            ppt_uploads.append(
                slide_library.register_ppt_upload(
                    path,
                    {
                        "title": args.title or path.stem,
                        "industry": normalize_list(args.industry) or ["待标注"],
                        "product": normalize_list(args.product) or ["待标注"],
                        "tags": normalize_list(args.tag) or ["ppt-upload", "needs-review"],
                    },
                    pages=args.page,
                )
            )

    dossier = {
        "version": "1.0",
        "task_id": task_id,
        "brief": args.brief,
        "source_inventory": inventory,
        **layers,
        "ppt_library_uploads": ppt_uploads,
        "handoff": {
            "deck_planner": "Use knowledge_layer as sourced facts and open questions.",
            "deck_renderer": "Use material_layer and slide_layer as visual/source constraints.",
            "deck_ingestor": "Ingest only after deck-auditor passes or user marks knowledge-only candidates.",
        },
    }
    write_json(out_dir / "source-dossier.json", dossier)
    (out_dir / "SOURCE_DOSSIER.md").write_text(render_markdown(dossier), encoding="utf-8")
    print(json.dumps({"dossier": str(out_dir / "source-dossier.json"), "report": str(out_dir / "SOURCE_DOSSIER.md"), **dossier}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
