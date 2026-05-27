#!/usr/bin/env python3
"""
deck-renderer  ·  deck-manage

Structural management tool for feishu-deck HTML files.
Handles image, layout, accent, decor, slide order, and slide CRUD operations.

Usage:
    # Inspect
    python3 deck-manage.py deck.html --info              # full deck overview
    python3 deck-manage.py deck.html --slide 4 --info    # single slide detail

    # Image operations
    python3 deck-manage.py deck.html --replace-img input/old.jpeg input/new.jpeg
    python3 deck-manage.py deck.html --img-size slide-06.screenshot 300x500
    python3 deck-manage.py deck.html --img-position slide-06.screenshot center

    # Layout / style operations
    python3 deck-manage.py deck.html --slide 4 --layout content-2col
    python3 deck-manage.py deck.html --slide 4 --accent teal
    python3 deck-manage.py deck.html --slide 4 --decor teal-glow
    python3 deck-manage.py deck.html --slide 4 --screen-label "04 New Label"

    # Slide CRUD
    python3 deck-manage.py deck.html --add-slide 5 section --key "section-new" --accent teal
    python3 deck-manage.py deck.html --remove-slide 5
    python3 deck-manage.py deck.html --duplicate-slide 4
    python3 deck-manage.py deck.html --move-slide 5 3    # move slide 5 to position 3

    # Batch operations via YAML spec
    python3 deck-manage.py deck.html --apply edits.yaml

All modifications are applied to the linked HTML (not inline).
After editing, re-run inline-assets.py to regenerate the inline version.

Exit codes: 0 ok, 1 bad args / not found, 2 io error
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

SLIDE_FRAME_OPEN_RE = re.compile(r'<div\b[^>]*class="[^"]*\bslide-frame\b[^"]*"[^>]*>', re.S)
SLIDE_OPEN_RE = re.compile(r'<div\b[^>]*class="[^"]*\bslide\b[^"]*"[^>]*>', re.S)
DIV_TOKEN_RE = re.compile(r'<div\b[^>]*>|</div>', re.S | re.I)

ATTRS_RE = {
    'layout': re.compile(r'data-layout="([^"]+)"'),
    'accent': re.compile(r'data-accent="([^"]+)"'),
    'decor': re.compile(r'data-decor="([^"]+)"'),
    'key': re.compile(r'data-slide-key="([^"]+)"'),
    'label': re.compile(r'data-screen-label="([^"]*)"'),
}

IMG_RE = re.compile(r'<img\s+[^>]*?data-text-id="([^"]+)"[^>]*?>', re.S)
IMG_TAG_RE = re.compile(r'<img\b[^>]*>', re.S)
IMG_SRC_RE = re.compile(r'(<img\s+[^>]*?src=")([^"]+)(")', re.S)
IMG_STYLE_RE = re.compile(r'(<img\s+[^>]*?style=")([^"]*)(")', re.S)


def find_matching_div_end(html: str, open_start: int) -> int | None:
    depth = 0
    for token in DIV_TOKEN_RE.finditer(html, open_start):
        if token.group(0).lower().startswith('<div'):
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return token.end()
    return None


def find_slides(html: str) -> list[dict]:
    slides = []
    for frame_m in SLIDE_FRAME_OPEN_RE.finditer(html):
        frame_start = frame_m.start()
        frame_end = find_matching_div_end(html, frame_start)
        if frame_end is None:
            continue
        frame_full = html[frame_start:frame_end]
        slide_m = SLIDE_OPEN_RE.search(frame_full)
        if not slide_m:
            continue
        slide_open = slide_m.group(0)
        attrs_str = slide_open
        attrs = {}
        for name, pat in ATTRS_RE.items():
            found = pat.search(attrs_str)
            attrs[name] = found.group(1) if found else None

        slides.append({
            'frame_start': frame_start,
            'frame_end': frame_end,
            'frame_full': frame_full,
            'slide_open_start': frame_start + slide_m.start(),
            'slide_open_end': frame_start + slide_m.end(),
            'slide_open': slide_open,
            'inner_html': frame_full[slide_m.end():],
            **attrs,
        })
    return slides


def cmd_info(html: str, slide_num: int | None = None):
    slides = find_slides(html)
    if slide_num is not None:
        if slide_num < 1 or slide_num > len(slides):
            print(f'❌ Slide {slide_num} 不存在（共 {len(slides)} 页）', file=sys.stderr)
            return
        s = slides[slide_num - 1]
        print(f'📄 Slide {slide_num:02d} 详情:')
        print(f'  layout:      {s["layout"] or "default"}')
        print(f'  accent:      {s["accent"] or "default"}')
        print(f'  decor:       {s["decor"] or "none"}')
        print(f'  key:         {s["key"] or "N/A"}')
        print(f'  label:       {s["label"] or "N/A"}')
        imgs = IMG_RE.findall(s['inner_html'])
        if imgs:
            print(f'  images:      {imgs}')
        text_ids = re.findall(r'data-text-id="([^"]+)"', s['inner_html'])
        if text_ids:
            print(f'  text fields: {text_ids}')
        return

    print(f'📊 Deck 概览: {len(slides)} 页\n')
    print(f'{"#":>3}  {"Layout":<16} {"Accent":<8} {"Decor":<14} {"Key":<22} {"Label"}')
    print(f'{"─"*3}  {"─"*16} {"─"*8} {"─"*14} {"─"*22} {"─"*20}')
    for i, s in enumerate(slides):
        print(f'{i+1:>3}  {(s["layout"] or "default"):<16} {(s["accent"] or "default"):<8} {(s["decor"] or "none"):<14} {(s["key"] or "N/A"):<22} {s["label"] or ""}')


def _set_attr(attrs_str: str, attr: str, value: str) -> str:
    attr_re = re.compile(rf'data-{attr}="[^"]*"')
    attr_tag = f'data-{attr}="{value}"'
    if attr_re.search(attrs_str):
        return attr_re.sub(attr_tag, attrs_str)
    return attrs_str.rstrip().removesuffix('>') + ' ' + attr_tag + '>'


def _remove_attr(attrs_str: str, attr: str) -> str:
    attr_re = re.compile(rf'\s*data-{attr}="[^"]*"')
    return attr_re.sub('', attrs_str)


def replace_slide_open(html: str, slide: dict, new_open: str) -> str:
    return html[:slide['slide_open_start']] + new_open + html[slide['slide_open_end']:]


def cmd_set_layout(html: str, slide_num: int, layout: str) -> str:
    slides = find_slides(html)
    if slide_num < 1 or slide_num > len(slides):
        print(f'❌ Slide {slide_num} 不存在', file=sys.stderr)
        return html
    s = slides[slide_num - 1]
    old_layout = s['layout'] or 'default'
    new_open = _set_attr(s['slide_open'], 'layout', layout)
    new_html = replace_slide_open(html, s, new_open)
    print(f'✅ Slide {slide_num:02d}: layout {old_layout} → {layout}')
    return new_html


def cmd_set_accent(html: str, slide_num: int, accent: str) -> str:
    slides = find_slides(html)
    if slide_num < 1 or slide_num > len(slides):
        print(f'❌ Slide {slide_num} 不存在', file=sys.stderr)
        return html
    s = slides[slide_num - 1]
    old_accent = s['accent'] or 'default'
    new_open = _set_attr(s['slide_open'], 'accent', accent)
    new_html = replace_slide_open(html, s, new_open)
    print(f'✅ Slide {slide_num:02d}: accent {old_accent} → {accent}')
    return new_html


def cmd_set_decor(html: str, slide_num: int, decor: str) -> str:
    slides = find_slides(html)
    if slide_num < 1 or slide_num > len(slides):
        print(f'❌ Slide {slide_num} 不存在', file=sys.stderr)
        return html
    s = slides[slide_num - 1]
    old_decor = s['decor'] or 'none'
    if decor == 'none':
        new_open = _remove_attr(s['slide_open'], 'decor')
    else:
        new_open = _set_attr(s['slide_open'], 'decor', decor)
    new_html = replace_slide_open(html, s, new_open)
    print(f'✅ Slide {slide_num:02d}: decor {old_decor} → {decor}')
    return new_html


def cmd_set_screen_label(html: str, slide_num: int, label: str) -> str:
    slides = find_slides(html)
    if slide_num < 1 or slide_num > len(slides):
        print(f'❌ Slide {slide_num} 不存在', file=sys.stderr)
        return html
    s = slides[slide_num - 1]
    old_label = s['label'] or ''
    new_open = _set_attr(s['slide_open'], 'screen-label', label)
    new_html = replace_slide_open(html, s, new_open)
    print(f'✅ Slide {slide_num:02d}: screen-label {old_label!r} → {label!r}')
    return new_html


def cmd_replace_img(html: str, old_src: str, new_src: str) -> str:
    count = 0
    def replacer(m):
        nonlocal count
        if old_src in m.group(2):
            count += 1
            return m.group(1) + new_src + m.group(3)
        return m.group(0)
    new_html = IMG_SRC_RE.sub(replacer, html)
    if count:
        print(f'✅ 替换图片: {old_src} → {new_src}（{count} 处）')
    else:
        print(f'❌ 未找到图片: {old_src}', file=sys.stderr)
    return new_html


def set_style_property(tag: str, prop: str, value: str) -> str:
    style_m = re.search(r'style="([^"]*)"', tag)
    if style_m:
        style = style_m.group(1)
        if re.search(rf'(^|;)\s*{re.escape(prop)}\s*:', style):
            style = re.sub(rf'(^|;)\s*{re.escape(prop)}\s*:[^;]*', lambda m: f'{m.group(1)} {prop}: {value}', style)
        else:
            style = style.rstrip().rstrip(';') + f'; {prop}: {value}'
        return tag[:style_m.start(1)] + style + tag[style_m.end(1):]
    return tag.rstrip().removesuffix('>') + f' style="{prop}: {value}">'


def update_img_style(html: str, text_id: str, updates: dict[str, str]) -> tuple[str, int]:
    count = 0

    def replacer(m):
        nonlocal count
        tag = m.group(0)
        if f'data-text-id="{text_id}"' not in tag:
            return tag
        for prop, value in updates.items():
            tag = set_style_property(tag, prop, value)
        count += 1
        return tag

    return IMG_TAG_RE.sub(replacer, html), count


def cmd_img_size(html: str, text_id: str, width: int, height: int) -> str:
    new_html, count = update_img_style(html, text_id, {
        'width': f'{width}px',
        'height': f'{height}px',
    })
    if count:
        print(f'✅ 图片 {text_id} 尺寸 → {width}x{height}')
    else:
        print(f'❌ 未找到图片 text-id: {text_id}', file=sys.stderr)
    return new_html


def cmd_img_position(html: str, text_id: str, position: str) -> str:
    new_html, count = update_img_style(html, text_id, {
        'object-position': position,
    })
    if count:
        print(f'✅ 图片 {text_id} 位置 → {position}')
    else:
        print(f'❌ 未找到图片 text-id: {text_id}', file=sys.stderr)
    return new_html


def cmd_img_size_legacy(html: str, text_id: str, width: int, height: int) -> str:
    def replacer(m):
        if text_id in m.group(0):
            existing_style = m.group(2)
            new_style = re.sub(r'width:\s*\d+px', f'width:{width}px', existing_style)
            new_style = re.sub(r'height:\s*\d+px', f'height:{height}px', new_style)
            if 'width:' not in new_style:
                new_style += f'; width:{width}px'
            if 'height:' not in new_style:
                new_style += f'; height:{height}px'
            return m.group(1) + new_style + m.group(3)
        return m.group(0)
    new_html = IMG_STYLE_RE.sub(replacer, html)
    print(f'✅ 图片 {text_id} 尺寸 → {width}x{height}')
    return new_html


def cmd_remove_slide(html: str, slide_num: int) -> str:
    slides = find_slides(html)
    if slide_num < 1 or slide_num > len(slides):
        print(f'❌ Slide {slide_num} 不存在', file=sys.stderr)
        return html
    s = slides[slide_num - 1]
    label = s['label'] or f'slide {slide_num}'
    new_html = html[:s['frame_start']] + html[s['frame_end']:]
    print(f'✅ 已删除 Slide {slide_num:02d} ({label})')
    return new_html


def cmd_duplicate_slide(html: str, slide_num: int) -> str:
    slides = find_slides(html)
    if slide_num < 1 or slide_num > len(slides):
        print(f'❌ Slide {slide_num} 不存在', file=sys.stderr)
        return html
    s = slides[slide_num - 1]
    insert_pos = s['frame_end']
    new_html = html[:insert_pos] + '\n\n    ' + s['frame_full'] + html[insert_pos:]
    print(f'✅ 已复制 Slide {slide_num:02d} → 新 Slide {slide_num + 1:02d}')
    return new_html


def cmd_move_slide(html: str, from_pos: int, to_pos: int) -> str:
    slides = find_slides(html)
    if from_pos < 1 or from_pos > len(slides) or to_pos < 1 or to_pos > len(slides):
        print(f'❌ 位置无效', file=sys.stderr)
        return html
    if from_pos == to_pos:
        print(f'⏭️ 位置未变，跳过')
        return html

    frames = [s['frame_full'] for s in slides]
    moved = frames.pop(from_pos - 1)
    frames.insert(to_pos - 1, moved)
    before = html[:slides[0]['frame_start']]
    after = html[slides[-1]['frame_end']:]
    new_html = before + '\n\n    '.join(frames) + after

    print(f'✅ Slide {from_pos:02d} → 位置 {to_pos:02d}')
    return new_html


LAYOUT_TEMPLATES = {
    'section': '''<div class="slide-frame">
      <div class="slide" data-layout="section"
           data-screen-label="{label}"
           data-slide-key="{key}">
        <div class="wordmark">飞书</div>
        <div class="chapter-num">{num}.</div>
        <h2 class="title" data-text-id="{id}.title">章节标题</h2>
        <p class="lede" data-text-id="{id}.lede">章节描述</p>
      </div>
    </div>''',
    'content-3up': '''<div class="slide-frame">
      <div class="slide" data-layout="content-3up"
           data-accent="blue"
           data-screen-label="{label}"
           data-slide-key="{key}"
           data-decor="blue-glow">
        <div class="wordmark">飞书</div>
        <div class="header"><div>
            <h2 class="title-zh" data-text-id="{id}.title">标题</h2>
          </div></div>
        <div class="stage"><div class="grid">
            <div class="card"><div class="head">
                <div class="ctitle" data-text-id="{id}.card1-title">卡片1标题</div>
                <div class="num">01</div></div>
              <div class="cbody" data-text-id="{id}.card1-body">卡片1内容</div></div>
            <div class="card"><div class="head">
                <div class="ctitle" data-text-id="{id}.card2-title">卡片2标题</div>
                <div class="num">02</div></div>
              <div class="cbody" data-text-id="{id}.card2-body">卡片2内容</div></div>
            <div class="card"><div class="head">
                <div class="ctitle" data-text-id="{id}.card3-title">卡片3标题</div>
                <div class="num">03</div></div>
              <div class="cbody" data-text-id="{id}.card3-body">卡片3内容</div></div>
          </div></div>
      </div>
    </div>''',
    'content-2col': '''<div class="slide-frame">
      <div class="slide" data-layout="content-2col"
           data-accent="blue"
           data-screen-label="{label}"
           data-slide-key="{key}"
           data-decor="blue-glow">
        <div class="wordmark">飞书</div>
        <div class="header"><div>
            <h2 class="title-zh" data-text-id="{id}.title">标题</h2>
          </div></div>
        <div class="stage"><div class="grid">
            <div class="col-text">
              <p class="lede" data-text-id="{id}.lede">描述</p>
              <ul class="feature-list">
                <li><b>要点1</b> — 说明</li>
                <li><b>要点2</b> — 说明</li>
                <li><b>要点3</b> — 说明</li>
              </ul>
            </div>
            <div class="col-visual">
              <div class="screenshot-frame">
                <img src="input/placeholder.png" alt="占位图" data-text-id="{id}.screenshot">
              </div>
            </div>
          </div></div>
      </div>
    </div>''',
    'stats': '''<div class="slide-frame">
      <div class="slide" data-layout="stats"
           data-accent="teal"
           data-screen-label="{label}"
           data-slide-key="{key}"
           data-decor="teal-glow">
        <div class="wordmark">飞书</div>
        <div class="header"><div>
            <h2 class="title-zh" data-text-id="{id}.title">数据标题</h2>
          </div></div>
        <div class="stage"><div class="grid">
            <div class="col"><div class="trend">趋势1</div>
              <div class="num">99<span class="unit">%</span></div>
              <div class="label" data-text-id="{id}.stat1-label">指标1</div></div>
            <div class="col"><div class="trend">趋势2</div>
              <div class="num">99<span class="unit">%</span></div>
              <div class="label" data-text-id="{id}.stat2-label">指标2</div></div>
            <div class="col"><div class="trend">趋势3</div>
              <div class="num">99<span class="unit">%</span></div>
              <div class="label" data-text-id="{id}.stat3-label">指标3</div></div>
            <div class="col"><div class="trend">趋势4</div>
              <div class="num">99<span class="unit">%</span></div>
              <div class="label" data-text-id="{id}.stat4-label">指标4</div></div>
          </div></div>
      </div>
    </div>''',
    'image-text': '''<div class="slide-frame">
      <div class="slide" data-layout="image-text"
           data-accent="blue"
           data-screen-label="{label}"
           data-slide-key="{key}"
           data-decor="blue-glow">
        <div class="wordmark">飞书</div>
        <div class="header"><div>
            <h2 class="title-zh" data-text-id="{id}.title">标题</h2>
          </div></div>
        <div class="stage"><div class="grid">
            <div class="col-text">
              <p class="lede" data-text-id="{id}.lede">描述</p>
              <ul class="feature-list">
                <li><b>要点1</b> — 说明</li>
                <li><b>要点2</b> — 说明</li>
              </ul>
            </div>
            <div class="col-visual">
              <div class="screenshot-frame">
                <img src="input/placeholder.png" alt="占位图" data-text-id="{id}.photo">
              </div>
            </div>
          </div></div>
      </div>
    </div>''',
    'process': '''<div class="slide-frame">
      <div class="slide" data-layout="process"
           data-accent="blue"
           data-screen-label="{label}"
           data-slide-key="{key}"
           data-decor="aurora">
        <div class="wordmark">飞书</div>
        <div class="header"><div>
            <h2 class="title-zh" data-text-id="{id}.title">流程标题</h2>
          </div></div>
        <div class="stage"><div class="flow" style="--cols: 4;">
            <div class="step"><div class="stnum">01</div>
              <h3 data-text-id="{id}.step1-title">步骤1</h3>
              <p data-text-id="{id}.step1-body">描述</p></div>
            <div class="step"><div class="stnum">02</div>
              <h3 data-text-id="{id}.step2-title">步骤2</h3>
              <p data-text-id="{id}.step2-body">描述</p></div>
            <div class="step"><div class="stnum">03</div>
              <h3 data-text-id="{id}.step3-title">步骤3</h3>
              <p data-text-id="{id}.step3-body">描述</p></div>
            <div class="step"><div class="stnum">04</div>
              <h3 data-text-id="{id}.step4-title">步骤4</h3>
              <p data-text-id="{id}.step4-body">描述</p></div>
          </div></div>
      </div>
    </div>''',
    'quote': '''<div class="slide-frame">
      <div class="slide" data-layout="quote"
           data-accent="blue"
           data-screen-label="{label}"
           data-slide-key="{key}">
        <div class="wordmark">飞书</div>
        <div class="stage">
          <blockquote data-text-id="{id}.quote">引用文字</blockquote>
          <cite data-text-id="{id}.cite">— 出处</cite>
        </div>
      </div>
    </div>''',
}


def cmd_add_slide(html: str, position: int, layout: str, key: str = None, accent: str = None) -> str:
    if layout not in LAYOUT_TEMPLATES:
        print(f'❌ 未知 layout: {layout}', file=sys.stderr)
        print(f'   可用: {", ".join(LAYOUT_TEMPLATES.keys())}', file=sys.stderr)
        return html

    slides = find_slides(html)
    slide_id = f'slide-{position:02d}'
    label = f'{position:02d} {layout.title()}'
    num = f'{position:02d}'

    template = LAYOUT_TEMPLATES[layout]
    new_slide = template.format(id=slide_id, label=label, key=key or layout, num=num)

    if accent:
        new_slide = new_slide.replace('data-accent="blue"', f'data-accent="{accent}"')

    if position > len(slides):
        insert_pos = slides[-1]['frame_end'] if slides else len(html) - len('</div>\n</body>')
        new_html = html[:insert_pos] + '\n\n    ' + new_slide + html[insert_pos:]
    else:
        target = slides[position - 1]
        new_html = html[:target['frame_start']] + new_slide + '\n\n    ' + html[target['frame_start']:]

    print(f'✅ 已在位置 {position} 插入 {layout} 页（key={key or layout}）')
    return new_html


def cmd_apply_spec(html: str, spec_path: str) -> str:
    with open(spec_path, 'r', encoding='utf-8') as f:
        spec_text = f.read()

    try:
        spec = json.loads(spec_text)
    except json.JSONDecodeError:
        import yaml
        spec = yaml.safe_load(spec_text)

    new_html = html
    ops = spec.get('operations', spec if isinstance(spec, list) else [])

    for op in ops:
        action = op.get('action', op.get('op'))
        if action == 'set-accent':
            new_html = cmd_set_accent(new_html, op['slide'], op['value'])
        elif action == 'set-layout':
            new_html = cmd_set_layout(new_html, op['slide'], op['value'])
        elif action == 'set-decor':
            new_html = cmd_set_decor(new_html, op['slide'], op['value'])
        elif action == 'set-screen-label':
            new_html = cmd_set_screen_label(new_html, op['slide'], op['value'])
        elif action == 'replace-img':
            new_html = cmd_replace_img(new_html, op['old'], op['new'])
        elif action == 'img-size':
            width, height = [int(part) for part in str(op['size']).lower().split('x', 1)]
            new_html = cmd_img_size(new_html, op['id'], width, height)
        elif action == 'img-position':
            new_html = cmd_img_position(new_html, op['id'], op['value'])
        elif action == 'remove-slide':
            new_html = cmd_remove_slide(new_html, op['slide'])
        elif action == 'duplicate-slide':
            new_html = cmd_duplicate_slide(new_html, op['slide'])
        elif action == 'move-slide':
            new_html = cmd_move_slide(new_html, op['from'], op['to'])
        elif action == 'add-slide':
            new_html = cmd_add_slide(new_html, op['position'], op['layout'],
                                     op.get('key'), op.get('accent'))
        else:
            print(f'⚠️  未知操作: {action}', file=sys.stderr)

    return new_html


def main() -> int:
    ap = argparse.ArgumentParser(
        description='deck-renderer deck-manage — structural editing tool',
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('html', help='deck HTML file')
    ap.add_argument('--info', action='store_true', help='show deck overview')
    ap.add_argument('--slide', type=int, help='target slide number (1-based)')
    ap.add_argument('--layout', metavar='VALUE', help='set slide layout')
    ap.add_argument('--accent', metavar='VALUE', help='set slide accent color')
    ap.add_argument('--decor', metavar='VALUE', help='set slide decor')
    ap.add_argument('--screen-label', metavar='VALUE', help='set slide screen label')
    ap.add_argument('--replace-img', nargs=2, metavar=('OLD', 'NEW'), help='replace image src')
    ap.add_argument('--img-size', nargs=2, metavar=('TEXT_ID', 'WxH'), help='set image width/height by data-text-id')
    ap.add_argument('--img-position', nargs=2, metavar=('TEXT_ID', 'POSITION'), help='set image object-position by data-text-id')
    ap.add_argument('--add-slide', nargs=2, metavar=('POS', 'LAYOUT'), help='add slide at position')
    ap.add_argument('--remove-slide', type=int, metavar='POS', help='remove slide at position')
    ap.add_argument('--duplicate-slide', type=int, metavar='POS', help='duplicate slide')
    ap.add_argument('--move-slide', nargs=2, type=int, metavar=('FROM', 'TO'), help='move slide')
    ap.add_argument('--key', help='slide key for --add-slide')
    ap.add_argument('--apply', metavar='SPEC', help='apply batch operations from YAML/JSON')
    ap.add_argument('--no-backup', action='store_true', help='skip .bak backup')
    ap.add_argument('--dry-run', action='store_true', help='preview only')

    args = ap.parse_args()
    html_path = Path(args.html)
    if not html_path.is_file():
        print(f'ERROR: {html_path} not found', file=sys.stderr)
        return 2

    html = html_path.read_text(encoding='utf-8')

    if args.info:
        cmd_info(html, args.slide)
        return 0

    new_html = html

    if args.layout and args.slide:
        new_html = cmd_set_layout(html, args.slide, args.layout)
    elif args.accent and args.slide:
        new_html = cmd_set_accent(html, args.slide, args.accent)
    elif args.decor and args.slide:
        new_html = cmd_set_decor(html, args.slide, args.decor)
    elif args.screen_label and args.slide:
        new_html = cmd_set_screen_label(html, args.slide, args.screen_label)
    elif args.replace_img:
        new_html = cmd_replace_img(html, args.replace_img[0], args.replace_img[1])
    elif args.img_size:
        try:
            width, height = [int(part) for part in args.img_size[1].lower().split('x', 1)]
        except Exception:
            print('ERROR: --img-size expects WIDTHxHEIGHT, e.g. 320x240', file=sys.stderr)
            return 1
        new_html = cmd_img_size(html, args.img_size[0], width, height)
    elif args.img_position:
        new_html = cmd_img_position(html, args.img_position[0], args.img_position[1])
    elif args.add_slide:
        new_html = cmd_add_slide(html, int(args.add_slide[0]), args.add_slide[1],
                                 args.key, args.accent)
    elif args.remove_slide:
        new_html = cmd_remove_slide(html, args.remove_slide)
    elif args.duplicate_slide:
        new_html = cmd_duplicate_slide(html, args.duplicate_slide)
    elif args.move_slide:
        new_html = cmd_move_slide(html, args.move_slide[0], args.move_slide[1])
    elif args.apply:
        new_html = cmd_apply_spec(html, args.apply)
    else:
        ap.print_help()
        return 1

    if new_html is html:
        return 0

    if args.dry_run:
        print('\n(dry-run, wrote nothing)')
        return 0

    if not args.no_backup:
        bak = html_path.with_suffix(html_path.suffix + '.bak')
        shutil.copy2(html_path, bak)
        print(f'📦 备份: {bak.name}')

    html_path.write_text(new_html, encoding='utf-8')
    print(f'💾 已写入: {html_path.name}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
