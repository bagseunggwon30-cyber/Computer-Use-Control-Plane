using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;

internal sealed record AppLaunchSpec(string Path, IReadOnlyList<string> Arguments)
{
    internal const int MaxArguments = 128;
    internal const int MaxCommandLineLength = 32766; // CreateProcessW includes the terminating NUL in its 32767 limit.

    internal static AppLaunchSpec Read(CommandOptions options, Func<string, bool> fileExists)
    {
        var path = options.Required("--path");
        if (!IsAbsoluteExecutablePath(path))
            throw CommandOptions.Invalid("--path must be an absolute drive or UNC path to an .exe file; names, URLs, scripts and device paths are unsupported.");
        var arguments = new List<string>();
        if (options.Has("--args-b64"))
        {
            try
            {
                var encoded = options.Required("--args-b64");
                if (encoded.Length > 65536) throw CommandOptions.Invalid("Encoded arguments exceed the launch limit.");
                var text = new UTF8Encoding(false, true).GetString(Convert.FromBase64String(encoded));
                using var document = JsonDocument.Parse(text, new JsonDocumentOptions { MaxDepth = 2 });
                if (document.RootElement.ValueKind != JsonValueKind.Array || document.RootElement.GetArrayLength() > MaxArguments)
                    throw CommandOptions.Invalid($"--args-b64 must encode a JSON array of at most {MaxArguments} strings.");
                foreach (var element in document.RootElement.EnumerateArray())
                {
                    if (element.ValueKind != JsonValueKind.String) throw CommandOptions.Invalid("Each launch argument must be a string.");
                    var value = element.GetString()!;
                    if (value.Length > 8192 || value.Contains('\0')) throw CommandOptions.Invalid("Each launch argument must contain at most 8192 UTF-16 units without NUL.");
                    arguments.Add(value);
                }
            }
            catch (Exception ex) when (ex is FormatException or DecoderFallbackException or JsonException or InvalidOperationException)
            {
                throw CommandOptions.Invalid("--args-b64 must contain base64-encoded UTF-8 JSON string-array data.");
            }
        }
        var spec = new AppLaunchSpec(path, arguments);
        if (spec.CommandLine().Length > MaxCommandLineLength) throw CommandOptions.Invalid("The encoded Windows command line exceeds 32766 UTF-16 units.");
        if (!fileExists(path)) throw new NativeFailure("executable_not_found", "The specified executable file does not exist or is inaccessible.");
        return spec;
    }

    // Explicit Windows path validation is platform-independent so contract tests never need to launch an app.
    internal static bool IsAbsoluteExecutablePath(string path)
    {
        if (path.Length is < 4 or > MaxCommandLineLength || !path.EndsWith(".exe", StringComparison.OrdinalIgnoreCase) ||
            path.Any(c => c < ' ' || c is '"' or '<' or '>' or '|' or '*' or '?')) return false;
        if (path.Length >= 3 && char.IsAsciiLetter(path[0]) && path[1] == ':' && path[2] is '\\' or '/')
            return !path[2..].Contains(':');
        if (!path.StartsWith("\\\\", StringComparison.Ordinal) || path.StartsWith("\\\\.\\", StringComparison.Ordinal) || path.Contains(':')) return false;
        var parts = path[2..].Split(['\\', '/']);
        return parts.Length >= 3 && parts.All(part => !string.IsNullOrEmpty(part)) && parts[0] is not ("." or "..");
    }

    internal string CommandLine() => string.Join(" ", new[] { Path }.Concat(Arguments).Select(QuoteArgument));

    // Standard Windows argv escaping: only backslashes before a quote or the final quote are doubled.
    // The explicit applicationName supplied to CreateProcessW never undergoes executable-name search.
    internal static string QuoteArgument(string value)
    {
        var result = new StringBuilder("\"");
        var slashes = 0;
        foreach (var ch in value)
        {
            if (ch == '\\') { slashes++; continue; }
            result.Append('\\', ch == '"' ? slashes * 2 + 1 : slashes);
            result.Append(ch);
            slashes = 0;
        }
        return result.Append('\\', slashes * 2).Append('"').ToString();
    }
}

internal interface IAppCloseTarget
{
    object Identity { get; }
    void RequireAccess();
    void RequestClose();
    bool IsOpen { get; }
}

internal interface IAppLifecyclePlatform
{
    bool FileExists(string path);
    void RequireLaunchAccess();
    int Launch(AppLaunchSpec spec);
    IAppCloseTarget ReadCloseTarget(CommandOptions options);
    long ElapsedMilliseconds { get; }
    Task DelayAsync(int milliseconds);
}

internal static class AppLifecycleActions
{
    internal static async Task<NativeResult> ExecuteAsync(string command, CommandOptions options, IAppLifecyclePlatform? platform = null)
    {
        if (command == "app-launch") options.Allow("--path", "--args-b64", "--allow-live-control");
        else if (command == "app-close") options.Allow("--hwnd", "--pid", "--timeout-ms", "--allow-live-control",
            "--expected-x", "--expected-y", "--expected-width", "--expected-height");
        else throw CommandOptions.Invalid("Unsupported app lifecycle command.");
        if (!options.Has("--allow-live-control")) throw new NativeFailure("live_control_required", "App lifecycle operations require --allow-live-control.");
        platform ??= new WindowsAppLifecyclePlatform();
        if (command == "app-launch")
        {
            var spec = AppLaunchSpec.Read(options, platform.FileExists);
            platform.RequireLaunchAccess();
            var pid = platform.Launch(spec);
            return NativeResult.Ok(command, new
            {
                path = spec.Path, pid, dispatched = true, verification = "not_verified",
                note = "Process creation succeeded. Observe windows to identify the application; startup, a visible window and application readiness are not confirmed."
            });
        }
        var timeout = options.Integer("--timeout-ms", 1500, 0, 10000);
        // Reject missing/malformed selectors before platform access or posting any message.
        _ = WindowTarget.ParseHwnd(options.Required("--hwnd"));
        _ = options.RequiredInteger("--pid", 1);
        var target = platform.ReadCloseTarget(options);
        target.RequireAccess();
        target.RequestClose();
        var start = platform.ElapsedMilliseconds;
        var open = target.IsOpen;
        while (open)
        {
            var remaining = timeout - (platform.ElapsedMilliseconds - start);
            if (remaining <= 0) break;
            await platform.DelayAsync((int)Math.Min(50, remaining));
            open = target.IsOpen;
        }
        return NativeResult.Observation(command, new
        {
            target = target.Identity, dispatched = true, closed = !open, still_open = open,
            verification = open ? "not_verified" : "window_closed", close_method = "wm_close", timeout_ms = timeout,
            note = open
                ? "The target window is still open. It may be waiting for confirmation, refusing to close or busy. No force termination was attempted; observe before taking another action."
                : "The selected HWND/PID is no longer present. This does not establish process exit or closure of the application's other windows."
        }, open ? [new NativeError("app_still_open", "The target window remained open at the close deadline.")] : []);
    }
}

internal sealed class WindowsAppLifecyclePlatform : IAppLifecyclePlatform
{
    private readonly Stopwatch clock = Stopwatch.StartNew();
    public bool FileExists(string path) => File.Exists(path);
    public void RequireLaunchAccess() => PrivilegeInspector.RequireInputAccess(Environment.ProcessId);
    public long ElapsedMilliseconds => clock.ElapsedMilliseconds;
    public Task DelayAsync(int milliseconds) => Task.Delay(milliseconds);
    public IAppCloseTarget ReadCloseTarget(CommandOptions options) => new WindowsAppCloseTarget(WindowTarget.Read(options, true));

    public int Launch(AppLaunchSpec spec)
    {
        PrivilegeInspector.RequireDefaultDesktop();
        var startup = new NativeMethods.STARTUPINFO { Size = Marshal.SizeOf<NativeMethods.STARTUPINFO>() };
        // A separate console (for console executables only) plus no handle inheritance prevents a
        // launched app from consuming requests or corrupting the native host's JSONL stdout/stderr.
        // Neither a shell, PATH search, an elevation verb nor a parent-owned redirected pipe is used.
        if (!NativeMethods.CreateProcess(spec.Path, new StringBuilder(spec.CommandLine()), IntPtr.Zero, IntPtr.Zero,
                false, 0x00000010, IntPtr.Zero, null, ref startup, out var process))
        {
            var error = Marshal.GetLastWin32Error();
            throw new NativeFailure(error == 740 ? "elevation_required" : "launch_failed",
                $"Process creation failed (Win32 {error}: {new Win32Exception(error).Message}). No automatic elevation or shell fallback was attempted.");
        }
        try { return checked((int)process.ProcessId); }
        finally
        {
            NativeMethods.CloseHandle(process.Thread);
            NativeMethods.CloseHandle(process.Process);
        }
    }

    private sealed class WindowsAppCloseTarget(WindowTarget target) : IAppCloseTarget
    {
        public object Identity => target.Identity;
        public void RequireAccess() => PrivilegeInspector.RequireInputAccess(target.Pid);
        public void RequestClose()
        {
            PrivilegeInspector.RequireDefaultDesktop();
            target.Validate(false); // WM_CLOSE is targeted, so no focus changes or global keyboard input are needed.
            if (!NativeMethods.PostMessage(target.Hwnd, 0x0010, UIntPtr.Zero, IntPtr.Zero))
                throw new NativeFailure("close_dispatch_failed", $"Unable to queue WM_CLOSE (Win32 {Marshal.GetLastWin32Error()}). Observe the target before retrying.");
        }
        public bool IsOpen
        {
            get
            {
                if (!NativeMethods.IsWindow(target.Hwnd)) return false;
                NativeMethods.GetWindowThreadProcessId(target.Hwnd, out var pid);
                return pid == (uint)target.Pid;
            }
        }
    }
}
