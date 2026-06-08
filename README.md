# claude-auto-approve

Intelligent multi-mode auto-approval hook for [Claude Code](https://claude.ai/code). Eliminates repetitive permission prompts for safe operations while preserving approval for destructive or externally-visible actions.

## Modes

| Mode | Auto-approves |
|------|--------------|
| `read-only` | Bash reads, `git log/status/diff`, `curl` GET, MCP reads. Writes only to `/tmp`. |
| `docs-write` *(default)* | Everything in `read-only` + `git add/commit/push` (non-force), `curl` POST to localhost, writes to your configured safe paths. |
| `force` | Everything. Session escape hatch — use when you need zero interruptions. |
| `off` | Nothing. Disables the hook entirely, all prompts restored. |

## Install

```bash
git clone https://github.com/uni-nithin-kumar/claude-auto-approve
cd claude-auto-approve
./install.sh
```

Restart Claude Code after install.

## Switch modes

**From terminal:**
```bash
claude-auto-approve mode read-only
claude-auto-approve mode docs-write
claude-auto-approve mode force
claude-auto-approve mode off
claude-auto-approve status
```

**Inside Claude Code (after skill install):**
```
/approve-mode read-only
/approve-mode status
```

## Configure safe write paths

Edit `~/.claude/hooks/claude-auto-approve.json`:

```json
{
  "safe_write_paths": [
    "~/workspace",
    "~/sandbox",
    "~/.claude",
    "/tmp",
    "~/Obsidian"
  ]
}
```

Files under these paths are auto-approved for `Edit`/`Write` in `docs-write` mode.

## How it works

A `PreToolUse` hook receives every tool call before Claude executes it. The hook:

1. Reads the current mode from `~/.claude/hooks/.approve-mode`
2. Classifies the tool call (Bash, Edit/Write, or MCP)
3. Returns `allow` or exits silently (falls through to Claude Code's normal permission prompt)

**It never denies** — unknown or risky calls always fall through to the normal prompt. A crash in the hook also falls through safely.

## Bash approval rules

Compound commands (`cmd1 | cmd2 && cmd3`) are split and every segment must be safe.

| Command type | `read-only` | `docs-write` |
|-------------|-------------|--------------|
| `ls`, `grep`, `cat`, `jq`, etc. | yes | yes |
| `git log/status/diff/show` | yes | yes |
| `git push --force` | no | no |
| `curl` GET (any host) | yes | yes |
| `curl` POST to localhost | no | yes |
| `curl` POST to external host | no | no |
| `kubectl get/describe/logs` | yes | yes |
| `kubectl apply/delete` | no | no |
| `rm`, `sudo`, `pip install` | no | no |

## Uninstall

```bash
./uninstall.sh
```

Removes the hook, config, mode file, CLI symlink, and the PreToolUse entry from `settings.json`. All other settings untouched.

## Requirements

- Python 3.8+ (stdlib only, no pip install needed)
- Claude Code

## License

MIT
