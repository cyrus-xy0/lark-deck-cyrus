#!/usr/bin/env bash
# package-skill.sh - build a portable lark-deck-cyrus project package.
#
# Produces lark-deck-cyrus-<YYYYMMDD>-<shortsha>.zip in the repo root.
# The archive contains the complete standalone project shell: install scripts,
# plugin manifests, docs, product skills, server wrappers, evals, config, and
# reusable libraries. It intentionally excludes local runs, caches, git data,
# and generated zip files.

set -euo pipefail

PACKAGE_NAME="lark-deck-cyrus"
SKILLS_ROOT="skills"
SKILL_NAMES=("lark-deck-cyrus" "deck-planner" "deck-renderer" "deck-auditor" "pitch-simulator")

for SKILL_NAME in "${SKILL_NAMES[@]}"; do
  if [ ! -d "$SKILLS_ROOT/$SKILL_NAME" ]; then
    echo "package-skill: must run from repo root (missing $SKILLS_ROOT/$SKILL_NAME/)" >&2
    exit 1
  fi
done
if [ ! -f ".codex-plugin/plugin.json" ]; then
  echo "package-skill: missing .codex-plugin/plugin.json" >&2
  exit 1
fi
if [ ! -x "install.sh" ]; then
  echo "package-skill: install.sh must exist and be executable" >&2
  exit 1
fi

DATE_STAMP="$(date +%Y%m%d)"
SHORT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo nogit)"
DIRTY_FLAG=""
if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
  DIRTY_FLAG="-dirty"
fi
VERSION="${DATE_STAMP}-${SHORT_SHA}${DIRTY_FLAG}"
ZIP_NAME="${PACKAGE_NAME}-${VERSION}.zip"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
STAGE="$TMP/$PACKAGE_NAME"
mkdir -p "$STAGE"

copy_path() {
  local path="$1"
  [ -e "$path" ] || return 0
  rsync -a \
    --exclude='.git/' \
    --exclude='.DS_Store' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='*.pyo' \
    --exclude='.pytest_cache/' \
    --exclude='node_modules/' \
    --exclude='runs/' \
    --exclude='.base-cache/' \
    --exclude='.deck-renderer-workspace/' \
    --exclude='library/knowledge/candidates/' \
    --exclude='library/presentation/candidates/' \
    --exclude='*.zip' \
    "$path" "$STAGE/"
}

INCLUDE_PATHS=(
  ".codex-plugin"
  ".claude-plugin"
  ".github"
  "skills"
  "scripts"
  "server"
  "evals"
  "config"
  "knowledge"
  "library"
  "README.md"
  "INSTALL.md"
  "install.sh"
  "package-skill.sh"
  "LICENSE"
  "PRODUCT.md"
  "PRODUCT_PLAN.md"
  "BUSINESS_RULES.md"
  "DESIGN.md"
  "CONTRIBUTING.md"
)
for path in "${INCLUDE_PATHS[@]}"; do
  copy_path "$path"
done

BUILT_AT="$(date '+%Y-%m-%d %H:%M:%S %Z')"
cat > "$STAGE/INSTALL-FROM-ZIP.md" <<EOF
# lark-deck-cyrus - install from zip

Version: \`$VERSION\`
Built: $BUILT_AT

## Quick install

\`\`\`bash
unzip $ZIP_NAME
cd lark-deck-cyrus
bash install.sh
\`\`\`

By default this copies the package into \`~/Projects/lark-deck-cyrus\`, then
symlinks these skills into \`~/.claude/skills/\`:

- \`lark-deck-cyrus\`
- \`deck-planner\`
- \`deck-renderer\`
- \`deck-auditor\`
- \`pitch-simulator\`

For another harness root:

\`\`\`bash
CLAUDE_DIR=~/.openclaw bash install.sh
\`\`\`

## Verify

\`\`\`bash
bash ~/.claude/skills/deck-renderer/assets/preflight.sh
\`\`\`

Expect \`PREFLIGHT OK\`.

## Contents

This archive is a standalone lark-deck-cyrus package. It contains no dependency
on the legacy upstream project. Local run outputs, Base cache copies, git
metadata, and prior zip artifacts are intentionally excluded.
EOF

(cd "$TMP" && zip -rq "$ZIP_NAME" "$PACKAGE_NAME")
mv "$TMP/$ZIP_NAME" .

SIZE_HUMAN="$(du -h "$ZIP_NAME" | cut -f1)"
FILE_COUNT="$(unzip -l "$ZIP_NAME" | tail -1 | awk '{print $2}')"
echo "OK -> $ZIP_NAME"
echo "    size:    $SIZE_HUMAN"
echo "    files:   $FILE_COUNT"
echo "    version: $VERSION"
echo
echo "Send $ZIP_NAME to the recipient. They unzip it, cd into $PACKAGE_NAME,"
echo "and run bash install.sh."
