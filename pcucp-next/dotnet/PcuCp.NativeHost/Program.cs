using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;

var command = args.Length > 0 ? args[0].Trim().ToLowerInvariant() : "version";
var options = new JsonSerializerOptions { WriteIndented = true };

switch (command)
{
    case "version":
        Console.WriteLine(JsonSerializer.Serialize(NativeVersion.Create(), options));
        return 0;
    case "windows":
        Console.WriteLine(JsonSerializer.Serialize(WindowEnumerator.Observe(), options));
        return 0;
    default:
        Console.Error.WriteLine($"unknown native host command: {command}");
        return 2;
}

internal static class NativeVersion
{
    public static object Create() => new
    {
        schema = "pcucp.native.version/v1",
        status = "ok",
        component = "PcuCp.NativeHost",
        runtime = RuntimeInformation.FrameworkDescription,
        os = RuntimeInformation.OSDescription,
        process = Environment.ProcessId
    };
}

internal sealed record WindowInfo(
    string Hwnd,
    string Title,
    string ProcessName,
    int ProcessId,
    bool Visible
);

internal static class WindowEnumerator
{
    public static object Observe()
    {
        if (!OperatingSystem.IsWindows())
        {
            return new
            {
                schema = "pcucp.observation/v1",
                status = "error",
                kind = "windows",
                data = new { windows = Array.Empty<WindowInfo>() },
                errors = new[] { "PcuCp.NativeHost window enumeration requires Windows." }
            };
        }

        var windows = new List<WindowInfo>();
        EnumWindows((hwnd, _) =>
        {
            var visible = IsWindowVisible(hwnd);
            var title = GetWindowTitle(hwnd);
            if (!visible || string.IsNullOrWhiteSpace(title))
            {
                return true;
            }

            GetWindowThreadProcessId(hwnd, out var pid);
            windows.Add(new WindowInfo(
                $"0x{hwnd.ToInt64():X}",
                title,
                GetProcessName(pid),
                (int)pid,
                visible
            ));
            return true;
        }, IntPtr.Zero);

        return new
        {
            schema = "pcucp.observation/v1",
            status = "ok",
            kind = "windows",
            data = new
            {
                windows,
                count = windows.Count
            },
            errors = Array.Empty<string>()
        };
    }

    private static string GetWindowTitle(IntPtr hwnd)
    {
        var length = GetWindowTextLength(hwnd);
        if (length <= 0)
        {
            return string.Empty;
        }

        var builder = new StringBuilder(length + 1);
        _ = GetWindowText(hwnd, builder, builder.Capacity);
        return builder.ToString();
    }

    private static string GetProcessName(uint pid)
    {
        try
        {
            using var process = Process.GetProcessById((int)pid);
            return process.ProcessName;
        }
        catch
        {
            return string.Empty;
        }
    }

    private delegate bool EnumWindowsProc(IntPtr hwnd, IntPtr lParam);

    [DllImport("user32.dll")]
    private static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);

    [DllImport("user32.dll")]
    private static extern bool IsWindowVisible(IntPtr hWnd);

    [DllImport("user32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    private static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);

    [DllImport("user32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    private static extern int GetWindowTextLength(IntPtr hWnd);

    [DllImport("user32.dll")]
    private static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);
}
