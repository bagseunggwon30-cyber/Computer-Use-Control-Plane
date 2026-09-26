using System.Runtime.InteropServices;
using System.Text;

internal sealed record ProcessPrivileges(int Pid, bool IsElevated, int IntegrityRid, string IntegrityLevel, bool UiAccess);
internal static class PrivilegeInspector
{
    [DllImport("kernel32.dll", SetLastError = true)] private static extern IntPtr OpenProcess(uint access, bool inherit, int pid);
    [DllImport("kernel32.dll")] private static extern bool CloseHandle(IntPtr handle);
    [DllImport("advapi32.dll", SetLastError = true)] private static extern bool OpenProcessToken(IntPtr process, uint access, out IntPtr token);
    [DllImport("advapi32.dll", SetLastError = true)] private static extern bool GetTokenInformation(IntPtr token, int infoClass, IntPtr buffer, int length, out int returned);
    [DllImport("advapi32.dll")] private static extern IntPtr GetSidSubAuthorityCount(IntPtr sid);
    [DllImport("advapi32.dll")] private static extern IntPtr GetSidSubAuthority(IntPtr sid, uint index);
    [DllImport("user32.dll", SetLastError = true)] private static extern IntPtr OpenInputDesktop(uint flags, bool inherit, uint access);
    [DllImport("user32.dll")] private static extern bool CloseDesktop(IntPtr desktop);
    [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)] private static extern bool GetUserObjectInformation(IntPtr obj, int index, StringBuilder information, int length, out int needed);

    public static NativeResult Observe(CommandOptions options)
    {
        options.Allow("--pid");
        var current = Read(Environment.ProcessId);
        ProcessPrivileges? target = null;
        var errors = new List<NativeError>();
        if (options.Has("--pid"))
        {
            try { target = Read(options.RequiredInteger("--pid", 1)); }
            catch (NativeFailure ex) { errors.Add(new NativeError(ex.Code, ex.Message)); }
        }
        string? desktop = null;
        try { desktop = InputDesktopName(); }
        catch (NativeFailure ex) { errors.Add(new NativeError(ex.Code, ex.Message)); }
        return NativeResult.Observation("privileges", new
        {
            current, target, target_access = target is null ? "unknown" : AccessStatus(current, target),
            input_desktop = desktop, desktop_available = desktop == "Default",
            limitation = "Integrity comparison is a preflight check, not a guarantee of input acceptance. UAC secure desktop and protected processes are unsupported."
        }, errors);
    }

    public static void RequireInputAccess(int pid)
    {
        RequireDefaultDesktop();
        var current = Read(Environment.ProcessId);
        var target = Read(pid);
        var access = AccessStatus(current, target);
        if (access == "unsupported_protected_target")
            throw new NativeFailure("unsupported_protected_target", "SYSTEM and protected-integrity processes are outside the supported desktop-control scope.");
        if (access == "elevation_required")
            throw new NativeFailure("elevation_required", "Target has higher integrity. Start the approved CUCP/Pi session as administrator through the normal Windows UAC prompt, then observe again.");
    }

    internal static string AccessStatus(ProcessPrivileges current, ProcessPrivileges target) =>
        target.IntegrityRid >= 0x4000 ? "unsupported_protected_target" :
        current.UiAccess || current.IntegrityRid >= target.IntegrityRid ? "integrity_check_passed" : "elevation_required";

    public static void RequireDefaultDesktop()
    {
        if (!string.Equals(InputDesktopName(), "Default", StringComparison.OrdinalIgnoreCase))
            throw new NativeFailure("secure_desktop_unavailable", "Only the interactive Default desktop is supported. UAC secure desktop cannot be automated.");
    }

    private static string InputDesktopName()
    {
        var desktop = OpenInputDesktop(0, false, 0x0001); // DESKTOP_READOBJECTS only; never switch desktops.
        if (desktop == IntPtr.Zero) throw new NativeFailure("secure_desktop_unavailable", "Cannot inspect the interactive input desktop.");
        try
        {
            var text = new StringBuilder(256);
            if (!GetUserObjectInformation(desktop, 2, text, text.Capacity * 2, out _))
                throw new NativeFailure("secure_desktop_unavailable", "Cannot identify the input desktop.");
            return text.ToString();
        }
        finally { CloseDesktop(desktop); }
    }

    private static ProcessPrivileges Read(int pid)
    {
        var process = OpenProcess(0x1000, false, pid); // PROCESS_QUERY_LIMITED_INFORMATION
        if (process == IntPtr.Zero) throw new NativeFailure("privilege_unknown", $"Cannot inspect process {pid} privileges (Win32 {Marshal.GetLastWin32Error()}).");
        IntPtr token = IntPtr.Zero;
        try
        {
            if (!OpenProcessToken(process, 0x0008, out token))
                throw new NativeFailure("privilege_unknown", $"Cannot inspect process {pid} token (Win32 {Marshal.GetLastWin32Error()}).");
            var elevated = ReadInt(token, 20) != 0;
            var uiAccess = ReadInt(token, 26) != 0;
            _ = GetTokenInformation(token, 25, IntPtr.Zero, 0, out var size);
            if (size <= 0 || size > 65536) throw new NativeFailure("privilege_unknown", "Invalid token integrity information.");
            var buffer = Marshal.AllocHGlobal(size);
            int rid;
            try
            {
                if (!GetTokenInformation(token, 25, buffer, size, out _)) throw new NativeFailure("privilege_unknown", "Unable to query token integrity.");
                var sid = Marshal.ReadIntPtr(buffer);
                var count = Marshal.ReadByte(GetSidSubAuthorityCount(sid));
                if (count == 0) throw new NativeFailure("privilege_unknown", "Token has no integrity authority.");
                rid = Marshal.ReadInt32(GetSidSubAuthority(sid, (uint)(count - 1)));
            }
            finally { Marshal.FreeHGlobal(buffer); }
            var level = rid switch { < 0x1000 => "untrusted", < 0x2000 => "low", < 0x3000 => "medium", < 0x4000 => "high", < 0x5000 => "system", _ => "protected" };
            return new ProcessPrivileges(pid, elevated, rid, level, uiAccess);
        }
        finally
        {
            if (token != IntPtr.Zero) CloseHandle(token);
            CloseHandle(process);
        }
    }

    private static int ReadInt(IntPtr token, int informationClass)
    {
        var buffer = Marshal.AllocHGlobal(4);
        try
        {
            if (!GetTokenInformation(token, informationClass, buffer, 4, out _)) throw new NativeFailure("privilege_unknown", "Unable to inspect token properties.");
            return Marshal.ReadInt32(buffer);
        }
        finally { Marshal.FreeHGlobal(buffer); }
    }
}
