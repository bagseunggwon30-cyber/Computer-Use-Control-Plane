using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

// Read-only precision planning. Every acquisition is a closed, captured effect.
// Mutations are terminal effects: the complete payload is validated before the
// caller writes history/cache, and no growing replay frame follows a write.
internal static partial class LegacyPrecisionKernel
{
    internal static Dictionary<string, object?> D(params object?[] pairs)
    {
        var d = new Dictionary<string, object?>();
        for (int i = 0; i < pairs.Length; i += 2) d.Add((string)pairs[i]!, pairs[i + 1]);
        return d;
    }
    internal static object? P(object? value, string name)
    {
        if (value is JsonElement j && j.ValueKind == JsonValueKind.Object)
            foreach (var p in j.EnumerateObject()) if (string.Equals(p.Name, name, StringComparison.OrdinalIgnoreCase)) return p.Value.Clone();
        if (value is Dictionary<string, object?> d)
            foreach (var p in d) if (string.Equals(p.Key, name, StringComparison.OrdinalIgnoreCase)) return p.Value;
        return null;
    }
    internal static object?[] A(object? value) => value switch
    {
        JsonElement { ValueKind: JsonValueKind.Array } j => j.EnumerateArray().Select(v => (object?)v.Clone()).ToArray(),
        object?[] a => a, IEnumerable<object?> e => e.ToArray(), null => [null], _ => [value]
    };
    internal static bool T(object? value) => value switch
    {
        null => false, bool b => b, string s => s.Length != 0,
        JsonElement j => j.ValueKind switch
        {
            JsonValueKind.Null or JsonValueKind.Undefined or JsonValueKind.False => false,
            JsonValueKind.True or JsonValueKind.Object => true, JsonValueKind.String => j.GetString()!.Length != 0,
            JsonValueKind.Array => j.GetArrayLength() > 1 || (j.GetArrayLength() == 1 && T(j[0])),
            JsonValueKind.Number => j.GetDouble() != 0, _ => false
        },
        object?[] a => a.Length > 1 || (a.Length == 1 && T(a[0])),
        IConvertible c => c.ToDouble(CultureInfo.InvariantCulture) != 0, _ => true
    };
    internal static string S(object? value) => value switch
    {
        null => "", string s => s, bool b => b ? "True" : "False",
        JsonElement j => j.ValueKind switch
        {
            JsonValueKind.Null or JsonValueKind.Undefined => "", JsonValueKind.String => j.GetString()!,
            JsonValueKind.True => "True", JsonValueKind.False => "False",
            JsonValueKind.Array => string.Join(" ", j.EnumerateArray().Select(v => S(v))),
            JsonValueKind.Object => "@{" + string.Join("; ", j.EnumerateObject().Select(p => p.Name + "=" + S(p.Value))) + "}", _ => j.ToString()
        }, _ => Convert.ToString(value, CultureInfo.InvariantCulture) ?? ""
    };
    internal static int I(object? value)
    {
        string s = S(value); if (s.Length == 0) return 0;
        try
        {
            if (value is bool || value is JsonElement { ValueKind: JsonValueKind.True or JsonValueKind.False }) return T(value) ? 1 : 0;
            if (s.StartsWith("0x", StringComparison.OrdinalIgnoreCase)) return unchecked((int)uint.Parse(s[2..], NumberStyles.HexNumber, CultureInfo.InvariantCulture));
            return Convert.ToInt32(double.Parse(s, NumberStyles.Float | NumberStyles.AllowThousands, CultureInfo.InvariantCulture));
        }
        catch (Exception ex) when (ex is FormatException or OverflowException)
        { throw new InvalidOperationException($"Cannot convert value \"{s}\" to type \"System.Int32\". Error: \"{(ex is FormatException ? "Input string was not in a correct format." : "Value was either too large or too small for an Int32.")}\""); }
    }
    internal static long L(object? value)
    {
        string s = S(value); if (s.Length == 0) return 0;
        try
        {
            if (value is bool || value is JsonElement { ValueKind: JsonValueKind.True or JsonValueKind.False }) return T(value) ? 1 : 0;
            if (s.StartsWith("0x", StringComparison.OrdinalIgnoreCase)) return unchecked((long)ulong.Parse(s[2..], NumberStyles.HexNumber, CultureInfo.InvariantCulture));
            if (long.TryParse(s, NumberStyles.Integer, CultureInfo.InvariantCulture, out long exact)) return exact;
            return Convert.ToInt64(double.Parse(s, NumberStyles.Float | NumberStyles.AllowThousands, CultureInfo.InvariantCulture));
        }
        catch (Exception ex) when (ex is FormatException or OverflowException)
        { throw new InvalidOperationException($"Cannot convert value \"{s}\" to type \"System.Int64\". Error: \"{(ex is FormatException ? "Input string was not in a correct format." : "Value was either too large or too small for an Int64.")}\""); }
    }
    internal static double N(object? value) => S(value).Length == 0 ? 0 : double.Parse(S(value), NumberStyles.Float | NumberStyles.AllowThousands, CultureInfo.InvariantCulture);
    internal static bool Eq(object? value, string expected) => string.Equals(S(value), expected, StringComparison.InvariantCultureIgnoreCase);
    private static bool IsTrue(object? value) => value switch
    {
        bool b => b, JsonElement { ValueKind: JsonValueKind.True } => true,
        JsonElement { ValueKind: JsonValueKind.False or JsonValueKind.Null } => false,
        string s => Eq(s, "True"), JsonElement { ValueKind: JsonValueKind.String } j => Eq(j, "True"),
        _ => S(value) == "1"
    };
    internal static string Step(IEnumerable<string> command) => string.Join(" ", command.Select(v => LegacyTextKernel.IsBareCommandToken(v, CultureInfo.CurrentCulture) ? v : "'" + v.Replace("'", "''", StringComparison.Ordinal) + "'"));
    internal static object? PipelineValue(object? value)
    {
        if (value is JsonElement { ValueKind: JsonValueKind.Array } || value is object?[])
        {
            var items = A(value); return items.Length == 0 ? null : items.Length == 1 ? items[0] : items;
        }
        return value;
    }
    internal static string CommandStep(object? command)
    {
        var tokens = new List<string>();
        foreach (var item in A(command))
        {
            if (item == null || item is JsonElement { ValueKind: JsonValueKind.Null }) continue;
            if (item is JsonElement { ValueKind: JsonValueKind.Array } || item is object?[])
            {
                foreach (var sub in A(item)) if (sub != null && sub is not JsonElement { ValueKind: JsonValueKind.Null }) tokens.Add(S(sub));
            }
            else tokens.Add(S(item));
        }
        return Step(tokens);
    }
    internal static string Hash(string value) => Convert.ToHexString(MD5.HashData(Encoding.UTF8.GetBytes(string.IsNullOrWhiteSpace(value) ? "_full" : LegacyTextKernel.LowerValue(value, CultureInfo.InvariantCulture)))).ToLowerInvariant();
    internal static string CacheKey(int x, int y, int radius, int step, int inset, int hwnd, string match, object? precheck, string signature)
        => Hash($"point-plan|x={x}|y={y}|r={radius}|s={step}|inset={inset}|th={hwnd}|tm={match}|root={(T(precheck) ? L(P(precheck, "root_hwnd")) : 0)}|title={S(P(precheck, "root_title"))}|proc={S(P(precheck, "process_name"))}|coord={signature}");
    internal static object ChildPlanEnvelope(IEnumerable<string> rawLines, int exitCode)
    {
        string raw = string.Join("\n", rawLines); object? json = null;
        try { using var document = JsonDocument.Parse(raw); json = document.RootElement.Clone(); } catch (JsonException) { }
        return D("exit", exitCode, "raw", raw, "json", json);
    }
    internal static double NormDistance(object? a, object? b)
    {
        if (!T(a) || !T(b)) return double.MaxValue;
        try { double x = N(P(a, "x")) - N(P(b, "x")), y = N(P(a, "y")) - N(P(b, "y")); return Math.Sqrt(x * x + y * y); }
        catch { return double.MaxValue; }
    }
    internal static object?[] ReadHistory(IEnumerable<string> lines, int last)
    {
        if (last <= 0) last = 500;
        var records = new List<object?>();
        foreach (string line in lines.TakeLast(last))
        {
            if (string.IsNullOrWhiteSpace(line)) continue;
            try { using var doc = JsonDocument.Parse(line); records.Add(doc.RootElement.Clone()); } catch (JsonException) { }
        }
        return records.ToArray();
    }
    internal static object Score(object? record, IEnumerable<object?> records, double tolerance, string path)
    {
        if (!T(record)) return D("schema", "cucp.anchor-reuse-score/v1", "enabled", true, "status", "partial", "reason", "missing_anchor_record", "score", 0, "confidence", "none", "recorded", false);
        if (tolerance <= 0) tolerance = .012; if (tolerance > .1) tolerance = .1;
        var all = records.ToArray(); var exact = new List<object?>(); var near = new List<object?>();
        string target = S(P(record, "target_match")), process = S(P(record, "process")), cls = S(P(record, "class"));
        foreach (var r in all)
        {
            if (T(P(r, "anchor_id")) && Eq(P(r, "anchor_id"), S(P(record, "anchor_id")))) exact.Add(r);
            bool same = target.Length != 0 && Eq(P(r, "target_match"), target) || process.Length != 0 && cls.Length != 0 && Eq(P(r, "process"), process) && Eq(P(r, "class"), cls);
            if (same && NormDistance(P(r, "normalized_window_point"), P(record, "normalized_window_point")) <= tolerance) near.Add(r);
        }
        var matches = new List<object?>(exact);
        foreach (var n in near) if (!matches.Any(e => T(P(e, "anchor_id")) && T(P(n, "anchor_id")) && Eq(P(e, "anchor_id"), S(P(n, "anchor_id"))))) matches.Add(n);
        var last = matches.LastOrDefault(); int safeCount = matches.Count(r => IsTrue(P(r, "safe_to_reuse")));
        double safeRate = matches.Count > 0 ? Math.Round((double)safeCount / matches.Count, 3) : 0;
        bool signature = T(last) && T(P(last, "coord_signature")) && T(P(record, "coord_signature")) && Eq(P(last, "coord_signature"), S(P(record, "coord_signature")));
        bool safe = IsTrue(P(record, "safe_to_reuse")); string risk = S(P(record, "coordinate_risk"));
        int score = (safe ? 30 : 5) + (Eq(risk, "low") ? 15 : Eq(risk, "medium") ? 5 : Eq(risk, "high") ? -25 : 0);
        score += Math.Min(25, exact.Count * 7) + Math.Min(15, near.Count * 3);
        if (matches.Count > 0) score += Convert.ToInt32(Math.Round(safeRate * 10)) + (signature ? 10 : -8);
        score = Math.Clamp(score, 0, 100);
        string confidence = score >= 80 ? "high" : score >= 60 ? "medium" : score >= 35 ? "low" : "none";
        var warnings = new List<string>();
        if (all.Length == 0) warnings.Add("no_anchor_history"); else if (matches.Count == 0) warnings.Add("no_matching_anchor_history");
        if (matches.Count > 0 && !signature) warnings.Add("coord_signature_changed_since_last_match");
        if (!safe) warnings.Add("current_anchor_not_safe_to_reuse"); if (Eq(risk, "high")) warnings.Add("coordinate_risk_high");
        return D("schema", "cucp.anchor-reuse-score/v1", "enabled", true, "status", "ok", "history_file", path, "score", score, "confidence", confidence, "recorded", false,
            "total_records", all.Length, "exact_match_count", exact.Count, "near_match_count", near.Count, "matched_record_count", matches.Count, "safe_match_count", safeCount,
            "safe_match_rate", safeRate, "tolerance_norm", tolerance, "signature_match", signature, "last_seen", S(P(last, "ts")), "last_screen_point", P(last, "screen_point"),
            "last_coord_signature", S(P(last, "coord_signature")), "warnings", warnings.ToArray(), "recommendation", score >= 80 && safe ? "reuse_ok_after_target_validate" : score >= 45 ? "verify_with_target_validate_before_live_click" : "re_ground_before_reuse");
    }
    internal static int ConfidenceRank(string confidence) => LegacyTextKernel.LowerValue(confidence, CultureInfo.InvariantCulture) switch { "high" => 3, "medium" => 2, "low" => 1, _ => 0 };
    internal static string SizeClass(object? rect, int area)
    {
        int width = TryInt(P(rect, "width")), height = TryInt(P(rect, "height"));
        if (area <= 0 && width > 0 && height > 0) area = I((long)width * height);
        if (width <= 0 || height <= 0 || area <= 0) return "unknown";
        if (width <= 20 || height <= 20 || area <= 900) return "tiny";
        if (width <= 44 || height <= 32 || area <= 2200) return "small";
        return width <= 140 && height <= 100 ? "medium" : "large";
    }
    private static int TryInt(object? value) { try { return I(value); } catch { return 0; } }
    internal static object? EdgeDistance(object? point, object? rect)
    {
        if (!T(point) || !T(rect)) return null;
        int x = I(P(point, "x")), y = I(P(point, "y")), rx = I(P(rect, "x")), ry = I(P(rect, "y")), rw = I(P(rect, "width")), rh = I(P(rect, "height"));
        if (rw <= 0 || rh <= 0) return null;
        int left = checked(x - rx), top = checked(y - ry), right = checked((int)((long)rx + rw - x - 1)), bottom = checked((int)((long)ry + rh - y - 1));
        return D("left", left, "top", top, "right", right, "bottom", bottom, "min", Math.Min(Math.Min(left, top), Math.Min(right, bottom)));
    }
    private sealed class NeedReply(object descriptor) : Exception { internal object Descriptor = descriptor; }
    private sealed class Context(JsonElement args, IPrecisionReadEffects? reader = null)
    {
        internal readonly JsonElement Args = args;
        internal readonly List<object> Queries = [];
        internal readonly List<object> Effects = [];
        internal int Cursor;
        internal object? Query(string kind, params object?[] fields)
        {
            var parameters = D(fields); var query = D("kind", kind, "args", parameters); Queries.Add(query);
            if (reader != null)
            {
                PrecisionTargetPoint Point() => new(I(P(parameters, "x")), I(P(parameters, "y")), L(P(parameters, "target_hwnd")), S(P(parameters, "target_match")));
                PrecisionScan Scan(string[] argv, bool child)
                {
                    string Prefix(string name) => child ? "--" + name : "-" + name;
                    string[] words = argv;
                    string? Get(string normal, string native) => V(words, Prefix(child ? normal : native));
                    var p = new PrecisionTargetPoint(I(Get("x", "X")), I(Get("y", "Y")), L(Get("target-hwnd", "TargetHwnd")), Get("target-match", "TargetMatch") ?? "");
                    return new(p, I(Get("click-inset", "ClickInset")), I(Get("radius", "ScanRadius")), I(Get("step", "ScanStep")));
                }
                string[] argv = parameters.TryGetValue("argv", out var av) ? A(av).Select(S).ToArray() : [];
                return kind switch
                {
                    "coord-map" => reader.CoordinateMap(Point()), "hit-test" => reader.HitTest(Point()), "coord-profile" => reader.CoordinateProfile(Point()),
                    "hit-scan" => reader.HitScan(Scan(argv, false)),
                    "point-plan-child" => reader.ChildPointPlan(new(Scan(argv, true), I(V(argv, "--cache-ttl")), B(argv, "--no-cache"))),
                    "history-lines" => reader.HistoryLines(HistoryFile),
                    "cache-read" => reader.ReadCache(CacheDir, S(P(parameters, "key")), I(P(parameters, "max_age_seconds"))),
                    _ => throw new ArgumentException("Unknown precision effect.")
                };
            }
            var replies = P(Args, "captured_replies"); var all = replies == null ? [] : A(replies);
            if (Cursor >= all.Length) throw new NeedReply(query);
            var reply = (JsonElement)all[Cursor++]!;
            if (reply.ValueKind != JsonValueKind.Object) throw new ArgumentException("Captured reply must be an object.");
            var keys = new HashSet<string>();
            foreach (var p in reply.EnumerateObject()) if (!keys.Add(p.Name) || p.Name is not ("kind" or "args" or "result" or "error")) throw new ArgumentException("Unknown or duplicate captured reply field.");
            bool hasResult = reply.TryGetProperty("result", out var result), hasError = reply.TryGetProperty("error", out var error);
            if (keys.Count != 3 || hasResult == hasError || !EqExact(P(reply, "kind"), kind) || !reply.TryGetProperty("args", out var actual) || !JsonEqual(actual, JsonSerializer.SerializeToElement(parameters)))
                throw new ArgumentException("Captured reply descriptor does not match exact query order/arguments.");
            if (hasError) { if (error.ValueKind != JsonValueKind.String) throw new ArgumentException("Captured error must be a string."); throw new InvalidOperationException(error.GetString()); }
            return result.Clone();
        }
        internal int Elapsed => I(P(Args, "elapsed_ms"));
        internal string HistoryFile => S(P(Args, "history_file"));
        internal string CacheDir => S(P(Args, "cache_dir"));
        internal object Complete(object? payload, int exit, string? brief, int depth)
        {
            if (reader == null && P(Args, "captured_replies") is { } raw && Cursor != A(raw).Length) throw new ArgumentException("Unused captured replies.");
            return D("state", "complete", "payload", payload, "exit", exit, "brief", brief, "json_depth", depth, "queries", Queries.ToArray(), "effects", Effects.ToArray());
        }
    }
    private static bool EqExact(object? value, string expected) => value is JsonElement { ValueKind: JsonValueKind.String } j && j.GetString() == expected;
    private static bool JsonEqual(JsonElement a, JsonElement b)
    {
        if (a.ValueKind != b.ValueKind) return false;
        if (a.ValueKind == JsonValueKind.Object)
        {
            var left = a.EnumerateObject().ToArray(); var right = b.EnumerateObject().ToArray();
            return left.Length == right.Length && left.Select(p => p.Name).Distinct().Count() == left.Length && left.All(p => right.Any(q => q.Name == p.Name && JsonEqual(p.Value, q.Value)));
        }
        if (a.ValueKind == JsonValueKind.Array) return a.GetArrayLength() == b.GetArrayLength() && a.EnumerateArray().Zip(b.EnumerateArray()).All(p => JsonEqual(p.First, p.Second));
        return a.ValueKind == JsonValueKind.Number ? a.TryGetDecimal(out var leftNumber) && b.TryGetDecimal(out var rightNumber) && leftNumber == rightNumber : a.ToString() == b.ToString();
    }
    internal static object Advance(string operation, JsonElement args) => Evaluate(operation, args, null);
    internal static object Execute(string operation, JsonElement args, IPrecisionReadEffects effects) => Evaluate(operation, args, effects);
    private static object Evaluate(string operation, JsonElement args, IPrecisionReadEffects? effects)
    {
        var ctx = new Context(args, effects);
        try
        {
            if (args.ValueKind != JsonValueKind.Object || args.GetRawText().Length > 4194304) throw new ArgumentException("Expected bounded precision object.");
            var allowed = new HashSet<string> { "rest", "cache_seconds", "brief", "elapsed_ms", "now", "history_file", "history_max", "cache_dir", "captured_replies", "value", "a", "b", "record", "records", "tolerance", "lines", "last", "rect", "area", "point", "x", "y", "radius", "step", "click_inset", "target_hwnd", "target_match", "precheck", "coord_signature", "raw_lines", "exit_code" };
            foreach (var p in args.EnumerateObject()) if (!allowed.Remove(p.Name)) throw new ArgumentException("Unknown or duplicate precision argument.");
            if (args.TryGetProperty("captured_replies", out var captures) && (captures.ValueKind != JsonValueKind.Array || captures.GetArrayLength() > 8)) throw new ArgumentException("At most eight captured replies are allowed.");
            if (operation == "child-plan-envelope") return ctx.Complete(ChildPlanEnvelope(A(P(args, "raw_lines")).Select(S), I(P(args, "exit_code"))), 0, null, 64);
            if (operation == "history-score") return ctx.Complete(Score(P(args, "record"), args.TryGetProperty("records", out var recs) ? A(recs) : [], args.TryGetProperty("tolerance", out var tol) ? N(tol) : .012, ctx.HistoryFile), 0, null, 32);
            if (operation == "history-distance") return ctx.Complete(NormDistance(P(args, "a"), P(args, "b")), 0, null, 2);
            if (operation == "history-read") return ctx.Complete(ReadHistory(A(P(args, "lines")).Select(S), I(P(args, "last"))), 0, null, 32);
            if (operation == "confidence-rank") return ctx.Complete(ConfidenceRank(S(P(args, "value"))), 0, null, 2);
            if (operation == "size-class") return ctx.Complete(SizeClass(P(args, "rect"), I(P(args, "area"))), 0, null, 2);
            if (operation == "edge-distance") return ctx.Complete(EdgeDistance(P(args, "point"), P(args, "rect")), 0, null, 4);
            if (operation == "cache-key") return ctx.Complete(CacheKey(I(P(args, "x")), I(P(args, "y")), I(P(args, "radius")), I(P(args, "step")), I(P(args, "click_inset")), I(P(args, "target_hwnd")), S(P(args, "target_match")), P(args, "precheck"), S(P(args, "coord_signature"))), 0, null, 2);
            var raw = args.GetProperty("rest");
            if (raw.ValueKind != JsonValueKind.Array || raw.GetArrayLength() > 4096 || raw.EnumerateArray().Any(v => v.ValueKind != JsonValueKind.String)) throw new ArgumentException("rest must be a bounded string array.");
            string[] rest = raw.EnumerateArray().Select(v => v.GetString()!).ToArray();
            if (rest.Sum(s => s.Length) > 262144) throw new ArgumentException("rest exceeds 262144 UTF-16 units.");
            return operation switch { "coord-anchor" => Anchor(ctx, rest), "point-plan" => PointPlan(ctx, rest), "target-validate" => Validate(ctx, rest), _ => throw new ArgumentException("Unsupported precision operation.") };
        }
        catch (NeedReply pending) { return D("state", "query", "query", pending.Descriptor, "queries", ctx.Queries.ToArray()); }
        catch (Exception ex) { return D("state", "error", "error", ex.Message, "queries", ctx.Queries.ToArray()); }
    }
    private static string? V(string[] rest, string name) { for (int i = 0; i + 1 < rest.Length; i++) if (Eq(rest[i], name)) return rest[i + 1]; return null; }
    private static bool B(string[] rest, string name) => rest.Any(s => Eq(s, name));
    private static string? Match(string[] rest) => new[] { V(rest, "--target-match"), V(rest, "--match"), V(rest, "--window") }.FirstOrDefault(T);
    private static void Opt(List<string> args, string name, object? value) { if (T(value)) args.AddRange([name, S(value)]); }
    private sealed record Options(int X, int Y, int Hwnd, string? Match, int Inset, int Radius, int Step, int Ttl, bool NoCache, bool Brief);
    private static Options Parse(Context ctx, string[] rest, string operation)
    {
        int x = I(V(rest, "--x")), y = I(V(rest, "--y")), hwnd = I(V(rest, "--target-hwnd")), inset = I(V(rest, "--click-inset"));
        int radius = T(V(rest, "--radius")) ? I(V(rest, "--radius")) : 6, step = T(V(rest, "--step")) ? I(V(rest, "--step")) : 2, ttl = T(V(rest, "--cache-ttl")) ? I(V(rest, "--cache-ttl")) : I(P(ctx.Args, "cache_seconds"));
        if (operation == "target-validate")
        {
            string min = LegacyTextKernel.LowerValue(T(V(rest, "--min-confidence")) ? V(rest, "--min-confidence")! : "medium", CultureInfo.InvariantCulture);
            if (min is not ("low" or "medium" or "high")) throw new InvalidOperationException("macro target-validate --min-confidence must be low, medium, or high");
        }
        if (x <= 0 || y <= 0) throw new InvalidOperationException($"macro {operation} requires --x and --y");
        return new(x, y, hwnd, Match(rest), inset <= 0 ? 2 : inset, Math.Clamp(radius, 0, 64), step <= 0 ? 2 : Math.Min(step, 16), B(rest, "--no-cache") ? 0 : Math.Max(ttl, 0), B(rest, "--no-cache"), T(P(ctx.Args, "brief")) && !B(rest, "--json-only"));
    }
}
