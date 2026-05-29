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
   - 默认优先查 live Feishu Base 的 `知识库`;使用当前沙箱 agent 的 user 身份,不要要求用户配置 token。若 lark-cli 身份无权限、网络不可达或云端未命中,再回退随包 `knowledge/` 本地知识,并在输出中明文说明。
   - 根据行业、飞书产品、客户名分别搜索;客户故事只使用用户提供、公开来源、live Base 授权记录或本地明确标注的素材。
   - 如果存在 `upload-recognizer` 结果,把其中的知识层当作用户提供素材,优先级高于通用知识库,但仍要保留来源和置信度。
   - 没有知识就暴露缺口,不要编。
   - 企业 AI / 数字员工 / 制造业知识萃取 / 高管讲座类 deck,必须读取
     `knowledge/recipes/zhongji-innolight-ai-lecture.md`,并把其中的
     "业务场景 -> 痛点 -> AI 机制 -> 人的角色变化 -> 价值证明"结构写入
     outline,而不是只复述资料标题。

4. **形成行业痛点判断**
   - 每个痛点必须包含:为什么现在重要、业务后果、建议证据、证据等级。
   - 不要把通用行业规律写成某客户已经发生的事实。
   - 每个核心解法页必须绑定一个可讲的业务时刻:谁在现场、正在处理什么
     输入、当前卡在哪里、Agent/数字员工下一步做什么、人的工作如何升级。
   - 对制造业 / NPI / 质量 / 供应链场景,优先写出"工程师/督导/项目经理
     的一天"或"一次异常闭环"这样的角色化故事,再落到功能模块。

5. **设计 deck arc**
   - 第一段:为什么这个问题现在必须解决。
   - 第二段:飞书 / agent / bot 如何改变工作方式。
   - 第三段:落地路径、证据、下一步。
   - demo 只能作为论据或体验入口,不能成为整份 deck 的唯一主体。
   - 当 brief 带有“流程重塑 / 流程被重新发明 / PPT 换成 HTML /
     工件反转 / 飞轮 / 范式”等信号时,优先套用 `process-reinvention`
     recipe,不要退回常规“痛点-方案-试点”模板。标准弧线是:
     **旧世界断头路 -> 物理层跃迁 -> 执行飞轮 -> 四个反转 -> 自我进化**。
     这类 deck 的每页必须有一条可复述的判断句;P2 的痛点要写成支撑
     “断头路”的证据,P3 要先讲载体/工件的物理性质变化,P4 要画出
     “每次输出也是下一次输入”的闭环,P5 抽象为工件/数据/颗粒度/角色
     四个反转,P6 再收束到组织能力如何自我生长。
   - 高质量企业 AI deck 的节奏应是:概念定调 -> 典型场景 -> 可视化机制
     -> 客户/类比案例 -> 落地建议;连续同构卡片页超过 3 页时必须插入
     quote / section / hero / demo 呼吸页。
   - 对制造业 / NPI / 质量 / 供应链 / 高管 AI 讲座类 deck,outline 必须至少包含:
     角色化业务场景页 1 页(如工程师的一天或一次异常闭环)、可视化机制/原型页
     1 页(仪表盘、review panel、雷达、工作台、iframe/raw demo 均可)、案例/证据页
     1 页、落地建议页 1 页。缺任何一类时,标记为 replan/open question,
     不允许交给 renderer 只套 3up / matrix / process / table。

6. **映射到 DeckJSON**
   - 优先选择 `deck-renderer/deck-json/deck-schema.json` 已有 layout。
   - 每页都给 `layout_candidate`,但只作为建议;`deck-renderer` 可在生产时调整。
   - 若需要真实交互或在线体验,标记 `iframe-embed` / `phone-iframe` 或 `demo` asset。
   - 若页面规划为工作台、仪表盘、应用原型或多状态 UI,tab / segmented
     control / slider / button 等控件必须在素材计划里标明交互状态。tab
     类控件默认需要可切换;如果只是静态示意,必须写出静态理由,不能把
     “看起来可点”的控件交给 renderer 自行脑补。

7. **生成素材计划**
   - logo/icon/demo 先查统一入口: `python3 scripts/base_library.py search-assets "<关键词>" --limit 20`。
   - 默认优先查云端 `素材库`;云端不可用或无权限时才读取 `assets/shared/asset-index.generated.json`,并明文提示已回退本地缓存。
   - 现场图片、客户截图、真实 demo 优先用户提供。
   - `upload-recognizer` 的素材层可直接进入 `asset_plan`,但 planner 只引用素材,不移动文件、不上传云端库。
   - 找不到素材时明确 fallback,不要让模型临时画商标或伪造客户现场。

## 硬规则

- 不编客户数据、STORY id、访谈来源、具名引语。
- 不用“行业领先、全面赋能、智能升级”填满页面;每页要有可 defend 的判断。
- 不允许把 planner 降级成资料目录;每个 section 都要讲清业务痛点和飞书 /
  Agent 解法的因果链。
- 不允许用泛化"效率提升、流程闭环、智能决策"替代具体场景。写不出角色、
  业务时刻、输入输出和证据缺口时,必须标为 replan/open question。
- 企业 AI / 制造业 deck 不能连续超过 3 页使用同构模板页;outline 必须显式安排
  场景、原型、案例、Quote/Section 呼吸页,否则不进入渲染。
- 信息不足时,提出少量高价值 open questions;已可合理规划时先给带假设的 outline。
- 每页必须有稳定的 `key`,后续会成为 `data-slide-key`。
- 输出要让 `deck-renderer` 能继续工作,而不是只给一段漂亮文字。

## Renderer handoff

用户确认 outline 后才允许 handoff;确认前只交付 outline / OUTLINE_REVIEW,不生成 deckhtml:

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
