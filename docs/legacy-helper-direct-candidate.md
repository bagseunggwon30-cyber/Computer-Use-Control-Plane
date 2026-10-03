# Explicit direct helper entry points: staged candidate

This adds `serve-direct` and `exchange-direct` to the existing fixed net48 helper
package. It does **not** select a default route, install/register a service,
modify a real Startup entry, change a user computer, or retire original source.
New Windows behavior remains unqualified until the owned gate passes.

## Caller evidence and precise mapping

The original public script is listed in `scripts/README.md`. Its parameter block
in `scripts/cucp-helper-server.ps1` exposes PipeName, LockFile, DebugLog and a signed
Int32 IdleTimeoutMs defaulting to 60,000. Omitted/empty PipeName selects
`cucp-helper-<current PID>`; omitted/empty LockFile creates/uses
`%TEMP%/computer-use-control-plane/helper.pid`. `_Log` gates human stderr output
on DebugLog. Both real wrapper launch sites, `Start-HelperServer` and
`Install-HelperAutostart`, pass only IdleTimeoutMs. Repository search found no
product caller supplying custom PipeName/LockFile/DebugLog, but absence of a
macro caller is not proof those public-script parameters may be dropped.

The new explicitly selected surfaces are:

```
PcuCp.LegacyHelper.exe serve-direct --pipe-name NAME --lock-file ABSENT_ABSOLUTE_PATH [--idle-timeout-ms N] [--debug-log]
PcuCp.LegacyHelper.exe exchange-direct --pipe-name NAME --request-file JSON_FILE [--connect-timeout-ms N] [--read-timeout-ms N]
```

The direct server retains the existing separate `--allow-readonly-desktop`
launch ceiling. Without it, health/lifecycle work and provider acquisition fails
closed. Requests cannot enable the provider or debug logging. The fixture and
desktop-provider options remain mutually exclusive before acquisition. Test
execution uses generated owned files and denied/inert providers only; the one
mutual-exclusion test cannot reach either provider.

Existing `serve`/`exchange`, the wrapper, Python CompiledLauncher/Transport,
inspect_lock, PID-bound discovery, and the original default bodies remain
unchanged in behavior. In particular, `serve --pipe-name` remains rejected and
`exchange` still accepts only its existing PID-shaped target. Its original
request-file-before-required-target validation precedence is preserved. Custom
records remain unusable by automatic discovery; no pipe name is remapped.

Both direct options are required. This stage deliberately does not reproduce
omitted/empty original defaults. Publishing a compiled PID-shaped service into
original `helper.pid` could make the retained default wrapper discover it without
selecting staging. The direct mode therefore requires a non-discovery filename;
`helper.pid` and `helper-staged.pid` are reserved case-insensitively everywhere,
including attempted stream/path aliases. Missing parents are not created.
Original optional/default lock behavior and user-facing transition remain an
explicit final-activation requirement; original script stays available.

## Literal local target and lock rules

Accepted pipe names are returned verbatim, up to 247 UTF-16 units (the local
namespace prefix occupies nine units). Spaces inside the name, Unicode, case and
accepted punctuation are preserved. Names must be valid Unicode; empty names,
separators, colon, control characters, quote/angle/vertical-bar characters,
reserved `anonymous` in any case, and trailing dot/space are refused. Framework's
full local pipe path must equal the exact supplied spelling plus the fixed local
prefix, rather than silently normalizing an alias. These are explicit staged
validation restrictions, not a claim every name the historical binder accepts
works identically. Native maximum-length and Unicode execution need Windows proof.

Lock paths must be explicit absolute local paths with existing fixed-drive NTFS,
non-reparse ancestry. Existing 8.3 directory aliases are admitted only when each
changed full directory prefix identifies the same retained native object as its
Framework-expanded spelling. Both chains must have equal depth/root and an exact
unchanged file leaf. Raw syntax is validated before any Framework normalization:
empty/dot/dotdot components, slash separators, trailing dot/space, invalid Unicode,
ADS and DOS device components (including extensions and superscript COM/LPT
aliases), and discovery filenames are rejected before lock creation. Root-to-leaf directory handles deny write and
delete sharing for the direct service's lifetime and are disposed on every
partial acquisition/exit path. Existing create-new lock publication, exact
original-byte plus native-file-identity cleanup, BOM/schema/owner/version fields
and same-user creation-time verified protected pipe ACL are reused.

The directory lease also prevents replacement through the tested ordinary rename
route while this service lives. Direct fixtures verify denial without weakening
the lease; same-file edits remain preserved by byte-CAS cleanup. The unchanged
ordinary-service transport fixtures separately prove identical-byte/new-file-ID
replacement refusal by the shared cleanup implementation.

This restriction is about the **lock filesystem**, not an assertion that named
pipes are NTFS files. UNC/ReFS/removable/junction-backed lock support is not added.
Hostile same-user DOS namespace remapping is not authenticated by directory
handles. Neither a chosen custom name nor a successful connection authenticates
a peer process. The explicit client targets the local machine only and introduces
no remote-host option; existing same-user trusted-acquisition assumptions remain.

## Transport, idle and DebugLog

Direct exchange shares the existing bounded wire core: strict UTF-8, 1 MiB frame
limits, one bounded connect, one shared write/read deadline, no fallback and no
retry after timeout/disconnect or uncertain shutdown. It does not use automatic
lock discovery or signal any advertised PID. Owned test cleanup uses only retained
new process objects. The inherited service-side connected ReadLine behavior is
unchanged: bounded exchange does not establish bounded arbitrary server reads or
a new connected-idle deadline.

Direct serve defaults to 60,000 ms, admits zero and rejects negative Int32 values
before lock creation, matching the compiled serve contract. Positive-only Python
start admission is unchanged. The original signed binder accepts negative values,
but its pinned startup fails at `owner_sid=(try ...)` before a usable lock/service;
that cannot qualify negative-duration semantics. Existing zero/negative fixtures
remain intact, with additive direct vectors. Exchange budgets must be positive.

`--debug-log` is a flag for direct serve only. Debug stderr consists of fixed
lifecycle events, sequential request ordinal, whitelisted action class (`other`
for arbitrary actions), ID kind and fixed response exit code. It never contains
raw request IDs, arbitrary action strings, arguments, results, parser exceptions
or payload secrets. It emits at most 128 bounded records plus one limit marker;
each line is at most 192 characters and contains no injected newline. No bytes
are emitted on stdout by the server. Disabled debug has no debug rows. Fatal CLI
errors and the separately selected existing diagnostic-phase/ACL streams retain
their own behavior.

This is an explicit bounded/private-metadata replacement for DebugLog, not an
alias for diagnostic-phases and not byte-compatible with the old timestamped
human log. Request/response events describe processing, not proof of delivery;
cleanup events describe an attempt, not permission to delete a replacement. The
separate phase diagnostics still expose bounded elapsed timing. A stderr consumer
must drain its selected log stream: record/field bounds do not promise that an OS
stderr write can never block. No log output grants authority or changes replay.

## Qualification and retained evidence

The staged-routing workflow runs the opt-in direct gate on changed paths with
contents:read only:

```
python pcucp-next/packaging/qualify_staged_legacy_helper.py --autostart --direct
python pcucp-next/packaging/qualify_staged_legacy_helper.py --windows --autostart --direct
```

The action gate also includes the direct tests under its owned Windows mode.
Portable contracts link the actual validation/debug source, rather than a Python
reimplementation. Windows cases use random names, temp lock roots, retained
process handles, bounded raw evidence and a separately named generated peer mode.
They cover custom spelling/health counters/lock schema/ACL, maximum length,
collisions, old-mode refusal and validation order, closed flags, invalid local
names/files, denied provider, zero/negative idle, cleanup edits/lease exclusion,
DebugLog default/cap/redaction, connect/write/read deadlines, uncertain shutdown,
UTF-8 framing, oversize refusal and no extra connection attempt. The old probe
mode and old test inputs are retained unchanged.

Fresh Windows and full combined regression remain mandatory. The package payload
list/schema/version are unchanged; the compiled executable simply includes these
additional explicit entry points. No PowerShell source or test driver is added
or retired by this patch. Retained historical sources/oracles still count toward
final zero-PowerShell source and execution. Source-mode installation and the old
optional/default direct surface remain open acceptance work.

## Initial local freeze evidence and source accounting

Independent static review found no remaining freeze blocker. Linux builds the
net48 service and owned transport probe with zero warnings/errors. The actual
portable linked host passes 117 action, 45 wire and 63 new direct checks. The
staged portable gate passes 185 methods (144 passed, 41 skipped); helper action
Python discovery passes 286 methods (220 passed, 66 skipped), with nine separate
evidence-collector passes. Full Python discovery passes 1,006 methods: 813 passed,
193 individual skips plus two setup skips. The 14 new Windows methods are still
unexecuted here; they must pass on the fresh combined Windows commit.

Local .NET evidence uses SDK 10.0.401 and explicit Major roll-forward to installed
runtime 10.0.12, workspace-local caches and the already-present offline NuGet
source. It is not native Windows/.NET Framework execution, installed .NET8 proof,
or a vulnerability-audit result. Raw local records are under
`.migration-logs/direct-local/`, including final staged/action/full reruns.

Canonical inventory remains 966,975 tracked PowerShell bytes on the isolated
`dd8df5d` base. This patch changes zero `.ps1` bytes and retires zero originals.
Across changed/new `.cs` and `.py` files, runtime grows 12,165 bytes (22,399 to
34,564 in changed files), tests grow 24,238 (9,491 to 33,729), and tooling grows
1,112 (7,063 to 8,175): 37,515 additional source bytes. These are changed-file
subtotals, not whole-repository totals. New portable links compile existing source
without double-counting it; generated JSON peer/request files are non-executable
fixture inputs. No new hash-pinned raw fixture/manifest is introduced, and no
PowerShell is concealed in strings or an alternate extension.

## First owned Windows failure and retained-alias correction

The first direct gate, run `37121668355` at public
`968379e6eca731ff849fd554339601261c291584`, ran 17 direct methods and recorded ten
failures. Every server-start failure had exactly
`ArgumentException: direct lock path must not require normalization`; the normal
runner TEMP prefix was `C:\Users\RUNNER~1`. Custom exchange, its hostile peers,
and pre-lock refusal cases passed. This was a runtime path-admission defect, not
an invalid temporary-directory fixture or a reason to widen a deadline.

Framework explicitly expands existing short-name components even when the final
file does not yet exist ([reference source](https://github.com/microsoft/referencesource/blob/main/mscorlib/system/io/path.cs#L597-L606)).
The corrected admission splits and validates the supplied string before any
`Path`/`DirectoryInfo` method can erase its spelling. It retains root-to-parent
handles for the supplied spelling and each differing full expanded prefix,
rejects reparses and non-NTFS components in both, and compares volume serial plus
both native file-index fields. Case-only spelling differences also receive native
identity proof. These are the documented
[file identity fields](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/ns-fileapi-by_handle_file_information);
NTFS [directory hard links are unavailable](https://learn.microsoft.com/en-us/windows/win32/fileio/hard-links-and-junctions).
No separate long-path-name conversion is trusted as an ownership proof.

The direct service now consumes the normalized path from that retained lease.
It no longer computes an independent earlier path that could become stale before
validation. Existing `serve` path handling, direct pipe spelling, isolated lock
leaf, create-new publication, byte/identity cleanup, ACL and transport limits stay
at their established boundaries. No directory is created, remapped or retried.

The archive is 603,426 bytes, artifact `11274200014`, SHA-256
`354fecd20d0f9730718490be9eee34ede172713643d02aa2d0a46e480eaab1ea`.
All 755 extracted files matched the ZIP byte-for-byte. The frozen public and local
`8fafca8cc4b59d86a34ee6674aaea88b97009afb` trees both equal
`5fb9191301f91e585efe40c8c86c0f74b296f92c`. Package manifest entries match the
captured build closure; its Program.cs/project hashes exactly match the Windows
CRLF checkout of that local source. This comparison does not claim a locally
rebuilt binary is identical to the Windows package.

`tests/fixtures/legacy-helper/observed-direct-path/` retains the exact failed
start record/stderr, complete direct-suite stderr and package manifest/closure.
Its provenance manifest is itself hash-pinned. All six files are protected with
`-text`; an actual Git checkout with CRLF conversion verifies every protected
file and an unprotected converting control. The original failure remains failed
and unqualified.

New native regressions require a genuine distinct short alias, independently
prove `samefile`, launch through each spelling, exercise health and an existing
lock collision through the other spelling, refuse ancestor rename through both,
and verify shutdown removes the one owned lock from both views. Raw lexical
negatives are passed as strings to avoid Python pre-normalization. Junction
refusal is checked through both directory spellings. The gate fails if it cannot
obtain an actual alias; it does not count a no-op conversion as coverage. No
filesystem setting is changed to provision aliases.

The local linked host passes 117 action, 45 wire and 91 direct contracts. The
staged portable gate runs 190 methods: 147 passed and 43 skipped. The net48
service builds with zero warnings/errors. Full Python discovery runs 1,024 methods
and returns `OK (skipped=197)` with no failure/error. All 16 direct
Windows methods, including the two new methods, require a fresh actual Windows
run of the repaired combined package. Local evidence retains the SDK/runtime and
offline-cache limitations described above under `.migration-logs/direct-path-local/`.

Canonical inventory at this repair base is 979,706 tracked PowerShell bytes,
including retained tests and newly integrated provider fixtures. This correction
changes zero PowerShell bytes and retires zero originals. Across
changed runtime C# files the subtotal grows 1,830 bytes (18,358 to 20,188), and
changed C#/Python tests grow 7,201 (23,355 to 30,556): 9,031 added executable source
bytes. The six new retained raw/provenance fixtures add 19,850 non-executable
bytes; these are included separately rather than hidden from total growth.
These are changed-file subtotals, not whole-repository totals.
