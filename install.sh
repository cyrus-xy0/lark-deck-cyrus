#!/usr/bin/env bash
# lark-deck-cyrus install script
#
# Installs the lark-deck-cyrus product skills into Claude Code or any compatible
# harness that follows the <harness-root>/skills convention.
#
# Supported sources:
#   1. A git checkout of https://github.com/cyrus-xy0/lark-deck-cyrus.git
#   2. A zip/package produced by package-skill.sh
#   3. An existing local working copy
#
# Environment variables:
#   INSTALL_DIR   where to keep the durable working copy
#                 default: ~/Projects/lark-deck-cyrus
#   CLAUDE_DIR    skill registration root
#                 default: ~/.claude
#   REPO_URL      git remote used when a network clone/update is needed
#                 default: https://github.com/cyrus-xy0/lark-deck-cyrus.git
#   LARK_DECK_CYRUS_INSTALL_FROM_LOCAL=1
#                 copy from this script's directory even if INSTALL_DIR is git
#   LARK_DECK_CYRUS_SKIP_PLAYWRIGHT_INSTALL=1
#                 skip default project-local Playwright + Chromium install

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/cyrus-xy0/lark-deck-cyrus.git}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/Projects/lark-deck-cyrus}"
CLAUDE_DIR="${CLAUDE_DIR:-$HOME/.claude}"
SKILLS_DIR="$CLAUDE_DIR/skills"
SKILL_NAMES=("lark-deck-cyrus" "upload-parser" "deck-planner" "deck-renderer" "deck-auditor" "pitch-simulator" "deck-ingestor")
PRIMARY_SKILL="deck-renderer"
PRIMARY_LINK_PATH="$SKILLS_DIR/$PRIMARY_SKILL"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PY_DEPS_DIR="$INSTALL_DIR/.deps/python"
PW_BROWSERS_DIR="$INSTALL_DIR/.deps/ms-playwright"

same_path() {
  local left right
  left="$(cd "$1" 2>/dev/null && pwd -P || true)"
  right="$(cd "$2" 2>/dev/null && pwd -P || true)"
  [ -n "$left" ] && [ "$left" = "$right" ]
}

has_local_package() {
  [ -d "$SCRIPT_DIR/skills/lark-deck-cyrus" ] && [ -d "$SCRIPT_DIR/skills/$PRIMARY_SKILL" ]
}

copy_local_package() {
  if same_path "$SCRIPT_DIR" "$INSTALL_DIR"; then
    echo "==> using current checkout at $INSTALL_DIR"
    return
  fi

  echo "==> copying local package to $INSTALL_DIR"
  mkdir -p "$INSTALL_DIR"
  rsync -a \
    --exclude='.git/' \
    --exclude='.DS_Store' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='*.pyo' \
    --exclude='.pytest_cache/' \
    --exclude='.deps/' \
    --exclude='runs/' \
    --exclude='.base-cache/' \
    --exclude='library/knowledge/candidates/' \
    --exclude='library/presentation/candidates/' \
    --exclude='*.zip' \
    "$SCRIPT_DIR/" "$INSTALL_DIR/"
}

ensure_remote_available() {
  if git ls-remote "$REPO_URL" HEAD >/dev/null 2>&1; then
    return
  fi

  if [[ "$REPO_URL" == git@github.com:* || "$REPO_URL" == ssh://git@github.com/* ]]; then
    SSH_OUT="$(ssh -T -o BatchMode=yes -o ConnectTimeout=5 git@github.com 2>&1 || true)"
    GH_USER="$(printf '%s\n' "$SSH_OUT" | sed -n 's/^Hi \([^!]*\)!.*/\1/p')"
    cat <<EOF

ERROR: cannot access the lark-deck-cyrus repository over SSH:
  $REPO_URL

This usually means the machine does not have a GitHub SSH key configured.
For the public repository, prefer the HTTPS URL:

  REPO_URL=https://github.com/cyrus-xy0/lark-deck-cyrus.git bash install.sh

If the repository is private, ask FuQiang to add you as a collaborator:

  你好，想用一下 lark-deck-cyrus 这个 skill，
  请把我加为仓库 collaborator：

  GitHub 用户名: ${GH_USER:-<your GitHub username>}
  仓库: ${REPO_URL}
  添加入口: 仓库 Settings > Collaborators / Access

After accepting the GitHub invitation or configuring SSH, rerun this script.

EOF
    exit 2
  fi

  cat <<EOF

ERROR: cannot access the lark-deck-cyrus repository:
  $REPO_URL

Check network access to GitHub first. If you are using a private fork, pass a
URL your environment can access, for example an HTTPS URL with a Personal
Access Token or an SSH URL after configuring a GitHub SSH key.

EOF
  exit 2
}

echo "==> lark-deck-cyrus install"
echo "    repo:    $REPO_URL"
echo "    source:  $SCRIPT_DIR"
echo "    target:  $INSTALL_DIR"
echo "    skills:  ${SKILL_NAMES[*]}"
echo "    into:    $SKILLS_DIR"
echo

# 1. Prepare a durable project copy.
if [ "${LARK_DECK_CYRUS_INSTALL_FROM_LOCAL:-}" = "1" ] && has_local_package; then
  copy_local_package
elif [ -d "$INSTALL_DIR/.git" ]; then
  echo "==> existing git checkout found at $INSTALL_DIR, pulling latest..."
  CURRENT_REMOTE="$(git -C "$INSTALL_DIR" remote get-url origin 2>/dev/null || true)"
  if [ "$CURRENT_REMOTE" != "$REPO_URL" ]; then
    echo "==> setting origin remote to $REPO_URL"
    git -C "$INSTALL_DIR" remote set-url origin "$REPO_URL"
  fi
  if ! git -C "$INSTALL_DIR" pull --ff-only; then
    if has_local_package; then
      echo "WARN: git update failed; falling back to the local package copy."
      copy_local_package
    else
      exit 1
    fi
  fi
elif has_local_package; then
  copy_local_package
else
  echo "==> cloning from git..."
  ensure_remote_available
  mkdir -p "$(dirname "$INSTALL_DIR")"
  git clone "$REPO_URL" "$INSTALL_DIR"
fi

# 2. Install project-local runtime dependencies.
install_playwright_deps() {
  if [ "${LARK_DECK_CYRUS_SKIP_PLAYWRIGHT_INSTALL:-}" = "1" ]; then
    echo "==> skipping Playwright install (LARK_DECK_CYRUS_SKIP_PLAYWRIGHT_INSTALL=1)"
    return
  fi

  if [ ! -f "$INSTALL_DIR/requirements.txt" ]; then
    echo "ERROR: missing $INSTALL_DIR/requirements.txt; cannot install Playwright dependency" >&2
    exit 1
  fi

  if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 is required to install Playwright and run deck validation" >&2
    exit 1
  fi
  if ! python3 -m pip --version >/dev/null 2>&1; then
    echo "ERROR: python3 -m pip is required to install Playwright" >&2
    echo "Install pip for your Python 3, then rerun install.sh." >&2
    exit 1
  fi

  mkdir -p "$PY_DEPS_DIR" "$PW_BROWSERS_DIR"
  echo "==> installing Python deps into $PY_DEPS_DIR"
  python3 -m pip install --upgrade --target "$PY_DEPS_DIR" -r "$INSTALL_DIR/requirements.txt"

  echo "==> installing Playwright Chromium into $PW_BROWSERS_DIR"
  PYTHONPATH="$PY_DEPS_DIR${PYTHONPATH:+:$PYTHONPATH}" \
  PLAYWRIGHT_BROWSERS_PATH="$PW_BROWSERS_DIR" \
    python3 -m playwright install chromium
}

install_playwright_deps

# 3. Symlink product skills into the harness skills directory.
mkdir -p "$SKILLS_DIR"
for SKILL_NAME in "${SKILL_NAMES[@]}"; do
  SRC_PATH="$INSTALL_DIR/skills/$SKILL_NAME"
  LINK_PATH="$SKILLS_DIR/$SKILL_NAME"
  if [ ! -d "$SRC_PATH" ]; then
    echo "ERROR: missing skill directory: $SRC_PATH" >&2
    exit 1
  fi
  if [ -L "$LINK_PATH" ] || [ -e "$LINK_PATH" ]; then
    echo "==> replacing existing $LINK_PATH"
    rm -rf "$LINK_PATH"
  fi
  ln -s "$SRC_PATH" "$LINK_PATH"
  echo "==> symlinked: $LINK_PATH -> $SRC_PATH"
done

# 4. Verify.
echo
echo "==> running preflight..."
if bash "$PRIMARY_LINK_PATH/assets/preflight.sh"; then
  echo
  echo "==> DONE. Restart your Claude Code / harness session to pick up the new skills."
else
  echo
  echo "WARN: preflight failed. The skills are installed, but this shell may not"
  echo "be in a writable project mount. cd into a real project before generating decks."
  exit 1
fi
