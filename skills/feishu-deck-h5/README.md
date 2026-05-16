# feishu-deck-h5

一个 [Claude Code](https://claude.com/claude-code) skill，用来生成**飞书/Lark 风格的深色商务汇报材料**——但产物不是 `.pptx`，而是一个**单文件 HTML deck**：1920×1080 设计画布、自动缩放适配窗口、内置移动端竖向浏览模式，效果上和手搓的 Lark sales deck 几乎看不出区别。

适用于客户提案、季度复盘、汇报材料、对外宣讲等场景。默认中文单语；显式要求才出双语。

## 安装

把仓库 clone 到 Claude Code 的 skills 目录：

```bash
git clone https://github.com/FuQiang/feishu-deck-h5.git ~/.claude/skills/feishu-deck-h5
```

下次启动 Claude Code，skill 会自动被加载。

## 使用

在 Claude Code 里直接说人话即可，例如：

- 「帮我做一份飞书风格的 PPT，主题是 Q2 客户复盘」
- 「用 h5 deck 给我做一个 16:9 网页演示」
- 「把这份 outline 改成飞书风格的汇报材料」

Claude 会按照 `SKILL.md` 里的流程：
1. **preflight** — 校验本地挂载（这个 skill 不在临时会话目录里跑，必须挂到你本地真实路径）
2. **new-run** — 在仓库根建一个 `runs/<时间戳>/` 工作目录
3. **render** — 生成 `runs/<时间戳>/output/index.html`，浏览器直接打开

预览样例可看 `preview-dark.html` 或 `examples/sample-deck.html`。

## 目录结构

```
feishu-deck-h5/
├── SKILL.md                 # skill 主入口，给 Claude 看的
├── assets/                  # CSS / JS / 品牌素材 / 渲染脚本
├── templates/               # slide 片段模板
├── examples/                # 可参考的成品 deck
└── README.md
```

生成的 deck 会落在**仓库根**的 `runs/<时间戳>/output/` 下，而不是塞在 skill 内部——这样多次生成不会互相覆盖，且可以直接 `git commit`。

## License

MIT
