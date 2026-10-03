using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.IO.Pipes;
using System.Text;
using System.Threading;
using PcuCp.LegacyHelper;

internal static class Program
{
    private static int Main(string[] args)
    {
        Console.OutputEncoding = new UTF8Encoding(false);
        try
        {
            if (args.Length == 2 && args[0] == "peer") return OwnedPipePeer.Run(args[1]);
            if (args.Length != 1) throw new ArgumentException("owned fixture JSON path required");
            var json = LegacyHelperService.NewJson();
            var spec = (IDictionary<string, object>)json.DeserializeObject(File.ReadAllText(args[0], Encoding.UTF8));
            string name = Convert.ToString(spec["pipe"]);
            if (!System.Text.RegularExpressions.Regex.IsMatch(name, "^cucp-helper-[0-9]+$")) throw new ArgumentException("invalid owned pipe");
            int timeout = spec.ContainsKey("read_timeout_ms") ? Convert.ToInt32(spec["read_timeout_ms"]) : 3000;
            var results = new List<object>();
            using (var pipe = new NamedPipeClientStream(".", name, PipeDirection.InOut, PipeOptions.Asynchronous))
            {
                pipe.Connect(3000);
                using (var reader = new StreamReader(pipe, Encoding.UTF8, true, 1024, true))
                using (var writer = new StreamWriter(pipe, Encoding.UTF8, 1024, true) { AutoFlush = true })
                {
                    if (spec.ContainsKey("hold_ms")) Thread.Sleep(Convert.ToInt32(spec["hold_ms"]));
                    foreach (object frame in (IEnumerable)spec["frames"])
                    {
                        writer.WriteLine(Convert.ToString(frame));
                        if (spec.ContainsKey("disconnect") && (bool)spec["disconnect"]) break;
                        var task = reader.ReadLineAsync();
                        if (!task.Wait(timeout))
                        {
                            results.Add(new Dictionary<string, object> { ["response"] = null, ["error"] = "owned_fixture_read_timeout" });
                            break;
                        }
                        results.Add(new Dictionary<string, object> { ["response"] = task.Result, ["error"] = null });
                    }
                }
            }
            Console.Out.WriteLine(json.Serialize(results));
            return 0;
        }
        catch (Exception e) { Console.Error.WriteLine(e.ToString()); return 1; }
    }
}
