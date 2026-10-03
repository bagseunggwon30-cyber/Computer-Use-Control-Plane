# Compiled helper autostart candidate: owned-temp stage only

This extends the explicit `CUCP_STAGED_COMPILED_HELPER=1` source-mode route. It
is candidate code with temporary-directory tests, **not permission or evidence
for installing/removing a real Startup entry, changing login registration,
activating a default, or retiring a source**. Existing installed launchers must
not be transitioned automatically. A real transition requires separately
explicit user authorization and the remaining gates below.

## Supported surface and retained evidence

The retained product caller is `Invoke-MacroSession` in `scripts/cucp.ps1`:

- `macro session install-autostart [--idle-timeout-ms N]` requires
  `-AllowLiveControl`, defaults to 28,800,000 ms (8 hours), and returns the
  `cucp.helper-autostart/v1` envelope. Success data is `status`, `action`,
  `shim_path`, `idle_timeout_ms`, `note`.
- `macro session uninstall-autostart` requires the same live guard. Success data
  is `status`, `action`, `shim_path`, `removed`; absent files remain an idempotent
  success. Status/uninstall must work when the compiled package is absent.
- `macro session autostart-status` is read-only. Data remains `status`,
  `installed`, `shim_path`. Like the original, presence does not prove ownership,
  valid command contents, a running service, or successful future login launch.
- `_Get-AutostartShimPath` is unchanged: OS current-user Startup directory plus
  `cucp-helper-autostart.cmd`. There is no product command-line folder option.
  The original comments explicitly identify shell:startup manual visibility and
  removal, a per-user entry, and hidden/minimized helper startup as intended use.
- The original wrapper's invalid integer parse fallback to the 8-hour default
  stays in its caller. The staged controller admits positive Int32 durations;
  zero/negative admission remains an explicit limit, not a supported-contract
  inference from PowerShell's signed parameter binder.

There is no repository evidence of a broader documented arbitrary Startup path,
command, interpreter or metadata-file option. Internal bridge CLI paths are
trusted launch context, not JSON options. The production wrapper obtains Startup
and LocalApplicationData from OS folder APIs, never caller request data. Tests
replace only these acquisition points with independently owned temporary paths.

All four original default functions remain byte-for-byte after removing only the
three exact staged delegate lines. A new source guard retrieves the original
wrapper from pinned tree `e36329b2a6b07539faacd070d661bc0e3819140d` (published
`3e892ab02395bdc916a5814e39d4154efd1f6249`), verifies its existing source-manifest
hash, and compares those bodies. Original tests/oracle inputs are retained. No
PowerShell is hidden in Python strings, encoded blobs, alternate extensions, or
generated launchers. The new `.ps1` acquisition driver is tracked/counted source.

## Candidate behavior and approved compatibility corrections

- The shim keeps its public name/path, uses UTF-8 without BOM with explicit CRLF,
  selects codepage 65001 before the Unicode command line, enables command
  extensions, disables delayed
  expansion, doubles literal percent signs, and quotes every fixed argument.
  The retained original writes ASCII and can corrupt Unicode paths. This is an
  intentional encoding correction. The existing source installer already uses
  UTF-8/codepage selection; this candidate also restores the prior codepage.
- It invokes a fixed discovered Python executable with `-E -s`, the fixed
  `legacy_helper_autostart_entry.py`, a staged marker, the chosen idle duration,
  and an optional captured read-only-desktop ceiling. No PowerShell invocation,
  generic command, `start`, `call`, or caller `%*` is generated. An inherited
  ERRORLEVEL variable is cleared inside setlocal so it cannot replace the actual
  bootstrap exit code. The batch returns that code after codepage restoration.
- The short bootstrap runs synchronously, validates the fixed compiled package,
  and calls the already-staged detached launch path once. A successful service
  remains detached/shared. This differs from the original minimized asynchronous
  `start` launcher: login window visibility and launch latency are unqualified.
- Install/uninstall require both the retained macro live guard and launch-time
  authority captured by the adapter. Later wrapper-variable changes, environment
  flags or JSON cannot elevate that captured authority. Read-only-desktop
  authority is independent and embedded at installation time; the service still
  has no live actuation capability. A service already running with a different
  ceiling retains the shared lifecycle semantics documented for staged routing.
- Existing legacy, unowned or changed shim/marker files are preserved with
  `shim_write_failed` or `shim_remove_failed`, plus bounded detail and `path`.
  There is no automatic upgrade/removal of an existing live registration.
- Identical owned configuration is idempotent. A changed idle duration,
  executable/bootstrap or desktop ceiling refuses while preserving both files.
  The original supports rewriting configuration in place; this is a documented
  staged limitation, **not full autostart compatibility**. A separately authorized
  uninstall/reinstall transition or reviewed transactional update remains work.
- Package validation is required for install and bootstrap launch, but not status
  or uninstall. Status is presence-only, preserving the original schema. Helper
  version reporting continues to use verified package metadata and the existing
  success/partial envelopes; its recoverable recommendation now names the
  compiled package publisher when staging is selected.

## Ownership, directories and failure recovery

The only Startup artifact is the public `.cmd`. Ownership metadata is at the
fixed OS LocalApplicationData path `.cucp-helper-autostart.json`, outside Startup;
no containing directory is created. A JSON file in Startup might be shell-opened
at login, so a dot-prefixed sidecar in Startup is explicitly not used.

Both existing directory chains must be local, fixed-drive NTFS and free of
reparse components. The adapter retains native handles to every ancestor from
root to leaf throughout the operation, denying write/delete sharing. Metadata
and all metadata-ancestor identities are checked against Startup's retained
identity, including pathname aliases. The marker binds Startup's exact path and
volume/file identifier, the exact generated command and SHA-256 of shim bytes.
This is corruption/ownership evidence, not a signature or same-user attacker
authentication. Hostile DOS drive remapping/SUBST namespace changes remain
unqualified. A user can redirect OS folders onto UNC, ReFS or junction-backed
storage; the candidate then fails before mutation (and status can fail) rather
than silently preserving universal filesystem support. No documented broader
filesystem promise was found. This limit requires product review before default
activation but does not prevent explicitly local-NTFS fixture qualification.

The metadata handle is retained with READ|DELETE and share-READ through shim
publication/removal. New metadata uses CREATE_NEW, checked complete WriteFile and
FlushFileBuffers before a create-new shim; no existing file is overwritten.
Marker-only recovery holds the same lease. Uninstall requires identical shim
bytes plus original file identity and uses the established handle-CAS removal;
metadata deletion uses its already-held native handle, never a pathname unlink.
No lock-advertised PID is killed and no uncertain mutation is retried. Errors
leave evidence in place. A partial new file or marker is not blindly cleaned up;
only a later explicit owned operation may recover a valid marker-only state.

These protections avoid accidental clobbering and races among cooperative
installers. Package hashes/marker bytes cannot protect a user against an attacker
who can replace the user's source, interpreter, both registration artifacts or
DOS namespace. No ACL, account, token or security setting is changed by this work.

## Proof plan and exact qualification boundary

Run `qualify_staged_legacy_helper.py --autostart` for portable tests and
`qualify_staged_legacy_helper.py --windows --autostart` for actual owned Windows
tests. The narrow read-only staged-routing CI workflow includes these tests.
It builds a fresh package but creates registration-shaped files only in owned
temporary directories. It never discovers or writes real Startup/LocalAppData.

New coverage includes closed requests, unchanged historical bodies, exact schemas,
no permission-before-effect bypass, configuration refusal, unknown/tampered-file
preservation, missing-package status/uninstall, marker-only recovery, no retry,
real Win32 leases/CAS/ancestor locks/path aliases/reparse refusal, real bridge
roundtrips, and real adapter captured authority with inert fixed-path Python.
Generated launcher captures execute only an inert checked-in Python fixture in an
owned hidden console with a temporary standard-library venv (no pip/installation).
They cover literal spaces/Korean/percent/exclamation/caret/ampersand/parentheses,
interpreter flags, default/custom idle, ceiling, ignored caller args, inherited
disabled extensions/ERRORLEVEL, delayed expansion, exit codes and equal input/output codepage pairs 437/949/65001. Raw
stdout/stderr, argv, command line and failure evidence are retained before cleanup.
Split input/output codepage restoration is not claimed.

Fresh Windows execution of all these new tests is required. Before any real
transition/default/retirement additionally qualify authorized real login/startup
visibility/lifetime, source/package move and Python update behavior, redirected
OS folders, recovery after real interrupted writes, product configuration-update
compatibility, and user-visible error/partial paths. Existing installer/default
portable distribution/direct PS launcher retirement remains outside this patch.
The outer wrapper and retained install/test/oracle PowerShell are still required.

## Separately verified staged lifecycle baseline

The already-shipping opt-in lifecycle route passed owned Windows CI run
`37114285871` at public `b9dff5ddd9daad44cb5a5ba0ef58d7a088ebe81b`, tree
`af4eb1af502a37a187eac6d3c19f0d09ed28f5b4` (local equivalent
`099f944c95224f52181c4ebe64e84b0afd2d5018`). Results: 27 package passes, 37 runtime
methods with 36 passes and one Linux-only skip, 43 client passes. Real wrapper
start/status/version success+partial/stop and concrete detached lifecycle passed.
Artifact `11271137587` SHA-256
`d8918d2d4a76db7171a61d67725c8a7d2fa33b8bb7ea765cb43533142e7c4dd7` preserves that
baseline. Those results do not qualify this new autostart code or authorize real
registration. Raw startup/setter, multiple-Python resolution and polluted-envelope
failure records remain pinned beside their corrections.

## Frozen-candidate source accounting

Canonical index-based PowerShell accounting at this candidate is 947,712 bytes:
`scripts/` only 612,316; additional runtime install/bootstrap files 4,577;
runtime-purpose subtotal 616,893; tests including retained oracle/drivers 319,758;
tooling/reference 11,061. The 4,577 bytes are `install.ps1` (1,519),
`pcucp-next/powershell/cucp-next.ps1` (932), and `start-pi.ps1` (2,126).
The lifecycle base099f944 has 942,925 PowerShell bytes, so this patch adds 4,787
and earns **zero retirement credit**. Historical 614,472 scripts-only / 619,049
runtime-purpose totals in the original staging note remain frozen-stage facts,
not current totals after other integrated families changed.

Across changed `.py`/`.ps1` files, candidate source grows by 88,935 bytes:
runtime +20,460 (410,978 to 431,438 in changed files), tests +68,077 (35,702 to
103,779), tooling +398 (2,617 to 3,015). These are changed-file sums, not a
whole-repository source-size claim. New runtime Python files total 17,741 bytes;
new test Python files 63,484 and the tracked PS authority driver 3,451. Existing
shared evidence/bridge/tests are included in the net sums. Generated launchers
are CMD UTF-8 bytes, with no PS invocation. The authority driver extracts already
counted production function text; it does not introduce another uncounted PS
implementation. Temporary copied Python fixtures and launcher captures execute
the tracked source and are included in execution qualification, not hidden as
source retirement.

## Final cutover blockers still open

1. Configuration updates: preserve the original ability to change idle/settings
   through a safe transactional design, or approve and qualify an explicit
   authorized transition. The staged changed-configuration refusal is not final
   compatibility and never authorizes automatically removing an existing shim.
2. Direct `cucp-helper-server.ps1 -PipeName/-LockFile/-DebugLog`: retain the
   standalone script until its supported direct-use contract and equivalent
   mapping/migration path are explicitly reviewed. No custom pipe is remapped.
3. Installation/package paths: this is a source-mode checkout plus separately
   built fixed net48 package. The generated command embeds the discovered Python
   executable and source bootstrap path; moving/removing either can break login
   launch. The existing `cucp-core` wheel includes package modules but not these
   top-level source entries, and the default portable installer is unchanged.
   No complete wheel/portable installed-helper distribution is claimed. Qualify
   authorized install/upgrade/uninstall, package relocation and interpreter
   update behavior before removing the old installer/launch surface.
4. Fixed local NTFS/non-reparse directories: redirected Startup/LocalAppData or
   TEMP on unsupported filesystems fails closed. Review product support and
   broaden only with an equivalent identity/ownership proof. Actual 8.3 aliases,
   hostile DOS namespace changes and redirected-folder login remain unqualified.
5. Fresh combined Windows regression, real login/window/lifetime proof, and the
   independent actual-provider/OCR/action gates remain separate prerequisites.
   They cannot be inferred from pure planning or inert launch capture.

Local candidate checks: portable staged gate passes 156 methods (129 passed,
27 explicit skips): package 27/27; runtime 29/37 with eight Windows skips;
client 42/43 with one Windows skip; new autostart 31/49 with 18 Windows skips.
Independent ownership/directory and launcher reviews found no remaining
confirmed blocker for this **unqualified local freeze**. Syntax, diff and
canonical source-inventory checks pass. New native methods cover owned paths
only; none of their skipped results is execution qualification.

The SDK-enabled full Python suite passes 899 methods: 720 passed, 179 individual
skips plus two class-setup skips (`OK (skipped=181)`). It uses SDK 10.0.401 and
explicit Major roll-forward to runtime 10.0.12, workspace-local CLI/HTTP caches
and the already-present offline NuGet package directory. This is not actual
.NET8 or Windows qualification, nor a vulnerability-audit result. An earlier
unconfigured SDK run was interrupted after build-setup errors; the retained
bounded reproduction records `System.IO.IOException: Read-only file system`
for the default `/home/agent/.dotnet` first-use directory. No system directory
was changed. Local logs retain both the failed setup probe and the corrected
full run under `.migration-logs/autostart-local/`.
