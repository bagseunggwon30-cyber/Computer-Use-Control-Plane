using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Pipes;
using System.Security.AccessControl;
using System.Security.Principal;
using PcuCp.LegacyHelper;

// Only this process's newly created pipes and in-memory descriptors. No account,
// token, impersonation, privilege, persistent grant or real desktop operation.
internal static class OwnedPipeAclProbe
{
    private static int checks;
    private static void Check(bool condition, string name)
    { if (!condition) throw new InvalidOperationException("owned ACL contract failed: " + name); checks++; }
    private static void Reject(Action action, string name)
    {
        try { action(); }
        catch (LegacyHelperPipeSecurityException) { checks++; return; }
        throw new InvalidOperationException("owned ACL policy unexpectedly accepted: " + name);
    }

    public static int Run()
    {
        SecurityIdentifier user;
        using (var identity = WindowsIdentity.GetCurrent()) user = identity.User;
        if (user == null) throw new InvalidOperationException("owned fixture user SID unavailable");
        var everyone = new SecurityIdentifier(WellKnownSidType.WorldSid, null);
        var anonymous = new SecurityIdentifier(WellKnownSidType.AnonymousSid, null);
        string name = "cucp-helper-" + Process.GetCurrentProcess().Id;
        var observations = new List<object>();

        // Inspect the old constructor's effective policy without modifying it
        // and without waiting for or accepting any client connection.
        using (var pipe = new NamedPipeServerStream(name, PipeDirection.InOut, 1,
            PipeTransmissionMode.Byte, PipeOptions.Asynchronous))
        {
            var observed = LegacyHelperPipeSecurity.Describe(pipe.GetAccessControl(), user);
            observed["kind"] = "legacy_default_read_only";
            observations.Add(observed);
        }

        var valid = LegacyHelperPipeSecurity.OwnerOnlyDescriptor(user);
        LegacyHelperPipeSecurity.ValidateDescriptor(valid, user);
        checks++;
        Reject(() => LegacyHelperPipeSecurity.OwnerOnlyDescriptor(null), "missing user SID");
        Reject(() => LegacyHelperPipeSecurity.ValidateDescriptor(null, user), "missing descriptor");
        Reject(() => LegacyHelperPipeSecurity.ValidateDescriptor(valid, null), "missing expected SID");
        Reject(() => LegacyHelperPipeSecurity.ValidateDescriptor(valid, everyone), "wrong expected user SID");
        Reject(() => LegacyHelperPipeSecurity.Create(name, everyone), "foreign live owner rejected before creation");

        // All adversarial ACLs below exist only in memory, never on a pipe.
        ValidateRejected(user, everyone, true, true, Ace(user), "wrong descriptor owner");
        ValidateRejected(user, null, true, true, Ace(user), "missing descriptor owner");
        ValidateRejected(user, user, false, true, Ace(user), "unprotected DACL");
        ValidateRejected(user, user, true, false, null, "absent DACL");
        ValidateRejected(user, user, true, true, null, "null DACL");
        ValidateRejected(user, user, true, true, new GenericAce[0], "empty DACL");
        ValidateRejected(user, user, true, true, new[] { Ace(user)[0], Ace(everyone)[0] }, "extra Everyone principal");
        ValidateRejected(user, user, true, true, Ace(anonymous), "Anonymous instead of current user");
        ValidateRejected(user, user, true, true, new[] { new CommonAce(AceFlags.None, AceQualifier.AccessDenied,
            (int)PipeAccessRights.FullControl, user, false, null) }, "deny ACE");
        ValidateRejected(user, user, true, true, new[] { new CommonAce(AceFlags.None, AceQualifier.AccessAllowed,
            (int)PipeAccessRights.Read, user, false, null) }, "insufficient rights");
        ValidateRejected(user, user, true, true, new[] { new CommonAce(AceFlags.None, AceQualifier.AccessAllowed,
            Int32.MaxValue, user, false, null) }, "unplanned access mask");
        ValidateRejected(user, user, true, true, new[] { new CommonAce(AceFlags.Inherited, AceQualifier.AccessAllowed,
            (int)PipeAccessRights.FullControl, user, false, null) }, "inherited ACE");
        ValidateRejected(user, user, true, true, new[] { new CommonAce(AceFlags.None, AceQualifier.AccessAllowed,
            (int)PipeAccessRights.FullControl, user, true, new byte[4]) }, "callback ACE cannot look ordinary");

        // PipeSecurity normalizes leaf-object flags and duplicate compatible
        // ACEs. These are positive controls on the evidence boundary, not claims
        // that the original native descriptor had one ACE with no flags.
        var inheritedMeaningless = MemoryDescriptor(user, true, true, new[] {
            new CommonAce(AceFlags.ContainerInherit, AceQualifier.AccessAllowed, (int)PipeAccessRights.FullControl, user, false, null)
        });
        LegacyHelperPipeSecurity.ValidateDescriptor(inheritedMeaningless, user); checks++;
        var merged = MemoryDescriptor(user, true, true, new[] { Ace(user)[0], Ace(user)[0] });
        LegacyHelperPipeSecurity.ValidateDescriptor(merged, user); checks++;
        Check(((List<object>)LegacyHelperPipeSecurity.Describe(merged, user)["aces"]).Count == 1,
            "Framework merges compatible owner ACEs before readback validation");

        using (var pipe = LegacyHelperPipeSecurity.Create(name, user))
        {
            var observed = LegacyHelperPipeSecurity.Describe(pipe.GetAccessControl(), user);
            observed["kind"] = "candidate_creation_time_verified";
            observations.Add(observed);
            Check(pipe.IsAsync, "creation preserves asynchronous pipe");
            Reject(() => { using (LegacyHelperPipeSecurity.Create(name, user)) { } }, "existing owned instance fails closed");
        }
        int callbacks = 0;
        Reject(() => LegacyHelperPipeSecurity.Create(name, user, _ => {
            callbacks++; throw new IOException("owned fixture evidence refusal");
        }), "post-creation failure disposes and aborts");
        Check(callbacks == 1, "no retry after post-creation failure");
        // FIRST_PIPE_INSTANCE allows this only if the failed acquisition's
        // retained handle was closed. No client or other process is contacted.
        using (LegacyHelperPipeSecurity.Create(name, user)) checks++;
        Console.Out.WriteLine(LegacyHelperService.NewJson().Serialize(new {
            status = "ok", checks, fixture_pid = Process.GetCurrentProcess().Id,
            current_user_sid = user.Value, full_control_mask = (int)PipeAccessRights.FullControl,
            scope = "owned pipes and in-memory descriptors only", observations,
            normalization_controls = new[] { "ineffective leaf inheritance flags removed", "compatible owner ACEs merged" }
        }));
        return 0;
    }

    private static GenericAce[] Ace(SecurityIdentifier sid)
    { return new GenericAce[] { new CommonAce(AceFlags.None, AceQualifier.AccessAllowed, (int)PipeAccessRights.FullControl, sid, false, null) }; }

    private static void ValidateRejected(SecurityIdentifier expected, SecurityIdentifier owner, bool protect, bool present, GenericAce[] entries, string name)
    { Reject(() => LegacyHelperPipeSecurity.ValidateDescriptor(MemoryDescriptor(owner, protect, present, entries), expected), name); }

    private static PipeSecurity MemoryDescriptor(SecurityIdentifier owner, bool protect, bool present, GenericAce[] entries)
    {
        RawAcl acl = null;
        if (entries != null)
        {
            acl = new RawAcl(GenericAcl.AclRevision, entries.Length);
            for (int i = 0; i < entries.Length; i++) acl.InsertAce(i, entries[i]);
        }
        var flags = ControlFlags.SelfRelative;
        if (protect) flags |= ControlFlags.DiscretionaryAclProtected;
        if (present) flags |= ControlFlags.DiscretionaryAclPresent;
        var raw = new RawSecurityDescriptor(flags, owner, null, null, acl);
        byte[] bytes = new byte[raw.BinaryLength]; raw.GetBinaryForm(bytes, 0);
        var descriptor = new PipeSecurity();
        descriptor.SetSecurityDescriptorBinaryForm(bytes);
        return descriptor;
    }
}
