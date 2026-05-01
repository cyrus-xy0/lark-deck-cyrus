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

# ---- Check 5: warn if another clone of the same repo lives elsewhere on disk ----
# This catches the "Claude Code mounted a session-storage copy, not the user's
# main GitHub clone" footgun: deck output lands in a folder the user can't
# easily find / commit / push from. Soft-warn (don't fail), and surface the
# competing paths so the agent can ask the user which one to use.
if command -v git >/dev/null 2>&1 && [ -d "$SKILL_ROOT/.git" ]; then
  CURRENT_REMOTE=$(git -C "$SKILL_ROOT" remote get-url origin 2>/dev/null || echo "")
  if [ -n "$CURRENT_REMOTE" ]; then
    # Search the most common dev locations on macOS / Linux. Bounded depth so
    # this stays cheap (< 1s on a typical home dir).
    SEARCH_ROOTS=(
      "$HOME/Documents/Github" "$HOME/Documents/GitHub"
      "$HOME/Documents"        "$HOME/Projects"
      "$HOME/GitHub"           "$HOME/Github"
      "$HOME/code"             "$HOME/Code"
      "$HOME/dev"              "$HOME/Dev"
      "$HOME/src"
    )
    # Identify directories by (device, inode) instead of path string, so the
    # comparison survives macOS APFS/HFS case-insensitivity (~/Documents/Github
    # vs ~/Documents/GitHub) and symlinks. `pwd -P` doesn't normalize case on
    # macOS, but inode IDs do.
    fs_id() {
      stat -f '%d:%i' "$1" 2>/dev/null \
        || stat -c '%d:%i' "$1" 2>/dev/null \
        || echo "$1"   # last-ditch fallback if neither stat flavor works
    }
    SKILL_ROOT_ID="$(fs_id "$SKILL_ROOT")"
    OTHER_CLONES=""
    SEEN_IDS=":"
    for root in "${SEARCH_ROOTS[@]}"; do
      [ -d "$root" ] || continue
      while IFS= read -r git_dir; do
        clone_dir="$(dirname "$git_dir")"
        clone_id="$(fs_id "$clone_dir")"
        # skip ourselves
        [ "$clone_id" = "$SKILL_ROOT_ID" ] && continue
        # dedupe — same physical dir reached via different SEARCH_ROOTS
        case "$SEEN_IDS" in *":$clone_id:"*) continue ;; esac
        SEEN_IDS="$SEEN_IDS$clone_id:"
        # check it's the same remote
        clone_remote=$(git -C "$clone_dir" remote get-url origin 2>/dev/null || echo "")
        if [ "$clone_remote" = "$CURRENT_REMOTE" ]; then
          OTHER_CLONES+="    - $clone_dir"$'\n'
        fi
      done < <(find "$root" -maxdepth 4 -type d -name '.git' 2>/dev/null)
    done
    if [ -n "$OTHER_CLONES" ]; then
      echo
      echo "WARNING · another clone of this repo lives on disk:"
      printf "%s" "$OTHER_CLONES"
      echo "  Current skill root  : $SKILL_ROOT"
      echo
      echo "  This means: outputs created here (runs/<ts>/, generated decks)"
      echo "  WILL NOT appear in the other clone(s). If the user usually"
      echo "  edits / commits from one of those, abort and re-run the skill"
      echo "  from inside that clone instead. Shared GitHub remote ≠ shared"
      echo "  filesystem — they're independent working directories."
      echo
      echo "  Agent: surface this to the user before creating the run folder."
    fi
  fi
fi

# ---- All checks passed ----
echo "PREFLIGHT OK"
echo "  skill root: $SKILL_ROOT"
echo "  writable  : yes"
echo "  ephemeral : no"
echo "  files     : ${#REQUIRED[@]}/${#REQUIRED[@]} present"
exit 0
