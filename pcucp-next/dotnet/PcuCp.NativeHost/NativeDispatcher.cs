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
                    component = "PcuCp.NativeHost", version = "0.4.0", runtime = RuntimeInformation.FrameworkDescription,
                    os = RuntimeInformation.OSDescription, process = Environment.ProcessId,
                    transport_protocol = "pcucp.native.request/v1",
                    parent_lifetime_guard = "inherited-parent-handle/v1", uia_action_references = "single-use-runtime-id/v1", uia_patterns = "explicit-pattern-actions/v1", ocr_window = "same-pixels-memory/v1",
                    commands = new[] { "version", "windows", "uia-tree", "ocr-image", "ocr-window", "screenshot", "focus", "click", "drag", "type", "key", "scroll", "app-launch", "app-close", "uia-invoke", "uia-set-value", "uia-toggle", "uia-select", "uia-expand-collapse", "uia-scroll", "privileges", "serve" }
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
            if (command is "ocr-window" or "screenshot" or "focus" or "click" or "drag" or "type" or "key" or "scroll" or "app-launch" or "app-close") UiaElementActions.Invalidate();
            var result = command switch
            {
                "windows" => WindowEnumerator.Observe(cli), "uia-tree" => UiaTreeObserver.Observe(cli),
                "legacy-diagnostic-read" => LegacyDiagnosticRead.Execute(cli),
                "ocr-window" => await OcrWindowObserver.ObserveAsync(cli),
                "screenshot" => ScreenshotObserver.Observe(cli), "privileges" => PrivilegeInspector.Observe(cli),
                "focus" or "click" or "drag" or "type" or "key" or "scroll" => DesktopActions.Execute(command, cli),
                "uia-invoke" or "uia-set-value" or "uia-toggle" or "uia-select" or "uia-expand-collapse" or "uia-scroll" => UiaElementActions.Execute(command, cli),
                "app-launch" or "app-close" => await AppLifecycleActions.ExecuteAsync(command, cli),
                _ => throw new NativeFailure("unknown_command", $"Unknown native command: {command}", 2)
            };
            return new(result.Status == "ok" ? 0 : 1, result);
        }
        catch (NativeFailure ex) { return new(ex.ExitCode, NativeResult.Error(command, ex.Code, ex.Message)); }
        catch (Exception ex) { return new(1, NativeResult.Error(command, "native_failure", ex.Message)); }
    }
}
