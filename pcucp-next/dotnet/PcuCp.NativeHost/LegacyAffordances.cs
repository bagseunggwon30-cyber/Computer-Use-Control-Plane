using System.Windows.Automation;
using System.Text.RegularExpressions;

/// <summary>The wrapper's label, tooltip, icon, and stable-id acquisition.</summary>
internal static class LegacyAffordances
{
    internal static string Slug(string? value)
    {
        if (string.IsNullOrWhiteSpace(value)) return "unknown";
        string result = Regex.Replace(value.ToLowerInvariant(), "[^a-z0-9가-힣]+", "-").Trim('-');
        if (result.Length == 0) return "unknown";
        return result[..Math.Min(32, result.Length)];
    }

    internal static object[] Read(string focusedWindow, int maximum = 400, int minimumSize = 6, long hwnd = 0)
    {
        var results = new List<object>();
        try
        {
            var root = AutomationElement.RootElement;
            if (root is null) return [];
            var target = root;
            if (hwnd > 0)
            {
                try { target = AutomationElement.FromHandle(new IntPtr(hwnd)) ?? root; } catch { }
            }
            if (target == root && focusedWindow.Length != 0)
            {
                var windows = root.FindAll(TreeScope.Children,
                    new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.Window));
                string needle = focusedWindow.ToLowerInvariant();
                needle = needle[..Math.Min(16, needle.Length)];
                foreach (AutomationElement window in windows)
                {
                    try
                    {
                        if (!string.IsNullOrEmpty(window.Current.Name) && window.Current.Name.ToLowerInvariant().Contains(needle))
                        { target = window; break; }
                    }
                    catch { }
                }
            }
            var types = new[] { ControlType.Button, ControlType.Edit, ControlType.Hyperlink, ControlType.MenuItem,
                ControlType.TabItem, ControlType.ListItem, ControlType.TreeItem, ControlType.CheckBox,
                ControlType.RadioButton, ControlType.ComboBox, ControlType.Document, ControlType.Text,
                ControlType.Header, ControlType.SplitButton, ControlType.Group, ControlType.Image,
                ControlType.ToolBar, ControlType.Pane };
            var condition = new OrCondition(types.Select(type => (Condition)new PropertyCondition(
                AutomationElement.ControlTypeProperty, type)).ToArray());
            var elements = target.FindAll(TreeScope.Descendants, condition);
            foreach (AutomationElement element in elements)
            {
                if (results.Count >= maximum) break;
                try
                {
                    var current = element.Current;
                    var bounds = current.BoundingRectangle;
                    if (bounds.IsEmpty || bounds.Width < minimumSize || bounds.Height < minimumSize) continue;
                    string name = Safe(() => current.Name), autoId = Safe(() => current.AutomationId),
                        help = Safe(() => current.HelpText), accessKey = Safe(() => current.AccessKey),
                        status = Safe(() => current.ItemStatus), className = Safe(() => current.ClassName);
                    var synonyms = new HashSet<string>();
                    foreach (var label in new[] { name, autoId, help, accessKey, status })
                        if (!string.IsNullOrWhiteSpace(label)) synonyms.Add(label.Trim());
                    if (synonyms.Count == 0) continue;
                    string text = !string.IsNullOrWhiteSpace(name) ? name : !string.IsNullOrWhiteSpace(autoId) ? autoId : help;
                    if (string.IsNullOrWhiteSpace(text)) continue;
                    string role = Safe(() => current.LocalizedControlType);
                    if (string.IsNullOrWhiteSpace(role)) role = Safe(() => current.ControlType.ProgrammaticName);
                    bool offscreen = Safe(() => current.IsOffscreen, false), enabled = Safe(() => current.IsEnabled, true),
                        focusable = Safe(() => current.IsKeyboardFocusable, false);
                    if (offscreen) continue;
                    int agree = new[] { name, autoId, help }.Count(label => !string.IsNullOrWhiteSpace(label));
                    string confidence = agree >= 2 ? "high" : agree == 0 ? "low" : "medium";
                    string window = focusedWindow.Length != 0 ? focusedWindow : Safe(() => current.Name);
                    int x = Convert.ToInt32(bounds.X), y = Convert.ToInt32(bounds.Y),
                        width = Convert.ToInt32(bounds.Width), height = Convert.ToInt32(bounds.Height);
                    string w = Slug(window); w = w[..Math.Min(24, w.Length)];
                    string r = Slug(role); r = r[..Math.Min(16, r.Length)];
                    string t = Slug(text);
                    // PS integer multiply promotes to Double on overflow.
                    long wideArea = (long)width * height;
                    object area = wideArea is >= int.MinValue and <= int.MaxValue ? (object)(int)wideArea : (double)wideArea;
                    results.Add(new
                    {
                        affordance_id = $"aff:{w}:{r}:{t}:{x}-{y}-{width}-{height}:uia",
                        stable_id = $"window:{w}|role:{r}|text:{t}|rect:{x},{y},{width},{height}",
                        text, synonyms = synonyms.ToArray(), role, class_name = className, window,
                        rect = new { x, y, width, height }, area, small_icon = width <= 32 && height <= 32,
                        enabled, focusable, access_key = accessKey, tooltip = help, item_status = status,
                        sources = new[] { "uia" }, confidence, source_ids = new { uia = autoId }
                    });
                }
                catch { }
            }
        }
        catch { }
        return results.ToArray();
    }
    private static string Safe(Func<string> read) { try { return read() ?? ""; } catch { return ""; } }
    private static bool Safe(Func<bool> read, bool fallback) { try { return read(); } catch { return fallback; } }
}
