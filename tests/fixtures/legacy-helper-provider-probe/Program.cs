// Test-only executable. No production route references this project.
using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Imaging;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Web.Script.Serialization;
using System.Windows.Automation;
using PcuCp.LegacyHelper;

internal static class Program
{
    private static readonly JavaScriptSerializer Json = new JavaScriptSerializer { MaxJsonLength = 8 * 1024 * 1024, RecursionLimit = 64 };
    internal static Dictionary<string, object> Map(params object[] values) { return LegacyHelperActions.Map(values); }
    private static IDictionary<string, object> ready;
    private static Provider provider;
    private static LegacyHelperActions actions;
    private static string title;
    private static int integer(object value) { return Convert.ToInt32(value, CultureInfo.InvariantCulture); }
    [STAThread] private static int Main(string[] args)
    {
        try
        {
            Console.SetOut(new StreamWriter(Console.OpenStandardOutput(), new UTF8Encoding(false)) { AutoFlush = true });
            if (Environment.OSVersion.Platform != PlatformID.Win32NT || args.Length != 3 || !new[] { "native", "uia", "ocr-file", "ocr-owned", "ocr-fallback", "ocr-retry" }.Contains(args[0]))
                throw new ArgumentException("Windows fixed owned-fixture group, readiness path and owned process ID required");
            ready = Json.DeserializeObject(File.ReadAllText(args[1], Encoding.UTF8)) as IDictionary<string, object>;
            if (ready == null || !(bool)ready["helper_provider"] || !(bool)ready["desktop_interactive"] || integer(ready["pid"]) != int.Parse(args[2], CultureInfo.InvariantCulture)) throw new InvalidOperationException("Owned readiness mismatch");
            title = (string)ready["title"];
            provider = new Provider(ready, Path.GetDirectoryName(Path.GetFullPath(args[1])), args[0]);
            actions = new LegacyHelperActions(provider, Process.GetCurrentProcess().Id, "owned-provider-probe", () => DateTime.UtcNow);
            switch (args[0])
            {
                case "native":
                    Run("health-cold", "health");
                    Run("windows-owned", "windows", Map("Match", title));
                    Run("windows-empty", "windows", Map("Match", title + " absent"));
                    Run("focused", "focused");
                    Run("modal", "modal-detect");
                    Run("unsupported", "not-a-supported-action");
                    Run("health-warm", "health");
                    break;
                case "uia":
                    Run("uia-missing", "uia-find-fast");
                    Run("uia-run", "uia-find-fast", Map("Match", title, "Label", "Run 한글"));
                    Run("uia-edit", "uia-find-fast", Map("Match", title, "Label", "Fixture value"));
                    Run("uia-disabled", "uia-find-fast", Map("Match", title, "Label", "Disabled"));
                    Run("uia-duplicate", "uia-find-fast", Map("Match", title, "Label", "Duplicate"));
                    Run("uia-cap", "uia-find-fast", Map("Match", title, "Label", "Cap target"));
                    Run("uia-scan-bound", "uia-find-fast", Map("Match", title, "Label", "Beyond scan"));
                    Run("uia-no-match", "uia-find-fast", Map("Match", title, "Label", title + " missing label"));
                    Run("uia-root-fallback", "uia-find-fast", Map("Match", title + " absent", "Label", title + " missing label"));
                    Run("uia-run-reused", "uia-find-fast", Map("Match", title, "Label", "Run 한글"));
                    Run("health-uia", "health");
                    break;
                case "ocr-file":
                    provider.ImageMode = "text"; Run("ocr-file-text", "ocr-screen-fast", Region());
                    provider.ImageMode = "blank"; Run("ocr-file-blank", "ocr-screen-fast", Region());
                    Run("ocr-file-defaults", "ocr-screen-fast", Map("X", 0, "Y", 0, "W", 0, "H", 0));
                    provider.ImageMode = "corrupt"; Run("ocr-file-corrupt", "ocr-screen-fast", Region());
                    provider.ImageMode = "text"; Run("ocr-file-reused", "ocr-screen-fast", Region());
                    Run("ocr-oversize", "ocr-screen-fast", Map("W", int.MaxValue, "H", 1));
                    provider.ImageMode = null; Run("ocr-invalid-size", "ocr-screen-fast", Map("W", -1, "H", 1));
                    break;
                case "ocr-owned":
                    Run("ocr-owned-text", "ocr-screen-fast", Region());
                    Run("ocr-owned-reused", "ocr-screen-fast", Region());
                    break;
                case "ocr-fallback":
                    provider.ImageMode = "text"; provider.EngineMode = "profile-null";
                    Run("ocr-language-fallback", "ocr-screen-fast", Region());
                    Run("ocr-language-reused", "ocr-screen-fast", Region());
                    break;
                case "ocr-retry":
                    provider.ImageMode = "text"; provider.EngineMode = "no-language";
                    Run("ocr-no-language", "ocr-screen-fast", Region());
                    provider.EngineMode = null;
                    Run("ocr-init-retry", "ocr-screen-fast", Region());
                    break;
            }
            return 0;
        }
        catch (Exception error) { Console.Error.WriteLine(error); return 1; }
    }
    private static Dictionary<string, object> Region()
    {
        var r = (IDictionary<string, object>)ready["ocr"];
        return Map("X", r["x"], "Y", r["y"], "W", r["width"], "H", r["height"]);
    }
    private static void Run(string name, string action, Dictionary<string, object> arguments = null)
    {
        provider.Calls.Clear(); provider.Diagnostics.Clear();
        object result = null, error = null;
        try { result = actions.Dispatch(action, arguments); }
        catch (Exception exception) { error = Map("type", exception.GetType().FullName, "detail", exception.ToString()); }
        Console.WriteLine(Json.Serialize(Map("schema", "cucp.helper-provider-case/v1", "name", name, "pid", Process.GetCurrentProcess().Id, "action", action, "args", arguments,
            "result", result, "error", error, "calls", provider.Calls, "diagnostics", provider.Diagnostics,
            "state", Map("request_count", actions.RequestCount, "win32_loaded", actions.Win32Loaded, "uia_loaded", actions.UiaLoaded, "ocr_warm", actions.OcrWarm))));
    }
    private sealed class Provider : ILegacyHelperProvider
    {
        private readonly WindowsLegacyHelperProvider real = new WindowsLegacyHelperProvider();
        private readonly IDictionary<string, object> owned;
        private readonly string evidenceDirectory, group;
        private int imageCount;
        private readonly Dictionary<object, int> identities = new Dictionary<object, int>(new IdentityComparer());
        internal readonly List<object> Calls = new List<object>(), Diagnostics = new List<object>();
        internal string ImageMode, EngineMode;
        internal Provider(IDictionary<string, object> fixture, string directory, string caseGroup) { owned = fixture; evidenceDirectory = directory; group = caseGroup; VerifyOwner(); }
        private void VerifyOwner()
        {
            uint pid; var hwnd = new IntPtr(Convert.ToInt64(owned["hwnd"]));
            GetWindowThreadProcessId(hwnd, out pid);
            var name = new StringBuilder(512); GetWindowText(hwnd, name, name.Capacity);
            if (pid != integer(owned["pid"]) || !IsWindowVisible(hwnd) || IsIconic(hwnd) || name.ToString() != (string)owned["title"])
                throw new InvalidOperationException("Owned fixture HWND/PID/title/visibility changed");
        }
        public object Invoke(string operation, params object[] arguments)
        {
            if (Calls.Count >= 12000) throw new LegacyHelperFixtureException("Provider evidence limit exceeded");
            var record = Map("operation", operation, "arguments", arguments.Select(Snapshot).ToArray(), "source", "actual-provider"); Calls.Add(record);
            try
            {
                object result;
                if (operation == "ocr.capture")
                {
                    VerifyTemp((string)arguments[4]);
                    if (ImageMode != null)
                    {
                        record["source"] = "generated-owned-image";
                        Generate((string)arguments[4], ImageMode, integer(arguments[2]), integer(arguments[3])); result = null;
                    }
                    else
                    {
                        // Negative dimensions throw in Bitmap before CopyFromScreen.
                        if (integer(arguments[2]) > 0 && integer(arguments[3]) > 0) VerifyPixels(arguments);
                        result = real.Invoke(operation, arguments);
                        if (integer(arguments[2]) > 0 && integer(arguments[3]) > 0) VerifyPixels(arguments);
                    }
                    var bytes = File.ReadAllBytes((string)arguments[4]);
                    if (bytes.Length > 2 * 1024 * 1024) throw new LegacyHelperFixtureException("Owned image evidence limit exceeded");
                    string artifact = Path.Combine(evidenceDirectory, group + "-image-" + (++imageCount) + (ImageMode == "corrupt" ? ".bin" : ".png"));
                    using (var file = new FileStream(artifact, FileMode.CreateNew)) file.Write(bytes, 0, bytes.Length);
                    using (var sha = SHA256.Create()) record["image_sha256"] = BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-", "").ToLowerInvariant();
                    record["image_bytes"] = bytes.Length; record["image_artifact"] = artifact;
                }
                else result = real.Invoke(operation, arguments);
                record["actual_result"] = Snapshot(result);
                if (operation == "ocr.createProfile" && EngineMode != null)
                { record["source"] = "actual-provider-plus-explicit-profile-null-seam"; result = null; }
                if (operation == "ocr.languages" && EngineMode == "no-language")
                { record["source"] = "actual-provider-plus-explicit-empty-languages-seam"; result = new object[0]; }
                record["result"] = Snapshot(result);
                if (operation == "ocr.tempPath") VerifyTemp((string)result);
                if (operation == "ocr.removeTemp") record["remaining_file"] = File.Exists((string)arguments[0]);
                // Independent, read-only acquisition metadata is labeled separately.
                // No identity/name/role/geometry is repaired or normalized.
                if (operation == "uia.subtree") foreach (var element in ((IEnumerable)result).Cast<AutomationElement>())
                {
                    try
                    {
                        var current = element.Current; var bounds = current.BoundingRectangle;
                        Diagnostics.Add(Map("element", Snapshot(element), "name", current.Name, "control_type", current.LocalizedControlType,
                            "hwnd", current.NativeWindowHandle, "pid", current.ProcessId,
                            "rect", Map("x", bounds.X, "y", bounds.Y, "w", bounds.Width, "h", bounds.Height)));
                    }
                    catch (Exception error)
                    {
                        // A side diagnostic cannot change the actual return value.
                        // Its incomplete schema independently fails qualification.
                        Diagnostics.Add(Map("element", Snapshot(element), "diagnostic_error", error.ToString()));
                    }
                }
                return result;
            }
            catch (Exception error) { record["error"] = Map("type", error.GetType().FullName, "detail", error.ToString()); throw; }
        }
        public void EnumerateWindows(Action<long> visit)
        {
            var handles = new List<long>(); var record = Map("operation", "win32.enumerate", "arguments", new object[0], "source", "actual-provider", "handles", handles); Calls.Add(record);
            real.EnumerateWindows(hwnd => { if (handles.Count >= 4096) throw new LegacyHelperFixtureException("Window evidence limit exceeded"); handles.Add(hwnd); visit(hwnd); });
        }
        private object Snapshot(object value)
        {
            if (value == null || value is string || value.GetType().IsPrimitive || value is decimal) return value;
            var map = value as IDictionary<string, object>;
            if (map != null) return map.ToDictionary(pair => pair.Key, pair => Snapshot(pair.Value));
            var elements = value as IEnumerable;
            if (elements != null)
            {
                var items = elements.Cast<object>().Take(4097).ToArray();
                if (items.Length > 4096) throw new LegacyHelperFixtureException("Provider collection evidence limit exceeded");
                return items.Select(Snapshot).ToArray();
            }
            int id; if (!identities.TryGetValue(value, out id)) { id = identities.Count + 1; identities.Add(value, id); }
            return Map("object_id", id, "type", value.GetType().FullName);
        }
        private static void VerifyTemp(string path)
        {
            if (Path.GetDirectoryName(Path.GetFullPath(path)) != Path.GetFullPath(Path.GetTempPath()).TrimEnd(Path.DirectorySeparatorChar)
                || !System.Text.RegularExpressions.Regex.IsMatch(Path.GetFileName(path), "^cucp-srv-ocr-[a-f0-9]{32}\\.png$"))
                throw new LegacyHelperFixtureException("OCR escaped owned TEMP directory");
        }
        private void VerifyPixels(object[] args)
        {
            VerifyOwner(); var region = (IDictionary<string, object>)owned["ocr"];
            int x = integer(args[0]), y = integer(args[1]), width = integer(args[2]), height = integer(args[3]);
            if (x != integer(region["x"]) || y != integer(region["y"]) || width != integer(region["width"]) || height != integer(region["height"]) || width * (long)height > 50000)
                throw new LegacyHelperFixtureException("Only exact bounded owned OCR rectangle may be captured");
            var hwnd = new IntPtr(Convert.ToInt64(owned["hwnd"]));
            for (int row = y; row < y + height; row++) for (int col = x; col < x + width; col++)
                if (GetAncestor(WindowFromPoint(new Point(col, row)), 2) != hwnd) throw new LegacyHelperFixtureException("Owned OCR rectangle is occluded; capture refused");
        }
        private static void Generate(string path, string mode, int width, int height)
        {
            if (!((width == 560 && height == 70) || (width == 800 && height == 600))) throw new LegacyHelperFixtureException("Generated image dimensions changed");
            if (mode == "corrupt") { File.WriteAllBytes(path, Encoding.ASCII.GetBytes("owned invalid PNG")); return; }
            using (var image = new Bitmap(width, height)) using (var graphics = Graphics.FromImage(image)) using (var font = new Font("Arial", 36, FontStyle.Bold))
            {
                graphics.Clear(Color.White);
                if (mode == "text") graphics.DrawString("HELLO 2468", font, Brushes.Black, new RectangleF(0, 0, width, height), new StringFormat { Alignment = StringAlignment.Center, LineAlignment = StringAlignment.Center });
                image.Save(path, ImageFormat.Png);
            }
        }
        private sealed class IdentityComparer : IEqualityComparer<object>
        { public new bool Equals(object x, object y) { return ReferenceEquals(x, y); } public int GetHashCode(object x) { return RuntimeHelpers.GetHashCode(x); } }
        [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint pid);
        [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern int GetWindowText(IntPtr hwnd, StringBuilder text, int count);
        [DllImport("user32.dll")] private static extern bool IsWindowVisible(IntPtr hwnd);
        [DllImport("user32.dll")] private static extern bool IsIconic(IntPtr hwnd);
        [DllImport("user32.dll")] private static extern IntPtr WindowFromPoint(Point point);
        [DllImport("user32.dll")] private static extern IntPtr GetAncestor(IntPtr hwnd, uint flags);
    }
}
