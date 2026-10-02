using System.Text.Json;

internal sealed partial class LegacyExecutionCoordinator
{
    private LegacyExecutionResult IconFind()
    {
        string? label = V("--label"), window = V("--window"), match = V("--match"), role = V("--role");
        int maximum = I(V("--max-size")), minimum = I(V("--min-size")), nearX = I(V("--near-x")), nearY = I(V("--near-y")), radius = I(V("--near-radius")), limit = I(V("--limit"));
        if (!Has(label)) throw CommandOptions.Invalid("macro icon-find requires --label"); if (!Has(match)) match = window;
        if (maximum <= 0) maximum = 64; if (minimum <= 0) minimum = 6; if (limit <= 0) limit = 8;
        bool hasNear = nearX > 0 || nearY > 0; Start("icon-find");
        var affordances = IE(LegacyExecutionEffectKind.UIAffordances, D("focused_window", match ?? "", "max_elements", 800));
        string needle = Normal(label!); var candidates = new List<Dictionary<string, object?>>();
        foreach (var el in A(affordances))
        {
            if (!FilterElement(el, window, role)) continue; var rect = P(el, "rect");
            double w = Number(P(rect, "width")), h = Number(P(rect, "height")); if (w > maximum || h > maximum || w < minimum || h < minimum) continue;
            var best = Hays(el).Select(v => LabelScore(Normal(v), needle, 2, 15)).OrderByDescending(s => s.Score).First();
            if (best.Score <= 0) continue;
            double score = best.Score; if (P(el, "confidence").ValueKind == JsonValueKind.String) score += ConfidenceBoost(P(el, "confidence"), 6, 3);
            var center = Center(el); int? distance = null;
            if (hasNear)
            {
                double dx = center.X - nearX, dy = center.Y - nearY; distance = Round(Math.Sqrt(dx * dx + dy * dy));
                if (radius > 0 && distance > radius) continue; score += Math.Max(0, 50 - distance.Value / 10d);
            }
            candidates.Add(D("affordance_id", P(el, "affordance_id"), "text", P(el, "text"), "synonyms", P(el, "synonyms"), "role", P(el, "role"),
                "window", P(el, "window"), "class_name", P(el, "class_name"), "rect", rect, "center", D("x", center.X, "y", center.Y),
                "area", P(el, "area"), "small_icon", P(el, "small_icon"), "enabled", P(el, "enabled"), "tooltip", P(el, "tooltip"), "score", Round(score),
                "match_reason", best.Reason, "distance_px", distance, "confidence", P(el, "confidence")));
        }
        var ranked = LegacyInteractionRanking.Sort(candidates, (a, b) => ((int)b["score"]!).CompareTo((int)a["score"]!)).Take(limit).ToArray(); int elapsed = Stop("icon-find");
        var top = ranked.FirstOrDefault(); bool ambiguous = ranked.Length > 1 && (int)ranked[0]["score"]! - (int)ranked[1]["score"]! < 8;
        string status = top is null || ambiguous ? "partial" : "ok";
        object[] errors = top is null ? [D("code", "no_icon", "message", $"no icon (size <= {maximum}px) matched '{label}' under window '{match}'", "recommended_action", $"Try '--max-size 96' or 'cucp macro list-affordances --window \"{match}\" --limit 50' to inspect.")]
            : ambiguous ? [D("code", "ambiguous_icon", "message", "top two icon candidates within 8 score points", "recommended_action", "Add --near-x/--near-y to anchor near a known reference point, or pick by affordance_id.")] : [];
        var payload = D("schema", "cucp.icon-find/v1", "status", status, "collected_at", Effect(LegacyExecutionEffectKind.Timestamp, "o"), "elapsed_ms", elapsed,
            "label", label, "window", window, "match", match, "max_size", maximum, "min_size", minimum,
            "near", hasNear ? D("x", nearX, "y", nearY, "radius", radius) : null, "candidate_count", ranked.Length, "ambiguous", ambiguous,
            "top", top, "candidates", candidates.Count > limit && limit == 1 ? ranked[0] : ranked, "recoverable_errors", errors);
        string line;
        if (top is null) line = $"partial icon-find '{label}' no_icon match='{match}' max_size={maximum} elapsed_ms={elapsed}";
        else
        {
            var t = J(top); var c = P(t, "center"); var r = P(t, "rect");
            line = $"{status} icon-find '{label}' top='{S(P(t, "text"))}' @({S(P(c, "x"))},{S(P(c, "y"))}) {S(P(r, "width"))}x{S(P(r, "height"))} score={top["score"]} reason={top["match_reason"]} candidates={ranked.Length} elapsed_ms={elapsed}";
        }
        return Result(payload, status == "ok" ? 0 : 2, 8, line);
    }
    private JsonElement NestedIcons(string[] args) => new LegacyExecutionCoordinator(effects, authority, args, brief, cacheSeconds, visionAvailable).IconFind().Payload;
    private LegacyExecutionResult IconClick()
    {
        Live("macro icon-click requires -AllowLiveControl");
        var found = NestedIcons([.. rest, "--json-only"]);
        if (!T(found)) return Silent(1, "err icon-click parse_failed");
        if (!Eq(P(found, "status"), "ok") || !T(P(found, "top")))
        {
            var errors = A(P(found, "recoverable_errors")); string reason = errors.Length > 0 ? S(P(errors[0], "code")) : "no_icon";
            return Result(found, 2, 8, $"partial icon-click '{S(P(found, "label"))}' {reason} candidates={S(P(found, "candidate_count"))}", renderBrief: brief);
        }
        var shot = Appshot(S(P(found, "match")), true); string observationId = T(shot) ? S(P(shot, "ObservationId")) : "";
        if (!Has(observationId)) observationId = S(IE(LegacyExecutionEffectKind.ObservationId, name: "icon-click"));
        var top = P(found, "top"); int x = I(P(P(top, "center"), "x")), y = I(P(P(top, "center"), "y"));
        var args = new List<string> { "act", "click", "--x", Num(x), "--y", Num(y), "--after", observationId };
        if (T(P(top, "window"))) args.AddRange(["--target-window", S(P(top, "window"))]);
        var clicked = Act(args);
        return Silent(ExitOf(clicked), ExitOf(clicked) == 0 ? $"ok icon-click '{S(P(found, "label"))}' @({x},{y}) win='{S(P(top, "window"))}' score={S(P(top, "score"))}"
            : $"err icon-click '{S(P(found, "label"))}' exit={ExitOf(clicked)}");
    }
    private LegacyExecutionResult ClickLabel(bool doubleClick, bool rightClick)
    {
        string? label = V("--label"), window = V("--window"), match = V("--match"), role = V("--role");
        int dx = I(V("--offset-x")), dy = I(V("--offset-y")); bool noVision = F("--no-vision");
        if (!Has(label)) throw CommandOptions.Invalid("macro click-label requires --label"); if (!Has(match)) match = window;
        if (!authority.AllowLiveControl) { Notice("ERROR", "라이브 클릭은 -AllowLiveControl이 필요합니다."); throw CommandOptions.Invalid("Live click requires -AllowLiveControl"); }
        var shot = Appshot(match, true); if (!T(shot)) throw CommandOptions.Invalid("appshot failed");
        var el = FindElement(shot, label!, window, role); JsonElement icon = Null, vision = Null; string source = "element";
        if (!T(el))
        {
            try
            {
                var found = NestedIcons(["--label", label!, "--match", match ?? "", "--window", window ?? "", "--max-size", "96", "--limit", "5", "--json-only"]);
                if (T(found) && Eq(P(found, "status"), "ok") && T(P(found, "top"))) icon = P(found, "top");
            }
            catch (Exception error) when (error is LegacyExecutionEffectException or NativeFailure or InvalidOperationException) { }
            if (T(icon)) source = "icon_find_fallback";
            else
            {
                if (!noVision)
                {
                    Notice("WARN", $"라벨 fusion + icon-find 실패 - codex vision으로 fallback: '{label}'");
                    string description = Has(window) ? $"{label} ({window} 창 안)" : label!;
                    vision = IE(LegacyExecutionEffectKind.Vision, D("screenshot_path", S(P(shot, "ScreenshotPath")), "description", description));
                    if (Eq(P(vision, "status"), "ok")) source = "vision_fallback";
                    else Notice("ERROR", $"vision fallback도 실패: {S(P(vision, "status"))} {S(P(vision, "reason"))}");
                }
                if (source != "vision_fallback")
                {
                    Notice("ERROR", $"라벨을 찾지 못했습니다: '{label}' (window='{window}'). 후보: {string.Join(" | ", A(P(shot, "FusedElements")).Take(10).Select(e => S(P(e, "text"))))}");
                    throw CommandOptions.Invalid("Label not found: " + label);
                }
            }
        }
        var point = source == "element" ? Center(el) : source == "icon_find_fallback" ? (I(P(P(icon, "center"), "x")), I(P(P(icon, "center"), "y"))) : (I(P(vision, "x")), I(P(vision, "y")));
        int x = point.Item1 + dx, y = point.Item2 + dy;
        string? target = source == "element" ? S(P(el, "window")) : source == "icon_find_fallback" ? S(P(icon, "window")) : window;
        var args = new List<string> { "act", rightClick ? "right-click" : "click", "--x", Num(x), "--y", Num(y), "--after", S(P(shot, "ObservationId")) };
        if (Has(target)) args.AddRange(["--target-window", target!]); var clicked = Act(args);
        if (doubleClick && ExitOf(clicked) == 0) Act(args);
        Dictionary<string, object?> trajectory;
        string success;
        if (source == "element")
        {
            trajectory = D("label", label, "window", P(el, "window"), "role", P(el, "role"), "x", x, "y", y,
                "observation_id", P(shot, "ObservationId"), "exit", ExitOf(clicked), "double", doubleClick, "right", rightClick);
            success = $"ok click-label '{label}' @({x},{y}) win='{target}'";
        }
        else
        {
            var acquired = source == "icon_find_fallback" ? icon : vision;
            trajectory = D("label", label, "window", source == "icon_find_fallback" ? P(icon, "window") : window, "source", source, "confidence", S(P(acquired, "confidence")), "x", x, "y", y);
            if (source == "icon_find_fallback") { trajectory["rect_w"] = I(P(P(icon, "rect"), "width")); trajectory["rect_h"] = I(P(P(icon, "rect"), "height")); }
            trajectory["observation_id"] = P(shot, "ObservationId"); trajectory["exit"] = ExitOf(clicked);
            success = source == "icon_find_fallback" ? $"ok click-label '{label}' @({x},{y}) via=icon-find size={I(P(P(icon, "rect"), "width"))}x{I(P(P(icon, "rect"), "height"))} score={S(P(icon, "score"))}"
                : $"ok click-label '{label}' @({x},{y}) via=vision conf={S(P(vision, "confidence"))}";
        }
        Trace("click", trajectory); if (brief) Pipeline(ExitOf(clicked) == 0 ? success : $"err click-label '{label}' exit={ExitOf(clicked)}");
        return Silent(ExitOf(clicked));
    }
}
