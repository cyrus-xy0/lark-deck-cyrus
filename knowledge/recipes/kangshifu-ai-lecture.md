# Kangshifu AI Lecture Reference Recipe

Source: https://fuqiang.github.io/feishusolution/Kangshifu-AI-Lecture/index.html

This recipe records what Cyrus should learn from the Kangshifu consumer-goods
AI lecture deck. Use it for consumer goods, retail, food and beverage, channel
sales, brand growth, executive AI lecture, and "AI changes business logic"
decks.

## Core Lesson

The reference deck works because it does not sell features first. It turns AI
into a business argument:

- Start with a contradiction the audience already feels: many companies have AI,
  but the business result does not move.
- Compress the full story into one memorable formula or operating equation.
- Move from abstract capability to named work moments: a new product stuck
  across eight departments, a sales representative's day, a channel visit, a
  live taste radar, or a report flywheel.
- Treat UI surfaces as proof. Dashboards, phone chats, radar panels, workflow
  maps, and live prototypes are evidence containers, not decoration.
- Close by abstracting the case into a management model: physical carrier shift,
  flywheel, four reversals, and self-evolving process.

## Required Narrative Pattern

Planner output for similar decks must contain these layers:

- **Opening conflict:** what the customer already tried, why it looked active,
  and why it did not create business movement.
- **Formula:** one equation or compact operating model that the audience can
  repeat after the meeting.
- **Three-part growth logic:** consumer understanding depth, decision response
  speed, and experience compound sharing, or a user-approved equivalent.
- **Business scene:** who is working, which input is stuck, which system or
  team owns it, and what decision is delayed.
- **UI proof:** a concrete visual work surface for the key claim: dashboard,
  phone/chat mock, review panel, radar, map, workflow, or iframe prototype.
- **Human role change:** the person moves from chasing, remembering, and making
  files into judging, coaching, and exception handling.
- **Model close:** the last section must translate the case into a reusable
  management language rather than ending with a feature list.

## Reusable Page Patterns

Use these patterns as first-class page candidates before falling back to generic
cards.

| Pattern | Job | Preferred DeckJSON path |
|---|---|---|
| 双引语冲突开场 | Let the audience hear its own failed AI adoption story. | `content/blocks` + `pullquote` or `raw` when two large quote cards are needed |
| 增长公式页 | Compress the lecture into a memorable equation. | `content/blocks` + `formula-band` |
| 多部门卡点矩阵 | Show why a workflow is slow without blaming one team. | `content/blocks` + `friction-grid` |
| 产品 UI 证据页 | Make the AI capability feel runnable. | `iframe-embed`, `phone-iframe`, `mockup-card`, or `raw` dashboard |
| 角色一天知识地图 | Turn invisible expertise into a protagonist story. | `content/blocks`, `table`, or `raw` when the day timeline is dense |
| 执行飞轮 | Show how one execution feeds the next execution. | `content/blocks` + `flywheel-loop` |
| 四个反转 | Convert the case into a reusable management model. | `content/blocks` + `verdict-grid` / `principle-band` / `raw` |

## Visual Quality Bar

For consumer AI lecture decks:

- At least 40% of body slides should have a concrete visual container.
- At least three body slides should use UI/work-surface proof, not only cards.
- No more than three consecutive body slides may use generic 3up, matrix, table,
  or process layouts without a quote, section, hero, or prototype breathing page.
- Every section should contain at least one "business scene -> AI mechanism ->
  human role change -> value proof or evidence gap" page.
- Motion must explain sequence or state: formula assembly, tab switching, wave
  state, table-cell reveal, orbit/flywheel flow, media restart, or iframe-native
  interaction.

## Authoring Rules

- Do not write "AI empowers growth" as a page idea. Write what gets faster,
  who changes behavior, and what business artifact becomes reusable.
- Do not fabricate consumer research, sales data, ROI, or named quotes. Mark
  missing evidence as a fact gap.
- Use concrete nouns: desk, system, department, route, SKU, channel, meeting,
  visit, report, sample, SOP, phone, radar, and map.
- The strongest pages should have one remembered sentence. If a page cannot be
  retold in one sentence, split or reframe it.
- If a control looks clickable, make it actually interactive in an iframe or
  state loop, or explicitly label it as a static mock in the material plan.

## Renderer Mapping

The first reusable renderer blocks for this recipe are:

- `formula-band`: equation-style strategic model.
- `friction-grid`: four-to-eight stakeholder/system pain cards.
- `flywheel-loop`: circular execution loop with a center thesis and optional
  closing line.

These blocks are deliberately small. More bespoke UI pages should still use
`iframe-embed` or a scoped `raw` slide until a pattern repeats across decks.

## Acceptance Checklist

Before rendering or publishing:

- Can the presenter open with a real contradiction instead of a feature claim?
- Does the deck have a formula or operating model by slide 3?
- Are the most important claims backed by visible UI/work-surface proof?
- Does every solution page name the role, input, AI action, human decision, and
  output?
- Does the closing section elevate the case into a reusable management model?
- Did the visual audit run, especially for dense UI and matrix pages?
