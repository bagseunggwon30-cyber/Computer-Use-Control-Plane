using System.Globalization;
using System.Text.Json;

internal sealed partial class LegacyExecutionCoordinator
{
    private LegacyExecutionResult ClickPoint()
    {
        Live("macro click-point requires -AllowLiveControl");
        string? xr = V("--x"), yr = V("--y"); if (!Has(xr) || !Has(yr)) throw CommandOptions.Invalid("macro click-point requires --x and --y");
        int x = I(xr), y = I(yr); string? button = V("--button"), target = V("--target-match");
        if (!Has(target)) target = V("--match"); if (!Has(target)) target = V("--window");
        int hwnd = I(V("--target-hwnd")); string? refine = V("--refine"); if (!Has(refine)) refine = V("--click-refine"); if (F("--uia-safe")) refine = "uia-safe";
        int inset = I(V("--click-inset")); bool noGuard = F("--no-fast-guard"), noMicro = F("--no-micro-refine"), noHistory = F("--no-anchor-history"),
            micro = F("--micro-refine") || F("--precision"), allowUnrefined = F("--allow-unrefined");
        string? rr = V("--precision-radius"), sr = V("--precision-step"), cr = V("--cache-ttl");
        if (!Has(rr)) rr = V("--micro-radius"); if (!Has(sr)) sr = V("--micro-step");
        int radius = Has(rr) ? I(rr) : 6, step = Has(sr) ? I(sr) : 2, ttl = Has(cr) ? I(cr) : cacheSeconds;
        if (!Has(button)) button = "left"; if (inset <= 0) inset = 3; radius = Math.Clamp(radius, 0, 64); step = step <= 0 ? 2 : Math.Min(step, 16); ttl = Math.Max(ttl, 0); if (F("--no-cache")) ttl = 0;
        bool guarded = hwnd > 0 || Has(target), autoMicro = false;
        if (!micro && !noMicro && guarded) { micro = true; autoMicro = true; }
        JsonElement precheck = Null; int originalX = x, originalY = y; object? microEvidence = null, anchorEvidence = null;
        if (guarded && !noGuard)
        {
            Start("click-point-precheck");
            precheck = IE(LegacyExecutionEffectKind.HitTestPoint, D("x", x, "y", y, "target_hwnd", hwnd, "target_match", target ?? ""));
            int elapsed = Stop("click-point-precheck");
            if (precheck.ValueKind == JsonValueKind.Null) throw CommandOptions.Invalid("Cannot bind argument to parameter 'InputObject' because it is null.");
            if (precheck.ValueKind == JsonValueKind.Object) { var extended = Object(precheck); extended["elapsed_ms"] = elapsed; precheck = J(extended); }
            if (!T(P(precheck, "matched")))
            {
                var payload = D("schema", "cucp.click-point/v1", "status", "blocked", "reason", "fast_guard_mismatch", "x", x, "y", y, "button", button,
                    "target_hwnd", hwnd, "target_match", target, "precheck", precheck);
                Trace("click", D("source", "native_click_point", "x", x, "y", y, "button", button, "target_match", target, "target_hwnd", hwnd, "exit", 3, "reason", "fast_guard_mismatch"));
                return Result(payload, 3, 8, $"blocked click-point @({x},{y}) target_mismatch actual='{S(P(precheck, "root_title"))}' process={S(P(precheck, "process_name"))} reason={S(P(precheck, "match_reason"))}", renderBrief: brief);
            }
        }
        if (micro)
        {
            JsonElement scan = Null, pointPayload = Null; bool fromCache = false; int age = 0; string? key = null;
            if (T(precheck) && ttl > 0)
            {
                key = LegacyPrecisionKernel.CacheKey(x, y, radius, step, inset, hwnd, target ?? "", precheck, "");
                var cached = IE(LegacyExecutionEffectKind.PointCacheRead, D("key", key, "max_age_seconds", ttl));
                if (T(cached) && Ok(cached) && T(P(Parsed(cached), "recommended_point"))) { pointPayload = Parsed(cached); fromCache = true; age = I(P(cached, "AgeMs")); }
            }
            if (!T(pointPayload))
            {
                var argv = new List<string> { "-Action", "hit-scan", "-X", Num(x), "-Y", Num(y), "-ClickInset", Num(inset), "-ScanRadius", Num(radius), "-ScanStep", Num(step) };
                if (Has(target)) argv.AddRange(["-TargetMatch", target!]); if (hwnd > 0) argv.AddRange(["-TargetHwnd", Num(hwnd)]);
                scan = INative(argv.ToArray());
                if (Ok(scan) && T(P(Parsed(scan), "recommended_point")))
                {
                    var sj = Parsed(scan);
                    pointPayload = J(D("schema", "cucp.point-plan/v1", "status", "ok", "mode", "coordinate_click", "source", "click_point_micro_refine", "x", x, "y", y,
                        "radius", radius, "step", step, "click_inset", inset, "target_hwnd", hwnd, "target_match", target, "from_cache", false,
                        "cache_ttl_seconds", ttl, "cache_key", key, "confidence", S(P(P(sj, "recommended_point"), "confidence")), "safe_to_act", true, "mouse_moved", true,
                        "reason", "", "precheck", precheck, "best", P(sj, "best"), "recommended_point", P(sj, "recommended_point"), "recommended_command", null,
                        "checks", new object[] {
                            D("source", "win32_fast_guard", "status", P(precheck, "status"), "matched", T(P(precheck, "matched")), "reason", S(P(precheck, "match_reason")), "evidence", precheck),
                            D("source", "hit_scan", "status", "ok", "reason", "", "exit", ExitOf(scan), "elapsed_ms", I(P(scan, "ElapsedMs"))) }, "scan", sj));
                    if (Has(key) && ttl > 0) IE(LegacyExecutionEffectKind.PointCacheWrite, D("key", key, "payload", pointPayload));
                }
            }
            if (T(pointPayload) && Eq(P(pointPayload, "status"), "ok") && T(P(pointPayload, "recommended_point")))
            {
                var point = P(pointPayload, "recommended_point"); int rx = I(P(point, "x")), ry = I(P(point, "y")); var detail = P(pointPayload, "scan");
                microEvidence = D("status", "ok", "original_x", originalX, "original_y", originalY, "refined_x", rx, "refined_y", ry,
                    "confidence", S(P(point, "confidence")), "point_source", S(P(point, "point_source")), "native_clickable", T(P(point, "native_clickable")),
                    "sample_count", T(detail) ? I(P(detail, "sample_count")) : 0, "candidate_count", T(detail) ? I(P(detail, "candidate_count")) : 0,
                    "from_cache", fromCache, "cache_age_ms", age, "cache_key", key, "elapsed_ms", T(scan) ? I(P(scan, "ElapsedMs")) : 0);
                x = rx; y = ry;
            }
            else
            {
                string reason = T(Parsed(scan)) && T(P(Parsed(scan), "reason")) ? S(P(Parsed(scan), "reason")) : "micro_refine_failed";
                if (!allowUnrefined)
                {
                    var payload = D("schema", "cucp.click-point/v1", "status", "blocked", "reason", "micro_refine_failed", "detail", reason,
                        "x", originalX, "y", originalY, "button", button, "target_hwnd", hwnd, "target_match", target, "precheck", precheck, "scan", T(Parsed(scan)) ? Parsed(scan) : null);
                    Trace("click", D("source", "native_click_point", "x", originalX, "y", originalY, "button", button, "target_match", target, "target_hwnd", hwnd, "refine", "micro", "exit", 3, "reason", "micro_refine_failed"));
                    return Result(payload, 3, 10, $"blocked click-point @({originalX},{originalY}) micro_refine_failed reason={reason}", renderBrief: brief);
                }
                microEvidence = D("status", "partial", "reason", reason, "allowed_unrefined", true);
            }
        }
        if (guarded && !noHistory)
        {
            try
            {
                var profile = IE(LegacyExecutionEffectKind.CoordProfile, D("has_point", true, "x", x, "y", y, "target_hwnd", (long)hwnd, "target_match", target ?? ""));
                var targetWindow = P(profile, "target_window"); var relative = P(profile, "point_window_relative");
                if (T(profile) && Eq(P(profile, "status"), "ok") && T(targetWindow) && T(relative))
                {
                    double nx = Number(P(relative, "norm_x")), ny = Number(P(relative, "norm_y")); var norm = D("x", nx, "y", ny);
                    string risk = S(P(profile, "coordinate_risk")); bool safe = T(P(profile, "point_inside_target_window")) && !Comparer.Equals(risk, "high");
                    string source = $"{S(P(targetWindow, "process"))}|{S(P(targetWindow, "class"))}|{target}|{Math.Round(nx, 4).ToString(CultureInfo.CurrentCulture)},{Math.Round(ny, 4).ToString(CultureInfo.CurrentCulture)}";
                    var record = D("ts", Effect(LegacyExecutionEffectKind.Timestamp, "o"), "anchor_id", LegacyPrecisionKernel.Hash(source), "anchor_type", "click_point_live_route",
                        "target_match", target, "target_hwnd_current", Long(P(targetWindow, "hwnd")), "process", S(P(targetWindow, "process")), "class", S(P(targetWindow, "class")),
                        "title", S(P(targetWindow, "title")), "source_point", D("x", originalX, "y", originalY), "screen_point", D("x", x, "y", y),
                        "normalized_window_point", norm, "visible_normalized_point", norm, "safe_to_reuse", safe, "coordinate_risk", risk,
                        "coord_signature", S(P(profile, "coord_signature")), "window_rect", P(targetWindow, "rect"));
                    var reuse = IE(LegacyExecutionEffectKind.AnchorScore, D("record", record));
                    anchorEvidence = D("status", "ok", "auto_record_after_success", true, "record", record, "reuse_history", reuse, "coordinate_profile", profile);
                }
            }
            catch (Exception error) when (error is LegacyExecutionEffectException or NativeFailure or InvalidOperationException)
            { anchorEvidence = D("status", "partial", "reason", "anchor_reuse_score_failed", "detail", error.Message); }
        }
        else if (guarded && noHistory) anchorEvidence = D("status", "skipped", "reason", "disabled_by_no_anchor_history");
        var clickArgs = new List<string> { "-Action", "click", "-X", Num(x), "-Y", Num(y), "-Button", button! };
        if (Has(target)) clickArgs.AddRange(["-TargetMatch", target!]); if (hwnd > 0) clickArgs.AddRange(["-TargetHwnd", Num(hwnd)]);
        if (Has(refine)) clickArgs.AddRange(["-ClickRefine", refine!]); if (inset > 0) clickArgs.AddRange(["-ClickInset", Num(inset)]);
        var clicked = INative(clickArgs.ToArray()); var anchor = J(anchorEvidence);
        if (Ok(clicked) && T(anchor) && Eq(P(anchor, "status"), "ok") && T(P(anchor, "record")))
        {
            bool recorded = T(IE(LegacyExecutionEffectKind.AnchorAppend, D("record", P(anchor, "record"))));
            var reuse = P(anchor, "reuse_history");
            if (reuse.ValueKind == JsonValueKind.Object)
            {
                var extended = Object(reuse); extended["recorded"] = recorded;
                ((Dictionary<string, object?>)anchorEvidence!)["reuse_history"] = extended; anchor = J(anchorEvidence);
            }
        }
        Trace("click", D("source", "native_click_point", "x", x, "y", y, "button", button, "target_match", target, "target_hwnd", hwnd,
            "refine", refine, "micro_refine", microEvidence, "auto_micro_refine", autoMicro, "anchor_reuse", T(anchor) ? P(anchor, "reuse_history") : null, "exit", ExitValue(clicked)));
        if (brief)
        {
            string guardSuffix = T(precheck) ? $" fast_guard={S(P(precheck, "match_reason"))}" : ""; var json = Parsed(clicked); var me = J(microEvidence);
            string refineSuffix = T(Member(json, "refined_by")) ? $" refined=({S(Member(json, "x"))},{S(Member(json, "y"))}) source={S(Member(json, "refined_point_source"))}" : "";
            string microSuffix = T(me) && Eq(P(me, "status"), "ok") ? $" micro_refine=({originalX},{originalY})->({S(P(me, "refined_x"))},{S(P(me, "refined_y"))}) confidence={S(P(me, "confidence"))}" : "";
            return Silent(ExitOf(clicked), Ok(clicked) ? $"ok click-point @({x},{y}) button={button} elapsed_ms={S(P(clicked, "ElapsedMs"))}{guardSuffix}{microSuffix}{refineSuffix}" : $"err click-point exit={S(ExitValue(clicked))}");
        }
        if (T(Parsed(clicked)))
        {
            object? Extend(JsonElement value)
            {
                // Add-Member operates on each object in the original pipeline;
                // retain scalar base values rather than replacing them with {}.
                if (value.ValueKind != JsonValueKind.Object) return value;
                var payload = Object(value);
                void Force(string name, object? data) { payload.Remove(name); payload.Add(name, data); }
                Force("schema", "cucp.click-point/v1"); Force("wrapper_action", "click-point");
                Force("original_point", D("x", originalX, "y", originalY)); Force("precheck", precheck); Force("micro_refine", microEvidence);
                Force("auto_micro_refine", autoMicro); Force("anchor_reuse", anchorEvidence);
                return payload;
            }
            var value = Parsed(clicked);
            object? payload = value.ValueKind == JsonValueKind.Array ? Pipe(A(value).Select(Extend)) : Extend(value);
            return Result(payload, ExitOf(clicked), 12, renderBrief: false);
        }
        return RawResult(clicked, null);
    }
}
