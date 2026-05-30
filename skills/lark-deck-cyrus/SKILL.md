---
name: lark-deck-cyrus
description: |
  End-to-end controller for Cyrus/Lark/Feishu-style H5 pitch decks. Use when
  the user asks for 飞书风格 PPT, Lark deck, H5 deck, 16:9 网页演示,
  用 HTML 模仿 PPT, 汇报材料, 客户提案, sales pitch, or when they want to
  convert/check/edit/package a PPT/PDF/HTML/source brief into a talk-ready
  Feishu / Lark-style deckhtml. Cyrus coordinates requirement clarification,
  narrative planning, upload recognition, DeckJSON/HTML rendering, quality
  acceptance, pitch rehearsal, cloud ingestion, user-confirmed iteration, and
  final delivery across upload-parser, deck-planner, deck-renderer,
  deck-auditor, pitch-simulator, and deck-ingestor. The visual style, layout
  discipline, generation gates, check-only behavior, and delivery contract
  remain the feishu-deck-h5 standard.
---

# lark-deck-cyrus

目标:把一个初始需求变成客户现场可以直接讲的飞书 / Lark 风格 H5 pitch deck。
这个 skill 是总控入口,负责判断当前应该调用哪个子 skill,并维护从需求到交付的上下文闭环。

**原则:**Cyrus 是结构化工作流升级,不是新视觉体系。凡是涉及 H5 deck 的外观、布局、字号、调色板、DeckJSON、HTML、校验、交付物和编辑回路,以 `deck-renderer` 中继承自 `feishu-deck-h5` 的规则为准。Cyrus 的 parser / planner / auditor / simulator / ingestor 只增强“素材怎么拆、讲什么、能不能交付、客户会怎么反应、如何沉淀复用”,不能覆盖 H5 已定义的风格和生产纪律。

**2026-05-30 renderer sync:**总控必须认得 renderer 新增的三类生产能力:
`chart/bar|line|donut` 用于确定性数据图表;`lifted` + `assets/lift-slides.py`
用于原生拼接母系统 slide;`assets/reskin.sh` 用于外部 HTML 的机械换肤。
这些能力都属于 renderer 生产层,不得绕过 planner 的 outline 确认、auditor
验收或 cyrus 的素材/入库链路。

## 入口判断

先判断用户是在要哪一段:

- 端到端:从 brief / 客户需求 / 销售想法开始,需要最终可讲 deck。继续使用本总控。
- 只要规划:用户明确要大纲、讲法、每页重点。路由到 `deck-planner`,但进入生产前仍必须回到本总控的 H5 生成流程。
- 只要解析上传物:用户给出 PDF / PPT / HTML / 图片 / 飞书文档等素材,需要拆解内容。路由到 `upload-parser`。
- 只要生产:用户已有 outline / deck.json / 素材解析结果,要生成、改稿、打包。路由到 `deck-renderer`,并遵守 H5 的 MODE SELECTION、PREFLIGHT、DESIGN-FIRST、DeckJSON-first 和 validator gate。
- 只要验收:用户问是否合格、能否分享、能否入库、哪里不合规。路由到 `deck-auditor`。auditor 内部完成 H5 CHECK-ONLY 标准检查,不要把底层 check-only 作为用户可见路径单独拎出来。
- 只要预演:用户问客户会怎么反应、怎么讲、会被问什么。路由到 `pitch-simulator`,预演建议需用户确认后才能进入改稿。
- 只要入库:用户说沉淀、入库、复用、同步到云端库。路由到 `deck-ingestor`,但 HTML deck / slide 入库前必须先有 `deck-auditor` 的通过结论。

如果请求横跨多段或用户只说“做一份 deck”,留在本总控,按下面标准工作流推进。

## 场景路由

Cyrus 对外只保留三个主入口。不要再把“PPT/PDF 转 HTML”、“HTML 改 HTML”、“PPT/PDF 改 HTML”、“飞书文档建 HTML”拆成四条独立执行路线;它们都是第 3 类“brief + 其他素材”的来源变体。

| 场景 | 用户信号 | 路由 |
|---|---|---|
| **1. 上传 HTML deck 做检查 / 入库** | 用户给出一个已有 HTML deck,只问是否合格、能否入库、哪里失败 | `lark-deck-cyrus -> deck-auditor -> deck-ingestor`。auditor 通过才调用 ingestor;失败则返回失败理由和修复路由,不自动改稿 |
| **2. 只有 brief,新建 deckhtml** | 用户只有文字 brief、主题、销售想法、客户提案方向 | `lark-deck-cyrus -> deck-planner -> 用户确认 outline -> deck-renderer -> deck-auditor -> pitch-simulator -> 用户确认是否改稿 -> 用户确认是否入库 -> deck-ingestor`。planner 直接基于知识库和 brief 生成 outline;不要在 planner 后插 simulator |
| **3. brief + 其他素材,新建或改成新 deckhtml** | 用户带 PDF / PPT / HTML / 飞书文档 / 图片 / demo / 素材包,并要求转换、改版、重做或基于材料生成 | `lark-deck-cyrus -> upload-parser -> 临时知识/素材库 -> deck-planner -> 用户确认 outline -> deck-renderer -> deck-auditor -> pitch-simulator -> 用户确认是否改稿 -> 用户确认是否入库 -> deck-ingestor`。先解析上传物并拆成知识层和素材层,在 agent runtime 本轮 run 内保存临时库,再由 planner 结合 brief 生成 outline |

场景 3 中的 PDF / PPT / HTML / 飞书文档处理原则:

- PDF / PPT / 旧 HTML 都先由 `upload-parser` 做 source inventory,不要直接进 renderer。
- 解析结果必须拆成知识层(场景、主张、证据、讲法、风险)和素材层(slide、图片、logo、截图、layout 线索、可复用片段)。
- `deck-planner` 消费 brief + 知识层生成 outline;`deck-renderer` 消费 outline + 素材层生成 H5 deck。
- H5 的 Replica / Rewrite / per-page polish 判断仍由 renderer 执行,但它必须基于 parser 的 inventory 和 planner 的目标。
- 飞书文档不是独立路线;读取后的标题、层级、表格、图片、附件和引用也先进入 parser 输出。

## 两个核心工作过程

### A. H5 生产过程是标准

所有生成或修改 HTML deck 的任务都先按 H5 模式分流:

- **AUDIT-ONLY:**用户给出已有 `.html` 并只要求检查 / validate / 审合规 / 入库判断时,不创建 run、不跑 preflight、不修改原文件。交给 `deck-auditor` 做验收结论;通过后再交给 `deck-ingestor` 入库。
- **GENERATION:**任何新建、改稿、转换、打包、交付都走 H5 生成流程。若输入是纯文本 brief / 主题列表 / Q&A / outline,先做每页设计方案并得到用户确认,再创建文件。

H5 生成流程的硬顺序:

1. **Design-first + outline confirmation:**在 chat / 状态页里先给出 planner outline 和页级设计方案,明确每页角色、唯一重点、A/B/C/D 信息层级、气质冲突、layout path 和素材计划。无论是否低风险,都必须等用户确认当前大纲框架后,才能写 deck.json、生成 HTML 或跑 `new-run.sh`。
2. **PREFLIGHT:**确认本地持久化工作区可写,不能把 deck 生成到临时会话目录。
3. **Workspace:**为本次任务创建 `runs/<timestamp>-<slug>/`,把用户输入、outline、deck.json、HTML、texts.md、FEEDBACK.md 和报告放在同一 run 内。
4. **DeckJSON-first:**默认写 `deck.json` 并用 `deck-json/render-deck.py` 渲染。只有 schema / `raw` / `replica` / `iframe-embed` 都无法表达时,才允许完整 raw HTML。
5. **H5 style fidelity:**使用 H5 已定义的 master、深色电影感、1920x1080、移动端纵向浏览、飞书品牌资产、layout recipe、字号阶梯、调色板和组件工具类。不要因为 Cyrus 的叙事规划另起一套视觉风格。
6. **Editable sidecar:**每页必须保留稳定 `slide key` 和可编辑文本回路,交付物至少能追溯到 `deck.json` / `texts.md` / `FEEDBACK.md`。
7. **Validator gate:**交付前必须通过 H5 validator / visual audit / package 检查;失败时按问题归因回到 renderer 或 planner。

### H5 layout / CSS 对齐口径

Cyrus 上游只能规划 DeckJSON 的 `layout + variant`;不要直接让 planner 输出 CSS 类或手写 HTML layout。renderer 会把 DeckJSON 映射成 H5 运行时的 `data-layout` 与标准 CSS:

| Planner / DeckJSON | H5 HTML `data-layout` | CSS / 设计标准来源 |
|---|---|---|
| `cover` | `cover` | 飞书母版封面,花朵背景,左侧标题,彩色 logo |
| `agenda` | `agenda` | 竖向 pill 目录,默认无 header |
| `section` | `section` | 一级章节页,大号章节数字,右侧蓝色氛围背景 |
| `content` + `3up` | `content-3up` | 三卡片并列,默认垂直居中 |
| `content` + `2col` | `content-2col` | 左文右图 / mock / data-panel |
| `content` + `story-case / blocks / matrix / before-after` | 对应 H5 content variant | 由 `deck-json/templates/*.fragment.html` 和 `extra-layouts.css` 控制 |
| `stats` + `row / hero / waterfall` | `stats` / `big-stat` / waterfall variant | KPI 和数字页,teal 可作为数据强调 |
| `chart` + `bar / line / donut` | `chart` | 确定性图表,renderer 由数值计算 SVG/CSS |
| `flow` + `timeline / process / tree / swim` | `timeline` / `process` / flow variant | 时间线、流程、树、泳道 |
| `logo-wall` / `arch-stack` | 同名 H5 layout | logo 矩阵 / 分层架构 |
| `replica` / `iframe-embed` / `raw` | special layout | PDF 页图复刻、原型嵌入、escape hatch |
| `end` | `end` | 飞书母版封底,slogan 为主 |

所有 CSS、字号阶梯、色值、logo、背景、present-mode UI、mobile scroll、`texts.md`
和 validator 规则都由 `deck-renderer/assets/feishu-deck.css`、`feishu-deck.js`
和 `deck-json/templates/` 承接。Cyrus 不新增 CSS 体系;如需要新视觉模式,先评估是否应该扩展 renderer schema / template,不要在 planner 或 simulator 里绕过 H5。

### B. Cyrus 产品过程只做增强

Cyrus 的结构性工作围绕 H5 生产过程插入:

- `upload-parser` 负责把用户上传的 PDF / PPT / HTML / 飞书文档 / 素材包拆成知识层和素材层,为 planner 与 ingestor 提供结构化输入。
- `deck-planner` 负责把业务 brief + 知识层变成可执行 outline:受众、决策目标、核心冲突、每页职责、关键 idea、讲法、证据缺口、素材计划和候选 layout。
- `deck-renderer` 负责把已确认的 outline / deck.json 落成 H5 标准交付物。它可以调整 planner 的 `layout_candidate`,但调整理由必须是 H5 renderer 更安全或更贴近 H5 风格。
- `deck-auditor` 负责把 H5 validator、截图、visual gate、交付包和可讲性合成验收结论,并把问题路由回 planner 或 renderer。
- `pitch-simulator` 负责模拟客户会议场景、异议地图和讲稿建议。它输出 scenario forecast,不是实际客户研究。
- `deck-ingestor` 负责把通过验收的知识和素材写入云端库,并把可复用整页保存在本地 Slide 候选库,沉淀为后续 planner / renderer 可复用资产。

当 Cyrus 判断和 H5 规则冲突时,优先级如下:

1. H5 的安全和交付硬门槛:PREFLIGHT、run workspace、DeckJSON source of truth、validator、delivery contract。
2. H5 的视觉和布局风格:master、layout recipe、字号、颜色、组件、文本编辑 sidecar。
3. Cyrus 的叙事规划和业务推理。
4. Cyrus 的预演建议和后续优化。

## 子 skill 分工

- `deck-planner`: 负责讲什么、每页讲什么、重点是什么、关键 idea 是什么、应该怎么讲。
- `upload-parser`: 负责上传解析,把 PDF / PPT / HTML / 飞书文档拆成知识层和素材层。
- `deck-renderer`: 根据已确认规划生产 DeckJSON,并按 H5 标准渲染成可编辑、可交付的 HTML deck。
- `deck-auditor`: 对生成后的 deck 做质量验收,覆盖 validator、screenshot、gate、交付物完整性和可讲性检查。
- `pitch-simulator`: 模拟客户看到 deck 后的反应,输出异议地图、讲法建议和改稿队列。
- `deck-ingestor`: 把验收通过的知识和素材写入云端库,把整页 slide 写入本地候选库,并返回可复用记录。

## 标准工作流

1. **场景分流**
   - 先判定是“上传 HTML deck 检查 / 入库”、“只有 brief 新建 deckhtml”,还是“brief + 其他素材新建或改版 deckhtml”。
   - 上传 HTML deck 且只做检查 / 入库时,直接交给 `deck-auditor`;通过才调用 `deck-ingestor`,失败只返回失败理由。
   - 只有 brief 时,跳过 `upload-parser`,直接进入 `deck-planner`。
   - brief + 其他素材时,先调用 `upload-parser`,再进入 `deck-planner`。

2. **需求澄清**
   - 如果用户明确说 `lark-deck-cyrus`,直接使用本总控。
   - 先判断用户要向谁讲、希望对方做什么决定、当前已有多少事实/素材、最终交付形态是什么。
   - 信息不足时,优先提出少量关键澄清问题;如果可以合理假设,先记录假设并继续推进。

3. **上传解析**
   - 仅在用户提供 PDF / PPT / HTML / 飞书文档 / 图片 / demo / 素材包且不是单纯检查 HTML deck 时调用 `upload-parser`。
   - 输出必须拆成知识层和素材层,并保留来源、页码、文件名、置信度和缺口。
   - 总控必须在本轮 run 内创建临时知识/素材库,例如 `input/runtime-library/knowledge.json`、`materials.json`、`slides.json` 和 `manifest.json`;后续 planner、renderer、ingestor 均以这些结构化结果为本轮事实源之一。
   - 不在解析阶段决定最终 deck 结构,也不直接渲染 HTML。

4. **规划讲法**
   - 调用 `deck-planner`。
   - planner 基于知识库、用户 brief 和 upload-parser 的知识层生成 outline;不要在 planner 后先跑 simulator。
   - 输出必须说明整套 deck 的主线、每页职责、页级重点、关键 idea、建议讲法、证据缺口、素材需求和候选 DeckJSON layout。
   - 大纲不能只到“页名 + layout”粒度;每页还必须带 `design_spec`、A/B/C/D 信息层级、`density_budget`、`content_completion` 和 `fact_boundary`,并在用户可见的 `DESIGN_PLAN.md` 中展开为逐页方案表、Q0-Q4、内容补全计划和事实边界。
   - 规划不是排版草稿,而是后续生产、验收、预演和迭代的事实源。
   - 输出后必须暂停,让用户确认目标受众、行业痛点、主张、证据缺口、素材计划和页序;用户确认前不得渲染 deckhtml。

5. **H5 设计确认**
   - 根据 planner outline 和 H5 DESIGN-FIRST POLICY 输出页级设计方案。
   - 明确哪些页用 H5 标准 layout,哪些页需要 `raw` / `replica` / `iframe-embed`,以及为什么。
   - 所有场景都必须等用户确认 outline / 设计框架;即使方案全是标准 schema 且风险低,也只能把假设写入单一用户可见确认稿 `DESIGN_PLAN.md`,不得直接创建最终 deckjson 或生成 HTML。`input/outline.json` 和 `input/runtime-library/source-dossier.json` 是后续脚本消费的机器契约,不要复制成 output 里的用户产物。

6. **生成和渲染**
   - 调用 `deck-renderer`。
   - 先完成 PREFLIGHT 和 run workspace,再用 DeckJSON-first 流程生产 `deck.json`、`index.html`、`texts.md`、`FEEDBACK.md` 和资产包。
   - 渲染前必须把 DeckJSON 中的飞书 / Lark 文件 URL 落成本地资产;不要把 `https://feishu.cn/file/...` 或 `https://*.larkoffice.com/file/...` 直接留在最终 HTML / zip 里。
   - 如果生产时发现规划无法落地,把原因写回反馈,再由总控决定是否回到 `deck-planner`。

7. **质量验收**
   - 调用 `deck-auditor`。
   - 验收要判断 deck 是否完整、可读、可讲、可交付,并把问题归类为:必须重渲染、需要改规划、可以后续优化。
   - 对企业 AI / 制造业 / 高管讲座类 deck,验收不能只看 H5 几何合规;还必须检查是否有场景页、原型/仪表盘/案例等可视锚点,以及是否连续多页落入 3up / matrix / process / table 等通用模板轮换。
   - 未通过验收时,总控根据问题类型回到 `deck-planner` 或 `deck-renderer`。

8. **预演和改稿**
   - deck-auditor 通过后调用 `pitch-simulator`,生成最终对客讲法预演、异议地图和改稿队列。
   - 预演必须发生在云端发布之前。若 high-stakes 制造业 / 企业 AI 场景出现 `request-more-material`、trust 低于门槛或 P0 证据/Deck 改稿项,先暂停发布并回到 planner / renderer;不能把“会被要求补材料”的版本先发出去。
   - 预演报告必须作为用户可见产物返回,不能只作为内部日志存在。
   - 预演结果是 scenario forecast,不是实际客户研究。
   - `pitch-simulator` 输出的 revision queue 只作为建议;必须等用户确认“修改”后,才能作为上下文重新输入 `deck-planner` 并生成新的 outline 给用户确认。用户确认“不用改”时,才进入是否入库确认。

9. **成稿确认、入库和最终交付**
   - deckhtml 生成、验收和预演完成后,必须先让用户确认是否按预演反馈修改;不修改时再询问是否入库。用户确认入库前不得自动入库。
   - deckhtml 通过验收且预演门禁通过后,默认用 `publish-magic-page` 发布为飞书妙笔 / Magic 云端 HTML 页面,并把 `app_url` / `cloud_publish.url` 作为最终交付入口;本地 `index.html` 和 zip 只作为审计、编辑和打包产物。只有用户明确要求“嵌入文档 / 生成飞书文档 / Docx HTML Box”时,才使用 legacy `generate-magic-doc` 路径,并把它标为文档嵌入而不是默认妙笔交付。
   - 用户确认入库后,随后调用 parser 解析最终 deckhtml,再调用 `deck-ingestor` 把通过验收且适合复用的知识和素材写入云端库;Slide Library 暂时不建云端表,整页可选复用单元保存在本地 Slide 候选库。Slide Library 的事实仍由 `素材库 + 知识库` 联合表达“怎么呈现 + 怎么讲”。
   - 默认优先使用云端素材库和知识库,以当前沙箱 agent 的 user 身份访问;不要要求用户配置 token。只有云端不可访问或无权限时才回退本地缓存,并用明文告诉用户“已回退本地”及原因。
   - 如果 simulator 发现必须修改的问题,先等待用户确认是否迭代;不要把未确认的模拟建议直接入库为事实。
   - 最终状态应是一份用户可以直接拿去讲的 H5 pitch deck。
   - 交付时说明当前版本、云端 HTML 页面入口、编辑入口、验收结果、预演摘要、入库结果和仍需用户确认的素材/事实缺口。

## 关键约束

- 新安装/注册时使用这些 skill 名:
  - `lark-deck-cyrus`
  - `deck-planner`
  - `upload-parser`
  - `deck-renderer`
  - `deck-auditor`
  - `pitch-simulator`
  - `deck-ingestor`
- `lark-deck-cyrus` 是总控 skill,不直接承担具体生产、验收或预演实现。
- 机器可读编排入口在 `assets/pipeline.yaml`;它描述调度、schema contract 和交付契约,具体能力仍由各子 skill 和可执行脚本承担。
- 所有子 skill / subagent 交接都必须用 `skills/lark-deck-cyrus/schema/` 下的 JSON Schema 约束。Markdown 只能作为用户解释或报告,不能作为下游 agent 的事实源。
- 总控在每个阶段只传结构化 JSON artifact:
  - `upload-parser -> deck-planner`: `source-dossier.json`, schema `source-dossier.schema.json`。
  - `deck-planner -> deck-renderer`: `outline.json`, schema `deck-outline.schema.json`;不要另建中间 JSON 复制 sections/theme/layout。
  - `deck-renderer -> deck-auditor`: `deck.json` + `index.html`;`deck.json` 走 DeckJSON schema,HTML 走 H5 validator。
  - `deck-auditor -> pitch-simulator`: `audit-report.json` gate + `outline.json` + `deck.json`;不另建 rehearsal request。
  - `pitch-simulator -> deck-ingestor`: `pitch-rehearsal.json` + `audit-report.json` + `deck.json` + 用户确认;不另建 ingestion request。
- 结构化产物落文件后,需要用 `python3 skills/lark-deck-cyrus/schema/validate-contract.py --schema <schema> --instance <json>` 或对应子 skill validator 校验;不要把未校验的自由文本摘要传给下游。
- 当前只有六个子 skill:`upload-parser`、`deck-planner`、`deck-renderer`、`deck-auditor`、`pitch-simulator`、`deck-ingestor`。
- 云端发布不是上述子 skill 的生产责任;默认最终发布调用独立
  `publish-magic-page`,legacy 文档嵌入才调用 `generate-magic-doc`。
- `deck-planner` 可以提出业务主线和候选 layout,但不能绕开 H5 design-first 确认,也不能要求 renderer 牺牲 H5 风格。
- `deck-renderer` 是 H5 风格和交付规则的执行者;不要把它降级为普通 HTML 生成器。
- `deck-auditor` 内聚 H5 CHECK-ONLY 标准检查;总控和用户路径不要把底层 validator 写成单独路由。
- `deck-ingestor` 只能沉淀已通过 auditor 或用户明确标记为“仅知识候选”的内容;模拟预测不能当作真实客户事实入库。
- 用户确认是迭代分界线:预演反馈、验收建议或 agent 判断都不能自动覆盖上一版规划。
