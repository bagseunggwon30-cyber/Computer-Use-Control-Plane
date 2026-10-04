# Native calls through Python

The production `Invoke-NativeHelper` cold route now sends bounded typed argv to
Python, which owns the .NET Framework 4.8 desktop worker. It no longer starts
`powershell.exe -File cucp-native-helper.ps1`, writes stdout/stderr scratch files,
or guesses the exit code after losing its process handle. The compiled worker's
payload and exit code are returned directly. Windows/UIA/OCR/image and input
operations use the existing C# implementations. The old PowerShell helper has
been deleted. Qualification reads its hash-pinned public Git history only in
owned temporary oracle folders; it is never installed or used by production.

The existing server-first and hot-cache ordering is retained. CDP continues to
use its already migrated Python transport. The 24 desktop actions and 10 CDP
actions also have a direct `python scripts/cucp-native-helper.py -Action ...`
entrypoint. Explicit `--allow-live-control` precedes `-Action` for authorized
standalone input; option-looking text does not grant startup authority.

Build `publish_legacy_desktop.py` and `publish_native.py` before using the migrated
native route. `CUCP_LEGACY_DESKTOP_EXE` can explicitly select the published worker;
normal actions do not rebuild it. Missing packages are reported without a script
fallback. Python and C# own their child processes; a timed-out live action is not
retried. The original native timeout exit remains 124.

Windows checks execute the actual extracted production route against the actual
worker for health, an absent matched window, a missing owned image and an owned
one-millisecond timeout. They verify exit codes, payload/Raw agreement and the
child route. Direct Python tests verify health, absent-window results and refusal
of unauthorized text input. These checks do not prove every positive interaction
or full root cutover. The separately qualified desktop provider covers owned
UIA/input/image fixtures.

The dispatch checkpoint was refreshed for only `Invoke-NativeHelper`, the shared
process bridge and the native helper entrypoint path. An independent regression
checks that all 109 ordered clauses, 108 distinct names, handler relationships
and safety metadata remain identical. Other macro bodies remain hash pinned.

Installation and Pi/bootstrap publishing use Python; four previous PowerShell
entrypoints and the 2,796-line native helper have been deleted. All 34 original
helper actions map to Python CDP or the C# desktop worker. Historical adapter
regressions are explicitly distinguished from current runtime qualification.
The remaining wrapper, helper server and tests are still being migrated. Main
has not reached 0% PowerShell.
