using System.Text.Json;

internal static class StrategyContractChecks
{
    internal static void Run(Action<bool, string> check)
    {
        foreach (var (source, expected) in new[] { ("CDP-click+fallback", "cdp_dom"), ("uia_coord", "uia_click"), ("uia_set_value", "uia_value_or_pattern"),
                     ("fusion_coord", "ocr"), (" custom ", " custom "), ("UIA_PATTERN\n", "uia_pattern") })
            check(LegacyStrategyKernel.NormalizeValue(source) == expected, "Route normalization changed");
        var result = JsonSerializer.SerializeToElement(LegacyStrategyKernel.Score(JsonSerializer.SerializeToElement(new
        {
            app_type = "browser", route_order = new[] { "cdp_dom", "uia_pattern", "ocr" }, browser_like = true, no_probe = true,
            labels = new[] { "Save", "save", "Save", " " }, persisted_strategy = new { strategy = "cdp_dom" }
        })));
        check(result.GetProperty("recommended_strategy").GetString() == "cdp_dom", "Browser strategy changed");
        check(result.GetProperty("total_score").GetInt32() == 57, "Route score accumulation changed");
        check(result.GetProperty("confidence").GetString() == "medium", "Confidence thresholds changed");
        check(result.GetProperty("evidence").GetProperty("label_count").GetInt32() == 2, "Label case uniqueness changed");
        var capped = JsonSerializer.SerializeToElement(LegacyStrategyKernel.Score(JsonSerializer.SerializeToElement(new
        {
            route_order = Enumerable.Repeat("uia_pattern", 20).ToArray(), uia_probe = new { available = true, label_hits = new[] { new { found = true } } }
        })));
        check(capped.GetProperty("total_score").GetInt32() == 100, "Final score clamp changed");
        foreach (var routes in new[] { new[] { "é", "e\u0301" }, new[] { "e\u0301", "é" } })
        {
            var merged = JsonSerializer.SerializeToElement(LegacyStrategyKernel.Score(JsonSerializer.SerializeToElement(new { route_order = routes })));
            var first = merged.GetProperty("route_scores")[0];
            check(first.GetProperty("route").GetString() == routes[0], "Linguistic route merge must preserve first key spelling");
            check(first.GetProperty("score").GetInt32() == 39, "Canonical-equivalent route weights must accumulate");
            check(first.GetProperty("reasons").GetArrayLength() == 2, "Merged route reasons must retain insertion order");
        }
        var failed = false;
        try { LegacyStrategyKernel.Score(JsonSerializer.SerializeToElement(new { browser_like = "false" })); } catch (NativeFailure) { failed = true; }
        check(failed, "Malformed boolean accepted");
    }
}
