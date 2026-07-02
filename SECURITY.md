# Security Policy

## Sensitive Information

Do not commit credentials, API keys, tokens, passwords, private keys, local
screenshots, live desktop logs, or personal workflow captures.

The repository `.gitignore` excludes common secret and runtime artifact paths,
including `.env`, key files, credential folders, CUCP caches, screenshots,
trajectory logs, and live verification captures.

## Live Control

CUCP can operate the local Windows desktop. Live actions must be user-approved
and must include `-AllowLiveControl`.

CUCP should refuse or pause on:

- UAC prompts
- credential and password dialogs
- payment screens
- private messages
- identity documents
- destructive system changes without exact user approval

## Reporting Issues

Open a GitHub issue with:

- CUCP version
- Windows version
- command used
- sanitized output
- reproduction steps

Do not include secrets, screenshots containing private data, local tokens, or
full desktop captures in public reports.
