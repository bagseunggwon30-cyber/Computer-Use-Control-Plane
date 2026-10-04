# Scripts

Public entry points:

- `cucp.ps1` - main wrapper, safety gates, macro dispatch, JSON envelopes.
- `cucp-native-helper.py` - Python entrypoint for the 24 compiled Windows actions and 10 Python CDP actions; the former PowerShell implementation is deleted.
- `cucp-helper-server.py` - compiled resident helper startup. The legacy `.ps1` remains for pending login-autostart migration; default wrapper start/status/stop and pipe calls use Python/C#.

Keep live-control behavior gated by `-AllowLiveControl`.
For standalone Python helper input, explicitly place `--allow-live-control` before `-Action`.
Historical native PowerShell comparisons read the pinned Git oracle through
`tests/python/legacy_historical_native.py`; production never loads it.
Prefer small wrapper changes with focused smoke tests; avoid mixing docs,
installer, and runtime changes in one patch.
