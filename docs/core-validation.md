# Core preview validation — 2026-09-26

This document records the initial 0.2.0 preview. See
[the resident-session validation](resident-native-session.md) for the 0.3.0
implementation and its 72 Python / 12,199 native assertions.

After publication, the Windows .NET build and native contracts passed on
[the first GitHub run](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/36215990046).
The Pester 4 installation failed due to a certificate-chain mismatch against the
preinstalled Pester 5. The follow-up migrated the regression suite to Pester 5;
[the subsequent Windows run](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/36216294498)
passed the build, 12 resident-transport tests and 14 Pester regressions.

Base revision: `adc2413760d9b94525d666fa3c598594300644fc`.
Development branch: `feature/pi-computer-use-core`.

| Check | Result | What it establishes |
| --- | --- | --- |
| Python unittest suite | 60 passed | Session policy, coordinates, stale observations, partial outcomes, sequential batches, native transport, JSONL process protocol and planning |
| Pi TypeScript check | Passed against published Pi 0.87.1 types | Extension API compatibility at compile time |
| Pi Node tests | 15 passed | Real child-process transport with a mock engine; queue, abort, lifecycle, image/error handling |
| Pi → actual Python engine | Passed | Capabilities, default read-only denial, unknown-command rejection, mode restart, stale-observation denial |
| Full C# source compilation | Passed, warnings treated as errors | Source typechecks against actual .NET 8, WPF and Windows SDK references |
| C# pure contracts | 12,184 assertions passed | INPUT ABI, representative per-pixel coordinate mapping, argument authority, privilege boundaries; no live input |
| Native non-Windows protocol smoke | Passed | Version JSON, unsupported-platform exit 1, malformed authority exit 2 |
| Whitespace/diff checks | Passed | No patch whitespace errors |

The development environment is Linux. Its process metadata API prevents normal
.NET CLI/MSBuild startup. Native source was compiled directly using the .NET
8.0.414 Roslyn compiler and actual .NET/WPF/Windows SDK reference assemblies.
That is evidence of compilation, not a successful Windows publish or GUI test.

The 12,184 native assertions include exhaustive pixel checks over selected
coordinate ranges; they do not represent 12,184 end-to-end application tasks.

## Remaining release gates

- Run self-contained Windows publishing and the older compatibility suite.
  The Windows build and new Pester regressions have since passed in CI.
- Exercise real capture, UIA, input and cancellation on a dedicated interactive
  Windows desktop, including Korean text/IME and application acceptance.
- Verify mixed DPI and negative-origin monitors, occlusion, focus races, window
  movement/closure and stale observations.
- Verify normal versus elevated application behavior through normal human UAC
  consent. The launcher currently elevates the whole Pi session. UAC secure
  desktop and SYSTEM/protected-integrity targets are outside the supported scope.
- Verify Windows worker-only cleanup and inherited parent-handle watchdog on actual
  parent crashes. Launched user applications must survive; no taskkill tree termination
  or Job Object ownership is used by the new core.

The GitHub workflow specifies Linux contract checks and Windows compilation /
Pester checks. The remote follow-up results are linked above. Hosted CI
compilation is not evidence of interactive desktop behavior.

See [the roadmap](core-modernization.md) for the generic Windows test matrix and
[setup](../pcucp-next/README.md) for commands. No model benchmark score or
unmeasured latency claim is presented as a CUCP result.
