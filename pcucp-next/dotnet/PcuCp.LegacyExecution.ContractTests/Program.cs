using System.Text.Json;

if (args.SequenceEqual(new[] { "--session-fixture" }))
{
    // Disposable test process only. This mode supplies no effect implementation.
    using var startup = JsonDocument.Parse(Console.In.ReadLine() ?? throw new InvalidOperationException("Missing fixture startup."));
    var root = startup.RootElement;
    var rest = root.GetProperty("rest").EnumerateArray().Select(v => v.GetString()!).ToArray();
    var authority = new LegacyExecutionAuthority(root.GetProperty("allow_live").GetBoolean(), root.GetProperty("confirm_sensitive").GetBoolean());
    Environment.ExitCode = new LegacyExecutionSession(Console.In, Console.Out).Run(root.GetProperty("operation").GetString()!, rest, authority);
    return;
}
if (args.SequenceEqual(new[] { "--self-test" })) { ExecutionChecks.Run(); return; }
if (args.SequenceEqual(new[] { "--fixtures" }))
{
    using var document = JsonDocument.Parse(Console.In.ReadToEnd(), new JsonDocumentOptions { MaxDepth = 128 });
    var results = document.RootElement.EnumerateArray().Select(ExecutionFixture.Evaluate).ToArray();
    Console.WriteLine(JsonSerializer.Serialize(results, new JsonSerializerOptions { MaxDepth = 128 }));
    return;
}
Console.WriteLine("Use --fixtures with captured effect replies. This runner has no live executor.");

internal sealed class ExecutionFixture : ILegacyExecutionEffects
{
    private readonly JsonElement fixture;
    private readonly List<object> trace = [];
    private readonly List<string> console = [];
    private int cursor;
    private ExecutionFixture(JsonElement fixture) { this.fixture = fixture; }
    private static JsonElement J(object? value) => JsonSerializer.SerializeToElement(value);
    private static JsonElement P(JsonElement v, string n) => v.ValueKind == JsonValueKind.Object && v.TryGetProperty(n, out var p) ? p : J(null);
    private static string S(JsonElement v) => v.ValueKind == JsonValueKind.String ? v.GetString()! : "";
    public JsonElement Invoke(LegacyExecutionEffect effect)
    {
        if (effect.Kind == LegacyExecutionEffectKind.Clock) return J(effect.Name == "start" ? 0 : 37);
        if (effect.Kind == LegacyExecutionEffectKind.Timestamp) return J(effect.Name == "o" ? "2026-10-02T00:00:00.0000000Z" : "000000-000");
        if (effect.Kind == LegacyExecutionEffectKind.CachePath) return J("C:\\fixture\\" + effect.Name + "-" + S(effect.Data) + ".png");
        trace.Add(new { kind = effect.Kind.ToString(), name = effect.Name, argv = effect.Argv, data = effect.Data, live = effect.Live, quiet = effect.Quiet, brief = effect.Brief, confirm_sensitive = effect.ConfirmSensitive });
        if (effect.Kind == LegacyExecutionEffectKind.Console) { console.Add(S(effect.Data)); return J(null); }
        if (effect.Kind is LegacyExecutionEffectKind.Sleep or LegacyExecutionEffectKind.TrajectoryAppend or LegacyExecutionEffectKind.HistoryAppend or LegacyExecutionEffectKind.RemoveFile) return J(null);
        var captures = P(fixture, "replies");
        if (captures.ValueKind != JsonValueKind.Array || cursor >= captures.GetArrayLength()) throw new LegacyExecutionProtocolException("Fixture exhausted at " + effect.Kind + ":" + effect.Name);
        var captured = captures[cursor++];
        if (P(captured, "throw").ValueKind == JsonValueKind.String) throw new LegacyExecutionEffectException(S(P(captured, "throw")), P(captured, "mutation_may_have_occurred").ValueKind == JsonValueKind.True);
        return captured;
    }
    internal static object Evaluate(JsonElement fixture)
    {
        var capture = new ExecutionFixture(fixture);
        try
        {
            var rest = P(fixture, "rest").EnumerateArray().Select(v => v.ValueKind == JsonValueKind.Null ? "" : v.GetString()!).ToArray();
            var authority = new LegacyExecutionAuthority(P(fixture, "allow_live").ValueKind == JsonValueKind.True,
                P(fixture, "confirm_sensitive").ValueKind == JsonValueKind.True);
            var machine = new LegacyExecutionCoordinator(capture, authority, rest, P(fixture, "brief").ValueKind == JsonValueKind.True,
                P(fixture, "cache_seconds").ValueKind == JsonValueKind.Number ? P(fixture, "cache_seconds").GetInt32() : 5,
                P(fixture, "vision_available").ValueKind == JsonValueKind.True);
            var result = machine.Run(S(P(fixture, "operation")));
            if (result.Brief is not null) capture.console.Add(result.Brief);
            return new { state = "complete", payload = result.Payload, exit = result.Exit, json_depth = result.JsonDepth, brief = result.Brief,
                emit_json = result.EmitJson, console = capture.console, effects = capture.trace, consumed = capture.cursor };
        }
        catch (Exception error) when (error is NativeFailure or LegacyExecutionEffectException or LegacyExecutionProtocolException or LegacyExecutionPostDispatchException)
        { return new { state = "error", error = error.Message, effects = capture.trace, console = capture.console, consumed = capture.cursor }; }
    }
}
