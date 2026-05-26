"""
deck-renderer  ·  texts_common

Shared utilities for the data-text-id ⇄ texts.md sidecar pipeline.
Imported by apply-texts.py (write side) and extract-texts.py (read side)
so both scripts agree on tag-recognition and inner-value encoding.

Previously these symbols lived in apply-texts.py and extract-texts.py
borrowed them via `importlib.import_module('apply-texts')` (the hyphen
made a normal import impossible). Extracting them here makes the
dependency visible to static analysis and lets the two scripts evolve
without one silently breaking the other.

Stays standard-library-only so the deliverable zip can run with stock
Python 3 on macOS / Windows / Linux.
"""

from __future__ import annotations
import re


# Open tag carrying data-text-id, the inner content (non-greedy), and matching
# close tag. We restrict to alphanumeric tag names (`[a-zA-Z][a-zA-Z0-9]*` —
# note the trailing digits ARE allowed, e.g. h1 / h2 / h3) to avoid matching
# SVG-style namespaced tags by accident.
TEXT_LEAF_RE = re.compile(
    r'(<(?P<tag>[a-zA-Z][a-zA-Z0-9]*)\s[^<>]*?'
    r'data-text-id="(?P<id>[^"]+)"[^<>]*?>)'
    r'(?P<inner>(?:(?!</(?P=tag)>).)*?)'
    r'(?P<close></(?P=tag)>)',
    re.S,
)


def encode_value_to_inner(value: str) -> str:
    """Convert texts.md value (with literal newlines) → HTML inner content.

    Rules:
        plain text → escape & < > to entities
        '\\n' inside value → '<br>' in HTML
    """
    parts = value.split('\n')
    escaped = [
        p.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        for p in parts
    ]
    return '<br>'.join(escaped)


def decode_inner_to_value(inner: str) -> str:
    """Inverse of encode_value_to_inner — HTML inner → texts.md value."""
    s = re.sub(r'<br\s*/?>', '\n', inner, flags=re.I)
    s = s.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    return s.strip()


def find_leaves(html: str) -> list[tuple[str, int, int, str, str, str, str]]:
    """Return list of (id, start, end, open_tag, inner, close_tag, full_match)
    for every data-text-id leaf in `html`."""
    found = []
    for m in TEXT_LEAF_RE.finditer(html):
        found.append((
            m.group('id'),
            m.start(), m.end(),
            m.group(1),
            m.group('inner'),
            m.group('close'),
            m.group(0),
        ))
    return found
