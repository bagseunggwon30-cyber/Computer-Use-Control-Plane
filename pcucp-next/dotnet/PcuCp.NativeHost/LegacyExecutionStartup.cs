using System.IO;
using System.Globalization;
using System.Text;
using System.Text.Json;

// Startup is separate from the effect stream. Only fixed process switches can
// grant ceilings; captured replies and plan contents never enter this parser.
internal sealed record LegacyExecutionStartup(string Operation, string[] Rest,
    LegacyExecutionAuthority Authority, bool Brief, int CacheSeconds,
    bool VisionAvailable, CultureInfo Culture)
{
    internal static object Confirmation(JsonElement args)
    {
        Exact(args, "original_argv");
        var argv = args.GetProperty("original_argv");
        if (argv.ValueKind != JsonValueKind.Array || argv.EnumerateArray().Any(v => v.ValueKind != JsonValueKind.String))
            throw CommandOptions.Invalid("Original confirmation argv must contain strings only.");
        return new { confirmed = LegacyExecutionConsent.HasStandaloneConfirmation(argv.EnumerateArray().Select(v => v.GetString())) };
    }
    internal const int MaximumStartupBytes = 32 * 1024 * 1024;
    internal const int MaximumFrameCharacters = 66000;
    internal static string ReadFrame(TextReader input)
    {
        var line = new StringBuilder();
        while (true)
        {
            int next = input.Read();
            if (next < 0) throw CommandOptions.Invalid("Execution startup stream closed before its end frame.");
            if (next == '\n') return line.ToString().TrimEnd('\r');
            if (line.Length == MaximumFrameCharacters) throw CommandOptions.Invalid("Execution startup frame exceeds 66000 characters.");
            line.Append((char)next);
        }
    }
    private static void Exact(JsonElement value, params string[] expected)
    {
        if (value.ValueKind != JsonValueKind.Object) throw CommandOptions.Invalid("Expected an execution startup object.");
        var seen = new HashSet<string>(StringComparer.Ordinal);
        foreach (var p in value.EnumerateObject())
            if (!seen.Add(p.Name) || !expected.Contains(p.Name)) throw CommandOptions.Invalid("Unexpected or duplicate execution startup field.");
        if (seen.Count != expected.Length) throw CommandOptions.Invalid("Missing execution startup field.");
    }
    internal static LegacyExecutionStartup Read(string[] options, TextReader input)
    {
        var flags = new HashSet<string>(StringComparer.Ordinal);
        foreach (var flag in options)
            if (flag is not ("--allow-live-control" or "--confirm-sensitive") || !flags.Add(flag))
                throw CommandOptions.Invalid("Unsupported or duplicate execution startup switch.");
        using var buffer = new MemoryStream();
        while (true)
        {
            using var part = JsonDocument.Parse(ReadFrame(input), new JsonDocumentOptions { MaxDepth = 4 });
            var frame = part.RootElement;
            if (frame.ValueKind != JsonValueKind.Object || !frame.TryGetProperty("kind", out var kind) || kind.ValueKind != JsonValueKind.String)
                throw CommandOptions.Invalid("Missing execution startup frame kind.");
            if (kind.GetString() == "end") Exact(frame, "kind", "id");
            else if (kind.GetString() == "part") Exact(frame, "kind", "id", "data");
            else throw CommandOptions.Invalid("Unknown execution startup frame kind.");
            if (frame.GetProperty("id").ValueKind != JsonValueKind.Number || !frame.GetProperty("id").TryGetInt64(out var id) || id != 0)
                throw CommandOptions.Invalid("Execution startup frames must use id zero.");
            if (kind.GetString() == "end") break;
            if (frame.GetProperty("data").ValueKind != JsonValueKind.String) throw CommandOptions.Invalid("Startup data must be base64 text.");
            byte[] bytes;
            try { bytes = Convert.FromBase64String(frame.GetProperty("data").GetString()!); }
            catch (FormatException) { throw CommandOptions.Invalid("Invalid execution startup base64."); }
            if (bytes.Length > 49152 || buffer.Length + bytes.Length > MaximumStartupBytes)
                throw CommandOptions.Invalid("Execution startup exceeds its chunk or aggregate bound.");
            buffer.Write(bytes);
        }
        using var doc = JsonDocument.Parse(new UTF8Encoding(false, true).GetString(buffer.ToArray()), new JsonDocumentOptions { MaxDepth = 8 });
        var root = doc.RootElement;
        Exact(root, "schema", "operation", "rest", "brief", "cache_seconds", "vision_available", "culture");
        if (root.GetProperty("schema").ValueKind != JsonValueKind.String || root.GetProperty("schema").GetString() != "cucp.execution-start/v1")
            throw CommandOptions.Invalid("Unsupported execution startup schema.");
        var operation = root.GetProperty("operation");
        if (operation.ValueKind != JsonValueKind.String || operation.GetString() is not ("workflow-run" or "task-run" or "form-run" or "smart-click" or "watch" or "recovery-plan" or "recovery-run"))
            throw CommandOptions.Invalid("Unknown execution family operation.");
        var rest = root.GetProperty("rest");
        if (rest.ValueKind != JsonValueKind.Array || rest.EnumerateArray().Any(v => v.ValueKind != JsonValueKind.String))
            throw CommandOptions.Invalid("Execution startup rest must contain strings only.");
        foreach (var name in new[] { "brief", "vision_available" })
            if (root.GetProperty(name).ValueKind is not (JsonValueKind.True or JsonValueKind.False)) throw CommandOptions.Invalid("Execution startup flags must be booleans.");
        if (root.GetProperty("cache_seconds").ValueKind != JsonValueKind.Number || !root.GetProperty("cache_seconds").TryGetInt32(out var cache)) throw CommandOptions.Invalid("Execution cache seconds must be Int32.");
        var cultureValue = root.GetProperty("culture");
        if (cultureValue.ValueKind != JsonValueKind.String || cultureValue.GetString()!.Length > 128) throw CommandOptions.Invalid("Execution culture must be a bounded name.");
        CultureInfo culture;
        try { culture = CultureInfo.GetCultureInfo(cultureValue.GetString()!); }
        catch (CultureNotFoundException) { throw CommandOptions.Invalid("Unsupported execution culture."); }
        var originalRest = rest.EnumerateArray().Select(v => v.GetString()!).ToArray();
        return new(operation.GetString()!, originalRest,
            new(flags.Contains("--allow-live-control"), flags.Contains("--confirm-sensitive") && LegacyExecutionConsent.HasStandaloneConfirmation(originalRest)),
            root.GetProperty("brief").GetBoolean(), cache, root.GetProperty("vision_available").GetBoolean(), culture);
    }
}
