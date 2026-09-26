# Core preview validation — 2026-09-26

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

- Run the Windows build/publish and both new Pester regression and compatibility
  suites. No PowerShell runtime was available in this development environment.
- Exercise real capture, UIA, input and cancellation on a dedicated interactive
  Windows desktop, including Korean text/IME and application acceptance.
- Verify mixed DPI and negative-origin monitors, occlusion, focus races, window
  movement/closure and stale observations.
- Verify normal versus elevated application behavior through normal human UAC
  consent. The launcher currently elevates the whole Pi session. UAC secure
  desktop and SYSTEM/protected-integrity targets are outside the supported scope.
- Verify Windows child-process cleanup; current taskkill tree termination is not
  the same as Job Object ownership when a parent crashes first.

The GitHub workflow specifies Linux contract checks and Windows compilation /
Pester checks. It has not run remotely as part of this local change. Hosted CI
compilation is not evidence of interactive desktop behavior.

See [the roadmap](core-modernization.md) for the generic Windows test matrix and
[setup](../pcucp-next/README.md) for commands. No model benchmark score or
unmeasured latency claim is presented as a CUCP result.
