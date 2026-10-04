# Python providers with retained functionality

This branch continues `migration/python-csharp-runtime`. It does not retire the
legacy macros, installer, daemon, recorder, helper lifecycle, CDP, UIA, vision,
clipboard/IME or workflows. The frozen 109 dispatch clauses (108 distinct names)
remain unchanged, including the seven existing unimplemented placeholders.

The full PowerShell retirement is **not complete**. The production launcher is
still `scripts/cucp.ps1`. Do not select this staged entry as a complete wrapper
replacement, merge a core-only retirement, or hide retained sources with Linguist.

## Implemented acquisition

`python -m pcucp_cli.legacy_diagnostic_runtime` runs the existing C# coordinators
for perf, diagnose-lag, health-quick, health-detail, log-tail, benchmark, self-test,
audit-summary and release-notes. Run `--help` for the explicit owned path options.
It supports original macro arguments, JSON/brief reports and application exits.

Python now owns file reads, tails, owned audit probes, cache operations, Node
version/CLI capture and trajectory storage. The native worker retains process
objects across two snapshots and reads their properties by owned ordinals. It
uses the retained wrapper/native Win32 enumerators separately. Label queries use
the existing managed interaction coordinator; `windows` retains optional CLI
enrichment, provenance, warnings and partial results. C# collects the wrapper's
UIA names, tooltip synonyms, small icons and stable affordance IDs.

Nested label/health queries inherit the diagnostic deadline. Node is launched
with an argument array and bounded drains; NativeHost-specific guard arguments
are never appended to Node. Cancellation terminates owned control workers only.
Unknown effects and changed paths/argv cannot acquire an input capability.

The desktop `cli.mjs` is an external dependency and is absent from this repository.
Select its real source explicitly. An absent CLI produces the original failure
or partial reports; it cannot synthesize a successful appshot. Tests use an owned
Node fixture to verify argument/artifact contracts, not to certify that dependency.
Backend identity now honestly reports .NET rather than a PowerShell version.

The external source was subsequently located using the installation path in
`references/command-reference.md`, adjusted for the current user profile. An
actual CLI `health-detail` probe has passed its required checks. Its native and
semantic adapters themselves still contain PowerShell calls; their connection
must also be migrated before claiming a complete runtime retirement.

`PcuCp.LegacyDesktop` now ports the 24 non-CDP native helper actions using the
existing Framework interop, observation and image libraries. Its typed Python
transport routes OCR matching to the existing native kernel. Startup authority
is separate from JSON/argv and a missing worker never selects a script fallback.
UIA pattern errors after dispatch return an uncertain outcome rather than trying
another action. `publish_legacy_desktop.py` builds the separate package explicitly.

Local owned-file checks cover actual WinRT OCR and matching. One disposable
Windows form has additionally verified background UIA value/invoke/toggle,
foreground focus, guarded Unicode input, refusal for a mismatched target, and
IME paste with clipboard restoration. This is proof of these owned scenarios,
not of every public macro or third-party application. The GUI surface lives in a
separate qualification project and is excluded from the production package.

## Verification and remaining cutovers

The Windows provider job builds the actual NativeHost, exercises all nine
diagnostics (including full/cold perf), retained find-label, appshot cold/warm
cache and audit, Unicode paths, missing dependencies, and shared sampling
deadlines. It also runs adjacent framing, cancellation and frozen dispatch tests.
It does not certify live input, real desktop CLI execution, or complete retirement.

Before deleting production scripts, connect all remaining interaction/execution/
precision providers, top-level argument aliases and Node forwarding; retain
recorder/daemon ownership and helper/autostart behavior; port native input, OCR,
clipboard/IME, app/vision paths and installation; and validate the corresponding
existing corpora and owned Windows scenarios. Final retirement must remove every
tracked PowerShell file and every runtime/installer/CI PowerShell invocation,
while preserving the supported registry and meaningful negative results.
