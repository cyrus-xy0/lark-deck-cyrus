#!/usr/bin/env python3
"""Build a portable cloud-agent deployment bundle for lark-deck-cyrus.

The bundle is intentionally platform-neutral. It gives a user's cloud agent a
stable contract: environment variables, start command, health check, and the
HTTP endpoints it can expose. It does not upload secrets or deploy remotely.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def write(path: Path, text: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | 0o111)


def build_bundle(output: Path, base_url: str, port: int) -> dict[str, str]:
    if not output.is_absolute():
        output = REPO / output
    output.mkdir(parents=True, exist_ok=True)
    env_example = f"""# lark-deck-cyrus cloud agent environment
GENERATOR_HOST=0.0.0.0
GENERATOR_PORT={port}
GENERATOR_PUBLIC_BASE_URL={base_url}

# Required only when writing knowledge/assets to Feishu Base.
LARK_LIBRARY_BASE_TOKEN=
LARK_LIBRARY_MODE=auto
LARK_LIBRARY_AS=user

# Feishu bot mode.
FEISHU_DECK_BOT_STATE=runs/feishu-bot-state.json
FEISHU_DECK_BOT_DRY_RUN=0

# Optional for constrained cloud runtimes.
LARK_DECK_CYRUS_SKIP_PLAYWRIGHT_INSTALL=0

# Required if this bundle is copied outside the lark-deck-cyrus repository.
LARK_DECK_CYRUS_ROOT=
"""
    start_sh = """#!/usr/bin/env bash
set -euo pipefail
BUNDLE_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="${LARK_DECK_CYRUS_ROOT:-$(cd "$BUNDLE_DIR/../.." && pwd)}"
if [ -f "$BUNDLE_DIR/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$BUNDLE_DIR/.env"
  set +a
fi
if [ -n "${LARK_DECK_CYRUS_ROOT:-}" ]; then
  REPO_ROOT="$LARK_DECK_CYRUS_ROOT"
fi
cd "$REPO_ROOT"
HOST="${GENERATOR_HOST:-0.0.0.0}"
PORT="${GENERATOR_PORT:-8765}"
exec python3 server/generator.py serve --host "$HOST" --port "$PORT"
"""
    bot_sh = """#!/usr/bin/env bash
set -euo pipefail
BUNDLE_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="${LARK_DECK_CYRUS_ROOT:-$(cd "$BUNDLE_DIR/../.." && pwd)}"
if [ -f "$BUNDLE_DIR/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$BUNDLE_DIR/.env"
  set +a
fi
if [ -n "${LARK_DECK_CYRUS_ROOT:-}" ]; then
  REPO_ROOT="$LARK_DECK_CYRUS_ROOT"
fi
cd "$REPO_ROOT"
exec python3 server/feishu_bot.py serve --base-url "${GENERATOR_PUBLIC_BASE_URL:-http://127.0.0.1:8765}"
"""
    health_sh = """#!/usr/bin/env bash
set -euo pipefail
BUNDLE_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$BUNDLE_DIR/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$BUNDLE_DIR/.env"
  set +a
fi
BASE="${GENERATOR_PUBLIC_BASE_URL:-http://127.0.0.1:8765}"
curl -fsS "$BASE/health"
"""
    manifest = {
        "version": "1.0",
        "name": "lark-deck-cyrus-cloud-agent",
        "base_url": base_url,
        "port": port,
        "entrypoints": {
            "generator": "deploy/cloud-agent/start-generator.sh",
            "feishu_bot": "deploy/cloud-agent/start-feishu-bot.sh",
            "healthcheck": "deploy/cloud-agent/healthcheck.sh",
        },
        "endpoints": {
            "health": "/health",
            "create_deck": "POST /decks",
            "edit_deck": "POST /decks/{task_id}/edits",
            "library_slides": "GET /library/slides",
            "ppt_uploads": "POST /library/ppt-uploads",
        },
        "base_policy": "Feishu Base writes only knowledge/assets. Slide Library is local-only.",
        "required_runtime": ["python3", "node", "bash", "lark-cli for live Base/bot operations"],
    }
    write(output / "env.example", env_example)
    write(output / "start-generator.sh", start_sh, executable=True)
    write(output / "start-feishu-bot.sh", bot_sh, executable=True)
    write(output / "healthcheck.sh", health_sh, executable=True)
    write(output / "cloud-agent.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    readme = f"""# lark-deck-cyrus Cloud Agent Bundle

Generated bundle for exposing Cyrus from a user's cloud agent.

## Files

- `env.example`: copy to `.env` and fill secrets. Set `LARK_DECK_CYRUS_ROOT`
  if this bundle is copied outside the repository.
- `start-generator.sh`: starts `server/generator.py serve`.
- `start-feishu-bot.sh`: starts the Feishu bot listener.
- `healthcheck.sh`: checks `{base_url}/health`.
- `cloud-agent.json`: machine-readable endpoint manifest.

## Start

```bash
cp deploy/cloud-agent/env.example deploy/cloud-agent/.env
bash deploy/cloud-agent/start-generator.sh
```

In a second process, after Feishu event auth is configured:

```bash
bash deploy/cloud-agent/start-feishu-bot.sh
```

Slide Library stays local. `--write-base` writes only `知识库` and `素材库`.
"""
    write(output / "README.md", readme)
    return {key: str(output / value) for key, value in {
        "manifest": "cloud-agent.json",
        "env_example": "env.example",
        "generator": "start-generator.sh",
        "bot": "start-feishu-bot.sh",
        "healthcheck": "healthcheck.sh",
    }.items()}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", type=Path, default=Path("deploy/cloud-agent"))
    ap.add_argument("--base-url", default="http://127.0.0.1:8765")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args(argv)
    files = build_bundle(args.output, args.base_url, args.port)
    print(json.dumps({"ok": True, "files": files}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
