using System;
using System.IO;
using System.Diagnostics;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using PcuCp.LegacyHelper;

internal static class WireContractChecks
{
    private static int checks;
    private static void Check(bool value, string name) { checks++; if (!value) throw new Exception("Wire contract failed: " + name); }
    private static void Reject<T>(Action action, string name) where T : Exception
    { try { action(); } catch (T) { checks++; return; } throw new Exception("Expected " + typeof(T).Name + ": " + name); }
    public static void Run()
    {
        int max = LegacyHelperWire.MaxFrameBytes;
        Check(LegacyHelperWire.RequestBytes(new string('x', max - 1)).Length == max, "exact outbound bytes");
        Reject<IOException>(() => LegacyHelperWire.RequestBytes(new string('x', max)), "request overflow");
        Check(LegacyHelperWire.RequestBytes(new string('한', (max - 1) / 3)).Length == max, "UTF8 byte count not character count");
        Reject<IOException>(() => LegacyHelperWire.RequestBytes(new string('한', (max - 1) / 3) + "x"), "UTF8 overflow");
        Reject<ArgumentException>(() => LegacyHelperWire.RequestBytes("{}\n{}"), "multiple requests");
        Reject<EncoderFallbackException>(() => LegacyHelperWire.RequestBytes("\ud800"), "malformed outgoing UTF16");
        foreach (string text in new[] { "한글😀\n", "한글😀\r", "한글😀\r\n", "한글😀" })
        {
            using (var stream = new FixtureStream(Encoding.UTF8.GetBytes("\ufeff" + text), 1))
                Check(LegacyHelperWire.ExchangeConnected(stream, LegacyHelperWire.RequestBytes("{}"), 1000) == "한글😀", "split Unicode/BOM/terminator");
        }
        using (var stream = new FixtureStream(new byte[0], 1))
            Check(LegacyHelperWire.ExchangeConnected(stream, new byte[] { 10 }, 1000) == null, "empty disconnect");
        using (var stream = new FixtureStream(new byte[] { 10 }, 1))
            Check(LegacyHelperWire.ExchangeConnected(stream, new byte[] { 10 }, 1000) == "", "blank line");
        using (var stream = new FixtureStream(Encoding.UTF8.GetBytes("one\ntwo\n"), 4096))
            Check(LegacyHelperWire.ExchangeConnected(stream, new byte[] { 10 }, 1000) == "one", "legacy first response line");
        using (var stream = new FixtureStream(Encoding.UTF8.GetBytes(new string('x', max - 1) + "\n"), 4096))
            Check(LegacyHelperWire.ExchangeConnected(stream, new byte[] { 10 }, 3000).Length == max - 1, "exact response boundary");
        foreach (byte[] response in new[] { Encoding.UTF8.GetBytes(new string('x', max)), Encoding.UTF8.GetBytes(new string('x', max + 1024) + "\n") })
            using (var stream = new FixtureStream(response, 4096))
            {
                Reject<IOException>(() => LegacyHelperWire.ExchangeConnected(stream, new byte[] { 10 }, 3000), "overlarge incremental response");
                Check(stream.ReadBytes <= max + 1, "oversize acquisition stays bounded");
            }
        foreach (byte[] response in new[] { new byte[] { 0xff, 10 }, new byte[] { 0xe3, 0x81, 10 }, new byte[] { 0xff, 0xfe, 123, 0, 10 } })
            using (var stream = new FixtureStream(response, 1))
                Reject<DecoderFallbackException>(() => LegacyHelperWire.ExchangeConnected(stream, new byte[] { 10 }, 1000), "strict UTF8 response");
        foreach (int timeout in new[] { 0, -1 })
            using (var stream = new FixtureStream(new byte[0], 1))
                Reject<ArgumentOutOfRangeException>(() => LegacyHelperWire.ExchangeConnected(stream, new byte[] { 10 }, timeout), "invalid I/O deadline");
        foreach (string mode in new[] { "write", "read", "drip" })
        {
            var stream = new FixtureStream(Encoding.UTF8.GetBytes("partial response without terminator"), 1, mode);
            var elapsed = Stopwatch.StartNew();
            Reject<TimeoutException>(() => LegacyHelperWire.ExchangeConnected(stream, new byte[] { 10 }, 150), "bounded " + mode);
            Check(elapsed.ElapsedMilliseconds < 1500, "absolute " + mode + " deadline");
            Check(stream.Disposed && stream.Writes == 1, "one write and owned connection disposal: " + mode);
        }
        string path = Path.Combine(Path.GetTempPath(), "cucp-owned-wire-" + Guid.NewGuid().ToString("N"));
        try
        {
            File.WriteAllBytes(path, new UTF8Encoding(true).GetPreamble());
            Check(LegacyHelperWire.ReadRequestFile(path) == "", "request file BOM only");
            File.WriteAllBytes(path, Encoding.UTF8.GetBytes("{}\r\n"));
            Check(LegacyHelperWire.ReadRequestFile(path) == "{}", "request file one terminator");
            File.WriteAllBytes(path, Encoding.UTF8.GetBytes("{}\n\n"));
            Reject<ArgumentException>(() => LegacyHelperWire.ReadRequestFile(path), "request file multiple frames");
            using (var file = File.Create(path)) file.SetLength(max + 4L);
            Reject<IOException>(() => LegacyHelperWire.ReadRequestFile(path), "file bounded before materialization");
        }
        finally { File.Delete(path); }
        Console.WriteLine("Passed " + checks + " helper wire contracts; generated bytes/owned files only.");
    }

    private sealed class FixtureStream : Stream
    {
        private readonly byte[] source; private readonly int chunk; private readonly string mode; private int cursor;
        private readonly TaskCompletionSource<int> pending = new TaskCompletionSource<int>();
        public bool Disposed; public int Writes, ReadBytes;
        public FixtureStream(byte[] source, int chunk, string mode = "") { this.source = source; this.chunk = chunk; this.mode = mode; }
        public override Task WriteAsync(byte[] buffer, int offset, int count, CancellationToken token)
        { Writes++; return mode == "write" ? pending.Task : Task.FromResult(0); }
        public override Task<int> ReadAsync(byte[] buffer, int offset, int count, CancellationToken token)
        {
            if (mode == "read") return pending.Task;
            if (mode == "drip") return Task.Delay(75).ContinueWith(_ => Disposed ? 0 : Copy(buffer, offset, count));
            return Task.FromResult(Copy(buffer, offset, count));
        }
        private int Copy(byte[] buffer, int offset, int count)
        { int size = Math.Min(Math.Min(count, chunk), source.Length - cursor); Buffer.BlockCopy(source, cursor, buffer, offset, size); cursor += size; ReadBytes += size; return size; }
        protected override void Dispose(bool disposing) { Disposed = true; if (mode == "read" || mode == "write") pending.TrySetException(new IOException("owned fixture disposed")); base.Dispose(disposing); }
        public override bool CanRead { get { return true; } } public override bool CanWrite { get { return true; } } public override bool CanSeek { get { return false; } }
        public override long Length { get { throw new NotSupportedException(); } } public override long Position { get { throw new NotSupportedException(); } set { throw new NotSupportedException(); } }
        public override int Read(byte[] buffer, int offset, int count) { throw new Exception("Unplanned synchronous read"); }
        public override void Write(byte[] buffer, int offset, int count) { throw new Exception("Unplanned synchronous write"); }
        public override void Flush() { throw new Exception("Unplanned synchronous flush"); }
        public override long Seek(long offset, SeekOrigin origin) { throw new NotSupportedException(); }
        public override void SetLength(long value) { throw new NotSupportedException(); }
    }
}
