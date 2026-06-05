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


# ── Bash helpers ──────────────────────────────────────────────────────────────

def is_safe_curl(command: str, allow_localhost_post: bool = True) -> bool:
    method_match = re.search(r'-X\s+(\w+)', command)
    if not method_match:
        return True
    method = method_match.group(1).upper()
    if method == "GET":
        return True
    if method in ("POST", "PUT", "PATCH") and allow_localhost_post:
        return bool(re.search(r'https?://(localhost|127\.0\.0\.1)(:\d+)?', command))
    return False


def is_safe_git(command: str, allow_writes: bool = True) -> bool:
    parts = command.strip().split()
    if len(parts) < 2:
        return False
    i = 1
    while i < len(parts) and parts[i] in ("-C", "--git-dir", "--work-tree"):
        i += 2
    if i >= len(parts):
        return False
    subcmd = parts[i]
    remaining = parts[i + 1:]
    if subcmd == "config":
        read_flags = {"--get", "--list", "-l", "--get-all", "--get-regexp", "--get-urlmatch"}
        return bool(read_flags.intersection(remaining))
    allowed = GIT_ALL_SAFE_SUBCOMMANDS if allow_writes else GIT_READ_SUBCOMMANDS
    if subcmd not in allowed:
        return False
    if subcmd == "push":
        return "--force" not in remaining and "-f" not in remaining
    if subcmd == "rebase":
        return "-i" not in remaining and "--interactive" not in remaining
    if subcmd == "reset":
        return "--hard" not in remaining and "--mixed" not in remaining
    return True


def is_safe_kubectl(command: str) -> bool:
    parts = command.strip().split()
    non_flags = [p for p in parts[1:] if not p.startswith("-")]
    return bool(non_flags) and non_flags[0] in KUBECTL_SAFE_SUBCOMMANDS


def is_safe_gh(command: str) -> bool:
    parts = command.strip().split()
    non_flags = [p for p in parts[1:] if not p.startswith("-")]
    if not non_flags or non_flags[0] not in GH_SAFE_SUBCOMMANDS:
        return False
    if non_flags[0] == "api":
        method_match = re.search(r"--method\s+(\w+)", command)
        if method_match and method_match.group(1).upper() != "GET":
            return False
    return True


def is_safe_awk(command: str) -> bool:
    return "system(" not in command


def is_safe_sed(command: str) -> bool:
    return not re.search(r'\s-[a-zA-Z]*i', command)


def is_safe_find(command: str) -> bool:
    if "-exec" not in command and "-execdir" not in command:
        return True
    exec_match = re.search(r"-exec(?:dir)?\s+(\S+)", command)
    if exec_match:
        safe_cmds = {"cat", "ls", "grep", "head", "tail", "wc", "stat", "file", "echo", "printf"}
        return os.path.basename(exec_match.group(1)) in safe_cmds
    return False


def is_safe_tee(command: str) -> bool:
    return "/dev/null" in command


def is_safe_python(command: str) -> bool:
    if "--version" in command or " -V" in command:
        return True
    if " -c " in command or command.endswith(" -c"):
        return not re.search(r"""open\s*\(.*['"]w['"]""", command)
    return False


def is_safe_segment(seg: str, allow_git_writes: bool = True, allow_localhost_post: bool = True) -> bool:
    seg = seg.strip()
    if not seg:
        return True
    seg = re.sub(r'^(?:\w+=\S*\s+)+', '', seg).strip()
    if not seg:
        return True
    parts = seg.split()
    cmd_name = os.path.basename(parts[0])
    if cmd_name in SAFE_SIMPLE_COMMANDS:
        return True
    if cmd_name == "awk":
        return is_safe_awk(seg)
    if cmd_name == "sed":
        return is_safe_sed(seg)
    if cmd_name == "find":
        return is_safe_find(seg)
    if cmd_name == "tee":
        return is_safe_tee(seg)
    if cmd_name == "git":
        return is_safe_git(seg, allow_writes=allow_git_writes)
    if cmd_name == "kubectl":
        return is_safe_kubectl(seg)
    if cmd_name == "curl":
        return is_safe_curl(seg, allow_localhost_post=allow_localhost_post)
    if cmd_name == "gh":
        return is_safe_gh(seg)
    if cmd_name in ("python3", "python", "python3.12", "python3.11", "python3.10"):
        return is_safe_python(seg)
    if cmd_name in ("pip", "pip3"):
        return len(parts) > 1 and parts[1] in ("show", "list", "freeze", "check")
    if cmd_name == "npm":
        return len(parts) > 1 and parts[1] in ("list", "ls", "version")
    if cmd_name == "brew":
        return len(parts) > 1 and parts[1] in ("list", "info", "outdated")
    return False


def split_bash_segments(command: str) -> list:
    segments = re.split(r'\|\||\|(?!\|)|&&|;', command)
    return [s.strip() for s in segments if s.strip()]


# ── Top-level classifiers ─────────────────────────────────────────────────────

def classify_bash(tool_input: dict, mode: str) -> bool:
    if mode == "off":
        return False
    if mode == "force":
        return True
    command = tool_input.get("command", "")
    if not command:
        return False
    if "$(" in command or "`" in command:
        return False
    segments = split_bash_segments(command)
    if not segments:
        return False
    allow_git_writes = (mode == "docs-write")
    allow_localhost_post = (mode == "docs-write")
    return all(
        is_safe_segment(seg, allow_git_writes=allow_git_writes, allow_localhost_post=allow_localhost_post)
        for seg in segments
    )


def classify_edit_write(tool_input: dict, mode: str, safe_paths: list) -> bool:
    if mode == "off":
        return False
    if mode == "force":
        return True
    file_path = tool_input.get("file_path", "") or tool_input.get("notebook_path", "")
    if mode == "read-only":
        return is_safe_path(file_path, ["/tmp"])
    return is_safe_path(file_path, safe_paths)


def classify_mcp(tool_name: str, mode: str) -> bool:
    if mode == "off":
        return False
    if mode == "force":
        return True
    if tool_name in BROWSEROS_SAFE_TOOLS:
        return True
    if tool_name == "mcp__atlassian__atlassianUserInfo":
        return True
    if not tool_name.startswith("mcp__"):
        return False
    parts = tool_name.split("__", 2)
    action = parts[2] if len(parts) >= 3 else ""
    read_prefixes = ("get_", "list_", "search_", "read_", "fetch_", "view_", "show_")
    return any(action.startswith(p) for p in read_prefixes)


def main():
    defer()


if __name__ == "__main__":
    main()
