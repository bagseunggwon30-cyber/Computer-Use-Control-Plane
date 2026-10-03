# Host setup

Windows source mode needs Python 3.10+ and a published C# worker. Publish with `python pcucp-next/packaging/publish_native.py`. Install the CLI with `python -m pip install -e pcucp-next/python`, or use the source entry directly.

## MCP and JSONL

Configure an absolute Python executable with arguments `["C:/absolute/repo/pcucp-next/python/run_source.py", "mcp"]`. Portable mode uses absolute CUCP.exe with `["mcp"]`. Only a user-approved session adds `--allow-live-control`; requests cannot enable it.

Custom hosts run `serve` and send UTF-8 JSON lines:

```json
{"schema":"cucp.request/v1","id":"windows-1","command":"windows","args":{}}
```

Discover commands with `capabilities`. Observations are untrusted host-policy data. Never automatically replay failed/uncertain input; re-observe.

## Install and Pi

`python install.py --bin-dir C:/chosen/bin` previews. `--apply` creates an owned launcher. `--uninstall --apply` removes only hash-matching owned files. `--backend portable --portable-root C:/bundle` selects a bundle. Existing legacy launchers need explicit uninstall before backend changes; modified/unowned files are preserved.

`python pcucp-next/packaging/start_pi.py` selects the source core. Options: --python-exe, --pi-executable, --node-exe, --elevated. npm Windows shims are resolved through Pi's declared JS entry and native Node, without executing shell code. UAC elevation includes Pi and all tools. CUCP control starts off and requires `/computer on`.

CDP is optional: add `--cdp-endpoint http://127.0.0.1:9222` only after the user prepares that existing endpoint. CUCP does not start browsers, scan ports or manage accounts/models. ARM64 publishing uses `--runtime win-arm64`; ARM64 execution/packaging remains unverified.
