using System.Globalization;
using System.IO;
using System.Text;
using System.Text.Json;

Console.OutputEncoding = new UTF8Encoding(false);
try
{
    var startup = ParentLifetimeGuard.Extract(args);
    args = startup.Args;
    ParentLifetimeGuard.Start(startup.Handle);
}
catch (Exception ex)
{
    Console.WriteLine(JsonSerializer.Serialize(NativeResult.Error("startup", "parent_guard_failed", ex.Message), NativeDispatcher.JsonOptions));
    return 2;
}
var command = args.Length > 0 ? args[0].ToLowerInvariant() : "version";
if (command is "legacy-precision-session" or "legacy-precision-storage")
{
    try
    {
        if (args.Length != 1) throw CommandOptions.Invalid("Precision sessions accept only a typed startup frame.");
        using var input = LegacySessionInput.Open(Console.OpenStandardInput());
        var startup = LegacyPrecisionSession.ReadStartup(input);
        var session = new LegacyPrecisionSession(input, Console.Out);
        return command == "legacy-precision-session" ? session.Run(startup) : session.RunStorage(startup);
    }
    catch (Exception ex)
    {
        Console.WriteLine(JsonSerializer.Serialize(NativeResult.Error(command,
            ex is NativeFailure failure ? failure.Code : "invalid_precision_startup", ex.Message), NativeDispatcher.JsonOptions));
        return 2;
    }
}
if (command is "legacy-execution-session" or "legacy-interaction-session" or "legacy-diagnostic-session")
{
    try
    {
        using var input = LegacySessionInput.Open(Console.OpenStandardInput());
        var family = command switch { "legacy-interaction-session" => "interaction", "legacy-diagnostic-session" => "diagnostics", _ => "execution" };
        var startup = LegacyExecutionStartup.Read(args.Skip(1).ToArray(), input, family);
        var previousCulture = CultureInfo.CurrentCulture;
        try
        {
            CultureInfo.CurrentCulture = startup.Culture;
            var session = new LegacyExecutionSession(input, Console.Out);
            if (family == "interaction")
                return session.Run(effects => new LegacyExecutionCoordinator(effects, startup.Authority, startup.Rest,
                    startup.Brief, startup.CacheSeconds, startup.VisionAvailable).RunInteraction(startup.Operation, startup.Double, startup.RightClick));
            if (family == "diagnostics")
                return session.Run(effects =>
                {
                    string Text(string name) => startup.Context.GetProperty(name).GetString()!;
                    var context = new LegacyDiagnosticContext(Text("audit_directory"), Text("cache_directory"), Text("wrapper_log"),
                        startup.Context.GetProperty("cli_path").GetString(), Text("changelog_path"), Text("temp_root"), Text("benchmark_schema"), Text("release_schema"));
                    var result = new LegacyDiagnosticCoordinator(new LegacyDiagnosticExecutionAdapter(effects), startup.Rest, context, startup.Brief).Run(startup.Operation);
                    return new LegacyExecutionResult(result.Payload, result.Exit, result.JsonDepth, result.Brief, result.EmitJson);
                });
            return session.Run(startup.Operation, startup.Rest, startup.Authority, startup.Brief, startup.CacheSeconds, startup.VisionAvailable);
        }
        finally { CultureInfo.CurrentCulture = previousCulture; }
    }
    catch (Exception ex)
    {
        // Startup failed before any effect. No partially accepted authority is used.
        Console.WriteLine(JsonSerializer.Serialize(NativeResult.Error(command,
            ex is NativeFailure failure ? failure.Code : "invalid_execution_startup", ex.Message), NativeDispatcher.JsonOptions));
        return 2;
    }
}
if (command is "legacy-ocr-match" or "legacy-compat" or "legacy-execution-confirmation" or "legacy-precision-advance")
{
    // Pure compatibility entry: bounded stdin JSON, no shell, files or desktop API.
    try
    {
        if (args.Length != 1) throw CommandOptions.Invalid("Pure compatibility commands accept JSON on stdin only.");
        using var input = Console.OpenStandardInput();
        using var buffer = new MemoryStream();
        var chunk = new byte[8192];
        bool confirmationOnly = command == "legacy-execution-confirmation";
        bool precisionOnly = command == "legacy-precision-advance";
        int maximumRequestBytes = confirmationOnly ? LegacyExecutionStartup.MaximumStartupBytes : precisionOnly ? 16 * 1024 * 1024 : LegacyOcrMatcher.MaximumRequestBytes;
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        while (true)
        {
            var count = await input.ReadAsync(chunk, timeout.Token);
            if (count == 0) break;
            if (buffer.Length + count > maximumRequestBytes) throw CommandOptions.Invalid(confirmationOnly
                ? "Execution confirmation request exceeds 32 MiB." : precisionOnly ? "Precision request exceeds 16 MiB." : "Legacy OCR request exceeds 1 MiB.");
            buffer.Write(chunk, 0, count);
        }
        var utf8 = buffer.ToArray();
        // Windows PowerShell/.NET Framework's redirected StreamWriter may emit
        // a UTF-8 preamble. Accept exactly one leading BOM, never arbitrary data.
        var prefix = utf8.Length >= 3 && utf8[0] == 0xEF && utf8[1] == 0xBB && utf8[2] == 0xBF ? 3 : 0;
        using var document = JsonDocument.Parse(new UTF8Encoding(false, true).GetString(utf8, prefix, utf8.Length - prefix), new JsonDocumentOptions { MaxDepth = precisionOnly ? 128 : 32 });
        // A legacy caller can have a runspace-specific culture. Preserve it
        // inside this one pure request, never in OS settings or later requests.
        var previousCulture = CultureInfo.CurrentCulture;
        object data;
        try
        {
            if (document.RootElement.ValueKind == JsonValueKind.Object && document.RootElement.TryGetProperty("culture", out var culture))
            {
                if (document.RootElement.EnumerateObject().Count(p => p.Name == "culture") != 1 || culture.ValueKind != JsonValueKind.String || culture.GetString()!.Length > 128)
                    throw CommandOptions.Invalid("culture must be one bounded culture-name string.");
                try { CultureInfo.CurrentCulture = CultureInfo.GetCultureInfo(culture.GetString()!); }
                catch (CultureNotFoundException) { throw CommandOptions.Invalid("Unsupported compatibility culture."); }
            }
            data = command == "legacy-ocr-match" ? LegacyOcrMatcher.Match(document.RootElement) : precisionOnly ? LegacyPrecisionFacade.Execute(document.RootElement) : LegacyCompatibilityDispatcher.Execute(document.RootElement, confirmationOnly);
        }
        finally { CultureInfo.CurrentCulture = previousCulture; }
        Console.WriteLine(JsonSerializer.Serialize(NativeResult.Ok(command, data), NativeDispatcher.JsonOptions));
        return 0;
    }
    catch (Exception ex)
    {
        Console.WriteLine(JsonSerializer.Serialize(NativeResult.Error(command,
            ex is NativeFailure failure ? failure.Code : "invalid_legacy_ocr_request", ex.Message), NativeDispatcher.JsonOptions));
        return 2;
    }
}
if (command == "serve")
{
    try
    {
        var options = new CommandOptions(args.Skip(1).ToArray());
        options.Allow("--allow-live-control");
        try
        {
            return await NativeSession.RunAsync(Console.OpenStandardInput(), Console.Out,
                options.Has("--allow-live-control"), NativeDispatcher.ExecuteAsync);
        }
        finally { LegacyDiagnosticRead.Close(); }
    }
    catch (IOException) { return 1; }
    catch (Exception ex)
    {
        Console.WriteLine(JsonSerializer.Serialize(NativeResult.Error(command,
            ex is NativeFailure failure ? failure.Code : "native_failure", ex.Message), NativeDispatcher.JsonOptions));
        return 2;
    }
}
var result = await NativeDispatcher.ExecuteAsync(command, args.Skip(1).ToArray());
Console.WriteLine(JsonSerializer.Serialize(result.Payload, NativeDispatcher.JsonOptions));
return result.ExitCode;
