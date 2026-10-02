# Interaction and target planning candidate

This isolated C# candidate covers `find-label`, `click-label` (including its
right/double switch modes), `click-point`, `safe-type`, `icon-find`, `icon-click`,
`ocr-click`, and `precision-validate`. The original PowerShell functions remain
in production. No source retirement or zero-PowerShell completion is claimed.

The accepted behavior oracle is `scripts/cucp.ps1` at tree
`c0d15371b60ebf62be45bfa68b90282405f07273`, reachable from published commit
`56be343c786027d27fa3dcb71732157caffc8de0` (and local checkout commit
`d78ea2bd0ea3ced7121beafd6888209dae872add`). The original
`bf895d3120dd5e145f360cb1c41e1d79a061d048` tree supplies only the already-qualified
pure point cache-key body in the oracle. In particular, SafeType preserves the
accepted no-probe/no-replay fix; the older unsafe SafeType body is not the oracle.

## Scope and byte accounting

Verified parser AST extents, rather than regex regions, are the retirement scope:

| Original function | UTF-8 bytes |
| --- | ---: |
| Invoke-MacroFindLabel | 12,541 |
| Invoke-MacroClickPoint | 14,896 |
| Invoke-MacroClickLabel | 5,993 |
| Invoke-MacroSafeType | 4,642 |
| Invoke-MacroIconFind | 8,258 |
| Invoke-MacroIconClick | 2,416 |
| Invoke-MacroOcrClick | 2,686 |
| Invoke-MacroPrecisionValidate | 3,661 |
| Total | 55,093 |

The initial function-to-next-function inventory was 56,831 bytes; it includes
1,738 bytes of separators/comments outside these AST extents. Neither number is
net retirement. Adapter/test overhead and retained shared leaves must be counted
before any future source-reduction claim.

`Find-Element`, `Get-ElementCenter`, `_New-ObservationEnvelope`, label score
pooling and PS5 numeric-score sorting are pure in-process helpers in the
candidate. Existing original helper definitions remain because other production
callers still use them. The candidate uses `LegacyPrecisionKernel.CacheKey` and
`Hash`; it does not introduce another precision-cache format.

## Integration interface

`PcuCp.LegacyInteraction` contains partial `LegacyExecutionCoordinator` sources.
It uses the same immutable `LegacyExecutionAuthority`, result, effects, tagged
wire codec and streaming session. `RunInteraction(operation, doubleClick,
rightClick)` is the candidate entry. The existing session's callback overload
can run that entry without a second protocol or process bridge. The sources props
file imports only this family; an embedding host must also include the qualified
execution/precision dependencies.

The integrator owns production dispatch/startup registration, exact retained
PowerShell adapters and future removal. A final adapter must preserve:

- The original global live/sensitive macro checks and immutable process ceilings
- `LegacyExecutionResult` payload, exit, depth and emit-json fields
- `PipelineOutput` as PowerShell pipeline output, not Console output
- `Console` with `name=write` as a raw write with no appended newline
- Nested IconFind acquisition in the same in-memory call; no growing reply replay
- Actual names and arities below; unknown descriptors fail before dispatch

All new effect names are empty unless explicitly listed:

| Kind | Data or arguments | Live |
| --- | --- | --- |
| Appshot | `{match,semantic:true,no_cache}` | false |
| Win32Windows | `{match}` | false |
| UIAffordances | `{focused_window,max_elements:800}` | false |
| Vision | `{screenshot_path,description}` | false |
| Cucp | argv starts `act click` or `act right-click`, then x/y/after and optional target-window | true |
| HitTestPoint | `{x,y,target_hwnd,target_match}` | false |
| PointCacheRead | `{key,max_age_seconds}` | false |
| PointCacheWrite | `{key,payload}` | false |
| CoordProfile | `{has_point:true,x,y,target_hwnd,target_match}` | false |
| AnchorScore | `{record}` | false |
| AnchorAppend | `{record}` | false |
| Notice | name `ERROR` or `WARN`; data is message string | false |
| PipelineOutput | data is output string | false |
| ObservationId | name `icon-click`; null data; returns full synthetic ID | false |

The existing `Native` kind is explicitly classified inside this candidate:
`focus`, `click`, `type`, `shortcut` are live; `windows`, `ocr-find-text`, and
`hit-scan` are acquisition. No unlisted native action is accepted. Point cache
and anchor writes are local persistence effects, not input authority; their
existing storage implementations and configured roots remain authoritative.
The candidate also uses existing Clock, Timestamp, Sleep, TrajectoryAppend and
Console effects. String parameters to legacy leaf seams use empty string for
missing values, while untyped report properties retain null.

Native and Cucp results retain `{ExitCode,ElapsedMs,Raw,Json}`. The internal
uncertainty envelope may use lowercase `exit`; this is not a second public wire
shape. The callback fixture does not execute commands, invoke models, move the
mouse, change clipboard/IME, write history or sleep.

## Preserved behavior and bounded correction

FindLabel retains fast-window short circuit, pool confidence, whitespace
normalization, ambiguity window, exact Console/public shapes, cache provenance,
and the historical exit-one not-found result. IconFind keeps size/near filters,
round-to-even coordinate and distance conversions, truncation before ambiguity,
and the singleton array shape when a multi-candidate list is truncated to one.
PS5 median-pivot sorting deliberately swaps equal keys; stable LINQ sorting would
change target selection. FindElement sorts the full tier/score list together.

ClickPoint retains guard, micro-refinement cache/scan/write, optional anchor
profile/score, action, successful anchor append and trajectory ordering. Its
cached points and history use the existing precision kernel/storage contract.
ClickLabel preserves direct/icon/vision paths, optional second action, notice
ordering and its unusual Brief pipeline output. IconClick preserves the existing
fresh observation and synthetic ID fallback. OCR threshold failure emits no JSON
when not brief. PrecisionValidate preserves per-sample exception continuation,
30ms captured sleeps, evidence and drift thresholds.

SafeType resolves a unique title/HWND before focus, retries only focus preparation,
pins the verified foreground identity, never injects an old probe string, and
never replays click/text/submit after ordinary failure. Input dispatch does not
claim the app accepted or saved text. Its historical last focus failure reason
is retained even if a later attempt succeeds.

Explicit `mutation_may_have_occurred:true` from a live effect is terminal before
any fallback, second click, success history, or trajectory append. A failed
read/persistence effect after input cannot enter a caught legacy fallback.
The shared session reports uncertainty after a lost/malformed live reply and
sets automatic_retry false. These qualified execution-boundary corrections are
separately tested, not represented as exact parity with a PS body that ignored
uncertainty metadata. Ordinary captured errors remain on the exact parity path.

## Evidence and remaining gates

The managed candidate compiles for net8 with zero warnings/errors. The local
self-test runs 106 checks on Linux and 109 on Windows, including immutable live denial, all four
native mutation classifications, uncertainty/no-replay, verified target identity,
equal-score selection, malformed shared-session frames and a reply larger than
1MiB split into bounded frames. The Python fixture corpus and exact oracle details
are documented in `legacy-interaction-corpus.md`.

Linux candidate/fixture checks do not qualify PS5.1 Console formatting or Windows
NLS ordering. The Windows pinned-oracle differential, exact actual-adapter gate,
production integration and bundled full regression remain required before
retirement. Actual acquisition/input/IME/clipboard/model leaves remain separate
Windows acceptance work. No mock result is evidence of interactive desktop input.

## First Windows candidate feedback

Run `37037485035`, interaction job `110939232562`, compiled the host and passed
86 managed checks, then found 71 exact candidate differential mismatches. Those
failures identified singleton conditional-source unrolling, an empty
Select-Object pipeline represented as `{}`, singleton icon array retention, PS5
Decimal confidence handling, Windows NLS Hangul matching, and native-array
member projection/missing-exit behavior. The candidate repairs these behaviors
and adds managed regressions while preserving all 854 exact oracle fixtures and
12 uncertainty fixtures. The next Windows differential is still required; the
first failed run is diagnostic evidence, not qualification.


## Confidence acquisition and Int32 boundary repair

The confidence type rule follows the production acquisition path, not just the
fixture decoder. In the pinned accepted tree, `Get-CachedAppshot` and
`Invoke-Appshot` load cached/fresh artifacts with `ConvertFrom-Json` (lines 1677
and 1722). `_Build-AppshotResult` assigns Items, FusedElements and Grounded from
those parsed artifacts (1755–1768), falling back to `_Get-UIAffordances` only when
the grounded pool is empty. The UIA fallback assigns `$conf` to `medium`, `high`
or `low` strings (2000–2006), then copies it to each element (2045).
Consequently acquired JSON fractions are PS5 Decimal values and receive no
numeric confidence boost; acquired Int32 values retain the original boost.
Preconstructed in-process Double confidence objects are not represented by this
JSON acquisition contract and are not claimed as supported inputs.

Sixteen appended oracle cases cover confidence 429496729, 429496730,
-429496729 and 2147483647 in FindLabel and IconFind, each in normal and Brief
mode. All original 854 cases retain their indices; the ordinary corpus is now
870 plus the same 12 uncertainty cases. FindLabel's explicit product-to-Int32
cast uses the existing `LegacyPrecisionKernel.I` compatibility helper so an
out-of-range product preserves the original cast error. Subsequent untyped
confidence/score additions preserve Int32-to-Double promotion, comparison and
integral Double JSON spelling. The shared FindElement ranking also avoids
Int32 wrapping. IconFind still ignores numeric confidence. These new probes,
like the six earlier Windows repairs, require the next exact PS5 oracle gate.
