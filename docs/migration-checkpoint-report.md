# Python/C# migration milestone

This remains a partial migration toward zero PowerShell source and execution.
Work is on `migration/python-csharp-runtime`; main has not been merged or replaced.
The provider-neutral core exposes 52 MCP/JSONL tools through Python and C# without
PowerShell, Pi, or an authenticated model provider. The broader legacy surface
still uses compatibility hosts and unported PowerShell acquisitions/actions.

## Latest qualified checkpoint

Commit `c414f0240a6a3fde78719f4ae44baddaf990e92b`, tree
`d4c9660d40c7e909f18afb166a8e846798f63b1d`, passed all 14 active jobs in
[full run 37072046282](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/37072046282)
on 2026-10-02 UTC. Three focused-only jobs were intentionally skipped because
that full gate ran. All 341 published blob hashes and modes match the reviewed
local tree. The gate includes Windows native/contracts, all six migration
families, profile, real-browser fixtures and relocated portable packaging.

The execution job passed 43 tests with zero skips, including 121 completion cases
and 259 strict integer cases under each of PS5.1 and PS7. Interaction passed 28
tests with zero skips, including all 870 actual-adapter comparisons and the
18-case ownership matrix under both shells. The original Windows boundary tests
also passed. These are automated noninteractive results, not live GUI, IME,
clipboard, focus-race, mixed-DPI or elevation acceptance.

At this qualified checkpoint, 26 tracked PowerShell files total **867,162 bytes**:
**612,709 runtime bytes** and **254,453 other source/test bytes**. All-source
reduction from the 1,013,478-byte baseline is **146,316 bytes (14.44%)**. Compared
with the older accepted `56be343c` milestone, runtime is 55,061 bytes lower, while
temporary fixtures make total PS 44,084 bytes higher. The older 190,400-byte
reduction is a dated milestone, not the current total. No files are hidden from
language accounting, and zero-PowerShell completion remains open.

### Literal-tokenizer candidate after the qualified checkpoint

The first candidate `48bb1651499d0857b4886b3f5cd8b2ed04d5e8a0` passed the three
active jobs in [focused run 37074340659](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/37074340659).
That Windows PS5.1 run confirmed six fixes, with 19 historical normalized gaps
still open, and found 100 differences in its 202 inferred probes (70 valid-input
rejections and 30 error-code differences). It established no newly accepted
invalid syntax within those cases, not full parser parity.

The next combined candidate covers embedded literal scanning, generic-token
boundaries and syntax-error precedence. Local replay now matches all 25 original
historical gaps and all 100 later observed results. At local source `fbba0fa`,
972 managed checks passed; Python discovery ran 531 tests, with 413 passing and
118 explicit platform skips. The 652 separately labelled inferred contracts
(388 literal, 213 boundary and 51 diagnostic) still require fresh Windows
comparison. Exact raw diagnostic text and plan-message equality are separately
captured and remain unqualified. Mode-sensitive or unknown syntax fails closed.
The focused foundation gate now requires every workflow test suite and retains
raw diagnostic evidence even if comparisons fail.

This candidate does not replace production callers or retire any PSParser code.
The NativeHost project still excludes it. Its explicitly tracked diagnostic
oracle adds 3,818 PowerShell bytes: the candidate index has 27 `.ps1` files,
870,980 total bytes (612,709 runtime and 258,271 other), a reduction of 142,498
bytes from baseline. Temporary oracle source remains counted and must later be
retired with equivalent provenance-backed coverage.

## Actual source replacement

The baseline is commit `9ffa354b9904235835a7bc6eb78ed8d3d76317c8`, tree
`bf895d3120dd5e145f360cb1c41e1d79a061d048`.

| Canonical Git source | Baseline | Prior verified `27400c98` | Accepted `56be343c` |
| --- | ---: | ---: | ---: |
| All tracked `.ps1` source/tests | 1,013,478 bytes | 921,614 bytes | 823,078 bytes |
| Runtime scripts, including the new shared host | 858,937 bytes | 770,805 bytes | 667,770 bytes |
| Actual all-source reduction | — | 91,864 bytes | **190,400 bytes (18.79%)** |

The accepted batch removes another **98,536 bytes** relative to the prior
verified checkpoint, including all adapter and test overhead. It replaces 53
original function extents: 42 retain compatible delegates and 11 private helpers
disappear. The duplicate adapter fixtures are removed; shared CDP host code is
counted once as PowerShell. No original algorithm is copied into a runtime archive,
renamed to hide its language, or excluded from statistics. Old source remains in
normal Git history.

These are source measurements, not a functional-completion percentage or GitHub
Linguist estimate. Run `python pcucp-next/packaging/check_migration_inventory.py`
to reproduce the current [inventory](legacy-function-inventory.json). Canonical
index blobs avoid checkout line-ending differences. Review and stage PS changes
before using `--update`.

## Historical integration before the full gate

The subsequent batch replaces 21 more original bodies: eight interaction macros,
seven diagnostic macros and six image/OCR helpers. Benchmark and audit-summary
retain their original bodies because unusual JSON conversion cases are not fully
matched. The exact source/adapter comparisons passed at `7fb6c2f6`; its one failed
job was a new clone-test setup error before assertions. That fixture is repaired
without removing assertions, and remains part of the required bundled full gate.

| Canonical Git source | Accepted `56be343c` | Published `7fb6c2f6` | Current integration |
| --- | ---: | ---: | ---: |
| All tracked `.ps1` source/tests | 823,078 | 930,801 | 849,829 |
| Runtime files under `scripts/` | 667,770 | 711,375 | 611,370 |
| Other PS source/tests | 155,308 | 219,426 | 238,459 |

The integration removes 80,972 net PS bytes relative to `7fb6c2f6`. Relative to
the prior fully accepted batch, runtime PS decreases by 56,400 bytes, while new
reference and startup fixtures add 83,151 other PS bytes. Therefore total PS is
currently **26,751 bytes higher** than that accepted milestone, despite genuine
runtime migration. These fixtures remain visible, counted PowerShell; they must
also be migrated or retired with equivalent regression coverage before zero is
reached. Current total reduction from the original baseline is 163,649 bytes.

New production-entry checks run a disposable copied main script with real module
loading and public dispatch. Hash-checked copied acquisition leaves stop before
any provider/native action, and only the final family entry is captured. The
original 21 Pester assertions remain unchanged. The integrated checkpoint needs
the complete Windows, browser, portable and regression gate; none of this is
interactive desktop, clipboard or IME acceptance.

## Historical integrated boundary repair

The initial integration tree (`031bff14` remotely, `2cc712d` locally) failed the
full run [37058066571](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/37058066571):
12 active jobs passed and two failed. Seven Pester boundary assertions rejected
valid PS7 completion integers, and the interaction argv-ownership fixture found
that casting a null argument array before cloning could produce a null receiver.
All 21 original Pester assertions remain unchanged.

The repair retains array ownership without that cast and accepts only Int32 or
Int64 protocol integers within the original Int32/domain bounds. It adds actual
PS5.1/PS7 completion and integer-guard matrices, including 25 malformed completion
cases after one acknowledged inert possible-write dispatch. These require the
same uncertainty marker, no automatic retry, and no premature output. Real
Windows results for this repaired tree remain pending until its full gate passes.

The first repaired index at `18807573` contains 26 tracked PowerShell files totaling **864,373 bytes**,
including **612,709 runtime bytes** and **251,664 other source/test bytes**. That
is 14,544 more than the initial integration, and 41,295 more than the last accepted
`56be343c` checkpoint. These temporary regression fixtures are fully counted;
they do not earn new accepted migration credit and must also be removed only
after equivalent zero-PowerShell coverage exists.

## Qualification and integration

All focused jobs passed at `e9e015c6bc7b39d52999dccccf6bb4316a6c8dfe` in
[run 37007340738](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/37007340738):

| Family | Evidence |
| --- | --- |
| Execution coordination | 370 managed checks, 56 startup checks, 35 Windows tests; both 462-case comparisons, including explicit uncertain-action cases |
| Precision/history/cache | 509 managed checks, 21 Windows tests without skips; 174 candidate and 174 actual-adapter cases, 138 helper cases, eight filesystem cases |
| Legacy CDP | 43 Windows tests; seven real-browser tests, including the 52-case native CSS escaping oracle and guarded-read tests |
| Shared contracts | Cross-platform Python suite and strict transport/authority checks |

Windows parser-derived function ranges and SHA-256 hashes were checked against
all six source/draft files before promotion. The integrated hosts copy the exact
qualified helper/delegate bodies and preserve bytes outside explicit replacement
and initialization regions. Production source selection is now enabled for all
three families. The integrated checkpoint `56be343c786027d27fa3dcb71732157caffc8de0`
passed all 11 active jobs in [full run 37022764709](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/37022764709);
three focused-only jobs were intentionally skipped because the complete gate ran.
All 283 published blob hashes and modes match tree
`c0d15371b60ebf62be45bfa68b90282405f07273`. The gate includes all production
adapters, prior Windows parity suites, Pester 21/21, relocated portable packaging,
modern Chrome 8/8 and legacy Chrome 11/11. Core passed 355 tests with 89 explicit
platform/browser skips; Windows CDP passed 55 with 11 browser-only skips.
Subsequent implementation batches require their own exact-commit full gate.

## What moved

Python owns MCP/JSONL transport, schema validation, core workflows, observations,
cancellation, installer/packaging logic and optional browser control. C# owns
Windows UIA/OCR/input/application primitives and the migrated compatibility logic.

Previously qualified replacements cover OCR matching with Windows NLS/UTF-16/tie
semantics; compiled Win32 interop declarations; safety classification; coordinate
math; workflow/task/form/preset/smart-plan assembly; app-profile assembly and its
sole-use strategy score helper; and the user installer. Their retained adapters
preserve acquisition, errors, formatting, explicit persistence and exit behavior.

The current batch adds:

- Workflow/task/form execution, SmartClick routing, watch and recovery coordination
  in C#, with closed typed effects and immutable startup authority
- Coordinate-anchor/point/target planning, history scoring and fixed-path cache/
  history storage in C#, including prevalidated persistence and exact legacy output
- Legacy CDP transport, page selection, DOM algorithms and wrapper construction in
  Python/JavaScript, with one retained PowerShell host bridge and typed live startup

Read-only browser evaluation keeps its side-effect guard; arbitrary evaluation
and mutations need startup live permission. Control-looking text remains data.
A failed read after possible mutation is terminal and cannot trigger retry or
fallback. UTF-8 protocol decoding is independent of the Windows console code page.
The large confirmation entry accepts only its existing pure confirmation operation;
other pure operations retain their smaller request limit.

## Remaining work and acceptance boundaries

The accepted checkpoint still contains 823,078 PowerShell bytes. Major remaining
work includes leaf UIA/OCR/window acquisition, IME/clipboard/drag/multi-edit,
application/process/registry/system macros, recorder/audit/profile acquisition,
helper lifecycle and IPC, optional vision/provider plumbing, the original workflow
tokenizer, installer/elevation shims, Pester/reference tests and CI oracle calls.
The image-diff candidate is separately qualified but not yet retired from its
legacy caller. Shared normalization helpers still have retained callers.

Compatibility parity is not a privacy or security proof. The CDP review found
legacy form values and source-only subtree text entering search results and logs.
The current integration intentionally removes those signals before matching,
locator construction and output, while preserving ordinary labels and current
visible button captions. Thirty-two original synthetic exposure cases and eleven additional textarea
scenarios characterize that divergence; ordinary parity assertions and the read side-effect guard remain.
Four legacy and one modern owned-browser privacy cases passed that full
gate. The modern observation path also excludes textarea defaults from direct
and ancestor text while keeping references, label matching and explicit typing.
This focused
correction does not establish privacy safety for every remaining legacy surface.

Hosted protocol and generated-data checks do not establish interactive Windows
acceptance. Outstanding checks include Korean IME composition, clipboard
restoration, focus/modal races, held-input cleanup, mixed-DPI/multi-monitor
coordinates, cross-integrity/UAC behavior, helper restart/crash handling and
application-specific success. No user desktop, personal documents or account-
connected model were used for these claims. An authorized isolated Windows fixture
environment is required for those acceptance cases.

Before the final zero-execution gate, replace temporary PowerShell oracle calls
with provenance-backed expected fixtures and independent Python/C# tests. Linking
the PowerShell SDK, retaining encoded bootstraps, or deleting unported operations
does not satisfy the target. See [the zero-PowerShell gates](zero-powershell-acceptance.md).

## Next bounded batch

The next independent scopes contain 119,960 bytes of exact current function
extents: interaction/target planners 55,093; diagnostics/report assembly 54,053;
file-image/OCR processing 10,814. These are scope measurements, not promised net
retirement. Shared OCR helpers keep their contracts for retained screen/fusion
callers. Candidate code reuses the qualified typed effects, startup authority and
chunked wire transport. Original bodies stay until candidate and actual-adapter
gates pass; temporary qualification scripts remain counted in the inventory.

The published `6fc7c882` candidate checkpoint adds 32,096 bytes of visible PowerShell oracle
and adapter fixtures, while leaving the accepted production bodies intact. Its
all-source total is 855,174 bytes (158,304 below baseline); the last accepted
production cutover remains the 190,400-byte net reduction at `56be343c`. No new
retirement is claimed from these candidates. Fixture overhead stays in the
inventory and must be replaced or removed at its appropriate qualification gate.

### Staged actual-adapter qualification

Focused run [37037485035](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/37037485035)
passed fast contracts but failed the three new family gates. All 110 image-diff
kernel/actual-adapter comparisons passed; two OCR fixture variable collisions
blocked the remaining intended observations. Diagnostic source decoding and
root-array nesting errors, six interaction compatibility causes, and a console
preview encoding error have staged repairs. No failed comparison was removed.

Interaction now requires the real NativeHost and shared PS host for all 870
ordinary cases (the original 854 plus 16 numeric boundary cases), 12 uncertainty
cases, and its forged-descriptor matrix. Diagnostics requires 321 complete cases,
196 guard/filesystem/getter checks, and its fixed actual acquisition adapter.
Both reuse the existing framed transport with closed family startup and immutable
ceilings. Owned-state accounting covers cache/log writes without granting live
input authority. Original production functions still remain in place.

The diagnostic guard's case generation and assertions were genuinely moved to
Python: its PS driver fell from 42,879 to 11,770 bytes, preserving all 196 checks.
This is a reduction of temporary new test scaffolding, not additional legacy
runtime retirement. Current staged tracked PS is **934,772 bytes**, or 78,706
below the original baseline, including every adapter and test fixture. The last
accepted production cutover remains `56be343c` with 823,078 bytes. These totals
must be measured again after actual adapters qualify and original bodies retire.

Local combined discovery passes 491 tests with 102 explicit platform/browser
skips. The staged shared session has 994 managed checks, startup has 110, and
interaction has 106 locally (109 on Windows). Windows actual-adapter checks are
still pending; local results do not establish those gates or interactive GUI
acceptance.

## Historical guard-fixture follow-up

Run [37066314234](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/37066314234)
passed the previously failing original Windows boundary stage, but its new guard
matrices found mismatched fixture wire containers, a custom-startup-reader gap,
PS5 null/PS7 typed-binding assumptions, and a real PS7 buffered-string replay
shape defect. The strict repairs retain all matrix cases and add raw CLR type
and wire-readiness checks. Their exact Windows gate is still pending.

This follow-up index contains **866,913 tracked PS bytes**, with the same runtime
source footprint as the first repair and 2,540 extra temporary test-fixture
bytes. No additional source retirement or zero-PowerShell completion is claimed.

The subsequent depth-zero fixture correction preserves the native PS5/PS7
renderer difference and actual non-JSON Silent completions. It retains the
original 118 cases and adds three, including post-write formatter refusal. This
and the explicit-null snapshot fix add 249 net temporary driver bytes, bringing
tracked PS to **867,162 bytes**; runtime
PS remains **612,709 bytes**. Exact Windows qualification is still pending.
