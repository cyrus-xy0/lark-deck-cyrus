---
name: lark-deck-cyrus
description: |
  End-to-end controller for Cyrus/Lark/Feishu-style H5 pitch decks. Use when
  the user wants to turn a business need, customer brief, sales idea, raw
  materials, or proposal direction into a talk-ready deck. It routes and
  coordinates requirement clarification, narrative planning, DeckJSON/HTML
  rendering, quality acceptance, pitch rehearsal, user-confirmed iteration, and
  final delivery across deck-planner, deck-renderer, deck-auditor, and
  pitch-simulator.
---

# lark-deck-cyrus

目标:把一个初始需求变成客户现场可以直接讲的 pitch deck。
这个 skill 是总控入口,负责判断当前应该调用哪个子 skill,并维护从需求到交付的上下文闭环。

## 入口判断

先判断用户是在要哪一段:

- 端到端:从 brief / 客户需求 / 销售想法开始,需要最终可讲 deck。继续使用本总控。
- 只要规划:用户明确要大纲、讲法、每页重点。路由到 `deck-planner`。
- 只要生产:用户已有 outline / deck.json / HTML,要生成、改稿、打包。路由到 `deck-renderer`。
- 只要验收:用户问是否合格、能否分享、能否入库、哪里不合规。路由到 `deck-auditor`。
- 只要预演:用户问客户会怎么反应、怎么讲、会被问什么。路由到 `pitch-simulator`。

如果请求横跨多段或用户只说“做一份 deck”,留在本总控,按标准工作流推进。

## 子 skill 分工

- `deck-planner`: 负责讲什么、每页讲什么、重点是什么、关键 idea 是什么、应该怎么讲。
- `deck-renderer`: 根据 `deck-planner` 生成的规划生产 DeckJSON,并渲染成可编辑、可交付的 HTML deck。
- `deck-auditor`: 对生成后的 deck 做质量验收,覆盖 validator、screenshot、gate、交付物完整性和可讲性检查。
- `pitch-simulator`: 模拟客户看到 deck 后的反应,输出异议地图、讲法建议和改稿队列。

## 标准工作流

1. **需求澄清**
   - 如果用户明确说 `lark-deck-cyrus`,直接使用本总控。
   - 先判断用户要向谁讲、希望对方做什么决定、当前已有多少事实/素材、最终交付形态是什么。
   - 信息不足时,优先提出少量关键澄清问题;如果可以合理假设,先记录假设并继续推进。

2. **规划讲法**
   - 调用 `deck-planner`。
   - 输出必须说明整套 deck 的主线、每页职责、页级重点、关键 idea、建议讲法、证据缺口和素材需求。
   - 规划不是排版草稿,而是后续生产、验收、预演和迭代的事实源。

3. **生成和渲染**
   - 调用 `deck-renderer`。
   - `deck-renderer` 只负责把已确认规划转成 DeckJSON,再生产 HTML deck、可编辑文本和交付包。
   - 如果生产时发现规划无法落地,把原因写回反馈,再由总控决定是否回到 `deck-planner`。

4. **质量验收**
   - 调用 `deck-auditor`。
   - 验收要判断 deck 是否完整、可读、可讲、可交付,并把问题归类为:必须重渲染、需要改规划、可以后续优化。
   - 未通过验收时,总控根据问题类型回到 `deck-planner` 或 `deck-renderer`。

5. **预演和改稿**
   - 调用 `pitch-simulator`。
   - 预演结果是 scenario forecast,不是实际客户研究。
   - `pitch-simulator` 输出的 revision queue 只作为建议;必须等用户确认后,才能作为上下文重新输入 `deck-planner` 和 `deck-renderer` 进入下一轮迭代。

6. **最终交付**
   - 最终状态应是一份用户可以直接拿去讲的 pitch deck。
   - 交付时说明当前版本、编辑入口、验收结果、预演摘要和仍需用户确认的素材/事实缺口。

## 关键约束

- 新安装/注册时使用这些 skill 名:
  - `lark-deck-cyrus`
  - `deck-planner`
  - `deck-renderer`
  - `deck-auditor`
  - `pitch-simulator`
- `lark-deck-cyrus` 是总控 skill,不直接承担具体生产、验收或预演实现。
- 当前只有四个子 skill:`deck-planner`、`deck-renderer`、`deck-auditor`、`pitch-simulator`。
- 用户确认是迭代分界线:预演反馈、验收建议或 agent 判断都不能自动覆盖上一版规划。
