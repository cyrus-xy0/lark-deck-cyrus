---
name: deck-planner
description: |
  Use this skill when the user asks for a deck plan, outline, proposal structure,
  sales narrative, 客户提案大纲, 汇报材料规划, 每页重点, 讲法设计, or gives a
  raw business brief that should become a pitch deck, or when upload-recognizer
  has produced a source dossier from PDF/PPT/HTML/Feishu docs. The skill decides
  what the deck should say, what each page should emphasize, what the key ideas
  are, how the presenter should tell the story, and what evidence or assets are
  still missing before deck-renderer produces the final deck. Do not use it for
  low-level HTML/CSS fixes, packaging, visual acceptance, ingestion, or pitch
  rehearsal.
---

# deck-planner

目标:把用户的业务场景转成可执行的 deck 规划,明确整套片子讲什么、每页讲什么、重点是什么、关键 idea 是什么、应该怎么讲。
这个 skill 不直接生成 HTML,也不急着套模板;它先判断“为什么要做这份 deck、要打中谁、每页承担什么说服任务”。

## 非目标

- 不直接写 HTML、CSS 或交付包;这些交给 `deck-renderer`。
- 不做最终质量判定;生成后的可读性、入库和交付验收交给 `deck-auditor`。
- 不模拟客户真实反应;预演和异议地图交给 `pitch-simulator`。
- 不直接把素材或知识写入云端库;入库交给 `deck-ingestor`。

## 输入

可接受任意组合:

- 一段业务 brief / 客户需求 / 销售场景
- 目标受众、行业、客户名、产品范围
- 用户提供的素材、文档、飞书链接、图片、视频或 demo 链接
- `upload-recognizer` 输出的 source dossier:知识层、素材层、slide inventory、来源和置信度
- 已有 outline,需要升级为更专业的 deck 规划

## 输入模式

- **Brief-only:**用户只有纯文字 brief。直接读取知识库和本地 recipe 生成 outline,不要先调用 `pitch-simulator`。
- **Brief + materials:**用户带 PDF / PPT / HTML / 飞书文档 / 图片 / demo。必须先消费 `upload-recognizer` 的结构化结果,再生成 outline。
- **HTML deck 检查 / 入库:**不要调用本 skill;直接走 `deck-auditor`,通过后走 `deck-ingestor`。

## 输出

默认输出一份符合 `schema/deck-outline.schema.json` 的 outline JSON,并附
一段面向用户的简短说明。若用户只是在 brainstorm,可以先输出人读版大纲,
但最终进入 deck 生产前必须有同等字段。落文件后用 stdlib 校验器检查:

```bash
python3 skills/deck-planner/validate-outline.py \
  skills/deck-planner/examples/retail-agent-outline.json
```

核心字段:

- `brief`:主题、受众、目标、使用入口(local-agent / feishu-bot)。
- `scene`:行业、角色、业务时刻、核心冲突、信心等级。
- `thesis`:一句话主张、痛点、解法角度、差异化。
- `outline.slides[]`:每页 key、角色、核心信息、关键 idea、建议讲法、候选 DeckJSON layout、素材需求。
- `asset_plan`:图片、视频、icon、logo、demo 等素材请求和兜底。
- `source_dossier_refs`:使用了哪些上传识别结果,包括文件名、页码、slide key、素材 id 或引用路径。
- `claim_discipline`:哪些判断是用户给的,哪些只是推断,哪些必须确认。

## 工作流

1. **识别使用入口**
   - 本地 agent:可以产出 repo 内文件,强调 deck.json/texts.md/FEEDBACK.md。
   - 飞书 bot:默认考虑远程 zip、在线预览、飞书消息里的多轮反馈。
   - 不确定时写 `delivery_mode: "unknown"`,并把它列为 open question。

2. **抽取场景目标**
   - 目标受众是谁?
   - 这份 deck 要让对方做什么决定?
   - 成功指标是什么:约会、立项、预算、内部 alignment、产品试用、复盘通过?

3. **读取知识库**
   - 默认通过仓库根目录的 `python3 scripts/base_library.py search-knowledge "<关键词>" --limit 10` 检索。
   - 外部 GitHub 安装默认使用随包 `knowledge/` 本地知识;有 `lark-cli`、`LARK_LIBRARY_BASE_TOKEN` 或 `LARK_LIBRARY_MODE=base` 时才查 live Feishu Base。
   - 根据行业、飞书产品、客户名分别搜索;客户故事只使用用户提供、公开来源、live Base 授权记录或本地明确标注的素材。
   - 如果存在 `upload-recognizer` 结果,把其中的知识层当作用户提供素材,优先级高于通用知识库,但仍要保留来源和置信度。
   - 没有知识就暴露缺口,不要编。

4. **形成行业痛点判断**
   - 每个痛点必须包含:为什么现在重要、业务后果、建议证据、证据等级。
   - 不要把通用行业规律写成某客户已经发生的事实。

5. **设计 deck arc**
   - 第一段:为什么这个问题现在必须解决。
   - 第二段:飞书 / agent / bot 如何改变工作方式。
   - 第三段:落地路径、证据、下一步。
   - demo 只能作为论据或体验入口,不能成为整份 deck 的唯一主体。

6. **映射到 DeckJSON**
   - 优先选择 `deck-renderer/deck-json/deck-schema.json` 已有 layout。
   - 每页都给 `layout_candidate`,但只作为建议;`deck-renderer` 可在生产时调整。
   - 若需要真实交互或在线体验,标记 `iframe-embed` / `phone-iframe` 或 `demo` asset。

7. **生成素材计划**
   - logo/icon/demo 先查统一入口: `python3 scripts/base_library.py search-assets "<关键词>" --limit 20`。
   - 外部安装默认读取 `assets/shared/asset-index.generated.json`;内部配置 live Base 后会优先查 Base。
   - 现场图片、客户截图、真实 demo 优先用户提供。
   - `upload-recognizer` 的素材层可直接进入 `asset_plan`,但 planner 只引用素材,不移动文件、不上传云端库。
   - 找不到素材时明确 fallback,不要让模型临时画商标或伪造客户现场。

## 硬规则

- 不编客户数据、STORY id、访谈来源、具名引语。
- 不用“行业领先、全面赋能、智能升级”填满页面;每页要有可 defend 的判断。
- 信息不足时,提出少量高价值 open questions;已可合理规划时先给带假设的 outline。
- 每页必须有稳定的 `key`,后续会成为 `data-slide-key`。
- 输出要让 `deck-renderer` 能继续工作,而不是只给一段漂亮文字。

## Renderer handoff

用户确认 outline 后:

1. 把 outline JSON 放进本次 run 的 `input/` 或 `output/`。
2. 调用 `deck-renderer` 的 DeckJSON-first 流程。
3. 根据 `outline.slides[].layout_candidate` 写 `deck.json`。
4. 根据 `asset_plan` 和 `source_dossier_refs` 解析素材;缺素材时用 open question 或安全兜底。
5. 生成后在 FEEDBACK.md 记录:哪些 outline 判断被保留、修改或无法落地。

## Quality handoff

deck 生成后,把 `deck.json`、HTML、`texts.md`、`FEEDBACK.md` 和校验报告交给
`deck-auditor` 做质量验收。若问题来自叙事结构、每页重点、关键 idea 或讲法,
回到本 skill;若问题来自布局、视觉、HTML、素材落地或交付包,交给 `deck-renderer`。

## Pitch simulation handoff

HTML deck 生成并通过 `deck-auditor` 后,把 outline 和 deck.json 交给
`pitch-simulator` 做最终 pitch rehearsal。不要在 planner 刚完成后先跑 simulator:

```bash
python3 skills/pitch-simulator/simulate-pitch.py \
  --outline runs/<ts>/input/outline.json \
  --deck-json runs/<ts>/output/deck.json \
  --out-json runs/<ts>/output/pitch-rehearsal.json \
  --out-md runs/<ts>/output/PITCH_REHEARSAL.md
```

预演结果里的 `revision_queue` 可回写到 outline:叙事结构问题回到本 skill,
页面/文案问题交给 `deck-renderer`,证据或素材缺口写入知识库/素材 backlog。
只有用户确认采纳预演建议后,这些反馈才进入下一轮 planner / renderer 迭代。
