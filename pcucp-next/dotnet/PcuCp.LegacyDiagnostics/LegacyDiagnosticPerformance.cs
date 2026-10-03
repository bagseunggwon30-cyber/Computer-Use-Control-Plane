using System.Text.Json;

internal sealed partial class LegacyDiagnosticCoordinator
{
    internal static object DiagnosticSubtractInt32(int left, int right)
    {
        // PowerShell IntOps.Sub uses a wide intermediate, then returns Int32
        // inside range or Double on overflow. Never wrap the verdict's sign.
        // Reference: retained-diagnostics-qualification.md, subtraction section.
        long difference = (long)left - right;
        if (difference >= int.MinValue && difference <= int.MaxValue) return (int)difference;
        return (double)difference;
    }

    private static int DiagnosticSloFailThreshold(int warnMilliseconds)
    {
        // PS promotes the multiply, then binds the nested _SloEval [int] FailMs
        // parameter. Preserve the conversion/binding error after all samples.
        try { return I(J((double)warnMilliseconds * 4)); }
        catch (NativeFailure error)
        { throw CommandOptions.Invalid("Cannot process argument transformation on parameter 'FailMs'. " + error.Message); }
    }
    private sealed record PerfTarget(string Id, string Kind, string[] Argv, int[] Accepted, string Macro = "", bool FindLabel = false);
    private LegacyDiagnosticResult Perf()
    {
        int iters = I(V("--iters")); if (iters <= 0) iters = 3;
        int warnFast = I(V("--warn-fast-ms")); if (warnFast <= 0) warnFast = 800;
        bool quick = F("--quick"), cold = F("--include-live-ish");
        var results = new List<Dictionary<string, object?>>();
        void Run(PerfTarget target)
        {
            var samples = new List<int>(); var exits = new List<JsonElement>();
            for (int index = 0; index < iters; index++)
            {
                Start("perf-sample"); JsonElement exit = J(1);
                try
                {
                    if (target.Kind == "macro")
                    {
                        try { exit = Effect(LegacyDiagnosticEffectKind.Macro, target.Macro, target.Argv); }
                        catch (LegacyDiagnosticEffectException) when (target.FindLabel) { exit = J(2); }
                    }
                    else exit = P(Cli(target.Argv), "exit");
                }
                catch (LegacyDiagnosticEffectException) { exit = J(1); }
                samples.Add(Stop("perf-sample")); exits.Add(exit);
            }
            // PS += flattens a scriptblock's pipeline result into the exit list.
            var flatExits = exits.SelectMany(v => v.ValueKind == JsonValueKind.Null ? new[] { v } : A(v)).ToArray();
            results.Add(D("id", target.Id, "kind", target.Kind, "iters", iters, "min_ms", samples.Min(),
                "avg_ms", Convert.ToInt32(samples.Average()), "max_ms", samples.Max(), "samples_ms", samples,
                "exit_codes", flatExits, "accepted_exits", target.Accepted,
                "exit_ok", flatExits.All(e => target.Accepted.Any(a => e.ValueKind != JsonValueKind.Array && (e.ValueKind == JsonValueKind.Number ? N(e) == a : S(e) == a.ToString())))));
        }
        Run(new("version", "cli", ["version"], [0]));
        Run(new("release", "cli", ["release"], [0]));
        Run(new("macro_metrics", "macro", [], [0], "metrics"));
        Run(new("macro_health_quick", "macro", [], [0, 1], "health-quick"));
        Run(new("windows_fast", "macro", [], [0], "windows"));
        Run(new("windows_no_match", "macro", ["--match", "unlikely-perf-target-window"], [0, 2], "windows"));
        Run(new("find_label_no_match_fast", "macro", ["--label", "__cucp_unlikely_label__", "--match", "unlikely-perf-target-window", "--fast"], [0, 1, 2], "find-label", true));
        if (!quick)
        {
            Run(new("health", "cli", ["health"], [0]));
            Run(new("windows_rich", "macro", ["--rich"], [0], "windows"));
            Run(new("context", "cli", ["observe", "context"], [0]));
            Run(new("screenshot", "cli", ["observe", "screenshot"], [0]));
            Run(new("appshot_no_match", "cli", ["observe", "appshot", "--match", "unlikely-perf-target-window"], [0, 1, 2]));
            Run(new("find_label_no_match", "macro", ["--label", "__cucp_unlikely_label__", "--match", "unlikely-perf-target-window"], [0, 1, 2], "find-label", true));
        }
        if (cold)
        {
            try { Effect(LegacyDiagnosticEffectKind.ClearAppshotCache, "appshot-*.json", data: paths.CacheDirectory); }
            catch (LegacyDiagnosticEffectException) { }
            // Despite the old comment, both cold/warm targets use every iteration.
            Run(new("appshot_cold", "cold", ["observe", "appshot"], [0, 1, 2]));
            Run(new("appshot_warm", "cli", ["observe", "appshot"], [0, 1, 2]));
        }
        var warnings = new List<string>(); var slo = new List<object>();
        foreach (var budget in new[] { ("windows_fast", warnFast, DiagnosticSloFailThreshold(warnFast)), ("windows_no_match", 500, 2000), ("macro_health_quick", 1000, 3000), ("find_label_no_match_fast", 800, 3000) })
        {
            var target = results.Single(r => Equals(r["id"], budget.Item1)); int avg = (int)target["avg_ms"]!;
            if (avg > budget.Item2) warnings.Add($"{budget.Item1} avg={avg}ms exceeded warn threshold {budget.Item2}ms");
            slo.Add(D("id", budget.Item1, "avg_ms", avg, "status", avg > budget.Item3 ? "fail" : avg > budget.Item2 ? "warn" : "pass", "warn_ms", budget.Item2, "fail_ms", budget.Item3));
        }
        var hints = new List<string>();
        var appshot = results.SingleOrDefault(r => Equals(r["id"], "appshot_no_match"));
        if (appshot is not null && (int)appshot["avg_ms"]! > 5000) hints.Add($"appshot_no_match avg={appshot["avg_ms"]}ms; helper response slow. Consider 'cucp macro ensure-helper'.");
        var find = results.SingleOrDefault(r => Equals(r["id"], "find_label_no_match"));
        if (find is not null && (int)find["avg_ms"]! > 8000) hints.Add($"find_label_no_match avg={find["avg_ms"]}ms; vision fallback may be active. Try '--no-vision' for fast-path measurement.");
        var payload = D("status", "ok", "schema", "cucp.macro.perf/v2", "collected_at", Now(), "iters", iters, "quick", quick,
            "include_cold_appshot", cold, "thresholds", D("windows_fast_warn_ms", warnFast, "windows_no_match_warn_ms", 500,
                "health_quick_warn_ms", 1000, "find_label_no_match_fast_warn_ms", 800), "slo", slo, "warnings", warnings, "regression_hints", hints, "targets", results);
        var lines = new List<string> { $"ok perf iters={iters} targets={results.Count} warnings={warnings.Count} quick={quick}" };
        lines.AddRange(results.Select(r => string.Format("  {0,-22} {1,-5} min={2,5}ms avg={3,5}ms max={4,5}ms", r["id"], r["kind"], r["min_ms"], r["avg_ms"], r["max_ms"])));
        lines.AddRange(warnings.Select(w => "  [WARN] " + w));
        return Result(payload, 0, 6, string.Join(Environment.NewLine, lines));
    }
    private LegacyDiagnosticResult Benchmark()
    {
        int iters = 3;
        if (Has(V("--iters"))) { try { iters = I(V("--iters")); } catch (NativeFailure) { iters = 3; } }
        iters = Math.Clamp(iters, 1, 10); string? baselinePath = V("--baseline");
        var results = new List<Dictionary<string, object?>>();
        foreach (var target in new[] { ("windows", 600), ("health", 400), ("focused", 500), ("modal-detect", 800) })
        {
            var samples = new List<Dictionary<string, object?>>();
            for (int index = 0; index < iters; index++)
            {
                Start("benchmark-sample"); bool ok = false; string? error = null; int elapsed;
                try
                {
                    var r = Native("-Action", target.Item1); elapsed = Stop("benchmark-sample");
                    ok = I(P(r, "exit")) == 0 && T(Parsed(r)) && (!T(P(Parsed(r), "status")) || Eq(P(Parsed(r), "status"), "ok"));
                }
                catch (LegacyDiagnosticEffectException e) { elapsed = Stop("benchmark-sample"); error = e.Message; }
                var row = D("iter", index + 1, "ms", elapsed, "ok", ok); if (Has(error)) row["error"] = error; samples.Add(row);
            }
            int[] values = samples.Where(s => (bool)s["ok"]!).Select(s => (int)s["ms"]!).Order().ToArray();
            int? p50 = values.Length == 0 ? null : values[(int)Math.Ceiling(values.Length * .5) - 1];
            int? p95 = values.Length == 0 ? null : values[(int)Math.Ceiling(values.Length * .95) - 1];
            results.Add(D("name", target.Item1, "iters", iters, "ok_count", values.Length, "failure_count", iters - values.Length,
                "p50_ms", p50, "p95_ms", p95, "avg_ms", values.Length == 0 ? null : Convert.ToInt32(values.Average()), "slo_ms", target.Item2,
                "slo_ok", values.Length == iters && values.Length > 0 && p95 <= target.Item2, "samples", samples));
        }
        int passed = results.Count(r => (bool)r["slo_ok"]!); double rate = Math.Round(passed / 4d * 100, 1);
        object? comparison = null;
        if (Has(baselinePath) && Exists(baselinePath!))
        {
            try
            {
                string raw = S(Effect(LegacyDiagnosticEffectKind.ReadText, data: baselinePath));
                var baseline = LegacyDiagnosticJson.ParseValue(raw); var rows = new List<object>(); int improved = 0, regressed = 0;
                foreach (var current in results)
                {
                    var before = baseline.Property("results").Elements.FirstOrDefault(b => Eq(b.Property("name").Json, (string)current["name"]!));
                    if (before is null || current["p50_ms"] is null || before.Property("p50_ms").IsNull) continue;
                    int b50 = before.Property("p50_ms").Int32();
                    object delta = DiagnosticSubtractInt32((int)current["p50_ms"]!, b50);
                    _ = DiagnosticSubtractInt32((int)current["p95_ms"]!, before.Property("p95_ms").Int32());
                    double numericDelta = Convert.ToDouble(delta, System.Globalization.CultureInfo.InvariantCulture);
                    double pct = b50 > 0 ? Math.Round(numericDelta / N(before.Property("p50_ms").Json) * 100, 1) : 0;
                    string verdict = "neutral"; if (numericDelta <= -10) { verdict = "improved"; improved++; } else if (numericDelta >= 30) { verdict = "regressed"; regressed++; }
                    rows.Add(D("name", current["name"], "baseline_p50_ms", b50, "current_p50_ms", current["p50_ms"], "delta_ms", delta, "delta_pct", pct, "verdict", verdict));
                }
                comparison = D("baseline_path", baselinePath, "compared_targets", rows.Count, "improved_count", improved, "regressed_count", regressed, "rows", rows);
            }
            catch (Exception e) when (e is LegacyDiagnosticEffectException or JsonException or NativeFailure or FormatException or OverflowException)
            { comparison = D("baseline_path", baselinePath, "error", "baseline_load_failed", "detail", e.Message); }
        }
        var payload = D("schema", paths.BenchmarkSchema, "status", "ok", "iters", iters, "target_count", 4, "results", results,
            "slo_pass_count", passed, "slo_pass_rate_pct", rate, "recommendation", rate >= 90 ? "all_within_slo" : rate >= 60 ? "review_slow_targets" : "investigate_helper_health", "baseline_compare", comparison);
        string line = $"ok benchmark targets=4 iters={iters} slo_pass={passed}/4 ({rate}%)";
        if (comparison is not null && !T(P(J(comparison), "error"))) line += $" improved={S(P(J(comparison), "improved_count"))} regressed={S(P(J(comparison), "regressed_count"))}";
        return Result(payload, 0, 10, line, renderBrief: brief);
    }
}
