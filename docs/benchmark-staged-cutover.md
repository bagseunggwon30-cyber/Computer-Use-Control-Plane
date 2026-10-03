# Benchmark-only staged production cutover

This local stage follows the Brief harness correction in `6ea356c` and the
separately qualified audit-summary body retirement at `3cbbaaad` /
run `37103102449` attempt 2 (all 14 active required core jobs). It is not accepted retirement or publication.
The benchmark's verified 5,389-byte original body is replaced by a 128-byte
fixed delegate to the existing closed diagnostic adapter/session. No original
benchmark runtime copy or fallback remains. All nine public diagnostic entries
now use their fixed delegates in this staged tree.

The only runtime routing changes are entry into the already qualified candidate
and its established session behavior. A matching NativeHost is now required for
benchmark; missing runtime must fail before effects. The eight established
uncertain-owned-effect cases stop at the same exact effect/reply boundary with
the existing `mutation_may_have_occurred=true; automatic_retry=false` error and
empty Console. No new failure category or permission is allowed.

## Evidence and retained assertions

Candidate run `37103413852` at `fa1c830e` passed the unchanged 668-case gate:
660 exact candidate records and eight established owned failures. All 258 audit
production/direct pairs passed. The newly added benchmark functional gates
failed on a Brief harness assumption after saving all raw arrays. The reviewed
[offline reassessment](benchmark-functional-qualification.md#saved-windows-evidence-and-brief-harness-repair)
confirms all 72 Decimal public pairs exactly and all 16 calendar cases
functionally (12 exact public pairs, four permitted detail-only differences).
The failed CI manifests remain unchanged and are not described as passing.

This cutover adds the current public production route to both functional gates.
Every one of their 88 cases must have an exact production/direct-candidate pair
before the original/pure/actual functional comparisons can pass. Brief absence
remains explicit; no synthetic public payload is substituted.

The 668 historical inputs and all prefix hashes remain unchanged. Their fixed
membership is independent of the now-empty `RETAINED_DIAGNOSTICS`. The existing
original/pure/actual assertions stay intact. Production/direct equality is now
required for all 410 benchmark cases as well as the existing 258 audit cases.
Both production and direct-candidate partitions must be exactly 660 exact,
eight owned failures and zero terminal failures. The owned-failure IDs are
pinned to `existing/24`–`existing/27` and `existing/55`–`existing/58`, preventing
a count-only substitution of newly tolerated cases.

Both oracle selectors remain an exact partition of the nine current public
entries: six runtime reports and three file reports. Production imports the
current delegate AST before acquisition rewriting; historical imports keep the
original body and seams. The public forwarding map now checks all 18
operation/Brief combinations. Source guards verify a single exact benchmark
delegate, no original runtime copy, and no adapter catch/fallback. The existing
196 authority/descriptor guards and full 323-case gate remain intact.

Actual main-script startup now covers benchmark with literal consent-like
arguments, false live authority and exactly one module load/call. Missing
support, duplicate loading and blocked provider checks include benchmark while
retaining the earlier perf/audit controls. The no-runtime test requires both
audit and benchmark to fail before any effect or consumed reply.

## Source accounting and release boundary

Benchmark body saving is 5,261 bytes. Supporting PowerShell selectors/maps and
comments add 70 bytes, so total tracked PowerShell in this staged tree falls
from 907,688 to 902,497 bytes, a physical reduction of 5,191 bytes. The original
baseline remains 1,013,478 bytes; physical removal is 110,981 bytes. Inventory
records the benchmark under `retired_bodies` with status
`staged_candidate_not_accepted`, retaining both original/delegate hashes. These
numbers do not grant accepted retirement credit.

Required next checks are fresh matching-source Windows diagnostics, all current
production-entry/startup/negative assertions, source-mapped artifacts, independent
review and the full regression/portable-package lane. No audit contract,
numeric conversion, protocol integer validation or effect authority is changed
by this routing stage.

Local staging validation passed 757 SDK-enabled Python tests with 153 explicit
platform/availability skips. NativeHost built with zero warnings/errors. Managed
diagnostic checks passed (14 + 37 + 24 + 28 + 67 + 3 + 18), alongside 994
execution and 110 startup checks. Inventory and diff checks passed. Independent
review found and corrected a stale selector exclusion, then found no remaining
code blocker. These local results do not replace the required fresh Windows
production-entry run or the accepted full-regression decision.

## First fresh production observation, not full qualification

At public `bb98df41d120cde6c6a2a18628e385d7ad432709`,
[full run 37107497220](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/37107497220)
finished with 12 of 14 active jobs passing. The production comparison itself
completed: all 668 cases met the closed contract, partitioned as 660 exact
original agreements, eight explicitly pinned owned failures, and no terminal
failures. All 410 benchmark and 258 audit production/direct pairs were exact.
The additional 16 calendar and 72 Decimal production cases passed their stated
functional criteria. All three raw manifests retain `finished`,
`comparison_completed`, and `qualification_passed` as true for those comparisons.
The verified diagnostics artifact is 11269040974, SHA-256
`256eea20d2fc9cb9ba37d4294766fe67d29d6a25e997bdddd30e4b203ff4ee50`.

Two independent harness problems kept the full gate red:

- Pester retained 19 passing and two failing tests. Anonymous extraction had
  erased the diagnostic context function's file provenance, making its
  changelog `Join-Path` fail before the managed host started. The repair imports
  the real definition-only support file, retaining both measurement assertions
  and adding context, row-count, sample-count and native-call-count checks.
- The diagnostics lane retained 61 passing and one failing test. Windows checkout
  changed the observed JSON fixture's sole LF to CRLF. This transformation exactly
  reproduces the observed failed digest. The repair preserves the original bytes
  through an explicit Git attribute; it does not change the fixture or expected
  SHA-256 assertion.

The production observations are retained, but accepted body retirement still
requires the repaired fresh full gate. The separate helper action candidate
remains unqualified and does not change these diagnostic results.
