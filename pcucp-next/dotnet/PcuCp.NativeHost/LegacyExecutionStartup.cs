using System.IO;
using System.Globalization;
using System.Text;
using System.Text.Json;

// Startup is separate from the effect stream. Only fixed process switches can
// grant ceilings; captured replies and plan contents never enter this parser.
internal sealed record LegacyExecutionStartup(string Operation, string[] Rest,
    LegacyExecutionAuthority Authority, bool Brief, int CacheSeconds,
    bool VisionAvailable, CultureInfo Culture, string Family = "execution",
    bool Double = false, bool RightClick = false, JsonElement Context = default)
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
    internal static LegacyExecutionStartup Read(string[] options, TextReader input, string family = "execution")
    {
        if (family is not ("execution" or "interaction" or "diagnostics")) throw CommandOptions.Invalid("Unknown execution startup family.");
        var flags = new HashSet<string>(StringComparer.Ordinal);
        foreach (var flag in options)
            if (flag is not ("--allow-live-control" or "--confirm-sensitive") || !flags.Add(flag))
                throw CommandOptions.Invalid("Unsupported or duplicate execution startup switch.");
        using var buffer = new MemoryStream();
        bool firstFrame = true;
        while (true)
        {
            var line = ReadFrame(input);
            // .NET Framework's redirected stdin writer may emit its UTF-8
            // preamble before the caller replaces it with a no-BOM writer.
            // Only the stream's first character can be an encoding marker.
            if (firstFrame && line.Length > 0 && line[0] == '\uFEFF') line = line[1..];
            firstFrame = false;
            using var part = JsonDocument.Parse(line, new JsonDocumentOptions { MaxDepth = 4 });
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
        string[] common = ["schema", "operation", "rest", "brief", "cache_seconds", "vision_available", "culture"];
        Exact(root, family switch { "interaction" => [..common, "double", "right_click"], "diagnostics" => [..common, "context"], _ => common });
        string schema = family switch { "interaction" => "cucp.interaction-start/v1", "diagnostics" => "cucp.diagnostic-start/v1", _ => "cucp.execution-start/v1" };
        if (root.GetProperty("schema").ValueKind != JsonValueKind.String || root.GetProperty("schema").GetString() != schema)
            throw CommandOptions.Invalid("Unsupported execution startup schema.");
        var operation = root.GetProperty("operation");
        string[] operations = family switch
        {
            "interaction" => ["find-label", "click-point", "click-label", "safe-type", "icon-find", "icon-click", "ocr-click", "precision-validate"],
            "diagnostics" => ["perf", "diagnose-lag", "health-quick", "health-detail", "log-tail", "benchmark", "self-test", "audit-summary", "release-notes"],
            _ => ["workflow-run", "task-run", "form-run", "smart-click", "watch", "recovery-plan", "recovery-run"]
        };
        if (operation.ValueKind != JsonValueKind.String || !operations.Contains(operation.GetString(), StringComparer.Ordinal))
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
        bool doubleClick = false, rightClick = false;
        JsonElement context = default;
        if (family == "interaction")
        {
            foreach (var name in new[] { "double", "right_click" })
                if (root.GetProperty(name).ValueKind is not (JsonValueKind.True or JsonValueKind.False)) throw CommandOptions.Invalid("Interaction startup flags must be booleans.");
            doubleClick = root.GetProperty("double").GetBoolean(); rightClick = root.GetProperty("right_click").GetBoolean();
            if (operation.GetString() != "click-label" && (doubleClick || rightClick)) throw CommandOptions.Invalid("Click options require click-label.");
        }
        if (family == "diagnostics")
        {
            context = root.GetProperty("context");
            Exact(context, "audit_directory", "cache_directory", "wrapper_log", "cli_path", "changelog_path", "temp_root", "benchmark_schema", "release_schema");
            foreach (var property in context.EnumerateObject())
            {
                if (property.Name == "cli_path" && property.Value.ValueKind == JsonValueKind.Null) continue;
                if (property.Value.ValueKind != JsonValueKind.String || property.Value.GetString()!.Contains('\0'))
                    throw CommandOptions.Invalid("Diagnostic owned context must contain strings without NUL, with only cli_path nullable.");
            }
            context = context.Clone();
        }
        var originalRest = rest.EnumerateArray().Select(v => v.GetString()!).ToArray();
        return new(operation.GetString()!, originalRest,
            new(flags.Contains("--allow-live-control"), flags.Contains("--confirm-sensitive") && LegacyExecutionConsent.HasStandaloneConfirmation(originalRest)),
            root.GetProperty("brief").GetBoolean(), cache, root.GetProperty("vision_available").GetBoolean(), culture, family, doubleClick, rightClick, context);
    }
}
