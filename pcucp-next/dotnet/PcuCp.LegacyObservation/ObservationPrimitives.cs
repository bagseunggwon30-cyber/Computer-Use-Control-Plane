using System;
using System.Collections.Specialized;
using System.Text.RegularExpressions;

namespace PcuCp.LegacyObservation
{
    // The reads, ordering and catch scopes intentionally follow the legacy helper.
    public sealed class ObservationPrimitives
    {
        private readonly IObservationProvider provider;

        public ObservationPrimitives(IObservationProvider provider)
        {
            if (provider == null) throw new ArgumentNullException(nameof(provider));
            this.provider = provider;
        }

        public string SupportedPattern(object element)
        {
            if (element == null) return null;
            try { if (provider.Pattern(element, ObservationPattern.Invoke) != null) return "InvokePattern"; } catch { }
            try { if (provider.Pattern(element, ObservationPattern.Toggle) != null) return "TogglePattern"; } catch { }
            try { if (provider.Pattern(element, ObservationPattern.SelectionItem) != null) return "SelectionItemPattern"; } catch { }
            return null;
        }

        public OrderedDictionary MatchPayload(object current, string pattern)
        {
            var rect = provider.Bounds(current);
            var name = ""; try { name = ObservationData.Text(provider.Property(current, ObservationProperty.Name)); } catch { }
            var automationId = ""; try { automationId = ObservationData.Text(provider.Property(current, ObservationProperty.AutomationId)); } catch { }
            object role = ""; try { role = provider.Property(current, ObservationProperty.LocalizedControlType); } catch { }
            var className = ""; try { className = ObservationData.Text(provider.Property(current, ObservationProperty.ClassName)); } catch { }
            var enabled = true; try { enabled = Convert.ToBoolean(provider.Property(current, ObservationProperty.IsEnabled)); } catch { }
            var offscreen = false; try { offscreen = Convert.ToBoolean(provider.Property(current, ObservationProperty.IsOffscreen)); } catch { }
            var preferred = "none";
            if (!string.IsNullOrWhiteSpace(name)) preferred = "name";
            else if (!string.IsNullOrWhiteSpace(automationId)) preferred = "automation_id";
            else if (!string.IsNullOrWhiteSpace(className)) preferred = "class_name";
            return ObservationData.Map(
                "name", name, "automation_id", automationId, "class_name", className, "role", role,
                "rect", ObservationData.Rect(rect), "center", ObservationData.Center(rect),
                "area", ObservationData.Integer(rect.Width * rect.Height),
                "is_enabled", enabled, "is_offscreen", offscreen,
                // PowerShell's [string] parameter binds a null pattern as an empty string.
                "invoke_pattern", pattern ?? "", "preferred_identifier", preferred);
        }

        public int RoleWeight(string role)
        {
            if (string.IsNullOrEmpty(role)) return 0;
            var normalized = role.ToLowerInvariant();
            if (Regex.IsMatch(normalized, "button|hyperlink|menu item|tab|check|radio|combo|split button", RegexOptions.IgnoreCase)) return 40;
            if (Regex.IsMatch(normalized, "edit|document|list item|tree item|data item", RegexOptions.IgnoreCase)) return 18;
            if (Regex.IsMatch(normalized, "pane|window|group|custom", RegexOptions.IgnoreCase)) return -8;
            return 0;
        }

        public ObservationPoint Clamp(double x, double y, ObservationRect rect, int inset = 3,
            string source = "center", bool nativeClickable = false)
        {
            if (rect == null || rect.IsEmpty || rect.Width <= 0 || rect.Height <= 0) return null;
            var safeInset = Math.Max(0, inset);
            var insetX = Math.Min((double)safeInset, Math.Max(0.0, (rect.Width - 1.0) / 2.0));
            var insetY = Math.Min((double)safeInset, Math.Max(0.0, (rect.Height - 1.0) / 2.0));
            var minX = rect.X + insetX;
            var maxX = rect.X + rect.Width - insetX;
            var minY = rect.Y + insetY;
            var maxY = rect.Y + rect.Height - insetY;
            if (maxX < minX) { minX = rect.X + rect.Width / 2.0; maxX = minX; }
            if (maxY < minY) { minY = rect.Y + rect.Height / 2.0; maxY = minY; }
            var clampedX = Math.Max(minX, Math.Min(maxX, x));
            var clampedY = Math.Max(minY, Math.Min(maxY, y));
            return new ObservationPoint {
                X = ObservationData.Integer(clampedX), Y = ObservationData.Integer(clampedY),
                Source = source ?? "", NativeClickable = nativeClickable
            };
        }

        public ObservationPoint PreferredClickPoint(object element, ObservationRect rect, int inset = 3)
        {
            if (element == null || rect == null || rect.IsEmpty) return null;
            try
            {
                double x, y;
                if (provider.ClickablePoint(element, out x, out y))
                    return Clamp(x, y, rect, inset, "clickable_point", true);
            }
            catch { }
            return Clamp(rect.X + rect.Width / 2.0, rect.Y + rect.Height / 2.0,
                rect, inset, "rect_center", false);
        }

        public ObservationRefinement ResolvePoint(int x, int y, int maxWidth = 360, int maxHeight = 220, int inset = 3)
        {
            if (!provider.EnsureUia()) return null;
            object element;
            try { element = provider.FromPoint(x, y); } catch { return null; }
            if (element == null) return null;
            var walker = provider.ControlViewWalker();
            ObservationRefinement best = null;
            for (var depth = 0; depth <= 5 && element != null; depth++)
            {
                try
                {
                    var current = provider.Current(element);
                    var rect = provider.Bounds(current);
                    if (!rect.IsEmpty && rect.Width > 1 && rect.Height > 1)
                    {
                        var pattern = SupportedPattern(element);
                        var role = ""; try { role = ObservationData.Text(provider.Property(current, ObservationProperty.LocalizedControlType)); } catch { }
                        var enabled = true; try { enabled = Convert.ToBoolean(provider.Property(current, ObservationProperty.IsEnabled)); } catch { }
                        var offscreen = false; try { offscreen = Convert.ToBoolean(provider.Property(current, ObservationProperty.IsOffscreen)); } catch { }
                        var area = rect.Width * rect.Height;
                        var bounded = rect.Width <= maxWidth && rect.Height <= maxHeight;
                        var score = 0;
                        if (pattern != null) score += 80;
                        score += RoleWeight(role);
                        score += bounded ? 30 : -45;
                        score += enabled ? 10 : -40;
                        if (offscreen) score -= 60;
                        if (depth > 0) score -= depth * 4;
                        if (area <= 800) score += 10;
                        if (area > 120000) score -= 30;
                        ObservationPoint point = null;
                        try { point = PreferredClickPoint(element, rect, inset); } catch { point = null; }
                        if (point != null && point.NativeClickable) score += 8;
                        if (score >= 45 && point != null)
                        {
                            var payload = MatchPayload(current, pattern);
                            var candidate = new ObservationRefinement {
                                X = point.X, Y = point.Y, Score = score, Depth = depth,
                                PatternName = pattern, Role = role, Area = area,
                                PointSource = point.Source, NativeClickable = point.NativeClickable,
                                Match = payload
                            };
                            if (best == null || candidate.Score > best.Score) best = candidate;
                        }
                    }
                    object parent = null;
                    try { parent = provider.Parent(walker, element); } catch { parent = null; }
                    if (parent == null) break;
                    element = parent;
                }
                catch { break; }
            }
            return best;
        }

        public ObservationGuard TestTarget(int x, int y, int expectedHwnd, string expectedMatch)
        {
            var child = provider.WindowFromPoint(x, y);
            if (child == 0)
                return new ObservationGuard { matched = false, actual_hwnd = 0, actual_root_hwnd = 0,
                    actual_title = "", reason = "no_window_at_coords" };
            var root = provider.RootAncestor(child);
            var title = provider.WindowText(root, 256);
            var matched = false;
            var reason = "";
            if (expectedHwnd > 0)
            {
                matched = root == expectedHwnd;
                if (!matched) reason = "hwnd_mismatch";
            }
            else if (!string.IsNullOrEmpty(expectedMatch))
            {
                var needle = expectedMatch.ToLowerInvariant();
                if (!string.IsNullOrEmpty(title) && title.ToLowerInvariant().Contains(needle)) matched = true;
                else reason = "title_mismatch";
            }
            else matched = true;
            return new ObservationGuard { matched = matched, actual_hwnd = child, actual_root_hwnd = root,
                actual_title = title, reason = reason };
        }
    }
}
