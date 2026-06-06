#!/usr/bin/env python3
"""
claude-auto-approve: intelligent multi-mode auto-approval hook for Claude Code.

Usage as hook (no args): invoked by Claude Code PreToolUse, reads JSON from stdin.
Usage as CLI:
  claude-auto-approve mode <read-only|docs-write|force|off>
  claude-auto-approve status
  claude-auto-approve audit [--tail N]
"""

import json
import sys
import os
import re
import time
import subprocess
from pathlib import Path

# ── Modes ────────────────────────────────────────────────────────────────────
MODES = ("read-only", "docs-write", "force", "off")
DEFAULT_MODE = "docs-write"

MODE_FILE   = Path.home() / ".claude" / "hooks" / ".approve-mode"
CONFIG_FILE = Path.home() / ".claude" / "hooks" / "claude-auto-approve.json"
AUDIT_LOG   = Path.home() / ".claude" / "hooks" / "auto-approve-audit.jsonl"

DEFAULT_SAFE_WRITE_PATHS = [
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
GH_SAFE_SUBCOMMANDS      = {"pr", "issue", "repo", "run", "api", "release"}

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

MODE_ICONS = {
    "read-only":  "🔒",
    "docs-write": "✏️",
    "force":      "⚡",
    "off":        "⭘",
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


def write_config(config: dict) -> None:
    """Write config dict back to CONFIG_FILE, creating dirs if needed."""
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2) + "\n")


def get_safe_write_paths(config: dict) -> list:
    """Expand ~ in safe_write_paths from config, falling back to defaults."""
    paths = config.get("safe_write_paths", DEFAULT_SAFE_WRITE_PATHS)
    return [str(Path(p).expanduser()) for p in paths]


def get_exclude_patterns(config: dict) -> list:
    """Regex patterns — if a Bash command matches any, it is always deferred."""
    return config.get("exclude_patterns", [])


def get_mcp_allow_patterns(config: dict) -> list:
    """Regex patterns for extra MCP tools to auto-approve beyond built-ins."""
    return config.get("mcp_allow_patterns", [])


def get_sound_enabled(config: dict) -> bool:
    """Whether to play a sound on mode switch (default: True)."""
    return bool(config.get("sound", True))


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


# ── Audit log ─────────────────────────────────────────────────────────────────

def log_decision(tool_name: str, summary: str, mode: str, decision: str) -> None:
    """Append one JSONL line to the audit log. Silently swallows all errors."""
    try:
        entry = {
            "ts":       int(time.time()),
            "tool":     tool_name,
            "cmd":      summary[:200],
            "mode":     mode,
            "decision": decision,
        }
        with AUDIT_LOG.open("a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


# ── Notifications ─────────────────────────────────────────────────────────────

def _notify_macos(title: str, msg: str, sound: bool, sound_file: str = "Glass.aiff") -> None:
    # Sound via afplay — works regardless of notification permission settings
    if sound:
        path = f"/System/Library/Sounds/{sound_file}"
        if not Path(path).exists():
            path = "/System/Library/Sounds/Glass.aiff"
        subprocess.run(["afplay", path], capture_output=True, timeout=3)
    # Visual banner via osascript (requires Script Editor → Banners in System Settings)
    script = f'display notification "{msg}" with title "{title}"'
    subprocess.run(["osascript", "-e", script], capture_output=True, timeout=3)


def _notify_linux(title: str, msg: str, sound: bool) -> None:
    subprocess.run(["notify-send", title, msg], capture_output=True, timeout=3)
    if sound:
        # Try PulseAudio then ALSA; both ship on most distros
        sound_files = [
            ("/usr/share/sounds/freedesktop/stereo/complete.oga",   ["paplay"]),
            ("/usr/share/sounds/gnome/default/alerts/glass.ogg",    ["paplay"]),
            ("/usr/share/sounds/freedesktop/stereo/complete.oga",   ["aplay"]),
        ]
        for path, player in sound_files:
            try:
                result = subprocess.run(player + [path], capture_output=True, timeout=3)
                if result.returncode == 0:
                    break
            except Exception:
                continue


def _notify_windows(title: str, msg: str, sound: bool) -> None:
    if sound:
        try:
            import winsound  # stdlib on Windows
            winsound.PlaySound("SystemNotification", winsound.SND_ALIAS | winsound.SND_ASYNC)
        except Exception:
            pass
    # PowerShell balloon notification — no external deps, works on Win 7+
    ps = (
        f'Add-Type -AssemblyName System.Windows.Forms; '
        f'$n = New-Object System.Windows.Forms.NotifyIcon; '
        f'$n.Icon = [System.Drawing.SystemIcons]::Information; '
        f'$n.Visible = $true; '
        f'$n.ShowBalloonTip(4000, "{title}", "{msg}", '
        f'[System.Windows.Forms.ToolTipIcon]::None); '
        f'Start-Sleep -Milliseconds 4500; $n.Dispose()'
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
        capture_output=True, timeout=6,
    )




def notify_input_needed(tool_name: str, summary: str, sound: bool = True) -> None:
    """Notify user that Claude is waiting for a permission decision.

    Fires when the hook defers — meaning Claude Code is about to show a
    permission prompt in the terminal. Use a distinct sound (Tink) so it
    feels different from the mode-switch chime (Glass).
    """
    try:
        title = "Claude needs your input"
        label = summary[:60] if summary else tool_name
        msg   = f"⏸ {tool_name}: {label}"
        if sys.platform == "darwin":
            _notify_macos(title, msg, sound, sound_file="Tink.aiff")
        elif sys.platform.startswith("linux"):
            subprocess.run(
                ["notify-send", "-u", "normal", title, msg],
                capture_output=True, timeout=3,
            )
            if sound:
                for path, player in [
                    ("/usr/share/sounds/freedesktop/stereo/bell.oga",     ["paplay"]),
                    ("/usr/share/sounds/freedesktop/stereo/complete.oga", ["paplay"]),
                ]:
                    try:
                        if subprocess.run(player + [path], capture_output=True, timeout=2).returncode == 0:
                            break
                    except Exception:
                        continue
        elif sys.platform == "win32":
            _notify_windows(title, msg, sound)
    except Exception:
        pass


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
    subcmd    = parts[i]
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
    parts     = command.strip().split()
    non_flags = [p for p in parts[1:] if not p.startswith("-")]
    return bool(non_flags) and non_flags[0] in KUBECTL_SAFE_SUBCOMMANDS


def is_safe_gh(command: str) -> bool:
    parts     = command.strip().split()
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
    parts    = seg.split()
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


def _classify_subshells(command: str, allow_git_writes: bool, allow_localhost_post: bool) -> bool:
    """
    Recursively inspect $(...) and `...` subshells.

    Extracts inner commands, classifies each one, then strips them from the
    outer command so the caller can classify the outer separately.

    Returns (outer_stripped, safe) where safe=False means an inner command
    failed and the whole expression should defer.
    """
    # Detect nested subshells — too complex to parse safely, defer
    inner_dollar = re.findall(r'\$\(([^)]*)\)', command)
    inner_tick   = re.findall(r'`([^`]*)`', command)

    for inner in inner_dollar + inner_tick:
        if "$(" in inner or "`" in inner:
            # Nested subshell — defer
            return None, False
        for seg in split_bash_segments(inner):
            if not is_safe_segment(seg, allow_git_writes=allow_git_writes,
                                   allow_localhost_post=allow_localhost_post):
                return None, False

    # All inner commands are safe; strip them to get the outer command
    outer = re.sub(r'\$\([^)]*\)', '', command)
    outer = re.sub(r'`[^`]*`', '', outer)
    return outer, True


# ── Exclude pattern check ────────────────────────────────────────────────────

def matches_exclude(command: str, patterns: list) -> bool:
    """Return True if command matches any user-configured exclude pattern."""
    for pattern in patterns:
        try:
            if re.search(pattern, command):
                return True
        except Exception:
            pass
    return False


# ── Top-level classifiers ─────────────────────────────────────────────────────

def classify_bash(tool_input: dict, mode: str, exclude_patterns: list = None) -> bool:
    if mode == "off":
        return False

    command = tool_input.get("command", "")
    if not command:
        return False

    # Exclude patterns always take precedence — even over force mode
    if exclude_patterns and matches_exclude(command, exclude_patterns):
        return False

    if mode == "force":
        return True

    allow_git_writes    = (mode == "docs-write")
    allow_localhost_post = (mode == "docs-write")

    # Subshell inspection: classify inners, then strip and classify outer
    if "$(" in command or "`" in command:
        outer, safe = _classify_subshells(command, allow_git_writes, allow_localhost_post)
        if not safe:
            return False
        command = outer  # continue with subshells stripped

    segments = split_bash_segments(command)
    if not segments:
        return False
    return all(
        is_safe_segment(seg, allow_git_writes=allow_git_writes,
                        allow_localhost_post=allow_localhost_post)
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


def classify_mcp(tool_name: str, mode: str, allow_patterns: list = None) -> bool:
    if mode == "off":
        return False
    if mode == "force":
        return True
    if tool_name in BROWSEROS_SAFE_TOOLS:
        return True
    if tool_name == "mcp__atlassian__atlassianUserInfo":
        return True
    # User-configured regex patterns
    if allow_patterns:
        for pattern in allow_patterns:
            try:
                if re.match(pattern, tool_name):
                    return True
            except Exception:
                pass
    if not tool_name.startswith("mcp__"):
        return False
    parts  = tool_name.split("__", 2)
    action = parts[2] if len(parts) >= 3 else ""
    read_prefixes = ("get_", "list_", "search_", "read_", "fetch_", "view_", "show_")
    return any(action.startswith(p) for p in read_prefixes)


# ── Hook entry point ──────────────────────────────────────────────────────────

def run_hook() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        defer()
        return

    mode             = read_mode()
    config           = read_config()
    safe_paths       = get_safe_write_paths(config)
    exclude_patterns = get_exclude_patterns(config)
    mcp_patterns     = get_mcp_allow_patterns(config)
    sound            = get_sound_enabled(config)
    tool_name        = data.get("tool_name", "")
    tool_input       = data.get("tool_input", {})

    # Notify user when deferring (except off mode — user wants full manual control)
    def _defer_with_notify(summary: str) -> None:
        log_decision(tool_name, summary, mode, "defer")
        if mode != "off":
            notify_input_needed(tool_name, summary, sound=sound)

    try:
        if tool_name == "Bash":
            cmd = tool_input.get("command", "")
            if classify_bash(tool_input, mode, exclude_patterns):
                log_decision(tool_name, cmd, mode, "allow")
                allow()
            else:
                _defer_with_notify(cmd)

        elif tool_name in ("Edit", "Write", "NotebookEdit"):
            path = tool_input.get("file_path", "") or tool_input.get("notebook_path", "")
            if classify_edit_write(tool_input, mode, safe_paths):
                log_decision(tool_name, path, mode, "allow")
                allow()
            else:
                _defer_with_notify(path)

        elif tool_name.startswith("mcp__"):
            if classify_mcp(tool_name, mode, mcp_patterns):
                log_decision(tool_name, "", mode, "allow")
                allow()
            else:
                _defer_with_notify(tool_name)

    except Exception:
        pass  # crash → defer safely

    defer()


# ── CLI entry point ───────────────────────────────────────────────────────────

def run_cli(args: list) -> None:
    if not args:
        print("Usage: claude-auto-approve mode <read-only|docs-write|force|off>")
        print("       claude-auto-approve sound <on|off>")
        print("       claude-auto-approve status")
        print("       claude-auto-approve audit [--tail N]")
        sys.exit(1)

    subcmd = args[0]

    if subcmd == "mode":
        if len(args) < 2:
            print(f"Usage: claude-auto-approve mode <{'|'.join(MODES)}>")
            sys.exit(1)
        mode = args[1]
        if mode not in MODES:
            print(f"Unknown mode '{mode}'. Valid: {', '.join(MODES)}")
            sys.exit(1)
        write_mode(mode)
        icon = MODE_ICONS.get(mode, "")
        print(f"{icon}  Mode set to: {mode}")
        # No sound/notification on mode switch — you're already at the terminal

    elif subcmd == "sound":
        if len(args) < 2 or args[1] not in ("on", "off"):
            print("Usage: claude-auto-approve sound <on|off>")
            sys.exit(1)
        enabled = args[1] == "on"
        config  = read_config()
        config["sound"] = enabled
        write_config(config)
        state = "🔊 on" if enabled else "🔇 off"
        print(f"Sound {state}")

    elif subcmd == "status":
        mode        = read_mode()
        config      = read_config()
        safe_paths  = get_safe_write_paths(config)
        excludes    = get_exclude_patterns(config)
        mcp_pats    = get_mcp_allow_patterns(config)
        sound       = get_sound_enabled(config)
        icon        = MODE_ICONS.get(mode, "")
        sound_icon  = "🔊" if sound else "🔇"
        print(f"Mode:              {icon}  {mode}")
        print(f"Sound:             {sound_icon}  {'on' if sound else 'off'}")
        print(f"Mode file:         {MODE_FILE}")
        print(f"Config:            {CONFIG_FILE}")
        print(f"Audit log:         {AUDIT_LOG}")
        print(f"Safe paths:        {', '.join(safe_paths)}")
        if excludes:
            print(f"Exclude patterns:  {', '.join(excludes)}")
        if mcp_pats:
            print(f"MCP allow patterns:{', '.join(mcp_pats)}")

    elif subcmd == "audit":
        tail = 20
        if "--tail" in args:
            idx = args.index("--tail")
            if idx + 1 < len(args):
                try:
                    tail = int(args[idx + 1])
                except ValueError:
                    pass
        if not AUDIT_LOG.exists():
            print("No audit log yet.")
            sys.exit(0)
        lines = AUDIT_LOG.read_text().splitlines()
        for line in lines[-tail:]:
            try:
                e = json.loads(line)
                ts  = time.strftime("%H:%M:%S", time.localtime(e["ts"]))
                dec = "✅ allow" if e["decision"] == "allow" else "⏭  defer"
                cmd = e.get("cmd", "")[:60]
                print(f"{ts}  {dec}  [{e['mode']:10}]  {e['tool']:20}  {cmd}")
            except Exception:
                print(line)

    else:
        print(f"Unknown command '{subcmd}'")
        sys.exit(1)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    if len(sys.argv) > 1:
        run_cli(sys.argv[1:])
    else:
        run_hook()


if __name__ == "__main__":
    main()
