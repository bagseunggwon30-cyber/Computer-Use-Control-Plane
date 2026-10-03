using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Pipes;
using System.Text;
using System.Threading;
using PcuCp.LegacyHelper;

// Disposable hostile wire peer, never a desktop provider or discovered service.
internal static class OwnedPipePeer
{
    public static int Run(string path)
    {
        var json = LegacyHelperService.NewJson();
        var spec = (IDictionary<string, object>)json.DeserializeObject(File.ReadAllText(path, Encoding.UTF8));
        string mode = Convert.ToString(spec["mode"]), ready = Convert.ToString(spec["ready"]);
        string name = "cucp-helper-" + Process.GetCurrentProcess().Id;
        if (Array.IndexOf(new[] { "stall-read", "stall-write", "oversized", "unicode-split", "exact-boundary", "unterminated", "invalid-utf8", "slow-drip", "absent" }, mode) < 0)
            throw new ArgumentException("unknown owned peer mode");
        if (mode == "absent")
        {
            File.WriteAllText(ready, json.Serialize(new { pipe_name = name }), new UTF8Encoding(false));
            Thread.Sleep(1800);
            return 0;
        }
        using (var pipe = new NamedPipeServerStream(name, PipeDirection.InOut, 1, PipeTransmissionMode.Byte, PipeOptions.Asynchronous, 512, 512))
        {
            File.WriteAllText(ready, json.Serialize(new { pipe_name = name }), new UTF8Encoding(false));
            var connect = pipe.WaitForConnectionAsync();
            if (!connect.Wait(1800))
            {
                pipe.Dispose();
                try { connect.GetAwaiter().GetResult(); } catch (IOException) { } catch (OperationCanceledException) { } catch (ObjectDisposedException) { }
                return 0;
            }
            connect.GetAwaiter().GetResult();
            Console.Out.WriteLine("peer_connected");
            if (mode == "stall-read") { Thread.Sleep(1500); return 0; }
            using (var reader = new StreamReader(pipe, Encoding.UTF8, true, 1024, true))
            {
                reader.ReadLine();
                Console.Out.WriteLine("peer_read_one_request");
            }
            if (mode == "stall-write") { Thread.Sleep(1500); return 0; }
            byte[] response;
            if (mode == "unicode-split") response = Encoding.UTF8.GetBytes("\ufeff한글😀\r\n");
            else if (mode == "exact-boundary") response = Encoding.UTF8.GetBytes(new string('x', LegacyHelperWire.MaxFrameBytes - 1) + "\n");
            else if (mode == "oversized") response = Encoding.UTF8.GetBytes(new string('x', LegacyHelperWire.MaxFrameBytes + 1024));
            else if (mode == "invalid-utf8") response = new byte[] { 0xff, 10 };
            else if (mode == "slow-drip") response = Encoding.UTF8.GetBytes(new string('x', 20));
            else response = Encoding.UTF8.GetBytes("tail without newline");
            try
            {
                if (mode == "unicode-split" || mode == "slow-drip")
                {
                    foreach (byte value in response)
                    {
                        pipe.WriteByte(value);
                        Thread.Sleep(mode == "slow-drip" ? 75 : 1);
                    }
                }
                else pipe.Write(response, 0, response.Length);
            }
            catch (IOException) { Console.Out.WriteLine("peer_observed_client_close"); }
        }
        return 0;
    }
}
