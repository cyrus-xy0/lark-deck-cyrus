#!/usr/bin/env bash
# feishu-deck-h5 · preflight check
# Verifies a local mount is present and writable before any skill action.
#
# Usage: bash assets/preflight.sh
#
# Exit codes:
#   0  OK — running from a real local mount, writable
#   1  no mount detected (working from a non-mounted path entirely)
#   2  read-only (mounted but can't write)
#   3  ephemeral session output only (/sessions/*/mnt/outputs/) — not allowed
#
# This script is the LAST LINE of the skill's preflight. It's a hard gate;
# any non-zero exit means the agent must STOP and refuse to proceed.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ---- Check 1: are we in ephemeral session output only? ----
case "$SKILL_ROOT" in
  */mnt/outputs|*/mnt/outputs/*)
    echo "PREFLIGHT FAIL · exit 3 · ephemeral session output detected"
    echo
    echo "  The skill is running from $SKILL_ROOT, which is an ephemeral"
    echo "  Cowork session output directory. Files here are wiped between"
    echo "  conversations and not visible in the user's editor or browser."
    echo
    echo "  REQUIRED: ask the user to mount their local working directory"
    echo "  via mcp__cowork__request_cowork_directory, then re-run from"
    echo "  inside that mounted folder."
    exit 3
    ;;
esac

# ---- Check 2: are we actually in any kind of mount? ----
# A non-Cowork user (running locally from a clone) will be at e.g.
# /Users/.../Projects/feishu-deck-h5 — that's a real mount.
# A Cowork user will be at /sessions/<id>/mnt/<folder-name>/feishu-deck-h5
# Both are valid; only /mnt/outputs/ is rejected.
if [[ -z "$SKILL_ROOT" ]]; then
  echo "PREFLIGHT FAIL · exit 1 · no skill root detected"
  exit 1
fi

# ---- Check 3: is the skill root writable? ----
PROBE="$SKILL_ROOT/.feishu-deck-h5-preflight-$$"
if ! ( touch "$PROBE" 2>/dev/null && rm -f "$PROBE" 2>/dev/null ); then
  echo "PREFLIGHT FAIL · exit 2 · skill root is read-only"
  echo
  echo "  $SKILL_ROOT exists but is not writable."
  echo "  Mount with write access so build.sh can produce examples/."
  exit 2
fi

# ---- Check 4: required asset files present? ----
REQUIRED=(
  "assets/feishu-deck.css"
  "assets/feishu-deck.js"
  "assets/validate.py"
  "assets/lark-logo.png"
  "assets/lark-cover-bg.jpg"
  "_body.partial.html"
  "build.sh"
  "SKILL.md"
)
MISSING=()
for f in "${REQUIRED[@]}"; do
  if [[ ! -f "$SKILL_ROOT/$f" ]]; then
    MISSING+=("$f")
  fi
done
if [[ ${#MISSING[@]} -gt 0 ]]; then
  echo "PREFLIGHT FAIL · exit 1 · missing required skill files"
  echo
  echo "  Mount root: $SKILL_ROOT"
  echo "  Missing files:"
  for f in "${MISSING[@]}"; do echo "    - $f"; done
  echo
  echo "  Likely cause: the user mounted an empty folder. Either git-clone"
  echo "  the feishu-deck-h5 repo into the mount, or copy from"
  echo "  ~/.claude/skills/feishu-deck-h5/ if installed via plugin."
  exit 1
fi

# ---- All checks passed ----
echo "PREFLIGHT OK"
echo "  skill root: $SKILL_ROOT"
echo "  writable  : yes"
echo "  ephemeral : no"
echo "  files     : ${#REQUIRED[@]}/${#REQUIRED[@]} present"
exit 0
