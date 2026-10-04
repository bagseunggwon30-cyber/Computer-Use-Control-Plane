using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;

namespace PcuCp.LegacyDesktop
{
    internal static class Program
    {
        private static StreamReader Input;
        private static readonly JavaScriptSerializer Json = new JavaScriptSerializer { MaxJsonLength = 32 * 1024 * 1024, RecursionLimit = 100 };
        [DllImport("kernel32.dll", SetLastError = true)] private static extern uint WaitForSingleObject(IntPtr handle, uint milliseconds);
        [DllImport("kernel32.dll", SetLastError = true)] private static extern bool CloseHandle(IntPtr handle);
        [STAThread]
        private static int Main(string[] args)
        {
            Console.SetOut(new StreamWriter(Console.OpenStandardOutput(), new UTF8Encoding(false)) { AutoFlush = true });
            Console.SetError(new StreamWriter(Console.OpenStandardError(), new UTF8Encoding(false)) { AutoFlush = true });
            try
            {
                bool live = false, validate = false;
                IntPtr parent = IntPtr.Zero;
                foreach (string argument in args)
                    if (argument == "--allow-live-control") { if (live) throw new ArgumentException("Duplicate authority flag."); live = true; }
                for (int i = 0; i < args.Length; i++)
                {
                    if (args[i] == "--allow-live-control") continue;
                    if (args[i] == "--validate-only") { if (validate) throw new ArgumentException("Duplicate validation flag."); validate = true; continue; }
                    if (args[i] != "--parent-handle" || parent != IntPtr.Zero || ++i >= args.Length ||
                        !long.TryParse(args[i], out long value) || value <= 0)
                        throw new ArgumentException("Unknown startup option or invalid parent handle.");
                    parent = new IntPtr(value);
                }
                if (parent != IntPtr.Zero)
                {
                    if (WaitForSingleObject(parent, 0) != 258) throw new InvalidOperationException("Parent guard failed before dispatch.");
                    var ownedHandle = parent;
                    new Thread(() => { WaitForSingleObject(ownedHandle, uint.MaxValue); CloseHandle(ownedHandle); Environment.Exit(125); })
                    { IsBackground = true, Name = "legacy-desktop-parent" }.Start();
                }
                Input = new StreamReader(Console.OpenStandardInput(), new UTF8Encoding(false, true), false);
                var request = ParseObject(ReadLine());
                if (request == null || request.Count != 2 || !request.ContainsKey("schema") || !request.ContainsKey("options") ||
                    !Equals(request["schema"], "cucp.legacy-desktop-request/v1")) throw new ArgumentException("Invalid desktop request.");
                var options = new DesktopOptions(request["options"] as IDictionary<string, object>);
                if (validate)
                {
                    Console.WriteLine(Json.Serialize(new { schema = "cucp.legacy-desktop-validation/v1", action = options.Action,
                        live = DesktopActions.IsLive(options.Action), has_coordinates = options.HasCoordinates }));
                    return 0;
                }
                var elapsed = Stopwatch.StartNew();
                DesktopReply reply;
                if (DesktopActions.IsLive(options.Action) && !live)
                    reply = DesktopReply.Of(3, "status", "blocked", "reason", "live_control_not_authorized");
                else reply = new DesktopActions(options).Run();
                if (!reply.Payload.ContainsKey("action")) reply.Payload["action"] = options.Action;
                if (!reply.Payload.ContainsKey("elapsed_ms")) reply.Payload["elapsed_ms"] = Convert.ToInt32(elapsed.Elapsed.TotalMilliseconds);
                Console.WriteLine(Json.Serialize(Normalize(reply.Payload)));
                return reply.Exit;
            }
            catch (Exception exception)
            {
                Console.Error.WriteLine(exception.GetType().Name + ": " + exception.Message);
                return 1;
            }
        }
        private static string ReadLine()
        {
            var characters = new StringBuilder(); int next;
            while ((next = Input.Read()) >= 0 && next != '\n')
            {
                if (characters.Length >= 32 * 1024 * 1024) throw new ArgumentException("Desktop frame exceeds its bounded budget.");
                characters.Append((char)next);
            }
            if (characters.Length == 0) throw new IOException("Desktop owner closed before its next typed frame.");
            return characters.ToString().TrimEnd('\r');
        }
        private static IDictionary<string, object> ParseObject(string source)
        {
            // Validate uniqueness before JavaScriptSerializer's dictionary
            // materialization; an escaped duplicate name must not overwrite.
            var objects = new Stack<HashSet<string>>();
            for (int i = 0; i < source.Length; i++)
            {
                char value = source[i];
                if (value == '{' || value == '[') { if (objects.Count >= 100) throw new ArgumentException("Desktop JSON nesting exceeds 100."); objects.Push(value == '{' ? new HashSet<string>(StringComparer.Ordinal) : null); }
                else if (value == '}' || value == ']') { if (objects.Count == 0) throw new ArgumentException("Invalid desktop JSON nesting."); objects.Pop(); }
                else if (value == '"')
                {
                    int first = i++; bool ended = false;
                    for (; i < source.Length; i++) { if (source[i] == '\\') i++; else if (source[i] == '"') { ended = true; break; } }
                    if (!ended) throw new ArgumentException("Unterminated desktop JSON string.");
                    int next = i + 1; while (next < source.Length && char.IsWhiteSpace(source[next])) next++;
                    if (next < source.Length && source[next] == ':' && objects.Count != 0 && objects.Peek() != null)
                    {
                        string name = Json.Deserialize<string>(source.Substring(first, i - first + 1));
                        if (!objects.Peek().Add(name)) throw new ArgumentException("Duplicate desktop JSON property.");
                    }
                }
            }
            return Json.DeserializeObject(source) as IDictionary<string, object>;
        }
        internal static IList<IDictionary<string, object>> MatchOcr(IDictionary body, string needle, string mode)
        {
            Console.WriteLine(Json.Serialize(Normalize(DesktopReply.Map("schema", "cucp.legacy-desktop-effect/v1",
                "operation", "ocr-match", "body", body, "needle", needle, "mode", mode))));
            var reply = ParseObject(ReadLine());
            if (reply == null || reply.Count != 2 || !reply.ContainsKey("schema") || !Equals(reply["schema"], "cucp.legacy-desktop-reply/v1"))
                throw new ArgumentException("Invalid owned OCR reply.");
            if (reply.TryGetValue("error", out object error)) throw new InvalidOperationException(Convert.ToString(error));
            if (!reply.TryGetValue("candidates", out object source) || !(source is object[] rows) || rows.Length > 10000)
                throw new ArgumentException("Invalid owned OCR candidates.");
            return rows.Select(row => row as IDictionary<string, object> ?? throw new ArgumentException("OCR candidate must be an object.")).ToList();
        }
        private static object Normalize(object value)
        {
            if (value is IDictionary dictionary)
            {
                var result = new Dictionary<string, object>();
                foreach (DictionaryEntry item in dictionary) result.Add((string)item.Key, Normalize(item.Value));
                return result;
            }
            if (value is IEnumerable enumerable && !(value is string)) return enumerable.Cast<object>().Select(Normalize).ToArray();
            return value;
        }
    }
}
