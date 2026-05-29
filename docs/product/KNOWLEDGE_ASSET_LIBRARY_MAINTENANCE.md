# 飞书知识库 / 素材库设计评估与维护说明

日期: 2026-05-29

## 结论

当前设计方向是对的,但还不能完整满足业务需求。

它已经把链路拆成了三层:

- planner 查 `场景索引`、`Outline模板库`、`知识库`,生成 design plan / outline。
- renderer 查 `素材库`,把 outline 编译成 DeckJSON,再渲染 HTML。组件类能力不再单独走组件库,统一作为素材记录维护。
- ingestor 在验收通过后,把可复用内容拆回知识、素材和本地 Slide 候选。

主要问题是:live Base 起步时只有空表结构,没有可检索内容;本地缓存能支撑 demo 和低风险生成,但不足以支撑稳定的业务化 pitch 生产。2026-05-29 已补充导入本地 shared assets 和旧 slide library 内容;后续主维护面收敛为知识库和素材库。

## 本次检查结果

### Live Base

`scripts/base_library.py doctor --probe` 在沙箱外通过,主链路四张表可读:

- `场景索引`
- `Outline模板库`
- `知识库`
- `素材库`

`组件库` 保留为 `legacy_optional`,不进入 planner / renderer 主链路,也不作为日常维护对象。

但抽样读取和关键词检索结果都是空:

- `场景索引`: 前 5 行为空,`search-scenarios 飞书` 为空。
- `Outline模板库`: 前 5 行为空,`search-outline-templates pitch` 为空。
- `知识库`: 前 5 行为空,`search-knowledge AI` 为空。
- `素材库`: 前 5 行为空,`search-assets 飞书` 为空。
- `组件库`: legacy optional,前 5 行为空;不影响主链路。

这意味着当前 live Base 还不是可用的业务知识 / 素材来源,只能作为待填充 schema。

### 本地知识库

本地 `knowledge/` 当前可用:

- 6 个 pitch recipe。
- 7 个行业包。
- 8 个产品模块。

`python3 server/pitch_recipes.py validate` 通过。它能辅助 planner 生成基础大纲,但它不是 live Base,也缺少按客户、来源、权限、证据等级细分的真实业务知识。

### 本地素材库

`skills/deck-renderer/assets/shared/asset-index.generated.json` 当前有 355 个素材:

- `clientlogo`: 257
- `feishu-products`: 40
- `digital_employee_avatars_50`: 45
- `mydigitalemployee`: 5
- `third-party-logos`: 6
- `bytedance-products`: 2

素材类型只有:

- `logo`: 305
- `image`: 50

所以它覆盖了大量用户 logo、飞书产品标识、数字人头像,但缺少:

- 飞书产品截图 / 产品界面图。
- 飞书常用 UI 元素 / 图形元素的结构化素材记录。
- 视频、音频、产品 demo 链接。
- 可直接由 renderer 按 asset id 下载、落本地、内联到 HTML 的完整资源契约。

### 本地 Slide Library

`library/business/slides/` 有 17 个 approved 业务 slide seed,覆盖常见 layout。

但 `python3 server/slide_library.py validate` 当前失败,原因是 `library/business/candidates/` 中有重复 slide key。approved slides 本身没有报错,但候选库需要清理或改去重策略,否则会影响维护门禁的可信度。

## 对业务需求的匹配判断

### 1. brief -> planner -> design plan

部分满足。

planner 的设计已经要求先查场景、模板和知识,再输出每页角色、重点、讲法、证据缺口和 layout candidate。`deck-outline.schema.json` 也能表达这些内容。

不足:

- live Base 没有记录,所以真实运行会回退本地知识。
- `场景索引` 和 `Outline模板库` 现在是文本字段为主,缺少更强的机器字段,例如默认页数、每页职责、必备素材类型、质量门禁、适用/禁用条件的结构化表达。
- 缺少来源/权限/证据等级的强约束,容易把假设写进 pitch。

### 2. design plan -> renderer -> deck.json -> HTML 内联素材

部分满足。

renderer 已支持 DeckJSON-first、local asset copy、single-file inline。`compile-outline.py` 能把 outline 的 `asset_plan` 编译为 DeckJSON `assets` manifest。

不足:

- `inline-assets.py` 只内联本地 CSS/JS/image 文件,不会内联 `http://` 或 `https://` 资源。
- Base 附件必须先通过 `sync-shared-assets` 下载到本地 shared assets,renderer 才能稳定引用。
- 当前 DeckJSON asset manifest 只粗分 `scenes` 和 `logos`,不够表达 video/audio/demo/component 的加载策略。
- 素材表还没有真实记录,renderer 无法按 live Base 的 asset id 直接找到素材。

因此要满足“HTML 中直接添加资源,不是只放链接”,需要把 Base 素材解析改成:先把附件/URL 下载或复制到 run workspace,再让 DeckJSON 指向本地路径,最后用 `--inline` 生成单文件。

### 3. 素材类型覆盖

部分满足。

已覆盖:

- 飞书产品标识。
- 数字人头像。
- 用户 logo。
- 第三方 logo。

不足:

- 飞书 icon 库没有完整结构化进入当前 index。
- 飞书产品图片 / 产品截图不足。
- 飞书常用元素更多存在于 HTML/CSS/template 层,没有作为 Base 组件资产可检索。
- 视频、音频、产品 demo 链接暂未沉淀。

## 建议的 Base v2 格式

建议保留当前四张主表方向,但补强字段契约;`组件库` 冻结为 legacy optional,组件类能力写入 `素材库`;同时新增一张 `来源/入库任务` 表。Slide Library 继续本地优先,等真实复用稳定后再决定是否上云。

### 1. 场景索引

用途: planner 的第一跳,从 brief 判断应该采用哪类 pitch 逻辑。

建议字段:

| 字段 | 类型 | 说明 |
|---|---|---|
| 场景ID | 文本 / 唯一 | 稳定 key,如 `retail-first-visit-ai-base` |
| 场景标题 | 文本 | 人读名称 |
| Brief关键词 | 多选 / 文本 | 触发词 |
| 行业 | 多选 | 消费零售、制造、金融等 |
| 客户阶段 | 多选 | 首访、POC、续约、竞品替代等 |
| 业务场景 | 多选 | 门店运营、NPI、知识管理等 |
| 受众角色 | 多选 | CEO、CIO、业务负责人、销售等 |
| 决策目标 | 多选 / 文本 | 约会、立项、试点、预算、续约 |
| 核心冲突 | 长文本 | 这类 pitch 必须打中的矛盾 |
| 推荐叙事 | 长文本 | 主线,不是页面文案 |
| 默认页数 | 数字 | 例如 6、8、10 |
| 推荐页序 | JSON | 页面 role 列表,引用模板或内嵌简版 |
| 推荐模板ID | 文本 / 关联 | 可多个 |
| 必备知识类型 | 多选 | 行业洞察、客户案例、异议、指标等 |
| 必备素材类型 | 多选 | logo、产品截图、demo、头像、视频等 |
| 相关知识ID | 文本 / 关联 | 可多个 |
| 相关素材ID | 文本 / 关联 | 可多个 |
| 不适用条件 | 长文本 | 禁用边界 |
| 质量门禁 | 长文本 | 例如“必须有场景页、机制页、证据页” |
| 状态 | 单选 | draft / planner_ready / reusable / disabled |
| Owner | 人员 | 维护人 |
| 最近验证时间 | 日期 | 最近人工确认时间 |
| 标签 | 多选 | 检索辅助 |

### 2. Outline 模板库

用途: 给 planner 提供页序和每页职责,不是给 renderer 的最终 DeckJSON。

建议字段:

| 字段 | 类型 | 说明 |
|---|---|---|
| 模板ID | 文本 / 唯一 | 稳定 key |
| 模板名称 | 文本 | 人读名称 |
| 适用场景ID | 文本 / 关联 | 关联场景 |
| 模板类型 | 单选 | 首访、POC、案例包、思想 pitch 等 |
| Brief触发词 | 多选 / 文本 | 检索词 |
| 叙事结构 | 长文本 | 大纲逻辑 |
| 页序JSON | JSON | 每页 `key/role/message/proof_needed/asset_need/layout_candidate` |
| 默认页型 | 多选 | cover、content/2col、stats/row 等 |
| Layout组合 | 文本 / JSON | 防止连续同构页面 |
| 必备知识类型 | 多选 | 每套模板必须查的知识 |
| 必备素材类型 | 多选 | 每套模板必须查的素材 |
| 适用条件 | 长文本 | 使用场景 |
| 不适用条件 | 长文本 | 禁用边界 |
| 版本 | 文本 | v1、v2 |
| 状态 | 单选 | draft / planner_ready / reusable / disabled |
| 标签 | 多选 | 检索辅助 |

`页序JSON` 建议形状:

```json
[
  {
    "key": "business-gap",
    "role": "pain",
    "message": "旧流程的业务后果",
    "proof_needed": ["客户当前流程证据", "行业公开 pattern"],
    "asset_need": ["场景图", "流程断点示意"],
    "layout_candidate": {"layout": "content", "variant": "before-after"}
  }
]
```

### 3. 知识库

用途: planner 的原子知识来源。每条记录应是一条可引用的 claim / insight / talk track,不要存整篇 deck 文案。

建议字段:

| 字段 | 类型 | 说明 |
|---|---|---|
| 知识ID | 文本 / 唯一 | 稳定 key |
| 知识标题 | 文本 | 人读名称 |
| 知识类型 | 单选 | 行业洞察、场景痛点、客户案例、指标口径、产品能力、讲法经验、异议处理、风险提醒 |
| 适用场景ID | 文本 / 关联 | 关联场景 |
| Brief关键词 | 多选 / 文本 | 检索词 |
| 行业 | 多选 | 行业 |
| 业务场景 | 多选 | 场景 |
| 受众角色 | 多选 | 受众 |
| 决策目标 | 多选 | 目标 |
| 产品组合 | 多选 | 飞书、Base、Aily、知识问答等 |
| 正文/要点 | 长文本 | 原子知识内容 |
| 推荐讲法 | 长文本 | presenter 怎么讲 |
| 适合页型 | 多选 | pain、solution、case、evidence 等 |
| 证据/来源 | 长文本 | 来源摘要 |
| 来源等级 | 单选 | user-provided / approved-story / public-pattern / hypothesis |
| 可信度 | 单选 | high / medium / low |
| 权限状态 | 单选 | public / internal / restricted / needs_review |
| 不适用条件 | 长文本 | 禁用边界 |
| 关联素材ID | 文本 / 关联 | 可多个 |
| 来源文档URL | URL | 原始来源 |
| 来源页码/SlideKey | 文本 | 可追溯位置 |
| 有效期/复核时间 | 日期 | 过期后需复核 |
| 风险标记 | 多选 | 未授权、数字待确认、客户事实待确认等 |
| 状态 | 单选 | draft / planner_ready / reusable / disabled |
| SHA256 | 文本 | 去重 |
| 贡献者 | 人员 / 文本 | 来源人 |
| 标签 | 多选 | 检索辅助 |

### 4. 素材库

用途: renderer 的资源入口。所有可渲染素材都必须能被 asset id 解析成可用资源。

建议字段:

| 字段 | 类型 | 说明 |
|---|---|---|
| 素材ID | 文本 / 唯一 | 稳定 key,DeckJSON 引用它 |
| 素材名称 | 文本 | 人读名称 |
| 素材类别 | 单选 | 飞书icon、飞书产品图片、数字人头像、用户logo、飞书常用元素、图片、视频、音频、demo链接、页面模板、整页Slide、代码片段 |
| 渲染用途 | 多选 | cover-logo、icon、avatar、hero-image、mockup、background、video、audio、demo-iframe、component |
| 适用场景ID | 文本 / 关联 | 场景 |
| 适合页型 | 多选 | cover、content/2col、logo-wall、iframe-embed 等 |
| 行业 | 多选 | 行业 |
| 客户 | 文本 | 客户/品牌 |
| 产品组合 | 多选 | 产品 |
| DeckJSON引用Key | 文本 | 推荐等于素材ID |
| 组件Key | 文本 | 若是组件或常用元素 |
| Renderer加载方式 | 单选 | local-path / base-attachment / cloud-url / iframe / component-json / inline-svg |
| HTML渲染方式 | 单选 | img / background-image / video / audio / iframe / component-json / raw-html |
| Inline策略 | 单选 | must_inline / can_inline / can_link / iframe_only / no_inline |
| 资源URL | URL | 云端资源或 demo URL |
| 素材附件 | 附件 | 原始文件 |
| 本地路径 | 文本 | 同步后的 repo 相对路径 |
| TOS/Magic URL | URL | 可选分发地址 |
| MIME | 文本 | image/png、video/mp4 等 |
| 尺寸/时长 | 文本 | 1920x1080、00:30 等 |
| 缩略图 | 附件 / URL | 方便人工维护 |
| Alt文案 | 文本 | 可访问性和语义 |
| 可直接渲染 | 复选 | renderer 是否可直接使用 |
| 质量状态 | 单选 | reusable / needs_review / needs_redo / disabled |
| 权限状态 | 单选 | public / internal / restricted / needs_review |
| 摘要 | 长文本 | 用途说明 |
| 调用示例 | JSON | 推荐 DeckJSON 片段 |
| SHA256 | 文本 | 去重 |
| 来源 | 长文本 | 来源文件/URL/贡献人 |
| 贡献者 | 人员 / 文本 | 维护人 |
| 最后校验时间 | 日期 | 最近验证 |
| 标签 | 多选 | 检索辅助 |

关键规则:

- `Renderer加载方式 = base-attachment` 时,生成前必须下载附件到 `runs/<task>/input/assets/` 或 shared cache。
- `Inline策略 = must_inline` 的图片/音频/视频必须在最终 HTML 中内联或打包,不能只保留 URL。
- `demo链接` 通常只能 `iframe_only`,不要假装内联第三方系统。
- `视频/音频` 需要明确文件大小和移动端可用性;大文件默认不 inline,而是发布包内资源或受控 URL。

### 5. Legacy 组件库

结论:组件库不再作为主链路表维护。短期不删除表,但状态设为 `legacy_optional`;不人工入库、不作为 planner 检索源、不作为 renderer 必依赖。

组件类内容统一进入 `素材库`:

| 组件诉求 | 素材库承载方式 |
|---|---|
| 数据面板、persona card、产品 mockup | `素材类别=飞书组件` 或 `页面模板` |
| 可合入 DeckJSON 的片段 | `DeckJSON引用Key` + `调用示例` JSON |
| HTML / CSS / JS 片段 | `素材类别=代码片段`,设置 `HTML渲染方式` |
| 依赖图片、logo、截图 | `调用示例.dependencies` 或 `标签/摘要` 记录依赖素材ID |
| 版本和来源 | `来源`、`SHA256`、`最后校验时间` |

只有当未来出现稳定 props schema、组件版本兼容、截图测试和 renderer 组件注册表需求时,再恢复独立组件库。

### 6. 来源 / 入库任务

用途: 管理每次上传、解析、入库和复核,保证知识和素材可追溯。

建议字段:

| 字段 | 类型 | 说明 |
|---|---|---|
| 来源ID | 文本 / 唯一 | 稳定 key |
| 来源标题 | 文本 | 文件或项目名称 |
| 来源类型 | 单选 | brief、PPT、PDF、HTML deck、飞书文档、图片包、demo、人工录入 |
| 原始URL/路径 | URL / 文本 | 原始来源 |
| 权限状态 | 单选 | public / internal / restricted / needs_review |
| 解析状态 | 单选 | pending / parsed / failed |
| 验收状态 | 单选 | not_required / auditor_passed / auditor_failed |
| 入库状态 | 单选 | pending / partially_ingested / ingested / rejected |
| 关联知识ID | 文本 / 关联 | 抽取出的知识 |
| 关联素材ID | 文本 / 关联 | 抽取出的素材 |
| 关联Deck/Run | 文本 | 本地 run 或发布链接 |
| 贡献者 | 人员 / 文本 | 提交人 |
| 复核人 | 人员 / 文本 | 审核人 |
| 备注 | 长文本 | 处理记录 |
| 创建时间 | 日期 | 创建时间 |
| 更新时间 | 日期 | 更新时间 |

## Planner / Renderer 数据契约

### Planner 检索顺序

1. 用 brief 搜 `场景索引`,找到场景、决策目标和推荐叙事。
2. 用场景和 deck 类型搜 `Outline模板库`,确定页数、页序、每页职责和 layout candidate。
3. 用行业、客户阶段、产品组合搜 `知识库`,填充痛点、证据、案例、讲法和风险。
4. 用每页 `asset_need` 搜 `素材库`,生成 `asset_plan`。组件类能力也从素材库读取。
5. 找不到的内容必须进入 `open_questions` 或 `evidence_needed`,不要编。

### Renderer 解析顺序

1. 从 outline 的 `asset_plan[].id` 查 `素材库`。
2. 如果是 Base 附件,先下载到 run workspace 或 shared cache。
3. 如果是本地路径,校验文件存在。
4. 如果是 cloud URL,按 `Inline策略` 决定下载、iframe,或拒绝。
5. 生成 DeckJSON 时只写可渲染本地路径、data URI、或明确允许的 iframe URL。
6. 最终交付时用 `render-deck.py --inline` 或 `copy-assets.py --shared=copy` 保证 HTML/包可独立打开。

## 维护 SOP

### 新增知识

1. 确认来源等级和权限状态。
2. 把整篇资料拆成原子记录:一个痛点、一个证据、一个案例、一条异议或一段 talk track。
3. 填写 `知识类型`、`适用场景ID`、`行业`、`业务场景`、`受众角色`、`决策目标`、`产品组合`。
4. `正文/要点` 写事实或经验,`推荐讲法` 写怎么讲。
5. 填写 `证据/来源`、`来源文档URL`、`来源页码/SlideKey`。
6. 如果不是可公开事实,状态先设为 `needs_review` 或 `draft`。
7. 至少用 3 个可能 brief 关键词检索验证能命中。

### 新增素材

1. 上传原文件到 `素材附件`,或填写可信 `资源URL` / `本地路径`。
2. 设置 `素材类别`、`渲染用途`、`Renderer加载方式`、`HTML渲染方式`、`Inline策略`。
3. 填写 MIME、尺寸/时长、缩略图、Alt 文案。
4. 检查权限状态;客户 logo、截图、现场照默认 `needs_review`,确认后再 `internal` 或 `approved`。
5. 填写 `DeckJSON引用Key`,建议与 `素材ID` 一致。
6. 写一个最小 `调用示例`,说明 renderer 应如何使用。
7. 跑一次素材同步和本地渲染验证。

### 组件类需求处理

1. 先判断是否已有 DeckJSON layout 或素材库条目可表达。
2. 能用 DeckJSON 片段表达的,作为 `素材类别=飞书组件` 或 `代码片段` 写入素材库。
3. 依赖素材放入 `调用示例.dependencies`,并保留 `DeckJSON引用Key`。
4. 用 `validate-deck.py` 或最小 demo deck 验证片段。
5. 暂不新增组件库记录;确需独立组件表时先提交 schema/renderer 需求评审。

### 入库 deck 的处理

1. 先通过 `deck-auditor`。
2. 预演通过后,等用户确认不再改稿。
3. 用户确认入库后再运行 `deck-ingestor`。
4. 入库时拆分为:
   - 知识: 主张、场景、证据、讲法、风险。
   - 素材: 图片、logo、截图、demo、DeckJSON fragment、组件类片段。
   - Slide 候选: 继续保存在本地候选库,等待维护人审核。
5. 模拟客户反馈不能当真实客户事实入库。

## 建议维护命令

检查 Base 可用性:

```bash
python3 scripts/base_library.py doctor --probe
```

搜索知识 / 素材:

```bash
python3 scripts/base_library.py search-scenarios "<关键词>" --limit 10
python3 scripts/base_library.py search-outline-templates "<关键词>" --limit 10
python3 scripts/base_library.py search-knowledge "<关键词>" --limit 10
python3 scripts/base_library.py search-assets "<关键词>" --limit 20
```

`search-components` 仅保留为 legacy 排查命令,日常维护不使用。

同步 Base 素材附件到本地 shared cache:

```bash
python3 scripts/base_library.py sync-shared-assets --export-index
```

重建本地素材索引:

```bash
python3 skills/deck-renderer/assets/catalog-assets.py
```

验证本地知识和 Slide Library:

```bash
python3 server/pitch_recipes.py validate
python3 server/slide_library.py validate
```

## 当前优先级建议

1. 先填充 live Base 的最小可用集:每个常见 pitch 场景至少 1 条场景索引、1 套 outline 模板、5-10 条知识、3-5 个素材。
2. 把本地 355 个 shared assets 批量写入 live `素材库`,并保证附件或本地路径可同步。
3. 补齐飞书 icon、产品截图、产品 demo、常用组件素材。
4. 清理 `library/business/candidates/` 的重复 slide key,恢复 Slide Library gate。
5. 扩展 renderer asset resolver:支持 `asset_id -> Base record -> 下载到 run -> DeckJSON 本地路径 -> inline HTML` 的完整闭环。
6. 等内容稳定后,再把 Slide 候选是否上云作为第二阶段。
