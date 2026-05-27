# Cloud Agent Deployment

目标:用户可以把一句话交给自己的云端 agent（如飞书 Aily、OpenClaw 或类似执行环境）,让它部署 Cyrus,随后通过一句 brief 生成可预览、可下载的 deckhtml。

## 一句话提示词

```text
请部署 lark-deck-cyrus：获取或更新 https://github.com/cyrus-xy0/lark-deck-cyrus，运行 bash install.sh；如果云端不能下载浏览器组件，先设置 LARK_DECK_CYRUS_SKIP_PLAYWRIGHT_INSTALL=1。然后运行 python3 scripts/cloud_agent_deploy.py --output deploy/cloud-agent --base-url <你的公网访问域名>，复制 deploy/cloud-agent/env.example 为 .env 并填好必要环境变量，启动 bash deploy/cloud-agent/start-generator.sh，确认 deploy/cloud-agent/healthcheck.sh 通过。部署完成后，我可以直接对你说“给某客户/主题做一份飞书风格 H5 deck”，你调用 POST /decks 生成 deckhtml，并返回 preview_url、download_url 和 edit_url。
```

注意:默认用 HTTPS 地址,不要把仓库地址改成 `git@github.com:...`。多数云端 agent
没有 GitHub SSH key,使用 SSH 会在 clone 前卡住。

## Agent 执行流程

1. 获取代码:使用用户有权限的 GitHub URL clone 或 pull 仓库。
2. 安装依赖:运行 `bash install.sh`。受限云环境可设置 `LARK_DECK_CYRUS_SKIP_PLAYWRIGHT_INSTALL=1`,此时基础生成可用,严格视觉审计会降级。
3. 生成部署包:

```bash
python3 scripts/cloud_agent_deploy.py \
  --output deploy/cloud-agent \
  --base-url https://your-agent.example.com
```

4. 配置环境:复制 `deploy/cloud-agent/env.example` 为 `.env`。如果 bundle 被复制到仓库外,设置 `LARK_DECK_CYRUS_ROOT` 指回仓库根目录。
5. 启动服务:运行 `bash deploy/cloud-agent/start-generator.sh`。需要飞书 bot 收消息时,再配置飞书事件订阅并启动 `bash deploy/cloud-agent/start-feishu-bot.sh`。
6. 验证:运行 `bash deploy/cloud-agent/healthcheck.sh`,或访问 `<base-url>/health`。
7. 使用:agent 收到用户 brief 后调用 `POST /decks`,把返回的 `preview_url`、`download_url`、`edit_url` 发给用户。

## 环境变量

- `GENERATOR_PUBLIC_BASE_URL`:用户能访问到的公网根地址。
- `GENERATOR_PORT`:默认 `8765`。
- `LARK_DECK_CYRUS_ROOT`:当部署包不在仓库内时必填。
- `LARK_LIBRARY_MODE`:默认 `auto`。`base` 表示 live Base 不可用时直接失败。
- `LARK_LIBRARY_AS`:默认 `user`;云端 bot 写 Base 时可设为 `bot`。
- `LARK_LIBRARY_BASE_TOKEN`:可选覆盖。当前仓库默认配置已指向用户指定 Base `DBtybdvHYaovVwsWLatcipJBnrg`,但真实读写仍需要云端 agent 的 `lark-cli` 身份有权限。

## Base 策略

Slide Library 不迁移到云端,继续作为本地整页候选库。飞书 Base 只承载:

- `知识库`:负责怎么讲,例如主张、证据、案例、talk track、异议和风险。
- `素材库`:负责怎么呈现,例如图片、logo、截图、video、demo、DeckJSON fragment 和附件。

知识和素材的映射通过 `关联SlideKey`、`关联素材ID`、`关联知识ID` 以及来源字段保留；当目标 Base 暂缺这些字段时,写入脚本会把关系降级写进 `适用页面`、`来源` 和 `标签`,避免中断生成链路。
