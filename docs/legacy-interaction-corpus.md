# Interaction oracle corpus

The interaction qualification corpus contains **870 deterministic source-parity fixtures** for eight functions. Each source scenario runs in normal and `-Brief` modes. Twelve additional boundary fixtures verify explicitly uncertain live replies and post-click readback failures separately from the source-parity gate. The corpus has a bounded reply list and bounded precision/focus loops; it does not sample randomly.

| Operation | Fixtures |
| --- | ---: |
| `find-label` | 178 |
| `click-point` | 158 |
| `safe-type` | 128 |
| `click-label` | 108 |
| `icon-find` | 116 |
| `ocr-click` | 84 |
| `precision-validate` | 50 |
| `icon-click` | 32 |

## Oracle and scope

`tests/python/test_legacy_interaction_parity.py` extracts `scripts/cucp.ps1` from accepted tree `c0d15371b60ebf62be45bfa68b90282405f07273`, reachable from remote commit `56be343c786027d27fa3dcb71732157caffc8de0` (the identical tree of local accepted commit `d78ea2bd0ea3ced7121beafd6888209dae872add`). Pinning the reachable tree makes the oracle available in CI. That source already contains the authorized SafeType correction: no probe text, only focus preparation retries, and no automatic replay of click, text, or submit failures.

The original baseline tree is `bf895d3120dd5e145f360cb1c41e1d79a061d048`. It supplies only the original, pure `_PointPlan-CacheKey` body because the accepted source's cache-key wrapper delegates to its separately migrated kernel. It is not the SafeType oracle.

`tests/fixtures/legacy-interaction-oracle.ps1` parses the pinned files with the PowerShell AST and loads only named functions. It never dot-sources the production script, launches another production PowerShell process, acquires a desktop, injects input, reads or writes a clipboard, changes an IME, or invokes a model.

The `PcuCp.LegacyInteraction.ContractTests --fixtures` runner receives the same bounded captured replies. The qualification compares the accepted function's raw object before JSON formatting, exact effect descriptors and order, consumed reply count, pipeline output, errors, exit codes, and console text. Console rendering is checked using Windows PowerShell 5.1 itself at the original serialization depth. Native raw writes retain their lack of a terminating newline. Dictionaries shaped `value`/`Count` remain ordinary objects; no wrapper detection unwraps them.

## Captured boundaries

| Kind | Captured descriptor |
| --- | --- |
| `Native` | Original helper `argv`; only `focus`, `click`, `type`, and `shortcut` are live |
| `Cucp` | Original CUCP `argv`, live |
| `Appshot` | `match`, `semantic`, `no_cache` |
| `Win32Windows` | `match` |
| `UIAffordances` | `focused_window`, `max_elements` |
| `Vision` | `screenshot_path`, `description` |
| `HitTestPoint` | `x`, `y`, `target_hwnd`, `target_match` |
| `PointCacheRead` | `key`, `max_age_seconds` |
| `PointCacheWrite` | `key`, raw `payload` |
| `CoordProfile` | `has_point`, `x`, `y`, `target_hwnd`, `target_match` |
| `AnchorScore`, `AnchorAppend` | Raw `record` |
| `Notice` | Level in `name`, original text in `data` |
| `PipelineOutput` | Original output line in `data` |
| `TrajectoryAppend` | Original kind in `name`, raw payload in `data` |
| `Console` | `name=write`, exact raw text without adding a newline |
| `Sleep` | Millisecond count; no actual sleep |

Native/CUCP replies retain the real `{ExitCode, ElapsedMs, Raw, Json}` shape. Each consuming seam advances one reply. Trace-only writes, notices, output, and sleeps do not advance the cursor. Captured effect data is snapshotted when dispatched so a later PowerShell `Add-Member` cannot retroactively change an earlier trace entry.

Time is fixed at `2026-10-02T00:00:00.0000000Z`; elapsed measurements are 37 ms. Generated icon-click observation IDs use the fixed suffix `0123456789ab`. These deterministic primitives do not consume replies or appear as external effects. Pure find/center/envelope helpers execute from the pinned source. The JSON interceptor preserves the real cmdlet's zero/one/multiple pipeline aggregation. Nested `icon-find` executes its real source logic with a captured UI-affordance query; its internal JSON is not mistaken for final output.

## Coverage

- Required arguments, permission precedence, first matching case-insensitive options, malformed numeric casts, aliases, clamps, empty strings, and Unicode
- Find-label fast guards, appshot failures, source tiers, exact/substring/prefix scoring, confidence types, whitespace normalization, ambiguous ties, role/window filters, cache provenance, and output truncation
- Icon synonyms/tooltips, size edges, near-point rounding, negative or zero anchors, radius, limit-before-ambiguity, nested icon-click, and synthesized observation IDs
- Click-label direct/icon/vision routes, double/right combinations, offsets, captured fallback failures, source priority, notices, and pipeline strings
- Click-point fast guards, automatic and explicit micro refinement, cache hits/misses, scan failure gates, optional unrefined clicks, anchor scoring/recording, raw native output, raw object shapes, and scalar/empty/singleton/multiple native JSON values
- SafeType target ambiguity, 64-bit HWNDs, focus-only retries, optional click and submit, failed mutation stop points, ignored legacy probe flags, and control-like text treated as data
- OCR minimum-score edges, malformed/valid regions, language and button forwarding, raw output, and failure exits
- Precision sample clamps, malformed sample fallback, exceptions, partial evidence, and drift boundaries at 2 px and 5 px
- Tied candidate orders at 2, 3, 4, 7, 16, and 17 elements; composed/decomposed Latin and Hangul text; distinct duplicate identities; explicit empty/singleton arrays; and changed target/focus/cache identity
- Twelve separate uncertainty cases assert that live dispatch and post-click readback loss stop at the exact boundary without automatic retry or later trajectory effects
- Thrown replies at every consuming boundary of representative multi-effect routes, with exact trace and consumption checks

## Running

Portable static and candidate checks:

```sh
CUCP_INTERACTION_DOTNET=/path/to/dotnet python -m unittest discover -s tests/python -p test_legacy_interaction_parity.py -v
```

Windows PowerShell 5.1 qualification runs automatically on Windows. `CUCP_INTERACTION_POWERSHELL` may select its executable explicitly. `CUCP_INTERACTION_DOTNET` or `DOTNET` selects the .NET SDK. The default runner rebuilds Release once per Python process. For a diagnostic against an explicitly built binary, `CUCP_INTERACTION_TEST_DLL` can select that DLL; this override does not rebuild it and must not be mistaken for a fresh-build qualification. A PowerShell 7 diagnostic may call `run_oracle(fixtures, portable=True)` explicitly; that mode is not a Windows PowerShell 5.1 qualification result and is never selected by the Windows gate.

A skipped platform/runtime check is not a parity pass. This corpus by itself does not promote an adapter, change the startup authority model, or prove real desktop behavior.

## Current verification

The 870-case candidate corpus executes without fixture exhaustion on the local .NET fixture runner; the 12 explicit boundary assertions also pass. All eight portable test methods pass. Windows PowerShell 5.1 is unavailable in this environment, so the exact accepted-oracle differential and exact console gate remain pending; their platform skip is reported explicitly.
