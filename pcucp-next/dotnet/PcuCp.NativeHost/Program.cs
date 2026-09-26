using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;

Console.OutputEncoding = new UTF8Encoding(false);
var command = args.Length > 0 ? args[0].ToLowerInvariant() : "version";
var jsonOptions = new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };
try
{
    var cli = new CommandOptions(args.Skip(1).ToArray());
    if (command == "version")
    {
        cli.Allow();
        Console.WriteLine(JsonSerializer.Serialize(NativeResult.Ok(command, new
        {
            component = "PcuCp.NativeHost", version = "0.2.0", runtime = RuntimeInformation.FrameworkDescription,
            os = RuntimeInformation.OSDescription, process = Environment.ProcessId,
            commands = new[] { "version", "windows", "uia-tree", "ocr-image", "screenshot", "focus", "click", "type", "key", "scroll", "privileges" }
        }), jsonOptions));
        return 0;
    }
    if (!OperatingSystem.IsWindows()) throw new NativeFailure("unsupported_platform", "Native desktop operations require Windows.");
    if (!NativeMethods.SetProcessDpiAwarenessContext(new IntPtr(-4)) && Marshal.GetLastWin32Error() != 5)
        throw new NativeFailure("dpi_awareness_failed", "Unable to enable per-monitor DPI awareness.");
    if (command == "ocr-image")
    {
        cli.Allow("--path", "-path", "--language", "-language");
        var payload = await OcrImageObserver.ObserveAsync(args.Skip(1).ToArray());
        Console.WriteLine(JsonSerializer.Serialize(payload, jsonOptions));
        return payload.ExitCode;
    }
    var result = command switch
    {
        "windows" => WindowEnumerator.Observe(cli),
        "uia-tree" => UiaTreeObserver.Observe(cli),
        "screenshot" => ScreenshotObserver.Observe(cli),
        "privileges" => PrivilegeInspector.Observe(cli),
        "focus" or "click" or "type" or "key" or "scroll" => DesktopActions.Execute(command, cli),
        _ => throw new NativeFailure("unknown_command", $"Unknown native command: {command}", 2)
    };
    Console.WriteLine(JsonSerializer.Serialize(result, jsonOptions));
    return result.Status == "ok" ? 0 : 1;
}
catch (NativeFailure ex)
{
    Console.WriteLine(JsonSerializer.Serialize(NativeResult.Error(command, ex.Code, ex.Message), jsonOptions));
    return ex.ExitCode;
}
catch (Exception ex)
{
    Console.WriteLine(JsonSerializer.Serialize(NativeResult.Error(command, "native_failure", ex.Message), jsonOptions));
    return 1;
}
