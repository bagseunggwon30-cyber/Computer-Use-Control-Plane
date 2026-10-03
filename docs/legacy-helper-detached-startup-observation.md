# Staged helper startup diagnostic and confirmed repair

The first staged-routing Windows run, [37109440409](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/37109440409),
used public commit `7b7e0d28bee82a7ae4818a0f9cfd753771ff8e5b`, tree
`41fc1aa16e3de591f85d6c085887bac0e6eccc5d`, identical to local `5d2075774a67bdaf302ab67402156ce4f5c9a23d`.
Artifact archive SHA-256:
`70116df7a30218f9c0535cae520af520fc66892be5a5d697463301de392d03ac`.

Observed failures remain failures: packaged detached service launches returned
3762504530 (`0xe0434352`) for zero, negative-one and Int32-minimum idle durations;
concrete start returned error. The production wrapper fixture returned exit zero
with zero stdout/stderr, then failed JSON decoding. No raw service stderr was
captured by its deliberately disconnected production launcher. These observations
alone do not identify a missing dependency or a particular managed exception.

Source analysis found two boundaries:

- Program.Main sets Console.OutputEncoding before its try. The Framework
  [reference implementation](https://github.com/Microsoft/referencesource/blob/main/mscorlib/system/console.cs)
  uses SetConsoleOutputCP for UTF-8 and raises an I/O exception on failure. This
  supports a no-console hypothesis; it is not the missing runtime stack trace.
- The wrapper fixture did not propagate a nested script's LASTEXITCODE. Quiet
  suppresses console Write-Notice output while retaining the wrapper log, so a
  wrapper failure could become a misleading successful outer process. The
  [PowerShell exit contract](https://learn.microsoft.com/en-us/powershell/module/Microsoft.PowerShell.Core/about/about_automatic_variables?view=powershell-5.1#lastexitcode)
  requires explicit propagation by this outer script. The 860 ms observed runtime
  also suggests failure before the client's three-second startup deadline.

The initial diagnostic patch changed no production service, client, provider or wrapper
behavior. It strengthens the fixture exit propagation, saves the bounded owned
wrapper log before assertions/cleanup, and adds twelve startup observations:
exact packaged executable and separate console-boundary probe under inherited,
CREATE_NO_WINDOW, and DETACHED_PROCESS + CREATE_NEW_PROCESS_GROUP modes. The
probe contrasts the exact original setter statement with explicit UTF-8 stream
writers. It contains no desktop, pipe or service acquisition. A probe is not a
rebuilt original helper or a parity oracle.

Package build evidence now optionally retains the complete flat output file
inventory with hashes/sizes, included-file list, source project/program hashes,
and final package manifest. This permits dependency-closure review without
loosening the three-file package manifest. No package artifact is executed by the
publisher itself.

All observations have bounded stdout/stderr, recorded creation flags, exit and
infrastructure status, and temporary lock paths. Cleanup uses only retained newly
launched handles. The collector labels its summary observations-only and never
accepts a crash as an expected input rejection. Collection success means evidence
was saved; unchanged runtime tests still decide their own result and retain the
same assertions/deadlines. Existing failures and historical evidence are retained.

Local checks compile the net48 probe with zero warnings/errors; portable staging
and raw-evidence tests pass. Actual Windows observations remain pending. The
next source fix must follow the captured exception/trace rather than guessing.
The unrelated uncommitted autostart candidate remains isolated and paused.

The diagnostic collector redirects standard streams to pipes to preserve bytes;
the production detached launcher uses DEVNULL. These are deliberately distinct
conditions. Existing exact-production launcher tests must pass after any fix;
a pipe-captured console probe alone cannot qualify the DEVNULL startup path.

## Confirmed detached boundary and narrowly scoped repair

[Windows run 37110868522](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/37110868522)
at public `89aa36fdae7b11f901fc1d1332b2391ef226c436` (tree
`e12363426425f3ebe8c355775b757d6748d04155`) retained all twelve complete observations. Artifact SHA-256
is `193b94049eec4c6f03c08f733f52f63c3bf10fef031a51af0f1917ddd0a74cfc`.
The exact packaged executable rejects negative-one and completes zero-idle under
inherited and no-window modes, but detached mode throws `System.IO.IOException`
with “The handle is invalid” at `Console.set_OutputEncoding`. The separate old
setter probe reproduces that boundary; the stream-writer probe emits exact UTF-8
Unicode stdout/stderr and exits zero under all three modes.

The repair replaces only that console-codepage setter with explicit UTF-8,
no-BOM, autoflushing stdout/stderr StreamWriters inside the existing try. It does
not add exception suppression, CLI allowances, launch retries or provider/action
changes. A new mandatory Windows fixture checks actual packaged Unicode output
and exact Unicode CLI-error bytes under all three startup modes. Existing
production DETACHED_PROCESS + DEVNULL start/reuse/health/shutdown and negative
CLI tests retain their assertions and deadlines. Their fresh result is still
required; the repaired service is not qualified by the earlier tiny probe alone.

The corrected outer wrapper driver now reports exit one. Its preserved log
establishes a separate Process.Start “system cannot find the file specified”
failure before the client's startup wait. It does not identify the resolved
executable. Get-Command and .Source selection remain unchanged. Only this launch
failure path adds a bounded record of command count, up to four command types,
Path/Source values and the assigned FileName (each path capped at 1,024 chars),
then rethrows the original ErrorRecord. No environment, request/argv, unrelated
path, alternative resolver or retry is added. Fresh Windows evidence must settle
that cause before resolver semantics change.

Both raw failure records and their hashes/package identity are pinned under
`tests/fixtures/legacy-helper/observed-staged-startup-manifest.json`. They are
failed historical observations, not acceptance expectations for the repaired
candidate. The earlier unmodified PowerShell startup and argument-binding
observations remain separate and unchanged.

“Inherited” in this matrix means inherited console attachment with captured
PIPE stdout/stderr. It does not qualify Unicode rendering into an attached
legacy-codepage console. Direct stream encoding intentionally avoids changing
that console's codepage; inspected production exchange/service routes use
redirected streams or DEVNULL. Interactive-console rendering remains unqualified.

Local repair validation: net48 build passed with zero warnings/errors; the
helper suite reported 169 methods, 135 passed and 34 skipped. The portable
staged gate passed. Full Python discovery reported 847 methods and
`OK (skipped=223)` (including class-setup skips). These are local checks, not a
fresh Windows result for the repaired package or the unresolved wrapper launch.
