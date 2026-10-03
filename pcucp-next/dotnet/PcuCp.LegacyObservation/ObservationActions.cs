using System;
using System.Collections.Generic;
using System.Collections.Specialized;
using System.Diagnostics;
using System.Globalization;
using System.Text.RegularExpressions;

namespace PcuCp.LegacyObservation
{
    /// <summary>Read-only action bodies. The PowerShell adapter retains its ordered assembly-load checks.</summary>
    public sealed class ObservationActions
    {
        private readonly IObservationProvider provider;
        private readonly ObservationPrimitives primitives;

        public ObservationActions(IObservationProvider provider)
        {
            if (provider == null) throw new ArgumentNullException("provider");
            this.provider = provider;
            primitives = new ObservationPrimitives(provider);
        }

        public ObservationResult HitTest(ObservationOptions options)
        {
            if (!options.HasCoordinates) return MissingCoordinates();
            long child = provider.WindowFromPoint(options.X, options.Y);
            if (child == 0) return Result(2, "status", "partial", "reason", "no_window_at_coords", "x", options.X, "y", options.Y);
            long root = provider.RootAncestor(child);
            string rootTitle = provider.WindowText(root, 256);
            string childTitle = provider.WindowText(child, 256);
            string rootClass = provider.WindowClass(root, 256);
            uint processId = provider.ProcessId(root);
            string processName = "";
            try { processName = provider.ProcessName(processId); } catch { }
            ObservationRefinement point = null;
            if (!options.SkipUia)
            {
                try { point = primitives.ResolvePoint(options.X, options.Y, 360, 220, options.ClickInset); } catch { point = null; }
            }
            bool matched = true;
            string reason = "no_target_specified";
            if (options.TargetHwnd > 0)
            {
                matched = root == options.TargetHwnd;
                reason = matched ? "hwnd_match" : "hwnd_mismatch";
            }
            else if (!string.IsNullOrEmpty(options.TargetMatch))
            {
                matched = !string.IsNullOrEmpty(rootTitle) && rootTitle.ToLowerInvariant().Contains(options.TargetMatch.ToLowerInvariant());
                reason = matched ? "title_match" : "title_mismatch";
            }
            int exitCode = ((options.TargetHwnd > 0 || !string.IsNullOrEmpty(options.TargetMatch)) && !matched) ? 2 : 0;
            var payload = ObservationData.Map(
                "status", exitCode == 0 ? "ok" : "partial", "x", options.X, "y", options.Y,
                "child_hwnd", child, "root_hwnd", root, "root_title", rootTitle, "child_title", childTitle,
                "root_class", rootClass, "process_id", checked((int)processId), "process_name", processName,
                "target_hwnd", options.TargetHwnd, "target_match", options.TargetMatch, "matched", matched,
                "match_reason", reason, "uia_skipped", options.SkipUia);
            if (point != null)
                payload.Add("uia_point", ObservationData.Map("refined_x", point.X, "refined_y", point.Y,
                    "score", point.Score, "role", point.Role, "pattern", point.PatternName,
                    "point_source", point.PointSource, "native_clickable", point.NativeClickable, "match", point.Match));
            return new ObservationResult(payload, exitCode);
        }

        public ObservationResult HitScan(ObservationOptions options)
        {
            if (!options.HasCoordinates) return MissingCoordinates();
            int radius = Math.Max(0, Math.Min(64, options.ScanRadius));
            int step = options.ScanStep <= 0 ? 6 : Math.Min(16, options.ScanStep);
            int inset = options.ClickInset <= 0 ? 3 : options.ClickInset;
            int vx = provider.SystemMetric(76), vy = provider.SystemMetric(77);
            int vw = provider.SystemMetric(78), vh = provider.SystemMetric(79);
            var stopwatch = Stopwatch.StartNew();
            var candidates = new List<ScanCandidate>();
            int sampleCount = 0, targetMatchedSamples = 0;
            var offsets = new List<int> { 0 };
            for (int offset = step; offset <= radius; offset += step) { offsets.Add(-offset); offsets.Add(offset); }
            if (radius > 0 && radius % step != 0) { offsets.Add(-radius); offsets.Add(radius); }
            offsets.Sort(); // The constructed offsets are unique; numeric ascending equals Sort-Object -Unique.
            foreach (int dy in offsets)
            {
                foreach (int dx in offsets)
                {
                    // PowerShell promotes overflowing Int32 arithmetic. Do not wrap virtual-screen edges.
                    double sampleX = (double)options.X + dx, sampleY = (double)options.Y + dy;
                    if (sampleX < vx || sampleX >= (double)vx + vw || sampleY < vy || sampleY >= (double)vy + vh) continue;
                    sampleCount++;
                    int sx = ObservationData.Integer(sampleX), sy = ObservationData.Integer(sampleY);
                    var hit = primitives.TestTarget(sx, sy, options.TargetHwnd, options.TargetMatch);
                    if (!hit.matched) continue;
                    targetMatchedSamples++;
                    ObservationRefinement point = null;
                    try { point = primitives.ResolvePoint(sx, sy, 360, 220, inset); } catch { point = null; }
                    if (point == null) continue;
                    var refinedHit = primitives.TestTarget(point.X, point.Y, options.TargetHwnd, options.TargetMatch);
                    if (!refinedHit.matched) continue;
                    string identifier = "";
                    try { identifier = ObservationData.Text(point.Match == null ? null : point.Match["preferred_identifier"]); } catch { }
                    if (string.IsNullOrEmpty(identifier))
                    {
                        try { identifier = ObservationData.Text(point.Match == null ? null : point.Match["name"]) + "|" +
                            ObservationData.Text(point.Match == null ? null : point.Match["automation_id"]) + "|" + point.Role; }
                        catch { identifier = ObservationData.Text(point.Role); }
                    }
                    candidates.Add(new ScanCandidate {
                        Key = identifier + "|" + point.Role + "|" + point.PatternName + "|" + point.X.ToString(CultureInfo.InvariantCulture) + "," + point.Y.ToString(CultureInfo.InvariantCulture),
                        SampleX = sx, SampleY = sy, Dx = dx, Dy = dy, Point = point,
                        Area = ObservationData.Integer(point.Area)
                    });
                }
            }
            // A PowerShell hashtable groups string keys case-insensitively. Keep every sample row.
            var groups = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
            foreach (var candidate in candidates)
            {
                int support;
                groups.TryGetValue(candidate.Key, out support);
                groups[candidate.Key] = support + 1;
            }
            var ranked = new List<OrderedDictionary>();
            foreach (var candidate in candidates)
            {
                var point = candidate.Point;
                int support = groups[candidate.Key];
                double xDistance = (double)point.X - options.X, yDistance = (double)point.Y - options.Y;
                double distance = Math.Sqrt(xDistance * xDistance + yDistance * yDistance);
                int distancePenalty = ObservationData.Integer(Math.Round(distance));
                int clickBonus = point.NativeClickable ? 12 : 0;
                if (string.Equals(point.PointSource, "clickable_point", StringComparison.InvariantCultureIgnoreCase)) clickBonus += 8;
                int finalScore = point.Score + support * 7 + clickBonus - distancePenalty;
                ranked.Add(ObservationData.Map(
                    "sample_x", candidate.SampleX, "sample_y", candidate.SampleY, "dx", candidate.Dx, "dy", candidate.Dy,
                    "refined_x", point.X, "refined_y", point.Y, "final_score", finalScore, "base_score", point.Score,
                    "support", support, "distance_from_origin", distance, "role", ObservationData.Text(point.Role),
                    "pattern", ObservationData.Text(point.PatternName), "point_source", ObservationData.Text(point.PointSource),
                    "native_clickable", point.NativeClickable, "depth", point.Depth, "area", candidate.Area, "match", point.Match));
            }
            SortDescending(ranked, "final_score", "support", "base_score");
            OrderedDictionary best = ranked.Count == 0 ? null : ranked[0];
            stopwatch.Stop();
            if (best == null)
                return Result(2, "status", "partial", "reason", "no_uia_candidate", "x", options.X, "y", options.Y,
                    "radius", radius, "step", step, "click_inset", inset, "target_hwnd", options.TargetHwnd,
                    "target_match", options.TargetMatch, "sample_count", sampleCount, "target_matched_samples", targetMatchedSamples,
                    "candidate_count", candidates.Count, "elapsed_ms", ObservationData.Integer(stopwatch.Elapsed.TotalMilliseconds),
                    "recommended_action", "Try a slightly larger --radius, narrower --target-match, or DOM/UIA label route.");
            int bestSupport = (int)best["support"];
            string confidence = bestSupport >= 4 || (bool)best["native_clickable"] ? "high" : bestSupport >= 2 ? "medium" : "low";
            return Result(0, "status", "ok", "x", options.X, "y", options.Y, "radius", radius, "step", step,
                "click_inset", inset, "target_hwnd", options.TargetHwnd, "target_match", options.TargetMatch,
                "sample_count", sampleCount, "target_matched_samples", targetMatchedSamples, "candidate_count", candidates.Count,
                "best", best, "recommended_point", ObservationData.Map("x", best["refined_x"], "y", best["refined_y"],
                    "point_source", best["point_source"], "native_clickable", best["native_clickable"], "confidence", confidence),
                "candidates", First(ranked, 12), "elapsed_ms", ObservationData.Integer(stopwatch.Elapsed.TotalMilliseconds));
        }

        public ObservationResult UiaTree(ObservationOptions options)
        {
            long target = SelectWindow(options.Match);
            if (target == 0) return Result(2, "status", "partial", "reason", "no_matching_window", "match", options.Match);
            object root = provider.FromHandle(target);
            if (root == null) return Result(2, "status", "partial", "reason", "uia_root_null");
            var items = new List<OrderedDictionary>();
            foreach (object element in provider.Descendants(root))
            {
                if (items.Count >= options.MaxElements) break;
                try
                {
                    object current = provider.Current(element);
                    ObservationRect rect = provider.Bounds(current);
                    if (rect.IsEmpty || rect.Width < options.MinSize || rect.Height < options.MinSize) continue;
                    string name = ReadText(current, ObservationProperty.Name);
                    string automationId = ReadText(current, ObservationProperty.AutomationId);
                    string help = ReadText(current, ObservationProperty.HelpText);
                    string accessKey = ReadText(current, ObservationProperty.AccessKey);
                    string className = ReadText(current, ObservationProperty.ClassName);
                    string role = ReadRole(current);
                    bool offscreen = ReadBoolean(current, ObservationProperty.IsOffscreen, false);
                    bool enabled = ReadBoolean(current, ObservationProperty.IsEnabled, true);
                    if (offscreen) continue;
                    string text = !string.IsNullOrWhiteSpace(name) ? name : !string.IsNullOrWhiteSpace(automationId) ? automationId :
                        !string.IsNullOrWhiteSpace(help) ? help : null;
                    if (string.IsNullOrEmpty(text)) continue;
                    items.Add(ObservationData.Map("text", text, "name", name, "automation_id", automationId,
                        "help_text", help, "access_key", accessKey, "class_name", className, "role", role, "enabled", enabled,
                        "rect", ObservationData.Rect(rect), "center", ObservationData.Center(rect)));
                }
                catch { continue; }
            }
            return Result(0, "status", "ok", "target_hwnd", target, "affordance_count", items.Count, "affordances", items.ToArray());
        }

        public ObservationResult UiaFind(ObservationOptions options)
        {
            if (string.IsNullOrEmpty(options.Label)) return Result(1, "status", "error", "reason", "missing_label");
            long target = SelectWindow(options.Match);
            if (target == 0) return Result(2, "status", "partial", "reason", "no_matching_window", "match", options.Match);
            object root = provider.FromHandle(target);
            if (root == null) return Result(2, "status", "partial", "reason", "uia_root_null");
            string needle = Normalize(options.Label.Trim().ToLowerInvariant());
            var candidates = new List<OrderedDictionary>();
            foreach (object element in provider.Descendants(root))
            {
                if (candidates.Count >= options.MaxElements) break;
                try
                {
                    object current = provider.Current(element);
                    ObservationRect rect = provider.Bounds(current);
                    if (rect.IsEmpty || rect.Width < options.MinSize || rect.Height < options.MinSize) continue;
                    // PowerShell adapts a throwing IsOffscreen getter to null, so the branch is false.
                    // Keep conversion outside that acquisition boundary.
                    object offscreenValue = null;
                    try { offscreenValue = provider.Property(current, ObservationProperty.IsOffscreen); } catch { }
                    if (Convert.ToBoolean(offscreenValue, CultureInfo.InvariantCulture)) continue;
                    string name = ReadText(current, ObservationProperty.Name);
                    string automationId = ReadText(current, ObservationProperty.AutomationId);
                    string help = ReadText(current, ObservationProperty.HelpText);
                    string accessKey = ReadText(current, ObservationProperty.AccessKey);
                    string role = ReadRole(current);
                    if (!string.IsNullOrEmpty(options.Role) && !string.IsNullOrEmpty(role) &&
                        !string.Equals(role.ToLowerInvariant(), options.Role.ToLowerInvariant(), StringComparison.InvariantCultureIgnoreCase)) continue;
                    int score = 0;
                    string reason = "";
                    foreach (string field in new[] { name, automationId, help, accessKey })
                    {
                        if (string.IsNullOrWhiteSpace(field)) continue;
                        string hay = Normalize(field.ToLowerInvariant());
                        int local = 0;
                        if (string.Equals(hay, needle, StringComparison.InvariantCultureIgnoreCase)) local = 100;
                        else if (Regex.IsMatch(hay, Regex.Escape(needle), RegexOptions.IgnoreCase))
                            local = 60 + Math.Max(0, 40 - Math.Abs(hay.Length - needle.Length));
                        else if (needle.Length >= 2 && hay.IndexOf(needle.Substring(0, Math.Min(2, needle.Length)), StringComparison.CurrentCulture) >= 0)
                            local = 15;
                        if (local > score) { score = local; reason = local >= 100 ? "exact" : local >= 60 ? "substring" : "prefix"; }
                    }
                    if (score <= 0) continue;
                    string pattern = null;
                    try { pattern = primitives.SupportedPattern(element); } catch { pattern = null; }
                    bool valuePattern = false;
                    object valueReadonly = null;
                    try
                    {
                        object value = provider.Pattern(element, ObservationPattern.Value);
                        if (value != null)
                        {
                            valuePattern = true;
                            // Both Current and IsReadOnly are adapted property reads; [bool]null is false.
                            valueReadonly = false;
                            valueReadonly = provider.ValueReadOnly(value);
                        }
                    }
                    catch { }
                    ObservationPoint point = null;
                    try { point = primitives.PreferredClickPoint(element, rect, options.ClickInset); } catch { point = null; }
                    candidates.Add(ObservationData.Map(
                        "text", !string.IsNullOrEmpty(name) ? name : !string.IsNullOrEmpty(automationId) ? automationId : help,
                        "role", role, "rect", ObservationData.Rect(rect), "center", ObservationData.Center(rect),
                        "click_point", point == null ? null : ObservationData.Map("x", point.X, "y", point.Y, "source", point.Source, "native_clickable", point.NativeClickable),
                        "score", score, "match_reason", reason, "automation_id", automationId, "invoke_pattern", pattern,
                        "value_pattern", valuePattern, "value_readonly", valueReadonly));
                }
                catch { continue; }
            }
            SortDescending(candidates, "score");
            if (candidates.Count == 0) return Result(2, "status", "partial", "reason", "no_match", "label", options.Label);
            bool ambiguous = candidates.Count > 1 && (int)candidates[0]["score"] - (int)candidates[1]["score"] < 8;
            // The source omits @(...): one pipeline result is a scalar, multiple results are an array.
            object selected = candidates.Count == 1 ? (object)candidates[0] : First(candidates, 5);
            return Result(ambiguous ? 2 : 0, "status", ambiguous ? "partial" : "ok", "label", options.Label,
                "top", candidates[0], "candidates", selected, "ambiguous", ambiguous);
        }

        private long SelectWindow(string match)
        {
            string needle = string.IsNullOrEmpty(match) ? null : match.ToLowerInvariant();
            foreach (var window in provider.TopLevelWindows())
            {
                if (needle != null)
                {
                    if (!string.IsNullOrEmpty(window.Title) && window.Title.ToLowerInvariant().Contains(needle)) return window.Hwnd;
                }
                else if (window.Foreground) return window.Hwnd;
            }
            return 0;
        }

        private string ReadText(object current, ObservationProperty property)
        { try { return ObservationData.Text(provider.Property(current, property)); } catch { return ""; } }
        private string ReadRole(object current)
        { try { return (string)provider.Property(current, ObservationProperty.LocalizedControlType); } catch { return null; } }
        private bool ReadBoolean(object current, ObservationProperty property, bool fallback)
        {
            object value = null;
            try { value = provider.Property(current, property); } catch { }
            // A getter failure is null, but an actual conversion failure still retains the source default.
            try { return Convert.ToBoolean(value, CultureInfo.InvariantCulture); } catch { return fallback; }
        }
        private static string Normalize(string text) { return Regex.Replace(text, "\\s+", " ").Trim(); }
        private static ObservationResult MissingCoordinates()
        { return Result(1, "status", "error", "reason", "missing_coords", "recommended_action", "provide -X and -Y (zero and negative screen coordinates are valid)"); }
        private static ObservationResult Result(int exitCode, params object[] fields)
        { return new ObservationResult(ObservationData.Map(fields), exitCode); }
        private static OrderedDictionary[] First(List<OrderedDictionary> rows, int count)
        { return rows.GetRange(0, Math.Min(count, rows.Count)).ToArray(); }
        private static void SortDescending(List<OrderedDictionary> rows, params string[] keys)
        {
            // Deliberately no input-index tiebreak and no stable LINQ sort. Sort-Object's full-sort
            // path uses List.Sort; Windows PowerShell 5.1 tied-row oracle qualification is required.
            rows.Sort(delegate(OrderedDictionary left, OrderedDictionary right) {
                foreach (string key in keys) { int comparison = ((int)right[key]).CompareTo((int)left[key]); if (comparison != 0) return comparison; }
                return 0;
            });
        }
        private sealed class ScanCandidate
        {
            public string Key;
            public int SampleX, SampleY, Dx, Dy, Area;
            public ObservationRefinement Point;
        }
    }
}
