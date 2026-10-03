# Verification for the 0.5.0 proposal

Local Windows checks:

- `python -m unittest discover -s tests/python -q`: 282 tests, 9 optional skips with the actual native worker selected, no failures.
- `dotnet run --project pcucp-next/dotnet/PcuCp.NativeHost.ContractTests -c Release`: 12,869 contract checks passed.
- `CUCP_NATIVE_TEST_HOST=<built native DLL>` + `python -m unittest test_native_session.RealNativeSessionTests -v`: real process reuse and read-only authority rejection passed.
- Real disposable Windows installer and Node/Pi package-entry fixtures passed with Korean/space/metacharacter paths and exact argv/exit propagation; no UAC was requested.
- Pi `npm run typecheck`, `npm test` (20 tests), `npm run test:engine` passed.
- All 13 original PowerShell sources removed; legacy execution/advertising rejected; CI uses explicit Bash defaults, not PowerShell/Pester.

The baseline lockfile still has the existing high-severity brace-expansion development dependency audit finding. This task does not change its versions; it is outside the standard-library core runtime.

Local `build_portable.py` passed: an actual Windows x64 bundle was built, relocated to a Korean/space path and checked with Python/Node/.NET absent from child PATH. Checksums, doctor, UTF-8 JSONL, authority rejection and resident worker reuse passed. `verify_pi_portable.py` passed against this bundle with no Python on child PATH. CI repeats these checks on the exact proposed commit.

None of these prove real desktop goals, actual UAC consent/cancellation, IME composition, clipboard workflows, UIA providers, mixed DPI or elevated-app compatibility. The old legacy features listed in [migration](migration-matrix.md) are deliberately retired, not tested as equivalent.
