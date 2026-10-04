using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Threading;

namespace PcuCp.LegacyHelper
{
    // No bytes are sent until a request has been consumed. In particular, do
    // not eagerly flush a UTF-8 preamble onto a duplex pipe before reading:
    // writes can wait for the other endpoint's first read. Requested pipe buffer
    // sizes are advisory, so the Windows fixture records their actual values.
    public sealed class LegacyHelperResponseWriter
    {
        private readonly Stream stream;
        private bool first = true;
        public LegacyHelperResponseWriter(Stream stream) { this.stream = stream; }
        public void WriteLine(string response)
        {
            // Preserve the legacy response BOM once per connection and CRLF.
            // One write also avoids a standalone preamble handshake. No Dispose
            // hook can emit or flush bytes after an interrupted response.
            byte[] bytes = Encoding.UTF8.GetBytes((first ? "\ufeff" : "") + response + "\r\n");
            first = false;
            stream.Write(bytes, 0, bytes.Length);
        }
    }

    public static class LegacyHelperDiagnostics
    {
        public const int MaxEvents = 128;
        public static Action<string> Create(bool enabled, Action<string> write)
        {
            if (!enabled) return _ => { };
            var clock = Stopwatch.StartNew();
            int count = 0;
            return phase =>
            {
                if (Volatile.Read(ref count) > MaxEvents) return;
                int index = Interlocked.Increment(ref count);
                if (index <= MaxEvents)
                    write("helper_phase=" + phase + " elapsed_ms=" + clock.ElapsedMilliseconds);
                else if (index == MaxEvents + 1) write("helper_phase=limit");
            };
        }
    }
}
