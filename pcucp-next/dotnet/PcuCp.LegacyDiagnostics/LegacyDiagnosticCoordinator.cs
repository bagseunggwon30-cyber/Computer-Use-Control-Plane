using System.Globalization;
using System.Text.Json;

internal sealed partial class LegacyDiagnosticCoordinator
{
    private readonly ILegacyDiagnosticEffects effects;
    private readonly string[] rest;
    private readonly bool brief;
    private readonly JsonElement context;
    private readonly LegacyDiagnosticContext paths;
    private string operation = "";
    private static readonly StringComparer Comparer = StringComparer.InvariantCultureIgnoreCase;
    private static readonly JsonElement Null = JsonSerializer.SerializeToElement<object?>(null);
    internal LegacyDiagnosticCoordinator(ILegacyDiagnosticEffects effects, string[] rest,
        LegacyDiagnosticContext context, bool brief = false)
    {
        this.effects = effects; this.rest = rest.Select(v => v ?? "").ToArray(); this.brief = brief;
        paths = context with { };
        this.context = J(D("audit_dir", paths.AuditDirectory, "cache_dir", paths.CacheDirectory,
            "wrapper_log", paths.WrapperLog, "cli_path", paths.CliPath, "changelog_path", paths.ChangelogPath,
            "temp_root", paths.TempRoot, "benchmark_schema", paths.BenchmarkSchema, "release_schema", paths.ReleaseSchema));
    }
    internal LegacyDiagnosticResult Run(string command)
    {
        operation = command;
        return command switch
        {
            "perf" => Perf(), "diagnose-lag" => DiagnoseLag(), "health-quick" => HealthQuick(),
            "health-detail" => HealthDetail(), "log-tail" => LogTail(), "benchmark" => Benchmark(),
            "self-test" => SelfTest(), "audit-summary" => AuditSummary(), "release-notes" => ReleaseNotes(),
            _ => throw new LegacyExecutionProtocolException("Unknown diagnostic operation.")
        };
    }
    private static Dictionary<string, object?> D(params object?[] values)
    {
        var d = new Dictionary<string, object?>();
        for (int i = 0; i < values.Length; i += 2) d.Add((string)values[i]!, values[i + 1]);
        return d;
    }
    private static JsonElement J(object? v) => v is JsonElement j ? j.Clone() : JsonSerializer.SerializeToElement(v);
    private static JsonElement P(JsonElement v, string key)
    {
        if (v.ValueKind == JsonValueKind.Object)
            foreach (var p in v.EnumerateObject()) if (Comparer.Equals(p.Name, key)) return p.Value;
        return Null;
    }
    private static bool T(JsonElement v) => v.ValueKind switch
    {
        JsonValueKind.Null or JsonValueKind.Undefined or JsonValueKind.False => false,
        JsonValueKind.True or JsonValueKind.Object => true, JsonValueKind.String => v.GetString()!.Length != 0,
        JsonValueKind.Number => v.GetDouble() != 0, JsonValueKind.Array => v.GetArrayLength() > 1 || v.GetArrayLength() == 1 && T(v[0]), _ => false
    };
    private static JsonElement[] A(JsonElement v) => v.ValueKind is JsonValueKind.Null or JsonValueKind.Undefined ? [] : v.ValueKind == JsonValueKind.Array ? v.EnumerateArray().ToArray() : [v];
    private static string S(JsonElement v) => v.ValueKind switch
    {
        JsonValueKind.Null or JsonValueKind.Undefined => "", JsonValueKind.String => v.GetString()!,
        JsonValueKind.True => "True", JsonValueKind.False => "False", JsonValueKind.Array => string.Join(" ", A(v).Select(S)),
        JsonValueKind.Object => "@{" + string.Join("; ", v.EnumerateObject().Select(p => p.Name + "=" + S(p.Value))) + "}", _ => v.GetRawText()
    };
    private static int I(JsonElement v) => LegacyTaskFormKernel.LegacyInt(v);
    private static int I(string? v) => LegacyTaskFormKernel.LegacyInt(v);
    private static double N(JsonElement v) => v.ValueKind == JsonValueKind.Number ? v.GetDouble() : T(v) ? Convert.ToDouble(S(v), CultureInfo.InvariantCulture) : 0;
    private static long L(JsonElement v) => Convert.ToInt64(N(v));
    private static bool Eq(JsonElement v, string s) => Comparer.Equals(S(v), s);
    private string? V(string name) { for (int i = 0; i + 1 < rest.Length; i++) if (Comparer.Equals(rest[i], name)) return rest[i + 1]; return null; }
    private bool F(string name) => rest.Contains(name, Comparer);
    private bool RenderBrief => brief && !F("--json-only");
    private static bool Has(string? s) => !string.IsNullOrEmpty(s);
    private JsonElement Effect(LegacyDiagnosticEffectKind kind, string name = "", string[]? argv = null, object? data = null)
    {
        // These two bounded maintenance capabilities cannot acquire their target
        // from a process/file reply. The future host must independently enforce it.
        if (kind == LegacyDiagnosticEffectKind.ClearAppshotCache && (operation != "perf" || !F("--include-live-ish") || S(J(data)) != paths.CacheDirectory))
            throw new LegacyExecutionProtocolException("Cache clear exceeds diagnostic invocation scope.");
        if (kind == LegacyDiagnosticEffectKind.AuditProbe && (operation is not ("health-quick" or "health-detail") || S(J(data)) != paths.AuditDirectory))
            throw new LegacyExecutionProtocolException("Audit probe exceeds diagnostic owned directory.");
        return effects.Invoke(new(kind, name, argv ?? [], J(data))).Clone();
    }
    private void Start(string scope) => Effect(LegacyDiagnosticEffectKind.Clock, "start", data: scope);
    private int Stop(string scope) => I(Effect(LegacyDiagnosticEffectKind.Clock, "stop", data: scope));
    private int Elapsed(string scope) => I(Effect(LegacyDiagnosticEffectKind.Clock, "elapsed", data: scope));
    private string Now() => S(Effect(LegacyDiagnosticEffectKind.Timestamp, "o"));
    private bool Exists(string path) => T(Effect(LegacyDiagnosticEffectKind.FileExists, data: path));
    private JsonElement Files(string path, bool recurse = false, string? filter = null, bool file = true) =>
        Effect(LegacyDiagnosticEffectKind.ListFiles, data: D("path", path, "recurse", recurse, "filter", filter, "file", file));
    private JsonElement Cli(params string[] argv) => Effect(LegacyDiagnosticEffectKind.Cli, argv: argv);
    private JsonElement Native(params string[] argv) => Effect(LegacyDiagnosticEffectKind.Native, argv: argv);
    private static JsonElement Parsed(JsonElement v) => P(v, "json");
    private static bool Success(JsonElement r) => I(P(r, "exit")) == 0 && Eq(P(Parsed(r), "status"), "ok");
    private LegacyDiagnosticResult Result(object? payload, int exit, int depth, string? line = null, bool? renderBrief = null) =>
        new(J(payload), exit, depth, (renderBrief ?? RenderBrief) ? line : null, !(renderBrief ?? RenderBrief), operation switch
        {
            "audit-summary" => ["by_macro", "by_exit_code"],
            "diagnose-lag" => ["processes.*.priority_classes"],
            _ => []
        });
}
