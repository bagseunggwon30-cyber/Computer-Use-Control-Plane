using System.Text.Json;

if (args.SequenceEqual(new[] { "--self-test" })) { InteractionChecks.Run(); InteractionBoundaryRegressionChecks.Run(); return; }
if (args.SequenceEqual(new[] { "--session-fixture" }))
{
    using var startup = JsonDocument.Parse(Console.In.ReadLine() ?? throw new InvalidOperationException("Missing fixture startup.")); var root = startup.RootElement;
    var argv = root.GetProperty("rest").EnumerateArray().Select(v => v.GetString()!).ToArray();
    var authority = new LegacyExecutionAuthority(root.GetProperty("allow_live").GetBoolean(), root.TryGetProperty("confirm_sensitive", out var c) && c.GetBoolean());
    Environment.ExitCode = new LegacyExecutionSession(Console.In, Console.Out).Run(e => new LegacyExecutionCoordinator(e, authority, argv).RunInteraction(root.GetProperty("operation").GetString()!));
    return;
}
if (args.SequenceEqual(new[] { "--fixtures" }))
{
    using var document = JsonDocument.Parse(Console.In.ReadToEnd(), new JsonDocumentOptions { MaxDepth = 128 });
    Console.WriteLine(JsonSerializer.Serialize(document.RootElement.EnumerateArray().Select(InteractionFixture.Evaluate).ToArray(), new JsonSerializerOptions { MaxDepth = 128 })); return;
}
Console.WriteLine("Use --fixtures with captured effect replies. This runner has no live executor.");

internal sealed class InteractionFixture : ILegacyExecutionEffects
{
    private readonly JsonElement fixture;
    private readonly List<object> trace = [], chunks = [];
    private readonly List<string> console = [], pipeline = [];
    private int cursor;
    private InteractionFixture(JsonElement fixture) { this.fixture = fixture; }
    internal static JsonElement J(object? value) => JsonSerializer.SerializeToElement(value);
    private static JsonElement P(JsonElement value, string name) => value.ValueKind == JsonValueKind.Object && value.TryGetProperty(name, out var p) ? p : J(null);
    private static string S(JsonElement v) => v.ValueKind == JsonValueKind.String ? v.GetString()! : "";
    public JsonElement Invoke(LegacyExecutionEffect effect)
    {
        if (effect.Kind == LegacyExecutionEffectKind.Clock) return J(effect.Name == "start" ? 0 : 37);
        if (effect.Kind == LegacyExecutionEffectKind.Timestamp) return J("2026-10-02T00:00:00.0000000Z");
        if (effect.Kind == LegacyExecutionEffectKind.ObservationId) return J("icon-click-0123456789ab");
        trace.Add(new { kind = effect.Kind.ToString(), name = effect.Name, argv = effect.Argv, data = effect.Data.Clone(), live = effect.Live, quiet = effect.Quiet, brief = effect.Brief, confirm_sensitive = effect.ConfirmSensitive });
        if (effect.Kind == LegacyExecutionEffectKind.Console)
        {
            string text = S(effect.Data); console.Add(text); chunks.Add(new { text, newline = effect.Name != "write" }); return J(null);
        }
        if (effect.Kind == LegacyExecutionEffectKind.PipelineOutput) { pipeline.Add(S(effect.Data)); return J(null); }
        if (effect.Kind is LegacyExecutionEffectKind.Notice or LegacyExecutionEffectKind.Sleep or LegacyExecutionEffectKind.TrajectoryAppend or LegacyExecutionEffectKind.PointCacheWrite) return J(null);
        var replies = P(fixture, "replies");
        if (replies.ValueKind != JsonValueKind.Array || cursor >= replies.GetArrayLength()) throw new LegacyExecutionProtocolException("Fixture exhausted at " + effect.Kind + ":" + effect.Name);
        var captured = replies[cursor++];
        if (P(captured, "throw").ValueKind == JsonValueKind.String) throw new LegacyExecutionEffectException(S(P(captured, "throw")), P(captured, "mutation_may_have_occurred").ValueKind == JsonValueKind.True);
        return captured;
    }
    internal static object Evaluate(JsonElement fixture)
    {
        var capture = new InteractionFixture(fixture);
        try
        {
            var rest = P(fixture, "rest").EnumerateArray().Select(v => v.ValueKind == JsonValueKind.Null ? "" : v.GetString()!).ToArray();
            var authority = new LegacyExecutionAuthority(P(fixture, "allow_live").ValueKind == JsonValueKind.True, P(fixture, "confirm_sensitive").ValueKind == JsonValueKind.True);
            var machine = new LegacyExecutionCoordinator(capture, authority, rest, P(fixture, "brief").ValueKind == JsonValueKind.True,
                P(fixture, "cache_seconds").ValueKind == JsonValueKind.Number ? P(fixture, "cache_seconds").GetInt32() : 5);
            var result = machine.RunInteraction(S(P(fixture, "operation")), P(fixture, "double").ValueKind == JsonValueKind.True, P(fixture, "right_click").ValueKind == JsonValueKind.True);
            if (result.Brief is not null) { capture.console.Add(result.Brief); capture.chunks.Add(new { text = result.Brief, newline = true }); }
            return new { state = "complete", payload = result.Payload, exit = result.Exit, json_depth = result.JsonDepth, brief = result.Brief, emit_json = result.EmitJson,
                console = capture.console, console_chunks = capture.chunks, pipeline = capture.pipeline, effects = capture.trace, consumed = capture.cursor };
        }
        catch (Exception error)
        { return new { state = "error", error = error.Message, effects = capture.trace, console = capture.console, console_chunks = capture.chunks, pipeline = capture.pipeline, consumed = capture.cursor }; }
    }
}
