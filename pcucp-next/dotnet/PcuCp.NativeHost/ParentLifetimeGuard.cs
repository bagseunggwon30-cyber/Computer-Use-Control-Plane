using System.Globalization;
using System.Runtime.InteropServices;

/// <summary>Watch the inherited parent kernel handle, never a reusable PID or app tree.</summary>
internal static class ParentLifetimeGuard
{
    [DllImport("kernel32.dll", SetLastError = true)] private static extern uint WaitForSingleObject(IntPtr handle, uint milliseconds);
    [DllImport("kernel32.dll", SetLastError = true)] private static extern bool CloseHandle(IntPtr handle);

    internal static (string[] Args, IntPtr Handle) Extract(string[] args)
    {
        var clean = new List<string>();
        var handle = IntPtr.Zero;
        for (var i = 0; i < args.Length; i++)
        {
            if (!string.Equals(args[i], "--parent-handle", StringComparison.OrdinalIgnoreCase)) { clean.Add(args[i]); continue; }
            if (handle != IntPtr.Zero || ++i >= args.Length ||
                !long.TryParse(args[i], NumberStyles.None, CultureInfo.InvariantCulture, out var value) || value <= 0 ||
                (IntPtr.Size == 4 && value > int.MaxValue))
                throw CommandOptions.Invalid("Invalid or repeated parent-liveness handle.");
            handle = new IntPtr(value);
        }
        return (clean.ToArray(), handle);
    }

    internal static void Start(IntPtr handle)
    {
        if (handle == IntPtr.Zero) return; // Direct CLI may run without a Python parent.
        if (!OperatingSystem.IsWindows()) throw CommandOptions.Invalid("Parent handles require Windows.");
        // WAIT_TIMEOUT proves this waitable object is still alive. Invalid/closed
        // handles and an already-dead parent fail before dispatch, closing launch races.
        if (WaitForSingleObject(handle, 0) != 258)
            throw new NativeFailure("parent_guard_failed", "Parent handle is invalid or parent already exited.");
        var watcher = new Thread(() =>
        {
            WaitForSingleObject(handle, uint.MaxValue);
            CloseHandle(handle);
            // Fail closed on parent exit OR wait failure. Terminate only ourselves;
            // user apps have no kill-on-close job and never inherit our handles.
            Environment.Exit(125);
        }) { IsBackground = true, Name = "native-parent-liveness" };
        watcher.Start();
    }
}
