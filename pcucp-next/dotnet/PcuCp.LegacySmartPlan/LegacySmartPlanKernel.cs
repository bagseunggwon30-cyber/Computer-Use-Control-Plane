using System.Globalization;
using System.Text.Json;
using System.Text.RegularExpressions;

// Captured replies only: no subprocess, filesystem, network, GUI or input API.
internal static class LegacySmartPlanKernel
{
    private sealed class NeedReply(object query) : Exception { internal object Query = query; }
    private static Dictionary<string, object?> D(params object?[] pairs)
    {
        var result = new Dictionary<string, object?>();
        for (int i = 0; i < pairs.Length; i += 2) result.Add((string)pairs[i]!, pairs[i + 1]);
        return result;
    }
    private static object? P(object? value, string name)
    {
        if (value is JsonElement j && j.ValueKind == JsonValueKind.Object)
            foreach (var item in j.EnumerateObject()) if (string.Equals(item.Name, name, StringComparison.OrdinalIgnoreCase)) return item.Value.Clone();
        if (value is Dictionary<string, object?> d) return d.GetValueOrDefault(name);
        return null;
    }
    private static bool T(object? value) => value switch
    {
        null => false, bool b => b, string s => s.Length != 0, int i => i != 0,
        JsonElement j => j.ValueKind switch
        {
            JsonValueKind.Null or JsonValueKind.False => false, JsonValueKind.True or JsonValueKind.Object => true,
            JsonValueKind.String => j.GetString()!.Length != 0, JsonValueKind.Number => j.GetDouble() != 0,
            JsonValueKind.Array => j.GetArrayLength() > 1 || (j.GetArrayLength() == 1 && T(j[0])), _ => false
        }, _ => true
    };
    private static string S(object? value) => value switch
    {
        null => "", string s => s, bool b => b ? "True" : "False",
        JsonElement j => j.ValueKind switch
        {
            JsonValueKind.Null => "", JsonValueKind.String => j.GetString()!, JsonValueKind.True => "True", JsonValueKind.False => "False",
            JsonValueKind.Array => string.Join(" ", j.EnumerateArray().Select(v => S(v))),
            JsonValueKind.Object => "@{" + string.Join("; ", j.EnumerateObject().Select(p => p.Name + "=" + S(p.Value))) + "}",
            _ => j.ToString()
        }, _ => Convert.ToString(value, CultureInfo.InvariantCulture) ?? ""
    };
    private static int I(object? value)
    {
        if (value is JsonElement jb && jb.ValueKind is JsonValueKind.True or JsonValueKind.False) return T(value) ? 1 : 0;
        string s = S(value); if (s.Length == 0) return 0;
        try
        {
            if (value is JsonElement number && number.ValueKind == JsonValueKind.Number) return Convert.ToInt32(number.GetDouble());
            if (s.StartsWith("0x", StringComparison.OrdinalIgnoreCase)) return unchecked((int)uint.Parse(s[2..], NumberStyles.HexNumber, CultureInfo.InvariantCulture));
            return Convert.ToInt32(double.Parse(s, NumberStyles.Float | NumberStyles.AllowThousands, CultureInfo.InvariantCulture));
        }
        catch (Exception ex) when (ex is FormatException or OverflowException)
        { throw new InvalidOperationException($"Cannot convert value \"{s}\" to type \"System.Int32\". Error: \"{(ex is FormatException ? "Input string was not in a correct format." : ex.Message)}\""); }
    }
    private static bool Eq(object? a, string b) => string.Equals(S(a), b, StringComparison.InvariantCultureIgnoreCase);
    private static string Step(IEnumerable<string> command) => string.Join(" ", command.Select(s => Regex.IsMatch(s, @"^[A-Za-z0-9_\-\.\/\\:=@]+$") ? s : "'" + s.Replace("'", "''") + "'"));
    internal static object Advance(JsonElement args)
    {
        if (args.ValueKind != JsonValueKind.Object || args.GetRawText().Length > 4194304) throw new ArgumentException("Expected bounded smart-plan object.");
        var allowed = new HashSet<string> { "rest", "cache_seconds", "brief", "elapsed_ms", "captured_replies" };
        foreach (var p in args.EnumerateObject()) if (!allowed.Remove(p.Name)) throw new ArgumentException("Unknown or duplicate smart-plan argument.");
        var raw = args.GetProperty("rest");
        if (raw.ValueKind != JsonValueKind.Array || raw.GetArrayLength() > 4096) throw new ArgumentException("rest must be a bounded array.");
        var rest = raw.EnumerateArray().Select(j => j.ValueKind == JsonValueKind.String ? j.GetString()! : throw new ArgumentException("rest must contain strings.")).ToArray();
        if (rest.Sum(s => s.Length) > 262144) throw new ArgumentException("rest exceeds 262144 UTF-16 units.");
        string? V(string name) { for (int i = 0; i + 1 < rest.Length; i++) if (Eq(rest[i], name)) return rest[i + 1]; return null; }
        bool B(string name) => rest.Any(s => Eq(s, name));
        string? F(string? a, string? b) => T(a) ? a : b;
        string? label = V("--label"), typeText = V("--type-text"), match = F(V("--match"), V("--window")), role = V("--role");
        string ocrMatch = F(V("--ocr-match"), "contains")!, ocrLang = V("--ocr-language") ?? "";
        string? page = V("--cdp-page-match"), portRaw = V("--cdp-port");
        int port = I(portRaw); if (port <= 0) port = 9222;
        if (!T(label)) throw new InvalidOperationException("macro smart-plan requires --label");
        int radius = 6, step = 2, ttl = I(P(args, "cache_seconds"));
        string? radiusRaw = F(V("--precision-radius"), V("--point-radius")), stepRaw = F(V("--precision-step"), V("--point-step")), ttlRaw = F(V("--point-cache-ttl"), V("--cache-ttl"));
        if (T(radiusRaw)) radius = I(radiusRaw); if (T(stepRaw)) step = I(stepRaw); if (T(ttlRaw)) ttl = I(ttlRaw);
        radius = Math.Clamp(radius, 0, 64); step = step <= 0 ? 2 : Math.Min(step, 16); ttl = Math.Max(ttl, 0);
        bool type = typeText != null, precision = B("--precision-points") || B("--point-plan");
        bool cdpEnabled = !B("--no-cdp") && (B("--allow-cdp") || T(page) || T(portRaw));
        if (args.TryGetProperty("captured_replies", out var captured) && captured.ValueKind != JsonValueKind.Array) throw new ArgumentException("captured_replies must be an array.");
        var replies = captured.ValueKind == JsonValueKind.Array ? captured.EnumerateArray().ToArray() : [];
        if (replies.Length > 5) throw new ArgumentException("At most five captured replies are allowed.");
        var queries = new List<object>(); int cursor = 0;
        object? Query(string kind, params string[] argv)
        {
            var descriptor = D("kind", kind, "argv", argv); queries.Add(descriptor);
            if (cursor >= replies.Length) throw new NeedReply(descriptor);
            var reply = replies[cursor++];
            if (reply.ValueKind != JsonValueKind.Object) throw new ArgumentException("Captured reply must be an object.");
            var keys = new HashSet<string>(StringComparer.Ordinal);
            foreach (var field in reply.EnumerateObject())
                if (!keys.Add(field.Name) || field.Name is not ("kind" or "argv" or "result" or "error"))
                    throw new ArgumentException("Unknown or duplicate captured reply field.");
            if (keys.Count != 3 || !reply.TryGetProperty("kind", out var actualKind) || actualKind.ValueKind != JsonValueKind.String || actualKind.GetString() != kind ||
                !reply.TryGetProperty("argv", out var actualArgv) || actualArgv.ValueKind != JsonValueKind.Array ||
                !actualArgv.EnumerateArray().All(v => v.ValueKind == JsonValueKind.String) ||
                !actualArgv.EnumerateArray().Select(v => v.GetString()).SequenceEqual(argv))
                throw new ArgumentException("Captured reply descriptor does not match exact query order/argv.");
            bool hasResult = reply.TryGetProperty("result", out var result), hasError = reply.TryGetProperty("error", out var error);
            if (hasResult == hasError) throw new ArgumentException("Captured reply must contain exactly one result or error.");
            if (hasError)
            {
                if (error.ValueKind != JsonValueKind.String) throw new ArgumentException("Captured error must be a string.");
                if (kind == "history") return null; // Original history lookup catches failures.
                throw new InvalidOperationException(error.GetString());
            }
            return result.Clone();
        }
        var candidates = new List<Dictionary<string, object?>>(); var checks = new List<object>();
        void Add(string route, int stage, long promotedScore, bool moved, List<string> command, object? evidence, string reason)
        {
            // PS promotes arithmetic, then binds the nested helper's [int] Score.
            // Keep that boundary; rank itself has no [int] cast and may be Int64.
            if (promotedScore < int.MinValue || promotedScore > int.MaxValue)
                throw new InvalidOperationException($"Cannot process argument transformation on parameter 'Score'. Cannot convert value \"{promotedScore}\" to type \"System.Int32\". Error: \"Value was either too large or too small for an Int32.\"");
            int score = (int)promotedScore;
            candidates.Add(D("route", route, "stage", stage, "score", score, "rank", 1000L - stage * 100 + score, "safe_to_act", true, "mouse_moved", moved, "command", command.ToArray(), "reason", reason, "evidence", evidence));
        }
        void Check(string source, string status, string reason, int exit = 0, object? evidence = null)
            => checks.Add(D("source", source, "status", status, "reason", reason, "exit", exit, "evidence", evidence));
        void Opt(List<string> command, string key, string? value) { if (T(value)) command.AddRange([key, value!]); }
        object? Evidence(object? top, params string[] names)
        {
            var e = D("matched_text", S(P(top, "text")), "role", S(P(top, "role")), "automation_id", S(P(top, "automation_id")));
            foreach (string name in names) e[name] = P(top, name); return e;
        }
        try
        {
            var history = Query("history", label!, match ?? "", "5");
            // PS5 ConvertTo-Json retains the Count ETS property on an array
            // returned as one pipeline object by the history query boundary.
            if (history is JsonElement historyArray && historyArray.ValueKind == JsonValueKind.Array)
                history = D("value", historyArray.Clone(), "Count", historyArray.GetArrayLength());
            if (cdpEnabled)
            {
                if (T(Query("cdp_port", port.ToString(CultureInfo.InvariantCulture), "120")))
                {
                    var cdpArgs = new List<string> { "-Action", type ? "cdp-smart-type-find" : "cdp-smart-find", "-CdpText", label!, "-CdpPort", S(port) };
                    Opt(cdpArgs, "-CdpPageMatch", F(page, match));
                    var reply = Query("native", cdpArgs.ToArray()); var json = P(reply, "Json");
                    if (T(json) && Eq(P(json, "status"), "ok"))
                    {
                        var command = type ? new List<string> { "macro", "cdp-smart-type", "--label", label!, "--text", typeText!, "--port", S(port) }
                            : new List<string> { "macro", "cdp-smart-click", "--text", label!, "--port", S(port) };
                        if (type && B("--press-enter")) command.Add("--press-enter"); if (type && B("--clear-first")) command.Add("--clear-first");
                        Opt(command, "--page-match", F(page, match));
                        Add(type ? "cdp_smart_type" : "cdp_smart_click", 0, I(P(json, "score")), false, command,
                            D("matched_text", S(P(json, "matched_text")), "tag_name", S(P(json, "tag_name")), "role", S(P(json, "role")), "page_title", S(P(json, "page_title")), "rect", P(json, "rect")),
                            type ? "DOM input candidate matched for direct value/event typing" : "DOM text/aria candidate matched without coordinates");
                    }
                    else Check("cdp", "partial", T(json) ? S(P(json, "reason")) : "helper_failed", I(P(reply, "ExitCode")));
                }
                else Check("cdp", "skipped", "cdp_port_closed");
            }
            else Check("cdp", "skipped", "not_requested");
            var uiaArgs = new List<string> { "-Action", "uia-find", "-Label", label! }; Opt(uiaArgs, "-Match", match); Opt(uiaArgs, "-Role", role);
            var uiaReply = Query("native", uiaArgs.ToArray()); var uia = P(uiaReply, "Json"); var top = P(uia, "top");
            if (T(uia) && T(top))
            {
                bool ambiguous = T(P(uia, "ambiguous"));
                if (Eq(P(uia, "status"), "ok") && !ambiguous)
                {
                    int score = I(P(top, "score")); var point = P(top, "click_point");
                    if (type)
                    {
                        if (T(P(top, "value_pattern")) && !T(P(top, "value_readonly")))
                        {
                            var command = new List<string> { "macro", "uia-set-value", "--label", label!, "--value", typeText! }; Opt(command, "--match", match); Opt(command, "--role", role);
                            Add("uia_set_value", 1, (long)score + 45, false, command, Evidence(top, "value_pattern", "value_readonly", "rect"), "UIA ValuePattern can set text without keyboard simulation");
                        }
                        else if (T(match) && T(point))
                        {
                            var command = new List<string> { "macro", "safe-type", "--target-match", match!, "--text", typeText! };
                            if (T(P(point, "x")) && T(P(point, "y"))) command.AddRange(["--click-x", S(P(point, "x")), "--click-y", S(P(point, "y"))]);
                            if (B("--press-enter")) command.Add("--enter");
                            Add("safe_type_guarded", 3, score, true, command, Evidence(top, "click_point", "rect"), "UIA field candidate exists; safe-type can focus target and use guarded click/type");
                        }
                        else Check("uia_type", "partial", "no_value_pattern_or_target_match", I(P(uiaReply, "ExitCode")), top);
                    }
                    else
                    {
                        string pattern = S(P(top, "invoke_pattern"));
                        if (!string.IsNullOrWhiteSpace(pattern))
                        {
                            var command = new List<string> { "macro", "uia-invoke", "--label", label! }; Opt(command, "--match", match); Opt(command, "--role", role);
                            var evidence = (Dictionary<string, object?>)Evidence(top, "rect", "click_point")!; evidence["invoke_pattern"] = pattern;
                            Add("uia_pattern", 1, (long)score + 40, false, command, evidence, "UIA pattern can invoke without mouse movement");
                        }
                        else
                        {
                            bool precisionAdded = false;
                            if (precision && T(match) && T(point) && T(P(point, "x")) && T(P(point, "y")))
                            {
                                var validate = new[] { "macro", "target-validate", "--x", S(P(point, "x")), "--y", S(P(point, "y")), "--target-match", match!, "--radius", S(radius), "--step", S(step) };
                                var command = new List<string> { "macro", "click-point", "--x", S(P(point, "x")), "--y", S(P(point, "y")), "--target-match", match!, "--refine", "uia-safe", "--micro-refine", "--precision-radius", S(radius), "--precision-step", S(step), "--cache-ttl", S(ttl) };
                                var evidence = (Dictionary<string, object?>)Evidence(top, "rect", "click_point")!;
                                evidence["precision_radius"] = radius; evidence["precision_step"] = step; evidence["cache_ttl_seconds"] = ttl;
                                evidence["target_validate_command"] = validate; evidence["target_validate_command_line"] = Step(validate);
                                evidence["click_point_defaults"] = D("micro_refine", "enabled_by_default_when_target_guard_present", "anchor_reuse_history", "scored_before_click_and_recorded_after_success");
                                Add("uia_precision_point", 2, (long)score + 25, true, command, evidence, "UIA label matched; validate target, then use guarded click-point with default micro-refine and short TTL point cache");
                                Check("point_precision", "ready", "recommended_micro_refine_click_point"); precisionAdded = true;
                            }
                            else if (precision) Check("point_precision", "skipped", "requires_target_match_and_click_point");
                            var fallback = new List<string> { "macro", "smart-click", "--label", label!, "--allow-mouse-fallback" }; Opt(fallback, "--match", match); Opt(fallback, "--role", role);
                            Add("uia_coord", 2, precisionAdded ? (long)score - 10 : score, true, fallback, Evidence(top, "rect", "click_point"), precisionAdded ? "Fallback if precision point route is not desired" : "UIA label matched; use guarded coordinate fallback");
                        }
                    }
                }
                else Check("uia", "partial", "ambiguous_or_partial", I(P(uiaReply, "ExitCode")), D("top", top, "ambiguous", ambiguous, "candidates", P(uia, "candidates")));
            }
            else Check("uia", "partial", T(uia) ? S(P(uia, "reason")) : "helper_failed", I(P(uiaReply, "ExitCode")));
            if (B("--include-ocr") && !type)
            {
                var command = new List<string> { "-Action", "ocr-uia-fuse", "-OcrText", label!, "-OcrMatch", ocrMatch }; Opt(command, "-Match", match); Opt(command, "-OcrLanguage", ocrLang);
                var reply = Query("native", command.ToArray()); var json = P(reply, "Json");
                if (T(json) && Eq(P(json, "status"), "ok"))
                {
                    string recommendation = S(P(json, "recommendation")); int score = 0; try { score = I(P(P(json, "ocr_top"), "score")); } catch { }
                    if (Eq(recommendation, "uia_invoke"))
                    {
                        var action = new List<string> { "macro", "ocr-uia-invoke", "--text", label!, "--match", ocrMatch }; Opt(action, "--match-window", match); Opt(action, "--language", ocrLang);
                        Add("fusion_uia_invoke", 4, (long)score + 30, false, action, D("ocr_top", P(json, "ocr_top"), "uia_match", P(json, "uia_match"), "invoke_pattern", S(P(json, "invoke_pattern"))), "OCR text sits on invokable UIA element");
                    }
                    else if (Eq(recommendation, "ocr_click") && score >= 70)
                    {
                        var action = new List<string> { "macro", "ocr-click", "--text", label!, "--match", ocrMatch }; Opt(action, "--target-match", match); Opt(action, "--language", ocrLang);
                        Add("ocr_text", 5, score, true, action, D("ocr_top", P(json, "ocr_top"), "region", P(json, "region")), "OCR candidate high enough for guarded text click");
                    }
                    else Check("ocr", "partial", recommendation, I(P(reply, "ExitCode")), json);
                }
                else Check("ocr", "partial", T(json) ? S(P(json, "reason")) : "helper_failed", I(P(reply, "ExitCode")));
            }
            else Check("ocr", "skipped", type ? "not_supported_for_type_plan" : "not_requested");
            if (cursor != replies.Length) throw new ArgumentException("Unused captured replies.");
            var ranked = candidates.ToArray(); LegacyRankSort(ranked);
            var best = ranked.FirstOrDefault(); bool safe = best != null;
            string confidence = safe && I(best!["stage"]) <= 1 && I(best["score"]) >= 100 ? "high" : safe && I(best!["score"]) >= 70 ? "medium" : "low";
            int elapsed = I(P(args, "elapsed_ms"));
            var payload = D("schema", "cucp.smart-plan/v1", "status", safe ? "ok" : "partial", "mode", type ? "type" : "click", "label", label, "match", match, "role", role, "type_text_length", type ? typeText!.Length : 0,
                "elapsed_ms", elapsed, "confidence", confidence, "history_hint", history, "best_route", best?.GetValueOrDefault("route"), "safe_to_act", safe,
                "recommended_command", best?.GetValueOrDefault("command"), "best", best, "candidates", ranked, "checks", checks,
                "precision_policy", D("enabled", precision, "live_click_default_micro_refine", true, "live_click_anchor_history", true, "target_validate_before_live_click", precision,
                    "disable_flags", new[] { "--no-micro-refine", "--no-anchor-history" }, "default_click_point_flags", new[] { "--target-match/--target-hwnd", "--micro-refine", "--cache-ttl", "--precision-radius", "--precision-step" }),
                "next_step", safe ? "Run recommended_command with -AllowLiveControl only after user authorization, then verify with wait-label/windows/screenshot-diff." : "No safe route. Narrow with --match/--role, enable --include-ocr, or inspect list-affordances.");
            string brief = safe ? $"ok smart-plan '{label}' route={best!["route"]} confidence={confidence} mouse_moved={S(best["mouse_moved"])} candidates={candidates.Count} elapsed_ms={elapsed}"
                : $"partial smart-plan '{label}' no_safe_route checks={checks.Count} elapsed_ms={elapsed}";
            return D("state", "complete", "payload", payload, "exit", safe ? 0 : 2, "brief", T(P(args, "brief")) && !B("--json-only") ? brief : null, "queries", queries);
        }
        catch (NeedReply needed) { return D("state", "query", "query", needed.Query, "queries", queries); }
        catch (Exception error) { return D("state", "error", "error", error.Message, "queries", queries); }
    }
    private static void LegacyRankSort(Dictionary<string, object?>[] values)
    {
        // At most four candidates. Match the PS5/.NET legacy median-pivot quicksort,
        // including equal-key swaps; stable LINQ OrderBy changes first-candidate choice.
        long Rank(int index) => Convert.ToInt64(values[index]["rank"], CultureInfo.InvariantCulture);
        int Compare(int a, int b) => Rank(b).CompareTo(Rank(a));
        void Swap(int a, int b) => (values[a], values[b]) = (values[b], values[a]);
        void Median(int a, int b) { if (a != b && Compare(a, b) > 0) Swap(a, b); }
        void Sort(int begin, int end)
        {
            while (begin < end)
            {
                int middle = begin + (end - begin) / 2; Median(begin, middle); Median(begin, end); Median(middle, end);
                long pivot = Rank(middle); int a = begin, b = end;
                while (a <= b)
                {
                    while (Rank(a) > pivot) a++; while (Rank(b) < pivot) b--;
                    if (a > b) break; Swap(a++, b--);
                }
                if (b - begin <= end - a) { if (begin < b) Sort(begin, b); begin = a; }
                else { if (a < end) Sort(a, end); end = b; }
            }
        }
        if (values.Length > 1) Sort(0, values.Length - 1);
    }
}
