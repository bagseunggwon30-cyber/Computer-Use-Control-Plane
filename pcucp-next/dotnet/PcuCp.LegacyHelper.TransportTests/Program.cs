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
            if (args.Length == 2 && args[0] == "handshake-server") return OwnedHandshakeProbe.RunServer(args[1]);
            if (args.Length == 2 && args[0] == "handshake-client") return OwnedHandshakeProbe.RunClient(args[1]);
            var phase = LegacyHelperDiagnostics.Create(true, Console.Error.WriteLine);
            if (args.Length != 1) throw new ArgumentException("owned fixture JSON path required");
            var json = LegacyHelperService.NewJson();
            var spec = (IDictionary<string, object>)json.DeserializeObject(File.ReadAllText(args[0], Encoding.UTF8));
            string name = Convert.ToString(spec["pipe"]);
            if (!System.Text.RegularExpressions.Regex.IsMatch(name, "^cucp-helper-[0-9]+$")) throw new ArgumentException("invalid owned pipe");
            int timeout = spec.ContainsKey("read_timeout_ms") ? Convert.ToInt32(spec["read_timeout_ms"]) : 3000;
            var results = new List<object>();
            using (var pipe = new NamedPipeClientStream(".", name, PipeDirection.InOut, PipeOptions.Asynchronous))
            {
                phase("probe.connect.start");
                pipe.Connect(3000);
                phase("probe.connect.complete");
                using (var reader = new StreamReader(pipe, Encoding.UTF8, true, 1024, true))
                {
                    bool first = true;
                    if (spec.ContainsKey("hold_ms")) Thread.Sleep(Convert.ToInt32(spec["hold_ms"]));
                    foreach (object frame in (IEnumerable)spec["frames"])
                    {
                        // Keep the fixture's legacy request BOM/CRLF, but put it
                        // in the first frame instead of a blocking constructor.
                        byte[] bytes = Encoding.UTF8.GetBytes((first ? "\ufeff" : "") + Convert.ToString(frame) + "\r\n");
                        first = false;
                        phase("probe.write.start");
                        var write = pipe.WriteAsync(bytes, 0, bytes.Length);
                        if (!write.Wait(timeout))
                        {
                            write.ContinueWith(pendingWrite => { var ignored = pendingWrite.Exception; }, System.Threading.Tasks.TaskContinuationOptions.OnlyOnFaulted);
                            pipe.Dispose();
                            throw new TimeoutException("owned_fixture_write_timeout");
                        }
                        write.GetAwaiter().GetResult();
                        phase("probe.write.complete");
                        if (spec.ContainsKey("disconnect") && (bool)spec["disconnect"]) break;
                        var task = reader.ReadLineAsync();
                        phase("probe.read.start");
                        if (!task.Wait(timeout))
                        {
                            task.ContinueWith(pending => { var ignored = pending.Exception; }, System.Threading.Tasks.TaskContinuationOptions.OnlyOnFaulted);
                            pipe.Dispose();
                            throw new TimeoutException("owned_fixture_read_timeout");
                        }
                        phase("probe.read.complete");
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
