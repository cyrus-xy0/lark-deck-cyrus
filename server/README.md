# Generator Wrapper

`server/generator.py` is the P0 productized wrapper around the skills. It turns
a request into a task directory under `runs/`, runs the renderer and validator,
and emits the fixed handoff contract:

- `deck.json`
- `index.html`
- `texts.md`
- `FEEDBACK.md`
- `assets-manifest.yaml`
- `journey.json`
- `JOURNEY.md`
- `quality-insights.json`
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
  --deck-json skills/deck-renderer/deck-json/examples/sample-deck.json
```

Read status:

```bash
python3 server/generator.py status <task-id>
```

Read the user journey:

```bash
python3 server/generator.py journey <task-id>
python3 server/generator.py journey <task-id> --json
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
  "insert_slides": [],
  "client_events": [{ "type": "global_edit", "detail": { "field": "deck-title" } }]
}
```

Every successful create/edit writes a journey bundle into the task output:

- `journey.json`: full version/event/edit-session trace.
- `JOURNEY.md`: human-readable story from first request to current result.
- `quality-insights.json`: aggregated tuning signals and next-generation hints
  that can be fed back into recipe/layout/copy improvements.

## HTTP

Run the local wrapper service:

```bash
python3 server/generator.py serve --host 127.0.0.1 --port 8765
```

Run the P1 local service pair:

```bash
GENERATOR_PUBLIC_BASE_URL=https://your-public-host.example.com \
scripts/run-p1-services.sh
```

Run the P1 smoke checks without a live Feishu event stream:

```bash
scripts/run-p1-smoke.sh
```

Endpoints:

- `GET /health`
- `POST /decks` with JSON body `{ "brief": ... }`, `{ "outline": ... }`, or `{ "brief": ..., "sources": [...] }` creates an outline-confirmation task by default. When sources/attachments are present, the server runs `upload-recognizer` first and writes a temporary `input/runtime-library/` for this run. Call `POST /decks/{id}/confirm-outline` after user confirmation; non-interactive tests must pass both `{ "auto_confirm_outline": true, "allow_skip_outline_confirmation": true }` if they intentionally skip the gate.
- `GET /decks/{id}`
- `GET /decks/{id}/status`
- `GET /decks/{id}/edit`
- `GET /decks/{id}/journey`
- `GET /decks/{id}/insights`
- `POST /decks/{id}/confirm-outline`
- `POST /decks/{id}/accept-rehearsal`
- `POST /decks/{id}/revise-from-rehearsal`
- `POST /decks/{id}/confirm-deck`
- `POST /decks/{id}/skip-ingest`
- `POST /decks/{id}/regenerate`
- `POST /decks/{id}/edits`
- `GET /decks/{id}/files/index.html`
- `GET /decks/{id}/files/<editable-zip>.zip`
- `GET /library/slides?q=...&industry=...&product=...&layout=...`
- `GET /library/gate`
- `GET /library/design-kit`
- `POST /library/candidates`
- `POST /library/ppt-uploads`
- `POST /library/candidates/{candidate-id}/approve`
- `GET /recipes/validate`
- `POST /recipes/plan`

Generated deckhtml is published as a standalone Feishu/Miaobi Magic Page before
the user sees the preview. `magic_page_url` / `cloud_url` / `magic_url` are the
user-facing delivery links; local HTML and zip files remain internal run
artifacts for validation, editing, and audit. The legacy Magic Doc HTML Box path
is used only when `publish_target` is explicitly `magic-doc`. Ingestion
confirmation (`confirm-deck`) runs the final deck parser and then the Base/local
ingestor using the published cloud page as the delivery source.

`GET /decks/{id}/edit` is the P1 lightweight web editor. It supports:

- deck title, customer slug, and customer logo edits
- per-slide title and body text edits
- delete and reorder pages
- insert a reusable slide from the local example slide library
- save as a new task version (`v001`, `v002`, ...)
- record sanitized edit actions such as text edits, global metadata edits,
  slide reorder/delete, reusable slide insertion, and save events

`GET /decks/{id}/status` shows task state, artifact links, validator report,
failure log tail, sibling versions, and journey/quality-insight summaries.

## Slide Library MVP

P2 starts with a local split library:

- `library/design-kit/manifest.json`: layout names, CSS token files, brand
  assets, and product icon index.
- `library/business/slides/*.json`: approved reusable business slides.
- `library/business/candidates/*.json`: GTM-marked slides waiting for review.
- `library/business/uploads/*.json`: user-selected PPT/PPTX pages registered
  as Slide Library candidates before conversion.
- `library/knowledge/candidates/*.json`: "讲什么" candidates for `deck-planner`
  (scenario, key idea, emphasis, talk track, proof needed, risk).
- `library/presentation/candidates/*.json`: "怎么呈现" candidates for
  `deck-renderer` (DeckJSON fragment, layout, variant, thumbnail, visual pattern).

Ingest evaluates these layers separately. A generated slide may be reusable as
planner knowledge but not as a visual pattern, or reusable as a renderer pattern
but too customer-specific to become planning knowledge.

In live Base, only `知识库` and `素材库` are written for now. Slide Library is
kept local under `library/business/{slides,candidates,uploads}` for whole-page
selection; selected pages can later be decomposed into knowledge and material
records before syncing those two Base tables. The two Base records share
`关联SlideKey`; knowledge records point to `关联素材ID`, and material records point
to `关联知识ID`, so a slide can still be reconstructed as a knowledge/material pair
without creating a cloud Slide table.

Gate and search:

```bash
python3 server/slide_library.py validate
python3 server/slide_library.py search --industry 消费零售 --product 飞书
python3 scripts/base_library.py search-slides 零售 --limit 5
python3 scripts/base_library.py doctor --probe
```

Mark a generated slide as worth reusing:

```bash
python3 server/slide_library.py mark-reuse \
  --task-id <task-id> \
  --slide-key <slide-key> \
  --industry 消费零售 \
  --product 飞书AI \
  --customer-stage 首访 \
  --deck-type 客户pitch \
  --tag 值得复用
```

This writes the legacy business candidate and, when suitable, split candidates
for the knowledge layer and presentation layer.

Register a user-selected PPT/PPTX as Slide Library candidates:

```bash
python3 server/slide_library.py register-ppt path/to/team-slides.pptx \
  --title 团队自选PPT \
  --industry 消费零售 \
  --product 飞书 \
  --page 3 \
  --page 8
```

Without `--page`, all PPTX pages are registered. These records are placeholders
for search/selection; selected pages still need recognizer/renderer work before
they become polished H5 slides. PPTX text is used to generate local SVG
thumbnails under `library/business/thumbnails/uploads/`; legacy `.ppt` files get
a review placeholder thumbnail with source metadata.

Approve a reviewed candidate into the Business Library:

```bash
python3 server/slide_library.py approve-candidate <candidate-id> \
  --reviewer maintainer \
  --source-level internal-approved \
  --thumbnail library/business/thumbnails/<final>.svg
```

The gate checks unique slide keys, explicit source level, thumbnail/text/tags
and deck source completeness, plus common sensitive-info patterns.

## Pitch Recipe MVP

P3 adds a deterministic recipe layer on top of the generator:

- `knowledge/recipes/*.json`: first-visit pitch, POC solution, renewal review,
  industry case pack, and competitive replacement.
- `knowledge/industries/*.json`: retail/consumer, manufacturing, finance,
  internet/SaaS support, education, HR, and horizontal collaboration packs.
- `knowledge/product-modules.json`: Base, Aily, knowledge QA, Miaoda, Projects,
  Meetings, People, and Messenger/Docs narrative modules.

Plan and validate:

```bash
python3 server/pitch_recipes.py validate
python3 server/pitch_recipes.py plan \
  --brief "制造质量异常 POC 方案介绍" \
  --industry 制造 \
  --deck-type POC方案 \
  --product-scope "知识问答,飞书Base"
```

Generator tasks now write `recipe_refs`, `library_suggestions`,
`product_module_refs`, and `template_backlog_seed` into `outline.json`, and
surface the recipe/library/backlog sections in `FEEDBACK.md`.

The current brief planner is deterministic and conservative. It creates a
valid outline and pauses for user confirmation before rendering. After render,
the wrapper runs validation and pitch rehearsal, then pauses again for deckhtml
confirmation before ingestion.

Feishu Base access is cloud-first by default. The wrapper uses the configured
Base and current `lark-cli` user identity for `知识库` / `素材库`; if cloud access is
unavailable or unauthorized, the task records a clear warning and falls back to
local cache/candidates. Set `GENERATOR_USE_BASE_LIBRARY=0` or
`GENERATOR_SYNC_BASE_ASSETS=0` only for explicit local/offline runs.

## Feishu Bot MVP

`server/feishu_bot.py` is the first Feishu entry point. It consumes
`im.message.receive_v1` events, extracts a business brief, asks up to 5 missing
high-value questions, then calls the local generator and replies with links.
The clarification flow is passed into generator `interaction_history`, so
`JOURNEY.md` starts at the user's first bot message rather than only at the
completed brief.

Run a local text simulation:

```bash
python3 server/feishu_bot.py handle-text "帮我做一份零售客户 AI 知识库 pitchdeck"
```

Run the event consumer:

```bash
GENERATOR_PUBLIC_BASE_URL=http://127.0.0.1:8765 \
python3 server/feishu_bot.py serve
```

Check runtime readiness:

```bash
python3 server/feishu_bot.py doctor --base-url "$GENERATOR_PUBLIC_BASE_URL"
```

Generate a portable cloud-agent deployment bundle:

```bash
python3 scripts/cloud_agent_deploy.py \
  --output deploy/cloud-agent \
  --base-url "$GENERATOR_PUBLIC_BASE_URL"
```

The bundle contains an environment template, generator and bot start scripts,
`healthcheck.sh`, and a machine-readable endpoint manifest. It does not upload
secrets or deploy remotely.

The bot expects the generator HTTP service to be reachable at
`GENERATOR_PUBLIC_BASE_URL` so returned `status / preview / edit / download`
links can be opened by the user. It uses `lark-cli event consume
im.message.receive_v1 --as bot` and replies with `lark-cli im +messages-reply
--as bot`.
