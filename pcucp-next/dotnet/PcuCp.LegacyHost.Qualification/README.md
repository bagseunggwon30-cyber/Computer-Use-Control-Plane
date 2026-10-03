# Portable source-linked legacy-host proof fixture

This test-only executable links the current production C# startup, tagged
session, diagnostic coordinator, reducers and effect semantics. It contains no
file/process/network/desktop effect provider. It accepts only the read-only,
brief `legacy-diagnostic-session` / `release-notes` startup.

Build it explicitly, then set `CUCP_LEGACY_HOST_TEST_PORTABLE` to its absolute DLL
path for `tests/python/test_legacy_host_owned.py`. Production Python code never
builds or automatically selects this fixture. A local .NET runtime roll-forward
run does not prove Windows/.NET 8 behavior. `CUCP_LEGACY_HOST_TEST_NATIVE` instead
selects the separately built actual Windows NativeHost and activates the original
PowerShell brief oracle gate on Windows.

Process tracing is a separate opt-in gate, not inferred from this fixture.
See `docs/legacy-python-host-spine.md` for provenance, retained gates and the next
complete caller/formatting retirement route.
