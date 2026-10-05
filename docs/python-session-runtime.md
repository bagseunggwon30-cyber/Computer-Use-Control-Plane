# Python session macro

All eight session subcommands run in `legacy_session_runtime.py`: `clear-cache`,
`info`, `start-helper`, `stop-helper`, `helper-status`, `install-autostart`,
`uninstall-autostart`, and `autostart-status`. The production wrapper only
supplies immutable startup context, restricts the current live ceiling against
the startup ceiling, calls the fixed Python bridge, emits notices, and renders
the returned report using the original shell JSON dialect.

Python performs cache IO and calls the previously qualified Python/C# helper
lifecycle directly. The package is resolved relative to the checked-in module
and hash-validated. No request selects an executable, lock path, Startup folder,
metadata folder, desktop permission, or live authority. Autostart mutations
still require `-AllowLiveControl`. Successful detached services keep their
existing lifetime; shutdown uses the existing authenticated/owned protocol
without killing a process by a discovered PID.

Cache enumeration retains case-insensitive fixed filename patterns and the
original Hidden/System filtering. Cleanup touches only immediate matching
entries, never recursively deletes a directory, and preserves nonempty
directories. `info` always emits JSON, including brief mode. Lifecycle reports,
notices, idle defaults, force flags and brief behavior retain the old contract.
The startup dialect preserves the PS7 whitespace-to-zero conversion and the
PS5 fallback to the original idle defaults.

The shared preserved owner also connects the entire session surface. Its
autostart folder discovery uses a closed read-only C# operation with the same
`Environment.GetFolderPath` getters as the wrapper. Scope cancellation and
deadlines remain inherited; side effects are never automatically replayed.

Qualification includes 83 original/current cases per actual PS5.1 and PS7
(166 comparisons), physical cache files, lifecycle argv/call counts, permission
denial, errors, exact Console output and notices. Actual owned helper startup,
reuse, status, pipe reads and shutdown pass the existing production suite.
Additional tests use the real shared owner, compare the special-folder getter
to both shells, reject request-selected paths/authority, and install/status/
uninstall a real launcher only in disposable owned directories.

This does not claim the remaining wrapper or legacy test files are retired.
No Linguist exclusions, renamed PowerShell or copied private CLI code are used.
