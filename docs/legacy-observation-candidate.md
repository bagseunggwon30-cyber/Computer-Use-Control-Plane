# One-shot geometry/UIA observation candidate

Status: staged, unqualified. Default execution and all original bodies remain.
No original PowerShell retirement is claimed by this candidate.

## Boundary and routing

The separate net48 `PcuCp.LegacyObservation` library moves real read acquisition
and decision work for the legacy one-shot helper. `WindowsObservationProvider`
uses the exact existing `PcuCp.LegacyInterop` / `CucpNative` ABI and the framework
`AutomationElement` APIs. It does not use the persistent helper's fast-find
semantics, modern NativeHost UIA reference store, script callbacks, serialized
UIA elements, a generic effect executor, or a new cache.

`CUCP_LEGACY_OBSERVATION_CANDIDATE=1` selects the ordinary adapter from the real
`scripts/cucp-native-helper.ps1` dispatch. Unset leaves the original functions
active. Other nonempty values fail closed. `CUCP_LEGACY_OBSERVATION_DLL` may point
to the separately built candidate. This selector is qualification-only. The
portable installer/package defaults are unchanged.

The original `_Ensure-Win32Native`, `_Ensure-UIA`, `_Emit`, parameter binding,
outer catch/dispatch, `_Resolve-UiaElement`, mutation bodies, and OCR acquisition
remain. Refinement's compiled provider loads UIA lazily in original assembly
order; `SkipUia` hit-test performs no UIA reads. UIA tree/find retain their original
PowerShell load gates. The closed provider has no input or pattern execution
operation. `Current`, element, root and pattern objects remain in-process.

## Source map and mapped equivalents

Pinned source: public commit `8f3cdde59d2d9574cfd036bab0b4c0bae0940c89`, tree
`c84b6c3963bb20f7f8f76562f0d0d8cc549beafb`; local equivalent
`5232048f68300f3d536822f96713124fc13b3757`. The manifest under
`tests/fixtures/legacy-observation/source-manifest.json` pins the raw Git blob,
SHA-256, normalized hash, all UTF-16 extents, function hashes, exact UTF-8 sizes,
and every permitted acquisition-type substitution. Windows qualification checks
those extents against the actual PowerShell AST before loading definitions.

| Retained original | UTF-8 bytes | Typed equivalent |
| --- | ---: | --- |
| `_Action-HitTest` | 2,895 | `ObservationActions.HitTest` |
| `_Action-HitScan` | 6,103 | `ObservationActions.HitScan` |
| `_Action-UiaTree` | 3,026 | `ObservationActions.UiaTree` |
| `_Action-UiaFind` | 5,269 | `ObservationActions.UiaFind` |
| `_Get-UiaSupportedPatternName` | 573 | `ObservationPrimitives.SupportedPattern` |
| `_New-UiaMatchPayload` | 1,247 | `ObservationPrimitives.MatchPayload` |
| `_Get-RoleWeight` | 355 | `ObservationPrimitives.RoleWeight` |
| `_Clamp-UiaPointToRect` | 1,150 | `ObservationPrimitives.Clamp` |
| `_Get-UiaPreferredClickPoint` | 704 | `ObservationPrimitives.PreferredClickPoint` |
| `_Resolve-UiaPointRefinement` | 2,521 | `ObservationPrimitives.ResolvePoint` |
| `_Test-CoordsInTarget` | 1,373 | `ObservationPrimitives.TestTarget` |
| Total retained, not retired | 25,216 | |

Original tests/oracles are neither removed nor rewritten. Three added PowerShell
files are ordinary tracked files included in inventory totals: the adapter,
pinned-source oracle driver, and typed-argv wrapper driver. The generated owned
window is a checked-in C# fixture, not embedded PowerShell. The oracle also pins
the unchanged `_Action-Click`, `_Find-SmallestUiaElementAtPoint`, and
`_Resolve-OcrUiaFusionCandidate` functions.

## Qualification gate

Run `python pcucp-next/packaging/qualify_legacy_observation.py --windows` on a
Windows host with Windows PowerShell 5.1, .NET Framework 4.8 and SDK 8. The dedicated
`legacy-observation-candidate.yml` workflow retains raw process evidence before
assertions, source/driver hashes, and a summary. It never changes defaults.

1. Portable contracts exercise the four action ports and seven shared helpers
   with an inert provider. These are logic contracts, not Windows proof.
2. The Windows exact-source oracle compares 95 original/candidate pairs. It
   retains full payloads, exit/status envelopes, ordered acquisition traces,
   null/scalar/array shapes, and raw diagnostics. Cases cover failure/load order,
   zero/negative/fractional geometry, Unicode/culture, title/class truncation,
   absent/failed process reads, property/pattern faults, no-root fallback,
   accepted-record budgets, duplicate/tied ranking, top-five/top-twelve shapes,
   virtual-screen clipping and the admitted 16,641-sample maximum.
3. The actual unchanged click function runs only with an inert native type seam.
   Original target mismatch must stop before refinement and reach zero mutation
   boundaries. Refined mismatch must recheck, restore the original point and clear
   refinement before exactly one inert `SendMouseClick`. Successful and unguarded
   cases also reach exactly one inert boundary. Pattern mutation tripwires count
   an attempt before throwing, so catches cannot hide it. The unchanged fusion
   resolver must preserve original element, current and root identity.
4. An owned WinForms process supplies known PID/HWND/geometry, a unique Unicode
   label, nested controls, duplicates, disabled and offscreen controls. The gate
   compares 11 actual original/candidate helper entries and three actual wrapper
   entries (`macro hit-test`, `macro hit-scan`, and `macro smart-plan --no-cdp`).
   The smart-plan recommendation is inspected, never executed. Per-case expected
   statuses and owned geometry must pass; equality between two failures is not
   accepted. Missing-DLL and invalid-selector probes prove fail-closed candidate
   entry routing. The actual-provider runs use `WindowsObservationProvider`, not
   the inert test seam.
5. TEMP/TMP and USERPROFILE are isolated to newly owned fixture directories.
   Cleanup uses the retained owned process object and a private close request;
   no process-name/PID search or unrelated window operation occurs. Readiness and
   shutdown input/invocation/value-change counters must all be zero.

A missing/unusable hosted desktop, wrong PowerShell version, empty UIA tree,
provider failure, missing readiness, or missing cleanup evidence fails clearly.
It is not converted into a skip or synthetic success. Every pair failure is
retained; a synthetic mismatch does not suppress the separate actual-entry pass.

### Equality policy

Only root action `elapsed_ms` (or the oracle's `captured.payload.elapsed_ms`) is
excluded from equality, after requiring a nonnegative integer. `_Emit` at
`cucp-native-helper.ps1:704-720` stamps this stopwatch measurement, and wrapper
hit-test/hit-scan pass the JSON through while SmartPlan stamps its own elapsed
measurement. No decision uses that measurement in these selected routes. Raw
stdout/stderr and timing remain retained. No diagnostic text, nested timing field,
array order, source field, number, scalar/array shape or acquisition event is
blanket-normalized. Uncaught method-wrapper diagnostic differences are currently
unqualified, not accepted by assumption.

Equal-key order specifically requires Windows PowerShell 5.1 evidence. The
candidate uses full `List.Sort` with precisely the original numeric keys and no
stable-index tie-break; portable .NET 8/10 ordering is not proof of the PS5/net48
execution order. Actual one-shot oracle ties, not persistent-helper fast-find
fixtures, decide acceptance.

## Current validation and remaining acceptance

Local Linux checks: net48 library, qualification assembly and owned WinForms
fixture compile; the linked net8 contracts pass 195 assertions; the new Python
structural/evidence tests pass 21 tests. Local net8 execution uses runtime 10
roll-forward. These are not Windows acquisition or PowerShell qualification.
Full local Python discovery ran 868 tests: 647 passed, 221 individual skips,
zero failures/errors, plus two setup skips (223 total skip records). No skipped
Windows tests earn proof. SDK 10.0.401/runtime 10.0.12 were used locally. The net48
compile used cached framework reference assemblies with `NuGetAudit=false` after
the environment denied the default vulnerability-cache write; this is not a
package security audit. The checked-in Windows gate does not disable that audit.

The candidate adds 12,397 counted PowerShell bytes (934,232 to 946,629). The
baseline-wide census is 1,013,478 original bytes, 946,629 current bytes and 66,849
net removed bytes from earlier qualified work. All 25,216 bytes targeted by this
candidate are still present; this batch receives zero retirement credit.

Independent source review found no remaining blocker for an opt-in unqualified
candidate after repairing stale readiness-file reuse and exact negative-outcome
assertions. It independently reran all 195 inert assertions and 21 Python tests.

Still required before promotion or removal: the exact Windows gate above, review
of raw pair/effect evidence, the full regression gate, and a fresh complete tracked
PowerShell census. Third-party provider behavior/hangs, real clicking/typing/IME,
mixed-DPI/multi-monitor, elevated/UIPI/session behavior, OCR acquisition and
clipboard restoration remain later separate acceptance. This candidate does not
perform or expand those effects.
