# Python/C# migration milestone

This remains a partial migration toward zero PowerShell source and execution.
Work is on `migration/python-csharp-runtime`; main has not been merged or replaced.
The provider-neutral core exposes 52 MCP/JSONL tools through Python and C# without
PowerShell, Pi, or an authenticated model provider. The broader legacy surface
still uses compatibility hosts and unported PowerShell acquisitions/actions.

## Actual source replacement

The baseline is commit `9ffa354b9904235835a7bc6eb78ed8d3d76317c8`, tree
`bf895d3120dd5e145f360cb1c41e1d79a061d048`.

| Canonical Git source | Baseline | Prior verified `27400c98` | Current integration |
| --- | ---: | ---: | ---: |
| All tracked `.ps1` source/tests | 1,013,478 bytes | 921,614 bytes | 823,078 bytes |
| Runtime scripts, including the new shared host | 858,937 bytes | 770,805 bytes | 667,770 bytes |
| Actual all-source reduction | — | 91,864 bytes | **190,400 bytes (18.79%)** |

The current integration removes another **98,536 bytes** relative to the prior
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
three families. This integration requires the **current commit's bundled full
regression**, including promoted central routing, prior legacy suites and relocated
Windows packaging. The earlier focused result does not substitute for that gate.

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

The tracked inventory still contains 823,078 PowerShell bytes. Major remaining
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
Four legacy and one modern owned-browser privacy cases require the current full
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
