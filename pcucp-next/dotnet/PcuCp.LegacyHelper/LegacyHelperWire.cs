using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Threading.Tasks;

namespace PcuCp.LegacyHelper
{
    // Closed concrete adapter budget: at most 1 MiB per UTF-8 wire frame,
    // including its terminator. The connected I/O deadline covers BOTH write
    // and read, and is never refreshed by a partial/slow peer response.
    public static class LegacyHelperWire
    {
        public const int MaxFrameBytes = 1024 * 1024;
        private static readonly UTF8Encoding StrictUtf8 = new UTF8Encoding(false, true);

        public static byte[] RequestBytes(string request)
        {
            if (request == null) throw new ArgumentNullException(nameof(request));
            if (request.IndexOf('\r') >= 0 || request.IndexOf('\n') >= 0)
                throw new ArgumentException("one request frame required");
            int size = StrictUtf8.GetByteCount(request);
            if (size >= MaxFrameBytes) throw new IOException("pipe_request_too_large");
            byte[] result = new byte[size + 1];
            StrictUtf8.GetBytes(request, 0, request.Length, result, 0);
            result[size] = 10;
            return result;
        }

        // A fixture CLI may read only an owned request file, but must not first
        // allocate an arbitrary file into a string and check its size afterwards.
        public static string ReadRequestFile(string path)
        {
            using (var file = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read))
            {
                if (file.Length > MaxFrameBytes + 3L) throw new IOException("pipe_request_too_large");
                var bytes = new byte[MaxFrameBytes + 4];
                int length = 0, count;
                while (length < bytes.Length && (count = file.Read(bytes, length, bytes.Length - length)) != 0) length += count;
                if (length > MaxFrameBytes + 3) throw new IOException("pipe_request_too_large");
                int start = HasBom(bytes, length) ? 3 : 0;
                string request = StrictUtf8.GetString(bytes, start, length - start);
                if (request.EndsWith("\r\n", StringComparison.Ordinal)) request = request.Substring(0, request.Length - 2);
                else if (request.EndsWith("\n", StringComparison.Ordinal) || request.EndsWith("\r", StringComparison.Ordinal)) request = request.Substring(0, request.Length - 1);
                RequestBytes(request); // Validate actual canonical wire size before connect.
                return request;
            }
        }

        public static string ExchangeConnected(Stream stream, byte[] request, int timeoutMs)
        {
            if (timeoutMs <= 0) throw new ArgumentOutOfRangeException(nameof(timeoutMs));
            if (request == null || request.Length > MaxFrameBytes) throw new IOException("pipe_request_too_large");
            var elapsed = Stopwatch.StartNew();
            Wait(stream.WriteAsync(request, 0, request.Length), stream, elapsed, timeoutMs, "pipe_write_timeout");
            var chunk = new byte[4096];
            using (var frame = new MemoryStream())
            {
                while (true)
                {
                    // Read at most one overflow byte; never accumulate an unbounded line.
                    int wanted = Math.Min(chunk.Length, MaxFrameBytes + 1 - (int)frame.Length);
                    var read = stream.ReadAsync(chunk, 0, wanted);
                    Wait(read, stream, elapsed, timeoutMs, "pipe_read_timeout");
                    int count = read.GetAwaiter().GetResult();
                    if (count == 0) return frame.Length == 0 ? null : Decode(frame.ToArray());
                    for (int i = 0; i < count; i++)
                    {
                        if (frame.Length + 1 > MaxFrameBytes) throw new IOException("pipe_response_too_large");
                        byte value = chunk[i];
                        // Preserve StreamReader.ReadLine's CR/LF/CRLF first-line behavior.
                        if (value == 10 || value == 13) return Decode(frame.ToArray());
                        frame.WriteByte(value);
                        if (frame.Length >= MaxFrameBytes) throw new IOException("pipe_response_too_large");
                    }
                }
            }
        }

        private static string Decode(byte[] frame)
        {
            int start = HasBom(frame, frame.Length) ? 3 : 0;
            return StrictUtf8.GetString(frame, start, frame.Length - start);
        }
        private static bool HasBom(byte[] data, int count)
        { return count >= 3 && data[0] == 0xef && data[1] == 0xbb && data[2] == 0xbf; }
        private static void Wait(Task operation, Stream stream, Stopwatch elapsed, int timeoutMs, string reason)
        {
            int remaining = timeoutMs - checked((int)Math.Min(Int32.MaxValue, elapsed.ElapsedMilliseconds));
            bool complete = false;
            try { if (remaining > 0) complete = operation.Wait(remaining); }
            catch (AggregateException) { operation.GetAwaiter().GetResult(); throw; }
            if (!complete)
            {
                // Observe a later cancellation/fault; never await cleanup indefinitely.
                operation.ContinueWith(task => { var ignored = task.Exception; }, TaskContinuationOptions.OnlyOnFaulted | TaskContinuationOptions.ExecuteSynchronously);
                stream.Dispose(); // This is the retained concrete connection, never another process/peer.
                throw new TimeoutException(reason);
            }
            operation.GetAwaiter().GetResult();
        }
    }
}
