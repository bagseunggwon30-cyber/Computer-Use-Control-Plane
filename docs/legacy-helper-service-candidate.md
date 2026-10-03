# Detached legacy helper candidate (not promoted)

This is a Python/C# replacement candidate. The later [conditional production
stage](legacy-helper-production-staging.md) adds opt-in concrete adapters and
wrapper delegates; the default route and all original PowerShell bodies remain.
No autostart registration, user computer or modern `NativeSession` is changed.
**Retirement credit: zero.** A passing portable contract test is not
Windows runtime qualification or permission to switch callers.

## Published provenance and measured scope

The oracle source is the published commit
[`3e892ab02395bdc916a5814e39d4154efd1f6249`](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/commit/3e892ab02395bdc916a5814e39d4154efd1f6249),
whose verified Git tree is `e36329b2a6b07539faacd070d661bc0e3819140d`.
Extraction uses `git show <published-tree>:<path>`, not a local-only commit.
`tests/fixtures/legacy-helper/source-manifest.json` records the canonical Git
blob identity, raw SHA-256 and byte count, LF/no-BOM normalized SHA-256, and
Windows-parser UTF-16 extent offsets/hashes. UTF-16 offsets are converted before
measuring UTF-8 bytes, including non-ASCII comments. No executable body is copied
into the manifest.

The exact gross family is 35,505 PowerShell bytes:

- Complete `scripts/cucp-helper-server.ps1`: 27,427
- `_Read-LockSafely`: 411
- `_Is-StaleLock`: 1,267
- `_Try-Delete-Lock`: 468
- `Get-HelperServerStatus`: 1,156
- `Invoke-HelperPipe`: 2,138
- `Start-HelperServer`: 1,657
- `Stop-HelperServer`: 981

`Invoke-NativeHelper` is additionally pinned for supporting route contracts; its
10,518 bytes are not added to that gross family. The nested `_AsyncWait` extent
is verified but never double-counted. The two new oracle drivers are ordinary,
fully counted `.ps1` files. Historical tests and negative guards are retained.
No source retirement is earned by adding these candidates or their fixtures.
The two new drivers add 13,777 tracked bytes (5,796 action oracle + 7,981 client
oracle): total tracked PowerShell increases from 870,201 to 883,978 bytes.
The inventory still counts every `.ps1` by canonical index blob bytes.

## Architecture

`PcuCp.LegacyHelper` is an independent, detached .NET Framework 4.8 executable.
Framework targeting retains the original Framework/WinRT and UIAutomation
boundary rather than substituting modern NativeHost schemas. C#7.3 action logic
is also linked into a .NET8 portable contract executable. The existing compiled
`PcuCp.LegacyInterop/HelperWin32` supplies the original ABI; no PowerShell is
embedded in C#, Python, or metadata.

The only dispatcher actions are `windows`, `health`, `focused`, `modal-detect`,
`ocr-screen-fast`, `uia-find-fast`, and lifecycle `shutdown`. Unknown action
strings produce the legacy fallback result. There is no generic macro, input,
shell, executable, HTTP, or network-listener dispatcher.

The action reducer has explicit provider and clock seams. Synthetic fixtures
require every provider call, its order and arguments, and every clock read;
missing, reordered, or unused captures are fatal harness errors, never normal
`status=error` action results. The real provider is selected only by the explicit
`--allow-readonly-desktop` flag. Tests never use that flag. Its interactive and
capture behavior remains unqualified.

The opt-in Python client accepts a lock store, a read-only process-existence
probe, a clock, a pipe transport, and an explicit fixed-service detached launcher.
There is intentionally no default discovery, subprocess command resolver,
installer, or production adapter. The lock store's conditional deletion contract
requires atomic identity/bytes comparison; an adapter that cannot guarantee it
must preserve the lock. Fixture process cleanup only uses retained handles from
newly launched fixture processes.

This service is shared by successive wrapper invocations. It must not use a
parent-death guard or the modern stdio session's ownership model.

## Preserved contracts under test

- Windows filtering is title-only, with numeric HWND/PID, `rect.w/h`, and a
  separate top-level foreground. One-shot title-or-process filtering and modern
  string handles are not substitutes.
- Health counts every dispatched request, including health, unsupported, and
  shutdown. Its integer seconds use midpoint-to-even rounding.
- Focused and modal responses keep their own legacy schemas and scoring.
- OCR defaults are truthiness-based `0,0,800,600`; zero dimensions select the
  default. Successful engine initialization is cached; failed initialization is
  retried. The otherwise-unused primary-screen/virtual-width query order remains.
- UIA selects the first matching root child or the root, scans at most 800
  elements, accepts at most 16 matches before sorting, and uses legacy scores.
- Wrapper routing tries the pipe before the hot cache; `ForceChild` and any
  nonempty force environment string skip the pipe. Code 99 falls back, while
  error 1 and partial 2 return the pipe response. Only the original four actions
  use the 500 ms hot cache.
- Wrapper routing forwards only `Match`, `TargetMatch`, and `TargetHwnd`.
  It still omits `Label/X/Y/W/H`; direct client/pipe tests separately cover those
  fields. This omission is not silently repaired.
- The pipe is `cucp-helper-<actual service PID>`; the concrete exchange client
  addresses only `.`. No TCP/HTTP listener is added. Framing is UTF-8 newline
  JSON with `id/action/args` and `id/exit_code/result/error`. One connection may
  contain multiple requests. A blank line closes the connection. Malformed JSON
  does not increment request count. The server ignores `timeout_ms`, as before.
- Idle expiry is checked while waiting for a connection, not while blocked in a
  connected `ReadLine`. A successful service is not terminated when its launching
  wrapper completes. Startup waits three seconds for the newly launched PID.
- An unacknowledged shutdown never kills a PID from a lock, including with Force.

## Explicit compatibility decisions, pending production review

These are proposed safety/robustness changes, not proven parity. None may be
silently included in a later retirement claim. User-visible consequences must be
reviewed before production cutover.

| Boundary | Original behavior | Candidate behavior and consequence | Independent guard |
| --- | --- | --- | --- |
| Candidate launch surface | Original script accepts custom `PipeName`, optional default lock path, debug-log switch and signed integer idle timeout | Candidate requires explicit isolated lock path, fixes pipe name to its PID, rejects negative timeouts, logs failures to stderr, and requires explicit desktop-provider opt-in; these launcher options are not a drop-in replacement | closed CLI parsing and owned fixture setup; production launcher remains untouched |
| Framework connection wait | Original creates a synchronous pipe, then invokes `BeginWaitForConnection`; Framework requires an async handle for that API | Candidate uses `PipeOptions.Asynchronous` and task-owned `WaitForConnectionAsync` cancellation, observes cancellation without closing its completion event, and does not retry unexpected setup/logic exceptions | owned service health/idle tests; unmodified original startup remains a separate mandatory observation |
| First response timing | Original and initial candidate enable `StreamWriter.AutoFlush` before reading any request, which synchronously writes a UTF-8 BOM | Candidate reads a complete nonblank request before writing the same BOM plus response and CRLF; blank/disconnected clients receive no unsolicited BOM. Response bytes and request counting stay unchanged. This is an explicit timing/blank-connection correction, pending Windows qualification | portable no-write-before-request and exact two-response byte checks; owned eager/deferred handshake controls and actual service phases |
| Pipe access policy | Original intends current-user-only access but creates a default-DACL pipe and attempts a setter without WRITE_DAC; setter errors continue fail-soft | Isolated ACL candidate supplies a protected current-user-only DACL at creation and verifies Framework-normalized readback before waiting for clients; any failure closes the owned pipe and terminates. Other principals lose accidental default read grants; unsupported security setups lose persistent service availability | owned descriptor/readback and same-user service tests; see [ACL candidate contract](legacy-helper-pipe-acl-candidate.md) for unqualified cross-user/session/elevation/SMB limits |
| Server startup lock | `Set-Content` overwrites the path, with write errors logged fail-soft | `CreateNew` requires an absent explicit candidate lock; existing or unwritable locks stop startup | `test_existing_lock_is_never_overwritten` |
| Server cleanup | Read matching PID, then delete pathname; a replacement can race | Check original file identity, exact bounded byte length and all originally written bytes (including UTF-8 BOM) under a write/delete-exclusive native handle, then delete that handle; replacement, BOM removal and encoding rewrites remain | `test_replacement_lock_survives_cleanup_even_if_pid_reused_in_content` and same-file BOM/encoding rewrite tests |
| Client pipe contact | `Invoke-HelperPipe` re-reads only lock existence/name, relying on callers | Revalidate owner/PID/time/name/version and expected lock identity before contact; a changed lock rejects the request | client framing/replacement and foreign-owner tests |
| Client lock cleanup | Owner-only pathname deletion, including some malformed/ownerless files | Atomic identity/bytes CAS required; foreign/malformed/unreadable/unremovable locks are preserved and can block startup | client malformed, foreign, stale-CAS and timeout tests |
| Startup timeout cleanup | Kill retained launched process, then path-based lock cleanup | Kill retained launch handle only; leave any lock not proven to belong to it | client startup-timeout replacement test |
| Client JSON framing | PowerShell conversion/coercion and permissive IDs/types | 1 MiB frames, unique JSON members, finite values (including exponent-overflow rejection at every nesting depth), integer correlated IDs/exit codes, positive timeouts; incompatible inputs fail closed | client bounds, framing, ID and duplicate-member tests |
| Request ID allocation | Original increments after a successful connect, without an explicit 32-bit reset | Candidate allocates before the combined transport exchange and wraps to 1 after Int32 max; a failed connect can therefore consume an ID | client failed-frame/connection and rollover contract |
| Concrete C# exchange I/O | Original client uses synchronous `WriteLine` and unbounded `ReadLine`, with a timeout only around the read task | Candidate checks a 1 MiB UTF-8 byte bound before connecting, incrementally bounds incoming bytes, and applies one absolute budget to write plus read after bounded connect; it closes only that connection on timeout and never retries | portable async-stream contracts and owned oversized/stalled/slow-drip Windows peers |
| Exchange client wire encoding | Original StreamReader detects BOM encodings and can replace malformed bytes; writer emits a UTF-8 BOM | Candidate exchange client sends UTF-8 without BOM plus LF, accepts optional UTF-8 BOM and CR/LF/CRLF or EOF, rejects malformed UTF-8/other encodings, and bounds the first response line including space for its terminator. Service responses retain their BOM and CRLF | split multibyte/BOM, exact-byte boundary, EOF and malformed-encoding tests |
| Server JSON parsing | PowerShell member access/coercion for some non-object values | Require object envelope and object-or-null args; Framework serializer diagnostics differ; 16 MiB JSON parser limit | direct invalid-envelope test |
| Lock types/dates | PowerShell casts, culture-dependent `DateTime.Parse`, regex `\d` | Integer positive PID, explicit-offset ISO date, ASCII version digits; some formerly accepted locks are rejected | client strict PID/date/version tests |
| Action replay | Existing wrapper can eventually dispatch arbitrary child actions | Candidate router executes only six read acquisitions; lifecycle shutdown is never replayed and unknown/mutation actions are rejected | client closed-action and no-replay tests |
| OCR resources | Original does not explicitly dispose decoded WinRT resources before deleting temp PNG | Dispose owned bitmap/stream before deletion; resource behavior is changed and real WinRT qualification remains open | provider code review; synthetic remove ordering only |

Static Framework UIA/Forms references may bind assemblies earlier than the
original PowerShell `Add-Type` calls. Preserved provider query order alone does
not qualify that loader timing.

Other unresolved compatibility limits include PowerShell nested-object/string and
numeric coercions, Framework exception wording, stable ordering of large score
ties, Python casefold versus .NET comparison on non-ASCII, raw JSON escaping/key
order/depth, and permissive status-counter casts. They are not waived by ordinary
shape equality. Large modal ties, multiple cultures, Unicode, arrays, truthiness,
retries and caps are represented in the candidate/oracle corpus. Most provider
failure branches are currently independent C# contracts; only the documented
loader-failure branches have original-function differential cases.

The original owner username, PID and pipe-name checks are not cryptographic
identity. The original ACL attempt is fail-soft, and that path was observed on
the first Windows run. The separate [ACL candidate](legacy-helper-pipe-acl-candidate.md)
now stages creation-time owner-only security with fail-closed readback. Neither
implementation is claimed to be
fully authenticated or safe against all same-user impersonation/PID reuse, nor
is the ACL attempt claimed to reject every possible remote SMB pipe access. A
broader authenticated-IPC redesign is a separate reviewed change.

## Qualification and evidence

Portable gate:

```text
python pcucp-next/packaging/qualify_legacy_helper.py --log-dir .migration-logs/helper-candidate
```

Required Windows gate, on an isolated authorized fixture machine:

```text
python pcucp-next/packaging/qualify_legacy_helper.py --windows --log-dir .migration-logs/helper-candidate
```

The dedicated workflow runs both. For integration, the known commit marker
`[focus foundation]` selects the existing full foundation checks; this separate
helper workflow is selected by narrowly scoped changed paths. Do not use an
unknown `[focus helper-*]` marker. Unrelated history/other-family pushes do not
match the helper paths, and the existing `history-candidate` and
`[full regression]` choices remain untouched. Manual helper `workflow_dispatch`
is an explicit alternative. It does not mark this family promoted in the
existing migration-adapter manifest and does not replace historical/full gates.
The Windows gate compiles net48 service/probes, executes actual candidate adapter
routes and owned pipe/lock/process fixtures, and compares hash-verified original
functions through explicit acquisition facades. Facades assert that every
resolved UIA/Drawing/WinRT type belongs to the inert fixture assembly before
executing any action. They cannot silently touch the desktop.

Action-oracle normalization is limited to health's actual process PID and wall
clock uptime; deterministic clock/rounding tests are separate. Original loader
functions are verified but replaced by explicit acquisition seams, so this is not
proof of real assembly-load or WinRT initialization equivalence. Positive OCR
oracle data is synthetic; no real screenshot or OCR engine is used. Full
unmodified original server startup/health/shutdown has its own Windows test;
function-extracted oracle success does not qualify startup. The original startup result is retained as a failed, unqualified oracle
observation. Only the precisely recorded baseline defect below has a separate
classification; it is never an expected action rejection.

Every subprocess fixture saves bounded raw stdout and stderr, exit code,
timeout, launch error, truncation, and incomplete-drain evidence before parsing
or asserting its output. Prefixes survive even when descendants keep inherited
pipes open. Running service snapshots are retained before probe assertions;
terminal records follow cleanup. Only owned retained process handles can be
terminated. Launch/timeout/truncation/incomplete-drain failures cannot satisfy a
negative expected action result. CI uploads raw evidence even on failure.

Initial local reviewed evidence (2026-10-03, before transport review fixes): 117 C# action checks passed; the focused
Python suite passed 45 checks with 14 Windows-only checks unrun, plus all five
bounded-evidence regression tests. Full Python discovery passed 631 tests with
138 platform/opt-in skips (493 executed). Net48 host/provider/transport and inert
C#5 facade builds passed without warnings. `git diff --check`, Python compilation,
and exact source inventory verification passed. Linux had SDK 10.0.401/runtime
10.0.12; net8-targeted contract executables ran with `DOTNET_ROLL_FORWARD=Major`.
That is not evidence of actual .NET8 or Framework execution. The workflow installs
SDK8 and still needs to run on Windows. Raw local evidence is generated under
`.migration-logs/helper-candidate/`, with terminal results in `reviewed/` and
`reviewed-portable/`; it is not committed as hidden source.

Local Linux verification can establish builds and portable contracts only.
Windows named pipes, ACLs, unmodified original startup, and PS5 differential
execution require the Windows gate. Interactive UIA, generated-file real OCR,
real capture, focus/input/IME/clipboard, mixed DPI, elevation and account/session
boundaries remain explicitly unqualified. No production cutover or retirement
may rely on the current synthetic suite alone.

Autostart and version discovery still read the existing PowerShell launcher and
header. The historical inline/encoded drivers in `test_legacy_interop.py` remain
an independent final-zero dependency. The final zero-source/zero-execution gate
must eliminate those dependencies and these newly counted oracle drivers after
reviewable expected fixtures and real qualification exist.

## Follow-up independent review fixes

The original published source pins and both PowerShell oracle drivers are
unchanged. The candidate now writes and retains one bounded exact byte array for
its lock, and cleanup compares that array before decoding. Same-file BOM removal
or UTF-16 rewriting cannot pass a decoded-text-equivalence check anymore.

The concrete exchange has no StreamWriter or unbounded ReadLineAsync. It uses
async byte I/O with one absolute connected write/read deadline. Its request-file
reader checks length and reads at most 1 MiB plus BOM/detection bytes before
allocating the request string. A peer that stalls writes, stalls reads, slowly
streams bytes, exceeds the frame limit, splits UTF-8 characters, or disconnects
without a terminator has independent portable and owned-Windows fixtures. There
is still no added idle deadline on the service's connected legacy ReadLine loop;
this correction applies to the explicit client adapter, not a silent service
protocol redesign.

The Framework service wait now uses an asynchronous pipe and task-owned
cancellation. No manual AsyncWaitHandle is closed while a completion callback can
signal it. IOException retries check the idle deadline and back off; unexpected
setup/logic failures terminate with retained evidence rather than spinning.
The unmodified original startup observation stays mandatory, with raw failure
status preserved. Unittest continues collecting independent cases after any
unexpected observation failure.

A separate review regression rejects JSON floating-point exponent overflow such
as nested `1e309` before the router attempts strict JSON serialization. This is
part of the explicit finite-JSON candidate correction, not an original-parser
parity claim.

After these fixes, the portable gate passes 117 action checks plus 36 new wire
checks, 47 focused Python helper tests and five raw-evidence tests. Nineteen
Windows-only helper tests remain unrun on Linux. The net48 service/probe build is
clean. These numbers do not imply Framework runtime, pipe or original-startup
qualification. No PowerShell source bytes were added or retired by the repair.

## Integration with the current migration candidates

The reviewed helper commits `5a14e6b` and `c448f9d` integrate after the parser,
diagnostic repair and history null-capture changes. Only the byte-count fields
and acceptance-document placement conflicted; existing retirement metadata and
the complete history/inline-source acceptance notes were preserved. Source
counts were recomputed from staged canonical blobs, not copied from the older
helper base. The integrated tree contains 896,443 counted PowerShell bytes in
30 files: 610,258 runtime and 286,185 other bytes. The 13,777 helper oracle bytes
are a temporary qualification cost, with zero runtime retirement credit.

The batch also fixes the Windows CP1252 failure in the separate history
source-isolation test using explicit strict UTF-8 reads. Its assertions, fixture
bytes, six-run requirement and transport remain unchanged. The integrated full
Python run has 700 tests: 555 passed and 145 explicit gated skips. The shared
qualification workflow remains unchanged; a recognized `[focus history-candidate]`
marker selects the history Windows gate, while this helper's changed paths
independently select its dedicated Linux/Windows workflow. This is an intentional
parallel qualification batch, not an unknown focused-family name or a bypass of
foundation/full regression. All relevant current production sources remain.

## First Windows observation and bounded repair

The first Windows run was GitHub Actions
[37096050336](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/37096050336),
at published commit `df200f07`. Ubuntu passed. Windows executed 66 test methods
and reported 30 failed assertions: 18 action-oracle cases stopped before
execution at the `Windows.Storage.StorageFile` assembly guard, 11 candidate
service probes timed out, and one unmodified original startup failed before
publishing a lock. The downloaded 510-file evidence archive has SHA-256
`984be0a34f835404c8a045d4c13b756cb0260a893b5b80419a5694c0a569d965`.
These are failed or blocked coverage, not passed action parity.

The original startup evidence `startup-failure-d1f9dc5b0fcb.json` records exit 1,
no timeout, zero stdout, complete 499-byte stderr, and no matching lock.
The stderr SHA-256 is
`e1de6715702675a2c502e1341d79d97c09b0a7db02f0e58d93f066d99e8978cb`.
It reports `CommandNotFoundException` for the command `try`. The pinned source
uses a parenthesized `try` statement for `owner_sid` at line 534, before writing
the lock. This is now an observed baseline startup defect; it does not establish
any later original pipe-loop behavior. The original bytes, source pin and
unmodified launch observation remain separate from synthetic action evidence.

The oracle guard correctly failed closed. The old diagnostic does not identify
whether `StorageFile` resolved to another assembly or did not resolve; no real
WinRT operation was invoked to investigate it. The repaired fixture uses the
unique `CucpFixture` namespace. After verifying the unchanged whole-source hash
and every original function extent/hash, it substitutes exactly 52 type-name
AST sites across eight functions, covering 23 inert types. It verifies every
resolved type against the emitted, source-hash-pinned fixture assembly before
importing any action. Native loader functions are verified but not imported.
Every non-type code unit is preserved. Per-site extents and original/substituted
function hashes are emitted and independently checked before output/query-order
parity. This explicitly bounded acquisition seam does not qualify native type
loading, real UIA or real OCR.

The service stall cause is not yet proven by the first run: its logs show the
legacy fail-soft ACL warning and a broken pipe after the probe was terminated;
the scripted provider consumed no captures. Framework `StreamWriter.AutoFlush`
synchronously emits its encoding preamble before user text. `PipeStream.Flush`
is a no-op, and requested pipe buffer sizes are advisory, so neither a
FlushFileBuffers wait nor a literal zero-byte kernel buffer is claimed.
The [Framework StreamWriter source](https://github.com/microsoft/referencesource/blob/main/mscorlib/system/io/streamwriter.cs)
and [Windows pipe buffer documentation](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-createnamedpipea#remarks)
support those distinctions. The repaired service defers its original BOM until a request has been read.
Owned counterfactual handshake fixtures record actual buffers and operation
phases on Windows to test the suspected pre-read write stall.

Opt-in `--diagnostic-phases` emits at most 128 fixed operation markers plus one
limit marker to stderr. It records no request content. Service, probe and actual
exchange evidence can now locate connection/read/write/cleanup stalls; failed
probes snapshot the server before asserting. Actual-adapter fixtures explicitly
request a 1.5-second inner I/O budget within the existing process budget, rather
than letting a 30-second inner budget outlive a 10-second process envelope.
No production timeout or caller has changed. Portable checks include exact
response BOM/CRLF, multiple responses, failed-write no replay, no unsolicited
initial bytes, and the diagnostic event cap. New Windows observations are still
required before calling the IPC repair or action parity qualified.

The explicit type seam and its refusal path add 6,547 temporary, fully counted
PowerShell test-driver bytes: the action oracle is now 12,343 bytes and both
helper oracle drivers total 20,324 bytes. Canonical tracked PowerShell is 902,990
bytes across 30 files, with 610,258 runtime bytes unchanged. This repair earns
zero retirement credit; executable fixture behavior is not moved into Python,
C# strings or metadata to reduce the count.

The reviewed functional criterion separately classifies only this pinned
original startup crash as `baseline-startup-defect`. Its raw oracle status stays
`failed` and `original_startup_qualified` stays false in a retained classification
artifact. The exact first-run stderr is committed as a 499-byte binary fixture.
A new unmodified launch must exit 1 with the same complete diagnostic for
`CommandNotFoundException` / `try`, identify the same owned source file, preserve
both published source hashes, and leave no owned process or lock. Only path and
formatting whitespace vary; any other text, stdout, side effect, source change,
process timeout, truncation, byte-count mismatch or incomplete drain fails.
Portable negative tests independently exercise those exclusions.

This is an intentional user-visible compatibility correction: the candidate
makes the documented service reachable where the original aborts before
publishing its lock. Reproducing that abort is not the functional release goal.
Candidate positive startup, health, unsupported action, request counts, multiple
clients, detached lifetime, shutdown and cleanup remain mandatory. The original
ACL warning remains visible and no authenticated-IPC claim is added. Deadline,
owner and lock protections remain the separately reviewed compatibility
decisions above. This classification grants no production cutover or retirement.

Local repair verification (Linux, SDK 10.0.401/runtime 10.0.12 with Major
roll-forward): 117 action and 45 wire contracts, 52 helper Python checks, five
raw-evidence checks, and the full 707-test Python run passed (560 executed,
147 platform/opt-in skips). The helper-only suite has 21 unrun Windows methods.
Net48 service/transport and inert C#5 facade builds passed with zero warnings.
Canonical inventory and diff checks passed. These results do not substitute for
a new Windows run; neither the repaired oracle execution nor the IPC diagnosis
has been observed on Windows yet.

## Second Windows observation and PowerShell 5.1 extent ordering

Windows run
[37099034933](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/37099034933)
at public commit `049eb924bd3ec1323c52e857f5c9a0c80a12b48d`
(tree `240c09fbb416bf13d016bde93bdc5cf027c0c041`) ran 73 helper test
methods. All 18 transport methods passed, including the separately classified
unmodified original startup defect. Nineteen assertions remained failed: the
wrong-type-binding refusal check and all 18 synthetic action cases stopped
before dispatch at `Overlapping or changed oracle type extent`. The retained
748-file archive has SHA-256
`5cedae15744e7dfc00929b2b0f63e19442999931aae83e34ca148987d27b8947`.
These failures do not qualify any original action behavior or the type-binding
guard's later refusal path. They also do not waive the separate real-provider,
ACL/security or production-cutover limits.

The edit plan consists of hashtables. Its named-property sort incorrectly
assumed that `Sort-Object -Property start` could sort hashtable keys on Windows
PowerShell 5.1. That support begins in PowerShell 6. The
[PowerShell 5.1 Sort-Object documentation](https://learn.microsoft.com/en-gb/powershell/module/Microsoft.PowerShell.Utility/Sort-Object?view=powershell-5.1)
specifies calculated properties for this input. The repair uses an explicit
integer dictionary lookup, sorted descending, so insertions at higher UTF-16
offsets cannot shift any remaining lower-offset extent. The original overlap
and exact-text checks remain mandatory; duplicate edits are never discarded.
The old evidence did not retain the failed site's order or establish duplicate
AST nodes, so neither is asserted as an observed runtime detail.

The counted driver now emits one bounded JSON site diagnostic before any
extent refusal. It identifies the function, source offsets, preceding edit
boundary, expected type, at most 128 UTF-16 code units of observed text, and
applied/planned counts. New opt-in negative paths introduce a duplicate extent
or a changed expected type inside the explicit `.ps1` driver. Both must fail
before facade compilation or action import. Python passes only data and option
arguments; it constructs no executable PowerShell command. A Windows regression
method first checks the complete valid 52-site/eight-function reconstruction
without dispatch, then verifies both precise failures and their raw evidence.
All original source pins, facade hash and 23-type assembly/identity guards remain
unchanged. Successful synthetic action execution still requires a fresh Windows
run after this repair.

This repair adds 1,479 fully counted temporary PowerShell driver bytes. The
action oracle is 13,822 bytes; both helper drivers total 21,803 bytes. Canonical
tracked PowerShell is 904,469 bytes in 30 files, comprising 610,258 runtime and
294,211 other bytes. Runtime retirement credit remains zero.

Local verification for this extent repair passed 117 action and 45 wire
contracts, five raw-evidence tests, and 53 helper Python checks with 22 explicit
Windows-only skips. Full Python discovery passed 711 tests: 563 executed and
148 platform/opt-in skips. The net48 inert facade compiled with zero warnings
or errors. The Linux SDK/runtime and Major roll-forward limitation above still
apply. The new PowerShell 5.1 ordering and refusal paths have not yet executed
locally; their mandatory Windows tests remain a qualification boundary.

### Diagnostic-first binding investigation after the extent repair

Windows run `37103102251` at published `3cbbaaad` reached all 18 action-oracle
cases. Every recorded response contained the same `System.Object[]` to
`System.Collections.Hashtable` conversion exception, with `request_count=0`,
empty effects, and `calls={}`. No acquisition was reached. The subsequent
candidate `Unplanned provider access` failures therefore do not establish a
Win32/UIA loader-order defect. The no-request extent case independently exposed
the incorrect empty trace JSON shape.

The exact published dispatcher and six actions declare `[hashtable]$Args`.
[PowerShell's automatic-variable documentation](https://learn.microsoft.com/en-us/powershell/module/Microsoft.PowerShell.Core/about/about_automatic_variables?view=powershell-5.1)
and [the analyzer's automatic-variable rule](https://learn.microsoft.com/en-us/powershell/utility-modules/psscriptanalyzer/rules/avoidassignmenttoautomaticvariable?view=ps-modules)
identify `$args` as engine-maintained. The current
[PowerShell binder source](https://github.com/PowerShell/PowerShell/blob/master/src/System.Management.Automation/engine/scriptparameterbindercontroller.cs)
binds named parameters before assigning the remaining-arguments object array to
that same variable. This supports an automatic-variable collision hypothesis;
it is not a new Windows PowerShell 5.1 observation by itself.

`tests/fixtures/legacy-helper/binding-probe.ps1` imports only hash-verified,
unchanged `_Action-Health` and `_Dispatch` definitions. It invokes health,
shutdown, and unsupported requests, plus harmless automatic-`Args` and
distinct-parameter controls. Literal hashtables and converted empty, populated,
and nested JSON inputs isolate conversion from invocation. Thirty records retain
input types/values, received and bound types when a control enters its body,
entry/request counts, and bounded exception type, ErrorRecord type, FQID,
invocation and stack information. A changed source must be rejected before
import. The diagnostic runs no loader, OCR capture, UIA query or desktop action.
Its Windows result is still pending; the original differential remains required
and is expected to continue failing until this binding behavior is resolved.

The relevant source-level loader comparison remains:

| Boundary | Published PowerShell | Candidate and inert seam |
| --- | --- | --- |
| Win32 | Cache successful load; check existing assembly identity, resolve/check DLL path, then load; return false on failure | Action caches successful `win32.ensure`; real provider checks Windows and interop assembly identity; fixture records the attempt and uses case success/failure |
| UIA find | Load UIAutomationClient, UIAutomationTypes, WindowsBase; cache only complete success | Action caches successful `uia.load`; real provider loads those three assemblies; fixture records the attempt and uses case success/failure |
| Modal UIA | Attempt two UIAutomation assemblies with silent errors on each request; no UIA-find cache | `uia.loadModal` attempts both with caught failures; fixture records the corresponding boundary before Win32 |
| OCR | Cache a created engine; initialize WinRT types, try profile language, then first available language; retain failure detail | Action/provider expose initialization and language calls; current inert seam covers explicit synthetic profile success or initialization failure |

This comparison does not qualify static binding timing, assembly-load failure
equivalence, or resource lifetime. Loader calls have not been added, reordered,
or changed to satisfy the failed replay. The trace now uses an explicit object
array so zero/one/many counts keep array shape. Portable checks reject a JSON
object in place of that array, malformed or unknown calls, wrong argument counts,
and incomplete response/dispatch counts before starting candidate replay. No
invalid trace is normalized to an empty list. All original source pins, the
52-site type substitution and 23-type assembly guard remain unchanged. No
production candidate code or facade is changed in this diagnostic step.

Local validation for this diagnostic step passed 117 action and 45 wire
contracts. The helper gate reported 81 test methods: 57 passed, 24 individually
skipped, zero failures or errors, and no class-setup skips. Five raw-evidence
checks passed. Full Python discovery reported 749 test methods: 598 passed,
151 individually skipped, zero failures or errors, plus two class-setup skips
outside that method count. The printed `skipped=153` combines both skip kinds;
counts here come from the verbose outcomes. The net48 service/probe build had
zero warnings.
The new 5,596-byte probe and 158-byte trace change add 5,754 counted PowerShell
bytes: canonical total 907,688 on base `a3adb8c`. No helper source is retired.
The safe binding observation and typed-array serialization still require the
next Windows run; these local passes do not settle the binding hypothesis.

### Observed binding defect and isolated corrected-intent comparison

[Run 37104552075](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/37104552075)
at published `f5797783c71b4d2e70ac3649d59ad838ef10cd02` established the binding
defect on Windows PowerShell 5.1.26100.33438. All five exact-original health
calls and 15 exact-original dispatch calls failed before dispatch. All five
automatic-`Args` controls failed, while all five distinct-name controls succeeded.
Every input was a Hashtable, including literal and converted empty, populated
and nested objects. Errors were `PSInvalidCastException` with the
`ConvertToFinalInvalidCastException` FQID and the invoked command suffix.
The typed empty-trace and extent/refusal tests passed. All 18 original action
cases still failed before replay, as the diagnostic-first gate required.

The complete 34,021-byte raw probe stdout is retained as
`tests/fixtures/legacy-helper/observed-binding.stdout.bin`, SHA-256
`4d7cfb0b5de6c4d76e0685c6d5ff84d7e0c2d29f90590f79646cb444ad99521f`.
Its adjacent provenance record pins the public commit, run, archive digest,
process outcome and unchanged counted probe hash. It is diagnostic data, including
reported invocation lines, and is never evaluated or imported as source.

The original mode remains the default. Every original action case still runs in
its own process and retains complete raw stdout/stderr before a narrow classifier
is applied. That classifier requires unchanged source and type-seam hashes,
original mode, no Args edits, zero dispatch/acquisition, and the exact known
binding error for every complete response. Changed results, different errors,
missing/duplicate fields, timeouts, truncation or incomplete drains fail. Saved
classification explicitly says `raw_oracle_status=failed` and
`original_dispatch_qualified=false`. The unchanged binding probe also remains
mandatory. This is a classification of an observed baseline defect, not an
allowance for infrastructure failures or proof of original action behavior.

An explicit `-CorrectedIntent` switch enables a separate comparison process.
Only 34 original AST name extents across seven closed functions are renamed:
seven parameter declarations and 21 `$Args` references become `$RequestData`,
and six dispatch `-Args` tokens become `-RequestData`. `_Log` is unchanged.
Absolute UTF-16 offsets, literal spelling, AST kinds, declaring function and
closed command targets are checked before rewriting. The existing 52 acquisition
type substitutions and 23-type assembly guard remain independent and unchanged.
The union of edits must be disjoint and match exact original text; a second parse
must produce the same single function definition. A separate Python census
reassembles unchanged byte intervals and verifies original, type-only and corrected
hashes. Duplicate extents, changed text and wrong replacement names refuse before
facade compilation or function import. The original source and facade hashes
are unchanged.

This mode is labelled `corrected-intent-only`, never exact-original parity.
It independently checks the six supported actions' complete output fields,
types, query arguments and acquisition order across the 18 cases, including
failure/retry/cache behavior, Unicode/cultures, caps and tied candidate membership.
The candidate must additionally consume every captured call and match corrected
responses and tie order exactly. The exhaustive provider still refuses extra,
missing, reordered or differently parameterized access. No canned provider call
is inserted to compensate for absent original execution.

The user-visible intended difference is explicit: the candidate can enter and
execute the documented actions, where the original typed automatic variable
prevents dispatch. This oracle patch changes no runtime candidate, production
caller, loader, autostart or original function. Production compatibility and
retirement remain separate decisions. Args-only correction may expose additional
baseline defects: source review flags hashtable `Sort-Object -Property score`
on PS5 and the nested OCR helper's typed `$T`/`$t` name collision. Neither is
silently corrected here. Independent action expectations will reject incorrect
sorting or OCR results and retain their raw observations. Actual corrected PS5
execution and its negative paths remain required Windows qualification.

Local validation passed 117 action and 45 wire contracts. The helper suite
reported 93 methods: 68 passed, 25 individually skipped, zero failures/errors and
no setup skips; five raw-evidence tests also passed. Full discovery reported
761 methods: 609 passed, 152 individually skipped, zero failures/errors, plus
two class-setup skips. Counts were checked against verbose outcomes. All 18
independent semantic fixtures passed the portable candidate host, and the net48
facade compiled with zero warnings. The counted oracle grows by 7,406 bytes;
canonical PowerShell is 915,094 bytes across 31 files, with runtime PowerShell
unchanged at 607,665 bytes. This patch earns no retirement credit.

The production-staging document supersedes the earlier no-production-caller
description for the opt-in staged route. Existing candidate idle-timeout
admission boundaries remain unchanged. Historical
candidate evidence above remains evidence for its recorded implementation.
### Next functional tier after observed OCR and ranking defects

The Args-only Windows run at `bb98df41` confirmed the additional OCR type-variable
failure and ranking/selection differences. A separately labelled four-site
functional tier is staged with explicit numeric descending order and stable
acquisition-order ties. Original and Args-only raw evidence remain distinct and
unqualified; the runtime candidate is unchanged. See the
[functional-intent scope, evidence and compatibility decisions](legacy-helper-functional-intent.md).
