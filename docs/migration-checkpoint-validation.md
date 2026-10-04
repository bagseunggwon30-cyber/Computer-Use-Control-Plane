# Python/C# migration checkpoint: verification and limits

Source checkpoint date: 2026-10-01 UTC. This is a feature-branch checkpoint, not full legacy retirement.

## Baseline integrity

The isolated working copy's starting Git tree was verified as `bf895d3120dd5e145f360cb1c41e1d79a061d048`, exactly the published `9ffa354b9904235835a7bc6eb78ed8d3d76317c8` tree. All earlier 42-file modernization changes are included. The original working copy and its artifacts were left untouched.

## Evidence collected before publication

| Check | Result | What it establishes |
|---|---|---|
| Python unittest discovery | 192 total: 191 passed, one real-native Windows test skipped | All baseline tests plus workflows/tasks/forms/watch/recording, adapters/CLI, OCR/fusion/PNG/diff and new UIA argument wiring |
| C# pure contracts | 12,869 assertions passed | UIA request/authority/one-dispatch/failure contracts, states, OCR request/bitmap budgets, typed capture JSON compatibility, and earlier native/input/lifetime contracts |
| Windows-targeted production build | Release, warnings as errors, 0 warnings/errors | Cross-compilation under .NET SDK 10.0.401; target remains .NET 8 Windows |
| C# contract execution | .NET 8 contract app executed using installed .NET 10 major roll-forward | Pure contracts only; production Windows APIs were not executed on Linux |
| Actual Python subprocess CLI/MCP | Passed | Handshake/listing, source CLI planning/dry-run, immutable read-only gates, no native/PowerShell required for pure planning |
| MCP and JSONL form workflow | Passed with injected native fixture | Same exact-selector/Unicode/no-retry orchestration through both transport adapters |
| PNG processing | 33 focused observation fixtures passed | Legacy-like scoring, phrase geometry, bounded fusion, CRC/filter/deflate handling, masks, dimensions and alpha policy |
| `git diff --check` | Passed | Whitespace consistency |

CI on the exact published branch commit must be checked separately. The Windows portable smoke was expanded to exercise frozen workflow, OCR/diff module availability, recording and MCP tool schemas without desktop input. A locally successful cross-build does not substitute for that packaging job.

## Language migration measurement

- Retained PowerShell runtime functions: all 298
- PowerShell runtime bytes removed at this checkpoint: **0**
- Legacy source files hidden from language statistics: **0**
- Legacy behavior intentionally deleted to lower PowerShell percentage: **0**

The new 40-tool Python/C# runtime does not invoke PowerShell. The separate source-only compatibility route still does. Replacing runtime dependence and retiring old source are different milestones; neither byte-for-byte legacy CLI parity nor a zero-PowerShell repository is claimed here.

## Still unverified or not ported

- Actual Windows UIA toggle/selection/expand/scroll provider behavior, live form outcomes and data entry, changed-state races, hidden/disabled/password providers and stalled providers
- Live window capture→OCR in installed languages, recognition accuracy, mixed-DPI geometry/occlusion and screenshots produced by real Windows app surfaces
- True physical IME composition, clipboard save/restore workflows, long/cross-window/held-input gestures
- CDP discovery/DOM/eval/prosemirror and optional model vision adapters
- Full legacy command-string workflows, broad task presets, persistent recording/strategy histories, recovery dismissal and background/autostart helper services
- Installer/elevation compatibility, remaining legacy system/process/registry macros and all legacy PowerShell test equivalence
- Interactive parent-death/OS crash acceptance, signing and a stable release

No authenticated AI provider was invoked. No user's desktop was operated. Input success is not evidence that a document was saved or a business task completed. The user or authorized host still decides consequential actions and data destinations.
