using System.Globalization;
using System.Runtime.InteropServices;
using System.Text.Json;
using System.Text.RegularExpressions;

/// <summary>Read-only ranking over supplied probe/history snapshots; never probes or launches.</summary>
internal static class LegacyStrategyKernel
{
    private sealed class Route(string name)
    {
        internal string Name = name;
        internal int Score;
        internal List<string> Reasons = [];
    }
    private sealed record Ranked(string route, int score, IReadOnlyList<string> reasons);
    private static readonly (string Pattern, string Value)[] Aliases =
    [
        ("^cdp", "cdp_dom"), ("^uia_set_value$", "uia_value_or_pattern"), ("^uia_pattern$", "uia_pattern"),
        ("^uia_precision_point$", "precision_point"), ("^uia_coord$", "uia_click"),
        ("^fusion_uia_invoke$", "fusion_uia_invoke"), ("^fusion_coord$", "ocr"),
        ("^ocr_text$", "ocr"), ("^vision_precise$", "vision_precise")
    ];
    private static void Fields(JsonElement args, params string[] allowed)
    {
        if (args.ValueKind != JsonValueKind.Object) throw CommandOptions.Invalid("Strategy arguments must be an object.");
        var seen = new HashSet<string>(StringComparer.Ordinal);
        foreach (var field in args.EnumerateObject())
            if (!seen.Add(field.Name) || !allowed.Contains(field.Name)) throw CommandOptions.Invalid("Unknown or duplicate strategy argument.");
    }
    private static string Text(JsonElement obj, string key, int maximum = 4096)
    {
        if (!obj.TryGetProperty(key, out var value) || value.ValueKind == JsonValueKind.Null) return string.Empty;
        return String(value, maximum);
    }
    private static string String(JsonElement value, int maximum = 4096)
    {
        if (value.ValueKind == JsonValueKind.Null) return string.Empty;
        if (value.ValueKind != JsonValueKind.String || value.GetString()!.Length > maximum) throw CommandOptions.Invalid("Expected bounded strategy string.");
        return value.GetString()!;
    }
    private static bool Boolean(JsonElement obj, string key)
    {
        if (!obj.TryGetProperty(key, out var value) || value.ValueKind == JsonValueKind.Null) return false;
        if (value.ValueKind is not (JsonValueKind.True or JsonValueKind.False)) throw CommandOptions.Invalid($"{key} must be boolean.");
        return value.GetBoolean();
    }
    private static int Integer(JsonElement obj, string key)
    {
        if (!obj.TryGetProperty(key, out var value) || value.ValueKind == JsonValueKind.Null) return 0;
        if (value.ValueKind != JsonValueKind.Number || !value.TryGetInt32(out var result)) throw CommandOptions.Invalid($"{key} must be an integer.");
        return result;
    }
    private static JsonElement[] Array(JsonElement obj, string key)
    {
        if (!obj.TryGetProperty(key, out var value) || value.ValueKind == JsonValueKind.Null) return [];
        if (value.ValueKind != JsonValueKind.Array || value.GetArrayLength() > 1000) throw CommandOptions.Invalid($"{key} must be an array with at most 1000 items.");
        return value.EnumerateArray().ToArray();
    }
    private static JsonElement? Object(JsonElement args, string key)
    {
        if (!args.TryGetProperty(key, out var value) || value.ValueKind == JsonValueKind.Null) return null;
        if (value.ValueKind != JsonValueKind.Object) throw CommandOptions.Invalid($"{key} must be an object or null.");
        return value;
    }
    internal static string NormalizeValue(string? strategy, CultureInfo? culture = null)
    {
        if (string.IsNullOrEmpty(strategy)) return string.Empty;
        if (strategy.Length > 4096) throw CommandOptions.Invalid("Strategy name exceeds 4096 UTF-16 units.");
        var value = Regex.Replace(strategy, @"\+.*$", "", RegexOptions.None, TimeSpan.FromSeconds(1)).ToLowerInvariant();
        // PowerShell switch -Regex uses current-culture regex case folding, which
        // is not interchangeable with NLS linguistic comparison. Regex has no
        // public CultureInfo argument. Scope only this synchronous match so an
        // explicit score culture is honored even under a different host culture.
        var previous = CultureInfo.CurrentCulture;
        try
        {
            if (culture is not null) CultureInfo.CurrentCulture = culture;
            foreach (var alias in Aliases)
                if (Regex.IsMatch(value, alias.Pattern, RegexOptions.IgnoreCase, TimeSpan.FromSeconds(1))) return alias.Value;
            return value; // Do not trim unknown routes: legacy whitespace is significant.
        }
        finally { CultureInfo.CurrentCulture = previous; }
    }
    internal static object Normalize(JsonElement args)
    {
        Fields(args, "strategy");
        return new { value = NormalizeValue(Text(args, "strategy")) };
    }
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern int CompareStringEx(string locale, uint flags, string left, int leftLength,
        string right, int rightLength, IntPtr version, IntPtr reserved, IntPtr parameter);
    private static int CompareText(string left, string right, bool ignoreCase, CultureInfo culture)
    {
        if (!OperatingSystem.IsWindows()) return culture.CompareInfo.Compare(left, right, (ignoreCase ? CompareOptions.IgnoreCase : CompareOptions.None));
        var result = CompareStringEx(culture.Name, ignoreCase ? 1u : 0u, left, left.Length, right, right.Length, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero);
        if (result == 0) throw new NativeFailure("legacy_collation_failed", "Windows NLS route ordering failed.");
        return result - 2;
    }
    internal static object Score(JsonElement args)
    {
        Fields(args, "app_type", "route_order", "cdp_probe", "uia_probe", "labels", "persisted_strategy", "browser_like", "office_like", "no_probe", "culture");
        var culture = CultureInfo.CurrentCulture;
        if (args.TryGetProperty("culture", out var cultureValue))
        {
            if (cultureValue.ValueKind != JsonValueKind.String || cultureValue.GetString()!.Length > 128)
                throw CommandOptions.Invalid("culture must be a valid culture name of at most 128 characters.");
            try { culture = CultureInfo.GetCultureInfo(cultureValue.GetString()!); }
            catch (CultureNotFoundException) { throw CommandOptions.Invalid("Unsupported strategy culture."); }
        }
        var appType = Text(args, "app_type");
        var routeOrder = Array(args, "route_order");
        var cdp = Object(args, "cdp_probe"); var uia = Object(args, "uia_probe"); var persisted = Object(args, "persisted_strategy");
        var browser = Boolean(args, "browser_like"); var office = Boolean(args, "office_like"); var noProbe = Boolean(args, "no_probe");
        // Windows PowerShell 5.1 literal hashtables use linguistic, case-insensitive
        // keys, unlike modern PowerShell's OrdinalIgnoreCase. Use the same NLS
        // comparison as route sorting. A bounded linear map avoids mixing an ICU
        // hash with NLS equality (at most 1000 supplied routes plus fixed defaults).
        var scores = new List<Route>();
        void Add(string route, int points, string reason)
        {
            var key = NormalizeValue(route, culture);
            if (key.Length == 0) return;
            var item = scores.FirstOrDefault(existing => CompareText(existing.Name, key, true, culture) == 0);
            if (item is null) { item = new Route(key); scores.Add(item); }
            item.Score += points;
            if (reason.Length > 0) item.Reasons.Add(reason);
        }
        var rank = 0;
        foreach (var route in routeOrder)
        {
            rank++;
            Add(String(route), Math.Max(4, 24 - rank * 3), $"base_route_rank_{rank}");
        }
        if (cdp is JsonElement c)
        {
            if (Boolean(c, "available")) Add("cdp_dom", 45, "cdp_probe_available");
            else Add("cdp_dom", -18, "cdp_probe_unavailable:" + Text(c, "reason"));
        }
        else if (browser && noProbe) Add("cdp_dom", 18, "browser_like_cdp_probe_skipped");
        if (uia is JsonElement u)
        {
            if (Boolean(u, "available"))
            {
                Add("uia_pattern", 28, "uia_affordances_available");
                Add("uia_click", 16, "uia_affordances_available");
                var hits = 0;
                foreach (var hit in Array(u, "label_hits"))
                {
                    if (hit.ValueKind != JsonValueKind.Object) throw CommandOptions.Invalid("label_hits must contain objects.");
                    if (Boolean(hit, "found")) hits++;
                }
                if (hits > 0) Add("uia_pattern", Math.Min(20, hits * 6), $"uia_label_hits={hits}");
                var icons = Integer(u, "small_icon_count");
                if (icons > 0) Add("precision_point", 14, $"uia_small_icon_targets={icons}");
            }
            else
            {
                Add("ocr", 18, "uia_probe_unavailable");
                Add("precision_point", 8, "uia_probe_unavailable");
            }
        }
        else Add("uia_pattern", 10, "uia_not_probed");
        if (office)
        {
            Add("uia_value_or_pattern", 24, "document_or_mail_app");
            Add("safe_type_guarded", 16, "document_or_mail_app");
        }
        else
        {
            Add("precision_point", 10, "generic_window_coordinate_fallback");
            Add("ocr", 8, "generic_visual_text_fallback");
        }
        if (persisted is JsonElement p) Add(Text(p, "strategy"), 18, "persisted_last_good_strategy");
        var ranked = scores.Select(r => new Ranked(r.Name, Math.Clamp(r.Score, 0, 100), r.Reasons)).ToArray();
        System.Array.Sort(ranked, (left, right) =>
        {
            var byScore = right.score.CompareTo(left.score);
            return byScore != 0 ? byScore : CompareText(left.route, right.route, true, culture);
        });
        var best = ranked.FirstOrDefault(); var total = best?.score ?? 0;
        var uniqueLabels = new List<string>();
        foreach (var label in Array(args, "labels").Select(v => String(v)).Where(v => !string.IsNullOrWhiteSpace(v)))
            if (!uniqueLabels.Any(existing => CompareText(existing, label, false, culture) == 0)) uniqueLabels.Add(label);
        var labels = uniqueLabels.Count;
        return new
        {
            schema = "cucp.app-profile-strategy-score/v1", app_type = appType, recommended_strategy = best?.route ?? "none",
            confidence = total >= 75 ? "high" : total >= 50 ? "medium" : total >= 25 ? "low" : "none",
            total_score = total, route_order = ranked.Select(r => r.route).ToArray(), route_scores = ranked,
            evidence = new
            {
                cdp_probe = cdp is JsonElement cp ? new { available = Boolean(cp, "available"), reason = Text(cp, "reason"), port = Integer(cp, "port") } : null,
                uia_probe = uia is JsonElement up ? new { available = Boolean(up, "available"), affordance_count = Integer(up, "affordance_count"), small_icon_count = Integer(up, "small_icon_count") } : null,
                label_count = labels, persisted_strategy = persisted?.Clone()
            }
        };
    }
}
