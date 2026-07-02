---
name: cucp
description: Use CUCP when a task needs local Windows desktop observation, grounded GUI automation, label-based clicking, UI Automation, OCR, Chromium CDP, screenshots, workflow planning, or safety-gated live control.
---

# CUCP

CUCP is a Windows Computer Use Control Plane. Use it to observe the desktop,
ground UI targets, plan actions, run approved live control, and verify results.

Primary command after installation:

```powershell
cucp <args>
```

Direct wrapper path from the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\cucp.ps1 <args>
```

## Operating Rules

- Start with read-only observation.
- Prefer labels, UI Automation, OCR, or CDP DOM evidence before coordinates.
- Require explicit user approval and `-AllowLiveControl` before clicks, typing,
  shortcuts, app launch/close, or live workflow execution.
- Do not operate UAC prompts, credential dialogs, payment screens, private
  messages, or identity documents unless the user approved that exact action.
- Verify immediately after every live action.

## Useful Commands

Read-only:

```powershell
cucp macro windows
cucp macro find-label --label "Save" --explain
cucp macro list-affordances --window "Notepad" --limit 20
cucp macro smart-plan --label "Save" --match "Notepad"
cucp macro health-quick
```

Live control after explicit approval:

```powershell
cucp -AllowLiveControl macro smart-click --label "Save" --match "Notepad"
cucp -AllowLiveControl macro fill-label --label "Name" --text "Alice"
cucp -AllowLiveControl macro shortcut --keys "ctrl+s"
```

## Scope

This public plugin package is limited to Windows computer-use automation. It
does not include unfinished industrial, vendor-specific, or project-specific
automation plans.
