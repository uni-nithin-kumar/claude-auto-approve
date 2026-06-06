#!/usr/bin/env bash
set -euo pipefail

HOOKS_DIR="$HOME/.claude/hooks"
HOOK_DEST="$HOOKS_DIR/claude_auto_approve.py"
CONFIG_FILE="$HOOKS_DIR/claude-auto-approve.json"
MODE_FILE="$HOOKS_DIR/.approve-mode"
SETTINGS="$HOME/.claude/settings.json"
SKILL_DEST="$HOME/.claude/skills/approve-mode"
CLI_LINK="$HOME/.local/bin/claude-auto-approve"

echo "=== claude-auto-approve uninstaller ==="
echo ""

[ -f "$HOOK_DEST" ] && rm "$HOOK_DEST" && echo "✓ Removed $HOOK_DEST"
[ -f "$CONFIG_FILE" ] && rm "$CONFIG_FILE" && echo "✓ Removed $CONFIG_FILE"
[ -f "$MODE_FILE" ] && rm "$MODE_FILE" && echo "✓ Removed $MODE_FILE"

if [ -f "$SETTINGS" ]; then
  python3 - "$SETTINGS" <<'PYEOF'
import json, sys
from pathlib import Path

settings_path = Path(sys.argv[1])
try:
    settings = json.loads(settings_path.read_text())
except Exception:
    print("settings.json not found or invalid, skipping.")
    sys.exit(0)

hooks = settings.get("hooks", {})
pre = hooks.get("PreToolUse", [])
before = len(pre)
hooks["PreToolUse"] = [
    entry for entry in pre
    if not any("claude_auto_approve.py" in h.get("command", "") for h in entry.get("hooks", []))
]
after = len(hooks["PreToolUse"])

if before != after:
    if not hooks["PreToolUse"]:
        del hooks["PreToolUse"]
    settings_path.write_text(json.dumps(settings, indent=2))
    print("✓ Removed PreToolUse entry from settings.json")
else:
    print("  No claude-auto-approve entry found in PreToolUse, skipping.")
PYEOF
fi

[ -L "$CLI_LINK" ] && rm "$CLI_LINK" && echo "✓ Removed CLI symlink $CLI_LINK"
[ -d "$SKILL_DEST" ] && rm -rf "$SKILL_DEST" && echo "✓ Removed skill $SKILL_DEST"

echo ""
echo "=== Uninstall complete ==="
echo "Restart Claude Code to apply changes."
