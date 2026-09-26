using System.Diagnostics;
using System.Text;

internal static class WindowEnumerator
{
    public static NativeResult Observe(CommandOptions options)
    {
        options.Allow();
        var windows = new List<object>();
        var errors = new List<NativeError>();
        if (!NativeMethods.EnumWindows((hwnd, _) =>
        {
            if (!NativeMethods.IsWindowVisible(hwnd)) return true;
            var length = NativeMethods.GetWindowTextLength(hwnd);
            if (length <= 0) return true;
            var title = new StringBuilder(Math.Min(length + 1, 32768));
            NativeMethods.GetWindowText(hwnd, title, title.Capacity);
            NativeMethods.GetWindowThreadProcessId(hwnd, out var pid);
            string processName;
            try { using var process = Process.GetProcessById((int)pid); processName = process.ProcessName; }
            catch (Exception ex) when (ex is ArgumentException or InvalidOperationException or System.ComponentModel.Win32Exception)
            {
                processName = string.Empty;
                if (errors.Count < 20) errors.Add(new NativeError("process_metadata_unavailable", $"PID {pid}: {ex.Message}"));
            }
            PixelRect? geometry = NativeMethods.GetWindowRect(hwnd, out var rect) ? new PixelRect(rect.Left, rect.Top, rect.Right - rect.Left, rect.Bottom - rect.Top) : null;
            windows.Add(new
            {
                hwnd = NativeMethods.HwndString(hwnd), title = title.ToString(), process_name = processName, process_id = (int)pid,
                visible = true, minimized = NativeMethods.IsIconic(hwnd), foreground = NativeMethods.GetForegroundWindow() == hwnd, geometry
            });
            return true;
        }, IntPtr.Zero)) throw new NativeFailure("enumeration_failed", "Window enumeration failed.");
        return NativeResult.Observation("windows", new { windows, count = windows.Count }, errors);
    }
}
