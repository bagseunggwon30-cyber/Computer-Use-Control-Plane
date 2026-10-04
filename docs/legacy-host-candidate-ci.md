# Candidate-only legacy host CI

The `Legacy Python host candidate only` workflow qualifies the reviewed bounded
host checkpoint. It does not promote an adapter, alter an installed/default
launcher, enable another provider, or retire any PowerShell. Existing production
and full-family qualification workflows are unchanged.

## Triggers and explicit authority

The workflow supports manual dispatch and a narrowly path-filtered push on
`migration/python-csharp-runtime`, matching the existing candidate workflow
pattern. Its only token permission is `contents: read`. The Linux and Windows
jobs use GitHub-hosted disposable runners, fixed time budgets and explicit CLI
requirements:

```text
python pcucp-next/packaging/qualify_legacy_host_candidate.py --candidate-only --target linux --require-process-trace --log-dir .migration-logs/legacy-host-candidate/linux
python pcucp-next/packaging/qualify_legacy_host_candidate.py --candidate-only --target windows --require-windows-oracle --log-dir .migration-logs/legacy-host-candidate/windows
```

Missing flags, a mismatched OS, missing required tools, a dirty source tree,
reused evidence directory, skipped required tests or missing raw evidence fail
the gate. The runner never installs a tracer, elevates, changes ptrace settings,
relaxes security, changes computers or replaces a failed trace with inference.
It requires the standard preinstalled `/usr/bin/strace` on the Linux runner.
Missing strace or EPERM remains failed/unqualified evidence.

The workflow configures the standard Python 3.12 and .NET 8 toolchain. Host builds
are explicitly non-incremental; generated runtime configuration must bind the
.NET 8 framework family. Child processes use `DOTNET_ROLL_FORWARD=LatestPatch`,
so local .NET 10 roll-forward results cannot stand in for this CI qualification.

## Exact non-vacuous test inventory

`tests/fixtures/legacy-host-candidate/cases.json` pins every required test ID:

- 66 host/source tests: 21 original registry, 4 exact reviewed source-refresh,
  17 protocol/ownership and 24 production-entry/provider/daemon tests
- 36 orchestration/trace-parser tests: 9 CI/evidence checks and 27 synthetic
  parser/security checks; none may skip
- Windows additionally requires 20 unchanged startup/source/integer guards:
  execution startup, interaction and diagnostic production startup, the existing
  startup harness and the PS5.1/PS7 protocol-integer checks; none may skip

Linux expects 101 successful tests and exactly one named skip: the Windows-only
original brief comparison. Windows expects 120 successful tests and exactly two
named skips: the Linux strace test and POSIX inherited-pipe fixture. These are
platform partitions, not missing required gates. The Windows original brief
comparison must execute, and its four original PowerShell process outcomes must
be present and successful with four distinct expected outputs.

The existing original PowerShell script, four comparison vectors, invocation
arguments and assertions are unchanged. An opt-in test transport wrapper only
retains their raw bytes before assertions. It also preserves raw production
Python root/typed-child/daemon process results and expected negative exits.
Infrastructure timeout, incomplete drains and truncation cannot masquerade as
an expected negative application exit.

## Linux process-level proof

The Linux job builds the explicitly source-linked portable qualification host.
It then requires three independent real strace captures:

1. Direct Python root → C# release-notes coordinator → owned changelog → brief
2. Typed stdin child entry → the same fixed coordinator → owned file → brief
3. One-command daemon → the same fixed coordinator → owned file → sentinel output

Each trace uses `strace -f -q -e trace=process -s 4096`, without `-v` or environment
expansion. Exactly one `-q` suppresses attachment/personality diagnostics that
can interleave stderr; it preserves syscall and terminal exit evidence. `-qq`,
which would suppress required exit evidence, is not used. The child PATH contains only the known .NET directory; Python and
strace are invoked by absolute path. Each capture must have exactly two successful
execve events, their complete fixed argv, one owned root-to-coordinator process
creation and successful exits for every observed/attached tracee. Ordinary
runtime threads are accounted for. Extra/failed exec, execveat, shells,
PowerShell, CLONE_UNTRACED, unowned signal targets, missing/resumed-call gaps,
truncation, denied collection or unknown trace syntax fail qualification.

The validator parses C-escaped strings, including octal UTF-8, rather than looking
for command-name substrings. Its unit fixtures are explicitly synthetic. They
prove parser behavior, not that strace ran successfully on a hosted runner.
Actual hosted output must pass those strict checks without format fallback.

## Windows actual-runtime and source proof

The Windows job rebuilds the actual `PcuCp.NativeHost` and supplies that exact
DLL to the Python entry and original brief comparisons. It never substitutes
the portable fixture. Its owned original-vs-candidate file tests and all 20
existing startup safeguards must run.

`pcucp-next/packaging/source_map.py` uses the C# syntax worker and the Windows
read-only parser library to capture the real AST without executing any source
or starting a PowerShell process. Qualification explicitly builds the worker.
The CI runner verifies all six remaining frozen PS file
hashes and all 123 function extent hashes. The remaining four frozen line-range
extents are covered by the unchanged registry/source tests. This map is retained
with the raw process captures and the concrete checkout identity.

The source refresh is separately explained in `legacy-dispatch-refresh.md`:
only the previously reviewed Raw/Err scalar-copy delta changed production source.
Its exact before/after blobs and unchanged dispatch/safety invariant are required.
The `l5` correction affects inert metadata only.

## Evidence and failure retention

The runner requires a fresh directory under this checkout's ignored
`.migration-logs` tree. It records the concrete Git commit/tree, clean state,
Python/platform, SDK/runtime information, runtime-config and native DLL hashes,
frozen dispatch/case-manifest hashes, relevant source hashes and tracer identity.
Source cleanliness and host identity are checked again before success.

Every owned process uses the existing bounded raw-evidence collector. Outer
streams and raw trace stderr are bounded at 4 MiB per stream; inner root/oracle
captures are bounded at 2 MiB. Counts, exact bytes, base64 metadata, terminal
exit, timeout, drain and truncation state are validated. Data is retained before
assertions; overflow is a failure, not a truncated success. Raw process evidence
must include all three entry modes and at least ten actual Python entry runs.
Windows additionally requires exactly four original oracle processes/outputs.

Both jobs upload evidence on success or failure, with `if-no-files-found: error`
and seven-day retention. A failed qualification report cannot be relabeled by
a successful upload. Only a complete result receives `passed-candidate-only`.
That status still does not authorize default activation or retirement.

## Local status and remaining boundaries

No hosted run is claimed by this code change. The previously observed local
`PTRACE_TRACEME: Operation not permitted` remains a blocked, unverified process
trace; no local retry or security workaround was attempted. Portable tests and
capture wiring were exercised independently, including 18 bounded raw records
covering root, typed-child and daemon. Actual Windows/original-oracle and hosted
Linux traces remain pending until this concrete commit runs in the owned CI.

General legacy JSON formatting, live/sensitive CDP, trajectory/history providers,
other coordinator families, daemon batch and installed callers remain unopened
qualification boundaries. The next coherent extension is still the complete
10-command CDP caller/formatting/consent/trajectory boundary described in
`legacy-python-host-spine.md`; this CI stage does not silently expand that scope.

## Local implementation review

Independent review approved the candidate-only CI and narrow registry refresh.
The reviewer loaded and matched all 66/20/36 required test IDs, ran all 36
orchestration/parser tests and 25 registry/refresh tests, and confirmed that raw
capture wiring leaves the original oracle logic unchanged. The host implementer
independently reviewed the trace parser and reran its 27 synthetic tests.
Local combined portable checks passed 100 tests with two explicit platform/trace
skips; this is implementation evidence only. It is not a hosted trace, a Windows
runtime result, or permission to promote the candidate.
