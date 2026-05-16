# feishu-deck-h5

> **飞书风格的客户提案 deck，但是 HTML 不是 PPT。**
> 浏览器全屏放映、单文件发 IM、文本编辑器改字、视觉与飞书母版完全对齐。

🔗 看样品 → [`examples/sample-deck.html`](examples/sample-deck.html)
（双击在浏览器打开，左右键翻页）

---

## 这是什么

把飞书母版 2025（深色通用）的 PowerPoint 视觉**完整搬到 HTML**，生成的就是一份
`.html` 文件，但它表现得跟 PPT 一样：

- **浏览器全屏 = 16:9 演示模式** — 左右键翻页、底部进度条、闲置自动隐藏控件
- **手机能看** — 自动切换成纵向滚动浏览，发链接给客户立刻能预览
- **单文件可直接转发** — 飞书 / 邮件 / IM 任何途径，对方双击就开，不用装 Office
- **文字用记事本改** — 配套 `texts.md` 文本侧文件，改文字不动布局
- **视觉跟飞书品牌完全对齐** — 13 种 layout 全部从官方 .thmx 母版抽出，色值/字号/留白都是母版坐标

---

## 为什么不直接用 PowerPoint

| | PowerPoint .pptx | feishu-deck-h5 .html |
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

13 种基础 layout，覆盖一份典型客户提案从封面到封底的所有页型：

| Layout | 适合什么内容 |
|---|---|
| **cover** | 封面 — 飞书母版花朵背景，标题在左、配图在右 |
| **agenda** | 议程 — 3-6 项垂直 pill 堆叠，开场目录 |
| **section** | 章节分隔 — 巨型序号 + 章节标题 + 产品 pill |
| **content-3up** | 三大能力 / 三个支柱 — 三卡并列 |
| **content-2col** | 一段叙事 + 配图 / UI 截图 — 左文右图 |
| **quote** | 客户证言 / 金句 — 居中大字 + 来源 |
| **stats** | 4-up KPI — 四个并列数字 + 单位 + 来源 |
| **big-stat** | 单个英雄数字 — 例如 "30 万人" + 旁边一段说明 |
| **image-text** | 全屏照片 + 左下角文字 — 客户现场 / 门店 / 工厂 |
| **table** | 对比表 — 飞书 vs 传统套件这种比较矩阵 |
| **timeline** | 横向时间轴 — 4-6 个里程碑 |
| **process** | 流程步骤 — 3-6 步带右指箭头 |
| **end** | 封底 — 飞书品牌花朵背景 + "先进团队 先用飞书" slogan |

**加成**：

- **11 个叙事模式** — 北极星指标 chip、verdict 判定矩阵、"做 / 不做" boundary band、
  现阶段 → 未来 evolution chip、北极星地图、行业邻接场景 grid 等，覆盖飞书内部
  常用的"几种主张并列"、"判断接 / 部分接 / 不接"等结构化论证。
- **27 个 UI 原语** — `.ui-window` / `.ui-grid` / `.ui-msg` / `.ui-tabs` / `.ui-kpi` 等，
  让产品截图用 HTML 重建而非贴 PNG，缩放永远清晰、字体永远跟 deck 一致。
- **飞书产品官方 logo** — aily / 多维表格 / 妙搭 / 飞书会议 / 飞书人事 / 集成平台
  等全套产品标识，无需自己画 SVG。

完整 layout 规格 + 11 个叙事模式 + UI 原语清单见 [SKILL.md](skills/feishu-deck-h5/SKILL.md)。

---

## 看更多例子

- [`examples/sample-deck.html`](examples/sample-deck.html) — 12 张 slide 涵盖全部 13 种 layout
- [`preview-dark.html`](preview-dark.html) — 设计令牌（颜色 / 字号 / 渐变）+ 组件 gallery
- [`templates/slide-recipes.html`](templates/slide-recipes.html) — 每种 layout 的 reference 实现

---

## 怎么开始用

**让 Claude 帮你装 + 帮你做**，一句话：

> "帮我安装 feishu-deck-h5 skill：https://github.com/FuQiang/feishu-deck-h5，
> 装完帮我做一份关于〔你的主题〕的 deck"

Claude 会读 [INSTALL.md](INSTALL.md) 走标准安装流程（plugin marketplace 或 install.sh），
然后按 [SKILL.md](skills/feishu-deck-h5/SKILL.md) 的规范生成 deck。

---

## 想看怎么搭出来的

| 内容 | 文档 |
|---|---|
| 安装路径（marketplace / install.sh / 手动 clone） | [INSTALL.md](INSTALL.md) |
| 13 layouts + 11 叙事模式 + 27 UI 原语 + 55 自检项 | [SKILL.md](skills/feishu-deck-h5/SKILL.md) |
| 9-section 完整设计系统 | [DESIGN.md](DESIGN.md) |

---

## License

MIT — 见 [LICENSE](LICENSE)。

`assets/lark-*.png/jpg` 是 ByteDance / 飞书的官方品牌资产，版权归飞书设计团队，
不在本仓库 MIT 许可范围内，第三方使用前请遵守飞书品牌规范。
