#!/usr/bin/env python3
"""
deck-renderer  ·  inline-assets

Reads a linked HTML deck, inlines all external CSS, JS, and image assets
as base64 data URIs or embedded content, producing a single self-contained
HTML file that works offline anywhere.

Usage:
    python3 inline-assets.py <input.html> --out <output.html>

Exit codes:
    0  ok
    1  bad arguments / missing input
    2  inlining failed
"""

from __future__ import annotations

import base64
import re
import sys
from pathlib import Path
from urllib.parse import unquote

MIME_MAP = {
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.gif': 'image/gif',
    '.svg': 'image/svg+xml',
    '.webp': 'image/webp',
    '.ico': 'image/x-icon',
}


def find_input_dir(html_path: Path) -> Path:
    return html_path.parent


def is_external_ref(ref: str) -> bool:
    ref = ref.strip()
    return (
        not ref
        or ref.startswith(("#", "data:", "blob:", "http://", "https://", "//"))
        or ref.lower().startswith("javascript:")
    )


def strip_ref(ref: str) -> str:
    return unquote(ref.strip().split("#", 1)[0].split("?", 1)[0])


def resolve_asset(base_path: Path, ref: str) -> Path | None:
    if is_external_ref(ref):
        return None
    raw = strip_ref(ref)
    if not raw:
        return None
    candidate = (base_path.parent / raw).resolve()
    if candidate.is_file():
        return candidate
    return None


def data_uri(asset: Path) -> str | None:
    suffix = asset.suffix.lower()
    mime = MIME_MAP.get(suffix)
    if mime is None:
        return None
    data = base64.b64encode(asset.read_bytes()).decode('ascii')
    return f'data:{mime};base64,{data}'


ATTR_RE = re.compile(r'([:\w-]+)\s*=\s*(["\'])(.*?)\2', re.S)


def attr_value(tag: str, name: str) -> str | None:
    for attr, _quote, value in ATTR_RE.findall(tag):
        if attr.lower() == name.lower():
            return value
    return None


def inline_css_urls(css: str, css_path: Path) -> tuple[str, int]:
    count = 0
    url_re = re.compile(r'url\(\s*(["\']?)([^)"\']+)\1\s*\)')

    def replace_url(m):
        nonlocal count
        ref = m.group(2)
        asset = resolve_asset(css_path, ref)
        if asset is None:
            return m.group(0)
        uri = data_uri(asset)
        if uri is None:
            return m.group(0)
        count += 1
        return f'url("{uri}")'

    return url_re.sub(replace_url, css), count


def inline_css_links(html: str, html_path: Path) -> tuple[str, int, int]:
    count = 0
    image_count = 0

    def replace_link(m):
        nonlocal count, image_count
        tag = m.group(0)
        rel = (attr_value(tag, "rel") or "").lower()
        href = attr_value(tag, "href")
        if "stylesheet" not in rel or not href:
            return tag
        asset = resolve_asset(html_path, href)
        if asset is None:
            return tag
        css = asset.read_text(encoding='utf-8')
        css, n_images = inline_css_urls(css, asset)
        count += 1
        image_count += n_images
        return f'<style>\n{css}\n</style>'

    out = re.sub(r'<link\b[^>]*?>', replace_link, html, flags=re.S | re.I)
    return out, count, image_count


def inline_js_scripts(html: str, html_path: Path) -> tuple[str, int]:
    count = 0

    def replace_script(m):
        nonlocal count
        tag = m.group(1)
        src = attr_value(tag, "src")
        if not src:
            return m.group(0)
        asset = resolve_asset(html_path, src)
        if asset is None:
            return m.group(0)
        js = asset.read_text(encoding='utf-8')
        count += 1
        return f'<script>\n{js}\n</script>'

    out = re.sub(
        r'(<script\b[^>]*src=["\'][^"\']+["\'][^>]*>)\s*</script>',
        replace_script, html, flags=re.S,
    )
    return out, count


def inline_css_images(html: str, html_path: Path) -> tuple[str, int]:
    count = 0
    style_re = re.compile(r'<style[^>]*>(.*?)</style>', re.S)

    def replace_in_style(m):
        nonlocal count
        css = m.group(1)
        new_css, n_images = inline_css_urls(css, html_path)
        count += n_images
        return f'<style>{new_css}</style>'

    out = style_re.sub(replace_in_style, html)
    return out, count


def inline_img_tags(html: str, html_path: Path) -> tuple[str, int]:
    count = 0

    def replace_img(m):
        nonlocal count
        src = m.group(1)
        asset = resolve_asset(html_path, src)
        if asset is None:
            return m.group(0)
        uri = data_uri(asset)
        if uri is None:
            return m.group(0)
        count += 1
        return m.group(0).replace(src, uri)

    out = re.sub(
        r'<img\s+[^>]*src=["\']([^"\']+)["\']',
        replace_img, html,
    )
    return out, count


def inline_html_style_urls(html: str, html_path: Path) -> tuple[str, int]:
    """Inline url(...) references that live directly in HTML style attrs.

    DeckJSON enrichers such as logo-wall intentionally emit per-item
    background-image styles. Those are not inside a <style> tag and are not
    <img> tags, so without this pass the "single-file" deck still depends on
    external logo/image assets.
    """
    count = 0
    url_re = re.compile(r'url\(\s*(["\']?)([^)"\']+)\1\s*\)')

    def replace_url(m):
        nonlocal count
        ref = m.group(2)
        asset = resolve_asset(html_path, ref)
        if asset is None:
            return m.group(0)
        uri = data_uri(asset)
        if uri is None:
            return m.group(0)
        count += 1
        return f'url("{uri}")'

    return url_re.sub(replace_url, html), count


def main() -> int:
    args = sys.argv[1:]
    html_in = None
    html_out = None

    i = 0
    while i < len(args):
        if args[i] == '--out' and i + 1 < len(args):
            html_out = args[i + 1]
            i += 2
        elif args[i] in ('-h', '--help'):
            print(__doc__)
            return 0
        elif html_in is None:
            html_in = args[i]
            i += 1
        else:
            i += 1

    if not html_in:
        print(__doc__)
        return 1

    src = Path(html_in).resolve()
    if not src.is_file():
        print(f'ERROR: input not found: {src}', file=sys.stderr)
        return 1

    if not html_out:
        stem = src.stem
        html_out = str(src.with_name(f'{stem}-inline.html'))

    dst = Path(html_out).resolve()
    html = src.read_text(encoding='utf-8')

    html, n_css, n_link_css_img = inline_css_links(html, src)
    html, n_js = inline_js_scripts(html, src)
    html, n_css_img = inline_css_images(html, src)
    html, n_img = inline_img_tags(html, src)
    html, n_style_img = inline_html_style_urls(html, src)

    if '<meta name="fs-deck-mode"' not in html:
        html = html.replace(
            '</head>',
            '<meta name="fs-deck-mode" content="inline">\n</head>',
            1,
        )

    dst.write_text(html, encoding='utf-8')
    size_kb = dst.stat().st_size / 1024
    print(f'inline-assets  ·  {src.name} -> {dst.name}')
    print(f'  CSS files inlined  : {n_css}')
    print(f'  JS files inlined   : {n_js}')
    print(f'  CSS images inlined : {n_css_img + n_link_css_img}')
    print(f'  <img> inlined      : {n_img}')
    print(f'  style url() inlined: {n_style_img}')
    print(f'  output size        : {size_kb:.0f} KB')
    return 0


if __name__ == '__main__':
    sys.exit(main())
