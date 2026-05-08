#!/usr/bin/env python3
"""
copy-assets.py — Make a per-run output self-contained.

For every HTML file under runs/<ts>/output/, scan for references to:
  ../../../../skills/feishu-deck-h5/assets/<path>     (single-pages/* depth)
  ../../../skills/feishu-deck-h5/assets/<path>        (output/* depth)
  ../skills/feishu-deck-h5/assets/<path>              (any other depth)
  ../../input/<file>                                   (input asset)

…and the corresponding feishu-deck.css / .js. Copy each referenced asset
into runs/<ts>/output/assets/ (preserving subfolders), and rewrite the
HTML path to a relative local path. Result: output/ is portable; the
deck runs standalone when copied/zipped/uploaded anywhere.

USAGE:
    python3 assets/copy-assets.py runs/<timestamp>/output/

Exits 0 on success. Idempotent: running twice is fine. Prints a summary
of bytes copied and HTML files patched.
"""

import os, re, sys, shutil
from pathlib import Path

# Match any reference of form *path*?/skills/feishu-deck-h5/(assets|...)/<file>
# and any input/ reference. Captures: prefix path back-tracking + the asset path.
RX_SKILL = re.compile(
    r'((?:\.\./)+)skills/feishu-deck-h5/(assets|examples|templates)/([^\'")\s]+)'
)
RX_INPUT = re.compile(
    r'((?:\.\./)+)input/([^\'")\s]+)'
)
# AFTER first rewrite, HTMLs use assets/<file> or ../assets/<file>
# (no skills/feishu-deck-h5 prefix). Both bare and ../-prefixed refs must
# be tracked so prune doesn't delete them.
# `*` (zero-or-more `../`) covers BOTH the deck root case (index.html in
# output/, refs like `assets/feishu-deck.css`) AND the sub-folder case
# (output/single-pages/p-NN.html, refs like `../assets/foo.png`).
RX_LOCAL_ASSET = re.compile(
    r'((?:\.\./)*)assets/([^\'")\s]+)'
)
RX_LOCAL_INPUT = re.compile(
    r'((?:\.\./)*)input/([^\'")\s]+)'
)

def find_skill_root() -> Path:
    """Walk up from this script to find skill root (feishu-deck-h5/)."""
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if (parent / "SKILL.md").exists():
            return parent
    raise SystemExit("Cannot locate feishu-deck-h5 skill root from script location.")

def find_run_root(out_dir: Path) -> Path:
    """Find runs/<ts>/ root from any nested output path."""
    for parent in [out_dir, *out_dir.parents]:
        if parent.name == "output" and parent.parent.parent.name == "runs":
            return parent.parent  # runs/<ts>/
    raise SystemExit(f"Cannot find run root from {out_dir}; expected runs/<ts>/output/.")

def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)

    out_dir = Path(sys.argv[1]).resolve()
    if not out_dir.is_dir():
        sys.exit(f"Not a directory: {out_dir}")

    skill_root = find_skill_root()
    run_root = find_run_root(out_dir)
    input_root = run_root / "input"

    # Local asset target inside output/
    local_assets = out_dir / "assets"
    local_input = out_dir / "input"
    local_assets.mkdir(parents=True, exist_ok=True)
    if input_root.exists():
        local_input.mkdir(parents=True, exist_ok=True)

    bytes_copied = 0
    files_copied = set()
    htmls_patched = 0
    referenced = set()      # paths still referenced after this run (relative to out_dir)

    for html_path in out_dir.rglob("*.html"):
        # Compute relative depth for new local paths
        # output/index.html             → assets/  / input/
        # output/single-pages/p01.html  → ../assets/ / ../input/
        depth = len(html_path.relative_to(out_dir).parts) - 1
        prefix = "../" * depth

        src = html_path.read_text(encoding="utf-8")
        original = src

        def replace_skill(m):
            nonlocal bytes_copied
            sub = m.group(2)  # assets / examples / templates
            rest = m.group(3)
            origin = skill_root / sub / rest
            target = local_assets / rest if sub == "assets" else local_assets / sub / rest
            referenced.add(str(target.relative_to(out_dir)))
            if origin.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists() or target.stat().st_size != origin.stat().st_size:
                    shutil.copy2(origin, target)
                    bytes_copied += origin.stat().st_size
                    files_copied.add(str(target.relative_to(out_dir)))
                # New ref: prefix + assets/rest (or assets/<sub>/rest)
                if sub == "assets":
                    return f'{prefix}assets/{rest}'
                else:
                    return f'{prefix}assets/{sub}/{rest}'
            else:
                # Origin missing — leave reference unchanged so author notices
                print(f"  [WARN] missing asset: {origin}")
                return m.group(0)

        def replace_input(m):
            nonlocal bytes_copied
            rest = m.group(2)
            origin = input_root / rest
            target = local_input / rest
            referenced.add(str(target.relative_to(out_dir)))
            if origin.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists() or target.stat().st_size != origin.stat().st_size:
                    shutil.copy2(origin, target)
                    bytes_copied += origin.stat().st_size
                    files_copied.add(str(target.relative_to(out_dir)))
                return f'{prefix}input/{rest}'
            else:
                print(f"  [WARN] missing input: {origin}")
                return m.group(0)

        src = RX_SKILL.sub(replace_skill, src)
        src = RX_INPUT.sub(replace_input, src)

        # Track already-rewritten refs (for second+ runs) so prune doesn't delete them.
        # Also self-heal: if the local target is missing, copy from skill_root/assets/
        # (or run input/) — protects against stale state after manual deletes.
        for m in RX_LOCAL_ASSET.finditer(src):
            rest = m.group(2)
            target = (out_dir / "assets" / rest).resolve()
            if not target.is_relative_to(out_dir):
                continue
            referenced.add(str(target.relative_to(out_dir)))
            if not target.exists():
                origin = skill_root / "assets" / rest
                if origin.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(origin, target)
                    bytes_copied += origin.stat().st_size
                    files_copied.add(str(target.relative_to(out_dir)))
        for m in RX_LOCAL_INPUT.finditer(src):
            rest = m.group(2)
            target = (out_dir / "input" / rest).resolve()
            if not target.is_relative_to(out_dir):
                continue
            referenced.add(str(target.relative_to(out_dir)))
            if not target.exists() and input_root.exists():
                origin = input_root / rest
                if origin.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(origin, target)
                    bytes_copied += origin.stat().st_size
                    files_copied.add(str(target.relative_to(out_dir)))

        if src != original:
            html_path.write_text(src, encoding="utf-8")
            htmls_patched += 1
            print(f"  patched  {html_path.relative_to(out_dir)}")

    # Pass 2: scan copied CSS files for internal url() refs (e.g.
    # feishu-deck.css uses url("lark-logo.png") with no ../ prefix). These
    # would-be-broken refs need their target files alongside the CSS.
    # We resolve each ref relative to the CSS file's location; if it isn't
    # already in output, copy from skill_root/assets/ (or skill_root sibling).
    rx_css_url = re.compile(r'url\(["\']?([^"\')\s]+)["\']?\)')
    for css_path in local_assets.rglob("*.css"):
        css_dir = css_path.parent
        css_src = css_path.read_text(encoding="utf-8")
        for m in rx_css_url.finditer(css_src):
            ref = m.group(1)
            # Skip data: URIs, absolute URLs, SVG fragment ids (#…), and bare punctuation
            if ref.startswith(("data:", "http:", "https:", "//", "#", "%23")):
                continue
            if ref in ("...", ""):
                continue
            if "/" not in ref and "." not in ref:
                continue       # not a file path
            # Resolve target relative to CSS location
            target = (css_dir / ref).resolve()
            if not target.is_relative_to(out_dir):
                continue       # ref escapes output/, skip
            referenced.add(str(target.relative_to(out_dir)))
            if target.exists():
                continue
            # Find the source: assume CSS lives at output/assets/* and the
            # corresponding file lives at skill_root/assets/<ref-relative>.
            # Compute the path inside skill assets that matches.
            rel_in_assets = target.relative_to(local_assets) if target.is_relative_to(local_assets) else None
            if rel_in_assets:
                origin = skill_root / "assets" / rel_in_assets
                if origin.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(origin, target)
                    bytes_copied += origin.stat().st_size
                    files_copied.add(str(target.relative_to(out_dir)))
                else:
                    print(f"  [WARN] CSS-referenced asset not found in skill: {origin}")

    # Prune: remove files in output/assets/ and output/input/ that are no
    # longer referenced (e.g. left over from previous runs).
    pruned = 0
    pruned_bytes = 0
    for root_dir in [local_assets, local_input]:
        if not root_dir.exists():
            continue
        for f in root_dir.rglob("*"):
            if not f.is_file():
                continue
            rel = str(f.relative_to(out_dir))
            if rel not in referenced:
                pruned += 1
                pruned_bytes += f.stat().st_size
                f.unlink()
        # remove empty subdirs left over after prune
        for d in sorted(root_dir.rglob("*"), key=lambda p: -len(p.parts)):
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()

    print()
    print(f"Done. {htmls_patched} HTML(s) patched · {len(files_copied)} unique asset(s) copied · {bytes_copied / 1024:.1f} KB copied")
    if pruned:
        print(f"      {pruned} stale file(s) pruned · {pruned_bytes / 1024:.1f} KB freed")
    print(f"Output is now self-contained — you can move {out_dir} anywhere and the deck still runs.")

if __name__ == "__main__":
    main()
