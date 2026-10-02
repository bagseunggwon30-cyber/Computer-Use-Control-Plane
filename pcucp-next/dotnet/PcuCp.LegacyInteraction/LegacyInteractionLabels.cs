using System.Text.Json;

internal sealed partial class LegacyExecutionCoordinator
{
    private static bool FilterElement(JsonElement el, string? window, string? role) => T(P(el, "text")) && T(P(el, "rect")) &&
        (!Has(window) || !T(P(el, "window")) || System.Text.RegularExpressions.Regex.IsMatch(Lower(S(P(el, "window"))), System.Text.RegularExpressions.Regex.Escape(Lower(window!)), System.Text.RegularExpressions.RegexOptions.IgnoreCase)) &&
        (!Has(role) || !T(P(el, "role")) || Comparer.Equals(Lower(S(P(el, "role"))), Lower(role!)));
    private static (int Score, string Reason) LabelScore(string hay, string needle, int prefixLength, int prefixScore)
    {
        if (Comparer.Equals(hay, needle)) return (100, "exact");
        if (System.Text.RegularExpressions.Regex.IsMatch(hay, System.Text.RegularExpressions.Regex.Escape(needle), System.Text.RegularExpressions.RegexOptions.IgnoreCase)) return (60 + Math.Max(0, 40 - Math.Abs(hay.Length - needle.Length)), "substring");
        if (needle.Length >= prefixLength && hay.IndexOf(needle[..prefixLength], StringComparison.CurrentCulture) >= 0) return (prefixScore, "prefix");
        return (0, "");
    }
    private static int ConfidenceBoost(JsonElement c, int high = 4, int medium = 2)
    {
        if (c.ValueKind == JsonValueKind.String) return Lower(S(c)) switch { "high" => high, "medium" => medium, "low" => 1, _ => 0 };
        return c.ValueKind == JsonValueKind.Number ? Round(c.GetDouble() * 5) : 0;
    }
    private static IEnumerable<string> Hays(JsonElement el)
    {
        var hays = new List<string> { Lower(S(P(el, "text"))) };
        foreach (var s in A(P(el, "synonyms"))) if (!string.IsNullOrWhiteSpace(S(s)))
        { string value = Lower(S(s)); if (!hays.Contains(value, StringComparer.Ordinal)) hays.Add(value); }
        if (T(P(el, "tooltip"))) { string value = Lower(S(P(el, "tooltip"))); if (!hays.Contains(value, StringComparer.Ordinal)) hays.Add(value); }
        return hays;
    }
    private static JsonElement FindElement(JsonElement shot, string label, string? window, string? role)
    {
        string needle = Lower(label).Trim();
        var hits = new List<(JsonElement Element, int Score, int Tier)>(); int tier = 0;
        foreach (string pool in new[] { "Grounded", "FusedElements", "Items" })
        {
            tier++;
            foreach (var el in A(P(shot, pool)))
            {
                if (!FilterElement(el, window, role)) continue;
                int score = Hays(el).Select(h => LabelScore(h, needle, 3, 20).Score).DefaultIfEmpty(0).Max();
                score += ConfidenceBoost(P(el, "confidence")); if (T(P(el, "small_icon"))) score += 3;
                if (el.ValueKind == JsonValueKind.Object && el.EnumerateObject().Any(p => Comparer.Equals(p.Name, "enabled")) && !T(P(el, "enabled"))) score -= 5;
                if (score > 0) hits.Add((el, score, tier));
            }
        }
        if (hits.Count == 0) return Null;
        return LegacyInteractionRanking.Sort(hits, (a, b) => a.Tier != b.Tier ? a.Tier.CompareTo(b.Tier) : b.Score.CompareTo(a.Score))[0].Element;
    }
    private LegacyExecutionResult FindLabel()
    {
        string? label = V("--label"), window = V("--window"), match = V("--match"), role = V("--role");
        bool explain = F("--explain"), fast = F("--fast"); int ambiguity = I(V("--ambiguity-window"));
        if (ambiguity <= 0) ambiguity = 10;
        if (!Has(label)) throw CommandOptions.Invalid("macro find-label requires --label");
        if (!Has(match)) match = window;
        Start("find-label");
        if (fast && Has(match))
        {
            var windows = IE(LegacyExecutionEffectKind.Win32Windows, D("match", match ?? ""));
            if (!A(windows).Any(w => T(P(w, "visible")) && !T(P(w, "minimized"))))
            {
                int elapsedFast = Stop("find-label");
                var data = D("label", label, "match", match, "window", window, "role", role, "fast_path", true, "ambiguous", false,
                    "ambiguity_window", ambiguity, "top", null, "candidates", Array.Empty<object>(), "candidate_count", 0);
                var errors = new object[] { D("code", "no_window", "message", $"fast-path: no visible window matches '{match}'", "recommended_action", $"Verify the app is running with 'cucp macro windows --match \"{match}\"', or drop --fast to engage UIA/OCR fallback.") };
                return Result(Envelope("partial", elapsedFast, data, ["win32"], recoverable: errors), 2, 8,
                    $"partial find-label '{label}' fast no_window match='{match}' elapsed_ms={elapsedFast}");
            }
        }
        var shot = Appshot(match);
        if (!T(shot))
        {
            string hint = "cucp macro windows --match '" + match + "'";
            return Result(Envelope("partial", Elapsed("find-label"), D("label", label, "match", match, "observed", 0), ["appshot"],
                recoverable: new object[] { D("code", "appshot_failed", "message", "observe appshot returned no usable artifact", "recommended_action", $"Run 'cucp macro ensure-helper' or retry; verify '{match}' window exists with {hint}") }),
                2, 8, $"partial find-label '{label}' appshot_failed");
        }
        string needle = Normal(label!); var candidates = new List<Dictionary<string, object?>>();
        foreach (var (pool, tier, boost) in new[] { ("Grounded", "grounded", 4), ("FusedElements", "fused", 2), ("Items", "items", 0) })
        {
            foreach (var el in A(P(shot, pool)))
            {
                if (!FilterElement(el, window, role)) continue;
                string hay = Normal(S(P(el, "text"))); var score = LabelScore(hay, needle, 3, 20); if (score.Score == 0) continue;
                int conf = boost + ConfidenceBoost(P(el, "confidence"));
                candidates.Add(D("text", P(el, "text"), "normalized", hay, "role", P(el, "role"), "window", P(el, "window"), "rect", P(el, "rect"),
                    "affordance_id", P(el, "affordance_id"), "score", score.Score + conf, "tier", tier, "match_reason", score.Reason, "confidence_boost", conf,
                    "sources", T(P(el, "sources")) ? A(P(el, "sources")).Cast<object>().ToArray() : new object[] { tier }));
            }
        }
        var ranked = LegacyInteractionRanking.Sort(candidates, (a, b) => ((int)b["score"]!).CompareTo((int)a["score"]!)); int elapsed = Stop("find-label");
        var top = ranked.FirstOrDefault(); bool ambiguous = ranked.Length > 1 && (int)ranked[0]["score"]! - (int)ranked[1]["score"]! < ambiguity;
        var sources = new List<object> { "appshot" }; if (T(P(shot, "Grounded")) && A(P(shot, "Grounded")).Length > 0) sources.Add("uia");
        bool fromCache = T(P(shot, "FromCache")); if (fromCache) sources.Add("cache");
        var cache = D("hit", fromCache, "age_ms", null, "max_age_ms", cacheSeconds * 1000, "key", $"appshot::match={match}", "reason", fromCache ? "cache_fresh" : "live_capture");
        object? foreground = T(P(shot, "FocusedWindow")) ? D("title", P(shot, "FocusedWindow")) : null;
        if (explain)
        {
            string status = top is not null && !ambiguous ? "ok" : "partial";
            string confidence = top is null ? "low" : (int)top["score"]! >= 100 ? "high" : (int)top["score"]! >= 60 ? "medium" : "low";
            object[] recover = top is null ? [D("code", "no_match", "message", $"no candidate matched '{label}'", "recommended_action", $"Try 'cucp macro list-affordances --window \"{match}\" --limit 30' to see available labels.")]
                : ambiguous ? [D("code", "ambiguous_target", "message", $"top two candidates within {ambiguity} score points", "recommended_action", "Narrow with --window or --role, or use the affordance_id from the candidates list.")] : [];
            var data = D("label", label, "window", window, "role", role, "ambiguous", ambiguous, "ambiguity_window", ambiguity, "top", top,
                "candidates", Pipe(ranked.Take(8)), "candidate_count", ranked.Length);
            string line = top is null ? $"partial find-label '{label}' no_match candidates=0 elapsed_ms={elapsed}" :
                $"{status} find-label '{label}' top='{S(J(top["text"]))}' score={top["score"]} reason={top["match_reason"]} ambiguous={ambiguous} candidates={ranked.Length} elapsed_ms={elapsed}";
            return Result(Envelope(status, elapsed, data, sources.ToArray(), confidence, recover, S(P(shot, "ObservationId")), foreground, cache), status == "ok" ? 0 : 2, 8, line);
        }
        if (top is not null && !ambiguous)
        {
            var point = Center(J(top));
            return Result(D("status", "ok", "schema", "cucp.find-label/v2", "label", label, "window", top["window"], "role", top["role"], "text", top["text"],
                "rect", top["rect"], "center", D("X", point.X, "Y", point.Y), "observation_id", P(shot, "ObservationId"), "from_cache", fromCache, "sources", sources,
                "score", top["score"], "candidates", Pipe(ranked.Take(5)), "elapsed_ms", elapsed), 0, 8,
                $"ok find-label '{label}' @({point.X},{point.Y}) win='{S(J(top["window"]))}' score={top["score"]}");
        }
        if (top is not null)
            return Result(D("status", "partial", "schema", "cucp.find-label/v2", "label", label, "reason", "ambiguous_target", "candidates", Pipe(ranked.Take(5)),
                "observation_id", P(shot, "ObservationId"), "from_cache", fromCache, "sources", sources, "ambiguity_window", ambiguity, "elapsed_ms", elapsed,
                "recommended_action", "Narrow with --window or --role, or pick by affordance_id."), 2, 8, $"partial find-label '{label}' ambiguous candidates={Math.Min(ranked.Length, 5)}");
        return Result(D("status", "not_found", "schema", "cucp.find-label/v2", "label", label, "window", window, "observation_id", P(shot, "ObservationId"),
            "from_cache", fromCache, "sources", sources, "candidates_text", string.Join(" | ", A(P(shot, "FusedElements")).Take(20).Select(e => S(P(e, "text")))),
            "elapsed_ms", elapsed, "recommended_action", $"Try 'cucp macro list-affordances --window \"{match}\"' or relax --window/--role."), 1, 8, $"err find-label '{label}' not_found");
    }
}
