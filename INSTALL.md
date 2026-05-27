# Install — agent-readable spec

> This file is the canonical install procedure for the lark-deck-cyrus product skills:
> `lark-deck-cyrus`, `upload-recognizer`, `deck-planner`, `deck-renderer`,
> `deck-auditor`, `pitch-simulator`, and `deck-ingestor`.
> If you are a Claude (or any AI agent) and the user asked you to install
> this skill from a git URL, follow these steps in order.
> If you are a human, [README.md](./README.md) is friendlier.

## TL;DR for the user

Tell your Claude agent:

> "帮我安装 lark-deck-cyrus 这个 skill：`https://github.com/cyrus-xy0/lark-deck-cyrus`"

Use the HTTPS URL above by default. If the user pasted
`git@github.com:cyrus-xy0/lark-deck-cyrus.git`, replace it with
`https://github.com/cyrus-xy0/lark-deck-cyrus.git` before cloning. Do not ask
the user for an SSH key or Personal Access Token for the public repository
unless the HTTPS clone also fails.

The agent will detect your harness, install the product skills, and verify.

---

## Decision tree (for the agent)

Run these checks **in order**, stop at the first match:

### 1. Plugin marketplace path (Claude Code with `/plugin` support)

**Detect:** the user is running Claude Code CLI / Claude Desktop and `/plugin marketplace add` is a known slash command.

**Action — instruct the user to run:**

```
/plugin marketplace add https://github.com/cyrus-xy0/lark-deck-cyrus
/plugin install lark-deck-cyrus@lark-deck-cyrus
```

Then restart the session. (Slash commands cannot be invoked by an agent — the user has to type them.)

**Verify:** after restart, `bash ~/.claude/skills/deck-renderer/assets/preflight.sh` should print `PREFLIGHT OK`.

### 2. install.sh path (any harness with `~/.claude/skills/` convention)

**Detect:** plugin marketplace not available, but `~/.claude/skills/` (or `$CLAUDE_DIR/skills/`) is the skill registration directory.

**Action — run as the user:**

```bash
git clone https://github.com/cyrus-xy0/lark-deck-cyrus.git /tmp/lark-deck-cyrus-installer
bash /tmp/lark-deck-cyrus-installer/install.sh
rm -rf /tmp/lark-deck-cyrus-installer
```

For non-Claude-Code harnesses (e.g. openclaw if it uses a different skill root), set `CLAUDE_DIR` first:

```bash
CLAUDE_DIR=~/.openclaw bash install.sh
```

**Verify:** the script symlinks the product skills, installs project-local
Playwright + Chromium into `.deps/` for visual audits, then auto-runs
`preflight.sh` for `deck-renderer`.
Look for `PREFLIGHT OK`.

### 3. Manual path (fallback when nothing else fits)

```bash
git clone https://github.com/cyrus-xy0/lark-deck-cyrus.git ~/Projects/lark-deck-cyrus
mkdir -p ~/.claude/skills
ln -s ~/Projects/lark-deck-cyrus/skills/lark-deck-cyrus ~/.claude/skills/lark-deck-cyrus
ln -s ~/Projects/lark-deck-cyrus/skills/upload-recognizer ~/.claude/skills/upload-recognizer
ln -s ~/Projects/lark-deck-cyrus/skills/deck-planner ~/.claude/skills/deck-planner
ln -s ~/Projects/lark-deck-cyrus/skills/deck-renderer ~/.claude/skills/deck-renderer
ln -s ~/Projects/lark-deck-cyrus/skills/deck-auditor ~/.claude/skills/deck-auditor
ln -s ~/Projects/lark-deck-cyrus/skills/pitch-simulator ~/.claude/skills/pitch-simulator
ln -s ~/Projects/lark-deck-cyrus/skills/deck-ingestor ~/.claude/skills/deck-ingestor
python3 -m pip install --upgrade --target ~/Projects/lark-deck-cyrus/.deps/python -r ~/Projects/lark-deck-cyrus/requirements.txt
PYTHONPATH=~/Projects/lark-deck-cyrus/.deps/python PLAYWRIGHT_BROWSERS_PATH=~/Projects/lark-deck-cyrus/.deps/ms-playwright python3 -m playwright install chromium
bash ~/.claude/skills/deck-renderer/assets/preflight.sh
```

---

## Prerequisites (verify before installing)

- Public install path uses HTTPS and does not require a GitHub SSH key.
- For a private fork, use a URL the environment can access: HTTPS + Personal
  Access Token, or SSH after `ssh -T git@github.com` returns `Hi <user>!`.
- Collaborator access if the repository or fork is private.
- `python3`, `bash`, `node` on PATH (used by build/validate)
- `python3 -m pip` available. `install.sh` uses it to install Playwright into
  project-local `.deps/python`, then downloads Chromium into
  `.deps/ms-playwright` by default. For offline installs, set
  `LARK_DECK_CYRUS_SKIP_PLAYWRIGHT_INSTALL=1` and visual audits will be skipped
  until dependencies are installed.
- No Feishu/Lark Base access is required for first use. The package falls back
  to local `knowledge/` and `assets/shared/` cache files. Internal users can set
  `LARK_LIBRARY_BASE_TOKEN` and `LARK_LIBRARY_MODE=base` to require live Base.
  The default internal Base is `DBtybdvHYaovVwsWLatcipJBnrg` and covers only
  `知识库` / `素材库`; Slide Library remains a local candidate library.
- To hand the same generator/bot to a cloud agent, run
  `python3 scripts/cloud_agent_deploy.py --output deploy/cloud-agent --base-url <public-url>`.
  It writes start scripts, `.env` template, health check, endpoint manifest and
  `ONE-SHOT-PROMPT.md`; it does not deploy remotely or copy secrets. See
  `CLOUD_AGENT.md` for the exact agent prompt.

If a user pasted an SSH URL such as `git@github.com:...` and the agent reports
SSH authentication failure, switch to the HTTPS URL first:

```bash
REPO_URL=https://github.com/cyrus-xy0/lark-deck-cyrus.git bash install.sh
```

### Don't have collaborator access yet?

If `git ls-remote <repo-url> HEAD` fails with
"Repository not found" or "Permission denied", the URL may point at a private
fork or an account without access.

When using an SSH URL, `install.sh` detects this and exits with **code 2**,
printing a copy-pasteable Lark/Feishu message template (with the user's GitHub
username pre-filled when available) for them to send to FuQiang. The agent
should:

1. Show the printed template to the user verbatim
2. Tell them to paste it into Lark to FuQiang
3. Wait for them to confirm the GitHub invitation email arrived + was accepted
4. Re-run `install.sh`

Do **not** try to add them as a collaborator via `gh api` — only the repo owner can do that.

---

## Repo structure (so agents know what they cloned)

```
.claude-plugin/plugin.json
skills/lark-deck-cyrus/SKILL.md
skills/upload-recognizer/SKILL.md
skills/deck-planner/SKILL.md
skills/deck-renderer/SKILL.md            ← present means: manual/install.sh path supported
skills/deck-auditor/SKILL.md
skills/pitch-simulator/SKILL.md
skills/deck-ingestor/SKILL.md
requirements.txt                   ← Playwright Python dependency spec
install.sh                        ← present means: install.sh path supported
INSTALL.md                        ← this file
README.md                         ← human-facing docs
```

Any of the three indicators present → that install path is supported.
