#!/usr/bin/env python3
"""
claude-auto-approve: intelligent multi-mode auto-approval hook for Claude Code.

Usage as hook (no args): invoked by Claude Code PreToolUse, reads JSON from stdin.
Usage as CLI:
  claude-auto-approve mode <read-only|docs-write|force|off>
  claude-auto-approve status
"""

import json
import sys
import os
import re
from pathlib import Path

# ── Modes ────────────────────────────────────────────────────────────────────
MODES = ("read-only", "docs-write", "force", "off")
DEFAULT_MODE = "docs-write"

MODE_FILE = Path.home() / ".claude" / "hooks" / ".approve-mode"
CONFIG_FILE = Path.home() / ".claude" / "hooks" / "claude-auto-approve.json"

DEFAULT_SAFE_WRITE_PATHS = [
    str(Path.home() / "workspace"),
    str(Path.home() / "sandbox"),
    str(Path.home() / ".claude"),
    "/tmp",
]

# ── Command constants ─────────────────────────────────────────────────────────
SAFE_SIMPLE_COMMANDS = {
    "ls", "ll", "la", "cat", "head", "tail", "wc", "du", "stat", "file",
    "sort", "uniq", "cut", "tr", "echo", "printf", "env", "printenv",
    "which", "type", "date", "uname", "hostname", "uptime", "pwd",
    "dirname", "basename", "jq", "yq", "ps", "lsof", "pgrep", "rg", "grep",
}

# git reads — safe in read-only mode
GIT_READ_SUBCOMMANDS = {
    "log", "status", "diff", "show", "branch", "remote",
    "rev-parse", "describe", "tag",
}

# git writes — only safe in docs-write mode (non-destructive)
GIT_WRITE_SUBCOMMANDS = {
    "add", "commit", "fetch", "pull", "merge", "push",
    "rebase", "checkout", "switch", "stash",
}

GIT_ALL_SAFE_SUBCOMMANDS = GIT_READ_SUBCOMMANDS | GIT_WRITE_SUBCOMMANDS

KUBECTL_SAFE_SUBCOMMANDS = {"get", "describe", "logs", "config", "auth", "top"}
GH_SAFE_SUBCOMMANDS = {"pr", "issue", "repo", "run", "api", "release"}

BROWSEROS_SAFE_TOOLS = {
    "mcp__browseros__take_snapshot",
    "mcp__browseros__get_page_content",
    "mcp__browseros__get_dom",
    "mcp__browseros__take_screenshot",
    "mcp__browseros__save_screenshot",
    "mcp__browseros__get_page_links",
    "mcp__browseros__list_pages",
    "mcp__browseros__list_windows",
    "mcp__browseros__list_tab_groups",
    "mcp__browseros__get_bookmarks",
    "mcp__browseros__get_recent_history",
    "mcp__browseros__search_bookmarks",
    "mcp__browseros__search_history",
    "mcp__browseros__search_dom",
    "mcp__browseros__get_console_logs",
    "mcp__browseros__get_active_page",
    "mcp__browseros__browseros_info",
    "mcp__browseros__discover_server_categories_or_actions",
    "mcp__browseros__get_category_actions",
    "mcp__browseros__get_action_details",
    "mcp__browseros__search_documentation",
}


# ── Mode / Config I/O ─────────────────────────────────────────────────────────

def read_mode() -> str:
    """Read current mode from mode file. Falls back to DEFAULT_MODE."""
    try:
        mode = MODE_FILE.read_text().strip().lower()
        if mode in MODES:
            return mode
    except Exception:
        pass
    return DEFAULT_MODE


def write_mode(mode: str) -> None:
    """Write mode to mode file, creating parent dirs if needed."""
    MODE_FILE.parent.mkdir(parents=True, exist_ok=True)
    MODE_FILE.write_text(mode + "\n")


def read_config() -> dict:
    """Read config JSON. Returns empty dict if missing or invalid."""
    try:
        return json.loads(CONFIG_FILE.read_text())
    except Exception:
        return {}


def get_safe_write_paths(config: dict) -> list:
    """Expand ~ in all safe_write_paths from config, falling back to defaults."""
    paths = config.get("safe_write_paths", DEFAULT_SAFE_WRITE_PATHS)
    return [str(Path(p).expanduser()) for p in paths]


# ── Hook output ───────────────────────────────────────────────────────────────

def allow() -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
        }
    }))
    sys.exit(0)


def defer() -> None:
    sys.exit(0)


# ── Path safety ───────────────────────────────────────────────────────────────

def is_safe_path(file_path: str, safe_paths: list) -> bool:
    """Return True if file_path resolves under any path in safe_paths."""
    if not file_path:
        return False
    try:
        p = Path(file_path).expanduser().resolve()
        for safe in safe_paths:
            try:
                p.relative_to(Path(safe).expanduser().resolve())
                return True
            except ValueError:
                continue
    except Exception:
        pass
    return False


def main():
    defer()


if __name__ == "__main__":
    main()
