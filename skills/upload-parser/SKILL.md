---
name: upload-parser
description: |
  Use this skill when the user provides PDF, PPT/PPTX, HTML deck, Feishu/Lark
  document, images, screenshots, demo files, or other source materials together
  with a brief and wants Cyrus to create, convert, rewrite, or modify an H5 deck.
  It decomposes uploads into a structured source dossier with separate knowledge
  layer and material layer outputs for deck-planner, deck-renderer, and
  deck-ingestor. Do not use it for a standalone HTML deck quality check; route
  that to deck-auditor.
---

# upload-parser

目标:把用户上传的 PDF / PPT / HTML / 飞书文档 / 图片 / demo / 素材包解析为结构化输入,拆成“知识层”和“素材层”,让后续 planner 知道讲什么,renderer 知道可用什么,ingestor 知道哪些内容可沉淀。

这个 skill 不负责生成 deck、不负责验收、不负责入库。它只做 source inventory 和内容分层。

## 入口边界

- 用户只有 HTML deck,只问“合不合格 / 能不能入库 / 哪里不对”:不要用本 skill,直接走 `deck-auditor`。
- 用户有 brief,并带 PDF / PPT / HTML / 飞书文档 / 图片 / demo,要求转换、改版、重做或基于材料生成:先用本 skill。
- 用户明确说“把这份 PPT 放进 Slide Library / 自选 PPT 库 / 以后可插页复用”:先记录为 slide-library source inventory;若只是登记候选,交给 `deck-ingestor --ppt-library`;若要拆成可生成素材,本 skill 继续输出 source dossier。
- 用户只给纯文字 brief,没有上传物:不要用本 skill,直接走 `deck-planner`。

## 输出

默认输出:

```text
input/runtime-library/source-dossier.json   # 结构化解析结果,供 planner / renderer / ingestor 消费
input/runtime-library/SOURCE_DOSSIER.md     # 内部摘要,默认不作为用户交付物暴露
input/runtime-library/assets/               # 可选:抽取出的图片、缩略图、页面渲染图、附件索引
```

核心字段:

- `source_inventory`: 文件名、类型、页数/slide 数、语言、标题、来源链接、处理方式。
- `knowledge_layer`: 场景、主张、痛点、证据、案例、讲法线索、术语、风险、引用来源。
- `material_layer`: slide 缩略图、截图、logo、图片、图表、表格、HTML 片段、layout 线索、可复用素材。
- `slide_layer`: 每页/每段的标题、正文摘要、原始顺序、页面编号、可复用价值。
- `slide_library_upload`: 若来源是用户自选 PPT,记录原始 PPT 路径/链接、页码、候选 slide key、权限状态和是否已登记到 Slide 库。
- `provenance`: 每条知识和素材来自哪个文件、页码、节点、截图或链接。
- `confidence`: 抽取置信度和需要人工确认的点。
- `handoff`: 给 `deck-planner`、`deck-renderer`、`deck-ingestor` 的结构化交接对象,每个目标包含 `target_skill`、`payload_schema`、`consumes`、`ready`、`notes`。

`source-dossier.json` 必须符合:

```text
skills/lark-deck-cyrus/schema/source-dossier.schema.json
```

不要把 `SOURCE_DOSSIER.md` 传给下游 agent;它只是人读摘要。下游只消费
`source-dossier.json` 和其中的结构化 handoff。

## 可执行入口

本 skill 配有标准库实现的轻量解析器,用于把本地文件/目录/URL 生成 source dossier:

```bash
python3 skills/upload-parser/parse.py \
  path/to/source.pptx path/to/source.html \
  --brief "给零售客户做飞书 Base 提案" \
  --output-dir runs/<task-id>/output
```

它会输出 `source-dossier.json` 和 `SOURCE_DOSSIER.md`;在 Cyrus 服务端工作流中这些文件会被放进 `input/runtime-library/`,不复制到 `output/` 作为重复交付物。支持:

- PPTX:统计页数,抽取每页文本和 `ppt/media/*` 素材清单。
- PPT:登记为单页来源,等待人工/后续转换。
- PDF:统计页数,保留来源和页序。
- HTML:抽取 `.slide` / `data-slide-key`、正文、图片、脚本和样式依赖。
- 图片/视频/目录/URL:登记素材层和 provenance。

生成后可用 contract validator 校验:

```bash
python3 skills/lark-deck-cyrus/schema/validate-contract.py \
  --schema skills/lark-deck-cyrus/schema/source-dossier.schema.json \
  --instance runs/<task-id>/input/runtime-library/source-dossier.json
```

用户要把 PPT/PPTX 先放入本地 Slide Library 自选库时:

```bash
python3 skills/upload-parser/parse.py path/to/team.pptx \
  --register-ppt-library \
  --title "团队自选 PPT" \
  --page 3 \
  --page 8
```

该模式只登记本地候选页,不写云端 Base。

## 工作流

1. **分类上传物**
   - PDF / PPT:先记录页数,保留原始页面顺序和章节节奏。若用户目标是“自选 PPT 入 Slide Library”,不要压缩或重写;先把每页登记为可选候选,后续再按用户选择拆知识/素材。
   - HTML deck:解析 `.slide`、`data-slide-key`、标题、正文、图片、脚本和样式依赖。
   - 飞书文档:抽取标题层级、段落、表格、图片、附件、引用链接。
     飞书文件 URL 只作为 provenance / 素材引用记录;真正用于 deck 的文件素材由
     `deck-renderer/deck-json/materialize-feishu-assets.py` 在渲染前下载为本地
     `assets/source-media/*`,不要把登录态 URL 当成最终图片地址。
   - 图片 / demo / 素材包:解析用途、尺寸、可访问性、可能关联的 slide 或主张。

2. **做 source inventory**
   - 记录每个来源的页数、章节、标题、关键对象和缺失项。
   - 不默认压缩 PDF/PPT 页数;压缩或改写由 planner / renderer 在后续基于用户目标决定。
   - 对旧 HTML,只做解析;是否合格由 `deck-auditor` 判断。

3. **拆知识层**
   - 抽取业务场景、客户/行业、核心主张、痛点、证据、案例、讲法、异议和风险。
   - 每条知识都要带 provenance,不要把推断写成事实。
   - 无法确认的客户事实写入 `confidence.needs_confirmation`。

4. **拆素材层**
   - 抽取可复用 slide、页面图、产品截图、logo、icon、照片、图表、demo 链接和 HTML 片段。
   - 为每个素材记录类型、尺寸、来源、适合用途、是否需要授权或人工替换。
   - 不在本阶段上传云端库;只给 `deck-ingestor` 准备候选。

5. **交给下游**
   - `deck-planner` 使用 knowledge_layer 生成 outline。
   - `deck-renderer` 使用 material_layer 和 slide_layer 落地视觉与素材。
   - `deck-ingestor` 在 auditor 通过后使用 provenance 与候选记录入库。

## 硬规则

- 不生成 HTML deck。
- 不给“合格 / 不合格”最终判断。
- 不直接写云端库。
- 不把 simulator 的预测或自己的推断写成真实客户反馈。
- 不丢页、不静默压缩、不改变原始材料顺序;任何删减都必须由 planner 或用户显式决定。
- 所有知识和素材候选都必须可追溯到原始来源。
