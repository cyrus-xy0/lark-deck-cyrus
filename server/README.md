# Generator Wrapper

`server/generator.py` is the P0 productized wrapper around the skills. It turns
a request into a task directory under `runs/`, runs the renderer and validator,
and emits the fixed handoff contract:

- `deck.json`
- `index.html`
- `texts.md`
- `FEEDBACK.md`
- `assets-manifest.yaml`
- editable `.zip`
- `task.json`
- `validator-report.md`

## CLI

Create a task from a business brief:

```bash
python3 server/generator.py create --request server/examples/brief-request.json
```

Create from an existing DeckJSON source:

```bash
python3 server/generator.py create \
  --deck-json skills/feishu-deck-h5/deck-json/examples/sample-deck.json
```

Read status:

```bash
python3 server/generator.py status <task-id>
```

Regenerate from the original request:

```bash
python3 server/generator.py regenerate <task-id>
```

Create an edited version without overwriting the original task:

```bash
python3 server/generator.py edit <task-id> --patch edit.json
```

`edit.json` may contain a full `deck_json` replacement or structured fields:

```json
{
  "updates": { "title": "新版标题", "customer_slug": "customer-demo" },
  "slide_updates": [{ "key": "cover", "data": { "title": "新版标题" } }],
  "delete_slide_keys": ["old-slide"],
  "slide_order": ["cover", "business-gap", "next-step"],
  "insert_slides": []
}
```

## HTTP

Run the local wrapper service:

```bash
python3 server/generator.py serve --host 127.0.0.1 --port 8765
```

Endpoints:

- `POST /decks` with JSON body `{ "brief": ... }`, `{ "outline": ..., "deck_json": ... }`, or `{ "deck_json": ... }`
- `GET /decks/{id}`
- `GET /decks/{id}/status`
- `GET /decks/{id}/edit`
- `POST /decks/{id}/regenerate`
- `POST /decks/{id}/edits`
- `GET /decks/{id}/files/index.html`
- `GET /decks/{id}/files/<editable-zip>.zip`

`GET /decks/{id}/edit` is the P1 lightweight web editor. It supports:

- deck title, customer slug, and customer logo edits
- per-slide title and body text edits
- delete and reorder pages
- insert a reusable slide from the local example slide library
- save as a new task version (`v001`, `v002`, ...)

`GET /decks/{id}/status` shows task state, artifact links, validator report,
failure log tail, and sibling versions.

The current brief planner is deterministic and conservative. It creates a
valid first draft and records missing information in `outline.json` and
`FEEDBACK.md`; richer GTM questioning and recipe selection should layer on top
of this wrapper rather than bypass it.

For service-side stability, Feishu Base access is opt-in. By default the
wrapper uses local knowledge cache files and runs the renderer with
`--offline-cache`, so CI and sandboxed workers do not need a local keychain.
Set `GENERATOR_USE_BASE_LIBRARY=1` plus `LARK_LIBRARY_AS=bot` for Feishu bot
workers that should query the live Base tables. Set
`GENERATOR_SYNC_BASE_ASSETS=1` only when the worker should refresh shared
assets from live Base during rendering.

## Feishu Bot MVP

`server/feishu_bot.py` is the first Feishu entry point. It consumes
`im.message.receive_v1` events, extracts a business brief, asks up to 5 missing
high-value questions, then calls the local generator and replies with links.

Run a local text simulation:

```bash
python3 server/feishu_bot.py handle-text "帮我做一份零售客户 AI 知识库 pitchdeck"
```

Run the event consumer:

```bash
GENERATOR_PUBLIC_BASE_URL=http://127.0.0.1:8765 \
python3 server/feishu_bot.py serve
```

The bot expects the generator HTTP service to be reachable at
`GENERATOR_PUBLIC_BASE_URL` so returned `status / preview / edit / download`
links can be opened by the user. It uses `lark-cli event consume
im.message.receive_v1 --as bot` and replies with `lark-cli im +messages-reply
--as bot`.
