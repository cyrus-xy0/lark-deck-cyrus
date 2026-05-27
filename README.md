# lark-deck-cyrus

> **飞书风格的客户提案 deck，但是 HTML 不是 PPT。**
> 浏览器全屏放映、单文件发 IM、文本编辑器改字、视觉与飞书母版完全对齐。

🔗 看样品 → [`skills/deck-renderer/examples/sample-deck.html`](skills/deck-renderer/examples/sample-deck.html)
（双击在浏览器打开，左右键翻页）

---

## 这是什么

把飞书母版 2025（深色通用）的 PowerPoint 视觉**完整搬到 HTML**，生成的就是一份
`.html` 文件，但它表现得跟 PPT 一样：

- **浏览器全屏 = 16:9 演示模式** — 左右键翻页、底部进度条、闲置自动隐藏控件
- **手机能看** — 自动切换成纵向滚动浏览，发链接给客户立刻能预览
- **单文件可直接转发** — 飞书 / 邮件 / IM 任何途径，对方双击就开，不用装 Office
- **文字用记事本改** — 配套 `texts.md` 文本侧文件，改文字不动布局
- **视觉跟飞书品牌完全对齐** — 15 个 DeckJSON layout enum（12 个基础 + 3 个 special）沿用飞书母版坐标，色值/字号/留白由 renderer 和 validator 约束

更完整的产品方向见 [`PRODUCT.md`](PRODUCT.md):本项目是 `lark-deck-cyrus`
总控 skill，串联“上传识别 → 场景规划 → 知识库 → 素材库 → DeckJSON → HTML 渲染
→ 质量验收 → Pitch 预演 → 云端入库 → 用户确认迭代”的产品闭环。

和 `feishu-deck-h5` 的主要区别: H5 是完整的单体生产 skill; Cyrus 沿用 H5 的
视觉和交付标准,但按场景拆成 recognizer / planner / renderer / auditor /
simulator / ingestor 多个子 skill,并新增 simulator 做客户情景预测。

---

## 产品化能力

- **deck planner** — `skills/deck-planner/` 先判断行业痛点、受众、
  每页重点、关键 idea、讲法、证据缺口、素材计划和页级 layout candidate,避免只做视觉 demo。
- **上传识别** — `skills/upload-recognizer/` 把 PDF / PPT / HTML / 飞书文档
  拆成知识层和素材层,供 planner 规划、renderer 使用、ingestor 入库。内置
  `recognize.py` 可直接输出 `source-dossier.json` 和 `SOURCE_DOSSIER.md`。
- **知识库** — GitHub 安装默认使用随包 `knowledge/`;内部用户可配置飞书 Base 作为 live source。
- **素材索引** — GitHub 安装默认读取 `assets/shared/asset-index.generated.json`;
  配置 `LARK_LIBRARY_BASE_TOKEN` 后可用飞书 Base 同步 logo、图片、video、icon、demo 等素材。
- **HTML deck 渲染** — `skills/deck-renderer/` 消费 outline,优先用 DeckJSON-first
  生成可编辑、可交付的 HTML deck。
- **质量验收** — `skills/deck-auditor/` 统一解释 validator、screenshot、gate、
  交付包和可讲性问题,并把修改项分流回 planner 或 renderer。
- **服务端 wrapper** — `server/generator.py` 固化 `Brief -> Outline -> DeckJSON -> HTML`
  链路,生成任务目录、运行 renderer / validator,并输出预览、编辑和下载链接字段。
- **Journey 学习闭环** — 每次生成和轻量编辑产出 `journey.json`、`JOURNEY.md`、
  `quality-insights.json`,把用户精调动作转成下一次生成的改进信号。
- **Pitch 预演** — `skills/pitch-simulator/` 在 HTML deck 之后模拟
  决策者、推动者、使用者、技术和财务角色逐页反应,输出异议地图和改稿队列。
- **Deck 入库** — `skills/deck-ingestor/` 在 auditor / simulator 之后把
  slide、素材和知识分别写入本地候选库;显式 `--write-base` 时只把
  `知识库` 和 `素材库` 同步到 live 飞书 Base。Slide Library 暂时保持本地,
  由本地候选库保存整页可选复用单元。默认 Base 指向
  `DBtybdvHYaovVwsWLatcipJBnrg` 的 `素材库` / `知识库`;Base 记录优先写
  `关联SlideKey`、`关联素材ID` / `关联知识ID`、来源 deck/PPT 和权限状态,
  若目标表暂缺显式关联字段,则降级写入 `适用页面`、`来源` 和 `标签`。
- **自选 PPT 入库** — 用户可直接上传团队 PPT/PPTX 到 Slide Library 候选库,
  先登记为可搜索/可选择页面,自动生成本地缩略图,再由 recognizer / renderer
  对选中页拆知识和素材。
- **云端 agent 部署包** — `scripts/cloud_agent_deploy.py` 生成
  `deploy/cloud-agent/` 下的 `.env` 模板、generator/bot 启动脚本、健康检查和
  端点 manifest,方便用户把同一套 skill 部署给自己的云端虾/agent。完整
  一句话部署方案见 [`CLOUD_AGENT.md`](CLOUD_AGENT.md)。

---

## 为什么不直接用 PowerPoint

| | PowerPoint .pptx | lark-deck-cyrus .html |
|---|---|---|
| 文件大小 | 几十 MB 起步 | 24-360 KB |
| 需要 Office license | 是 | 否（任何浏览器都能开） |
| 飞书/IM 转发 | 经常变形 | 单文件，对方双击即看 |
| AI 直接生成 | 很难做出像样的 | 天然适合（HTML 是 LLM 母语） |
| 视觉一致性 | 靠人盯 | 55 项规范程序化自动校验 |
| 版本管理 / 协作 | git 看不了 diff | 标准 git diff，PR review 友好 |

不是替代 PPT 所有场景——客户硬要 .pptx 还是给 .pptx。但售前/内训/产品提案
这些**多人迭代 + 多渠道分发**的场景，HTML 几乎是完胜。

---

## 支持哪些 layout

15 个 DeckJSON layout enum（12 个基础 + 3 个 special），覆盖一份典型客户提案
从封面到封底的所有页型。`content` / `stats` / `flow` 是多 variant layout，
因此实际可用版式约 20 个：

| Layout | 适合什么内容 |
|---|---|
| **cover** | 封面 — 飞书母版花朵背景，标题在左、配图在右 |
| **agenda** | 议程 — 3-6 项垂直 pill 堆叠，开场目录 |
| **section** | 章节分隔 — 巨型序号 + 章节标题 + 产品 pill |
| **content** | 三卡并列、左文右图、一页纸案例、矩阵、前后对比、全宽 blocks |
| **stats** | KPI 行、单个英雄数字、桥图 |
| **quote** | 客户证言 / 金句 — 居中大字 + 来源 |
| **image-text** | 全屏照片 + 左下角文字 — 客户现场 / 门店 / 工厂 |
| **table** | 对比表 — 飞书 vs 传统套件这种比较矩阵 |
| **flow** | 时间轴、流程步骤、MECE 树、多泳道 roadmap |
| **logo-wall** | 行业 / 客户 logo 矩阵 |
| **arch-stack** | 应用、平台、AI、数据底座等分层架构图 |
| **iframe-embed** | 嵌入 live demo、原型、报表或外部 HTML |
| **end** | 封底 — 飞书品牌花朵背景 + "先进团队 先用飞书" slogan |
| **replica / raw** | special: PDF 页图复刻 / 单页 HTML escape hatch |

**加成**：

- **11 个叙事模式** — 北极星指标 chip、verdict 判定矩阵、"做 / 不做" boundary band、
  现阶段 → 未来 evolution chip、北极星地图、行业邻接场景 grid 等，覆盖飞书内部
  常用的"几种主张并列"、"判断接 / 部分接 / 不接"等结构化论证。
- **27 个 UI 原语** — `.ui-window` / `.ui-grid` / `.ui-msg` / `.ui-tabs` / `.ui-kpi` 等，
  让产品截图用 HTML 重建而非贴 PNG，缩放永远清晰、字体永远跟 deck 一致。
- **飞书产品官方 logo** — aily / 多维表格 / 妙搭 / 飞书会议 / 飞书人事 / 集成平台
  等全套产品标识，无需自己画 SVG。

完整 layout 规格 + 11 个叙事模式 + UI 原语清单见 [deck-renderer/SKILL.md](skills/deck-renderer/SKILL.md)。

---

## 看更多例子

- [`skills/deck-renderer/examples/sample-deck.html`](skills/deck-renderer/examples/sample-deck.html) — HTML 示例 deck
- [`skills/deck-renderer/preview-dark.html`](skills/deck-renderer/preview-dark.html) — 设计令牌（颜色 / 字号 / 渐变）+ 组件 gallery
- [`skills/deck-renderer/templates/slide-recipes.html`](skills/deck-renderer/templates/slide-recipes.html) — 每种 layout 的 reference 实现

---

## 怎么开始用

**让 Claude 帮你装 + 帮你做**，一句话：

> "帮我安装 lark-deck-cyrus skill：git@github.com:cyrus-xy0/lark-deck-cyrus.git，
> 装完帮我做一份关于〔你的主题〕的 deck"

Claude 会读 [INSTALL.md](INSTALL.md) 走标准安装流程（plugin marketplace 或 install.sh），
然后按 [lark-deck-cyrus/SKILL.md](skills/lark-deck-cyrus/SKILL.md) 的总控流程生成 deck。
`install.sh` 默认会把 Playwright 和 Chromium 安装到项目本地 `.deps/`,这样
`deck-renderer` 的视觉审计不用额外手动装全局 Python 包。

如果你只有一段业务场景 brief,推荐先让 agent 使用 `deck-planner`
产出 outline,确认后再交给 `deck-renderer` 渲染。

如果已经生成了 HTML deck,先让 agent 使用 `deck-auditor` 做质量验收。需要模拟
客户反应时,再使用 `pitch-simulator` 预演“拿这套片子去讲会发生什么”,产出
`pitch-rehearsal.json` 和 `PITCH_REHEARSAL.md`;用户确认采纳后,再把修改队列
回写到 outline / deck.json。

上传材料可先跑识别器:

```bash
python3 skills/upload-recognizer/recognize.py path/to/source.pptx \
  --brief "给零售客户做飞书 Base 提案" \
  --output-dir runs/source-dossiers/retail-base
```

云端 agent 部署包可这样生成:

```bash
python3 scripts/cloud_agent_deploy.py \
  --output deploy/cloud-agent \
  --base-url https://your-agent.example.com
```

如果用户只想把任务交给自己的云端 agent,直接使用
[`CLOUD_AGENT.md`](CLOUD_AGENT.md) 里的“一句话提示词”;部署包也会生成
`deploy/cloud-agent/ONE-SHOT-PROMPT.md` 供 agent 复制执行。

---

## 想看怎么搭出来的

| 内容 | 文档 |
|---|---|
| 安装路径（marketplace / install.sh / 手动 clone） | [INSTALL.md](INSTALL.md) |
| 云端 agent 一句话部署与使用 | [CLOUD_AGENT.md](CLOUD_AGENT.md) |
| 总控流程 | [lark-deck-cyrus/SKILL.md](skills/lark-deck-cyrus/SKILL.md) |
| 15 layout enum + 11 叙事模式 + 27 UI 原语 + 55 自检项 | [deck-renderer/SKILL.md](skills/deck-renderer/SKILL.md) |
| 9-section 完整设计系统 | [DESIGN.md](DESIGN.md) |

---

## License

MIT — 见 [LICENSE](LICENSE)。

`assets/lark-*.png/jpg` 是 ByteDance / 飞书的官方品牌资产，版权归飞书设计团队，
不在本仓库 MIT 许可范围内，第三方使用前请遵守飞书品牌规范。
