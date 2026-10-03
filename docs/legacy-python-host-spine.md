# Staged Python legacy host spine

## Status and exact claim

This is an opt-in proof checkpoint, not default activation, an installed legacy
launcher, a complete family cutover, or a PowerShell retirement. Existing legacy
entry points and every retained PowerShell source are unchanged. The modern
52-tool engine is not involved.

The separate frozen dispatch contract records the original **109 ordered
clauses / 108 unique names**, including the repeated returning `click-point`
clause, alias options, seven not-implemented entries and 41 direct-sensitive
macro names. Registry resolution is inert; it cannot execute a handler name or
grant authority. The complete registry does **not** imply all commands are
implemented by the staged host.

The executable checkpoint deliberately enables only:

- Four read-only CDP macros in brief mode: `cdp-detect`, `cdp-smart-find`,
  `cdp-smart-type-find`, `cdp-deep-find`, using the existing Python legacy CDP
  contracts, adapter, transport and audited read algorithms
- `release-notes` in brief mode, using the existing NativeHost diagnostic
  coordinator, startup validation, sequence-bound session and reducers; Python
  provides only the exact owned `ResolvePath` and `ReadLines` effects
- The seven existing `not_implemented <name>` brief responses with exit 1
- A typed child re-entry and the bounded typed subset of legacy daemon `serve`
  with its original ready/control envelopes and BEGIN/END sentinel ownership

Normal JSON formatting, daemon batch, top-level version/CLI/help, arbitrary JSON
argument coercion, unqualified macros and all live effects are refused before
provider acquisition. Refusal is a separate `unqualified_surface` diagnostic,
not a falsely advertised legacy `not_implemented` result. Startup live/sensitive
ceilings cannot expand this allowlist. There is no PowerShell bridge or fallback.

## Explicit entry

From a source checkout with its Python module path configured:

```text
python -m pcucp_cli.legacy_host_entry --staged-brief-host --brief -- macro release-notes
python -m pcucp_cli.legacy_host_entry --staged-brief-host --brief --cdp-endpoint http://127.0.0.1:9222 -- macro cdp-detect --port 9222
python -m pcucp_cli.legacy_host_entry --staged-brief-host --brief -- macro daemon serve --max-commands 2
```

`CUCP_NATIVE_HOST` selects an already-built matching executable/DLL for the
coordinator path through the existing native-host locator. Runtime execution
never builds, downloads, invokes a shell, or substitutes a fixture. This source
entry has not been added to the existing CLI or installer. Process flags before
`--` are trusted startup context; macro argv after it stays data.

`--typed-child` reads one bounded JSON object from stdin, then requires EOF:

```json
{"schema":"cucp.legacy-python-child/v1","argv":["macro","release-notes"],"live":false,"quiet":true,"brief":true,"confirm_sensitive":false}
```

This is the explicitly staged Python typed-child ABI, not a claim that the old
PowerShell child adapter has already switched. Child grants intersect the
immutable startup ceilings, cannot modify a source path or choose an executable,
and cannot interpret control-looking argv strings as parent flags. In-process
re-entry shares the same CDP adapter and one-second endpoint port cache. No
fresh PowerShell process is spawned per effect. Each C# coordinator invocation
retains its complete invocation state in its one owned process.

## Common session boundary

`legacy_host_protocol.py` and `legacy_host_session.py` implement the host half of
the existing three-family transport. The process entry determines the family.
A trusted provider must first validate the complete startup and then every
closed descriptor before dispatch. Only the release-notes provider is currently
installed. Other families have no acquisition/input provider in this checkpoint.

The host preserves:

- Strict UTF-8, exact fields and duplicate-key rejection; 48 KiB chunks,
  66,000-character frames, 32 MiB startup, explicit tagged arrays/objects/scalars
- No aggregate report cap or growing transcript replay; whole replies are
  serialized before their first frame, and effects are dispatched only after a
  complete matching end frame
- Monotonic exact integer sequence IDs, stable targets, immutable Boolean live
  and sensitive ceilings, fixed process entry, and no reply-supplied authority
- Family completion schemas, exits and depth metadata, plus exact process-exit
  agreement and rejection of data after completion before releasing output
- One single-attempt worker, existing native parent-liveness guard, owned-worker
  cancellation, bounded stderr, and deadline-aware protocol reads/writes
- Conservative owned-state/live outcome accounting mirroring the existing
  `LegacyExecutionEffectSemantics`; loss after possible dispatch retains
  `mutation_may_have_occurred=true`, `automatic_retry=false`
- Validation/transport failures remain terminal and never become ordinary
  provider failures. A failed coordinator poisons its owner, so queued daemon
  commands cannot implicitly restart it or replay the operation

The generic codec is foundational, not complete PowerShell object/JSON parity.
The current providers consume fixed string-keyed objects and primitive arrays.
Windows NLS property collision semantics, general JSON number/date/depth display,
interaction pipeline outputs, diagnostic counter-map rendering and exact
Console serialization remain qualification dependencies. No generic JSON
formatter is substituted for PowerShell output.

## Owned file and daemon limits

The release-notes context is copied from immutable startup. The only accepted
order is one configured-path resolution followed by one read of that returned
path. Other diagnostic kinds, alternate paths, changed authority, duplicate
queries, early completion or malformed output fail closed. The coordinator keeps
all version filtering, redaction and report assembly in its existing C# code.
BOM text follows the reached text boundary; Windows uses its actual ACP for
unmarked files. Portable proof uses only ASCII/BOM files and rejects an unmarked
non-ASCII file instead of pretending a Linux locale proves Windows behavior.
Only regular files are accepted. The provider records device/file identity at
resolution and validates the opened object before reading bytes; replacement,
symlink and FIFO changes fail closed. Reparse/network-filesystem semantics remain
unqualified.

Daemon `serve` owns one host, retains CDP session/cache state, serializes one
command at a time and preserves the ready/ping/shutdown and sentinel envelopes.
Only string argv arrays, scalar sentinel-safe IDs and single-assignment decimal
Int32 daemon option literals are currently accepted.
Unknown fields cannot supply authority; malformed IDs cannot inject sentinel
lines. Provider output containing the reserved `<<<CUCP-` token is quarantined
before stdout and poisons the owner; this restricted daemon ABI does not claim
parity for arbitrary sentinel-looking legacy output. `--idle-timeout-ms` remains informational like the retained implementation.
Broader legacy input coercion and batch file parsing are still explicit gates.

## Evidence and limits

Portable tests use disposable owned processes, temporary changelogs and a
loopback HTTP/WebSocket fixture. No user service, Startup registration, actual
browser/account, desktop input, or user file was used.

`PcuCp.LegacyHost.Qualification` links the actual managed startup/session,
coordinators, reducers and effect semantics. Its small entry accepts only
read-only brief release-notes. It is an explicit portable proof fixture, not the
Windows NativeHost executable or its WPF/provider environment. The Python
production entry was exercised end to end against that fixture. The real Windows
NativeHost route is enabled separately with `CUCP_LEGACY_HOST_TEST_NATIVE`.
The original PowerShell brief oracle is also a separate Windows-only gate and
retains its exact Git source from `bf895d3120dd5e145f360cb1c41e1d79a061d048`.

At the initial local run:

- 17 new protocol/security/owned-process tests passed
- 24 new entry/provider/typed-child/daemon tests: 22 passed, 2 gates skipped
- Existing legacy-CDP suite: 66 tests, 40 passed, 26 platform/browser gates skipped
- Existing execution Python suite: 43 tests, 22 passed, 21 Windows gates skipped
- Existing interaction Python suite: 24 tests, 14 passed, 10 Windows gates skipped
- Existing diagnostics Python suite: 59 tests, 49 passed, 10 Windows gates skipped
- Managed regression checks rebuilt and passed: 994 execution, 110 startup,
  106 interaction plus 67 boundary assertions, 191 diagnostic assertions
- Portable source-linked fixture rebuilt with zero warnings and errors
- Source entry succeeded with PowerShell/pwsh absent from PATH

The attempted OS process trace was **blocked**, not passed:
`strace: PTRACE_TRACEME: Operation not permitted`. The independent trace gate is
explicitly opt-in via `CUCP_LEGACY_HOST_TRACE=1`; it is not replaced by a mocked
subprocess trace. No ptrace workaround was attempted. Windows/net8 runtime,
actual original-caller comparisons, installed launcher, general output formatting
and full production trace qualification remain outstanding.

## Scope ledger and next coherent retirement route

The local source checkpoint is `8fafca8cc4b59d86a34ee6674aaea88b97009afb`,
with tree `5fb9191301f91e585efe40c8c86c0f74b296f92c` (locally verified). This local
commit is a provenance label, not assumed public ancestry. The frozen registry
reads checked-in bytes and never fetches that commit. Public CI must use the
reachable public commit
[`968379e6eca731ff849fd554339601261c291584`](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/commit/968379e6eca731ff849fd554339601261c291584),
whose same tree and all 657 blob/mode/path entries were independently verified
against this local checkpoint during publication qualification. Gross candidates remain:

- Shared execution host functions: **28,794** canonical Git bytes
- Complete interaction adapter: **18,399** bytes
- Complete diagnostic adapter: **30,058** bytes
- Distinct entry/discovery/Node/confirmation/daemon: **46,197** bytes
- Combined gross scope: **123,448** bytes, excluding 3,615 bytes of the 24
  already-delegated public macro bodies
- Separate direct-CDP adapter: **11,945** bytes, not added to the above sum

This checkpoint removes **zero PowerShell bytes**. New Python host, test fixture,
frozen contract and qualification glue add source and stay explicitly counted.
No 123 KB retirement is claimed.

At the reviewed implementation checkpoint, added executable Python source is
42,724 bytes across the four host modules, plus 9,644 bytes for the inert
registry module. The frozen registry JSON is 91,559 bytes; it stores hashes,
source locations and contract metadata, not executable PowerShell bodies.
The portable qualification entry is 1,762 C# bytes plus its 1,385-byte project
file. Tests and documentation are additional qualification source. These are
separate additions, not offsets against the gross PowerShell retirement scope.

The next coherent extension should complete the direct CDP host boundary:

1. Qualify exact legacy Console/JSON formatting and all ten existing CDP macro
   outputs against unchanged helper/wrapper oracles, including raw passthrough,
   depths, nullable arrays, Unicode, errors and exits.
2. Reuse managed arity-aware consent and safety classification before permitting
   live CDP macros; port the exact trajectory provider and post-dispatch failure
   output without retries or hidden logging fallbacks.
3. Route every direct/native-helper/typed-child/daemon CDP caller through the
   same trusted host and persistent endpoint cache, then qualify source and
   installed entry paths with PowerShell unavailable and real process tracing.
4. Only after those caller and Windows gates pass, switch that bounded production
   surface and retire its separately counted 11,945-byte adapter. Keep shared
   execution/interaction/diagnostic callers retained until their own providers
   and complete output contracts qualify.

A complete coordinator-family extension is also coherent, but must supply all
its closed effects and exact formatting together. Workflow parser/tokenizer,
history/trajectory, appshot and optional vision remain named dependencies.
Helper lifecycle/direct and geometry/UIA providers remain the responsibility of
their existing workstreams and must be consumed only when independently
qualified. No substitute reducer, arbitrary-script bridge, encoded legacy body,
per-effect PowerShell process, silent fallback, or replay is permitted.

### Owned CI plan to close the unverified gates

Use the repository's existing GitHub-hosted qualification runners, not a user
computer. Publication/CI dispatch is not part of this checkpoint.

- In the existing Linux `core.yml` / `migration-qualification.yml` qualification
  environment (Python 3.12, .NET 8), build
  `pcucp-next/dotnet/PcuCp.LegacyHost.Qualification` in Release, set
  `CUCP_LEGACY_HOST_TEST_PORTABLE` to that exact DLL and
  `CUCP_LEGACY_HOST_TRACE=1`, then run `test_legacy_host*.py`. Retain the test log,
  source commit, host SHA-256 and SDK/runtime versions. Run an additional owned
  changelog invocation under `strace -f -e trace=process -o <CI-artifact-path>`
  with PATH restricted to the known .NET directory. Its trace must contain only
  the Python root and one fixed .NET coordinator executable; no PowerShell, pwsh,
  shell or alternate launch is allowed. EPERM or any missing trace is a failed
  qualification gate, never an inferred success.
- In the existing Windows .NET 8 qualification environment, rebuild the exact
  `PcuCp.NativeHost` from the same commit and set
  `CUCP_LEGACY_HOST_TEST_NATIVE` to that published executable/DLL. Run the new
  host tests and the unchanged execution startup/transport/uncertainty/completion,
  interaction startup/adapters/parity and diagnostic startup/adapters/retained/
  parity suites and production-startup harness. This activates the separate
  original-PowerShell brief oracle test. All fixtures stay in owned temp roots;
  no real desktop input, user's helper service or Startup registration is used.
- Before any installed/default cutover, qualify that actual installed entry and
  its caller graph separately. An existing qualified Windows process-creation
  collector can supply the Windows launch trace; do not install a collector,
  elevate privileges or change security policy merely to make this gate pass.
  If the owned runner cannot collect it, leave that gate open.

Neither the local PATH restriction nor source-linked kernel fixture replaces
these production and process-level observations.

## Review record

The registry freeze was independently reviewed by the host implementer and
passed 21 source/contract tests before commit
`0a921f95e43cca6407da56216e9ed01489a89120`.

A separate reviewer inspected the host and independently reproduced/fixed-boundary
checked strict UTF-8 byte ingress, sentinel-output injection, regular-file
identity, cancellation while a CDP wire lock is held, and inherited-pipe cleanup.
Those findings were repaired with regression tests before freezing the host.
The reviewer independently reran the final 41-test host suite (39 passed,
2 explicit gates skipped), including the final daemon action-case/Int32
narrowing changes, and approved the bounded checkpoint with no remaining
review blockers.
This review approves only the stated staged read-only scope, not the unopened
Windows/formatting/installed-caller/OS-trace gates.
