# DeckJSON · Phase 0

**Purpose**: one structured data model for every feishu-deck-h5 deck.
Decouples *deck content* from *HTML/CSS rendering* so that:

1. The LLM stops producing free-form HTML and starts producing JSON →
   生成稳定性飞跃（输出空间收敛到 schema 内）.
2. A visual editor edits the same JSON the LLM produces → 编辑器和 AI 共用
   一套数据模型.
3. Renderer is a pure function → 同样的 JSON 永远渲染同样的 HTML（确定性）.

This folder is the Phase 0 deliverable: the schema + an example + a validator.
**No renderer yet** — that's Phase 1.

```
deck-json/
├── README.md              ← this file
├── deck-schema.json       ← JSON Schema Draft 2020-12 (single source of truth)
├── validate-deck.py       ← stdlib-only CLI validator
└── examples/
    └── sample-deck.json   ← 14-slide example covering every layout
```

---

## Quick start

```bash
# Validate the sample deck
python3 validate-deck.py examples/sample-deck.json

# Validate your own deck
python3 validate-deck.py path/to/my-deck.json

# Strict mode (warnings promoted to errors)
python3 validate-deck.py my-deck.json --strict

# Schema-only check (skip business rules)
python3 validate-deck.py my-deck.json --no-business-rules
```

Exit 0 = valid · 1 = invalid · 2 = file/schema load error.

---

## What's in the schema

### Top-level shape

```json
{
  "version": "1.0",
  "deck":   { "title", "author", "date", "language", ... },
  "slides": [ { "key", "layout", "accent", "decor", "data" }, ... ],
  "assets": { "scenes": {...}, "logos": {...} }
}
```

### 10 layouts + 2 specials (Phase 0 coverage)

`layout` is the primary discriminator; `variant` further specializes
multi-variant layouts. The renderer outputs a distinct `data-layout` per
(layout, variant) combo — visual fingerprints stay separate, schema just
groups them.

| Layout | Variant | HTML output (`data-layout=`) | Source |
|---|---|---|---|
| `cover` | — | `cover` | slide-recipes |
| `agenda` | — | `agenda` | slide-recipes |
| `section` | — | `section` | slide-recipes |
| `content` | `3up` | `content-3up` | slide-recipes |
| `content` | `2col` | `content-2col` | slide-recipes |
| `content` | `story-case` | `content-2col` + `.story-case` | render.py one-pager (Path A) |
| `content` | `blocks` | `content-2col` w/ full-width body | Phase 0.1 finding (production 2-col w/o text+visual split) |
| `content` | `matrix` | `matrix-2x2` | _layout-proposal.html · 2×2 strategic prioritization |
| `stats` | `row` | `stats` | slide-recipes |
| `stats` | `hero` | `big-stat` | slide-recipes |
| `stats` | `waterfall` | `waterfall` | _layout-proposal.html · 桥图分解 |
| `quote` | — | `quote` | slide-recipes |
| `image-text` | — | `image-text` | slide-recipes |
| `table` | — | `table` | slide-recipes |
| `flow` | `timeline` | `timeline` | slide-recipes |
| `flow` | `process` | `process` | slide-recipes |
| `flow` | `tree` | `issue-tree` | _layout-proposal.html · MECE 拆解 |
| `end` | — | `end` | slide-recipes |
| **specials** |||
| `replica` | — | full-bleed page image | SKILL.md Replica mode |
| `raw` | — | verbatim HTML | escape hatch |

= **10 base layouts** (7 single-variant + 3 multi-variant covering **12 effective forms**) + 2 specials.

The 10-base invariant is intentional — when adding a new pattern, the schema's discipline is: **first try to express it as a variant of an existing layout**. Only when the structural shape is too distinct (different DOM tree, different CSS architecture) does a new base layout become justified.

**Multi-variant layouts MUST declare `variant`**. The schema enforces
this via if/then: `layout=content` without `variant` errors immediately;
unknown variants (e.g. `variant=4up`) error too.

"Schema only" = the data shape is defined and validated, but the
**renderer hasn't been written yet** (Phase 1). For now you can:
- Author DeckJSON by hand or with Claude
- Validate it passes the schema + business rules
- Trust that when Phase 1 lands, the rendered HTML will be brand-correct

### Embeddable narrative-pattern blocks

Inside `content/3up.data.body_blocks[]` and `content/2col.data.text.body_blocks[]`:

- `pullquote` — italic blockquote with tone variants
- `cta-box` — call-to-action strip
- `kpi-strip` — 2-4 metric mini-cards
- `principle-band` — three-color strategy principles
- `data-panel` — non-app structured data (replaces `.ui-window` for non-screenshot content)

More patterns (north-star-map, scene-grid, two-hand-arch, ui-window family,
voice-card, overview-grid) will land in Phase 0.1 / Phase 1.

### Shared slide attributes

| Field | Type | Notes |
|---|---|---|
| `key` | string, kebab-case, **unique** | Semantic locator (`data-slide-key`). Required for slide-library ingest. |
| `layout` | enum (12 values) | Primary discriminator. |
| `variant` | string (REQUIRED for `content`/`stats`/`flow`) | Sub-discriminator within multi-variant layouts. Ignored on single-variant layouts. |
| `screen_label` | string (optional) | Pager UI label. Defaults to derived-from-title. |
| `accent` | enum: blue/teal/violet/purple/orange | **No cyan** (R49). |
| `decor` | array of decor tokens | violet-glow / blue-glow / mix-glow / teal-glow / orange-spark / aurora / grain / topo / flower-bg / section-bg / photo-bg. |
| `variant` | string | Layout-specific subvariant (e.g. agenda `with-header` / `recap`). |
| `language_override` | enum | Per-slide override of `deck.language`. |
| `custom_css` | string | **Escape hatch**. Discouraged. Phase 1+ renderer aims to eliminate need. |
| `notes` | string | Presenter notes / authoring intent (not rendered). |

---

## What the validator checks

### Pure schema (deck-schema.json)
- Required fields per layout
- Type / enum / pattern / length floors
- Discriminated union: layout determines data shape (via `if/then` per layout)
- `additionalProperties: false` on every closed object → no typos slip through

### Cross-field business rules (validate-deck.py)

| Rule | What it catches |
|---|---|
| **slide.key uniqueness** | duplicate keys (would break slide-library ingest) |
| **table.rows[*].length == headers.length** | rows out of sync with header count |
| **agenda single active** | recap variant has ≤ 1 highlighted item |
| **flow/timeline cols ↔ nodes count** | warn if mismatched |
| **flow/process cols ↔ steps count** | warn if mismatched |
| **content/story-case fit-check** | placeholder text (TBD/占位/...), too-short beats, duplicate beats (mirrors render.py ONE_PAGER_FIT_CHECK) |
| **R-LANG-ish** | `title_en` on content/3up cards in `zh-only` decks → warn |
| **R49 defense** | `accent: cyan` rejected even if schema enum changes |
| **variant required** | `content`/`stats`/`flow` without `variant` → error |
| **variant valid** | unknown variants (e.g. `variant: "4up"`) → error |

`--strict` promotes warnings to errors.

### What the validator does NOT check (yet)

- Visual layout integrity (R-OVERFLOW / R-VIS-* family) — needs the renderer + a browser
- Typography ladder (R20) — needs rendered CSS
- Per-page font floor (R06) — needs rendered CSS
- White-text-on-dark (R-WHITE-TEXT) — needs computed style

These come back in Phase 1 — the existing `validate.py` (HTML validator)
runs on the renderer's output and catches all of them. The DeckJSON-level
validator catches issues *before* you render, which is what makes the
generate→validate→regenerate loop cheap enough for LLM autocorrect.

---

## How this maps to current Path A (render.py)

| Path A pattern | DeckJSON | Notes |
|---|---|---|
| `one-pager` | `layout: content`, `variant: story-case` | Field shape identical to TOML. Schema enforces the same `fit_check` rules. |
| `quote` | `layout: quote` | TOML → JSON transcription is mechanical. |
| `big-stat` | `layout: stats`, `variant: hero` | Now grouped under `stats` since both are number-driven. |
| `multi-case-bundle` | **N slides in `slides[]`** | A bundle in DeckJSON is just a deck with `cover + agenda + N×(content/story-case) + end`. No special "composite pattern" needed — the array of slides IS the composition. |

This is one of the cleaner wins: in TOML-land, multi-case-bundle needs its
own renderer code path (`render_composite()`) to stitch fragments. In
DeckJSON-land, it's a non-event — the slides are just slides.

---

## Authoring discipline (when you write DeckJSON by hand)

1. **Pick `layout` first, then `variant` if applicable**. `content` /
   `stats` / `flow` REQUIRE `variant`; others ignore it. Each
   (layout, variant) combo's data shape is non-negotiable — schema
   rejects extra fields and missing required ones.
2. **`key` is semantic, not positional**. `arr-history` not `slide-08`.
   This is what the slide-library ingests. Don't change `key` just because
   you reordered slides.
3. **Accent goes on the slide, not in `data`**. `accent: "teal"` not
   `data: { accent: "teal" }`.
4. **Don't reach for `raw` layout to skip the schema**. If you're tempted,
   the right answer is usually "the layout you want doesn't exist yet —
   open an issue". `raw` is for one-off non-recurring weirdness.
5. **Image references**: prefer absolute or repo-relative paths inside
   `image_ref.src`. The `assets:` manifest is a future affordance; Phase 0
   renderer (not built yet) will resolve relative paths against the deck
   file's location.

---

## Roadmap

### Phase 0 — DONE (this folder)
- [x] Schema for 10 layouts (incl. 3 multi-variant) + 2 specials + 5 embeddable blocks
- [x] Stdlib-only validator with variant-required enforcement
- [x] 14-slide example covering every (layout, variant) combo
- [x] 12 negative-test cases proved validator catches violations (8 original + 4 variant-specific)
- [x] Reduced from initial 16 layouts → 10 to lower selection noise

### Phase 0.1 — extend schema (1-2 weeks, only if needed before Phase 1)
- [ ] Add narrative patterns as either standalone layouts or embeddable blocks:
      `north-star-map`, `scene-grid`, `two-hand-arch`, `overview-grid`,
      `voice-card`, `ui-window` family
- [ ] Add `phone-frame` / `desktop-frame` iframe-embed block
- [ ] Add bilingual mode flags per layout

### Phase 1 — Renderer (2-3 weeks)
- [ ] `render.py deck <deck.json> <output-dir>` produces full HTML deck
- [ ] Reuses existing `feishu-deck.css` / `feishu-deck.js` byte-for-byte
- [ ] Runs existing `validate.py` on rendered HTML (HARD GATE before delivery)
- [ ] Adds `--inline` for single-file delivery
- [ ] Same `runs/<ts>/output/` workflow

### Phase 2 — LLM produces DeckJSON (1-2 weeks)
- [ ] SKILL.md updated: prompts the LLM to emit DeckJSON via Tool Use
- [ ] PDF/HTML → DeckJSON transcription pipeline
- [ ] Replace SKILL.md authoring sections with "fill these JSON fields"
      instead of "write this HTML"

### Phase 3 — CLI editor (1 week)
- [ ] `deck-cli reorder <from> <to>` / `insert --after N --layout X` /
      `delete <key>` / `set <key>.path "value"`
- [ ] Wraps DeckJSON edits + revalidation; survives ID renumbering

### Phase 4 — Visual editor (4-6 weeks)
- [ ] Local web app (Vite + React)
- [ ] slide list / preview iframe / properties panel
- [ ] In-place text edit / drag reorder / layout swap / image upload
- [ ] "Redesign this section with AI" → Claude operates on the JSON subnode

---

## Open questions for review

1. **Is the layout enum complete enough for the next 6 months of decks?**
   Look at the recent `runs/<ts>/output/` history — any slide there that
   wouldn't map cleanly to one of the 16 layouts is a gap to fix in
   Phase 0.1.

2. **Should `data-page="NN"` per-page custom CSS stay as an escape hatch
   (`custom_css` field) or be banned outright?** It's the main vector of
   R20/R06 drift. Banning it forces every layout permutation to be a
   first-class schema field — better long-term, slower short-term.

3. **Embeddable-block depth: how nestable?** Phase 0 says: pullquote /
   cta-box / kpi-strip / principle-band / data-panel embed inside
   content-* layouts. Should they also embed inside each other (e.g. a
   `data-panel` with a `kpi-strip` inside)? Phase 0 says no — would
   complicate the renderer disproportionately for early days.

4. **Asset manifest vs inline paths**: do we need the `assets:` manifest
   in Phase 0, or wait until the renderer is built and we know how paths
   get rewritten in `runs/<ts>/output/`?

---

## Maintainer notes

- The schema lives at `deck-schema.json` and is the source of truth for
  every layout. **Add a layout = update schema first, then update
  validators / renderers**.
- The validator implements a subset of JSON Schema Draft 2020-12. If you
  need new schema keywords (e.g. `dependentRequired`, `format`,
  cross-file `$ref`), they need to be added to `validate-deck.py` too.
- Negative tests live inline in the README's verification recipe above.
  When you extend the schema, add a corresponding negative test to prove
  the new rule fires.
