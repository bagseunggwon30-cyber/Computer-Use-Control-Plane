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
if (command == "legacy-ocr-match")
{
    // Pure compatibility entry: bounded stdin JSON, no shell, files or desktop API.
    try
    {
        if (args.Length != 1) throw CommandOptions.Invalid("legacy-ocr-match accepts JSON on stdin only.");
        using var input = Console.OpenStandardInput();
        using var buffer = new MemoryStream();
        var chunk = new byte[8192];
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        while (true)
        {
            var count = await input.ReadAsync(chunk, timeout.Token);
            if (count == 0) break;
            if (buffer.Length + count > LegacyOcrMatcher.MaximumRequestBytes) throw CommandOptions.Invalid("Legacy OCR request exceeds 1 MiB.");
            buffer.Write(chunk, 0, count);
        }
        var utf8 = buffer.ToArray();
        // Windows PowerShell/.NET Framework's redirected StreamWriter may emit
        // a UTF-8 preamble. Accept exactly one leading BOM, never arbitrary data.
        var prefix = utf8.Length >= 3 && utf8[0] == 0xEF && utf8[1] == 0xBB && utf8[2] == 0xBF ? 3 : 0;
        using var document = JsonDocument.Parse(new UTF8Encoding(false, true).GetString(utf8, prefix, utf8.Length - prefix), new JsonDocumentOptions { MaxDepth = 32 });
        Console.WriteLine(JsonSerializer.Serialize(NativeResult.Ok(command, LegacyOcrMatcher.Match(document.RootElement)), NativeDispatcher.JsonOptions));
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
        return await NativeSession.RunAsync(Console.OpenStandardInput(), Console.Out,
            options.Has("--allow-live-control"), NativeDispatcher.ExecuteAsync);
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
