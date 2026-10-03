using System.Globalization;
using System.Text.Json;

if (args.SequenceEqual(new[] { "--fixtures" }))
{
    using var document = JsonDocument.Parse(Console.In.ReadToEnd(), new JsonDocumentOptions { MaxDepth = 128 });
    Console.WriteLine(JsonSerializer.Serialize(document.RootElement.EnumerateArray().Select(DiagnosticFixture.Evaluate).ToArray()));
    return;
}
if (args.SequenceEqual(new[] { "--self-test" })) { DiagnosticChecks.Run(); DiagnosticBoundaryRegressionChecks.Run(); DiagnosticSubtractionChecks.Run(); DiagnosticJsonObservedChecks.Run(); DiagnosticNumberDisplayChecks.Run(); return; }
Console.WriteLine("Use --fixtures or --self-test. This runner never dispatches a real acquisition or write.");

internal sealed class DiagnosticFixture(JsonElement fixture) : ILegacyDiagnosticEffects
{
    internal readonly List<object> Trace = [];
    internal int Cursor;
    private int clockCursor;
    private static JsonElement J(object? v) => JsonSerializer.SerializeToElement(v);
    private static JsonElement P(JsonElement v, string n) => v.ValueKind == JsonValueKind.Object && v.TryGetProperty(n, out var p) ? p : J(null);
    private static string S(JsonElement v) => v.ValueKind == JsonValueKind.String ? v.GetString()! : "";
    public JsonElement Invoke(LegacyDiagnosticEffect effect)
    {
        Trace.Add(new { kind = effect.Kind.ToString(), name = effect.Name, argv = effect.Argv, data = effect.Data });
        if (effect.Kind == LegacyDiagnosticEffectKind.Timestamp) return J("2026-10-02T00:00:00.0000000Z");
        if (effect.Kind == LegacyDiagnosticEffectKind.Clock)
        {
            if (effect.Name == "start") return J(0);
            var clocks = P(fixture, "clocks");
            int time = clocks.ValueKind == JsonValueKind.Array && clockCursor < clocks.GetArrayLength() ? clocks[clockCursor].GetInt32() : 37;
            if (effect.Name == "stop") clockCursor++;
            return J(time);
        }
        if (effect.Kind is LegacyDiagnosticEffectKind.Sleep or LegacyDiagnosticEffectKind.Notice) return J(null);
        var replies = P(fixture, "replies");
        if (replies.ValueKind != JsonValueKind.Array || Cursor >= replies.GetArrayLength()) throw new LegacyExecutionProtocolException("Fixture exhausted at " + effect.Kind + ":" + effect.Name);
        var reply = replies[Cursor++];
        if (P(reply, "throw").ValueKind == JsonValueKind.String) throw new LegacyDiagnosticEffectException(S(P(reply, "throw")));
        return reply.Clone();
    }
    internal static LegacyDiagnosticContext Context(JsonElement fixture)
    {
        var c = P(fixture, "context"); string Value(string name, string fallback) => P(c, name).ValueKind == JsonValueKind.String ? S(P(c, name)) : fallback;
        string? cli = c.ValueKind == JsonValueKind.Object && c.TryGetProperty("cli_path", out var cliValue) && cliValue.ValueKind == JsonValueKind.Null ? null : Value("cli_path", "C:\\fixture\\cli.mjs");
        return new(Value("audit_dir", "C:\\fixture\\audit"), Value("cache_dir", "C:\\fixture\\cache"),
            Value("wrapper_log", "C:\\fixture\\wrapper.log"), cli,
            Value("changelog_path", "C:\\fixture\\CHANGELOG.md"), Value("temp_root", "C:\\fixture\\computer-use-control-plane"));
    }
    internal static object Evaluate(JsonElement fixture)
    {
        var capture = new DiagnosticFixture(fixture); var previous = CultureInfo.CurrentCulture;
        try
        {
            CultureInfo.CurrentCulture = CultureInfo.GetCultureInfo(P(fixture, "culture").ValueKind == JsonValueKind.String ? S(P(fixture, "culture")) : "en-US");
            var rest = P(fixture, "rest").EnumerateArray().Select(v => v.ValueKind == JsonValueKind.Null ? "" : v.GetString()!).ToArray();
            var result = new LegacyDiagnosticCoordinator(capture, rest, Context(fixture), P(fixture, "brief").ValueKind == JsonValueKind.True).Run(S(P(fixture, "operation")));
            return new { state = "complete", payload = result.Payload, exit = result.Exit, json_depth = result.JsonDepth,
                brief = result.Brief, emit_json = result.EmitJson, hashtable_paths = result.HashtablePaths, effects = capture.Trace, consumed = capture.Cursor };
        }
        catch (Exception error) { return new { state = "error", error = error.Message, effects = capture.Trace, consumed = capture.Cursor }; }
        finally { CultureInfo.CurrentCulture = previous; }
    }
}

internal static class DiagnosticChecks
{
    private static int checks;
    private static JsonElement J(object? v) => JsonSerializer.SerializeToElement(v);
    private static JsonElement Run(string operation, object?[] replies, string[]? rest = null, int[]? clocks = null) =>
        J(DiagnosticFixture.Evaluate(J(new { operation, replies, rest = rest ?? [], clocks })));
    private static void Check(bool value, string message) { checks++; if (!value) throw new InvalidOperationException(message); }
    internal static void Run()
    {
        var benchmark = Run("benchmark", Enumerable.Repeat<object?>(new { exit = 0, json = new { status = "ok" } }, 12).ToArray());
        Check(benchmark.GetProperty("state").GetString() == "complete", "benchmark completes");
        Check(benchmark.GetProperty("payload").GetProperty("slo_pass_count").GetInt32() == 4, "benchmark SLO");
        var mixed = Enumerable.Repeat<object?>(new { exit = 0, json = new { status = "ok" } }, 12).ToArray(); mixed[0] = new { exit = 1, json = new { status = "ok" } };
        var mixedResult = Run("benchmark", mixed).GetProperty("payload");
        Check(mixedResult.GetProperty("slo_pass_count").GetInt32() == 3, "accepted all-samples-success correction retained");
        Check(mixedResult.GetProperty("results")[0].GetProperty("failure_count").GetInt32() == 1, "partial benchmark failure count");
        var bad = Run("perf", [], ["--iters", "bad"]); Check(bad.GetProperty("state").GetString() == "error", "legacy int error");
        Check(bad.GetProperty("effects").GetArrayLength() == 0, "option error precedes effects");
        var wire = J(new { value = new[] { "retain" }, Count = 1 });
        Check(LegacyExecutionWire.Decode(J(LegacyExecutionWire.Encode(wire))).GetRawText() == wire.GetRawText(), "shared tagged codec object preservation");
        var missing = Run("log-tail", [false]);
        Check(missing.GetProperty("exit").GetInt32() == 2, "missing log partial exit");
        Check(missing.GetProperty("payload").GetProperty("data").GetProperty("lines").GetArrayLength() == 0, "missing log empty array");
        var tail = Run("log-tail", [true, new { total_bytes = 100, tail_bytes = 100, text = "INFO a\nERROR password=synthetic token=synthetic\n" }]);
        var data = tail.GetProperty("payload").GetProperty("data");
        Check(data.GetProperty("redacted_count").GetInt32() == 2, "redaction count is per matched pattern and line");
        Check(data.GetProperty("lines")[1].GetString() == "ERROR [redacted] [redacted]", "redaction precedence");
        var audit = Run("audit-summary", [false]);
        Check(audit.GetProperty("payload").GetProperty("status").GetString() == "empty", "audit empty");
        var unknown = Run("cleanup", []); Check(unknown.GetProperty("state").GetString() == "error", "cleanup remains excluded");
        Check(unknown.GetProperty("effects").GetArrayLength() == 0, "unknown operation has no effects");
        Console.WriteLine($"Passed {checks} diagnostic managed contracts.");
    }
}
