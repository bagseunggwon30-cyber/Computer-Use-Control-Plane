using System;
using System.Collections.Generic;
using System.IO.Pipes;
using System.Security.AccessControl;
using System.Security.Principal;

namespace PcuCp.LegacyHelper
{
    public sealed class LegacyHelperPipeSecurityException : InvalidOperationException
    {
        public LegacyHelperPipeSecurityException(string message, Exception inner = null) : base(message, inner) { }
    }

    // The original post-creation SetAccessControl call needs WRITE_DAC, which
    // its default duplex handle lacks. Supply the DACL at creation instead of
    // adding mutation rights or exposing an initial default-DACL interval.
    public static class LegacyHelperPipeSecurity
    {
        public static PipeSecurity OwnerOnlyDescriptor(SecurityIdentifier owner)
        {
            if (owner == null) throw new LegacyHelperPipeSecurityException("current user SID is required");
            var security = new PipeSecurity();
            security.SetOwner(owner);
            security.SetAccessRuleProtection(true, false);
            security.AddAccessRule(new PipeAccessRule(owner, PipeAccessRights.FullControl, AccessControlType.Allow));
            ValidateDescriptor(security, owner);
            return security;
        }

        public static void ValidateDescriptor(PipeSecurity security, SecurityIdentifier owner)
        {
            if (security == null || owner == null) throw new LegacyHelperPipeSecurityException("pipe security evidence is missing");
            var raw = new RawSecurityDescriptor(security.GetSecurityDescriptorBinaryForm(), 0);
            if (raw.Owner == null || !raw.Owner.Equals(owner))
                throw new LegacyHelperPipeSecurityException("pipe descriptor owner differs from current user SID");
            if ((raw.ControlFlags & ControlFlags.DiscretionaryAclPresent) == 0 || raw.DiscretionaryAcl == null ||
                (raw.ControlFlags & ControlFlags.DiscretionaryAclProtected) == 0 || !security.AreAccessRulesCanonical)
                throw new LegacyHelperPipeSecurityException("pipe DACL must be present, protected and canonical");
            if (raw.DiscretionaryAcl.Count != 1)
                throw new LegacyHelperPipeSecurityException("pipe DACL must contain exactly one current-user ACE");
            var ace = raw.DiscretionaryAcl[0] as CommonAce;
            // GetAccessRules can conceal callback/opaque ACE distinctions.
            // This raw view is AFTER Framework normalization (which can strip
            // ineffective inheritance flags or merge compatible owner ACEs).
            // It is an effective normalized policy, not native-byte evidence.
            if (ace == null || ace.AceType != AceType.AccessAllowed || ace.IsCallback || ace.OpaqueLength != 0 ||
                ace.AceFlags != AceFlags.None || !ace.SecurityIdentifier.Equals(owner) ||
                ace.AccessMask != (int)PipeAccessRights.FullControl)
                throw new LegacyHelperPipeSecurityException("pipe DACL is not the exact current-user full-control policy");
        }

        public static NamedPipeServerStream Create(string name, SecurityIdentifier owner, Action<Dictionary<string, object>> evidence = null)
        {
            NamedPipeServerStream pipe = null;
            try
            {
                SecurityIdentifier current;
                using (var identity = WindowsIdentity.GetCurrent()) current = identity.User;
                if (owner == null || current == null || !owner.Equals(current))
                    throw new LegacyHelperPipeSecurityException("pipe SID must be the current process user");
                var security = OwnerOnlyDescriptor(owner);
                // Default duplex rights include READ_CONTROL for readback.
                // No ChangePermissions, TakeOwnership or SACL right is added.
                pipe = new NamedPipeServerStream(name, PipeDirection.InOut, 1,
                    PipeTransmissionMode.Byte, PipeOptions.Asynchronous, 0, 0, security);
                PipeSecurity actual = pipe.GetAccessControl();
                ValidateDescriptor(actual, owner);
                if (evidence != null) evidence(Describe(actual, owner));
                return pipe;
            }
            catch (Exception error)
            {
                Exception cleanupError = null;
                try { if (pipe != null) pipe.Dispose(); }
                catch (Exception failure) { cleanupError = failure; }
                // Deliberately not IOException: the service's recoverable I/O
                // loop must never retry or accept clients after an ACL failure.
                string detail = error.GetType().Name + " (0x" + error.HResult.ToString("x8") + "): " + error.Message;
                if (cleanupError != null) detail += "; owned pipe cleanup failed: " + cleanupError.GetType().Name;
                throw new LegacyHelperPipeSecurityException("owner-only pipe creation or verification failed: " + detail, error);
            }
        }

        // Read-only descriptor evidence. No SID translation, token creation,
        // account lookup, impersonation, or access-control mutation occurs here.
        public static Dictionary<string, object> Describe(PipeSecurity security, SecurityIdentifier expectedOwner)
        {
            var raw = new RawSecurityDescriptor(security.GetSecurityDescriptorBinaryForm(), 0);
            var rules = new List<object>();
            if (raw.DiscretionaryAcl != null)
            {
                if (raw.DiscretionaryAcl.Count > 64) throw new LegacyHelperPipeSecurityException("owned ACL evidence exceeds ACE bound");
                foreach (GenericAce entry in raw.DiscretionaryAcl)
                {
                    var common = entry as CommonAce;
                    rules.Add(new Dictionary<string, object> {
                        ["type"] = entry.AceType.ToString(), ["flags"] = entry.AceFlags.ToString(),
                        ["sid"] = common == null ? null : common.SecurityIdentifier.Value,
                        ["mask"] = common == null ? (object)null : common.AccessMask,
                        ["callback"] = common == null ? (object)null : common.IsCallback,
                        ["opaque_bytes"] = common == null ? (object)null : common.OpaqueLength
                    });
                }
            }
            return new Dictionary<string, object> {
                ["schema"] = "cucp.owned-pipe-acl/v1", ["evidence_kind"] = "framework-normalized-descriptor",
                ["expected_user_sid"] = expectedOwner == null ? null : expectedOwner.Value,
                ["owner_sid"] = raw.Owner == null ? null : raw.Owner.Value,
                ["group_sid"] = raw.Group == null ? null : raw.Group.Value,
                ["dacl_present"] = (raw.ControlFlags & ControlFlags.DiscretionaryAclPresent) != 0,
                ["dacl_null"] = raw.DiscretionaryAcl == null,
                ["protected"] = security.AreAccessRulesProtected, ["canonical"] = security.AreAccessRulesCanonical,
                ["sddl"] = security.GetSecurityDescriptorSddlForm(AccessControlSections.Access | AccessControlSections.Owner | AccessControlSections.Group),
                ["aces"] = rules
            };
        }
    }
}
