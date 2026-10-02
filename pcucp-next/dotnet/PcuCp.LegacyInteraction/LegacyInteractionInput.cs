using System.Text.Json;

internal sealed partial class LegacyExecutionCoordinator
{
    private LegacyExecutionResult SafeType()
    {
        Live("macro safe-type requires -AllowLiveControl");
        string? text = V("--text"), tm = V("--target-match"), xr = V("--click-x"), yr = V("--click-y");
        long hwnd = LegacyPrecisionKernel.L(V("--target-hwnd"));
        bool hasX = Has(xr), hasY = Has(yr), enter = F("--enter"), ctrlEnter = F("--ctrl-enter");
        int maximum = I(V("--max-attempts"));
        if (!Has(text)) throw CommandOptions.Invalid("macro safe-type requires --text");
        if (!Has(tm) && hwnd <= 0) throw CommandOptions.Invalid("macro safe-type requires --target-match or --target-hwnd");
        if (hasX != hasY) throw CommandOptions.Invalid("macro safe-type requires both --click-x and --click-y");
        if (enter && ctrlEnter) throw CommandOptions.Invalid("choose --enter or --ctrl-enter, not both");
        maximum = maximum <= 0 ? 1 : Math.Min(maximum, 10);
        int x = hasX ? I(xr) : 0, y = hasX ? I(yr) : 0;
        var windows = INative("-Action", "windows");
        var candidates = ExitOf(windows) == 0 && Ok(windows) ? A(P(Parsed(windows), "windows")).Where(w =>
            (hwnd <= 0 || Long(P(w, "hwnd")) == hwnd) && (!Has(tm) || T(P(w, "title")) && S(P(w, "title")).Contains(tm!, StringComparison.OrdinalIgnoreCase))).ToArray() : [];
        string reason = ""; int attempts = 0; bool success = false; bool? dispatched = false;
        if (candidates.Length != 1) reason = candidates.Length > 1 ? "ambiguous_target" : "target_unavailable";
        else
        {
            hwnd = Long(P(candidates[0], "hwnd"));
            while (attempts < maximum && !success)
            {
                attempts++;
                var focus = INative("-Action", "focus", "-WindowHwnd", hwnd.ToString(System.Globalization.CultureInfo.InvariantCulture));
                if (!(ExitOf(focus) == 0 && T(Parsed(focus)) && T(P(Parsed(focus), "verified")) && Long(P(Parsed(focus), "target_hwnd")) == hwnd))
                { reason = "focus_failed"; continue; }
                if (hasX)
                {
                    var click = INative("-Action", "click", "-X", Num(x), "-Y", Num(y), "-TargetHwnd", hwnd.ToString(System.Globalization.CultureInfo.InvariantCulture));
                    if (!(ExitOf(click) == 0 && Ok(click))) { reason = "click_blocked_or_failed"; break; }
                }
                dispatched = null;
                var type = INative("-Action", "type", "-Text", text!, "-TargetHwnd", hwnd.ToString(System.Globalization.CultureInfo.InvariantCulture));
                if (!(ExitOf(type) == 0 && Ok(type))) { reason = "main_type_blocked_or_failed"; break; }
                dispatched = true;
                if (enter || ctrlEnter)
                {
                    var send = INative("-Action", "shortcut", "-Keys", ctrlEnter ? "ctrl+enter" : "enter", "-TargetHwnd", hwnd.ToString(System.Globalization.CultureInfo.InvariantCulture));
                    if (!(ExitOf(send) == 0 && Ok(send))) { reason = "send_blocked_or_failed"; break; }
                }
                success = true;
            }
        }
        string status = success ? "ok" : "partial";
        return Result(D("schema", "cucp.safe-type/v1", "status", status, "reason", reason, "target_match", tm,
            "target_hwnd", hwnd, "attempts", attempts, "probe", null, "probe_mode", "disabled", "text_dispatched", dispatched,
            "application_result_verified", false, "send", ctrlEnter ? "ctrl+enter" : enter ? "enter" : "none"), success ? 0 : 2, 4,
            $"{status} safe-type target='{tm}' attempts={attempts} reason={reason}", renderBrief: brief);
    }
    private LegacyExecutionResult OcrClick()
    {
        Live("macro ocr-click requires -AllowLiveControl");
        string? text = V("--text"), match = V("--match"), region = V("--region"), button = V("--button"), language = V("--language"), target = V("--target-match");
        int minimum = I(V("--min-score"));
        if (!Has(text)) throw CommandOptions.Invalid("macro ocr-click requires --text");
        if (!Has(match)) match = "contains"; if (!Has(button)) button = "left"; if (minimum <= 0) minimum = 70;
        var args = new List<string> { "-Action", "ocr-find-text", "-OcrText", text!, "-OcrMatch", match!, "-OcrMaxCandidates", "8" };
        if (Has(language)) args.AddRange(["-OcrLanguage", language!]); if (Has(target)) args.AddRange(["-Match", target!]);
        if (Has(region))
        {
            var parts = region!.Split(',');
            if (parts.Length == 4) args.AddRange(["-ScreenshotX", parts[0].Trim(), "-ScreenshotY", parts[1].Trim(), "-ScreenshotW", parts[2].Trim(), "-ScreenshotH", parts[3].Trim()]);
        }
        var found = INative(args.ToArray());
        if (!Ok(found)) return Silent(2, $"partial ocr-click '{text}' reason=no_text_match exit={ExitOf(found)}");
        var top = P(Parsed(found), "top");
        if (I(P(top, "score")) < minimum) return Silent(2, $"partial ocr-click '{text}' low_confidence score={S(P(top, "score"))} min={minimum} matched='{S(P(top, "text"))}'");
        int x = I(P(top, "cx")), y = I(P(top, "cy"));
        args = ["-Action", "click", "-X", Num(x), "-Y", Num(y), "-Button", button!, "-ClickRefine", "uia-safe"];
        if (Has(target)) args.AddRange(["-TargetMatch", target!]);
        var click = INative(args.ToArray());
        Trace("click", D("source", "ocr_click", "x", x, "y", y, "button", button, "text", text, "matched_text", P(top, "text"), "score", P(top, "score"), "exit", ExitOf(click)));
        return RawResult(click, Ok(click) ? $"ok ocr-click '{text}' matched='{S(P(top, "text"))}' score={S(P(top, "score"))} @({x},{y}) button={button} elapsed_ms={S(P(click, "ElapsedMs"))}"
            : $"err ocr-click '{text}' click_failed exit={ExitOf(click)}");
    }
    private LegacyExecutionResult PrecisionValidate()
    {
        string? xr = V("--x"), yr = V("--y");
        if (!Has(xr) || !Has(yr)) throw CommandOptions.Invalid("macro precision-validate requires --x and --y");
        string? target = V("--target-match"), sr = V("--samples"); int x = I(xr), y = I(yr), samples = 5;
        if (Has(sr)) { try { samples = I(sr); } catch (NativeFailure) { samples = 5; } }
        samples = Math.Clamp(samples, 1, 20);
        var points = new List<object>(); int total = 0, errors = 0;
        for (int i = 0; i < samples; i++)
        {
            Start("precision-validate");
            try
            {
                var argv = new List<string> { "-Action", "hit-scan", "-X", Num(x), "-Y", Num(y), "-ScanRadius", "6", "-ScanStep", "2" };
                if (Has(target)) argv.AddRange(["-TargetMatch", target!]);
                var scan = INative(argv.ToArray()); int elapsed = Stop("precision-validate"); total += elapsed;
                int? bx = null, by = null; int score = 0; var json = Parsed(scan); var point = P(json, "recommended_point");
                if (ExitOf(scan) == 0 && Ok(scan) && T(point))
                {
                    if (P(point, "x").ValueKind != JsonValueKind.Null) bx = I(P(point, "x"));
                    if (P(point, "y").ValueKind != JsonValueKind.Null) by = I(P(point, "y"));
                    if (T(P(json, "best")) && P(P(json, "best"), "final_score").ValueKind != JsonValueKind.Null) score = I(P(P(json, "best"), "final_score"));
                }
                if (bx.HasValue && by.HasValue) points.Add(D("iteration", i + 1, "x", bx.Value, "y", by.Value, "elapsed_ms", elapsed, "score", score));
                else errors++;
            }
            catch (Exception error) when (error is LegacyExecutionEffectException or NativeFailure or InvalidOperationException)
            { Stop("precision-validate"); errors++; }
            Sleep(30);
        }
        double maximum = 0, average = 0;
        if (points.Count >= 2)
        {
            double mx = points.Average(p => Number(P(J(p), "x"))), my = points.Average(p => Number(P(J(p), "y")));
            var distances = points.Select(p => Math.Sqrt(Math.Pow(Number(P(J(p), "x")) - mx, 2) + Math.Pow(Number(P(J(p), "y")) - my, 2))).ToArray();
            maximum = distances.Max(); average = distances.Average();
        }
        bool evidence = points.Count >= 2 && errors == 0, stable = evidence && maximum <= 2;
        string recommendation = !evidence ? "collect_successful_samples" : stable ? "safe_to_use_anchor" : maximum <= 5 ? "use_with_micro_refine" : "use_uia_pattern_or_relabel";
        string status = evidence ? "ok" : "partial"; object? driftMax = points.Count >= 2 ? Math.Round(maximum, 2) : null;
        return Result(D("schema", "cucp.precision-validate/v1", "status", status, "input", D("x", x, "y", y, "target_match", target, "samples", samples),
            "sample_count", points.Count, "error_count", errors, "avg_elapsed_ms", Round((double)total / samples), "points", points.ToArray(),
            "drift_max", driftMax, "drift_avg", points.Count >= 2 ? Math.Round(average, 2) : null, "stable", stable, "recommendation", recommendation), evidence ? 0 : 2, 10,
            $"{status} precision-validate samples={points.Count} drift_max={S(J(driftMax))}px stable={stable} rec={recommendation}", renderBrief: brief);
    }
}
