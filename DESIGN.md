# DESIGN.md — deck-renderer

> Brand-safe, dark, cinematic, bilingual (ZH primary / EN secondary) HTML
> presentation system, derived from the **飞书母版 2025 (深色通用)** PowerPoint
> theme. Single HTML file, 1920×1080 design canvas, scaled fluidly to PC
> 16:9 + mobile vertical. Generated decks must look indistinguishable from a
> hand-built Lark sales deck. Use ONLY the tokens listed below.

---

## 1. Visual Theme & Atmosphere

| Attribute      | Value |
|----------------|---|
| Mood           | Calm, declarative, evidence-led. Premium enterprise. |
| Density        | Dense but disciplined. Content pages can be information-rich; section / quote / hero pages create breath. |
| Light          | Dark canvas always (`#000` default), cool radial blooms. |
| Texture        | Flat. **No drop shadows on slides.** No backdrop-blur. |
| Energy         | Comes from hierarchy, native UI/diagram form, and purposeful state motion; never from punctuation. |
| Bilingual rule | **ZH always primary** (larger, on top); EN small + below in muted Latin. Never reverse. |
| Voice          | Third person about the customer (组织 / 团队 / 我们). Numbers and named customers do the persuading. |
| Forbidden      | Emoji on slides. `!` `…` `???`. Drop shadows. Isometric clip-art. Stock photo people. Gradient mesh outside listed gradients. |

Two reference precedents: **Apple keynote** (architectural negative space) and **Tesla.com** (full-bleed cinematic single-subject). We are darker and more rigorous than either.

### H5 deck rendering craft

The best decks in this system look like a presentation tool with web-native
surface area. They are not exported PPT screenshots and not generic web pages.

1. **Native DOM first.** Use structured HTML/CSS for UI mocks, diagrams,
   tables, chats, phone screens, pipelines, and data panels. Use raster images
   for photos, product renders, artwork, or replica-mode preservation.
2. **Dark stage, controlled glow.** A slide should get depth from the dark
   canvas, low-opacity radial blooms, hairlines, and type weight. Avoid noisy
   gradients, blur-heavy glass, and decorative blobs.
3. **Semantic accent color.** Blue anchors system / mainline pages; teal
   signals positive metric / growth; orange signals judgment / engine /
   exception; violet / purple signals AI, intelligence, or transformation.
   The mapping is not mandatory, but every accent choice should have intent.
4. **One visual center.** Dense pages need a clear hub: a processor, hero KPI,
   quote, diagram core, UI surface, or center node. If a viewer squints and
   sees only evenly weighted cards, redesign the page.
5. **Living artifacts.** Video, iframe prototypes, animated tabs, chat typing,
   audio waves, and progress fills are allowed when they make a process feel
   live. Motion must explain state or sequence.

---

## 2. Color Palette & Roles

All theme colors lift directly from `theme1.xml` of the .thmx master.

### Backgrounds

| Token        | Hex      | Role |
|--------------|----------|---|
| `--fs-bg-0`  | `#000000`| Default slide background — content / stats / table / process |
| `--fs-bg-1`  | `#04060F`| Alt deep background for product UI mocks |
| `--fs-bg-2`  | `#0A1230`| Cool depth (used in `--fs-grad-hero`) |
| `--fs-bg-3`  | `#1B1F3A`| Cool depth (used in `--fs-grad-section`) |

### Brand accents — **one per slide**

| Token             | Hex      | Role |
|-------------------|----------|---|
| `--fs-blue`       | `#3C7FFF`| **Default cobalt.** First choice for any slide. |
| `--fs-cyan`       | `#24C3FF`| **Inline highlight only** — single keyword inside otherwise white text. Never used as primary slide accent. |
| `--fs-teal`       | `#33D6C0`| Stats / KPI eyebrows. Sibling differentiation. |
| `--fs-purple`     | `#5C3FFB`| Differentiation only. |
| `--fs-violet`     | `#9F6FF1`| Differentiation only. |
| `--fs-orange`     | `#FE7F00`| Differentiation only. Use sparingly — high-attention. |

### Text on dark

| Token            | Value                       | Role |
|------------------|-----------------------------|---|
| `--fs-text`      | `#FFFFFF`                   | Headings, big numbers. |
| `--fs-text-72`   | `rgba(255,255,255,.72)`     | Body / lede on dark. |
| `--fs-text-65`   | `rgba(255,255,255,.65)`     | Card body. |
| `--fs-text-48`   | `rgba(255,255,255,.48)`     | Captions, subtitles in EN. |
| `--fs-text-40`   | `rgba(255,255,255,.40)`     | Footer chrome, source citations. |
| `--fs-text-16`   | `rgba(255,255,255,.16)`     | Hairline accents on text. |

### Lines

| Token            | Value                  | Role |
|------------------|------------------------|---|
| `--fs-hairline`  | `rgba(255,255,255,.10)`| Card borders, footer underline. |
| `--fs-divider`   | `rgba(255,255,255,.20)`| Strong dividers under headers. |

### Gradients

| Token                   | Definition |
|-------------------------|---|
| `--fs-grad-hero`        | `radial-gradient(120% 100% at 0% 0%, #0F1A4A 0%, #060B22 38%, #000 78%)` — Cover & big-stat |
| `--fs-grad-section`     | `radial-gradient(140% 110% at 100% 0%, #1A2256 0%, #050817 50%, #000)` — Section / agenda |
| `--fs-grad-keyline`     | `linear-gradient(90deg, #33D6C0, #3C7FFF 50%, #5C3FFB)` — keyline bars + accent text |
| `--fs-grad-glow-blue`   | `radial-gradient(80% 60% at 50% 50%, rgba(60,127,255,0.22), transparent 60%)` — Quote glow |
| `--fs-grad-close`       | dual radial blooms — purple top-right + blue bottom-left over `#000` — Closing |

### Color rules (must follow)
1. **One brand accent per slide.** Pick one of blue / teal / purple / violet / orange. Cobalt is default. Don't paint heading one accent and subtitle another.
2. **Cyan is reserved** for single-keyword highlight inside white text. Never as primary slide accent.
3. **Never re-tint the Lark logo.** Color tri-petal on dark bg, mono-white over imagery.
4. Differentiating 2–6 sibling items (chart series, comparison columns, feature pills) is the only legitimate reason to use multiple accents on one slide. Even then, label them clearly.

---

## 3. Typography Rules

### Stacks

| Family | CSS variable | Stack |
|---|---|---|
| CJK (primary) | `--fs-font-cjk` | `"方正兰亭黑Pro_GB18030", "FZLanTingHeiPro_GB18030 Light", "Noto Sans SC", "PingFang SC", "Microsoft YaHei", system-ui, sans-serif` |
| Latin / numerals | `--fs-font-latin` | `"Inter", "Helvetica Neue", "Arial", sans-serif` |
| Mono / code | `--fs-font-mono` | `"JetBrains Mono", "SF Mono", "Menlo", monospace` |

> Note: `方正兰亭黑Pro` is the brand face from the .thmx and is licensed.
> Web decks substitute Noto Sans SC / PingFang SC. Mention this in the deck README.

### Hierarchy (sizes assume 1920-px design canvas)

| Role | Size / Weight | Line | Tracking | Family | Color |
|---|---|---|---|---|---|
| Cover title          | **100 / 700** | 1.18 | -0.005em| CJK | `#fff` (master 50pt × 2) |
| Cover subtitle       | **40 / 600**  | 1.40 |  0      | CJK | `#fff` |
| Cover author block   | **30 / 600**  | 1.45 |  0.02em | CJK | `#fff` 0.85 |
| Section title        | **88 / 700**  | 1.18 | -0.005em| CJK | `#fff` (master 44pt × 2) |
| Closing slogan       | **PNG**       | —    | —       | —     | (`lark-slogan.png` master) |
| Quote                | **92 / 600**  | 1.20 |  0      | CJK | `#fff` |
| Image-text title     | **96 / 700**  | 1.10 | -0.005em| CJK | `#fff` |
| **Page header H2**   | **52 / 600**  | 1.10 | -0.005em| CJK | `#fff` (master 26pt × 2; ONE LINE) |
| Agenda TOC number    | **44 / 700**  | 1.10 |  0.01em | Latin | `--fs-accent` |
| Agenda TOC title     | **44 / 600**  | 1.15 | -0.005em| CJK | `#fff` (matches number) |
| Big number (stats)   | **132 / 700** | 1.00 | -0.03em | Latin | `#fff` |
| Big number (hero)    | **240 / 700** | 1.00 | -0.04em | Latin | gradient |
| Chapter numeral      | **160 / 700** | 1.00 | -0.02em | Latin | gradient (master 80pt × 2) |
| Lede                 | **32–36 / 500**| 1.40 | 0      | CJK | `text-72` |
| Body                 | **28 / 500**  | 1.50 |  0      | CJK | `text-72` |
| Card body            | **20 / 500**  | 1.60 |  0      | CJK | `text-65` |
| Stats trend tag      | **20 / 600**  | 1.00 |  0.04em | CJK | `--fs-accent` (NOT Latin/uppercase) |
| Stats label          | **24 / 500**  | 1.40 |  0      | CJK | `text-72` |
| Table thead (`th`)   | **24 / 600**  | 1.30 |  0.02em | CJK | `#fff` (NOT Latin/uppercase) |
| Table tbody (`td`)   | **22 / 500**  | 1.45 |  0      | CJK | `text-72` |
| EN subtitle (cover)  | **22–28 / 500**| 1.30| 0.02em | Latin | `text-48` |
| Eyebrow              | **14 / 600**  | 1.00 |  0.18em UPPER | Latin | `--fs-accent` |
| Footer / page no     | **16 / 500**  | 1.00 |  0.08em | Latin | `text-40` |
| Caption / source     | **14–16 / 500**| 1.40| 0.04–.06em | Latin | `text-40` |
| **Floor**            | 14 px (page chrome only). **Body text never < 22 px. CJK never below 20 px.** |||| |

### Casing & punctuation
- Latin headings: **Sentence case**. Title Case only for product names (`Lark Suite`, `Lark Base`).
- All-caps Latin reserved for eyebrows / metadata, always with `letter-spacing: 0.14–0.18em`.
- CJK punctuation: `「」 《》 。 ，` (full-width). EN punctuation: ASCII. Never mix.
- Never use `!`, `…`, `???` on slides.

### Bilingual coexistence
When ZH + EN appear together (cover, section, image-text):
1. ZH on top, larger, full opacity.
2. EN below, ~40% size, `--fs-text-48` opacity.
3. Single em-dash or slash separator: `先进团队的工作方式 / The way advanced teams work`.

---

## 4. Component Stylings

States are listed where applicable.

### Eyebrow
- 18 px / 600 / uppercase / tracked 0.18em / color `--fs-accent`.
- `<div class="eyebrow">CHAPTER 02 / 06</div>`

### Keyline accent bar
- 96 × 3 px / `--fs-grad-keyline` / radius 999 px.
- Anchors section openings, quote, cover.

### Tinted icon tile
- 64×64 (or 48×48 small) / radius 14 px.
- Background `color-mix(in srgb, var(--fs-accent) 14%, transparent)`.
- Border `color-mix(in srgb, var(--fs-accent) 42%, transparent)`.
- Inner SVG inherits `currentColor` = `--fs-accent`.

### Cards on dark
- Background `linear-gradient(180deg, rgba(255,255,255,.04), rgba(255,255,255,0))`.
- Border 1 px `--fs-hairline`.
- Radius `16` px. Padding `36` px. Min-height `400` px.
- Header row: tile (left) + accent number 56 px / 700 / 0.55 opacity (right).
- **No drop shadows.** **No hover scale.** Static.

### Pills / tags
- Radius 999 px. Padding `10–12` × `18` px. Font 18 px / 500.
- Default: ghost = transparent + 1 px `--fs-text-16` border + body text.
- Solid (`.solid`): `--fs-accent` background + white text. **Solid only for closing-page CTAs.**

### Buttons (closing only)
| State    | Style |
|----------|---|
| Primary  | `.pill.solid` — `--fs-accent` bg, white text, with arrow SVG, `padding: 18px 28px`, `font: 600 22px/1`. |
| Ghost    | `.pill` (default ghost) — transparent + 1 px white .30 border. |
| Hover    | `border-color: --fs-divider` for ghost; primary unchanged (decks are static). |
| Disabled | n/a — decks don't have disabled states. |

### Indicator / page no
- Latin 16–18 px / 500, tracked 0.08em, `--fs-text-40`. Pad zero-padded (`01 / 12`).

### Tables
- Header row: 16 px / 600 / Latin / uppercase / tracked 0.18em / `--fs-accent` / underline `--fs-divider`.
- Body cells: 22 px / 500 / CJK / `--fs-text-72` / row underline `--fs-hairline`.
- First column: weight 600 / `#fff` (entity column).

### Charts
- Series colors come from accent set, in this canonical order: `blue → teal → purple → orange → violet → cyan`.
- One eyebrow + accent per chart.
- Gridlines `--fs-text-16`. Axis labels 14 px / 500 / Latin / `--fs-text-48`.
- Annotation arrows: 1 px solid `--fs-text-48` with chevron. **No drop shadow.**

---

## 5. Layout Principles

### Canvas
- **1920 × 1080** (16:9). Fixed pixel design. Scaled to fit by JS via `--fs-scale` on each `.slide`.
- Outer padding: `96` px left/right, `64–90` px top/bottom (`--fs-pad-x`, `--fs-pad-y`).
- Implicit grid: 8 columns, 24 px gutter. Express via `repeat(N, 1fr)` Grid.

### Spacing scale (px on canvas)
`8 · 12 · 16 · 20 · 24 · 32 · 36 · 56 · 64 · 80 · 96 · 128`
Don't introduce other multiples. Aligns to 8-px baseline.

### Six canonical layouts (recipes)
| Code              | When to use |
|-------------------|---|
| `cover`           | First slide. Title + EN subtitle + brand + date. |
| `section`         | Chapter divider between groups of slides. Giant numeral + title. |
| `agenda`          | TOC. 4–8 numbered items in 2 columns. |
| `content-3up`     | Three parallel concepts / capabilities / pillars. |
| `content-2col`    | One narrative + supporting visual / mock / list. |
| `quote`           | Customer quote, executive thesis. Single sentence centered. |
| `stats`           | 4-up KPI row. Big numbers as evidence. |
| `big-stat`        | One hero number + paragraph. |
| `image-text`      | Single full-bleed photo with type bottom-left. |
| `table`           | Comparison or matrix. Up to 6 rows × 5 cols. |
| `timeline`        | Chronological 4–6 milestones. |
| `process`         | 3–6 sequential steps with arrows. |
| `end`             | Closing — title + CTA + contact grid. |

### Inner-container naming (`.stage` is canonical, others are historical aliases)

The body-content container inside each layout has a per-layout name for
historical reasons. Validators (`check_balance`, `check_default_centering`)
accept all of them as equivalent. When writing a NEW layout, prefer `.stage`.

| Layout            | Container class    |
|-------------------|--------------------|
| `content-3up`     | `.grid`            |
| `content-2col`    | `.grid`            |
| `agenda`          | `.toc`             |
| `stats`           | `.grid`            |
| `big-stat`        | `.stage`           |
| `quote`           | `.stack`           |
| `process`         | `.flow`            |
| `timeline`        | `.nodes`           |
| `table`           | `.table-wrap`      |
| `cover`           | `.stage`           |
| `end`             | (no inner; `.slogan` + `.contact` direct children) |
| `image-text`      | `.stage`           |
| (custom layout)   | `.stage` (canonical) |

### Slide chrome (every non-cover slide)
- **Top-right wordmark** (mono on imagery, color on closing top-left). 32 px tall, 0.85 opacity.
- **Footer row** at `bottom: 48px`: brand line on the left, page number `01` on the right. 16 px / 500 / Latin / 0.08em / `--fs-text-40`.
- **Header underline** for content slides: 1 px `--fs-hairline` 32 px below header text.

### Whitespace philosophy
- A slide should have ONE focal element. Body copy supports it; chrome stays out of the way.
- If a slide feels balanced, you have probably under-emphasized. Push the focal element bigger.
- Empty space top-right / top-left around the headline is intentional, not lazy.

### Complex-slide composition

For information-rich slides, choose a composition before choosing decoration:

| Pattern | Use when | Composition rule |
|---------|----------|------------------|
| **Input → processor → output** | Pipeline, AI engine, automation, decision workflow | Inputs on left, processor visually heavier in center, outputs on right. Connectors are information paths, not ornament. |
| **Center hub → branches** | Org collaboration, capability maps, ecosystem views | Put the hub at the visual center; branch weight decreases outward. Keep labels short and aligned to the branch direction. |
| **UI surface + explanation** | Product feature, workflow demo, dashboard proof | One side is a believable UI mock; the other side names why it matters. Do not make both sides equal lists. |
| **Evidence wall** | Many examples, scripts, personas, customer situations | Make the repeated cards consistent, then give A-tier weight to the remembered phrase / number / avatar / scene marker. |
| **Breath page** | Chapter transitions, thesis, close, quote | One large statement, one keyline or glow, no dense card grid. These pages reset audience attention. |

Every dense slide must name its entry point in the design pass. Typical entry
points: hero number, engine block, active tab, central node, strongest quote,
or live prototype viewport.

---

## 6. Depth & Elevation

There is **no elevation system** for slides. Decks rely on contrast and type weight, not shadows.

| Surface          | Treatment |
|------------------|---|
| Slide background | Solid `#000` or one of the listed gradients. |
| Card on dark     | 4–6% white fill + 10% white hairline. **No shadow.** |
| Pill             | Transparent + 16% white hairline. **No shadow.** |
| Modal / overlay  | Not used on slides. |

Allowed shadow exceptions (these wrappers exist to mock real product UI
chrome where shadows are part of the metaphor — they're NOT slide content):
- `.ui-window`, `.ui-browser` — UI mock window panels
- `.phone-frame`, `.desktop-frame` — prototype iframe wrappers
- `.deck-controls` (the deck's own bottom control pill)

Slide content cards (`.card`, `.boundary-no/.yes`, `.verdict-card`,
`.evolution-chip`, etc.) carry no shadow. Contrast and hairline borders
do the work.

---

## 7. Do's and Don'ts

### Do
- Use exactly **one** brand accent per slide.
- Choose a concrete render form for every content slide: UI mock, system
  diagram, data panel, video/prototype, evidence wall, or sparse thesis page.
- Give dense slides a visible entry point and a single hub.
- Put **ZH on top, EN below** in muted Latin.
- Keep body copy ≥ 24 px, page chrome ≥ 16 px, headers ≥ 64 px.
- Use real inline SVG icons in Lucide style: 24 px viewBox, `stroke: currentColor`, stroke-width 2, round caps/joins.
- Use the listed gradients verbatim. Don't tweak hex stops.
- Number cards / steps / chapters with Latin numerals zero-padded (`01`, `02`, …).
- Render the keyline bar (96 × 3 px gradient) on cover, section, quote — it's a brand signature.
- Add `data-screen-label="01 Cover"` / `02 Section` etc. on every slide for tooling.

### Don't
- ❌ Turn complex content into only equal-weight cards and bullets.
- ❌ Add motion just to make a page feel "premium"; motion must show state,
  sequence, or media entering/leaving.
- ❌ Use emoji as icons or inline. Ever.
- ❌ Use `!`, `…`, `???` in slide copy.
- ❌ Mix two brand accents on one slide except for sibling differentiation (chart series / comparison columns / feature pills).
- ❌ Stretch or re-tint the 飞书 logo. Don't redraw the tri-petal mark.
- ❌ Apply drop shadows or backdrop-blur to slide content.
- ❌ Use Title Case in Latin headings (Sentence case only).
- ❌ Shrink body copy below 24 px to fit content. Cut content instead.
- ❌ Mix CJK and ASCII punctuation (`，` vs `,`).
- ❌ Use stock-photo people, isometric clip-art, hand-drawn illustration, or animated GIFs.
- ❌ Use unicode glyphs `→ ✓ ✗` as icons — write a real SVG instead.

### Brand 规范 (mandatory rules — auto-enforced by CSS)

These are recurring corrections that we've folded into the CSS as defenses.
Even if the markup is wrong, the CSS prevents the wrong thing from rendering.
But authors should still write the markup right.

1. **Logo is always the colored tri-petal + 飞书 wordmark.** Never mono-white,
   never re-tinted, never redrawn. The mono-white variant exists only as a
   fallback for over-imagery cases — do not use it on dark slides.
   - Cover & End: 235 × 74 (top-left)
   - Every other slide: 160 × 50 (top-right)

2. **Page-header titles are single-line.** No `<br>`, no soft-wrap.
   - Font: 52 px / 600 / CJK / line-height 1.1
   - Position: top: 61 (vertically aligned with logo center), left: 73
   - The optional `.eyebrow` goes BELOW the title as a 14 px tag.
   - If the title is too long for one line, **shorten the title**, don't shrink the font.
   - Hero 2-line titles are reserved for `cover` and `image-text` layouts only.

3. **Agenda numbers and item titles share the same font size.** Both 44 px /
   matching weights (number 700, title 600). The agenda is NOT a form — items
   are large, generously spaced, and sit on a shared baseline.

4. **Stats `.trend` tags ≥ 20 px CJK.** Table `<th>` headers ≥ 24 px CJK / 600 / white.
   Don't force CJK glyphs through Latin-uppercase styling — the fallback render
   makes them visually smaller and unreadable at projection distance.

5. **Atmospheric backgrounds are sticky.** When migrating an existing slide
   into a standard layout, its distinctive radial glows, photographic
   backgrounds, brand gradients, aurora, or film grain MUST be preserved via
   a `data-decor` attribute on the `.slide`. Decor is orthogonal to layout —
   layout = structure, decor = tone. Never silently strip atmospheric content;
   the user notices immediately and the redesign feels sterile. See SKILL.md
   for the full token list (violet-glow / mix-glow / aurora / grain / etc.).

---

## 8. Responsive Behavior

The deck supports **two render modes** in a single HTML file. JS auto-detects and the user can toggle.

| Mode          | Trigger                                  | Behavior |
|---------------|------------------------------------------|---|
| **`present`** | Default on viewport > 900 px wide        | One slide visible, fills viewport via scale-to-fit. ←/→/PgUp/PgDn/Space/Home/End to navigate. Wheel scroll ± 1. Touch swipe ± 1. URL hash `#3` syncs current slide. Indicator and mode toggle in corners. |
| **`scroll`**  | Default on viewport ≤ 900 px wide. Also reachable by toggle button or `?mode=scroll`. | All `.slide-frame` elements stack vertically with 12 px gap, each at 16:9 aspect filling container width. Tap a frame to enter present mode for that slide. Smooth-scroll to selection. |

### Motion rules

Motion is part of rendering quality, but it is never decorative filler.

- **Entrance reveal**: allowed globally; keep it subtle (opacity + small
  translate). Do not stagger so slowly that the presenter waits for content.
- **State loops**: use for active tabs, voice waves, typing dots, progress
  fills, live dashboards, and process demos. The loop must point to the current
  state or next action.
- **Control honesty**: if a slide draws tabs or segmented controls, they must
  switch visible state via the deck `data-tab-group` / `data-tab-target` /
  `data-tab-panel` contract, or be marked `data-static-tabs` with an explicit
  reason. Static tabs that look clickable are treated as unfinished prototypes.
- **Sequence highlights**: use when a viewer should follow steps in order. One
  active highlight at a time; inactive items should remain readable.
- **Media lifecycle**: videos and audio-like visuals should restart on slide
  enter and pause on leave. Decorative video stays muted; content video may
  attempt sound only after a user gesture.
- **Reduced motion**: custom raw slides with non-trivial loops must include a
  `prefers-reduced-motion: reduce` path that disables or simplifies animation.
- **Do not animate**: background glows, logos, ordinary cards, and decorative
  icons unless the movement communicates state.

### Sizing & scale
- Design canvas is fixed 1920 × 1080. Each slide is `position: absolute; width: 1920px; height: 1080px` and is transformed by `transform: scale(var(--fs-scale))`.
- JS attaches a `ResizeObserver` to each `.slide-frame` and recomputes `--fs-scale = min(frame.clientWidth / 1920, frame.clientHeight / 1080)`.
- Mobile scroll mode → frame width = container width (≤ 1280 px max), aspect-ratio 16/9, scale ≈ width / 1920.

### Touch targets
- The mode-toggle button and indicator are 44 px+ tall on actual rendered output. The slide content itself is non-interactive on phones (it's a deck, not a form).

### Present-mode deck chrome (mandatory in `present` mode)

When `data-mode="present"`, the deck always renders the following chrome around
the slide. It's built by `feishu-deck.js` automatically — do not author it
per-deck. But know it exists, because every规范 below is hard-required:

| Element                | Position             | Content                            | Behavior |
|------------------------|----------------------|------------------------------------|---|
| **Top progress bar**   | `top: 0; left/right: 0; height: 3px` | empty track + `.bar` fill | Bar uses `--fs-grad-keyline`. Width = `(currentIdx+1)/total × 100%`. 320 ms cubic-bezier transition. Only visible in present mode. |
| **Mode toggle**        | top-right (`right: 24; top: 20`) | "演示模式" / "退出演示" | Clicking it ALSO requests browser fullscreen via `requestFullscreen()`. Clicking "退出演示" exits both fullscreen and present mode. |
| **Bottom control bar** | bottom-center (`bottom: 24; left: 50% translateX(-50%)`) | `[‹] [01 / 12] [›] | [⛶]` | Glassmorphism pill (`rgba(8,12,24,.55)` + 10% border + 14px backdrop-blur). Prev/next disabled at endpoints. Page indicator is 14px Latin 600 #fff. Vertical hairline separator before fullscreen icon. Icon swaps to "exit" glyph when fullscreen is active. |
| **Nav hint**           | bottom-left (`left: 24; bottom: 32`) | "← →   翻页  ·  F 全屏" | 12 px Latin 500 / `text-40`. Pointer-events: none. Hidden on mobile ≤ 640 px. |

**Why fullscreen is automatic for 演示模式.** Without it, the present-mode
slide letterboxes inside the browser window — the user sees URL bar, bookmarks,
window chrome, and the slide doesn't feel like "presenting". Browsers require a
user gesture for `requestFullscreen()`, and the click on the 演示模式 button
satisfies that. If the call is denied (browser policy, iframe, mobile Safari
edge case), the deck still works — it's just letterboxed in-window.

**Why prev/next + page-no live in one bottom pill.** Clicking the slide is
ambiguous (could be content). Side-floating arrows are easy to miss. A center
pill is the universal pattern — Google Slides, Keynote, Reveal, every video
player. Keyboard ←/→ remains the primary nav for power users; the pill is for
the audience clicking on a phone.

**fit() must run after `fullscreenchange`.** When the document enters or exits
fullscreen, the visible viewport changes (browser chrome appears/disappears).
The runtime listens for `fullscreenchange` and `webkitfullscreenchange` and
re-runs `scaleFrame()` on every slide.

**Defensive timing — fit on the second rAF.** Some browsers fire
`fullscreenchange` before the new viewport size has propagated to layout. If
we measure `clientWidth/Height` synchronously in the handler, we get stale
values, and the slide ends up under- or over-scaled. The runtime therefore
schedules `refit()` via `requestAnimationFrame(requestAnimationFrame(refit))`
plus a 120 ms `setTimeout` belt-and-suspenders. Without this, fullscreen
transitions look "wrong ratio for half a second" before snapping into place.

**Centering pattern — absolute + negative margins, not grid.** Present mode
positions the slide via `position: absolute; left: 50%; top: 50%; margin:
-540px 0 0 -960px;` and scales with `transform-origin: center center`. We do
NOT use `display: grid; place-items: center` here, because grid auto-track
sizing combined with `overflow: hidden` on the frame and a CSS transform on
the child can clip layout-overflowing portions of the pre-transform layout
box on certain WebKit/Blink versions. Absolute centering with negative
half-margins anchors the slide's center to the viewport center deterministically,
and the transform scales the visual to fit — there's no layout-vs-transform
conflict for the clip rect to argue with.

**Auto-idle fade — chrome must not permanently cover slide content.** In a
true 16:9 fullscreen (1920×1080 monitor, scale = 1), the slide fills the
viewport exactly — there's no letterbox bar to hide chrome in. The slide's
own footer at slide y=1032 lands at viewport y=1032, right where the bottom
control pill sits. To resolve this without removing chrome entirely, the
runtime adds `.deck-ui.is-idle` after 2.5 s of no user input (mousemove /
keydown / wheel / touchstart / click), which fades the bottom pill, mode
toggle, and nav hint to `opacity: 0` and the top progress bar to 35%. Any
user input restores them immediately. Hovering directly over the chrome
cancels the fade locally. This matches the YouTube/Keynote pattern.

**Use both 100vh and 100dvh.** iOS Safari's URL bar appears/disappears, and
`100vh` returns the larger fixed value, which causes the bottom of the slide
to sit under the URL bar. The deck declares `height: 100vh; height: 100dvh;`
so modern browsers use the dynamic value while older ones fall back gracefully.

### Mobile-specific niceties
- `<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">`
- iOS Safari address bar tolerance: present mode uses `100vh` plus `100dvh` fallback — see `feishu-deck.css`.
- Frames in scroll mode get a faint `box-shadow: 0 8px 32px rgba(0,0,0,.45)` and 6 px radius **for in-list framing only** — this is the single allowed "elevation" on mobile.

### Print / export
- `@media print` hides the deck-ui chrome and forces every `.slide-frame` to a new page — `Cmd+P → Save as PDF` produces a usable handout.

---

## 9. Agent Prompt Guide

Drop this block into the system prompt when asking an LLM to extend or generate a slide.

```
You are producing a slide for the deck-renderer design system. Use ONLY the
tokens defined in DESIGN.md / feishu-deck.css. Hard rules:

  COLORS  (CSS variables only)
    bg          var(--fs-bg-0) / --fs-bg-1 / --fs-bg-2 / --fs-bg-3
    accent      ONE of --fs-blue (default) / --fs-teal / --fs-purple
                       / --fs-violet / --fs-orange  (cyan = inline word only)
    text        --fs-text / --fs-text-72 / --fs-text-65
                / --fs-text-48 / --fs-text-40 / --fs-text-16
    line        --fs-hairline / --fs-divider
    gradient    --fs-grad-hero / --fs-grad-section / --fs-grad-keyline
                / --fs-grad-glow-blue / --fs-grad-close

  TYPE
    cjk = var(--fs-font-cjk)   latin = var(--fs-font-latin)
    Cover title 152/700  ·  Section 128/700  ·  Quote 92/600
    Big stat 132/700  ·  Header 64/600  ·  Lede 32/500  ·  Body 28/500
    Card body 20/500  ·  Eyebrow 18/600 uppercase tracked 0.18em
    Footer 16/500 tracked 0.08em  ·  Floor 18px (corner only)

  STRUCTURE
    Wrap slide in:
      <div class="slide-frame">
        <div class="slide" data-layout="LAYOUT" data-screen-label="NN Title">
          ... (use markup from templates/slide-recipes.html for that LAYOUT) ...
        </div>
      </div>

  CHROME
    Every non-cover slide has a top-right .wordmark and a bottom .footer
    (brand line · page no.). Cover and end use top-left wordmark.

  CHECKLIST before delivery (run all 11 items)
    [ ] Slide is 1920×1080.
    [ ] One accent. Cyan only for inline word.
    [ ] ZH ≥ EN; ZH on top.
    [ ] No emoji, no '!' '…' '???'.
    [ ] Body ≥ 24 px; chrome ≥ 16 px.
    [ ] Wordmark + footer present (non-cover); data-screen-label set.
    [ ] All icons inline SVG, stroke:currentColor, no unicode glyphs.
    [ ] All hex values come from --fs-* tokens (grep for stray '#').
    [ ] Punctuation full-width in CJK, ASCII in EN, never mixed.
    [ ] No drop shadows on slide content.
    [ ] Lark logo never re-tinted.

If content is missing, use 〔TODO〕 placeholders that are easy to find later.
```

### Ready-to-use prompts

> "Produce a single deck-renderer slide using `data-layout=\"content-3up\"`. Title 「先进团队的工作方式」 / 'The way advanced teams work'. Three pillars: 即时同步、共识对齐、闭环交付. Accent: blue. Eyebrow: CHAPTER 02 / 06. No emoji. No drop shadow. Render the wordmark top-right and the footer with page no. 04. Output only HTML — no Markdown, no preamble."

> "Produce a `data-layout=\"stats\"` slide. KPIs: 30万人组织 (秒级触达 3 秒)、98% 已读率、3.2x ROI、< 60 秒 决策时长. Accent: teal. Eyebrow: BUSINESS IMPACT. Footnote: 数据样本 12 家中国头部企业 · 2024 Q3-Q4. Output only HTML."
