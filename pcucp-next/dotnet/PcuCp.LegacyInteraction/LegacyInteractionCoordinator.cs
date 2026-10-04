using System.Globalization;
using System.Text.Json;
using System.Text.RegularExpressions;

// Interaction orchestration shares the qualified execution authority and wire.
// Every external dependency is a closed effect; this file has no OS/process API.
internal sealed partial class LegacyExecutionCoordinator
{
    private bool interactionDispatched;
    internal LegacyExecutionResult RunInteraction(string operation, bool doubleClick = false, bool rightClick = false)
    {
        try
        {
            return operation switch
            {
                "find-label" => FindLabel(), "icon-find" => IconFind(), "icon-click" => IconClick(),
                "click-label" => ClickLabel(doubleClick, rightClick), "double-click-label" => ClickLabel(true, false),
                "right-click-label" => ClickLabel(false, true), "click-point" => ClickPoint(),
                "safe-type" => SafeType(), "ocr-click" => OcrClick(), "precision-validate" => PrecisionValidate(),
                _ => throw CommandOptions.Invalid("Unknown interaction family operation.")
            };
        }
        catch (LegacyExecutionUncertainException uncertain)
        {
            return Result(D("schema", "cucp." + operation + "/v1", "status", "partial", "reason", "mutation_may_have_occurred",
                "mutation_may_have_occurred", true, "automatic_retry", false,
                "effect", D("kind", uncertain.Effect.Kind.ToString(), "name", uncertain.Effect.Name, "argv", uncertain.Effect.Argv),
                "result", Parsed(uncertain.Reply), "raw", Raw(uncertain.Reply),
                "next_action", "Inspect the target and re-ground before deciding whether another action is safe."), 2, 14,
                $"partial {operation} reason=mutation_may_have_occurred strategy=stopped", renderBrief: brief);
        }
    }
    private JsonElement IE(LegacyExecutionEffectKind kind, object? data = null, string[]? argv = null, string name = "", bool live = false)
    {
        // Flags are derived by the kernel, never from a reply or command argument.
        if (live) interactionDispatched = true;
        JsonElement reply;
        try { reply = Effect(kind, name, argv, data, live); }
        catch (LegacyExecutionEffectException error) when (!live && interactionDispatched)
        { throw new LegacyExecutionPostDispatchException(error.Message); }
        if (live && Uncertain(reply)) throw new LegacyExecutionUncertainException(new(kind, name, argv ?? [], J(data), live), reply);
        return reply;
    }
    private JsonElement INative(params string[] argv)
    {
        if (argv.Length < 2 || argv[0] != "-Action") throw new LegacyExecutionProtocolException("Invalid interaction native descriptor.");
        bool live = argv[1] switch
        {
            "focus" or "click" or "type" or "shortcut" => true,
            "windows" or "ocr-find-text" or "hit-scan" => false,
            _ => throw new LegacyExecutionProtocolException("Unknown interaction native action.")
        };
        return IE(LegacyExecutionEffectKind.Native, argv: argv, live: live);
    }
    private JsonElement Appshot(string? match, bool noCache = false) => IE(LegacyExecutionEffectKind.Appshot, D("match", match ?? "", "semantic", true, "no_cache", noCache));
    private JsonElement Act(List<string> argv) => IE(LegacyExecutionEffectKind.Cucp, argv: argv.ToArray(), live: true);
    private void Notice(string level, string message) => IE(LegacyExecutionEffectKind.Notice, message, name: level);
    private void Pipeline(string message) => IE(LegacyExecutionEffectKind.PipelineOutput, message);
    private void Trace(string kind, object payload) => IE(LegacyExecutionEffectKind.TrajectoryAppend, payload, name: kind);
    private static JsonElement ExitValue(JsonElement reply) => P(reply, "ExitCode").ValueKind == JsonValueKind.Null ? P(reply, "exit") : P(reply, "ExitCode");
    private static int ExitOf(JsonElement reply) => I(ExitValue(reply));
    private static bool ExitIsZero(JsonElement reply) => ExitValue(reply).ValueKind != JsonValueKind.Null && ExitOf(reply) == 0;
    private static JsonElement Member(JsonElement value, string name)
    {
        if (value.ValueKind != JsonValueKind.Array) return P(value, name);
        var members = value.EnumerateArray().Select(v => Member(v, name)).ToArray();
        return members.Length == 1 ? members[0] : J(members);
    }
    private static bool EqualAny(JsonElement value, string text) => value.ValueKind == JsonValueKind.Array
        ? value.EnumerateArray().Any(v => EqualAny(v, text)) : Eq(value, text);
    private static bool Ok(JsonElement reply) => T(Parsed(reply)) && EqualAny(Member(Parsed(reply), "status"), "ok");
    private static string Num(int n) => n.ToString(CultureInfo.InvariantCulture);
    private static long Long(JsonElement value) => LegacyPrecisionKernel.L(value);
    private static double Number(JsonElement value) => LegacyPrecisionKernel.N(value);
    private static int Round(double n) => Convert.ToInt32(n);
    private static string Lower(string s) => LegacyTextKernel.LowerValue(s, CultureInfo.InvariantCulture);
    private static string Normal(string s) => Regex.Replace(Lower(s).Trim(), @"\s+", " ").Trim();
    private static object? Pipe(IEnumerable<object?> source) { var a = source.ToArray(); return a.Length == 0 ? null : a.Length == 1 ? a[0] : a; }
    private static Dictionary<string, object?> Object(JsonElement value) => value.ValueKind == JsonValueKind.Object ? value.EnumerateObject().ToDictionary(p => p.Name, p => (object?)p.Value.Clone()) : D();
    private static (int X, int Y) Center(JsonElement element)
    {
        var rect = P(element, "rect"); return (Round(Number(P(rect, "x")) + Number(P(rect, "width")) / 2), Round(Number(P(rect, "y")) + Number(P(rect, "height")) / 2));
    }
    private LegacyExecutionResult Silent(int exit, string? line = null) => new(Null, exit, 0, brief ? line : null, false);
    private LegacyExecutionResult RawResult(JsonElement reply, string? line)
    {
        if (!brief && T(P(reply, "raw"))) IE(LegacyExecutionEffectKind.Console, S(P(reply, "raw")), name: "write");
        return Silent(ExitOf(reply), line);
    }
    private object Envelope(string status, int elapsed, object? data, object[] sources, string confidence = "high", object? recoverable = null,
        string observationId = "", object? foreground = null, object? cache = null) => D(
        "schema", "cucp.observation/v1", "kind", "find-label", "status", status,
        "collected_at", Effect(LegacyExecutionEffectKind.Timestamp, "o"), "elapsed_ms", elapsed, "sources", sources,
        "provenance", null, "observation_id", observationId, "foreground", foreground, "active_hwnd", 0,
        "focused_title", foreground is null ? "" : S(P(J(foreground), "title")), "desktop", null, "windows", null,
        "data", data, "cache", cache, "stale", false, "confidence", confidence, "warnings", Array.Empty<object>(),
        "recoverable_errors", recoverable ?? Array.Empty<object>(), "degraded_helper_empty", false);
}
