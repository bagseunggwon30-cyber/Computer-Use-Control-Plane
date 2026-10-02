using System.Text.Json;
using System.Security.Cryptography;
using System.IO;

// Closed, pure acquisition controller. Every query is replayed from captured data;
// this class performs no acquisition, persistence, process launch, or live action.
internal static class LegacyAppProfileController
{
    private const string Schema = "cucp.app-profile-controller/v1";
    private const string AuthorizationSchema = "cucp.app-profile-record-authorization/v1";
    private static Dictionary<string, object?> D(params object?[] values)
    {
        var result = new Dictionary<string, object?>();
        for (int i = 0; i < values.Length; i += 2) result.Add((string)values[i]!, values[i + 1]);
        return result;
    }
    private static JsonElement J(object? value) => JsonSerializer.SerializeToElement(value);
    private static JsonElement P(JsonElement value, string name) => value.ValueKind == JsonValueKind.Object && value.TryGetProperty(name, out var property) ? property : default;
    private static string? S(JsonElement value) => value.ValueKind == JsonValueKind.String ? value.GetString() : null;
    private static bool B(JsonElement value) => value.ValueKind == JsonValueKind.True;
    private static JsonElement[] A(JsonElement value) => value.ValueKind == JsonValueKind.Array ? value.EnumerateArray().ToArray() : [];
    private static bool Same(JsonElement a, JsonElement b)
    {
        if (a.ValueKind != b.ValueKind) return false;
        return a.ValueKind switch
        {
            JsonValueKind.String => a.GetString() == b.GetString(),
            JsonValueKind.Array => a.GetArrayLength() == b.GetArrayLength() && a.EnumerateArray().Zip(b.EnumerateArray()).All(p => Same(p.First, p.Second)),
            JsonValueKind.Object => a.EnumerateObject().Count() == b.EnumerateObject().Count() &&
                a.EnumerateObject().Select(p => p.Name).Distinct(StringComparer.Ordinal).Count() == a.EnumerateObject().Count() &&
                b.EnumerateObject().Select(p => p.Name).Distinct(StringComparer.Ordinal).Count() == b.EnumerateObject().Count() &&
                a.EnumerateObject().All(p => b.TryGetProperty(p.Name, out var other) && Same(p.Value, other)),
            JsonValueKind.Number => a.TryGetDecimal(out decimal left) && b.TryGetDecimal(out decimal right) ? left == right : a.GetRawText() == b.GetRawText(),
            _ => true
        };
    }
    private static void Require(bool condition, string message)
    {
        if (!condition) throw new ArgumentException(message);
    }
    private static string Digest(JsonElement value)
    {
        using var buffer = new MemoryStream();
        using (var writer = new Utf8JsonWriter(buffer))
        {
            void Write(JsonElement value)
            {
                if (value.ValueKind == JsonValueKind.Object)
                {
                    writer.WriteStartObject();
                    foreach (var p in value.EnumerateObject().OrderBy(p => p.Name, StringComparer.Ordinal)) { writer.WritePropertyName(p.Name); Write(p.Value); }
                    writer.WriteEndObject();
                }
                else if (value.ValueKind == JsonValueKind.Array) { writer.WriteStartArray(); foreach (var v in value.EnumerateArray()) Write(v); writer.WriteEndArray(); }
                else if (value.ValueKind == JsonValueKind.Number && value.TryGetDecimal(out decimal number)) writer.WriteRawValue(number.ToString("G29", System.Globalization.CultureInfo.InvariantCulture));
                else value.WriteTo(writer);
            }
            Write(value);
        }
        return Convert.ToHexString(SHA256.HashData(buffer.ToArray()));
    }
    private static string ContextDigest(JsonElement args, int captureCount)
    {
        // A deterministic binding, not a credential. Measured durations and the
        // yet-unperformed record result are deliberately outside this context.
        var context = args.EnumerateObject().Where(p => p.Name is not ("elapsed_ms" or "cdp_elapsed_ms" or "uia_elapsed_ms"))
            .ToDictionary(p => p.Name, p => p.Value.Clone(), StringComparer.Ordinal);
        context["effective_culture"] = J(S(P(args, "culture")) ?? System.Globalization.CultureInfo.CurrentCulture.Name);
        context["captured_replies"] = J(A(P(args, "captured_replies")).Take(captureCount).ToArray());
        return Digest(J(context));
    }
    private static JsonElement ScoreSummary(JsonElement score) => J(D("recommended_strategy", P(score, "recommended_strategy"),
        "confidence", P(score, "confidence"), "total_score", P(score, "total_score")));
    private static void Fields(JsonElement value, params string[] names)
    {
        Require(value.ValueKind == JsonValueKind.Object, "Expected a controller object.");
        var remaining = new HashSet<string>(names, StringComparer.Ordinal);
        foreach (var property in value.EnumerateObject()) Require(remaining.Remove(property.Name), "Unexpected or duplicate controller field.");
        Require(remaining.Count == 0, "Missing controller field.");
    }
    private static void Descriptor(JsonElement actual, JsonElement expected)
    {
        Fields(actual, "kind", "argv");
        Require(S(P(actual, "kind")) is not null && P(actual, "argv").ValueKind == JsonValueKind.Array &&
            A(P(actual, "argv")).All(v => v.ValueKind == JsonValueKind.String), "Invalid app-profile query descriptor.");
        Require(S(P(actual, "kind")) == S(P(expected, "kind")) && Same(P(actual, "argv"), P(expected, "argv")), "App-profile query does not match original acquisition schedule.");
    }
    private static void Trace(JsonElement state, JsonElement[] captures)
    {
        var trace = P(state, "queries");
        bool query = S(P(state, "state")) == "query";
        Require(trace.ValueKind == JsonValueKind.Array && trace.GetArrayLength() == captures.Length + (query ? 1 : 0), "Invalid app-profile query trace length.");
        for (int i = 0; i < captures.Length; i++) Descriptor(trace[i], captures[i]);
        if (query)
        {
            var descriptor = P(state, "query");
            Descriptor(descriptor, trace[trace.GetArrayLength() - 1]);
            string? kind = S(P(descriptor, "kind"));
            string[] argv = A(P(descriptor, "argv")).Select(v => v.GetString()!).ToArray();
            bool closed = kind switch
            {
                "windows" => argv.Length == 0 || argv.Length == 2 && argv[0] == "-Match",
                "cdp_port" => argv.Length == 2 && argv[1] == "120",
                "native" => argv.Length == 4 && argv[0] == "-Action" && argv[1] == "cdp-detect" && argv[2] == "-CdpPort",
                "uia" => argv.Length == 8 && argv[0] == "-FocusedWindow" && argv[2] == "-MaxElements" && argv[4] == "-MinSize" && argv[5] == "6" && argv[6] == "-Hwnd",
                "history" => argv.Length == 1,
                "record" => argv.Length == 8,
                _ => false
            };
            Require(closed && captures.Length < 7, "App-profile query is outside the closed acquisition schedule.");
        }
    }
    private static JsonElement RecordDescriptor(JsonElement binding, JsonElement score) => J(D("kind", "record", "argv", new[]
    {
        S(P(binding, "app_key")), S(P(binding, "app_type")), S(P(score, "recommended_strategy")), S(P(score, "confidence")),
        P(score, "total_score").GetInt32().ToString(System.Globalization.CultureInfo.InvariantCulture),
        S(P(P(binding, "selected_window"), "process")), S(P(P(binding, "selected_window"), "class")), S(P(P(binding, "selected_window"), "title"))
    }));
    private static void Completion(JsonElement state, JsonElement args, JsonElement[] captures, JsonElement binding)
    {
        Require(S(P(state, "state")) == "complete", "App-profile preflight did not complete.");
        Trace(state, captures);
        var payload = P(state, "payload");
        bool target = P(binding, "selected_window").ValueKind != JsonValueKind.Null;
        Require(S(P(payload, "schema")) == "cucp.app-profile/v1" && S(P(payload, "status")) == (target ? "ok" : "partial") &&
            P(state, "exit").TryGetInt32(out int exit) && exit == (target ? 0 : 2) &&
            P(state, "json_depth").TryGetInt32(out int depth) && depth == (target ? 14 : 12), "Invalid app-profile completion envelope.");
        Require(Same(P(payload, "selected_window"), P(binding, "selected_window")), "App-profile selected target identity changed.");
        var persistence = P(payload, "strategy_persistence");
        bool requested = B(P(binding, "record_requested")), historyEnabled = !B(P(binding, "no_history"));
        Require(P(persistence, "enabled").ValueKind is JsonValueKind.True or JsonValueKind.False && B(P(persistence, "enabled")) == historyEnabled &&
            P(persistence, "record_requested").ValueKind is JsonValueKind.True or JsonValueKind.False && B(P(persistence, "record_requested")) == requested &&
            Same(P(persistence, "app_key"), P(binding, "app_key")) && Same(P(persistence, "history_file"), P(binding, "history_file")), "Invalid app-profile persistence binding.");
        var score = P(payload, "strategy_score");
        Require(S(P(score, "schema")) == "cucp.app-profile-strategy-score/v1" && Same(P(score, "app_type"), P(binding, "app_type")) &&
            P(score, "total_score").TryGetInt32(out int total) && total is >= 0 and <= 100, "Invalid app-profile strategy score.");
        total = P(score, "total_score").GetInt32();
        string confidence = total >= 75 ? "high" : total >= 50 ? "medium" : total >= 25 ? "low" : "none";
        var routes = P(score, "route_order"); var scores = P(score, "route_scores");
        Require(S(P(score, "confidence")) == confidence && Same(P(payload, "recommended_strategy"), P(score, "recommended_strategy")) &&
            Same(P(payload, "route_order"), routes) && routes.ValueKind == JsonValueKind.Array && scores.ValueKind == JsonValueKind.Array &&
            routes.GetArrayLength() == scores.GetArrayLength(), "Inconsistent app-profile recommendation or confidence.");
        Require(target ? Same(P(payload, "app_type"), P(binding, "app_type")) && scores.GetArrayLength() > 0 : total == 0 && scores.GetArrayLength() == 0, "App-profile classification differs from selected target.");
        for (int i = 0; i < scores.GetArrayLength(); i++)
        {
            var item = scores[i];
            Require(!string.IsNullOrEmpty(S(P(item, "route"))) && Same(P(item, "route"), routes[i]) &&
                P(item, "score").TryGetInt32(out int points) && points >= 0 && points <= total, "Inconsistent app-profile route scores.");
            if (i == 0) Require(P(item, "score").GetInt32() == total && Same(P(item, "route"), P(score, "recommended_strategy")), "Inconsistent app-profile winning route.");
        }
        bool needsRecord = target && requested && historyEnabled && total >= 50;
        var records = captures.Where(c => S(P(c, "kind")) == "record").ToArray();
        Require(records.Length == (needsRecord ? 1 : 0) && (records.Length == 0 || S(P(captures[^1], "kind")) == "record"), "App-profile record schedule differs from explicit flags and derived confidence.");
        JsonElement rawRecord = J(null);
        if (needsRecord)
        {
            Descriptor(P(state, "queries")[captures.Length - 1], RecordDescriptor(binding, score));
            Require(records[0].TryGetProperty("result", out rawRecord), "A completed record must have its actual result.");
        }
        var outcome = LegacyAppProfileKernel.RecordOutcome(rawRecord);
        Require(Same(P(persistence, "recorded"), P(outcome, "recorded")) && Same(P(persistence, "record"), P(outcome, "record")), "App-profile completion changed the captured record result.");
        bool brief = B(P(binding, "brief_enabled"));
        if (brief)
        {
            string summary = target
                ? $"ok app-profile type={S(P(binding, "app_type"))} strategy={S(P(payload, "recommended_strategy"))} labels={A(P(payload, "probe_commands")).Length} elapsed_ms={P(payload, "elapsed_ms").GetInt32()}"
                : $"partial app-profile reason={S(P(payload, "reason"))} windows={P(payload, "window_count").GetInt32()}";
            Require(S(P(state, "brief")) == summary, "App-profile brief differs from its payload.");
        }
        else Require(P(state, "brief").ValueKind == JsonValueKind.Null, "Unexpected app-profile brief in JSON mode.");
    }
    internal static object Advance(JsonElement args)
    {
        int evaluations = 0;
        JsonElement current = default;
        object Envelope(JsonElement state, JsonElement authorization = default, JsonElement recordCompletion = default)
        {
            var result = state.EnumerateObject().ToDictionary(p => p.Name, p => (object?)p.Value.Clone());
            result.Add("facade", Schema); result.Add("kernel_evaluations", evaluations);
            if (authorization.ValueKind != JsonValueKind.Undefined) result.Add("record_authorization", authorization);
            if (recordCompletion.ValueKind != JsonValueKind.Undefined) result.Add("record_completion", recordCompletion);
            return result;
        }
        JsonElement Evaluate(JsonElement input) { evaluations++; return J(LegacyAppProfileKernel.Advance(input)); }
        try
        {
            Require(args.ValueKind == JsonValueKind.Object, "Expected app-profile controller arguments.");
            var input = new Dictionary<string, JsonElement>(StringComparer.Ordinal);
            JsonElement authorization = default;
            foreach (var field in args.EnumerateObject())
            {
                if (field.Name == "record_authorization")
                {
                    Require(authorization.ValueKind == JsonValueKind.Undefined, "Duplicate record authorization.");
                    Require(field.Value.GetRawText().Length <= 1048576, "Record authorization exceeds its protocol budget.");
                    authorization = field.Value.Clone();
                }
                else Require(input.TryAdd(field.Name, field.Value.Clone()), "Duplicate app-profile argument.");
            }
            var kernelArgs = J(input);
            current = Evaluate(kernelArgs);
            if (S(P(current, "state")) == "error") return Envelope(current);
            var captures = A(P(kernelArgs, "captured_replies"));
            Trace(current, captures);
            bool completedRecord = captures.Length > 0 && S(P(captures[^1], "kind")) == "record";
            Require(completedRecord == (authorization.ValueKind != JsonValueKind.Undefined), "Record completion requires exactly its preflight authorization.");
            if (S(P(current, "state")) == "query" && S(P(P(current, "query"), "kind")) == "record")
            {
                var query = P(current, "query");
                var supplied = captures.Select(c => (object)c).Append(D("kind", "record", "argv", P(query, "argv"), "result", null)).ToArray();
                input["captured_replies"] = J(supplied);
                var preflightArgs = J(input);
                var preflight = Evaluate(preflightArgs);
                var binding = LegacyAppProfileKernel.RecordBinding(kernelArgs);
                Completion(preflight, preflightArgs, A(P(preflightArgs, "captured_replies")), binding);
                var score = P(P(preflight, "payload"), "strategy_score");
                Require(B(P(binding, "record_requested")) && !B(P(binding, "no_history")) && P(score, "total_score").GetInt32() >= 50, "App-profile record lacks explicit permission and sufficient confidence.");
                Descriptor(query, RecordDescriptor(binding, score));
                authorization = J(D("schema", AuthorizationSchema, "query", query, "selected_window", P(binding, "selected_window"),
                    "app_type", P(binding, "app_type"), "app_key", P(binding, "app_key"), "history_file", P(binding, "history_file"), "strategy_score", ScoreSummary(score),
                    "strategy_score_sha256", Digest(score),
                    "context_sha256", ContextDigest(kernelArgs, captures.Length)));
                // Return the already validated completion before persistence. The
                // acquisition shim finalizes only record/recorded after Append;
                // no response-sized request or process is needed after that write.
                return Envelope(current, authorization, preflight);
            }
            if (S(P(current, "state")) == "complete")
            {
                var binding = LegacyAppProfileKernel.RecordBinding(kernelArgs);
                Completion(current, kernelArgs, captures, binding);
                if (completedRecord)
                {
                    Fields(authorization, "schema", "query", "selected_window", "app_type", "app_key", "history_file", "strategy_score", "strategy_score_sha256", "context_sha256");
                    Fields(P(authorization, "strategy_score"), "recommended_strategy", "confidence", "total_score");
                    Require(S(P(authorization, "schema")) == AuthorizationSchema, "Invalid app-profile record authorization.");
                    Require(S(P(authorization, "context_sha256")) == ContextDigest(kernelArgs, captures.Length - 1), "App-profile invocation changed after record preflight.");
                    Descriptor(P(authorization, "query"), captures[^1]);
                    foreach (string field in new[] { "selected_window", "app_type", "app_key", "history_file" })
                        Require(Same(P(authorization, field), P(binding, field)), "App-profile record target or destination changed after preflight.");
                    var finalScore = P(P(current, "payload"), "strategy_score");
                    Require(Same(P(authorization, "strategy_score"), ScoreSummary(finalScore)) && S(P(authorization, "strategy_score_sha256")) == Digest(finalScore), "App-profile score changed after recording.");
                }
                return Envelope(current);
            }
            Require(S(P(current, "state")) == "query", "Invalid app-profile controller state.");
            return Envelope(current);
        }
        catch (Exception error)
        {
            return D("state", "error", "error", error.Message, "queries", current.ValueKind == JsonValueKind.Object ? P(current, "queries") : J(Array.Empty<object>()),
                "facade", Schema, "kernel_evaluations", evaluations);
        }
    }
}
