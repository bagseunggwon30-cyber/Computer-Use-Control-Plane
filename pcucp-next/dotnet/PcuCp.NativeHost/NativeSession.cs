using System.IO;
using System.Text;
using System.Text.Json;

internal sealed record DispatchResult(int ExitCode, object Payload);
internal sealed record NativeRequest(long Id, string Command, string[] Args);
internal sealed record NativeResponse(string Schema, long? Id, string? Command, int ExitCode, object Payload);

/// <summary>One inherited stdin/stdout connection, fixed process authority, ordered requests.</summary>
internal static class NativeSession
{
    internal const int MaxFrameBytes = 128 * 1024;
    internal static NativeRequest Parse(string text, bool allowLive, long lastId)
    {
        using var doc = JsonDocument.Parse(text, new JsonDocumentOptions { MaxDepth = 16 });
        var root = doc.RootElement;
        if (root.ValueKind != JsonValueKind.Object) throw CommandOptions.Invalid("Request must be an object.");
        var names = new HashSet<string>();
        foreach (var field in root.EnumerateObject())
            if (!names.Add(field.Name) || field.Name is not ("schema" or "id" or "command" or "args"))
                throw CommandOptions.Invalid("Unexpected or duplicate request field.");
        if (names.Count != 4 || root.GetProperty("schema").GetString() != "pcucp.native.request/v1")
            throw CommandOptions.Invalid("Expected schema, id, command and args.");
        if (!root.GetProperty("id").TryGetInt64(out var id) || id <= lastId)
            throw CommandOptions.Invalid("Request IDs must be positive and strictly increasing.");
        var command = root.GetProperty("command").GetString();
        if (string.IsNullOrEmpty(command) || command.Length > 64 || command.Contains('\0'))
            throw CommandOptions.Invalid("Invalid command.");
        command = command.ToLowerInvariant();
        if (command == "serve") throw CommandOptions.Invalid("Nested sessions are not supported.");
        var values = root.GetProperty("args");
        if (values.ValueKind != JsonValueKind.Array || values.GetArrayLength() > 64)
            throw CommandOptions.Invalid("args must contain at most 64 strings.");
        var args = new List<string>();
        foreach (var value in values.EnumerateArray())
        {
            if (value.ValueKind != JsonValueKind.String) throw CommandOptions.Invalid("Each argument must be a string.");
            var arg = value.GetString()!;
            if (arg.Length > 65536 || arg.Contains('\0')) throw CommandOptions.Invalid("Invalid argument length or NUL.");
            args.Add(arg);
        }
        // A request's flag can never increase the authority selected by the parent at startup.
        if (!allowLive && (command is "focus" or "click" or "type" or "key" or "scroll" ||
            args.Any(a => string.Equals(a, "--allow-live-control", StringComparison.OrdinalIgnoreCase))))
            throw new NativeFailure("live_control_required", "This native session was started read-only.", 2);
        return new NativeRequest(id, command, args.ToArray());
    }

    internal static async Task<int> RunAsync(Stream input, TextWriter output, bool allowLive,
        Func<string, string[], Task<DispatchResult>> dispatch)
    {
        long lastId = 0;
        var buffer = new byte[8192];
        using var frame = new MemoryStream();
        while (true)
        {
            var count = await input.ReadAsync(buffer);
            if (count == 0) return frame.Length == 0 ? 0 : 2; // Incomplete frame is never executed.
            for (var i = 0; i < count; i++)
            {
                if (buffer[i] != (byte)'\n')
                {
                    if (frame.Length >= MaxFrameBytes) return 2; // Stop without draining unbounded input.
                    frame.WriteByte(buffer[i]);
                    continue;
                }
                NativeRequest? request = null;
                DispatchResult result;
                var fatal = false;
                try
                {
                    request = Parse(new UTF8Encoding(false, true).GetString(frame.ToArray()), allowLive, lastId);
                    lastId = request.Id; // Consume before dispatch; never replay an uncertain operation.
                    result = await dispatch(request.Command, request.Args);
                }
                catch (Exception ex)
                {
                    // Protocol failures close the connection, including forbidden authority escalation.
                    fatal = true;
                    result = new(2, NativeResult.Error("protocol", ex is NativeFailure nf ? nf.Code : "invalid_request", ex.Message));
                }
                var response = new NativeResponse("pcucp.native.response/v1", request?.Id, request?.Command, result.ExitCode, result.Payload);
                await output.WriteLineAsync(JsonSerializer.Serialize(response, new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower }));
                await output.FlushAsync();
                frame.SetLength(0);
                if (fatal) return 2;
            }
        }
    }
}
