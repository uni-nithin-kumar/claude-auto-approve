---
name: approve-mode
description: Switch claude-auto-approve mode or check status. Use /approve-mode read-only, /approve-mode docs-write, /approve-mode force, /approve-mode off, /approve-mode status.
---

Switch the claude-auto-approve mode or check current status.

## Usage

```
/approve-mode <mode>
/approve-mode status
```

Valid modes: `read-only`, `docs-write`, `force`, `off`

## What to do

Run the appropriate CLI command and confirm the result:

- `/approve-mode read-only` → run `claude-auto-approve mode read-only`
- `/approve-mode docs-write` → run `claude-auto-approve mode docs-write`
- `/approve-mode force` → run `claude-auto-approve mode force`
- `/approve-mode off` → run `claude-auto-approve mode off`
- `/approve-mode status` → run `claude-auto-approve status`

Report the output to the user.
