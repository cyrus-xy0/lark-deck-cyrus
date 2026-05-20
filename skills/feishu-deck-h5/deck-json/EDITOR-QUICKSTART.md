# deck-editor · QUICKSTART

可视化编辑 feishu-deck-h5 deck.json 的本地工具。**零依赖**（只需 Python 3.11+，macOS / Linux 自带）。

---

## 一键启动（3 选 1）

### 选项 A · Shell alias（推荐）

```bash
echo "alias edit-deck='python3 ~/Documents/GitHub/feishu-deck-h5/skills/feishu-deck-h5/deck-json/deck-editor.py'" >> ~/.zshrc
source ~/.zshrc
```

之后任何目录直接打：

```bash
edit-deck                                # 自动找最近的 deck.json
edit-deck path/to/my-deck.json           # 指定路径
```

### 选项 B · Dock 图标（GUI 双击）

把 `deck-json/deck-editor.command` 拖到 Dock 右侧（Stack 区）。

- **双击** → 打开最近的 deck.json
- **把 deck.json 文件拖到这个 Dock 图标** → 打开那个 deck

### 选项 C · 系统命令（symlink）

```bash
ln -s ~/Documents/GitHub/feishu-deck-h5/skills/feishu-deck-h5/deck-json/deck-editor.py /usr/local/bin/edit-deck
```

---

## 第一次使用

```bash
# 1. 克隆 repo
git clone <repo-url> ~/Documents/GitHub/feishu-deck-h5

# 2. 创建你的 deck.json
mkdir -p ~/Documents/GitHub/feishu-deck-h5/runs/my-first-deck/output
cp ~/Documents/GitHub/feishu-deck-h5/skills/feishu-deck-h5/deck-json/examples/sample-deck.json \
   ~/Documents/GitHub/feishu-deck-h5/runs/my-first-deck/output/deck.json

# 3. 启动
edit-deck    # (装了 alias 之后)
```

浏览器自动打开 → 开始编辑。

---

## 编辑器布局

```
┌───────────────────────────────────────────────────────────────────┐
│ deck-editor · <title> · N slides   导入 全屏 ↻Render ⟳Reload [就绪]│
├─────────────┬─────────────────────────────────┬───────────────────┤
│ SLIDES      │  PREVIEW (16:9, fit-to-pane)    │  SLIDE INSPECTOR  │
│ 01 cover    │  ┌───────────────────────────┐  │  Key / Layout     │
│ 02 agenda   │  │                           │  │  Variant 下拉切换 │
│ 03 ... ▶   │  │   双击文字直接编辑          │  │  Screen label     │
│             │  │                           │  │  Title (auto-save)│
│ +拖动排序   │  │   blur → 保存             │  │  Extras 按 layout │
│             │  │                           │  │  Accent · Decor   │
│             │  └───────────────────────────┘  │  ─── Arrays ───   │
│             │                                 │  ▶ Cards (3 / 3)  │
│             │                                 │  ▶ etc.           │
└─────────────┴─────────────────────────────────┴───────────────────┘
```

---

## 常用编辑

| 想做 | 怎么做 |
|---|---|
| 改文字 | 双击 preview 里的文字 → 改 → 鼠标点别处保存 |
| 单行字段(标题等) 提交 | `Enter` 直接保存 · `Shift+Enter` 才换行 |
| 多行字段(正文等) 提交 | `Cmd+Enter` 保存 · `Enter` 是换行 |
| 取消改动 | `Esc`(在编辑中) → 恢复改前 |
| 重排 slide | 左边 slide 列表拖动 → 看缝隙横线落点 |
| 加 / 删 slide | Inspector 底部"复制此页" / "删除" 按钮 |
| 改 slide layout | Inspector "Variant" 下拉(content/stats/flow 三层) |
| 改 accent 颜色 | Inspector "Accent" 下拉 (blue/teal/violet/purple/orange) |
| 改装饰背景 | Inspector "Decor" 输入框,逗号分隔 (`blue-glow,grain`) |
| 加 card / col / node 等数组项 | Inspector 底部数组区 "+ 添加" |
| 改某张 card 字段 | Inspector 底部展开 card #N → 改 → blur 自动保存 |
| 导入别的 deck 的 slide | 顶栏"导入幻灯片" → 选 deck.json → 勾选要导入的 slide |
| 全屏 preview | 顶栏 "⛶ 全屏" 按钮 / `Esc` 退出 |
| 跑完整 render | 顶栏 "↻ Render" / `Cmd+S` |
| 重载 deck.json | 顶栏 "⟳ Reload" |

---

## 输出文件

每次编辑后，deck.json 自动 backup 为 `<deck>.json.bak-pre-<command>-<timestamp>`（万一改坏可以恢复）。

`_preview/` 目录是 editor 内部 render 出来的 HTML，**不用直接用**。最终交付：

```bash
# 完整渲染 + 自包含 output/ (含 assets/ + texts.md)
python3 .../render-deck.py runs/my-deck/output/deck.json runs/my-deck/output/

# 单文件 inline 模式 (适合邮件附件)
python3 .../render-deck.py runs/my-deck/output/deck.json runs/my-deck/output/ --inline
```

---

## 故障排查

| 症状 | 处理 |
|---|---|
| 浏览器没自动开 | console 看打印的 URL,手动复制粘贴 |
| `no deck path given and none auto-detected` | 显式 `edit-deck path/to/deck.json` 或 cd 到含 `runs/` 的目录 |
| 端口被占 | `edit-deck deck.json --port 7421` |
| 远程 / SSH | `edit-deck deck.json --no-browser`,然后从本地用 SSH port-forward |
| 改完文字看不到变化 | 编辑器为流畅故意不每次都 reload iframe。点 "↻ Render" 或做结构操作触发 |
| 编辑器要做的事 schema 装不下 | 用 `layout: raw` slide,把 HTML 手写在 `data.html` |

---

## 用法层次

- **80% 场景**：浏览器双击编辑 + Inspector 改字段
- **15% 场景**：直接编辑 deck.json 文件（结构性大改,然后 ⟳ Reload）
- **5% 场景**：跳到 raw HTML 自由发挥（schema 装不下的 layout）

更多细节看：
- `deck-schema.json` — 字段定义
- `MIGRATION-REPORT.md` — 设计取舍 + 历史
- `README.md` — Phase 0 schema 说明
