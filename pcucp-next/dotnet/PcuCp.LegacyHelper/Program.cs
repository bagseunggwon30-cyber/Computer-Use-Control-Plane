using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text;

namespace PcuCp.LegacyHelper
{
    internal static class Program
    {
        [STAThread]
        private static int Main(string[] args)
        {
            try
            {
                // Detached workers have no console codepage to set. Encode the
                // retained standard streams directly; preserve UTF-8 without BOM.
                // Do not suppress initialization errors or retry startup.
                Console.SetOut(new StreamWriter(Console.OpenStandardOutput(), new UTF8Encoding(false)) { AutoFlush = true });
                Console.SetError(new StreamWriter(Console.OpenStandardError(), new UTF8Encoding(false)) { AutoFlush = true });
                if (args.Length == 0) throw new ArgumentException("candidate mode required: serve or exchange");
                var options = Options(args);
                var phase = LegacyHelperDiagnostics.Create(options.ContainsKey("diagnostic-phases"), Console.Error.WriteLine);
                if (args[0] == "fixture")
                {
                    Only(options, "input-file");
                    var json = LegacyHelperService.NewJson();
                    var fixture = json.DeserializeObject(File.ReadAllText(Required(options, "input-file"), Encoding.UTF8)) as IDictionary<string, object>;
                    if (fixture == null) throw new ArgumentException("fixture object required");
                    Console.Out.WriteLine(json.Serialize(LegacyHelperFixtureRunner.Evaluate(fixture)));
                    return 0;
                }
                if (args[0] == "exchange" || args[0] == "exchange-direct")
                {
                    bool directExchange = args[0] == "exchange-direct";
                    Only(options, directExchange ? "pipe-name" : "pipe", "request-file", "connect-timeout-ms", "read-timeout-ms", "diagnostic-phases");
                    string target = directExchange ? LegacyHelperDirect.WindowsPipeName(Required(options, "pipe-name")) : null;
                    string request = LegacyHelperWire.ReadRequestFile(Required(options, "request-file"));
                    if (!directExchange) target = Required(options, "pipe"); // Preserve old malformed-input precedence.
                    var response = directExchange
                        ? LegacyHelperService.ExchangeDirect(target, request, Integer(options, "connect-timeout-ms", 2000), Integer(options, "read-timeout-ms", 30000), phase)
                        : LegacyHelperService.Exchange(target, request, Integer(options, "connect-timeout-ms", 2000), Integer(options, "read-timeout-ms", 30000), phase);
                    if (response == null) throw new IOException("pipe_empty_response");
                    Console.Out.Write(response + "\n");
                    return 0;
                }
                bool direct = args[0] == "serve-direct";
                if (args[0] != "serve" && !direct) throw new ArgumentException("unknown candidate mode");
                if (direct) Only(options, "pipe-name", "lock-file", "idle-timeout-ms", "allow-readonly-desktop", "fixture", "diagnostic-phases", "diagnostic-acl", "debug-log");
                else Only(options, "lock-file", "idle-timeout-ms", "allow-readonly-desktop", "fixture", "diagnostic-phases", "diagnostic-acl");
                string directName = direct ? LegacyHelperDirect.WindowsPipeName(Required(options, "pipe-name")) : null;
                string lockFile = direct ? Required(options, "lock-file") : Path.GetFullPath(Required(options, "lock-file"));
                if (!direct && !Directory.Exists(Path.GetDirectoryName(lockFile))) throw new DirectoryNotFoundException("candidate lock directory must exist");
                int pid = Process.GetCurrentProcess().Id;
                string pipe = direct ? directName : "cucp-helper-" + pid.ToString(CultureInfo.InvariantCulture);
                if (options.ContainsKey("fixture") && options.ContainsKey("allow-readonly-desktop")) throw new ArgumentException("fixture and desktop provider are mutually exclusive");
                ILegacyHelperProvider provider = options.ContainsKey("allow-readonly-desktop")
                    ? (ILegacyHelperProvider)new WindowsLegacyHelperProvider() : new DeniedDesktopProvider();
                ScriptedHelperProvider scripted = null;
                if (options.ContainsKey("fixture"))
                {
                    var fixture = LegacyHelperService.NewJson().DeserializeObject(File.ReadAllText(options["fixture"], Encoding.UTF8)) as IDictionary<string, object>;
                    if (fixture == null) throw new ArgumentException("fixture object required");
                    scripted = new ScriptedHelperProvider(LegacyHelperService.Field(fixture, "calls"));
                    provider = scripted;
                }
                Func<DateTime> clock = () => DateTime.UtcNow;
                var actions = new LegacyHelperActions(provider, pid, pipe, clock);
                int aclRecords = 0;
                Action<Dictionary<string, object>> aclEvidence = null;
                if (options.ContainsKey("diagnostic-acl")) aclEvidence = value => {
                    if (++aclRecords <= 16) Console.Error.WriteLine("helper_acl_evidence=" + LegacyHelperService.NewJson().Serialize(value));
                    else if (aclRecords == 17) Console.Error.WriteLine("helper_acl_evidence_limit=16");
                };
                var debug = direct && options.ContainsKey("debug-log") ? new LegacyHelperDebugLog(Console.Error.WriteLine) : null;
                Action<string> log = message => Console.Error.WriteLine(message);
                if (direct) log = message => { if (debug != null) debug.Event("pipe.error"); };
                int idle = Integer(options, "idle-timeout-ms", 60000);
                Func<string, LegacyHelperService> service = retainedPath => new LegacyHelperService(actions, pid, pipe, retainedPath,
                    idle, clock, log, phase, aclEvidence, debug);
                if (direct)
                {
                    // Use the path whose original/expanded ancestors are held by this lease.
                    using (var directory = new LegacyHelperDirectLockDirectory(lockFile)) service(directory.LockPath).Run();
                }
                else service(lockFile).Run();
                if (scripted != null) scripted.AssertExhausted();
                return 0;
            }
            catch (Exception exception)
            {
                Console.Error.WriteLine(exception.GetType().Name + ": " + exception.Message);
                return 1;
            }
        }
        private static Dictionary<string, string> Options(string[] args)
        {
            var result = new Dictionary<string, string>(StringComparer.Ordinal);
            for (int i = 1; i < args.Length; i++)
            {
                if (!args[i].StartsWith("--", StringComparison.Ordinal)) throw new ArgumentException("named candidate options required");
                string key = args[i].Substring(2);
                string value = key == "allow-readonly-desktop" || key == "diagnostic-phases" || (key == "debug-log" && args[0] == "serve-direct") || key == "diagnostic-acl" ? "true" : ++i < args.Length ? args[i] : null;
                if (value == null || result.ContainsKey(key)) throw new ArgumentException("missing or repeated candidate option");
                result.Add(key, value);
            }
            return result;
        }
        private static void Only(Dictionary<string, string> options, params string[] allowed)
        {
            foreach (string name in options.Keys) if (Array.IndexOf(allowed, name) < 0) throw new ArgumentException("unknown candidate option: " + name);
        }
        private static string Required(Dictionary<string, string> options, string key)
        {
            string value;
            if (!options.TryGetValue(key, out value) || String.IsNullOrEmpty(value)) throw new ArgumentException("missing candidate option: " + key);
            return value;
        }
        private static int Integer(Dictionary<string, string> options, string key, int fallback)
        {
            string value;
            int number;
            if (!options.TryGetValue(key, out value)) return fallback;
            if (!Int32.TryParse(value, NumberStyles.Integer, CultureInfo.InvariantCulture, out number) || number < 0)
                throw new ArgumentException("nonnegative integer required: " + key);
            return number;
        }
        private sealed class DeniedDesktopProvider : ILegacyHelperProvider
        {
            public object Invoke(string operation, params object[] arguments)
            {
                throw new InvalidOperationException("Desktop acquisition is disabled in this candidate invocation: " + operation);
            }
            public void EnumerateWindows(Action<long> visit) { throw new InvalidOperationException("Desktop acquisition is disabled"); }
        }
    }
}
