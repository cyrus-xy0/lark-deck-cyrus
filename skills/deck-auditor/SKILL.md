---
name: deck-auditor
description: |
  Quality acceptance skill for lark-deck-cyrus. Use after deck-renderer has
  produced a deck, or when the user asks whether a generated deck is ready to
  present, share, publish, enter the slide library, or when the user asks
  "审一下/检查一下/看看哪里不合规" for an existing HTML deck. Its baseline is the
  full feishu-deck-h5 CHECK-ONLY standard: run and interpret the H5 validator,
  visual audit, report grouping, context hints, and ingest gate rules before
  adding Cyrus-level talk-readiness, evidence, delivery-package, ingestion
  readiness, and routing judgments. In the Cyrus controller, uploaded HTML decks
  route here first; only passing decks continue to deck-ingestor.
---

# deck-auditor

目标:判断一份已经生成的 H5 pitch deck 是否达到“可以讲、可以发、可以继续迭代或可以入库”的质量门槛。
这个 skill 不负责生成页面,也不负责模拟客户会议;它负责验收、归因和分流。对用户来说,H5 CHECK-ONLY 是 auditor 的内部检查标准,不是一条单独暴露的底层 validator 路由。

**核心原则:**`deck-auditor` 的底层检查标准必须完全对齐 `feishu-deck-h5` 的 CHECK-ONLY 模式。auditor 不是另起一套规则,而是在 H5 CHECK-ONLY 规则报告之上,增加 Cyrus 的可讲性、证据纪律、交付完整性和修复路由判断。

## 入口边界

- 用户要“检查 HTML / validate / 审合规 / 哪里不对”:使用本 skill,底层必须按 H5 CHECK-ONLY 标准扫描。
- 用户要“能不能发 / 能不能讲 / 能不能入库”:使用本 skill,先跑或读取 H5 CHECK-ONLY 报告,再做产品级验收。
- 用户只明确要求底层技术规则输出:可以只输出 H5 CHECK-ONLY markdown 报告,但仍由本 skill 保证不改文件、不进生成流程。
- 用户上传 HTML deck 且目标是入库:本 skill 先验收;通过后才把可入库对象交给 `deck-ingestor`,失败时只返回失败理由和修复路由。
- 用户要求直接修改页面或重新生成:先验收并归因,再把修复路由到 `deck-renderer` 或 `deck-planner`;本 skill 不直接改 deck。

## H5 CHECK-ONLY 标准

当输入包含已有 `.html` deck,并且用户是在检查、审阅、验收或入库判断时,必须按 H5 CHECK-ONLY 处理:

- 不创建 `runs/<ts>/`。
- 不跑 `new-run.sh` / `preflight.sh`。
- 不调用 `copy-assets.py` / `extract-texts.py` / `package-deliverable.sh`。
- 不修改输入 HTML。
- 不自动修复问题;修复必须由用户另行确认,再路由到 GENERATION / `deck-renderer`。

底层命令使用 Cyrus 内的 H5 renderer 工具:

```bash
bash skills/deck-renderer/assets/check-only.sh <html-path> [--strict] [--visual] [--report PATH]
```

### 检查内容

H5 CHECK-ONLY 必须覆盖完整 `validate.py` 规则集:

- R02 / R05 / R06 / R10 / R12 / R13 / R20 / R29-32 / R36 / R38 / R47 / R48 / R49 / R56
- L1-L4
- UI1
- R-LANG / R-KEY / R-DOM / R-WHITE-TEXT / R-HIERARCHY
- T00-T03
- P50-P55
- R-FEEDBACK
- visual audit 中的 R-OVERFLOW / R-OVERLAP / R-VIS-TIER / R-VIS-HIER / R-VIS-LABEL-FLOOR / R-VIS-BODY-FLOOR / R-VIS-ALIGN / R-VIS-ABSPOS-DUAL-ANCHOR / R-VIS-ORPHAN

扫描时必须保留 H5 行为:自动解析已链接的 `<link rel="stylesheet">` 和
`<script src="">`,所以非 inline deck 也按真实渲染依赖检查。

报告必须保持 H5 的 family 分组:

| Family | Codes | What it audits |
|---|---|---|
| 结构 / DOM | R02 / R07 / R-DOM | `.slide` 的 `data-layout` / `data-screen-label` / `.wordmark`; DOM 平衡 |
| 排版 / 文案 | R05 / R06 / R13 / R20 / R56 / R-WHITE-TEXT / R-HIERARCHY | 禁用标点; 字号底线; 标题不强换行; 4-tier ladder; header-minimal; 白字可读 |
| 品牌 / 调色板 | L1 / R10 / R12 / R38 / R49 / R-LANG | 彩色 logo 默认; 品牌色; 禁真阴影; decor token; cyan 不作主色; 语言声明 |
| 布局完整性 | L2 / L4 / R36 / R47 / R48 | stage 平衡; 窄列单列; present-mode 居中; variant 结构重声明; 默认居中 |
| UI 仿真 / slide-key | UI1 / R-KEY | 系统 UI 用 HTML primitives 重建; 每页有语义化 `data-slide-key` |
| 演示模式 / 运行时 | R29-32 | progress、controls、prev/next/fs、fullscreen、idle fade |
| texts.md 联动 | T00 / T01 / T02 / T03 | `data-text-id` 存在、格式正确、唯一,并和 `texts.md` 同步 |
| 性能预算 | P50-P55 | base64、blur、ResizeObserver、AbortController、GPU layers |
| 视觉 | R-OVERFLOW / R-OVERLAP / R-VIS-* | 画布溢出、重叠、字号阶梯、层级、正文底线、对齐、双 anchor 拉伸、CJK 孤字 |
| 交付物附件 | R-FEEDBACK | `FEEDBACK.md` sidecar 是否存在 |

报告还必须保留 H5 的 context hints:

- Replica `.page-replica`
- inline `fs-deck-mode=inline`
- bilingual `fs-language=zh-en`
- context-dependent rules: T00 / T03 / UI1 / P50 / R29-32 / R-FEEDBACK

这些 hint 不能直接删掉 warning;auditor 要解释哪些是 blocker,哪些是上下文导致的安全可忽略项。

## Flag 选择

按用户场景选择 H5 CHECK-ONLY flags:

- **default:**`bash check-only.sh deck.html`。用于外部 deck 或第一轮卫生检查;warn 不阻断。
- **strict:**`bash check-only.sh deck.html --strict`。用于即将发客户、正式交付、需要零 warning 的审查;warn 升为 error。
- **visual:**`--visual`。用于客户现场展示、投影可读性、布局疑似溢出、重叠、字号、对齐检查。
- **report:**`--report path/to/report.md`。需要把报告作为交付物、转发给用户或进入 run output 时使用。
- **gate ingest:**`--gate ingest`。用于 slide library 入库准入;自动开启 visual,全部必修 warn 升级为 error。

普通交付验收默认命令:

```bash
bash skills/deck-renderer/assets/check-only.sh path/to/deck.html --strict --visual --report path/to/audit-report.md
```

Slide Library 入库验收默认命令:

```bash
bash skills/deck-renderer/assets/check-only.sh path/to/deck.html --gate ingest --report path/to/ingest-gate-report.md
```

结构化 DeckJSON 校验:

```bash
python3 skills/deck-renderer/deck-json/validate-deck.py path/to/deck.json
```

## Gate Ingest 标准

当用户问“能不能入库 / 入素材库 / slide-library / ingest / 复用”时,必须使用 `--gate ingest`。

Gate ingest 只看 21 条必修规则,按业务关切分组:

**A · 客户看不见** —— 投影硬伤

- `R-OVERFLOW` 内容超出 1920x1080 画框
- `R06` 正文字号 < 24px
- `R-WHITE-TEXT` 文字色融背景
- `L2` 内容堆顶留空
- `L4` 多列被挤窄字截断

**B · 库找不回这张 slide** —— locator 失锚

- `R-KEY` 缺 slide-key
- `R-DOM` DOM 嵌套坏
- `R02` 缺 layout / 屏幕标签
- `T01` text-id 格式错
- `T02` text-id 重复

**C · 复用时会打架** —— slide 复用品质

- `R05` emoji / `!` / `...` 等违禁标点
- `R10` 调色板飘移
- `R12` 真 drop-shadow
- `R13` 标题 `<br>` 强换行
- `R20` 字号 off-tier
- `R47` variant 改结构没重声明对齐
- `R48` 多卡片版式没默认居中
- `R49` cyan 当主色调
- `R56` 内容页 header 有 eyebrow
- `R-HIERARCHY` 次要字段比主要醒目
- `L1` logo 配色错

Gate ingest 直接屏蔽与入库无关的 10 类规则:

`T00` / `T03` / `R-FEEDBACK` / `UI1` / `P50` / `P51-P55` / `R29-32` / `R36` / `R-LANG` 单条 title-en warn。

这些规则可能对交付有价值,但不能作为 slide-library 入库阻断项。auditor 输出时必须区分“入库 blocker”和“交付 hygiene warning”。

## Cyrus 验收叠加层

H5 CHECK-ONLY 报告是 audit 的底座,但不是终点。拿到报告后,再叠加以下判断:

1. **结构完整**
   - 是否有稳定 slide key、合理页序、明确 layout、可追溯 source artifact。
   - 是否保留 `deck.json` / `texts.md` / `FEEDBACK.md` / assets 等编辑与交付回路。

2. **视觉和可读性**
   - 是否通过 H5 static validator。
   - 是否通过 visual audit 的溢出、遮挡、字号、对齐和投影可读性检查。
   - 所有 opt-out 必须是 documented intent,不能把 warning 批量静音。

3. **叙事可讲**
   - 开场是否说明为什么现在必须解决。
   - 每页重点是否清楚,是否承接上一页。
   - 结尾是否能推动下一步决策。
   - 叙事、主张或页序问题必须回到 `deck-planner`。

4. **素材和证据纪律**
   - 素材是否存在、可访问、来源清楚。
   - 客户事实、数字、案例、引语是否有来源或明确标注为假设。
   - 缺素材或缺证据时,不能让 renderer 硬补虚构内容。

5. **交付和入库门槛**
   - 本地 HTML、预览链接、可编辑包是否齐全。
   - 入库判断必须分三层:知识库候选服务 `deck-planner` 的“讲什么”;素材库候选服务 `deck-renderer` 的“怎么呈现”;Slide 库候选保存整页可选复用单元并引用前两层。
   - 同一页可以只适合进入知识库、只适合进入素材库、只适合进入 Slide 库、多层都适合,或都不适合。
   - 只有 `verdict: pass` 或用户明确要求“仅作为知识候选保存”的内容,才能交给 `deck-ingestor`。

## 输出纪律

输出时第一句话必须给 H5 报告形态和 Cyrus 验收结论:

```text
H5 CHECK-ONLY: FAIL, 3 errors / 5 warns. Cyrus verdict: rerender-required.
```

默认输出一份验收结论,包含:

- `h5_checkonly_summary`: H5 报告 PASS/FAIL、error/warn 数、使用 flags、报告路径。
- `h5_rule_findings`: 按 H5 family 分组的关键问题;问题集中时点明主因。
- `context_hints`: Replica / inline / bilingual / context-dependent rules 的解释。
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
- `ingestion_handoff`: 若通过,列出应交给 `deck-ingestor` 的 knowledge / slide / asset 对象;若失败,列出阻断原因。

如果用户只要 H5 CHECK-ONLY 报告,输出 markdown 报告即可,但仍要保留首句 verdict 和 family 聚焦说明。

如果用户问某个规则码是什么意思,到 `skills/deck-renderer/assets/validate.py`
里查对应规则;每个 audit function 的 docstring 和错误信息才是解释依据。

## 硬规则

- H5 CHECK-ONLY 规则是 audit 的底线;不要用 Cyrus 可讲性判断覆盖 H5 blocker。
- 不直接改 deck;只输出验收结论和分流建议。
- 不创建 run、不跑 generation preflight、不修改输入 HTML。
- 不直接写云端库;入库动作交给 `deck-ingestor`。
- 不把 validator PASS 等同于“客户一定能听懂”;必须检查可讲性。
- 不把预演结果写成真实客户反馈;客户反应模拟交给 `pitch-simulator`。
- 不因赶时间跳过 blocker;如需带风险交付,必须明确风险并等待用户确认。
