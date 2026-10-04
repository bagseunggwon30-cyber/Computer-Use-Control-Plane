# Conditional compiled helper routing (staged, unqualified)

This branch connects the existing detached net48 helper and Python client to the
actual `scripts/cucp.ps1` user-facing session and native-read routes. **It is not
promotion, accepted source retirement, or action-semantic qualification.** The
27,427-byte original server and all seven original client function default bodies
are retained. The original action oracle, its input corpus, hashes and baseline
startup failure remain unchanged by this work. Intended-working-contract oracle
repairs are independent and must be merged/reviewed separately.

## Activation and packaging

Build a fresh separate package with:

```
python pcucp-next/packaging/publish_legacy_helper.py
```

This builds net48, copies exactly the executable, its config and the interop DLL,
and writes `manifest.json` with status `staged-unqualified`. Existing output is
never overwritten. No installation, Startup registration, external publication,
portable-bundle change or default route switch occurs. Windows and .NET Framework
4.8 are required at runtime; source-mode Python must be discoverable as
`python.exe`. The current outer wrapper still independently requires Node and
retains its other Python/C#/PowerShell dependencies. Building is not execution
qualification. The executable includes its existing compiled inert fixture seam;
no fixture assets, test drivers or source files are included in this package.

For a deliberately selected source-mode staging invocation, set
`CUCP_STAGED_COMPILED_HELPER=1` in that invocation's environment. This selects the
seven actual wrapper delegates, including `macro session start-helper`,
`helper-status`, `stop-helper`, and server-first native read acquisition.
The selected service uses `%TEMP%/computer-use-control-plane/helper-staged.pid`.
The retained service still uses `helper.pid`; staged mode cannot accidentally
reuse that original service. Existing live services are never automatically
stopped, migrated, restarted or killed by advertised PID.

`CUCP_STAGED_HELPER_READONLY_DESKTOP=1` separately authorizes the provider on a
newly launched staged shared service. It is captured at wrapper startup, never
accepted in bridge/action data. It is **launch authority**, not a global wrapper
policy or a way to revoke a previously started shared service's capability.
Without it, lifecycle and health work while desktop acquisition fails closed.
The test gate never sets it. Existing one-shot wrapper read fallback retains its
own behavior/authorization. Changing a startup flag cannot downgrade an already
running shared service: deliberately stop it before starting with another ceiling.

The bridge resolves its package beside its fixed source entry, independent of
CWD, `CUCP_ROOT`, `PYTHONPATH`, request JSON and executable override variables.
Both publisher and runtime reject a linked package root, missing/extra payloads,
changed hashes and malformed metadata. These hashes detect corruption; they are
not signatures or protection against a malicious same-user installer replacing
both binaries and manifest. The existing account/ACL trust boundary remains.

## Preserved routing and safety

The same `Invoke-NativeHelper` owns route choice, three-option forwarding,
ForceChild/nonempty force-environment semantics, pipe-before-hot-cache order,
500 ms four-action cache, and original one-shot fallback. Code 99 falls back;
error 1 and partial 2 return the pipe result. Label/crop omissions in that wrapper
are preserved, not repaired. Bridge/package failures in the preliminary read and
staleness checks permit existing cache/read-child fallback; start/stop never fall
back to the old service and never retry an uncertain mutation. Metadata failures
return a recoverable version error. The new internal snapshot property never
appears in the selected-field public lifecycle/status/version schemas.

Concrete adapters implement bounded lock reads, real process-username lookup,
read-only process-existence probes, and exclusive-write/delete handle acquisition
for exact file-identity AND original-byte conditional deletion. The native
FILE_DISPOSITION_INFO uses its one-byte BOOLEAN layout. Lock replacement, even
with identical contents, and same-file byte edits cannot satisfy that acquisition.
Unreadable/foreign/malformed metadata is not deleted; failed CAS preserves the file.
A request failure can only clean the attempted snapshot, never a later replacement.

The staged CAS adapter deliberately requires a local NTFS lock path rooted at a
drive reported as fixed.
It refuses UNC, removable/non-fixed drives and other filesystems before cleanup.
The drive-type check uses the lexical drive; mounted-volume/junction redirection
is not qualified as fixed-storage isolation, even though the acquired file handle
must report NTFS. The published wrapper derives its path from TEMP and offers no session option to
choose a lock file, but users can configure TEMP onto other storage. Their selected
staged service can therefore fail to start (or reads use the ordinary one-shot
fallback) instead of working persistently. No universal filesystem guarantee was
found in product docs. Broader filesystem support needs a reviewed identity design
and qualification; this does not prevent qualification of the explicit local-NTFS
route. In particular, the 64-bit BY_HANDLE_FILE_INFORMATION identifier is not a
claim of unique identity on ReFS.

Detached launch uses the retained newly created Popen process handle, disconnected
standard streams, DETACHED_PROCESS and CREATE_NEW_PROCESS_GROUP. It deliberately
has no modern NativeSession/parent-death guard or broad process-tree kill. Startup
failure terminates only that retained new process. Successful services outlive
the wrapper. A lock is still not a readiness/authentication proof: ACL failure may
follow publication, as documented by the existing candidate contract.

The short-lived exchange worker has bounded parallel stdout/stderr drains and an
absolute timeout; its pipe transport also bounds connected I/O. The PowerShell
bridge uses bounded asynchronous stdin/out/err operations with an outer deadline.
Only the retained bridge/exchange process is terminated on failure. Shutdown is
never replayed. No shell, generic executable or authority field is added to the
protocol. The server's already-documented connected ReadLine idle limitation is
not changed here.

## Option and dependent-path inventory

- `macro session start-helper --idle-timeout-ms`: real product caller. The
  PowerShell parameter binder accepts signed Int32 values, but no product
  documentation or qualified intended-behavior evidence was found promising
  zero/negative-duration service behavior. This stage retains the candidate
  client's positive-Int32 admission rule before any lock/process effect. The
  direct compiled serve CLI retains its existing nonnegative parser: negative
  values fail before lock creation, while zero remains admissible there. This
  distinction and the stage's narrower nonpositive-input behavior are explicit
  compatibility limits pending a reviewed product-contract decision. The
  retained PowerShell default path is unchanged. No negative CLI guard is waived
  merely because its Windows execution was skipped locally.
- Direct `cucp-helper-server.ps1 -PipeName/-LockFile/-DebugLog`: parameters of the
  retained standalone script. Repository product callers do not pass them;
  documentation search found no broader product CLI contract for them. This
  stage does not remove that script or silently remap custom names. If the direct
  script is retired, its supported direct-use surface needs an explicit decision
  and migration path first. The later [explicit direct candidate](legacy-helper-direct-candidate.md)
  maps custom launch/exchange only; it keeps automatic discovery and old modes
  unchanged and leaves original optional/default lock semantics unretired.
- Version reporting: staged path reads verified compiled-package metadata,
  reports that manifest as its source, and retains partial/recoverable failure
  behavior. Default mode still uses the original PS header.
- `install-autostart`, `uninstall-autostart`, `autostart-status`: now delegate in
  explicit staging to the separately unqualified compiled-bootstrap candidate.
  See [autostart candidate](legacy-helper-autostart-candidate.md) for preserved
  public paths/schemas/live guards, approved compatibility corrections, owned-temp
  proof plan and remaining real-registration/update gates. Existing live or legacy
  shims are never automatically overwritten or removed.
- `install.ps1`, default portable distribution and direct script launchers are
  unchanged. Source-mode staging packaging is not a complete user installation.

## Proof gates and promotion/removal path

```
python pcucp-next/packaging/qualify_staged_legacy_helper.py
python pcucp-next/packaging/qualify_staged_legacy_helper.py --windows
```

Windows mode requires a clean fixed-package destination, builds fresh artifacts,
and runs actual Win32 CAS, process/lifecycle, denied-desktop service and production
wrapper start/status/version/stop across processes. It also executes extracted
actual production functions with an injected failed bridge, checking hot cache,
one-shot inert child, recoverable version and nonthrowing cleanup. Extraction is
only an acquisition-failure fixture; the distinct full-wrapper fixture executes
the real entry point. Gate, wrapper and fallback-fixture processes retain bounded raw evidence. The
production detached launcher deliberately disconnects service stdout/stderr; those
service streams are not captured by this route. Detailed service diagnostics
remain covered by the separate owned transport fixtures, and lifecycle assertions
record the observable lock/process/response outcomes.
The three new `.ps1` drivers are normal tracked source, not encoded or concealed
in Python strings. Their extracted function text comes from tracked source; it
is not additional uncounted generated implementation.

The narrow staged-routing workflow has read-only repository permission and runs
on its changed paths on `migration/python-csharp-runtime`, plus manual dispatch.
It is separate from the action candidate workflow and does not hide action
failures. A staged-routing pass alone cannot activate a default or earn retirement.

Required before default activation/removal:

1. Fresh actual Windows stage gate passes, including PS5 async bridge behavior,
   quoting/Unicode paths, no-desktop fixtures, owned lock races and detached
   cross-process lifetime. Expand process-death and package/bridge-failure negative
   cases as needed; no local Linux build substitutes for them.
2. Independently corrected intended-working-contract action oracle and raw exact
   historical observations retained side by side. Resolve remaining sort/OCR,
   coercion/ordering/resource issues with real action evidence, not just synthetic
   shape checks. Existing helper transport/ACL gate must pass at the same commit.
3. Complete real-production read action, error/partial/99 and cache/fallback tests,
   generated-file real OCR, UIA/capture, DPI, elevation/session/account boundaries
   and agreed security/compatibility corrections on an authorized fixture machine.
4. Close compiled autostart/install/direct-CLI transition and platform/runtime
   requirements; explicitly review local-NTFS and shared-launch authority limits.
   Benchmark per-operation Python bridge overhead before selecting it by default.
5. Full regression against the frozen combined commit, source inventory and
   independent review. Only then separately switch the default, retire the exact
   original function/server bodies, repoint all callers and update accepted
   retirement evidence. Retain all old inputs via hash-pinned Git sources until
   independent fixtures qualify. Never mark this stage as accepted retirement.

Final zero-PowerShell includes the outer wrapper, one-shot child, install/CI
commands, retained oracle drivers, extracted/generated test execution and inline
engine dependencies. This branch does not claim that broader unfinished goal.

## Local evidence and honest source accounting

Linux builds the updated net48 service with zero warnings/errors; this is not
Framework execution. The portable staging gate and focused helper source/client/
package/runtime suites pass. All seven new Windows methods are still unrun here,
as are the existing Windows action and transport gates on this commit. The
SDK is 10.0.401; portable net8 execution, if recorded, uses explicit Major
roll-forward to runtime 10.0.12 and is not proof of installed .NET8 behavior.

Canonical index accounting includes all retained oracles and the new normal
PowerShell test drivers. No source bytes are retired by this stage. Runtime,
test and tooling subtotals below classify source purpose, not shipping status;
retained tests remain a final-zero source/execution dependency. Exact counts are
refreshed with the frozen index and recorded in the inventory. Test extraction
executes existing counted function source; no additional generated script body
is stored in Python or an alternate file extension.

Frozen-stage source totals: runtime-classified PowerShell 619,049 bytes,
test PowerShell 287,534 bytes, tooling/reference PowerShell 11,061 bytes;
all tracked PowerShell 917,644 bytes. The canonical `scripts/`-only subtotal is
614,472 bytes. The runtime-purpose category additionally includes `install.ps1`
(1,519), `pcucp-next/powershell/cucp-next.ps1` (932), and
`pcucp-next/powershell/start-pi.ps1` (2,126), totaling 4,577 extra install/bootstrap
bytes. Thus 614,472 + 4,577 = 619,049; the two classifications do not disagree. This is 9,956 bytes more than
base 855d548 (907,688), with zero helper retirement. The new runtime adapter
adds 5,081 bytes; the three new test drivers add 3,149 bytes. The remaining
increase is the conditional wrapper delegates. Inventory uses canonical index
blobs, so Windows checkout newline expansion cannot distort these totals.

Final local checks for this stage: net48 build passed with 0 warnings/errors;
net8-targeted synthetic self-tests passed 117 action and 45 wire checks. The
existing helper gate passed using an explicitly local offline NuGet source and
workspace-local caches after a retained initial NU1900 failure attempted the
read-only default cache. No vulnerability-audit result is claimed by that offline
build. The final portable stage gate passed. Full Python discovery reported
804 methods and `OK (skipped=220)`; the skip display includes two class-setup
skips, and unavailable Windows/opt-in/other built-host dependencies are not
qualified. See raw local `.migration-logs/staged-helper-local/` records when
reviewing the worktree; logs are not shipping source.

## Pre-publication admission correction

Integration review found that the initial staging commit admitted negative
serve idle durations while the retained Windows closed-CLI test requires
rejection before lock creation. Signed PowerShell binding alone was insufficient
contract evidence. The follow-up restores Program.cs byte-for-byte to the base
candidate and restores the client's original positive-duration validator.
`test_closed_cli_options_reject_before_lock_creation` and its inputs remain
unchanged. New portable coverage rejects nonpositive and invalid values before
state acquisition or launch; the added Windows direct-CLI fixture retains all
three vectors (0, -1, Int32 minimum) with the original admission boundaries.
Fresh Windows execution is still required, rather than inferred from the local
compile or skipped methods.

## Verified lifecycle checkpoint and subsequent autostart stage

The earlier local-only/unrun statements above describe the original freeze.
The owned Windows lifecycle checkpoint subsequently passed at public
`b9dff5ddd9daad44cb5a5ba0ef58d7a088ebe81b`, tree
`af4eb1af502a37a187eac6d3c19f0d09ed28f5b4`, CI `37114285871`: 27 package passes,
36 runtime passes plus one Linux-only skip, and 43 client passes. Real wrapper
start/status/version success+partial/stop and concrete detached lifecycle pass.
Raw prior failures and corrected-intent action evidence remain separate. This is
bounded lifecycle qualification, not default activation or source retirement.
The new [autostart candidate](legacy-helper-autostart-candidate.md) is a subsequent
unqualified change requiring fresh owned Windows and real-transition proof.
