using System.Globalization;
using System.Text.Json;

internal static partial class LegacyPrecisionKernel
{
    private static object Anchor(Context ctx, string[] rest)
    {
        int x = I(V(rest, "--x")), y = I(V(rest, "--y")); string? tm = Match(rest); long th = L(V(rest, "--target-hwnd"));
        int radius = T(V(rest, "--radius")) ? I(V(rest, "--radius")) : 6, step = T(V(rest, "--step")) ? I(V(rest, "--step")) : 2;
        double tolerance = T(V(rest, "--history-tolerance")) ? N(V(rest, "--history-tolerance")) : .012;
        if (x <= 0 || y <= 0) throw new InvalidOperationException("macro coord-anchor requires --x and --y");
        radius = Math.Max(0, radius); if (step <= 0) step = 2; if (tolerance <= 0) tolerance = .012; if (tolerance > .1) tolerance = .1;
        bool recordHistory = B(rest, "--record-history") || B(rest, "--learn-history"), noHistory = B(rest, "--no-history");
        bool brief = T(P(ctx.Args, "brief")) && !B(rest, "--json-only");
        var map = ctx.Query("coord-map", "from", "screen", "x", x, "y", y, "norm_x", 0, "norm_y", 0, "has_norm", false, "target_hwnd", th, "target_match", tm ?? "");
        if (!T(map) || !Eq(P(map, "status"), "ok"))
        {
            string reason = T(P(map, "reason")) ? S(P(map, "reason")) : "coord_map_failed";
            return ctx.Complete(D("schema", "cucp.coord-anchor/v1", "status", "partial", "reason", reason, "source_point", D("x", x, "y", y), "coord_map", map, "elapsed_ms", ctx.Elapsed,
                "next_step", "Run coord-map with a target window or first re-ground the target via app-profile/windows."), 2, brief ? $"partial coord-anchor reason={reason} elapsed_ms={ctx.Elapsed}" : null, 12);
        }
        var selected = P(map, "selected_window"); var norm = P(map, "normalized_window_point"); var clip = P(map, "visible_window_clip"); var visible = P(map, "visible_window_point");
        string target = T(tm) ? tm! : T(P(selected, "title")) ? S(P(selected, "title")) : T(P(selected, "process")) ? S(P(selected, "process")) : "";
        object? visibleNorm = T(clip) && T(visible) && I(P(clip, "width")) > 0 && I(P(clip, "height")) > 0
            ? D("x", Math.Round(N(P(visible, "x")) / N(P(clip, "width")), 6), "y", Math.Round(N(P(visible, "y")) / N(P(clip, "height")), 6)) : null;
        var restore = new List<string> { "macro", "coord-map", "--from", "normalized", "--norm-x", S(P(norm, "x")), "--norm-y", S(P(norm, "y")) }; Opt(restore, "--target-match", target);
        string hwnd = S(L(P(selected, "hwnd"))), sx = S(P(P(map, "screen_point"), "x")), sy = S(P(P(map, "screen_point"), "y"));
        string[] byHwnd = ["macro", "coord-map", "--from", "normalized", "--norm-x", S(P(norm, "x")), "--norm-y", S(P(norm, "y")), "--target-hwnd", hwnd];
        var pointPlan = new List<string> { "macro", "point-plan", "--x", sx, "--y", sy, "--radius", S(radius), "--step", S(step) }; Opt(pointPlan, "--target-match", target);
        string[] pointHwnd = ["macro", "point-plan", "--x", sx, "--y", sy, "--target-hwnd", hwnd, "--radius", S(radius), "--step", S(step)];
        var profile = P(map, "coordinate_profile"); string risk = T(profile) ? S(P(profile, "coordinate_risk")) : "unknown";
        bool safe = T(P(map, "inside_window")) && T(P(map, "inside_visible_clip")) && !Eq(risk, "high");
        string id = Hash($"{S(P(selected, "process"))}|{S(P(selected, "class"))}|{target}|{S(P(norm, "x"))},{S(P(norm, "y"))}");
        var record = D("ts", S(P(ctx.Args, "now")), "anchor_id", id, "anchor_type", "window_normalized_point", "target_match", target, "target_hwnd_current", L(P(selected, "hwnd")),
            "process", S(P(selected, "process")), "class", S(P(selected, "class")), "title", S(P(selected, "title")), "source_point", D("x", x, "y", y), "screen_point", P(map, "screen_point"),
            "normalized_window_point", norm, "visible_normalized_point", visibleNorm, "safe_to_reuse", safe, "coordinate_risk", risk, "coord_signature", S(P(profile, "coord_signature")), "window_rect", P(selected, "rect"));
        object? reuse;
        if (noHistory) reuse = D("schema", "cucp.anchor-reuse-score/v1", "enabled", false, "status", "skipped", "reason", "disabled_by_no_history", "score", 0, "confidence", "none", "recorded", false);
        else
        {
            var lines = ctx.Query("history-lines", "path", ctx.HistoryFile);
            reuse = Score(record, ReadHistory(T(lines) ? A(lines).Select(S) : [], 500), tolerance, ctx.HistoryFile);
        }
        if (recordHistory && !noHistory)
        {
            // Add-Member -Force replaces the legacy note property at the end.
            var reordered = ((Dictionary<string, object?>)reuse!).Where(p => p.Key != "recorded").ToDictionary(p => p.Key, p => p.Value);
            reordered.Add("recorded", false); reuse = reordered;
            ctx.Effects.Add(D("kind", "history-append", "args", D("path", ctx.HistoryFile, "record", record, "max", I(P(ctx.Args, "history_max"))), "bind", "reuse_history.recorded"));
        }
        return ctx.Complete(D("schema", "cucp.coord-anchor/v1", "status", "ok", "anchor_id", id, "anchor_type", "window_normalized_point", "source_point", D("x", x, "y", y),
            "safe_to_reuse", safe, "coordinate_risk", risk, "selected_window", selected,
            "anchor", D("target_match", target, "target_hwnd_current", L(P(selected, "hwnd")), "process", S(P(selected, "process")), "class", S(P(selected, "class")), "normalized_window_point", norm, "visible_normalized_point", visibleNorm, "coord_signature", S(P(profile, "coord_signature"))),
            "restore_coord_map_command", restore.ToArray(), "restore_coord_map_command_line", Step(restore), "immediate_restore_by_hwnd_command", byHwnd,
            "immediate_point_plan_command", pointPlan.ToArray(), "immediate_point_plan_command_line", Step(pointPlan), "immediate_point_plan_by_hwnd_command", pointHwnd,
            "reuse_history", reuse, "anchor_history_record", recordHistory && !noHistory ? record : null, "coord_map", map, "warnings", A(P(map, "warnings")), "elapsed_ms", ctx.Elapsed,
            "next_step", "Persist anchor.normalized_window_point with target_match; later run restore_coord_map_command, then target-validate or point-plan on its screen_point before live control. Use --record-history after verified reuse to improve reuse_history.score."), 0,
            brief ? $"ok coord-anchor id={id} risk={risk} safe_to_reuse={safe} reuse_score={S(P(reuse, "score"))} reuse_confidence={S(P(reuse, "confidence"))} norm=({S(P(norm, "x"))},{S(P(norm, "y"))}) elapsed_ms={ctx.Elapsed}" : null, 14);
    }
    private static object PointPlan(Context ctx, string[] rest)
    {
        var o = Parse(ctx, rest, "point-plan"); var checks = new List<object>(); object? precheck = null, profile = null;
        try
        {
            precheck = ctx.Query("hit-test", "x", o.X, "y", o.Y, "target_hwnd", o.Hwnd, "target_match", o.Match ?? "");
            checks.Add(D("source", "win32_fast_guard", "status", P(precheck, "status"), "matched", T(P(precheck, "matched")), "reason", S(P(precheck, "match_reason")), "evidence", precheck));
        }
        catch (NeedReply) { throw; }
        catch (LegacyExecutionProtocolException) { throw; }
        catch (ArgumentException) { throw; }
        catch (Exception ex) { checks.Add(D("source", "win32_fast_guard", "status", "error", "matched", false, "reason", ex.Message)); }
        try
        {
            profile = ctx.Query("coord-profile", "has_point", true, "x", o.X, "y", o.Y, "target_hwnd", o.Hwnd, "target_match", o.Match ?? "");
            checks.Add(D("source", "coord_profile", "status", P(profile, "status"), "risk", P(profile, "coordinate_risk"), "warnings", A(P(profile, "warnings")), "elapsed_ms", I(P(profile, "elapsed_ms"))));
        }
        catch (NeedReply) { throw; }
        catch (LegacyExecutionProtocolException) { throw; }
        catch (ArgumentException) { throw; }
        catch (Exception ex) { checks.Add(D("source", "coord_profile", "status", "error", "reason", ex.Message)); }
        bool target = o.Hwnd > 0 || T(o.Match), guard = T(precheck) && T(P(precheck, "matched")); string? key = null;
        if (T(precheck) && (!target || guard))
        {
            key = CacheKey(o.X, o.Y, o.Radius, o.Step, o.Inset, o.Hwnd, o.Match ?? "", precheck, S(P(profile, "coord_signature")));
            object? hit = null;
            if (o.Ttl > 0) hit = ctx.Query("cache-read", "directory", ctx.CacheDir, "key", key, "max_age_seconds", o.Ttl);
            if (T(hit) && T(P(hit, "Json")))
            {
                var cached = P(hit, "Json");
                if (cached is not JsonElement { ValueKind: JsonValueKind.Object } cj) throw new InvalidOperationException("Cached point-plan payload must be an object.");
                var payload = cj.EnumerateObject().ToDictionary(p => p.Name, p => (object?)p.Value.Clone());
                int age = I(P(hit, "AgeMs")); checks.Add(D("source", "point_plan_cache", "status", "hit", "age_ms", age, "path", S(P(hit, "Path"))));
                payload["from_cache"] = true; payload["cache_age_ms"] = age; payload["cache_ttl_seconds"] = o.Ttl; payload["cache_key"] = key; payload["elapsed_ms"] = ctx.Elapsed;
                payload["precheck"] = precheck; payload["coordinate_profile"] = profile; payload["checks"] = checks.ToArray(); bool ok = Eq(P(payload, "status"), "ok");
                string? brief = !o.Brief ? null : ok && T(P(payload, "recommended_point"))
                    ? $"ok point-plan @({o.X},{o.Y}) cached recommended=({S(P(P(payload, "recommended_point"), "x"))},{S(P(P(payload, "recommended_point"), "y"))}) confidence={S(P(payload, "confidence"))} age_ms={age} elapsed_ms={ctx.Elapsed}"
                    : $"partial point-plan @({o.X},{o.Y}) cached reason={S(P(payload, "reason"))} age_ms={age} elapsed_ms={ctx.Elapsed}";
                return ctx.Complete(payload, ok ? 0 : 2, brief, 12);
            }
        }
        object? scan = null;
        if (!target || guard)
        {
            var argv = new List<string> { "-Action", "hit-scan", "-X", S(o.X), "-Y", S(o.Y), "-ClickInset", S(o.Inset), "-ScanRadius", S(o.Radius), "-ScanStep", S(o.Step) };
            Opt(argv, "-TargetMatch", o.Match); if (o.Hwnd > 0) Opt(argv, "-TargetHwnd", o.Hwnd);
            scan = ctx.Query("hit-scan", "argv", argv.ToArray()); var json = P(scan, "Json");
            checks.Add(D("source", "hit_scan", "status", T(json) ? S(P(json, "status")) : "error", "reason", S(P(json, "reason")), "exit", I(P(scan, "ExitCode")), "elapsed_ms", I(P(scan, "ElapsedMs"))));
        }
        object? best = null, point = null, command = null; string confidence = "low", status = "partial", reason = ""; var scanJson = P(scan, "Json");
        if (target && !guard) reason = "fast_guard_mismatch";
        else if (T(scan) && T(scanJson) && Eq(P(scanJson, "status"), "ok") && T(P(scanJson, "recommended_point")))
        {
            best = P(scanJson, "best"); var rp = P(scanJson, "recommended_point"); confidence = S(P(rp, "confidence"));
            point = D("x", I(P(rp, "x")), "y", I(P(rp, "y")), "confidence", confidence, "point_source", S(P(rp, "point_source")), "native_clickable", T(P(rp, "native_clickable")));
            var cmd = new List<string> { "macro", "click-point", "--x", S(P(point, "x")), "--y", S(P(point, "y")), "--refine", "uia-safe", "--click-inset", S(o.Inset), "--micro-refine", "--precision-radius", S(o.Radius), "--precision-step", S(o.Step) };
            Opt(cmd, "--target-match", o.Match); if (o.Hwnd > 0) Opt(cmd, "--target-hwnd", o.Hwnd); command = cmd.ToArray(); status = "ok";
        }
        else reason = T(P(scanJson, "reason")) ? S(P(scanJson, "reason")) : "no_scan_candidate";
        var result = D("schema", "cucp.point-plan/v1", "status", status, "mode", "coordinate_click", "source", "win32_fast_guard+hit_scan", "x", o.X, "y", o.Y, "radius", o.Radius, "step", o.Step,
            "click_inset", o.Inset, "target_hwnd", o.Hwnd, "target_match", o.Match, "elapsed_ms", ctx.Elapsed, "from_cache", false, "cache_ttl_seconds", o.Ttl, "cache_key", key,
            "confidence", confidence, "safe_to_act", status == "ok", "mouse_moved", false, "reason", reason, "precheck", precheck, "coordinate_profile", profile, "best", best,
            "recommended_point", point, "recommended_command", command, "checks", checks.ToArray(), "scan", T(scanJson) ? scanJson : null,
            "next_step", status == "ok" ? "Run recommended_command with -AllowLiveControl only after user authorization; it will re-run micro-refine before the live click." : "Try a narrower --target-match/--target-hwnd, a slightly larger --radius, or prefer smart-plan/CDP for web UI.");
        if (T(key) && o.Ttl > 0 && (!target || guard)) ctx.Effects.Add(D("kind", "cache-write", "args", D("directory", ctx.CacheDir, "key", key), "bind", "payload"));
        return ctx.Complete(result, status == "ok" ? 0 : 2, !o.Brief ? null : status == "ok"
            ? $"ok point-plan @({o.X},{o.Y}) recommended=({S(P(point, "x"))},{S(P(point, "y"))}) confidence={confidence} source={S(P(point, "point_source"))} samples={S(P(scanJson, "sample_count"))} elapsed_ms={ctx.Elapsed}"
            : $"partial point-plan @({o.X},{o.Y}) reason={reason} elapsed_ms={ctx.Elapsed}", 12);
    }
    private static object Validate(Context ctx, string[] rest)
    {
        var o = Parse(ctx, rest, "target-validate"); string minConfidence = LegacyTextKernel.LowerValue(T(V(rest, "--min-confidence")) ? V(rest, "--min-confidence")! : "medium", CultureInfo.InvariantCulture);
        var planArgs = new List<string> { "--x", S(o.X), "--y", S(o.Y), "--radius", S(o.Radius), "--step", S(o.Step), "--click-inset", S(o.Inset), "--cache-ttl", S(o.Ttl) };
        Opt(planArgs, "--target-match", o.Match); if (o.Hwnd > 0) Opt(planArgs, "--target-hwnd", o.Hwnd); if (o.NoCache) planArgs.Add("--no-cache");
        var planResult = ctx.Query("point-plan-child", "argv", planArgs.ToArray()); var plan = P(planResult, "json");
        var warnings = new List<string>(); var errors = new List<object>();
        if (!T(plan)) return ctx.Complete(D("schema", "cucp.target-validate/v1", "status", "error", "reason", "point_plan_unparseable", "x", o.X, "y", o.Y,
            "safe_to_click", false, "point_plan_exit", I(P(planResult, "exit")), "point_plan_raw", P(planResult, "raw"), "elapsed_ms", ctx.Elapsed,
            "next_step", "Re-run point-plan directly, then re-ground the target window before live control."), 1, null, 8);
        bool target = o.Hwnd > 0 || T(o.Match), planOk = Eq(P(plan, "status"), "ok") && T(P(plan, "safe_to_act")) && T(P(plan, "recommended_point")) && T(P(plan, "recommended_command"));
        if (!target) warnings.Add("no_target_guard_specified"); bool guard = T(P(P(plan, "precheck"), "matched")); if (!guard) warnings.Add("target_guard_not_matched");
        var profile = P(plan, "coordinate_profile"); string risk = T(P(profile, "coordinate_risk")) ? S(P(profile, "coordinate_risk")) : "unknown";
        if (Eq(risk, "high")) warnings.Add("coordinate_profile_high_risk");
        foreach (var cw in A(P(profile, "warnings"))) if (T(cw) && !warnings.Any(w => Eq(cw, w))) warnings.Add(S(cw));
        string confidence = T(P(plan, "confidence")) ? LegacyTextKernel.LowerValue(S(P(plan, "confidence")), CultureInfo.InvariantCulture) : "low";
        bool confidenceOk = ConfidenceRank(confidence) >= ConfidenceRank(minConfidence); if (!confidenceOk) warnings.Add("confidence_below_minimum");
        var best = P(plan, "best"); var match = T(P(best, "match")) ? P(best, "match") : null; var rect = T(P(match, "rect")) ? P(match, "rect") : null;
        int area = TryInt(P(best, "area")); if (area <= 0) area = TryInt(P(match, "area"));
        string size = SizeClass(rect, area); int width = TryInt(P(rect, "width")), height = TryInt(P(rect, "height")), support = TryInt(P(best, "support"));
        var rp = P(plan, "recommended_point"); bool native = T(P(rp, "native_clickable")); string source = S(P(rp, "point_source")), role = S(P(best, "role")), pattern = S(P(best, "pattern"));
        var edge = EdgeDistance(rp, rect); bool near = T(edge) && I(P(edge, "min")) >= 0 && I(P(edge, "min")) < o.Inset, inside = !T(edge) || I(P(edge, "min")) >= 0;
        if (near) warnings.Add("recommended_point_near_element_edge"); if (!inside) warnings.Add("recommended_point_outside_element_rect");
        bool tiny = size == "tiny", small = tiny || size == "small", tinyOk = !tiny || native || support >= 2 || ConfidenceRank(confidence) >= 3;
        if (!tinyOk) warnings.Add("tiny_target_needs_more_support_or_native_clickable_point");
        bool largeOk = size != "large" || B(rest, "--allow-large-surface") || native || T(pattern);
        if (!largeOk) warnings.Add("large_surface_without_pattern_or_native_clickable_point"); if (size == "unknown") warnings.Add("target_size_unknown");
        bool safe = planOk && target && guard && !Eq(risk, "high") && confidenceOk && tinyOk && largeOk && inside;
        if (!planOk) errors.Add(D("code", "point_plan_not_safe", "message", "point-plan did not produce a safe recommended point", "reason", S(P(plan, "reason"))));
        if (!target) errors.Add(D("code", "missing_target_guard", "message", "target-validate requires --target-match or --target-hwnd for safe_to_click=true"));
        if (Eq(risk, "high")) errors.Add(D("code", "high_coordinate_risk", "message", "coordinate profile reports high risk"));
        object? command = safe ? PipelineValue(P(plan, "recommended_command")) : null;
        string[] sortedWarnings = warnings.Distinct(StringComparer.CurrentCultureIgnoreCase).OrderBy(w => w, StringComparer.CurrentCultureIgnoreCase).ToArray();
        return ctx.Complete(D("schema", "cucp.target-validate/v1", "status", safe ? "ok" : "partial", "mode", "pre_click_validation", "x", o.X, "y", o.Y, "radius", o.Radius, "step", o.Step,
            "click_inset", o.Inset, "target_hwnd", o.Hwnd, "target_match", o.Match, "guard_level", target ? "target_guarded" : "unguarded", "safe_to_click", safe,
            "confidence", confidence, "min_confidence", minConfidence, "coordinate_risk", risk, "target_size_class", size, "tiny_target", tiny, "small_target", small, "elapsed_ms", ctx.Elapsed,
            "point_plan_exit", I(P(planResult, "exit")), "point_plan", plan,
            "validation", D("point_plan_ok", planOk, "target_guard_specified", target, "guard_matched", guard, "coordinate_ok", !Eq(risk, "high"), "confidence_ok", confidenceOk,
                "tiny_target_ok", tinyOk, "large_surface_ok", largeOk, "has_recommended_point", T(rp), "has_recommended_command", T(P(plan, "recommended_command")), "target_size_class", size,
                "target_width", width, "target_height", height, "target_area", area, "support", support, "native_clickable", native, "point_source", source, "role", role, "pattern", pattern,
                "recommended_point_inside_rect", inside, "near_element_edge", near, "edge_distance", edge),
            "recommended_command", command, "recommended_command_line", safe && T(command) ? CommandStep(command) : "", "warnings", sortedWarnings, "errors", errors.ToArray(),
            "next_step", safe ? "Run recommended_command with -AllowLiveControl only after user authorization, then verify with wait-label/windows/screenshot-diff." : "Do not live-click yet. Re-ground with app-profile/smart-plan, add --target-match or --target-hwnd, increase --radius, or prefer DOM/UIA pattern routes."),
            safe ? 0 : 2, !o.Brief ? null : safe ? $"ok target-validate @({o.X},{o.Y}) size={size} confidence={confidence} support={support} native={native} elapsed_ms={ctx.Elapsed}"
            : $"partial target-validate @({o.X},{o.Y}) safe=false size={size} confidence={confidence} warnings={sortedWarnings.Length} errors={errors.Count} elapsed_ms={ctx.Elapsed}", 18);
    }
}
