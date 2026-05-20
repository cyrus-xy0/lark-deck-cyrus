#!/usr/bin/env bash
# deck-editor.command — macOS one-click launcher
#
# Use it any of these ways:
#   • Double-click in Finder → opens the most-recently-edited deck.json
#     in <repo>/runs/<ts>/output/
#   • Drag a deck.json file onto this .command in Finder → opens that deck
#   • Add to Dock for one-click access
#
# Requires Python 3.11+ (built-in on modern macOS).

set -e
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EDITOR_PY="$HERE/deck-editor.py"

if [ ! -f "$EDITOR_PY" ]; then
    osascript -e "display dialog \"deck-editor.py 找不到 ($EDITOR_PY). 这个 .command 文件需要跟 deck-editor.py 在同一目录.\""
    exit 1
fi

# If a file is dragged onto this .command, $1 is its path
if [ -n "$1" ]; then
    DECK="$1"
else
    # Auto-detect: most recently modified deck.json in any runs/<ts>/output/
    # under the skill repo root (= deck-editor.py's grandparent's parent).
    REPO_ROOT="$(cd "$HERE/../../.." && pwd)"
    if [ -d "$REPO_ROOT/runs" ]; then
        DECK=$(ls -t "$REPO_ROOT"/runs/*/output/deck.json 2>/dev/null | head -1)
    fi
    if [ -z "$DECK" ]; then
        osascript -e "display dialog \"找不到 deck.json. 把一个 deck.json 文件拖到这个 .command 文件上,或者先在 $REPO_ROOT/runs/<your-name>/output/ 里放一个 deck.json.\""
        exit 1
    fi
fi

echo "→ Launching deck-editor on $DECK"
echo ""
exec /usr/bin/env python3 "$EDITOR_PY" "$DECK"
