#!/usr/bin/env bash
# feishu-deck-h5 · install script
#
# Installs this skill into Claude Code (or any compatible harness that follows
# the ~/.claude/skills/ convention) by:
#   1. Cloning to $INSTALL_DIR (default: ~/Projects/feishu-deck-h5)
#   2. Symlinking skills/feishu-deck-h5 into $CLAUDE_DIR/skills/feishu-deck-h5
#   3. Running preflight to verify
#
# Usage:
#   bash install.sh                              # from inside an existing clone
#   git clone <url> tmp && bash tmp/install.sh   # one-shot from anywhere
#
# Environment variables:
#   INSTALL_DIR   where to keep the working clone (default: ~/Projects/feishu-deck-h5)
#   CLAUDE_DIR    skill registration root (default: ~/.claude — use ~/.openclaw etc. for other harnesses)
#   REPO_URL      override the git remote (default: git@github.com:FuQiang/feishu-deck-h5.git)

set -e

REPO_URL="${REPO_URL:-git@github.com:FuQiang/feishu-deck-h5.git}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/Projects/feishu-deck-h5}"
CLAUDE_DIR="${CLAUDE_DIR:-$HOME/.claude}"
SKILLS_DIR="$CLAUDE_DIR/skills"
LINK_PATH="$SKILLS_DIR/feishu-deck-h5"

echo "==> feishu-deck-h5 install"
echo "    repo:    $REPO_URL"
echo "    target:  $INSTALL_DIR"
echo "    symlink: $LINK_PATH"
echo

# Prereq: SSH access to GitHub
if ! ssh -T -o BatchMode=yes -o ConnectTimeout=5 git@github.com 2>&1 | grep -q "successfully authenticated\|Hi "; then
  echo "ERROR — SSH to github.com failed. Make sure your SSH key is registered:"
  echo "  https://github.com/settings/keys"
  echo "  Test with: ssh -T git@github.com"
  exit 1
fi

# 1. clone (or update if exists)
if [ -d "$INSTALL_DIR/.git" ]; then
  echo "==> existing clone found at $INSTALL_DIR, pulling latest..."
  git -C "$INSTALL_DIR" pull --ff-only
else
  echo "==> cloning..."
  mkdir -p "$(dirname "$INSTALL_DIR")"
  git clone "$REPO_URL" "$INSTALL_DIR"
fi

# 2. symlink into $CLAUDE_DIR/skills/
mkdir -p "$SKILLS_DIR"
if [ -L "$LINK_PATH" ] || [ -e "$LINK_PATH" ]; then
  echo "==> removing existing $LINK_PATH..."
  rm -rf "$LINK_PATH"
fi
ln -s "$INSTALL_DIR/skills/feishu-deck-h5" "$LINK_PATH"
echo "==> symlinked: $LINK_PATH -> $INSTALL_DIR/skills/feishu-deck-h5"

# 3. verify
echo
echo "==> running preflight..."
if bash "$LINK_PATH/assets/preflight.sh"; then
  echo
  echo "==> DONE. Restart your Claude Code / harness session to pick up the new skill."
else
  echo
  echo "WARN — preflight failed. The skill is installed but the current directory"
  echo "may not be a writable mount. cd into a real project before generating decks."
  echo "(See SKILL.md PREFLIGHT for details.)"
  exit 1
fi
