using System.Globalization;
using System.Runtime.InteropServices;
using System.Text.Json;
using System.Text.RegularExpressions;

// Pure captured-reply replay. Descriptors are data, never executable commands.
internal static class LegacyAppProfileKernel
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
        if (value is JsonElement j)
        {
            if (j.ValueKind == JsonValueKind.Object)
                foreach (var p in j.EnumerateObject()) if (string.Equals(p.Name, name, StringComparison.OrdinalIgnoreCase)) return p.Value.Clone();
            if (j.ValueKind == JsonValueKind.Array)
                return j.EnumerateArray().Select(v => P(v, name)).Where(v => v is not null).ToArray();
        }
        if (value is Dictionary<string, object?> d) return d.GetValueOrDefault(name);
        return null;
    }
    private static object?[] A(object? value) => value switch
    {
        null => [], JsonElement { ValueKind: JsonValueKind.Null } => [],
        JsonElement { ValueKind: JsonValueKind.Array } j => j.EnumerateArray().Select(v => (object?)v.Clone()).ToArray(),
        object?[] a => a, _ => [value]
    };
    private static bool T(object? value) => value switch
    {
        null => false, bool b => b, string s => s.Length > 0, int i => i != 0,
        object?[] a => a.Length > 1 || (a.Length == 1 && T(a[0])),
        JsonElement j => j.ValueKind switch
        {
            JsonValueKind.Null or JsonValueKind.False => false, JsonValueKind.True or JsonValueKind.Object => true,
            JsonValueKind.String => j.GetString()!.Length > 0, JsonValueKind.Number => j.GetDouble() != 0,
            JsonValueKind.Array => j.GetArrayLength() > 1 || (j.GetArrayLength() == 1 && T(j[0])), _ => false
        }, _ => true
    };
    private static string S(object? value) => value switch
    {
        null => "", string s => s, bool b => b ? "True" : "False",
        object?[] a => string.Join(" ", a.Select(S)),
        JsonElement j => j.ValueKind switch
        {
            JsonValueKind.Null => "", JsonValueKind.String => j.GetString()!, JsonValueKind.True => "True", JsonValueKind.False => "False",
            JsonValueKind.Array => string.Join(" ", j.EnumerateArray().Select(v => S(v))),
            JsonValueKind.Object => "@{" + string.Join("; ", j.EnumerateObject().Select(p => p.Name + "=" + S(p.Value))) + "}",
            _ => j.ToString()
        }, _ => Convert.ToString(value, CultureInfo.InvariantCulture) ?? ""
    };
    private static long N(object? value, bool wide = false)
    {
        string source = S(value), type = wide ? "Int64" : "Int32";
        if (source.Length == 0) return 0;
        string failure;
        try
        {
            if (value is JsonElement b && b.ValueKind is JsonValueKind.True or JsonValueKind.False) return T(b) ? 1 : 0;
            if (value is JsonElement number && number.ValueKind == JsonValueKind.Number)
            {
                if (wide && number.TryGetInt64(out long exact)) return exact;
                return wide ? Convert.ToInt64(number.GetDouble()) : Convert.ToInt32(number.GetDouble());
            }
            string text = source.Trim();
            if (text.Length == 0) throw new IndexOutOfRangeException();
            if (text.StartsWith("0x", StringComparison.OrdinalIgnoreCase))
            {
                try { return wide ? unchecked((long)ulong.Parse(text[2..], NumberStyles.AllowHexSpecifier, CultureInfo.InvariantCulture)) : unchecked((int)uint.Parse(text[2..], NumberStyles.AllowHexSpecifier, CultureInfo.InvariantCulture)); }
                catch (OverflowException) { throw new InvalidOperationException($"Cannot convert value \"{source}\" to type \"System.{type}\". Error: \"Value was either too large or too small for a U{type}.\""); }
            }
            try { return wide ? long.Parse(text, NumberStyles.Integer, CultureInfo.InvariantCulture) : int.Parse(text, NumberStyles.Integer, CultureInfo.InvariantCulture); }
            catch (FormatException)
            {
                try
                {
                    double numberValue = double.Parse(text, NumberStyles.Float | NumberStyles.AllowThousands, CultureInfo.InvariantCulture);
                    if (!double.IsFinite(numberValue)) throw new FormatException();
                    return wide ? Convert.ToInt64(numberValue) : Convert.ToInt32(numberValue);
                }
                catch (Exception fallback) when (fallback is FormatException or OverflowException) { throw new FormatException(); }
            }
        }
        catch (FormatException) { failure = "Input string was not in a correct format."; }
        catch (IndexOutOfRangeException) { failure = "Index was outside the bounds of the array."; }
        catch (OverflowException) { failure = $"Value was either too large or too small for an {type}."; }
        throw new InvalidOperationException($"Cannot convert value \"{source}\" to type \"System.{type}\". Error: \"{failure}\"");
    }
    private static int I(object? value) => (int)N(value);
    private static bool Eq(object? value, string expected) => string.Equals(S(value), expected, StringComparison.InvariantCultureIgnoreCase);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern int CompareStringEx(string locale, uint flags, string left, int leftLength, string right, int rightLength, IntPtr version, IntPtr reserved, IntPtr parameter);
    private static int CompareText(string left, string right, bool ignoreCase, CultureInfo culture)
    {
        if (!OperatingSystem.IsWindows()) return culture.CompareInfo.Compare(left, right, ignoreCase ? CompareOptions.IgnoreCase : CompareOptions.None);
        int result = CompareStringEx(culture.Name, ignoreCase ? 1u : 0u, left, left.Length, right, right.Length, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero);
        if (result == 0) throw new InvalidOperationException("Windows NLS app-profile comparison failed.");
        return result - 2;
    }
    private static string[] Unique(IEnumerable<string> items, CultureInfo culture)
    {
        var result = new List<string>();
        foreach (string item in items)
            if (!string.IsNullOrWhiteSpace(item) && !result.Any(previous => CompareText(previous, item, false, culture) == 0)) result.Add(item);
        return result.ToArray();
    }
    // PS5's legacy .NET median-pivot quicksort is deliberately unstable for tied keys.
    private static void LegacySort<T>(T[] values, Comparison<T> compare)
    {
        void Swap(int a, int b) => (values[a], values[b]) = (values[b], values[a]);
        void Median(int a, int b) { if (a != b && compare(values[a], values[b]) > 0) Swap(a, b); }
        void Sort(int begin, int end)
        {
            while (begin < end)
            {
                int middle = begin + (end - begin) / 2; Median(begin, middle); Median(begin, end); Median(middle, end);
                T pivot = values[middle]; int a = begin, b = end;
                while (a <= b)
                {
                    while (compare(values[a], pivot) < 0) a++;
                    while (compare(values[b], pivot) > 0) b--;
                    if (a > b) break;
                    Swap(a++, b--);
                }
                if (b - begin <= end - a) { if (begin < b) Sort(begin, b); begin = a; }
                else { if (a < end) Sort(a, end); end = b; }
            }
        }
        if (values.Length > 1) Sort(0, values.Length - 1);
    }
    internal static object Advance(JsonElement args)
    {
        var queries = new List<object>();
        try { return Replay(args, queries); }
        catch (NeedReply next) { return D("state", "query", "query", next.Query, "queries", queries); }
        catch (Exception ex) { return D("state", "error", "error", ex.Message, "queries", queries); }
    }
    private static string[] ReadRest(JsonElement args)
    {
        if (args.ValueKind != JsonValueKind.Object || args.GetRawText().Length > 4194304) throw new ArgumentException("Expected bounded app-profile object.");
        var fields = new HashSet<string> { "rest", "brief", "culture", "elapsed_ms", "cdp_elapsed_ms", "uia_elapsed_ms", "history_file", "captured_replies" };
        foreach (var field in args.EnumerateObject()) if (!fields.Remove(field.Name)) throw new ArgumentException("Unknown or duplicate app-profile argument.");
        if (!args.TryGetProperty("rest", out var raw) || raw.ValueKind != JsonValueKind.Array || raw.GetArrayLength() > 4096) throw new ArgumentException("rest must be a bounded array.");
        string[] rest = raw.EnumerateArray().Select(j => j.ValueKind == JsonValueKind.String ? j.GetString()! : j.ValueKind == JsonValueKind.Null ? "" : throw new ArgumentException("rest must contain strings or null.")).ToArray();
        if (rest.Sum(s => s.Length) > 262144) throw new ArgumentException("rest exceeds 262144 UTF-16 units.");
        return rest;
    }
    private static string? Option(string[] rest, string name) { for (int i = 0; i + 1 < rest.Length; i++) if (Eq(rest[i], name)) return rest[i + 1]; return null; }
    private static string[] AllOptions(string[] rest, string name) { var values = new List<string>(); for (int i = 0; i + 1 < rest.Length; i++) if (Eq(rest[i], name)) values.Add(rest[++i]); return values.ToArray(); }
    private static bool Switch(string[] rest, string name) => rest.Any(s => Eq(s, name));
    private static string? WindowMatch(string[] rest) { string? match = Option(rest, "--match"); return T(match) ? match : Option(rest, "--window"); }
    private static bool RecordRequested(string[] rest) => Switch(rest, "--record-strategy") || Switch(rest, "--remember-strategy");
    private static CultureInfo ReadCulture(JsonElement args)
    {
        CultureInfo culture = CultureInfo.CurrentCulture;
        if (args.TryGetProperty("culture", out var cultureValue))
        {
            if (cultureValue.ValueKind != JsonValueKind.String || cultureValue.GetString()!.Length > 128) throw new ArgumentException("culture must be a bounded string.");
            culture = CultureInfo.GetCultureInfo(cultureValue.GetString()!);
        }
        return culture;
    }
    private static object? ReadHistoryFile(JsonElement args)
    {
        var historyFile = P(args, "history_file");
        if (historyFile is JsonElement hf && hf.ValueKind is not (JsonValueKind.String or JsonValueKind.Null)) throw new ArgumentException("history_file must be a string or null.");
        return historyFile;
    }
    private static bool ReadBrief(JsonElement args, bool jsonOnly)
    {
        if (args.TryGetProperty("brief", out var briefArg) && briefArg.ValueKind is not (JsonValueKind.True or JsonValueKind.False)) throw new ArgumentException("brief must be boolean.");
        return T(P(args, "brief")) && !jsonOnly;
    }
    private sealed class CaptureReader
    {
        private readonly JsonElement[] replies;
        private readonly List<object> queries;
        private int cursor;
        internal CaptureReader(JsonElement args, List<object> queries)
        {
            this.queries = queries;
            if (args.TryGetProperty("captured_replies", out var captured) && captured.ValueKind != JsonValueKind.Array) throw new ArgumentException("captured_replies must be an array.");
            replies = captured.ValueKind == JsonValueKind.Array ? captured.EnumerateArray().ToArray() : [];
            if (replies.Length > 7) throw new ArgumentException("At most seven captured replies are allowed.");
        }
        internal bool HasUnusedReplies => cursor != replies.Length;
        internal object? Query(string kind, params string[] argv)
        {
            var descriptor = D("kind", kind, "argv", argv); queries.Add(descriptor);
            if (cursor >= replies.Length) throw new NeedReply(descriptor);
            var reply = replies[cursor++];
            if (reply.ValueKind != JsonValueKind.Object) throw new ArgumentException("Captured reply must be an object.");
            var names = new HashSet<string>(StringComparer.Ordinal);
            foreach (var p in reply.EnumerateObject())
                if (!names.Add(p.Name) || p.Name is not ("kind" or "argv" or "result" or "error")) throw new ArgumentException("Unknown or duplicate captured reply field.");
            if (names.Count != 3 || !reply.TryGetProperty("kind", out var kindValue) || kindValue.ValueKind != JsonValueKind.String || kindValue.GetString() != kind ||
                !reply.TryGetProperty("argv", out var argValue) || argValue.ValueKind != JsonValueKind.Array ||
                !argValue.EnumerateArray().All(v => v.ValueKind == JsonValueKind.String) || !argValue.EnumerateArray().Select(v => v.GetString()).SequenceEqual(argv))
                throw new ArgumentException("Captured reply descriptor does not match exact query order/argv.");
            bool hasResult = reply.TryGetProperty("result", out var result), hasError = reply.TryGetProperty("error", out var error);
            if (hasResult == hasError) throw new ArgumentException("Captured reply must contain exactly one result or error.");
            if (hasError)
            {
                if (error.ValueKind != JsonValueKind.String) throw new ArgumentException("Captured error must be a string.");
                if (kind == "history") return null;
                throw new InvalidOperationException(error.GetString());
            }
            return result.Clone();
        }
    }
    private static (object?[] Visible, object? Target) SelectWindow(string? match, Func<string, string[], object?> query)
    {
        object?[] all = A(query("windows", []));
        object?[] visible = all.Where(w => T(P(w, "visible"))).ToArray();
        object?[] candidates = T(match) ? A(query("windows", ["-Match", match!])).Where(w => T(P(w, "visible"))).ToArray() : visible;
        object?[] eligible = candidates.Where(w => !T(P(w, "minimized"))).ToArray(); if (eligible.Length == 0) eligible = candidates;
        // Evaluate each source sort key once, matching Sort-Object's key capture.
        var windows = eligible.Select(w => (Window: w, Foreground: T(P(w, "foreground")) ? 0 : 1, Title: T(P(w, "title")) ? 0 : 1,
            Area: -(double)I(P(P(w, "rect"), "width")) * I(P(P(w, "rect"), "height")))).ToArray();
        LegacySort(windows, (left, right) => { int c = left.Foreground.CompareTo(right.Foreground); if (c == 0) c = left.Title.CompareTo(right.Title); return c == 0 ? left.Area.CompareTo(right.Area) : c; });
        object? target = windows.FirstOrDefault().Window;
        return (visible, target);
    }
    private static string Lower(string value) => LegacyStrategyKernel.LowerValue(value, CultureInfo.InvariantCulture);
    private static (string Title, string Process, string Class, string TargetMatch, bool Browser, bool Office) IdentifyWindow(object? target, string? match, CultureInfo culture)
    {
        string title = T(P(target, "title")) ? S(P(target, "title")) : "", process = T(P(target, "process")) ? S(P(target, "process")) : "", @class = T(P(target, "class")) ? S(P(target, "class")) : "";
        string titleLower = Lower(title), processLower = Lower(process), classLower = Lower(@class);
        string identity = (titleLower + " " + processLower + " " + classLower).Trim();
        string targetMatch = T(match) ? match! : T(title) ? title : T(process) ? process : S(P(target, "hwnd"));
        bool Match(string value, string pattern)
        {
            var previous = CultureInfo.CurrentCulture;
            try { CultureInfo.CurrentCulture = culture; return Regex.IsMatch(value, pattern, RegexOptions.IgnoreCase, TimeSpan.FromSeconds(1)); }
            finally { CultureInfo.CurrentCulture = previous; }
        }
        // The source wildcard has only leading/trailing stars. Its literal
        // characters are lowercased with the current culture before matching.
        bool browser = Match(processLower, "^(chrome|msedge|brave|firefox|electron|cursor|code|windsurf)$") ||
            LegacyStrategyKernel.LowerValue(classLower, culture).Contains(LegacyStrategyKernel.LowerValue("chrome_widgetwin", culture), StringComparison.Ordinal);
        bool office = Match(identity, "winword|excel|powerpnt|outlook|onenote|hwp|wordpad|notepad");
        return (title, process, @class, targetMatch, browser, office);
    }
    private static string AppType(bool browser, bool office) => browser ? "browser_or_electron" : office ? "document_or_mail_app" : "win32_desktop";
    private static string AppKey(string process, string @class, string appType, CultureInfo culture)
    {
        string KeyPart(string value)
        {
            // PowerShell -replace remains case-insensitive after ToLowerInvariant.
            // Non-ASCII case equivalents can therefore survive the ASCII range.
            return LegacyTextKernel.SanitizeAppKeyPart(Lower(value.Trim()), culture);
        }
        string appKey = string.Join("|", new[] { process, @class, appType }.Select(KeyPart).Where(s => s.Length > 0));
        return appKey.Length == 0 ? "unknown-app" : appKey;
    }
    private static Dictionary<string, object?> SelectedWindow(object? target, string title, string process, string @class) =>
        D("title", title, "process", process, "class", @class, "hwnd", P(target, "hwnd"), "pid", P(target, "pid"), "foreground", T(P(target, "foreground")), "minimized", T(P(target, "minimized")), "rect", P(target, "rect"));
    private static object? EvidenceCapture(object? value) => value is JsonElement { ValueKind: JsonValueKind.Array } array ? D("value", array, "Count", array.GetArrayLength()) : value;
    private static bool Recorded(object? value) => T(value) && !T(P(value, "error"));
    internal static JsonElement RecordOutcome(JsonElement value) => JsonSerializer.SerializeToElement(D("recorded", Recorded(value), "record", EvidenceCapture(value)));
    // Called only after Advance has consumed every required windows capture.
    // This reuses captured data and never requests acquisition from the caller.
    internal static JsonElement RecordBinding(JsonElement args)
    {
        string[] rest = ReadRest(args);
        string? match = WindowMatch(rest);
        CultureInfo culture = ReadCulture(args);
        object? historyFile = ReadHistoryFile(args);
        var captures = new CaptureReader(args, []);
        var (_, target) = SelectWindow(match, captures.Query);
        string appType = "unknown", appKey = "not_found";
        object? selectedWindow = null;
        if (T(target))
        {
            var (title, process, @class, _, browser, office) = IdentifyWindow(target, match, culture);
            appType = AppType(browser, office);
            appKey = AppKey(process, @class, appType, culture);
            selectedWindow = SelectedWindow(target, title, process, @class);
        }
        return JsonSerializer.SerializeToElement(D("record_requested", RecordRequested(rest), "no_history", Switch(rest, "--no-strategy-history"),
            "history_file", historyFile, "app_type", appType, "app_key", appKey, "selected_window", selectedWindow, "brief_enabled", ReadBrief(args, Switch(rest, "--json-only"))));
    }
    private static object Replay(JsonElement args, List<object> queries)
    {
        string[] rest = ReadRest(args);
        string? V(string name) => Option(rest, name);
        string[] All(string name) => AllOptions(rest, name);
        bool B(string name) => Switch(rest, name);
        string? match = WindowMatch(rest);
        bool jsonOnly = B("--json-only"), auto = B("--auto-probe") || B("--probe"), noProbe = B("--no-probe");
        bool recordRequested = RecordRequested(rest), noHistory = B("--no-strategy-history");
        int port = I(V("--cdp-port")); if (port <= 0) port = I(V("--port")); if (port <= 0) port = 9222;
        int limit = I(V("--probe-uia-limit")); if (limit <= 0) limit = 120;
        var labels = All("--label").Concat(All("--click-label")).ToList();
        foreach (string spec in All("--field")) if (spec.Contains('=')) { var label = spec[..spec.IndexOf('=')].Trim(); if (label.Length > 0) labels.Add(label); }
        CultureInfo culture = ReadCulture(args);
        int Milliseconds(string name)
        {
            if (!args.TryGetProperty(name, out var value)) return 0;
            if (value.ValueKind != JsonValueKind.Number || !value.TryGetInt32(out int n) || n < 0) throw new ArgumentException(name + " must be a nonnegative Int32.");
            return n;
        }
        int elapsed = Milliseconds("elapsed_ms"), cdpElapsed = Milliseconds("cdp_elapsed_ms"), uiaElapsed = Milliseconds("uia_elapsed_ms");
        bool brief = ReadBrief(args, jsonOnly);
        var historyFile = ReadHistoryFile(args);
        var captures = new CaptureReader(args, queries);
        object? Query(string kind, params string[] argv) => captures.Query(kind, argv);
        object Complete(Dictionary<string, object?> payload, int exit, int depth, string summary)
        {
            if (captures.HasUnusedReplies) throw new ArgumentException("Unused captured replies.");
            return D("state", "complete", "payload", payload, "exit", exit, "brief", brief ? summary : null, "json_depth", depth, "queries", queries);
        }
        var (visible, target) = SelectWindow(match, Query);
        var sample = visible.Take(10).Select(w => D("title", P(w, "title"), "process", P(w, "process"), "class", P(w, "class"), "foreground", T(P(w, "foreground")), "minimized", T(P(w, "minimized")), "rect", P(w, "rect"))).ToArray();
        string[] uniqueLabels = Unique(labels, culture);
        if (!T(target))
        {
            string reason = T(match) ? "no_matching_window" : "no_visible_window";
            var payload = D("schema", "cucp.app-profile/v1", "status", "partial", "reason", reason, "match", match, "window_count", visible.Length,
                "selected_window", null, "recommended_strategy", "not_found", "route_order", Array.Empty<string>(),
                "strategy_score", D("schema", "cucp.app-profile-strategy-score/v1", "app_type", "unknown", "recommended_strategy", "not_found", "confidence", "none", "total_score", 0,
                    "route_order", Array.Empty<string>(), "route_scores", Array.Empty<object>(), "evidence", D("cdp_probe", null, "uia_probe", null, "label_count", uniqueLabels.Length, "persisted_strategy", null)),
                "strategy_persistence", D("enabled", !noHistory, "app_key", "not_found", "history_file", historyFile, "last_good_strategy", null, "record_requested", recordRequested,
                    "recorded", false, "record", null, "skipped_reason", recordRequested ? "no_matching_window" : ""),
                "recommended_task_options", Array.Empty<string>(), "probe_commands", Array.Empty<object>(), "windows_sample", sample, "elapsed_ms", elapsed,
                "next_action", T(match) ? "Run macro windows --json-only to inspect available windows, then retry app-profile with a narrower --match." : "Open or focus the target app, then run macro app-profile again.");
            return Complete(payload, 2, 12, $"partial app-profile reason={reason} windows={visible.Length}");
        }
        var (title, process, @class, targetMatch, browser, office) = IdentifyWindow(target, match, culture);
        string Step(IEnumerable<string> command) => LegacyTaskPresetKernel.StepString(command, culture);
        object? cdp = null, uia = null;
        if (!noProbe && (auto || B("--probe-cdp") || browser))
        {
            bool available = false; string reason = "cdp_port_closed", status = "partial"; object? browserName = null, protocol = null; int pages = 0;
            if (T(Query("cdp_port", S(port), "120")))
            {
                var reply = Query("native", "-Action", "cdp-detect", "-CdpPort", S(port)); var json = P(reply, "Json");
                if (T(json) && Eq(P(json, "status"), "ok"))
                {
                    available = true; status = "ok"; reason = ""; browserName = P(json, "browser"); protocol = P(json, "protocol_version");
                    try { pages = I(P(json, "page_count")); } catch { pages = 0; }
                }
                else reason = T(json) && T(P(json, "reason")) ? S(P(json, "reason")) : "cdp_detect_failed";
            }
            cdp = D("kind", "cdp", "enabled", true, "status", status, "available", available, "port", port, "browser", browserName,
                "protocol_version", protocol, "page_count", pages, "reason", reason, "elapsed_ms", cdpElapsed);
        }
        if (!noProbe && (auto || B("--probe-uia")))
        {
            long hwnd = N(P(target, "hwnd"), true);
            var items = A(Query("uia", "-FocusedWindow", targetMatch, "-MaxElements", S(limit), "-MinSize", "6", "-Hwnd", S(hwnd)));
            var groups = new List<Dictionary<string, object?>>();
            foreach (var item in items)
            {
                string role = S(P(item, "role"));
                var group = groups.FirstOrDefault(g => CompareText(S(g["role"]), role, true, culture) == 0);
                if (group is null) groups.Add(D("role", role, "count", 1)); else group["count"] = I(group["count"]) + 1;
            }
            // PS5 Group-Object keeps first-seen group order; sorting names here
            // changes the subsequent unstable Count tie order and first eight.
            var roles = groups.ToArray();
            LegacySort(roles, (a, b) => I(b["count"]).CompareTo(I(a["count"])));
            var hits = uniqueLabels.Select(label =>
            {
                string needle = Lower(label); bool found = false;
                foreach (var item in items)
                {
                    var hay = new List<string>(); if (T(P(item, "text"))) hay.Add(S(P(item, "text")));
                    if (T(P(item, "synonyms"))) foreach (var synonym in A(P(item, "synonyms"))) if (T(synonym)) hay.Add(S(synonym));
                    if (hay.Any(s => { string lower = Lower(s); return Eq(lower, needle) || lower.Contains(needle, StringComparison.Ordinal) || needle.Contains(lower, StringComparison.Ordinal); })) { found = true; break; }
                }
                return D("label", label, "found", found);
            }).ToArray();
            uia = D("kind", "uia", "enabled", true, "status", items.Length > 0 ? "ok" : "partial", "available", items.Length > 0, "affordance_count", items.Length,
                "small_icon_count", items.Count(it => T(P(it, "small_icon"))), "roles", roles.Take(8).ToArray(), "label_hits", hits,
                "sample", items.Take(8).Select(it => D("text", P(it, "text"), "role", P(it, "role"), "rect", P(it, "rect"), "small_icon", P(it, "small_icon"), "confidence", P(it, "confidence"))).ToArray(), "elapsed_ms", uiaElapsed);
        }
        string appType = AppType(browser, office); string[] routes = ["uia_pattern", "uia_click", "precision_point", "ocr"];
        var notes = new List<string>(); var options = new List<string> { "--match", targetMatch, "--precision-points", "--settle-ms", "150", "--verify-after-step", "--retry-failed-step", "1" };
        options.RemoveAll(s => s.Length == 0); // Original nested option adder drops empty values.
        bool useCdp = false, cdpAvailable = T(cdp) && T(P(cdp, "available"));
        if (browser)
        {
            if (cdpAvailable || noProbe)
            {
                routes = ["cdp_dom", "uia_pattern", "uia_click", "ocr", "precision_point"]; options.Add("--allow-cdp"); if (port != 9222) options.AddRange(["--cdp-port", S(port)]); useCdp = true;
                notes.Add(cdpAvailable ? "CDP probe succeeded; prefer DOM actions because they avoid mouse movement and coordinate drift." : "CDP probing was skipped by --no-probe; keep CDP in the route as an opt-in assumption.");
            }
            else notes.Add("CDP probe did not confirm an available DevTools port, so the recommended route starts with UIA and precision points.");
            notes.Add("For Chrome/Electron, enable remote debugging when DOM-grade control is required.");
        }
        else if (office)
        {
            routes = ["uia_value_or_pattern", "safe_type_guarded", "shortcut", "precision_point", "ocr"];
            notes.Add("Document/mail apps usually benefit from direct UIA value/pattern actions, guarded typing, and verification after each step.");
        }
        else notes.Add("Generic Win32 route: try UIA actions first, then guarded precision points, then OCR only when labels are not exposed.");
        if (T(uia) && !T(P(uia, "available"))) notes.Add("UIA probe found no exposed affordances; expect OCR or guarded coordinate routes to matter more for this app.");
        else if (T(uia) && I(P(uia, "small_icon_count")) > 0) notes.Add("UIA probe found small icon affordances; precision-point routes are useful for tiny toolbar controls.");
        string appKey = AppKey(process, @class, appType, culture);
        object? history = noHistory ? null : Query("history", appKey);
        if (T(history)) notes.Add($"Last good app strategy found in app-strategy history: {S(P(history, "strategy"))}.");
        var scoreInput = D("app_type", appType, "route_order", routes, "cdp_probe", cdp, "uia_probe", uia, "labels", labels.ToArray(),
            "persisted_strategy", T(history) ? D("strategy", S(P(history, "strategy"))) : null, "browser_like", browser, "office_like", office, "no_probe", noProbe, "culture", culture.Name);
        var score = JsonSerializer.SerializeToElement(LegacyStrategyKernel.Score(JsonSerializer.SerializeToElement(scoreInput)));
        var strategyScore = score.EnumerateObject().ToDictionary(p => p.Name, p => (object?)p.Value.Clone());
        var evidence = score.GetProperty("evidence").EnumerateObject().ToDictionary(p => p.Name, p => (object?)p.Value.Clone());
        // The typed strategy helper sees a normalized strategy string; evidence keeps the complete capture.
        evidence["persisted_strategy"] = EvidenceCapture(history); strategyScore["evidence"] = evidence;
        object? record = null; string skipped = "", confidence = S(P(strategyScore, "confidence")), recommended = S(P(strategyScore, "recommended_strategy"));
        if (recordRequested && !noHistory)
        {
            if (confidence is "medium" or "high")
                record = Query("record", appKey, appType, recommended, confidence, S(I(P(strategyScore, "total_score"))), process, @class, title);
            else skipped = "confidence_below_medium";
        }
        else if (recordRequested && noHistory) skipped = "disabled_by_no_strategy_history";
        var commands = uniqueLabels.Select(label =>
        {
            var command = new List<string> { "macro", "smart-plan", "--label", label, "--match", targetMatch, "--precision-points" };
            if (useCdp) { command.Add("--allow-cdp"); if (port != 9222) command.AddRange(["--cdp-port", S(port)]); } command.Add("--json-only");
            return D("label", label, "command", command.ToArray(), "command_line", Step(command), "purpose", "Read-only route probe for this label before any live control.");
        }).ToArray();
        object? affordance = null;
        if (B("--include-affordances"))
        {
            string[] command = ["macro", "list-affordances", "--window", targetMatch, "--limit", "40", "--json-only"];
            affordance = D("command", command, "command_line", Step(command), "purpose", "Optional read-only UIA affordance inventory for label discovery.");
        }
        string[] prefix = new[] { "macro", "task-plan" }.Concat(options).ToArray();
        var final = D("schema", "cucp.app-profile/v1", "status", "ok", "match", match,
            "selected_window", SelectedWindow(target, title, process, @class),
            "app_type", appType, "recommended_strategy", recommended, "route_order", P(strategyScore, "route_order"), "strategy_score", strategyScore,
            "strategy_persistence", D("enabled", !noHistory, "app_key", appKey, "history_file", historyFile, "last_good_strategy", EvidenceCapture(history), "record_requested", recordRequested,
                "recorded", Recorded(record), "record", EvidenceCapture(record), "skipped_reason", skipped),
            "capability_probes", D("cdp", cdp, "uia", uia), "recommended_task_options", options.ToArray(), "suggested_task_plan_prefix", prefix,
            "suggested_task_plan_prefix_line", Step(prefix), "probe_commands", commands, "affordance_probe", affordance,
            "windows_sample", sample, "notes", notes.ToArray(), "elapsed_ms", elapsed,
            "next_action", "Append the task-specific fields/click labels/text to suggested_task_plan_prefix, run the returned plan or probe commands as read-only, then use task-run --dry-run before live control.");
        return Complete(final, 0, 14, $"ok app-profile type={appType} strategy={recommended} labels={commands.Length} elapsed_ms={elapsed}");
    }
}
