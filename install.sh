#!/usr/bin/env bash
set -euo pipefail

HOOK_SRC="$(cd "$(dirname "$0")" && pwd)/claude_auto_approve.py"
HOOKS_DIR="$HOME/.claude/hooks"
HOOK_DEST="$HOOKS_DIR/claude_auto_approve.py"
CONFIG_FILE="$HOOKS_DIR/claude-auto-approve.json"
MODE_FILE="$HOOKS_DIR/.approve-mode"
SETTINGS="$HOME/.claude/settings.json"
SKILL_SRC="$(cd "$(dirname "$0")" && pwd)/skill/SKILL.md"
SKILL_DEST="$HOME/.claude/skills/approve-mode/SKILL.md"
CLI_LINK="$HOME/.local/bin/claude-auto-approve"

echo "=== claude-auto-approve installer ==="
echo ""

# Check Python 3.8+
python3 -c "import sys; assert sys.version_info >= (3,8), 'Python 3.8+ required'" 2>/dev/null \
  || { echo "ERROR: Python 3.8+ is required."; exit 1; }
echo "✓ Python 3.8+ found"

mkdir -p "$HOOKS_DIR"

DEFAULT_PATHS="$HOME/.claude /tmp"
echo ""
echo "Default safe write paths (Edit/Write auto-approved in docs-write mode):"
for p in $DEFAULT_PATHS; do echo "  $p"; done
echo ""
echo "Add your project directories (space-separated, e.g. ~/workspace ~/projects ~/dev ~/Obsidian)"
echo "Press Enter to skip (you can edit ~/.claude/hooks/claude-auto-approve.json later)"
read -r EXTRA_PATHS

ALL_PATHS="$DEFAULT_PATHS ${EXTRA_PATHS:-}"
PATHS_JSON="["
FIRST=1
for p in $ALL_PATHS; do
  [ -z "$p" ] && continue
  p="${p/#\~/$HOME}"
  if [ $FIRST -eq 1 ]; then
    PATHS_JSON="${PATHS_JSON}\"$p\""
    FIRST=0
  else
    PATHS_JSON="${PATHS_JSON}, \"$p\""
  fi
done
PATHS_JSON="${PATHS_JSON}]"

cat > "$CONFIG_FILE" <<CONF
{
  "safe_write_paths": $PATHS_JSON
}
CONF
echo "✓ Config written to $CONFIG_FILE"

cp "$HOOK_SRC" "$HOOK_DEST"
chmod +x "$HOOK_DEST"
echo "✓ Hook installed to $HOOK_DEST"

python3 - "$HOOK_DEST" "$SETTINGS" <<'PYEOF'
import json, sys
from pathlib import Path

hook_path = sys.argv[1]
settings_path = Path(sys.argv[2])

try:
    settings = json.loads(settings_path.read_text())
except Exception:
    settings = {}

hooks = settings.setdefault("hooks", {})
pre = hooks.setdefault("PreToolUse", [])

for entry in pre:
    for h in entry.get("hooks", []):
        if "claude_auto_approve.py" in h.get("command", ""):
            print("PreToolUse hook already registered, skipping.")
            sys.exit(0)

pre.append({
    "matcher": "",
    "hooks": [{
        "type": "command",
        "command": f"python3 {hook_path}",
        "timeout": 5000
    }]
})

settings_path.write_text(json.dumps(settings, indent=2))
print("✓ PreToolUse hook registered in settings.json")
PYEOF

echo "docs-write" > "$MODE_FILE"
echo "✓ Default mode set to: docs-write"

mkdir -p "$(dirname "$CLI_LINK")"
ln -sf "$HOOK_DEST" "$CLI_LINK"
echo "✓ CLI symlinked: $CLI_LINK"

if [ -f "$SKILL_SRC" ]; then
  mkdir -p "$(dirname "$SKILL_DEST")"
  cp "$SKILL_SRC" "$SKILL_DEST"
  echo "✓ /approve-mode skill installed"
else
  echo "  (skill/SKILL.md not found, skipping skill install)"
fi

echo ""
echo "=== Installation complete ==="
echo ""
echo "Restart Claude Code for the hook to take effect."
echo ""
echo "Switch modes with:"
echo "  claude-auto-approve mode read-only"
echo "  claude-auto-approve mode docs-write   (default)"
echo "  claude-auto-approve mode force"
echo "  claude-auto-approve mode off"
echo "  claude-auto-approve status"
echo ""
echo "Or inside Claude Code: /approve-mode read-only"
