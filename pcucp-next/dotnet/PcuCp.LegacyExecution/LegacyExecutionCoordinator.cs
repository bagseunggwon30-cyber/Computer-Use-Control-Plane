using System.Globalization;
using System.Text.Json;

internal sealed partial class LegacyExecutionCoordinator
{
    private readonly ILegacyExecutionEffects effects;
    private readonly LegacyExecutionAuthority authority;
    private readonly bool brief;
    private readonly string[] rest;
    private readonly int cacheSeconds;
    private readonly bool visionAvailable;
    private static readonly StringComparer Comparer = StringComparer.InvariantCultureIgnoreCase;
    private static readonly JsonElement Null = JsonSerializer.SerializeToElement<object?>(null);
    internal LegacyExecutionCoordinator(ILegacyExecutionEffects effects, LegacyExecutionAuthority authority,
        string[] rest, bool brief = false, int cacheSeconds = 5, bool visionAvailable = false)
    {
        this.effects = effects; this.authority = authority with { }; this.rest = rest.Select(v => v ?? "").ToArray();
        this.brief = brief; this.cacheSeconds = cacheSeconds; this.visionAvailable = visionAvailable;
    }
    internal LegacyExecutionResult Run(string operation)
    {
        try
        {
            return operation switch
            {
                "workflow-run" => Workflow(), "task-run" => TaskRun(), "form-run" => FormRun(),
                "smart-click" => SmartClick(), "watch" => Watch(), "recovery-plan" => RecoveryPlan(),
                "recovery-run" => RecoveryRun(), _ => throw CommandOptions.Invalid("Unknown execution family operation.")
            };
        }
        catch (LegacyExecutionUncertainException uncertain)
        {
            var payload = D("schema", "cucp." + operation + "/v1", "status", "partial", "reason", "mutation_may_have_occurred",
                "mutation_may_have_occurred", true, "effect", D("kind", uncertain.Effect.Kind.ToString(), "name", uncertain.Effect.Name, "argv", uncertain.Effect.Argv),
                "result", Parsed(uncertain.Reply), "raw", Raw(uncertain.Reply), "next_action", "Inspect the target and re-ground before deciding whether another action is safe.");
            return Result(payload, 2, 14, $"partial {operation} reason=mutation_may_have_occurred strategy=stopped");
        }
    }
    private static Dictionary<string, object?> D(params object?[] values)
    {
        var result = new Dictionary<string, object?>();
        for (int i = 0; i < values.Length; i += 2) result.Add((string)values[i]!, values[i + 1]);
        return result;
    }
    private static JsonElement J(object? value) => value is JsonElement node ? node.Clone() : JsonSerializer.SerializeToElement(value);
    private static JsonElement P(JsonElement value, string name)
    {
        if (value.ValueKind == JsonValueKind.Object)
            foreach (var item in value.EnumerateObject()) if (Comparer.Equals(item.Name, name)) return item.Value;
        return Null;
    }
    private static bool T(JsonElement value) => value.ValueKind switch
    {
        JsonValueKind.Null or JsonValueKind.Undefined or JsonValueKind.False => false,
        JsonValueKind.True or JsonValueKind.Object => true,
        JsonValueKind.String => value.GetString()!.Length > 0,
        JsonValueKind.Number => value.GetDouble() != 0,
        JsonValueKind.Array => value.GetArrayLength() > 1 || value.GetArrayLength() == 1 && T(value[0]), _ => false
    };
    private static JsonElement[] A(JsonElement value) => value.ValueKind is JsonValueKind.Null or JsonValueKind.Undefined
        ? [] : value.ValueKind == JsonValueKind.Array ? value.EnumerateArray().ToArray() : [value];
    private static string S(JsonElement value) => value.ValueKind switch
    {
        JsonValueKind.Null or JsonValueKind.Undefined => "", JsonValueKind.String => value.GetString()!,
        JsonValueKind.True => "True", JsonValueKind.False => "False",
        JsonValueKind.Array => string.Join(" ", A(value).Select(S)),
        JsonValueKind.Object => "@{" + string.Join("; ", value.EnumerateObject().Select(p => p.Name + "=" + S(p.Value))) + "}",
        _ => value.GetRawText()
    };
    private static int I(JsonElement value) => LegacyTaskFormKernel.LegacyInt(value.ValueKind == JsonValueKind.Undefined ? Null : value);
    private static int I(string? value) => LegacyTaskFormKernel.LegacyInt(value);
    private static bool Eq(JsonElement value, string text) => Comparer.Equals(S(value), text);
    private string? V(string name)
    {
        for (int i = 0; i + 1 < rest.Length; i++) if (Comparer.Equals(rest[i], name)) return rest[i + 1];
        return null;
    }
    private bool F(string name) => rest.Contains(name, Comparer);
    private bool Confirm => LegacyExecutionConsent.HasStandaloneConfirmation(rest) && authority.ConfirmSensitive;
    private static bool Has(string? text) => !string.IsNullOrEmpty(text);
    private bool RenderBrief => brief && !F("--json-only");
    private void Live(string message) { if (!authority.AllowLiveControl) throw CommandOptions.Invalid(message); }
    private JsonElement Effect(LegacyExecutionEffectKind kind, string name = "", string[]? argv = null, object? data = null,
        bool live = false, bool quiet = false, bool childBrief = false, bool confirm = false)
    {
        if (live && !authority.AllowLiveControl) throw new LegacyExecutionProtocolException("Live effect exceeds immutable startup authority.");
        if (confirm && !authority.ConfirmSensitive) throw new LegacyExecutionProtocolException("Sensitive effect exceeds immutable startup authority.");
        var descriptor = new LegacyExecutionEffect(kind, name, argv ?? [], J(data), live, quiet, childBrief, confirm);
        JsonElement reply;
        try { reply = effects.Invoke(descriptor).Clone(); }
        catch (LegacyExecutionEffectException error) when (!live && error.MutationMayHaveOccurred)
        {
            throw new LegacyExecutionPostDispatchException(error.Message);
        }
        catch (LegacyExecutionEffectException error) when (live && error.MutationMayHaveOccurred)
        {
            reply = J(D("exit", 2, "raw", error.Message, "json", D("status", "partial", "reason", "effect_failed_after_possible_mutation", "detail", error.Message, "mutation_may_have_occurred", true)));
        }
        if (live && kind is LegacyExecutionEffectKind.Native or LegacyExecutionEffectKind.LocalMacro or LegacyExecutionEffectKind.SendEscape && Uncertain(reply))
            throw new LegacyExecutionUncertainException(descriptor, reply);
        return reply;
    }
    private JsonElement Child(IEnumerable<string> command, bool live = false, bool quiet = true, bool childBrief = false, bool confirm = false, bool direct = false) =>
        Effect(LegacyExecutionEffectKind.Child, name: direct ? "direct" : "", argv: command.ToArray(), live: live, quiet: quiet, childBrief: childBrief, confirm: confirm);
    private JsonElement Native(params string[] argv) => Effect(LegacyExecutionEffectKind.Native, argv: argv, live: IsNativeLive(argv));
    private static bool IsNativeLive(string[] argv) => argv.Length > 1 && argv[1] is "uia-invoke" or "uia-click" or "click" or "ocr-uia-invoke" or "cdp-smart-click";
    private void Sleep(int ms) => Effect(LegacyExecutionEffectKind.Sleep, data: ms);
    private void Start(string scope) => Effect(LegacyExecutionEffectKind.Clock, "start", data: scope);
    private int Stop(string scope) => I(Effect(LegacyExecutionEffectKind.Clock, "stop", data: scope));
    private int Elapsed(string scope) => I(Effect(LegacyExecutionEffectKind.Clock, "elapsed", data: scope));
    private void Append(string kind, object payload)
    {
        try { Effect(LegacyExecutionEffectKind.TrajectoryAppend, kind, data: payload); }
        catch (LegacyExecutionEffectException) { }
    }
    private static bool Uncertain(JsonElement reply) => P(reply, "mutation_may_have_occurred").ValueKind == JsonValueKind.True ||
        P(P(reply, "json"), "mutation_may_have_occurred").ValueKind == JsonValueKind.True;
    private static JsonElement Parsed(JsonElement reply) => P(reply, "json");
    private static object? Raw(JsonElement reply) => T(Parsed(reply)) ? null : P(reply, "raw");
    private LegacyExecutionResult Result(object? payload, int exit, int depth, string? line = null, bool? renderBrief = null)
    {
        // Dictionary insertion order is observable in the legacy Console JSON.
        if (payload is Dictionary<string, object?> p && p.TryGetValue("schema", out var schema) && Equals(schema, "cucp.form-run/v1"))
        {
            string[] order = ["schema", "status", "reason", "dry_run", "confirm_sensitive", "safe_to_act", "executed_count", "failed_count", "sensitive_step_count", "safety_issues", "confirmation_flag", "total_steps", "elapsed_ms", "plan_elapsed_ms", "plan_exit", "plan_raw", "command_plan", "unsafe_steps", "plan_errors", "plan", "steps", "next_action"];
            payload = order.Where(p.ContainsKey).ToDictionary(k => k, k => p[k]);
        }
        return new(J(payload), exit, depth, (renderBrief ?? RenderBrief) ? line : null, !(renderBrief ?? RenderBrief));
    }
    private static string[] Strings(JsonElement value) => A(value).Select(S).ToArray();
    private string[] PlanArgs(bool workflow = false)
    {
        var skip = new HashSet<string>(["--json-only", "--dry-run", "--continue-on-error", "--include-plan", "--confirm-sensitive"], Comparer);
        var values = new HashSet<string>(Comparer);
        if (workflow)
        {
            skip.UnionWith(["--observe-after-step", "--verify-after-step", "--retry-live-steps"]);
            values.UnionWith(["--settle-ms", "--observe-match", "--verify-match", "--verify-label-after-step", "--verify-after-label", "--verify-label-window", "--verify-label-timeout-ms", "--verify-label-interval-ms", "--retry-failed-step", "--retry-delay-ms"]);
        }
        var result = new List<string>();
        for (int i = 0; i < rest.Length; i++) { if (skip.Contains(rest[i])) continue; if (values.Contains(rest[i])) { i++; continue; } result.Add(rest[i]); }
        return result.ToArray();
    }
}
