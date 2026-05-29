#!/usr/bin/env python3
"""Materialize Feishu/Lark file URLs inside DeckJSON before rendering.

Feishu file links such as https://feishu.cn/file/<token> require an
authenticated browser/session and are not portable in delivered HTML or zip
packages. This utility downloads preview images through lark-cli, rewrites the
DeckJSON to local assets, and writes a small report.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


FEISHU_FILE_URL_RE = re.compile(r"https?://[^\s\"'<>]+/file/[A-Za-z0-9_-]+[^\s\"'<>]*")
LARK_HOST_SUFFIXES = ("feishu.cn", "larkoffice.com", "larksuite.com")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def is_lark_host(host: str) -> bool:
    host = host.lower().strip()
    return any(host == suffix or host.endswith("." + suffix) for suffix in LARK_HOST_SUFFIXES)


def token_from_feishu_file_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not is_lark_host(parsed.netloc):
        return ""
    parts = [part for part in parsed.path.split("/") if part]
    try:
        idx = parts.index("file")
    except ValueError:
        return ""
    if idx + 1 >= len(parts):
        return ""
    token = parts[idx + 1].strip()
    return token if re.fullmatch(r"[A-Za-z0-9_-]+", token) else ""


def find_feishu_file_urls(value: Any) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    def add(url: str) -> None:
        if token_from_feishu_file_url(url) and url not in seen:
            seen.add(url)
            found.append(url)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)
        elif isinstance(node, str):
            for match in FEISHU_FILE_URL_RE.finditer(node):
                add(match.group(0))

    walk(value)
    return found


def source_hints(source_dossier: Path | None) -> dict[str, str]:
    if not source_dossier or not source_dossier.exists():
        return {}
    try:
        payload = read_json(source_dossier)
    except Exception:
        return {}
    hints: dict[str, str] = {}

    def nearby_label(node: dict[str, Any]) -> str:
        for key in ["id", "title", "name", "label", "alt", "description", "summary"]:
            value = node.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def walk(node: Any, label: str = "") -> None:
        if isinstance(node, dict):
            label = nearby_label(node) or label
            for child in node.values():
                walk(child, label)
        elif isinstance(node, list):
            for child in node:
                walk(child, label)
        elif isinstance(node, str):
            for url in find_feishu_file_urls(node):
                token = token_from_feishu_file_url(url)
                if token and label and token not in hints:
                    hints[token] = label

    walk(payload)
    return hints


def ascii_slug(value: str, fallback: str) -> str:
    raw = value.lower()
    raw = re.sub(r"[^a-z0-9]+", "-", raw)
    raw = re.sub(r"-+", "-", raw).strip("-")
    return raw[:48] or fallback


def unique_asset_path(asset_dir: Path, token: str, hint: str = "") -> Path:
    hint_slug = ascii_slug(hint, "") if hint else ""
    stem = f"{hint_slug}-{token[:12]}" if hint_slug else f"feishu-file-{token[:12]}"
    candidate = asset_dir / f"{stem}.png"
    if not candidate.exists():
        return candidate
    suffix = 2
    while True:
        candidate = asset_dir / f"{stem}-{suffix}.png"
        if not candidate.exists():
            return candidate
        suffix += 1


def run_lark_cli(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)


def materialize_token(token: str, destination: Path, identity: str, dry_run: bool = False) -> dict[str, Any]:
    if dry_run:
        return {"ok": True, "token": token, "path": str(destination), "method": "dry-run"}

    destination.parent.mkdir(parents=True, exist_ok=True)
    output_cwd = destination.parent
    output_name = destination.name
    preview_cmd = [
        "lark-cli",
        "docs",
        "+media-preview",
        "--token",
        token,
        "--output",
        output_name,
        "--overwrite",
    ]
    if identity:
        preview_cmd.extend(["--as", identity])

    try:
        proc = run_lark_cli(preview_cmd, cwd=output_cwd)
    except FileNotFoundError as exc:
        return {
            "ok": False,
            "token": token,
            "path": str(destination),
            "method": "media-preview",
            "error": str(exc),
            "command": " ".join(shlex.quote(part) for part in preview_cmd),
        }

    if proc.returncode == 0 and destination.exists() and destination.stat().st_size > 0:
        return {
            "ok": True,
            "token": token,
            "path": str(destination),
            "method": "media-preview",
            "stdout": proc.stdout.strip()[-1200:],
        }

    download_cmd = [
        "lark-cli",
        "docs",
        "+media-download",
        "--token",
        token,
        "--output",
        output_name,
        "--overwrite",
    ]
    if identity:
        download_cmd.extend(["--as", identity])
    try:
        fallback = run_lark_cli(download_cmd, cwd=output_cwd)
    except FileNotFoundError as exc:
        fallback = subprocess.CompletedProcess(download_cmd, 127, "", str(exc))

    if fallback.returncode == 0 and destination.exists() and destination.stat().st_size > 0:
        return {
            "ok": True,
            "token": token,
            "path": str(destination),
            "method": "media-download",
            "stdout": fallback.stdout.strip()[-1200:],
        }

    return {
        "ok": False,
        "token": token,
        "path": str(destination),
        "method": "media-preview/media-download",
        "preview_stderr": proc.stderr.strip()[-1200:],
        "download_stderr": fallback.stderr.strip()[-1200:],
    }


def rewrite_feishu_file_urls(value: Any, token_to_path: dict[str, str]) -> Any:
    def replace_text(text: str) -> str:
        def replace_match(match: re.Match[str]) -> str:
            url = match.group(0)
            token = token_from_feishu_file_url(url)
            return token_to_path.get(token, url)

        return FEISHU_FILE_URL_RE.sub(replace_match, text)

    if isinstance(value, dict):
        return {key: rewrite_feishu_file_urls(child, token_to_path) for key, child in value.items()}
    if isinstance(value, list):
        return [rewrite_feishu_file_urls(child, token_to_path) for child in value]
    if isinstance(value, str):
        return replace_text(value)
    return value


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Asset Materialization",
        "",
        f"- scanned_urls: {report['summary']['scanned_urls']}",
        f"- materialized: {report['summary']['materialized']}",
        f"- unresolved: {report['summary']['unresolved']}",
        "",
    ]
    if report["items"]:
        lines.extend(["## Items", ""])
        for item in report["items"]:
            status = "ok" if item.get("ok") else "unresolved"
            token = str(item.get("token") or "")
            token_label = token[:8] + "..." if len(token) > 8 else token
            lines.append(f"- {status}: `{token_label}` -> `{item.get('local_path') or item.get('path') or ''}`")
        lines.append("")
    if report.get("unresolved_urls"):
        lines.extend(["## Unresolved URLs", ""])
        for url in report["unresolved_urls"]:
            lines.append(f"- {url}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("deck_json", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--source-dossier", type=Path)
    parser.add_argument("--asset-dir", type=Path, help="Defaults to output_dir/assets/source-media")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--as", dest="identity", default=os.environ.get("LARK_CLI_AS", "user"), help="lark-cli identity: user or bot")
    parser.add_argument("--fail-on-unresolved", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    deck_path = args.deck_json.resolve()
    output_dir = args.output_dir.resolve()
    asset_dir = (args.asset_dir or output_dir / "assets" / "source-media").resolve()
    report_path = args.report or output_dir / "asset-materialization.json"
    markdown_path = args.markdown or output_dir / "ASSET_MATERIALIZATION.md"

    if not deck_path.exists():
        print(f"deck not found: {deck_path}", file=sys.stderr)
        return 2

    deck = read_json(deck_path)
    urls = find_feishu_file_urls(deck)
    hints = source_hints(args.source_dossier)
    token_urls: dict[str, list[str]] = {}
    for url in urls:
        token_urls.setdefault(token_from_feishu_file_url(url), []).append(url)

    items: list[dict[str, Any]] = []
    token_to_path: dict[str, str] = {}
    for token in sorted(token_urls):
        destination = unique_asset_path(asset_dir, token, hints.get(token, ""))
        result = materialize_token(token, destination, args.identity, dry_run=args.dry_run)
        local_path = ""
        if result.get("ok"):
            saved = Path(str(result.get("path") or destination)).resolve()
            local_path = os.path.relpath(saved, start=deck_path.parent).replace(os.sep, "/")
            token_to_path[token] = local_path
        item = {
            **result,
            "urls": token_urls[token],
            "local_path": local_path,
        }
        items.append(item)

    rewritten = rewrite_feishu_file_urls(deck, token_to_path)
    if rewritten != deck and not args.dry_run:
        write_json(deck_path, rewritten)

    unresolved_urls = []
    if token_to_path:
        unresolved_urls = find_feishu_file_urls(rewritten)
    else:
        unresolved_urls = urls

    report = {
        "ok": not unresolved_urls,
        "deck_json": str(deck_path),
        "asset_dir": str(asset_dir),
        "summary": {
            "scanned_urls": len(urls),
            "tokens": len(token_urls),
            "materialized": sum(1 for item in items if item.get("ok")),
            "unresolved": len(unresolved_urls),
        },
        "items": items,
        "unresolved_urls": unresolved_urls,
    }
    write_json(report_path, report)
    if urls or items or unresolved_urls:
        markdown_path.write_text(render_markdown(report), encoding="utf-8")
    elif markdown_path.exists():
        markdown_path.unlink()

    if unresolved_urls and args.fail_on_unresolved:
        print(f"unresolved Feishu/Lark file URLs: {len(unresolved_urls)}", file=sys.stderr)
        return 1
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
