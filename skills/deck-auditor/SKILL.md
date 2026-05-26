---
name: deck-auditor
description: |
  Quality acceptance skill for lark-deck-cyrus. Use after deck-renderer has
  produced a deck, or when the user asks whether a generated deck is ready to
  present, share, publish, enter the slide library, or when the user asks
  "审一下/检查一下/看看哪里不合规" for an existing HTML deck. It runs and
  interprets validator, screenshot, gate, delivery-package, and talk-readiness
  checks, then routes required fixes back to deck-planner or deck-renderer.
---

# deck-auditor

目标:判断一份已经生成的 pitch deck 是否达到“可以讲、可以发、可以继续迭代或可以入库”的质量门槛。
这个 skill 不负责生成页面,也不负责模拟客户会议;它负责验收、归因和分流。

## 入口边界

- 用户要“能不能发 / 能不能讲 / 能不能入库 / 哪里不合规”:使用本 skill。
- 用户只明确要求底层技术规则输出:调用 `deck-renderer` 的 check-only 工具,但结论仍可由本 skill 解释。
- 用户要求直接修改页面或重新生成:先验收并归因,再把修复路由到 `deck-renderer` 或 `deck-planner`。

## 输入

优先读取这些 artifact:

- `deck.json`: 结构化源,用于检查页序、slide key、layout、文案和资产引用。
- `index.html` 或交付命名 HTML: 用于静态 validator、视觉检查和真实浏览器预览。
- `texts.md`: 用于检查可编辑文本回路。
- `FEEDBACK.md`: 用于检查生成过程中的缺口、fallback 和未解决问题。
- `validation-report.md` / `validator-report.md`: 已有校验报告。
- `assets-manifest.yaml`: 用于检查素材引用、来源和交付完整性。

## 验收维度

1. **结构完整**
   - 是否有稳定 slide key、合理页序、明确 layout、可追溯 source artifact。
   - 是否保留可编辑入口和必要 sidecar 文件。

2. **视觉和可读性**
   - 是否通过静态 validator。
   - 是否需要 screenshot / visual audit 检查溢出、遮挡、字号、对齐和投影可读性。
   - 是否满足客户现场展示的最低可读标准。

3. **叙事可讲**
   - 开场是否说明为什么现在必须解决。
   - 每页重点是否清楚,是否承接上一页。
   - 结尾是否能推动下一步决策。
   - 如果问题来自叙事、主张或页序,必须回到 `deck-planner`。

4. **素材和证据纪律**
   - 素材是否存在、可访问、来源清楚。
   - 客户事实、数字、案例、引语是否有来源或明确标注为假设。
   - 缺素材或缺证据时,不能让 renderer 硬补虚构内容。

5. **交付和入库门槛**
   - 本地 HTML、预览链接、可编辑包是否齐全。
   - 需要入库时,使用 gate 模式检查复用质量。
   - 入库判断必须分两层:知识库候选服务 `deck-planner` 的“讲什么”;素材库候选服务 `deck-renderer` 的“怎么呈现”。
   - 同一页可以只适合进入知识库、只适合进入素材库、两者都适合,或两者都不适合。
   - 入库失败要给出具体修复项,不是只说“不合格”。

## 推荐命令

`deck-auditor` 可以调用 `deck-renderer` 提供的底层检查命令,但验收结论归
`deck-auditor`。不要让 renderer 的 PASS/FAIL 直接等同于“可交付”。

普通交付验收:

```bash
bash skills/deck-renderer/assets/check-only.sh path/to/deck.html --strict --visual --report path/to/audit-report.md
```

Slide Library 入库验收:

```bash
bash skills/deck-renderer/assets/check-only.sh path/to/deck.html --gate ingest --report path/to/ingest-gate-report.md
```

结构化 DeckJSON 校验:

```bash
python3 skills/deck-renderer/deck-json/validate-deck.py path/to/deck.json
```

## 输出

默认输出一份验收结论,包含:

- `verdict`: `pass` / `revise-before-share` / `rerender-required` / `replan-required`。
- `blockers`: 交付前必须修的问题。
- `warnings`: 可以后续优化但不阻断的问题。
- `routing`: 每个问题应该回到哪个 skill:
  - `deck-planner`: 叙事主线、每页重点、关键 idea、讲法、证据策略。
  - `deck-renderer`: DeckJSON、layout、视觉、HTML、素材落地、交付包。
  - `pitch-simulator`: 客户反应、异议地图、讲稿和预演后改稿建议。
- `acceptance_summary`: 面向用户的简短验收摘要。
- `reuse_assessment`: 入库复用判断,至少包含:
  - `knowledge_candidate`: 是否适合作为 planner 的场景、主张、证据、讲法素材。
  - `presentation_candidate`: 是否适合作为 renderer 的 layout、DeckJSON、视觉或素材片段。

## 硬规则

- 不直接改 deck;只输出验收结论和分流建议。
- 不把 validator PASS 等同于“客户一定能听懂”;必须检查可讲性。
- 不把预演结果写成真实客户反馈;客户反应模拟交给 `pitch-simulator`。
- 不因赶时间跳过 blocker;如需带风险交付,必须明确风险和用户确认。
