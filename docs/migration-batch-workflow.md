# Parallel migration batches and qualification

The user-approved target remains zero PowerShell source and execution, preserving
the existing public capabilities. The feature branch is
`migration/python-csharp-runtime`; a main-branch merge still needs approval.

The next implementation batch covers three independent families in parallel:

| Family | Existing PS source footprint | Boundary |
| --- | ---: | --- |
| Execution coordination | 69,774 bytes | Workflow, task/form runs, SmartClick, watch and recovery |
| Precision planning | 36,848 bytes | Coordinate anchors, point plans, target validation, cache/history |
| Legacy CDP | 72,323 bytes | Transport, page selection, DOM algorithms and legacy wrappers |

These 178,945 bytes include function regions and separators. They are a scope
inventory, not a promised net reduction. Bridge overhead is included when actual
retirement is measured. Existing PS bodies remain until replacement behavior is
qualified; adding candidate code alone does not count as retirement.

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
run the full suite. A focused green run never substitutes for this full gate.

Fix fixture or implementation failures using the affected focused suite, then
run one final full gate for the coherent integrated batch. Keep original output,
error, exit, query order, authority and uncertainty checks. Where formatting
limits deep output, compare the original unformatted object separately from its
exact public Console representation; do not discard either assertion.

After the full gate passes, verify the published commit/tree and every blob,
recompute actual PS bytes, and report only the accepted reduction. Interactive
Windows checks remain separately identified; captured effects and headless
browser fixtures do not prove desktop input, IME, focus or mixed-DPI behavior.

## Last accepted checkpoint

Commit `27400c98ea9f460e243240be0f27d39e69ca348c`, tree
`73efdd9ae8f6702afafa91a81afaf12e7db955fc`, passed all five jobs in
[run 36973181910](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/36973181910).
All 217 blobs and modes matched the reviewed tree. The app-profile replacement
passed 523 candidate/actual-adapter cases, 12 wire cases, 34 kernel checks and 63
controller guards, plus the separate culture/quote/casing suite. It retires
13,320 PS bytes, bringing accepted all-source retirement to 91,864 bytes from the
1,013,478-byte baseline. The remaining 921,614 bytes are not a feature-completion
percentage. Main remains at `9ffa354b9904235835a7bc6eb78ed8d3d76317c8`.

## Current candidate source accounting

The three exact adapter fixtures are executable PowerShell files, counted normally
in the inventory. With original bodies retained, the candidate currently contains
982,825 PS bytes, 61,211 more than the last accepted checkpoint. This temporary
overlap is qualification code, not retirement. After the combined adapter/kernel
Windows gate, promote the same glue, remove verified original bodies and duplicate
fixtures, then measure the resulting blobs and run the full regression gate.
