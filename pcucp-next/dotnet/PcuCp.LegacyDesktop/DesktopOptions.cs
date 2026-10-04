using System;
using System.Collections.Generic;
using System.Linq;

namespace PcuCp.LegacyDesktop
{
    internal sealed class DesktopOptions
    {
        private readonly IDictionary<string, object> values;
        internal static readonly HashSet<string> Integers = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        { "X", "Y", "ScreenshotX", "ScreenshotY", "ScreenshotW", "ScreenshotH", "MaxElements", "MinSize", "WindowHwnd",
          "TargetHwnd", "ClickInset", "ScanRadius", "ScanStep", "OcrMaxCandidates", "DiffThreshold" };
        internal static readonly HashSet<string> Switches = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        { "ClearFirst", "PressEnter", "SkipUia", "JsonOnly", "Quiet" };
        internal static readonly HashSet<string> Texts = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        { "Action", "Match", "Button", "Text", "Value", "Keys", "OutPath", "Label", "Role", "WindowTitle", "TargetMatch",
          "ClickRefine", "OcrLanguage", "OcrPath", "OcrText", "OcrMatch", "DiffBefore", "DiffAfter", "DiffIgnoreRegions" };
        internal string Action { get; }
        internal bool HasCoordinates => values.ContainsKey("X") && values.ContainsKey("Y");
        internal DesktopOptions(IDictionary<string, object> input)
        {
            if (input == null) throw new ArgumentException("Typed desktop options required.");
            var result = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase);
            foreach (var pair in input)
            {
                if (result.ContainsKey(pair.Key)) throw new ArgumentException("Duplicate desktop option.");
                if (Integers.Contains(pair.Key))
                {
                    if (!(pair.Value is int)) throw new ArgumentException("Desktop integer options must be Int32.");
                }
                else if (Switches.Contains(pair.Key))
                {
                    if (!(pair.Value is bool)) throw new ArgumentException("Desktop switches must be Boolean.");
                }
                else if (!Texts.Contains(pair.Key) || !(pair.Value is string) || ((string)pair.Value).Contains("\0"))
                    throw new ArgumentException("Unknown or invalid desktop option.");
                result.Add(pair.Key, pair.Value);
            }
            values = result;
            Action = Text("Action").ToLowerInvariant();
            if (!DesktopActions.Actions.Contains(Action)) throw new ArgumentException("Unknown desktop action.");
            if (!new[] { "left", "right", "middle", "double" }.Contains(Text("Button", "left"), StringComparer.OrdinalIgnoreCase) ||
                !new[] { "none", "uia-safe" }.Contains(Text("ClickRefine", "none"), StringComparer.OrdinalIgnoreCase))
                throw new ArgumentException("Invalid desktop button or refinement mode.");
        }
        internal string Text(string key, string fallback = "") => values.TryGetValue(key, out object value) ? (string)value : fallback;
        internal int Int(string key, int fallback = 0) => values.TryGetValue(key, out object value) ? (int)value : fallback;
        internal bool Flag(string key) => values.TryGetValue(key, out object value) && (bool)value;
    }
    internal sealed class DesktopReply
    {
        internal int Exit;
        internal IDictionary<string, object> Payload;
        internal static Dictionary<string, object> Map(params object[] pairs)
        { var result = new Dictionary<string, object>(); for (int i = 0; i < pairs.Length; i += 2) result.Add((string)pairs[i], pairs[i + 1]); return result; }
        internal static DesktopReply Of(int exit, params object[] pairs) => new DesktopReply { Exit = exit, Payload = Map(pairs) };
        internal static DesktopReply From(int exit, System.Collections.IDictionary source)
        { var result = Map(); foreach (System.Collections.DictionaryEntry pair in source) result.Add((string)pair.Key, pair.Value); return new DesktopReply { Exit = exit, Payload = result }; }
    }
}
