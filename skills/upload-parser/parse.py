#!/usr/bin/env python3
"""Create a Cyrus source dossier from uploaded materials.

The parser is intentionally conservative: it inventories files, extracts
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
import shutil
import subprocess
import sys
import zipfile
import zlib
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
VOID_HTML_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


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


def is_url(value: str) -> bool:
    return bool(re.match(r"https?://", value))


def is_lark_doc_url(value: str) -> bool:
    return bool(re.search(r"(larkoffice\.com|feishu\.cn)/(docx|docs|wiki)/", value))


def safe_source_stem(source: str) -> str:
    stem = Path(source).stem if not is_url(source) else re.sub(r"[^a-zA-Z0-9]+", "-", source).strip("-")
    stem = re.sub(r"[^a-zA-Z0-9._-]+", "-", stem).strip("-._")
    digest = hashlib.sha1(source.encode("utf-8")).hexdigest()[:10]
    return f"{stem[:48] or 'source'}-{digest}"


def fetch_lark_doc(source: str, target: Path) -> tuple[Path | None, list[str]]:
    if not shutil.which("lark-cli"):
        return None, ["lark-cli not found; Lark document URL was preserved but not fetched."]
    cmd = [
        "lark-cli",
        "docs",
        "+fetch",
        "--api-version",
        "v2",
        "--doc",
        source,
        "--doc-format",
        "markdown",
        "--format",
        "json",
    ]
    try:
        proc = subprocess.run(cmd, cwd=REPO, text=True, capture_output=True, timeout=60)
    except subprocess.TimeoutExpired:
        return None, ["lark-cli docs +fetch timed out; Lark document URL was preserved but not parsed."]
    if proc.returncode != 0:
        reason = (proc.stderr or proc.stdout).strip().splitlines()[:2]
        return None, ["lark-cli docs +fetch failed: " + " ".join(reason)]
    content = ""
    try:
        payload = json.loads(proc.stdout)
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        document = data.get("document") if isinstance(data.get("document"), dict) else {}
        content = str(document.get("content") or payload.get("content") or "")
    except json.JSONDecodeError:
        content = proc.stdout
    if not content.strip():
        return None, ["lark-cli docs +fetch returned no readable content."]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target, []


def prepare_runtime_source(source: str, library_dir: Path) -> dict[str, Any]:
    record: dict[str, Any] = {
        "original_source": source,
        "runtime_source": source,
        "preserved": False,
        "warnings": [],
    }
    if is_lark_doc_url(source):
        fetched = library_dir / "fetched" / f"{safe_source_stem(source)}.md"
        target, warnings = fetch_lark_doc(source, fetched)
        record["warnings"].extend(warnings)
        if target:
            record.update({
                "runtime_source": str(target),
                "runtime_library_path": repo_rel(target),
                "preserved": True,
                "preservation_kind": "lark-doc-fetch",
            })
        return record
    if is_url(source):
        record["preservation_kind"] = "url-reference"
        return record

    path = Path(source)
    if not path.exists():
        return record
    raw_dir = library_dir / "raw"
    target = raw_dir / f"{safe_source_stem(source)}{path.suffix if path.is_file() else ''}"
    if path.is_dir():
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(path, target)
        kind = "directory-copy"
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        kind = "file-copy"
    record.update({
        "runtime_source": str(target),
        "runtime_library_path": repo_rel(target),
        "preserved": True,
        "preservation_kind": kind,
    })
    return record


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


def pdf_text_light(path: Path, limit: int = 12000) -> str:
    """Best-effort PDF text extraction using only the standard library.

    This is intentionally conservative. It handles common unencrypted PDFs
    with literal text strings in plain or Flate-compressed streams, and leaves
    provenance/confirmation gaps when text cannot be safely recovered.
    """
    try:
        raw = path.read_bytes()
    except OSError:
        return ""
    chunks: list[bytes] = []
    chunks.extend(match.group(1) for match in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", raw, re.S))
    expanded: list[bytes] = []
    for chunk in chunks[:80]:
        expanded.append(chunk)
        try:
            expanded.append(zlib.decompress(chunk.strip()))
        except Exception:
            pass

    texts: list[str] = []
    string_re = re.compile(rb"\((?:\\.|[^\\()]){2,}\)")
    for chunk in expanded:
        for match in string_re.finditer(chunk):
            value = match.group(0)[1:-1]
            value = re.sub(rb"\\([nrtbf()\\])", lambda m: {
                b"n": b"\n",
                b"r": b"\n",
                b"t": b"\t",
                b"b": b"",
                b"f": b"",
                b"(": b"(",
                b")": b")",
                b"\\": b"\\",
            }[m.group(1)], value)
            decoded = value.decode("utf-8", errors="ignore") or value.decode("latin1", errors="ignore")
            decoded = re.sub(r"\s+", " ", decoded).strip()
            if len(decoded) >= 2 and not re.fullmatch(r"[\W_]+", decoded):
                texts.append(decoded)
        if sum(len(item) for item in texts) >= limit:
            break
    return "\n".join(dict.fromkeys(texts))[:limit]


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
        self.current_slide: dict[str, Any] | None = None
        self.current_depth = 0
        self.skip_text_stack: list[str] = []
        self.slides: list[dict[str, Any]] = []
        self.images: list[str] = []
        self.scripts: list[str] = []
        self.stylesheets: list[str] = []

    def collect_asset(self, tag: str, attr: dict[str, str]) -> None:
        if tag == "img" and attr.get("src"):
            self.images.append(attr["src"])
        if tag == "script" and attr.get("src"):
            self.scripts.append(attr["src"])
        if tag == "link" and attr.get("rel", "").lower() == "stylesheet" and attr.get("href"):
            self.stylesheets.append(attr["href"])

    def handle_slide_start(self, tag: str, attr: dict[str, str]) -> None:
        classes = set(attr.get("class", "").split())
        is_slide = tag in {"section", "div", "article"} and ("slide" in classes or attr.get("data-slide-key"))
        if is_slide:
            if self.current_slide is not None:
                self.close_slide()
            self.current_slide = {
                "tag": tag,
                "key": attr.get("data-slide-key", ""),
                "layout": attr.get("data-layout", ""),
                "screen_label": attr.get("data-screen-label", ""),
                "texts": [],
            }
            self.current_depth = 0 if tag in VOID_HTML_TAGS else 1
        elif self.current_slide is not None and tag not in VOID_HTML_TAGS:
            self.current_depth += 1

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {k: v or "" for k, v in attrs}
        self.collect_asset(tag, attr)
        if tag in {"style", "script", "svg"}:
            self.skip_text_stack.append(tag)
        self.handle_slide_start(tag, attr)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {k: v or "" for k, v in attrs}
        self.collect_asset(tag, attr)

    def handle_endtag(self, tag: str) -> None:
        if self.skip_text_stack and tag == self.skip_text_stack[-1]:
            self.skip_text_stack.pop()
        if self.current_slide is None or tag in VOID_HTML_TAGS:
            return
        self.current_depth -= 1
        if self.current_depth <= 0:
            self.close_slide()

    def close_slide(self) -> None:
        if self.current_slide is None:
            return
        slide = self.current_slide
        texts = [text for text in slide.pop("texts") if text]
        slide["title"] = texts[0][:120] if texts else slide.get("key") or "slide"
        slide["text"] = "\n".join(texts)
        slide["text_items"] = texts
        slide["page"] = len(self.slides) + 1
        self.slides.append(slide)
        self.current_slide = None
        self.current_depth = 0

    def handle_data(self, data: str) -> None:
        if self.current_slide is None or self.skip_text_stack:
            return
        text = html.unescape(re.sub(r"\s+", " ", data)).strip()
        if text:
            self.current_slide["texts"].append(text)

    def close(self) -> None:
        super().close()
        if self.current_slide is not None:
            self.close_slide()


def inspect_html(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    parser = SlideHTMLParser()
    parser.feed(raw)
    parser.close()
    expected = len(re.findall(r"\bdata-slide-key\s*=", raw))
    warnings = []
    if expected and expected != len(parser.slides):
        warnings.append(f"HTML declares {expected} data-slide-key values but parser extracted {len(parser.slides)} slides")
    return parser.slides, {
        "images": sorted(set(parser.images)),
        "scripts": sorted(set(parser.scripts)),
        "stylesheets": sorted(set(parser.stylesheets)),
        "declared_slide_keys": expected,
        "warnings": warnings,
    }


def markdown_image_refs(text: str) -> list[str]:
    refs = []
    for match in re.finditer(r"!\[[^\]]*\]\(([^)]+)\)", text):
        ref = match.group(1).strip()
        if ref:
            refs.append(ref)
    return list(dict.fromkeys(refs))


def inspect_text(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    title = next((line.lstrip("#").strip() for line in text.splitlines() if line.strip()), path.stem)
    return [{"page": 1, "title": title[:120], "text": text[:5000], "text_items": [text[:5000]]}], markdown_image_refs(text)


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
        return {
            **base,
            "processing_status": "needs_conversion",
            "slides": [],
            "warnings": ["Legacy .ppt text extraction is not available in the stdlib parser; convert to .pptx or PDF."],
        }
    if suffix == ".pdf":
        pages = pdf_page_count(path)
        text = pdf_text_light(path)
        slides = [
            {
                "page": idx,
                "title": f"{path.stem} · Page {idx}",
                "text": text if idx == 1 else "",
                "text_items": [text] if text and idx == 1 else [],
                "source_node": f"page-{idx}",
            }
            for idx in range(1, pages + 1)
        ]
        warnings = [] if text else ["PDF page count extracted, but no selectable text was recovered; renderer should use page replica or ask for source text."]
        return {**base, "page_count": pages, "slide_count": pages, "slides": slides, "warnings": warnings}
    if suffix in {".html", ".htm"}:
        slides, assets = inspect_html(path)
        return {**base, "slide_count": len(slides), "slides": slides, "html_assets": assets}
    if suffix == ".json":
        slides, media = inspect_json(path)
        return {**base, "slide_count": len(slides), "slides": slides, "media": media}
    if suffix in {".md", ".txt"}:
        slides, media = inspect_text(path)
        return {**base, "slides": slides, "media": media}
    if suffix in IMAGE_EXTS:
        return {**base, "material_kind": "image"}
    if suffix in VIDEO_EXTS:
        return {**base, "material_kind": "video"}
    return base


def inventory_source(source: str) -> dict[str, Any]:
    if re.match(r"https?://", source):
        source_type = "larkdoc-url" if re.search(r"(larkoffice\.com|feishu\.cn)/(docx|docs|wiki|file|slides)/", source) else "url"
        return {
            "path": source,
            "name": source.rsplit("/", 1)[-1],
            "type": source_type,
            "exists": True,
            "processing_status": "metadata-only",
            "warnings": ["URL content was not fetched by the stdlib parser; provide an exported file or run the Lark document reader before planning."],
        }
    return inventory_path(Path(source))


def build_layers(inventory: list[dict[str, Any]], brief: str) -> dict[str, Any]:
    knowledge_items: list[dict[str, Any]] = []
    material_items: list[dict[str, Any]] = []
    slide_items: list[dict[str, Any]] = []
    needs_confirmation: list[str] = []
    for src in inventory:
        source_path = src.get("path", "")
        original_source = src.get("original_source") or source_path
        if not src.get("exists", True):
            needs_confirmation.append(f"source not found: {source_path}")
        for warning in src.get("warnings") or []:
            needs_confirmation.append(f"{source_path}: {warning}")
        if src.get("processing_status") in {"needs_conversion", "metadata-only"}:
            needs_confirmation.append(f"{source_path}: {src.get('processing_status')}")
        for idx, slide in enumerate(src.get("slides") or [], 1):
            text = str(slide.get("text") or "")
            slide_key = str(slide.get("key") or f"{Path(str(source_path)).stem or 'source'}-p{idx:03d}")
            if text:
                knowledge_items.append({
                    "id": f"know-{slide_key}",
                    "title": slide.get("title") or slide_key,
                    "content": text[:2000],
                    "provenance": {
                        "source": original_source,
                        "runtime_source": source_path,
                        "page": slide.get("page", idx),
                        "slide_key": slide_key,
                    },
                    "confidence": "extracted-text",
                })
            slide_items.append({
                "slide_key": slide_key,
                "title": slide.get("title") or slide_key,
                "source": original_source,
                "runtime_source": source_path,
                "page": slide.get("page", idx),
                "layout_hint": slide.get("layout", ""),
                "text_summary": text[:500],
            })
        for item in src.get("media") or []:
            material_items.append({
                "id": f"media-{hashlib.sha1(str(item).encode()).hexdigest()[:10]}",
                "type": Path(str(item)).suffix.lower().lstrip(".") or "media",
                "path": item,
                "provenance": {"source": original_source, "runtime_source": source_path},
            })
        html_assets = src.get("html_assets") if isinstance(src.get("html_assets"), dict) else {}
        for kind, asset_type in [
            ("images", "image"),
            ("scripts", "script"),
            ("stylesheets", "stylesheet"),
        ]:
            for item in html_assets.get(kind) or []:
                item_text = str(item).strip()
                if not item_text:
                    continue
                digest = hashlib.sha1(f"{source_path}:{kind}:{item_text}".encode("utf-8")).hexdigest()[:10]
                material_items.append({
                    "id": f"html-{asset_type}-{digest}",
                    "type": asset_type,
                    "path": item_text,
                    "provenance": {"source": original_source, "runtime_source": source_path},
                })
        if src.get("material_kind"):
            material_items.append({
                "id": f"asset-{hashlib.sha1(str(source_path).encode()).hexdigest()[:10]}",
                "type": src.get("material_kind"),
                "path": source_path,
                "provenance": {"source": original_source, "runtime_source": source_path},
            })
    if not any(item.get("content") for item in knowledge_items) and brief:
        needs_confirmation.append("source text could not be extracted; planner should rely on brief and ask for proof.")
    return {
        "knowledge_layer": knowledge_items,
        "material_layer": material_items,
        "slide_layer": slide_items,
        "confidence": {"needs_confirmation": list(dict.fromkeys(needs_confirmation))},
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
        original = src.get("original_source")
        suffix = f" · original=`{original}`" if original and original != src.get("path") else ""
        lines.append(f"- `{src.get('path')}` · {src.get('type')} {count}{suffix}")
    if dossier.get("confidence", {}).get("needs_confirmation"):
        lines.extend(["", "## Needs Confirmation"])
        lines.extend(f"- {item}" for item in dossier["confidence"]["needs_confirmation"])
    failed = [src for src in dossier.get("source_inventory") or [] if not src.get("exists", True)]
    if failed:
        lines.extend(["", "## Failed Sources"])
        lines.extend(f"- `{src.get('path')}` · {src.get('error') or 'unavailable'}" for src in failed)
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
    ap.add_argument("--allow-missing", action="store_true", help="write dossier but exit 0 even when local source files are missing")
    args = ap.parse_args(argv)

    task_id = args.task_id or f"parser-{now_slug()}"
    out_dir = args.output_dir or (REPO / "runs" / task_id / "output")
    if not out_dir.is_absolute():
        out_dir = REPO / out_dir

    library_dir = out_dir / "source-library"
    prepared_sources = [prepare_runtime_source(source, library_dir) for source in args.sources]
    inventory = []
    for prepared in prepared_sources:
        item = inventory_source(str(prepared["runtime_source"]))
        item["original_source"] = prepared["original_source"]
        item["runtime_source"] = prepared["runtime_source"]
        if prepared.get("runtime_library_path"):
            item["runtime_library_path"] = prepared["runtime_library_path"]
        item["preservation_status"] = "preserved" if prepared.get("preserved") else "reference-only"
        item["preservation_kind"] = prepared.get("preservation_kind", "")
        warnings = list(item.get("warnings") or [])
        warnings.extend(prepared.get("warnings") or [])
        if warnings:
            item["warnings"] = list(dict.fromkeys(warnings))
        inventory.append(item)
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
        "source_library": {
            "root": repo_rel(library_dir),
            "items": prepared_sources,
        },
        "source_inventory": inventory,
        **layers,
        "ppt_library_uploads": ppt_uploads,
        "handoff": {
            "deck_planner": {
                "target_skill": "deck-planner",
                "payload_schema": "skills/lark-deck-cyrus/schema/source-dossier.schema.json",
                "consumes": ["knowledge_layer", "confidence.needs_confirmation", "source_inventory"],
                "ready": True,
                "notes": ["Use knowledge_layer as sourced facts; keep confidence gaps as open questions."],
            },
            "deck_renderer": {
                "target_skill": "deck-renderer",
                "payload_schema": "skills/deck-planner/schema/deck-outline.schema.json",
                "consumes": ["material_layer", "slide_layer", "source_library"],
                "ready": True,
                "notes": ["Use material_layer and slide_layer only after planner has produced a confirmed outline."],
            },
            "deck_ingestor": {
                "target_skill": "deck-ingestor",
                "payload_schema": "skills/lark-deck-cyrus/schema/source-dossier.schema.json",
                "consumes": ["knowledge_layer", "material_layer", "slide_layer", "provenance"],
                "ready": False,
                "notes": ["Ingest only after deck-auditor passes or the user marks records as knowledge-only candidates."],
            },
        },
        "validation": {
            "schema": "skills/lark-deck-cyrus/schema/source-dossier.schema.json",
            "validated": False,
        },
    }
    write_json(out_dir / "source-dossier.json", dossier)
    (out_dir / "SOURCE_DOSSIER.md").write_text(render_markdown(dossier), encoding="utf-8")
    print(json.dumps({"dossier": str(out_dir / "source-dossier.json"), "report": str(out_dir / "SOURCE_DOSSIER.md"), **dossier}, ensure_ascii=False, indent=2))
    missing = [src for src in inventory if not src.get("exists", True)]
    return 0 if args.allow_missing or not missing else 2


if __name__ == "__main__":
    raise SystemExit(main())
