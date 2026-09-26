using System.Runtime.InteropServices;
using System.Text.Json;

internal static class NativeDispatcher
{
    internal static readonly JsonSerializerOptions JsonOptions = new() { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };
    public static async Task<DispatchResult> ExecuteAsync(string command, string[] args)
    {
        try
        {
            var cli = new CommandOptions(args);
            if (command == "version")
            {
                cli.Allow();
                return new(0, NativeResult.Ok(command, new
                {
                    component = "PcuCp.NativeHost", version = "0.3.0", runtime = RuntimeInformation.FrameworkDescription,
                    os = RuntimeInformation.OSDescription, process = Environment.ProcessId,
                    transport_protocol = "pcucp.native.request/v1",
                    commands = new[] { "version", "windows", "uia-tree", "ocr-image", "screenshot", "focus", "click", "type", "key", "scroll", "privileges", "serve" }
                }));
            }
            if (!OperatingSystem.IsWindows()) throw new NativeFailure("unsupported_platform", "Native desktop operations require Windows.");
            if (!NativeMethods.SetProcessDpiAwarenessContext(new IntPtr(-4)) && Marshal.GetLastWin32Error() != 5)
                throw new NativeFailure("dpi_awareness_failed", "Unable to enable per-monitor DPI awareness.");
            if (command == "ocr-image")
            {
                cli.Allow("--path", "-path", "--language", "-language");
                var payload = await OcrImageObserver.ObserveAsync(args);
                return new(payload.ExitCode, payload);
            }
            var result = command switch
            {
                "windows" => WindowEnumerator.Observe(cli), "uia-tree" => UiaTreeObserver.Observe(cli),
                "screenshot" => ScreenshotObserver.Observe(cli), "privileges" => PrivilegeInspector.Observe(cli),
                "focus" or "click" or "type" or "key" or "scroll" => DesktopActions.Execute(command, cli),
                _ => throw new NativeFailure("unknown_command", $"Unknown native command: {command}", 2)
            };
            return new(result.Status == "ok" ? 0 : 1, result);
        }
        catch (NativeFailure ex) { return new(ex.ExitCode, NativeResult.Error(command, ex.Code, ex.Message)); }
        catch (Exception ex) { return new(1, NativeResult.Error(command, "native_failure", ex.Message)); }
    }
}
