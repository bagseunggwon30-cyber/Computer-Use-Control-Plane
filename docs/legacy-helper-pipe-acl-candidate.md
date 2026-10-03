# Owned helper pipe ACL candidate

This isolated patch stages a security correction for the opt-in C# legacy
helper. Production PowerShell, callers, autostart and the frozen published repair
remain unchanged. No PowerShell bytes are added or retired. Windows execution
and review are required before this correction can be qualified.

## Confirmed failure and construction semantics

The first Windows run, [37096050336](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/37096050336),
retained `PipeSecurity ACL failed (continuing): Attempted to perform an unauthorized operation.`
This generic diagnostic establishes setter failure and continued startup. It
does not establish the native error code or the effective DACL on that runner.

The [Framework constructor](https://raw.githubusercontent.com/microsoft/referencesource/refs/heads/main/System.Core/System/IO/Pipes/Pipe.cs)
forwards null security and zero additional rights from the five-argument overload.
Duplex access includes ordinary read/write and READ_CONTROL, but not WRITE_DAC.
Changing the DACL through that handle requires WRITE_DAC. Merely adding that
mutation right would leave an initial default-DACL interval. The eight-argument
constructor accepts the intended descriptor at creation and needs no setter.

A null *creation-time security descriptor* selects Windows' default pipe
security. The [documented default](https://learn.microsoft.com/en-us/windows/win32/ipc/named-pipe-security-and-access-rights)
includes Everyone and Anonymous read entries, in addition to owner/system/admin
access. This differs from a null DACL, which permits unrestricted discretionary
access. Neither the documented default nor the old error proves successful
anonymous or remote access on this runner. The owned fixture records its actual
default descriptor without changing it or accepting any requests.

## Staged policy and compatibility impact

The principal is the current process's WindowsIdentity.User SID. Descriptor
ownership is a separate field: Windows' token default owner can differ. The
candidate sets the descriptor owner to that user SID, protects the DACL without
preserving inherited entries, and supplies one ordinary explicit Allow
FullControl ACE for that same SID. This implements the original intended
user-level policy for wrappers in successive processes. No additional account,
token, credential, privilege or persistent grant is created.

That descriptor is passed to the asynchronous, single-instance, duplex pipe
constructor. Before WaitForConnectionAsync, the retained handle reads Access,
Owner and Group with GetAccessControl. No SACL privilege is requested. Existing
duplex access already supplies READ_CONTROL; no additional handle rights are
added. Framework's additionalAccessRights parameter would accept only
ChangePermissions, TakeOwnership and AccessSystemSecurity, not ReadPermissions.

The readback must report the expected owner and a present, non-null, protected,
canonical DACL with one effective ordinary owner Allow FullControl ACE. A raw
view of the **Framework-normalized descriptor** checks ACE type, SID, mask,
flags and callback/opaque fields rather than using AccessRule projection alone.
This is deliberately not a claim about the original native descriptor's exact
ACE count or flags. Framework [CommonAcl normalization](https://raw.githubusercontent.com/microsoft/referencesource/refs/heads/main/mscorlib/system/security/accesscontrol/acl.cs)
can remove irrelevant leaf inheritance flags, omit ineffective entries and merge
compatible owner entries. Positive normalization controls document that limit.
Callback ACEs retain their distinct type and opaque data and are rejected.
Null/absent DACL fixtures both fail the policy, but their native distinction is
not claimed to survive Framework serialization.

Any creation, readback or validation failure disposes only the retained pipe and
throws a security-specific failure outside the existing IOException retry loop.
The service cannot retry with default security or accept requests after that
failure. Existing byte-exact owned lock cleanup then runs. Lock publication and
matching-PID startup detection retain their timing: a lock can briefly precede
a later fatal ACL failure. A matching lock remains neither readiness proof nor
authenticated identity.

The user-visible correction is deliberate: a helper that cannot enforce its
intended owner policy now exits instead of running with accidental default
access. Other principals lose those accidental read grants. The six action
schemas, framing, detached lifetime, and owner/lock/client guards are unchanged.
The availability/privacy tradeoff requires compatibility review; it is not
parity with the old fail-soft path.

## Bounded evidence and tests

Opt-in --diagnostic-acl emits at most 16 descriptor records and a limit marker.
Records contain expected user SID, owner/group, normalized ACE details and SDDL,
with an explicit framework-normalized-descriptor label. No request, UI or image
content is recorded. Existing raw subprocess evidence is retained before
assertions.

The owned probe inspects the old constructor, then the actual candidate
creation-time descriptor. Twenty-seven checks cover missing/wrong owner,
unprotected/absent/null/empty DACL, Everyone/Anonymous, deny/wrong-mask/inherited
and callback ACEs, and the two normalization controls. Adversarial descriptors
exist only in memory. A colliding newly owned instance must fail closed. An
injected post-creation error must close its retained handle without retry; a
subsequent first-instance creation proves that handle was released. Actual
same-user health/shutdown also checks every emitted descriptor and requires the
old fail-soft warning to be absent. Existing transport/cleanup tests remain.

These tests establish only construction, normalized readback and the fixture's
same-token/same-user path when Windows runs them. A user-SID DACL does not isolate
sessions, identify one particular same-user wrapper, or reject an authenticated
remote SMB caller carrying that SID. Matching SID alone also does not prove
cross-elevation compatibility: [mandatory integrity controls](https://learn.microsoft.com/en-us/windows/win32/secauthz/mandatory-integrity-control)
can independently deny access. Cross-user, anonymous, SMB, cross-session and
cross-integrity behavior remains unqualified. No account creation, impersonation,
token manipulation or real desktop acquisition is included. A local-only policy
such as PIPE_REJECT_REMOTE_CLIENTS needs a separate explicit compatibility
decision and implementation.

The prior [repair run 37099034933](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/37099034933)
passed all 18 service/transport methods. Its controls support eager-preamble
blocking on that runner: default-buffer eager peers stop before reading;
deferred writers, explicit 512-byte buffers and a BOM-draining client complete.
That diagnosis is separate from ACL qualification. Working transport does not
qualify the old access policy or this new creation-time correction.

Local validation on Linux passed the net48 service/probe build with zero warnings,
117 action and 45 wire contracts, 52 helper Python checks and five raw-evidence
checks. Full Python discovery passed 710 tests (562 executed, 148 gated skips).
The helper suite has 22 unrun Windows methods, including the new method containing
all 27 ACL checks. Those ACL runtime checks have only compiled locally; no
Windows policy/readback/access outcome is claimed. SDK 10.0.401/runtime 10.0.12
used Major roll-forward for the net8-targeted portable contracts. Canonical
PowerShell remains 902,990 bytes on this isolated base, unchanged by this patch.
The independently prepared oracle extent repair may change that combined count;
this ACL patch adds zero PowerShell bytes and no retirement credit.

## Subsequent owned Windows qualification

[Run 37103413691](https://github.com/bagseunggwon30-cyber/Computer-Use-Control-Plane/actions/runs/37103413691)
at published commit `fa1c830e1142b89388551b9577f89dd46138d27f` passed
the owned ACL probe's 27 checks and all service/transport methods. The retained
`owned-acl-contracts-ace7704b1941` process record has exit 0, 1,832 stdout bytes,
empty stderr, complete drains, and no timeout, launch error or truncation. The
downloaded artifact archive SHA-256 is
`c1ae8ec8771746424f5cba71ded90189fc52f55a6b5cbe6f33063dc3984b46c6`.

On that runner, the old constructor's normalized readback had an unprotected DACL
with Everyone and Anonymous read ACEs. The candidate's readback had the current
user as owner, a protected canonical DACL, and exactly one ordinary current-user
FullControl ACE. This observes the creation policy and same-user owned fixture
path. It does not establish cross-principal, session, integrity or SMB behavior.
The whole helper run remained failed because of the separate action-oracle
argument-binding and empty-trace cardinality assertions; those failures do not
erase the successful owned ACL evidence or qualify action parity.
