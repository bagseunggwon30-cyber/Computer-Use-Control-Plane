using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

// One retained planner invocation. Effect replies are framed independently;
// neither history nor prior replies are replayed as the session advances.
internal sealed class LegacyPrecisionSession(TextReader input, TextWriter output) : IPrecisionReadEffects
{
    private const int ChunkBytes = 49152;
    private static readonly JsonSerializerOptions JsonOptions = new() { MaxDepth = 128 };
    private long sequence;
    private bool persistenceStarted;
    private static object D(params object?[] values) => LegacyPrecisionKernel.D(values);
    private static JsonElement J(object? value) => JsonSerializer.SerializeToElement(value, JsonOptions);
    private void Send(string target, long id, object? value)
    {
        byte[] bytes = JsonSerializer.SerializeToUtf8Bytes(LegacyExecutionWire.Encode(J(value)), JsonOptions);
        for (int offset = 0; offset < bytes.Length; offset += ChunkBytes)
        {
            int length = Math.Min(ChunkBytes, bytes.Length - offset);
            output.WriteLine(JsonSerializer.Serialize(new { kind = "part", target, id, data = Convert.ToBase64String(bytes, offset, length) }));
        }
        output.WriteLine(JsonSerializer.Serialize(new { kind = "end", target, id })); output.Flush();
    }
    private JsonElement Receive(long id)
    {
        using var buffer = new MemoryStream();
        while (true)
        {
            string line = ReadBoundedLine(input, 70000) ?? throw new LegacyExecutionProtocolException("Precision reply stream closed; no persistence is retried.");
            using var document = JsonDocument.Parse(line, new JsonDocumentOptions { MaxDepth = 8 }); var frame = document.RootElement;
            var names = frame.ValueKind == JsonValueKind.Object ? frame.EnumerateObject().Select(p => p.Name).ToArray() : [];
            if (names.Distinct(StringComparer.Ordinal).Count() != names.Length || names.Any(n => n is not ("kind" or "id" or "data")) ||
                frame.ValueKind != JsonValueKind.Object || !frame.TryGetProperty("kind", out var kind) || kind.ValueKind != JsonValueKind.String || !frame.TryGetProperty("id", out var rawId) || rawId.ValueKind != JsonValueKind.Number || !rawId.TryGetInt64(out long actualId) || actualId != id)
                throw new LegacyExecutionProtocolException("Precision reply must match the outstanding request.");
            if (kind.GetString() == "end") { if (names.Length != 2) throw new LegacyExecutionProtocolException("Unexpected precision end fields."); break; }
            if (kind.GetString() != "part" || names.Length != 3 || !frame.TryGetProperty("data", out var data) || data.ValueKind != JsonValueKind.String) throw new LegacyExecutionProtocolException("Invalid precision reply chunk.");
            byte[] bytes;
            try { bytes = Convert.FromBase64String(data.GetString()!); } catch (FormatException) { throw new LegacyExecutionProtocolException("Invalid precision reply encoding."); }
            if (bytes.Length > ChunkBytes) throw new LegacyExecutionProtocolException("Split precision reply into 48KiB chunks.");
            buffer.Write(bytes);
        }
        using var reply = JsonDocument.Parse(buffer.ToArray(), new JsonDocumentOptions { MaxDepth = 128 });
        var value = LegacyExecutionWire.Decode(reply.RootElement);
        string[] fields = value.ValueKind == JsonValueKind.Object ? value.EnumerateObject().Select(p => p.Name).ToArray() : [];
        if (fields.Length != 2 || !value.TryGetProperty("state", out var state) || state.ValueKind != JsonValueKind.String) throw new LegacyExecutionProtocolException("Invalid precision reply envelope.");
        if (state.GetString() == "error" && value.TryGetProperty("message", out var message) && message.ValueKind == JsonValueKind.String) throw new InvalidOperationException(message.GetString());
        if (state.GetString() != "ok" || !value.TryGetProperty("value", out var result)) throw new LegacyExecutionProtocolException("Invalid precision reply state.");
        return result.Clone();
    }
    private JsonElement Read(string kind, object parameters)
    {
        long id = ++sequence; Send("read", id, D("kind", kind, "args", parameters)); return Receive(id);
    }
    private static object Point(PrecisionTargetPoint p) => D("x", p.X, "y", p.Y, "target_hwnd", p.TargetHwnd, "target_match", p.TargetMatch);
    public object? CoordinateMap(PrecisionTargetPoint p) => Read("coord-map", D("from", "screen", "x", p.X, "y", p.Y, "norm_x", 0, "norm_y", 0, "has_norm", false, "target_hwnd", p.TargetHwnd, "target_match", p.TargetMatch));
    public object? HitTest(PrecisionTargetPoint p) => Read("hit-test", Point(p));
    public object? CoordinateProfile(PrecisionTargetPoint p) => Read("coord-profile", D("has_point", true, "x", p.X, "y", p.Y, "target_hwnd", p.TargetHwnd, "target_match", p.TargetMatch));
    private static string[] ScanArgs(PrecisionScan scan, bool child, int ttl = 0, bool noCache = false)
    {
        var p = scan.Point; string S(long x) => x.ToString(CultureInfo.InvariantCulture);
        var result = child ? new List<string> { "--x", S(p.X), "--y", S(p.Y), "--radius", S(scan.Radius), "--step", S(scan.Step), "--click-inset", S(scan.ClickInset), "--cache-ttl", S(ttl) }
            : new List<string> { "-Action", "hit-scan", "-X", S(p.X), "-Y", S(p.Y), "-ClickInset", S(scan.ClickInset), "-ScanRadius", S(scan.Radius), "-ScanStep", S(scan.Step) };
        if (p.TargetMatch.Length > 0) result.AddRange([child ? "--target-match" : "-TargetMatch", p.TargetMatch]);
        if (p.TargetHwnd > 0) result.AddRange([child ? "--target-hwnd" : "-TargetHwnd", S(p.TargetHwnd)]);
        if (child && noCache) result.Add("--no-cache"); return result.ToArray();
    }
    public object? HitScan(PrecisionScan scan) => Read("hit-scan", D("argv", ScanArgs(scan, false)));
    public object? ChildPointPlan(PrecisionChildPlan plan) => Read("point-plan-child", D("argv", ScanArgs(plan.Scan, true, plan.CacheSeconds, plan.NoCache)));
    public string[] HistoryLines(string configuredPath)
    {
        var result = Read("history-lines", D("path", configuredPath));
        if (result.ValueKind != JsonValueKind.Array || result.EnumerateArray().Any(v => v.ValueKind != JsonValueKind.String)) throw new LegacyExecutionProtocolException("History-lines must return a real string array.");
        return result.EnumerateArray().Select(v => v.GetString()!).ToArray();
    }
    public object? ReadCache(string configuredDirectory, string key, int maximumAgeSeconds) => Read("cache-read", D("directory", configuredDirectory, "key", key, "max_age_seconds", maximumAgeSeconds));

    internal int Run(JsonElement startup) => RunCore(startup, false);
    internal int RunStorage(JsonElement startup) => RunCore(startup, true);
    private int RunCore(JsonElement startup, bool storageMode)
    {
        try
        {
            var previous = CultureInfo.CurrentCulture;
            try
            {
                Fields(startup, "schema", "operation", "args", "culture");
                if (startup.GetProperty("schema").ValueKind != JsonValueKind.String || startup.GetProperty("schema").GetString() != (storageMode ? "cucp.precision-storage/v1" : "cucp.precision-session/v1")) throw new ArgumentException("Invalid precision session schema.");
                if (startup.GetProperty("operation").ValueKind != JsonValueKind.String || startup.GetProperty("culture").ValueKind != JsonValueKind.String) throw new ArgumentException("Precision operation and culture must be strings.");
                string operation = startup.GetProperty("operation").GetString()!;
                bool planner = operation is "coord-anchor" or "point-plan" or "target-validate";
                string culture = startup.GetProperty("culture").GetString()!;
                if (culture.Length > 128) throw new ArgumentException("Invalid precision culture.");
                CultureInfo.CurrentCulture = CultureInfo.GetCultureInfo(culture);
                JsonElement args = LegacyExecutionWire.Decode(startup.GetProperty("args"));
                if (storageMode)
                {
                    if (operation is not ("history-lines" or "history-file-read" or "history-file-score" or "history-append" or "cache-read" or "cache-path" or "cache-write")) throw new ArgumentException("Unsupported precision storage operation.");
                    return Utility(operation, args);
                }
                if (!planner)
                {
                    if (operation is not ("history-read" or "history-distance" or "history-score" or "cache-key" or "confidence-rank" or "size-class" or "edge-distance" or "child-plan-envelope")) throw new ArgumentException("Unsupported pure precision helper.");
                    var helper = J(LegacyPrecisionKernel.Advance(operation, args));
                    if (helper.GetProperty("state").GetString() != "complete") { Send("error", ++sequence, helper); return 1; }
                    Send("complete", ++sequence, helper); return 0;
                }
                Fields(args, "rest", "cache_seconds", "brief", "now", "history_file", "history_max", "cache_dir", "elapsed_ms");
                foreach (string name in new[] { "history_file", "cache_dir", "now" }) if (args.GetProperty(name).ValueKind != JsonValueKind.String || args.GetProperty(name).GetString()!.Length > 32768) throw new ArgumentException("Invalid precision startup string.");
                foreach (string name in new[] { "cache_seconds", "history_max", "elapsed_ms" }) if (args.GetProperty(name).ValueKind != JsonValueKind.Number || !args.GetProperty(name).TryGetInt32(out _)) throw new ArgumentException("Invalid precision startup integer.");
                if (args.GetProperty("brief").ValueKind is not (JsonValueKind.True or JsonValueKind.False)) throw new ArgumentException("Invalid precision startup brief flag.");
                foreach (string name in new[] { "history_file", "cache_dir" }) if (args.GetProperty(name).GetString()!.Length != 0) _ = Path.GetFullPath(args.GetProperty(name).GetString()!);
                var clock = Stopwatch.StartNew();
                var completed = (Dictionary<string, object?>)LegacyPrecisionKernel.Execute(operation, args, this);
                clock.Stop();
                if (LegacyPrecisionKernel.S(LegacyPrecisionKernel.P(completed, "state")) == "complete" && LegacyPrecisionKernel.P(completed, "payload") is Dictionary<string, object?> payload)
                {
                    int elapsed = Convert.ToInt32(clock.Elapsed.TotalMilliseconds); payload["elapsed_ms"] = elapsed;
                    if (completed["brief"] is string briefText)
                    {
                        int position = briefText.LastIndexOf("elapsed_ms=", StringComparison.Ordinal);
                        if (position >= 0) completed["brief"] = briefText[..position] + "elapsed_ms=" + elapsed.ToString(CultureInfo.InvariantCulture);
                    }
                }
                var result = J(completed);
                if (result.GetProperty("state").GetString() != "complete") { Send("error", ++sequence, result); return 1; }
                var effects = result.GetProperty("effects");
                if (effects.GetArrayLength() == 0) { Send("complete", ++sequence, result); return result.GetProperty("exit").GetInt32(); }
                if (effects.GetArrayLength() != 1) throw new LegacyExecutionProtocolException("Unexpected precision terminal effect count.");
                var effect = effects[0]; string kind = effect.GetProperty("kind").GetString()!;
                if (kind is not ("history-append" or "cache-write")) throw new LegacyExecutionProtocolException("Unknown precision terminal effect.");
                var writeValue = kind == "history-append" ? effect.GetProperty("args").GetProperty("record") : result.GetProperty("payload");
                var expectedSerialization = Project(writeValue, 0, kind == "history-append" ? 10 : 14);
                long preparedId = ++sequence; Send("prepare", preparedId, result);
                // Client renders the entire final Console and serializes the
                // exact legacy cache/history value before authorizing this write.
                JsonElement prepared = Receive(preparedId);
                Fields(prepared, "serialized");
                if (prepared.GetProperty("serialized").ValueKind != JsonValueKind.String) throw new LegacyExecutionProtocolException("Missing serialized terminal value.");
                string serialized = prepared.GetProperty("serialized").GetString()!;
                using (var validated = JsonDocument.Parse(serialized, new JsonDocumentOptions { MaxDepth = 128 }))
                {
                    if (validated.RootElement.ValueKind != JsonValueKind.Object) throw new LegacyExecutionProtocolException("Terminal serialization must be a JSON object.");
                    if (!Equivalent(expectedSerialization, validated.RootElement)) throw new LegacyExecutionProtocolException("Terminal serialization differs from the complete prevalidated value.");
                }
                string receipt = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(serialized))).ToLowerInvariant();
                long commitId = ++sequence; Send("commit-ready", commitId, D("receipt", receipt));
                var acknowledgement = Receive(commitId); Fields(acknowledgement, "receipt");
                if (acknowledgement.GetProperty("receipt").ValueKind != JsonValueKind.String || acknowledgement.GetProperty("receipt").GetString() != receipt) throw new LegacyExecutionProtocolException("Precision commit receipt changed.");
                string history = args.GetProperty("history_file").GetString()!, cache = args.GetProperty("cache_dir").GetString()!;
                var storage = new LegacyPrecisionStorage(history, cache, () => DateTime.Now);
                // Build and serialize the bounded completion outcome before the
                // write too. After persistence only a prebuilt frame is emitted.
                string trueOutcome = BuildOutcome(commitId + 1, true), falseOutcome = BuildOutcome(commitId + 1, false), emptyOutcome = BuildOutcome(commitId + 1, null);
                string completion;
                persistenceStarted = true;
                if (kind == "history-append") completion = storage.AppendHistory(serialized, effect.GetProperty("args").GetProperty("max").GetInt32()) ? trueOutcome : falseOutcome;
                else { storage.WriteCache(effect.GetProperty("args").GetProperty("key").GetString()!, serialized); completion = emptyOutcome; }
                output.Write(completion); output.Flush(); return result.GetProperty("exit").GetInt32();
            }
            finally { CultureInfo.CurrentCulture = previous; }
        }
        catch (Exception ex)
        {
            // A broken stream after persistence is an uncertain outcome. Never
            // replay or attempt a newly serialized report after that boundary.
            if (!persistenceStarted) Send("error", ++sequence, D("state", "error", "error", ex.Message));
            return 1;
        }
    }
    private int Utility(string operation, JsonElement args)
    {
        static string Text(JsonElement a, string name)
        {
            if (!a.TryGetProperty(name, out var value) || value.ValueKind != JsonValueKind.String || value.GetString()!.Length > 32768) throw new LegacyExecutionProtocolException("Invalid precision utility string.");
            return value.GetString()!;
        }
        static int Integer(JsonElement a, string name)
        {
            if (!a.TryGetProperty(name, out var value) || value.ValueKind != JsonValueKind.Number || !value.TryGetInt32(out int result)) throw new LegacyExecutionProtocolException("Invalid precision utility integer.");
            return result;
        }
        object? payload;
        string history = "", cache = "";
        if (operation is "history-file-read" or "history-file-score" or "history-append" or "history-lines") history = Text(args, "history_file");
        if (operation is "cache-read" or "cache-write" or "cache-path") cache = Text(args, "cache_dir");
        if (history.Length != 0) _ = Path.GetFullPath(history); if (cache.Length != 0) _ = Path.GetFullPath(cache);
        var storage = new LegacyPrecisionStorage(history, cache, () => DateTime.Now);
        switch (operation)
        {
            case "history-lines": Fields(args, "history_file"); payload = storage.HistoryLines(); break;
            case "history-file-read": Fields(args, "history_file", "last"); payload = LegacyPrecisionKernel.ReadHistory(storage.HistoryLines(), Integer(args, "last")); break;
            case "history-file-score":
                Fields(args, "history_file", "record", "tolerance");
                if (args.GetProperty("tolerance").ValueKind != JsonValueKind.Number || !args.GetProperty("tolerance").TryGetDouble(out double tolerance)) throw new LegacyExecutionProtocolException("Invalid history tolerance.");
                var record = args.GetProperty("record");
                payload = LegacyPrecisionKernel.Score(record, LegacyPrecisionKernel.T(record) ? LegacyPrecisionKernel.ReadHistory(storage.HistoryLines(), 500) : [], tolerance, history); break;
            case "cache-read": Fields(args, "cache_dir", "key", "max_age_seconds"); payload = storage.ReadCache(Text(args, "key"), Integer(args, "max_age_seconds")); break;
            case "cache-path": Fields(args, "cache_dir", "key"); payload = storage.CachePath(Text(args, "key")); break;
            case "history-append":
            case "cache-write":
                string serialized;
                if (operation == "history-append") { Fields(args, "history_file", "maximum", "serialized"); _ = Integer(args, "maximum"); }
                else { Fields(args, "cache_dir", "key", "serialized"); _ = storage.CachePath(Text(args, "key")); }
                if (args.GetProperty("serialized").ValueKind != JsonValueKind.String) throw new LegacyExecutionProtocolException("Serialized persistence value must be a string.");
                serialized = args.GetProperty("serialized").GetString()!;
                using (var parsed = JsonDocument.Parse(serialized, new JsonDocumentOptions { MaxDepth = 128 })) { }
                string yes = CompletionFrames(++sequence, true), no = CompletionFrames(sequence, false), none = CompletionFrames(sequence, null);
                persistenceStarted = true;
                string reply;
                if (operation == "history-append") reply = storage.AppendHistory(serialized, Integer(args, "maximum")) ? yes : no;
                else { storage.WriteCache(Text(args, "key"), serialized); reply = none; }
                output.Write(reply); output.Flush(); return 0;
            default: throw new ArgumentException("Unsupported precision operation.");
        }
        Send("complete", ++sequence, Completion(payload)); return 0;
    }
    private static object Completion(object? payload) => D("state", "complete", "payload", payload, "exit", 0, "brief", null, "json_depth", 100, "queries", Array.Empty<object>(), "effects", Array.Empty<object>());
    private static string CompletionFrames(long id, object? payload)
    {
        var bytes = JsonSerializer.SerializeToUtf8Bytes(LegacyExecutionWire.Encode(J(Completion(payload))), JsonOptions);
        return JsonSerializer.Serialize(new { kind = "part", target = "complete", id, data = Convert.ToBase64String(bytes) }) + Environment.NewLine + JsonSerializer.Serialize(new { kind = "end", target = "complete", id }) + Environment.NewLine;
    }
    private JsonElement Project(JsonElement value, int depth, int maximumDepth)
    {
        if (value.ValueKind is not (JsonValueKind.Object or JsonValueKind.Array)) return value.Clone();
        if (depth > maximumDepth)
        {
            // PS5's depth cutoff uses LanguagePrimitives.ConvertTo with the
            // invariant culture. Acquire only that fixed, read-only conversion
            // for this retained subtree; never accept arbitrary replacement JSON.
            var text = Read("json-string", D("value", value));
            if (text.ValueKind != JsonValueKind.String) throw new LegacyExecutionProtocolException("JSON depth conversion must return one string.");
            return text;
        }
        return value.ValueKind == JsonValueKind.Array ? J(value.EnumerateArray().Select(v => Project(v, depth + 1, maximumDepth)).ToArray())
            : J(value.EnumerateObject().ToDictionary(p => p.Name, p => Project(p.Value, depth + 1, maximumDepth), StringComparer.Ordinal));
    }
    private static bool Equivalent(JsonElement expected, JsonElement actual)
    {
        if (expected.ValueKind != actual.ValueKind) return false;
        if (expected.ValueKind == JsonValueKind.Object)
        {
            var left = expected.EnumerateObject().ToArray(); var right = actual.EnumerateObject().ToArray();
            return left.Length == right.Length && right.Select(p => p.Name).Distinct(StringComparer.Ordinal).Count() == right.Length && left.All(p => right.Any(q => p.Name == q.Name && Equivalent(p.Value, q.Value)));
        }
        if (expected.ValueKind == JsonValueKind.Array) return expected.GetArrayLength() == actual.GetArrayLength() && expected.EnumerateArray().Zip(actual.EnumerateArray()).All(pair => Equivalent(pair.First, pair.Second));
        if (expected.ValueKind == JsonValueKind.Number) return expected.TryGetDecimal(out var a) && actual.TryGetDecimal(out var b) ? a == b : expected.GetDouble() == actual.GetDouble();
        return expected.ToString() == actual.ToString();
    }
    internal static JsonElement ReadStartup(TextReader reader)
    {
        string line = ReadBoundedLine(reader, 4194304) ?? throw new ArgumentException("Missing precision startup.");
        using var document = JsonDocument.Parse(line, new JsonDocumentOptions { MaxDepth = 128 }); return document.RootElement.Clone();
    }
    private static string? ReadBoundedLine(TextReader reader, int maximum)
    {
        var text = new StringBuilder();
        while (true)
        {
            int next = reader.Read();
            if (next < 0) return text.Length == 0 ? null : text.ToString();
            if (next == '\n') { if (text.Length > 0 && text[^1] == '\r') text.Length--; return text.ToString(); }
            if (text.Length >= maximum) throw new LegacyExecutionProtocolException("Precision line exceeds its character bound.");
            text.Append((char)next);
        }
    }
    private static string BuildOutcome(long id, bool? recorded)
    {
        var bytes = JsonSerializer.SerializeToUtf8Bytes(LegacyExecutionWire.Encode(J(D("recorded", recorded))), JsonOptions);
        return JsonSerializer.Serialize(new { kind = "part", target = "committed", id, data = Convert.ToBase64String(bytes) }) + Environment.NewLine + JsonSerializer.Serialize(new { kind = "end", target = "committed", id }) + Environment.NewLine;
    }
    private static void Fields(JsonElement value, params string[] expected)
    {
        string[] names = value.ValueKind == JsonValueKind.Object ? value.EnumerateObject().Select(p => p.Name).ToArray() : [];
        if (names.Length != expected.Length || names.Distinct(StringComparer.Ordinal).Count() != names.Length || expected.Any(n => !names.Contains(n))) throw new LegacyExecutionProtocolException("Invalid precision session fields.");
    }
}
