# Install — agent-readable spec

> This file is the canonical install procedure for the lark-deck-cyrus product skills:
> `lark-deck-cyrus`, `deck-planner`, `deck-renderer`, `deck-auditor`, and `pitch-simulator`.
> If you are a Claude (or any AI agent) and the user asked you to install
> this skill from a git URL, follow these steps in order.
> If you are a human, [README.md](./README.md) is friendlier.

## TL;DR for the user

Tell your Claude agent:

> "帮我安装 lark-deck-cyrus 这个 skill：`https://github.com/cyrus-xy0/feishu-deck-h5.git`"

The agent will detect your harness, install the product skills, and verify.

---

## Decision tree (for the agent)

Run these checks **in order**, stop at the first match:

### 1. Plugin marketplace path (Claude Code with `/plugin` support)

**Detect:** the user is running Claude Code CLI / Claude Desktop and `/plugin marketplace add` is a known slash command.

**Action — instruct the user to run:**

```
/plugin marketplace add https://github.com/cyrus-xy0/feishu-deck-h5.git
/plugin install lark-deck-cyrus@lark-deck-cyrus
```

Then restart the session. (Slash commands cannot be invoked by an agent — the user has to type them.)

**Verify:** after restart, `bash ~/.claude/skills/deck-renderer/assets/preflight.sh` should print `PREFLIGHT OK`.

### 2. install.sh path (any harness with `~/.claude/skills/` convention)

**Detect:** plugin marketplace not available, but `~/.claude/skills/` (or `$CLAUDE_DIR/skills/`) is the skill registration directory.

**Action — run as the user:**

```bash
git clone https://github.com/cyrus-xy0/feishu-deck-h5.git /tmp/lark-deck-cyrus-installer
bash /tmp/lark-deck-cyrus-installer/install.sh
rm -rf /tmp/lark-deck-cyrus-installer
```

For non-Claude-Code harnesses (e.g. openclaw if it uses a different skill root), set `CLAUDE_DIR` first:

```bash
CLAUDE_DIR=~/.openclaw bash install.sh
```

**Verify:** the script symlinks exactly five skills: `lark-deck-cyrus`,
`deck-planner`, `deck-renderer`, `deck-auditor`, and `pitch-simulator`, then
auto-runs `preflight.sh` for `deck-renderer`.
Look for `PREFLIGHT OK`.

### 3. Manual path (fallback when nothing else fits)

```bash
git clone https://github.com/cyrus-xy0/feishu-deck-h5.git ~/Projects/lark-deck-cyrus
mkdir -p ~/.claude/skills
ln -s ~/Projects/lark-deck-cyrus/skills/lark-deck-cyrus ~/.claude/skills/lark-deck-cyrus
ln -s ~/Projects/lark-deck-cyrus/skills/deck-planner ~/.claude/skills/deck-planner
ln -s ~/Projects/lark-deck-cyrus/skills/deck-renderer ~/.claude/skills/deck-renderer
ln -s ~/Projects/lark-deck-cyrus/skills/deck-auditor ~/.claude/skills/deck-auditor
ln -s ~/Projects/lark-deck-cyrus/skills/pitch-simulator ~/.claude/skills/pitch-simulator
bash ~/.claude/skills/deck-renderer/assets/preflight.sh
```

---

## Prerequisites (verify before installing)

- SSH key registered with GitHub: `ssh -T git@github.com` returns `Hi <user>!`
- Collaborator access if the repository is private
- `python3`, `bash`, `node` on PATH (used by build/validate)

If `ssh -T git@github.com` fails, stop and ask the user to set up their SSH key first — every install path depends on it.

### Don't have collaborator access yet?

If `git ls-remote <repo-url> HEAD` fails with
"Repository not found" or "Permission denied" but `ssh -T git@github.com`
works, the user has SSH set up but is not yet a collaborator on this private
repo.

`install.sh` detects this and exits with **code 2**, printing a copy-pasteable
Lark/Feishu message template (with the user's GitHub username pre-filled) for
them to send to FuQiang. The agent should:

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
skills/deck-planner/SKILL.md
skills/deck-renderer/SKILL.md            ← present means: manual/install.sh path supported
skills/deck-auditor/SKILL.md
skills/pitch-simulator/SKILL.md
install.sh                        ← present means: install.sh path supported
INSTALL.md                        ← this file
README.md                         ← human-facing docs
```

Any of the three indicators present → that install path is supported.
