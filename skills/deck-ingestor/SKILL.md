---
name: deck-ingestor
description: |
  Use this skill when a Cyrus H5 deck, uploaded HTML deck, slide, extracted
  material, or source-dossier knowledge needs to be saved into the cloud library
  for reuse. It writes asset/material and knowledge records into Feishu Base,
  while Slide Library remains a local candidate library for now. Do not use it
  to validate or fix decks; validation belongs to deck-auditor and production
  belongs to deck-renderer.
---

# deck-ingestor

目标:把通过验收的知识和素材沉淀到云端库,把整页 slide 沉淀到本地候选库,让后续 `deck-planner` 能复用“讲什么”,`deck-renderer` 能复用“怎么呈现”。

这个 skill 是入库执行者,不是验收者。HTML deck、slide 和呈现素材入库前必须有 `deck-auditor` 的通过结论;知识候选可以由用户明确标记为“仅知识入库”,但必须保留来源和风险。

## 入库对象

分三类沉淀,不要混成一个大记录:

- **知识库 records**:场景、客户/行业、主张、证据、案例、talk track、异议、风险、来源;显式 `--write-base` 时可写入飞书 Base。
- **素材库 records**:图片、logo、icon、截图、demo、附件、页面渲染图、可复用 HTML 片段;显式 `--write-base` 时可写入飞书 Base。
- **Slide 库 records**:slide key、layout、DeckJSON fragment、HTML fragment、thumbnail、文本摘要、标签、来源 deck;当前只写本地候选库。

Slide Library 的含义不是把所有东西塞进第三张表。`知识库` 表达这页“怎么讲”,
`素材库` 表达这页“怎么呈现”;当前先不建云端 Slide 表,本地 Slide 候选库只保存
整页可选复用单元,并通过 slide key / source deck / source ppt 追溯到后续可拆出的
知识与素材。

## 前置条件

- 上传 HTML deck 入库:必须先走 `deck-auditor`;通过才入 slide / 素材库,失败只返回失败理由。
- 新生成 deck 入库:标准链路是 `deck-renderer -> deck-auditor -> pitch-simulator -> deck-ingestor`。
- brief + 素材场景:优先读取 `upload-recognizer` 的 source dossier,再结合 `deck.json`、`FEEDBACK.md`、audit report 和 rehearsal report。
- 涉及客户真实数据、商标、截图、内部文档时,必须保留来源和权限状态;不确定就标为 `needs_review`。

## 输出

默认产出:

```text
ingestion-manifest.json   # 写入计划、记录 id、失败项和回滚提示
INGESTION_REPORT.md       # 用户可读入库报告
```

核心字段:

- `source`: deck、HTML、source dossier、audit report、rehearsal report。
- `knowledge_records`: 写入知识库的记录和来源。
- `asset_records`: 写入素材库的记录、文件路径、缩略图和权限状态。
- `slide_records`: 写入本地 slide 候选库的 slide key、layout、fragment、thumbnail 和标签。
- `skipped`: 未入库项及原因。
- `cloud_refs`: 云端库记录 id、URL 或 token。
- `next_reuse`: 下次 planner / renderer 检索时应该使用的标签。

## 可执行入口

通过验收后的本地 run 可以直接入库为复用候选:

```bash
python3 skills/deck-ingestor/ingest.py \
  --task-id <runs-dir-name> \
  --title "<deck title>" \
  --industry "<industry>" \
  --product "飞书"
```

默认会读取 `runs/<task-id>/output/deck.json`,把可复用的非封面/封底页写入本地候选库,并在同一 run 输出 `ingestion-manifest.json` 和 `INGESTION_REPORT.md`。只入指定页时重复传 `--slide-key <key>`。

需要同步到飞书 Base 时显式加 `--write-base`;这会调用 `scripts/base_library.py create-knowledge` 写入知识库,调用 `create-asset-record` 把每页 DeckJSON fragment 作为素材元数据写入素材库。Slide Library 暂时只保存在本地候选库,不会写云端 Slide 表。要求 `LARK_LIBRARY_BASE_TOKEN` 和 `lark-cli` 可用。没有 live Base 时必须失败并写入失败原因,不能伪造云端记录:

```bash
python3 skills/deck-ingestor/ingest.py \
  --task-id <runs-dir-name> \
  --write-base \
  --base-as user
```

调试 Base 字段映射时可用 `--dry-run-base`,只打印将写入的 JSON,不访问 live Base。
Base 字段映射必须保留知识/素材关系:目标表有 `关联SlideKey`、`关联素材ID`、
`关联知识ID`、`来源Deck`、`来源PPT`、`来源页码` 和 `权限状态` 时优先写这些
显式字段;若当前 Base 表暂缺字段,则把同一关系降级写入 `适用页面`、`来源` 和
`标签`。这样 Slide Library 虽然不建云端 Slide 表,仍能由“讲什么”的知识记录和
“怎么呈现”的素材记录联合表达。

用户直接上传一份想作为 Slide Library 自选来源的 PPT/PPTX 时,可以先登记为
可选候选,不立即转换成 H5:

```bash
python3 skills/deck-ingestor/ingest.py \
  --ppt-library path/to/team-slides.pptx \
  --title "团队自选 PPT" \
  --industry "消费零售" \
  --product "飞书" \
  --ppt-page 3 \
  --ppt-page 8
```

不传 `--ppt-page` 时默认登记全部页。该模式会在本地 Slide 候选库生成
`replica` 占位记录和本地 SVG 缩略图,标记 `needs_review`;即使加 `--write-base`,PPT 自选登记也不写 Base,
要等 `upload-recognizer` / `deck-renderer` 把选中页拆出知识与素材后,再同步这两类记录。

## 工作流

1. **读取验收结论**
   - `deck-auditor` 失败时,不要入库 deck / slide / 呈现素材。
   - 如果用户只要知识候选入库,必须把风险标成 `knowledge_only` 和 `needs_review`。

2. **拆分入库层**
   - 知识层服务 planner:主张、场景、证据、讲法、风险。
   - 素材层服务 renderer:文件、截图、图表、logo、demo、HTML 片段。
   - Slide 层服务复用:可插入页、layout、DeckJSON fragment、缩略图;当前只本地保存。

3. **去重与标签**
   - 用 slide key、文件 hash、来源 URL、客户名、行业、产品模块和 layout 做去重。
   - 标签至少覆盖:行业、客户阶段、产品、场景、layout、来源 deck、权限状态。

4. **写入云端库**
   - 先写素材文件或对象存储,再写素材记录。
   - 再写知识 records,引用 slide key / source deck / 素材来源。
   - 不写云端 Slide 表;Slide 候选记录留在本地库。
   - 任一步失败都写入 `skipped` 和可重试原因,不要伪造成功 id。

5. **回传复用结果**
   - 返回云端记录引用和下次检索关键词。
   - 把不可入库原因交回 `deck-auditor` 或 `deck-planner`。

## 硬规则

- 不绕过 auditor 把失败 HTML deck 入 slide / 素材库。
- 不把 `pitch-simulator` 的 simulated quote、预测阻力或成交判断当成真实客户事实入库。
- 不丢 provenance;每条记录都要能追到来源文件、页码、slide key 或用户 brief。
- 不把知识、素材、slide 混写到同一类库。
- 不自动上传敏感或权限不明的客户材料;标记 `needs_review` 并等待用户确认。
