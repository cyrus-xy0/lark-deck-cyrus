# Cyrus Skill Contract Schemas

This directory defines the machine contracts between the Cyrus controller and
its sub skills. The rule is simple: subagents pass JSON artifacts that validate
against these schemas. User-facing markdown can still explain the result, but it
is never the source of truth for downstream agents.

## Skill I/O Matrix

| Skill | Canonical input | Canonical output | Downstream transfer |
|---|---|---|---|
| `upload-parser` | user brief + source files / URLs | `source-dossier.schema.json` | `source-dossier.json` feeds planner, renderer, and ingestor |
| `deck-planner` | user brief and optional `source-dossier.json` | `../deck-planner/schema/deck-outline.schema.json` | `outline.json` feeds renderer directly |
| `deck-renderer` | `outline.json` plus optional `source-dossier.json` | `../deck-renderer/deck-json/deck-schema.json` plus rendered files | `deck.json` + `index.html` feed auditor |
| `deck-auditor` | `index.html` plus optional `deck.json` | `audit-report.schema.json` | `audit-report.json` gates simulator, publish, and ingestion |
| `pitch-simulator` | `outline.json`, `deck.json`, optional `audit-report.json` | `../pitch-simulator/schema/pitch-rehearsal.schema.json` | `pitch-rehearsal.json` feeds user revision decision and ingestion |
| `deck-ingestor` | `audit-report.json`, `deck.json`, optional `source-dossier.json` / `pitch-rehearsal.json` | `ingestion-manifest.schema.json` | `ingestion-manifest.json` closes the reuse loop |

## Transfer Rule

Every downstream transfer must use the smallest canonical artifact set. Do not
create a second entity when an existing artifact already carries the required
structure. In particular:

- no `planner-to-renderer.json`; renderer consumes `outline.json`.
- no parser/planner/auditor/rehearsal/ingestion request wrapper JSON unless a
  real API boundary starts consuming that file.
- no `renderer-output.json`; auditor consumes `deck.json` and `index.html`.

Canonical domain artifacts such as `source-dossier.json`, `outline.json`,
`deck.json`, `audit-report.json`, `pitch-rehearsal.json`, and
`ingestion-manifest.json` keep their own schema shape and are passed directly.

For example, planner to renderer is not a prose paragraph and is not a second
copied planning entity. It is the same `outline.json` that validates against
`deck-outline.schema.json`:

When a user edits the confirmation draft `DESIGN_PLAN.md`, the confirmation
step must sync controlled markdown fields back into this same `outline.json`
before renderer handoff. The markdown is a review surface, not a second source
of truth.

```json
{
  "version": "1.0",
  "brief": {},
  "scene": {},
  "thesis": {},
  "outline": {
    "arc": "...",
    "slides": []
  },
  "asset_plan": [],
  "claim_discipline": {
    "unsupported_claims": [],
    "needs_user_confirmation": []
  },
  "handoff": {
    "target_skill": "deck-renderer",
    "deckjson_strategy": "needs-user-confirmation"
  }
}
```

Human confirmation is a workflow gate around `outline.json`, not a separate
payload that repeats the outline.

## Validation

Use the stdlib-only contract validator for schemas in this directory:

```bash
python3 skills/lark-deck-cyrus/schema/validate-contract.py \
  --schema skills/lark-deck-cyrus/schema/source-dossier.schema.json \
  --instance runs/<task>/input/runtime-library/source-dossier.json
```

The validator reuses the DeckJSON schema subset implementation, so these
schemas intentionally stay within that supported JSON Schema surface.
