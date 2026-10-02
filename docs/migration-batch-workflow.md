# Parallel migration batches and qualification

The user-approved target remains zero PowerShell source and execution, preserving
the existing public capabilities. The feature branch is
`migration/python-csharp-runtime`; a main-branch merge still needs approval.

The current integrated batch covers three independent families developed in parallel:

| Family | Existing PS source footprint | Boundary |
| --- | ---: | --- |
| Execution coordination | 69,774 bytes | Workflow, task/form runs, SmartClick, watch and recovery |
| Precision planning | 36,848 bytes | Coordinate anchors, point plans, target validation, cache/history |
| Legacy CDP | 72,323 bytes | Transport, page selection, DOM algorithms and legacy wrappers |

These 178,945 bytes include function regions and separators. They are a scope
inventory, not a promised net reduction. Bridge overhead is included when actual
retirement is measured. Original bodies were retained through qualification and
then replaced with the exact verified adapters; adding candidates alone did not
count as retirement.

Workers own separate new implementations, contract projects and fixtures. The
integrator owns shared interfaces, entry points, existing-script replacements,
packaging and publication. Stateful execution uses bounded individual effects
while accumulated report state stays in process. It must not resend an expanding
workflow transcript through a fixed-size bridge. Optional writes are prevalidated;
new transport/assembly failures must not appear after persistence.

## Fast feedback and the full gate

Migration-branch pushes run the focused workflow. Its first commit-title line can
select `[focus execution]`, `[focus precision]`, `[focus cdp]`, or
`[focus foundation]`. With no marker, all three family suites run in parallel.
Every focused run also executes the fast cross-platform Python contracts.
Unknown or contradictory focus markers fail rather than creating an empty pass.

The focused Windows jobs compile the native host, run the selected managed
contracts and its pinned differential fixtures. CDP additionally runs owned,
temporary-profile browser fixtures on Ubuntu with the sandbox enabled. Missing
requested test projects or suites fail explicitly. The adapter manifest
`.github/migration-adapters.json` chooses promoted production adapters. Before
promotion, the same jobs execute the exact adapters in real `.ps1` fixture files
alongside their candidate kernels. Missing drafts fail the job instead of silently
skipping this gate. The fixture bytes remain visible in the PS inventory; they are
removed when the same glue is promoted. Passing a draft gate is not proof that the
production dispatcher has already switched.

After integrating a verified batch, a commit beginning with `[full regression]`
runs the complete core, native, legacy, profile, browser and portable-package
suite, including every staged migration family. Focused jobs are not duplicated
in that mode. Normal pull requests and non-migration-branch pushes continue to
run the full suite. A focused green run never substitutes for this full gate. The existing Pester
boundary suite runs near the start of the broad Windows job so process-discovery
failures are visible while the independent differential suites continue.

Fix fixture or implementation failures using the affected focused suite, then
run one final full gate for the coherent integrated batch. Keep original output,
error, exit, query order, authority and uncertainty checks. Where formatting
limits deep output, compare the original unformatted object separately from its
exact public Console representation; do not discard either assertion.

Each family command saves its complete stdout/stderr bytes as a CI artifact.
Inline job output shows at most the final 64 KiB of each command so large exact
comparison failures cannot make the entire job log unreadable. A failed command
still fails the job; log capture does not alter or suppress test assertions.
Artifacts are retained for seven days, including on failure.
Windows artifacts also contain parser-derived function offsets and hashes for
the current scripts and exact adapter drafts. Those maps parse source without
executing it, normalize checkout line endings, and identify UTF-16 offsets.
Before using a range for retirement, verify its whole-file and function hashes
against the exact candidate, then convert the offsets to UTF-8 byte positions.

The first combined candidate, commit `120b64a605bece965da4637e6510afcbd46fe871`
(tree `fe6d3c2e2d6dd65b5351072fa20586549a330302`), is preserved in
[run 36997186053](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/36997186053).
Fast contracts passed; all three Windows family jobs and the browser job failed.
Those results are diagnostic evidence, not retirement approval. The candidate
and adapter repairs are qualified together before any original family is removed.

The next combined checkpoint, `a7bffa18b8325fe06f00459324c1f3631f2c896a`,
passed Windows CDP qualification and the fast contracts in
[run 37000162419](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/37000162419).
Execution/precision startup still failed because their UTF-8 input was decoded
through the inherited Windows console code page. Their replacement readers now
share one strict UTF-8 byte stream without changing console settings; malformed
bytes and other encodings remain rejected. The browser probes isolated native
`CSS.escape` as a guarded-evaluation blocker, so the candidate uses a pure
equivalent with a native browser oracle. These repairs were subsequently qualified with the combined adapters and kernels
at the checkpoint below; an intermediate repair alone did not authorize retirement.

After the full gate passes, verify the published commit/tree and every blob,
recompute actual PS bytes, and report only the accepted reduction. Interactive
Windows checks remain separately identified; captured effects and headless
browser fixtures do not prove desktop input, IME, focus or mixed-DPI behavior.

## Prior accepted checkpoint

Commit `27400c98ea9f460e243240be0f27d39e69ca348c`, tree
`73efdd9ae8f6702afafa91a81afaf12e7db955fc`, passed all five jobs in
[run 36973181910](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/36973181910).
All 217 blobs and modes matched the reviewed tree. The app-profile replacement
passed 523 candidate/actual-adapter cases, 12 wire cases, 34 kernel checks and 63
controller guards, plus the separate culture/quote/casing suite. It retires
13,320 PS bytes, bringing accepted all-source retirement to 91,864 bytes from the
1,013,478-byte baseline. The remaining 921,614 bytes are not a feature-completion
percentage. Main remains at `9ffa354b9904235835a7bc6eb78ed8d3d76317c8`.

## Accepted integration and source accounting

All focused jobs passed at `e9e015c6bc7b39d52999dccccf6bb4316a6c8dfe` in
[run 37007340738](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/37007340738).
The integrator verified parser-derived source hashes and all function extents
before copying the qualified adapters into production. The three duplicate
fixture scripts were removed, and the manifest now selects production sources.
The shared CDP host remains an ordinary counted PowerShell file.

The integration replaces 53 original function extents, retaining 42 compatible
delegates and removing 11 private helpers. Including adapter and test overhead,
accepted tracked PowerShell is 823,078 bytes: 98,536 fewer than the prior accepted
checkpoint and 190,400 fewer than the original baseline. The
[canonical source inventory](legacy-function-inventory.json) reproduces these
measurements. Exact checkpoint `56be343c786027d27fa3dcb71732157caffc8de0`
passed all 11 active jobs in [full run 37022764709](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/37022764709).
All 283 blob hashes/modes match tree `c0d15371b60ebf62be45bfa68b90282405f07273`;
main is unchanged. The three focused-only jobs were intentionally skipped.

The full gate also checks promoted central CDP routing, relocated test loaders,
portable packaging and a narrow intentional privacy correction. Legacy CDP
search exposed field values and source-only text; the corrected assets exclude
those signals before matching and output. Synthetic characterization is separate
from ordinary parity, and all four legacy plus one modern owned-browser privacy cases passed. The
existing side-effect guard and ordinary compatibility assertions remain intact.

## Next parallel scopes

| Family | Exact retained function bytes | Boundary |
| --- | ---: | --- |
| Interaction/target planners | 55,093 | Eight FindLabel/ClickPoint/ClickLabel/SafeType/icon/OCR-click/precision bodies |
| Diagnostic/report assembly | 54,053 | Nine performance, lag, health, logs, benchmark, self-test, audit and release-note bodies |
| File-image/OCR processing | 10,814 | Six diff/file-OCR/runtime/conversion helpers; no screen acquisition or input |

The 119,960-byte total uses verified Windows AST function extents at `56be343c`,
excluding inter-function comments. Bridge/test overhead and retained shared
helper dependencies affect eventual net retirement. Cleanup/termination,
registration, actual screen/IME/clipboard actions and authenticated providers
are outside these candidates' executed fixtures. Existing shared helpers remain
callable for unported families. Candidates reuse the same effect/codec/session
infrastructure with closed new descriptors; startup registration and effect
validation stay closed until integration. Qualify the independent families in
parallel, then run one bundled full gate for their coherent production cutover.

The initial `[focus next-batch]` checkpoint runs those three Windows families in
parallel plus fast contracts. Interaction and diagnostics are explicitly
candidate-only: the manifest rejects marking either as promoted until its exact
host adapter is added and that temporary stage is removed. The file-images gate
already requires its real adapter draft and both image-diff and file-OCR suites.
A candidate-only result is printed in logs and the CI summary and never qualifies
source retirement. Actual adapter work proceeds alongside these initial oracle
runs; the production cutover still requires its own bundled full regression.

The subsequent adapter checkpoint removes the two temporary candidate-only stage
declarations. It requires each exact adapter test module, each fixed draft, and
the matching NativeHost; missing files or host configuration cannot silently skip
the adapter gate. Both families run shared startup/session checks too. No new
family is marked promoted in the manifest until its original-body cutover.
Python child reports use explicit UTF-8; a bounded preview escapes characters an
older console cannot encode while the artifact preserves every original byte and
the child exit status. All three new families are qualified together before the
single full regression for retirement.

## Focused literal-tokenizer candidate feedback

The existing `[focus foundation]` lane retains its inventory, pure-kernel and
TaskForm checks and now also runs `PcuCp.LegacyWorkflow.ContractTests` plus the
complete `test_legacy_workflow_parity.py` Windows suite. Missing either Python
suite fails before any build. This makes the observed literal-token fixtures and
inferred non-relaxation probes part of actual candidate feedback, without
switching production callers or removing tests. The complete parser remains
unqualified while known gaps remain; `CUCP_REQUIRE_WORKFLOW_PARSER_PARITY=1` and
the final full production gate are still required before tokenizer retirement.
