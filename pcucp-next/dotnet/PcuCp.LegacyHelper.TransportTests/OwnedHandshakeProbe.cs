using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Pipes;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Win32.SafeHandles;
using PcuCp.LegacyHelper;

// Independent, disposable endpoints for the Windows Framework handshake
// diagnosis. The Python OwnedProcess supervisor owns both processes, their
// deadlines and termination. In particular, do not put a blocking legacy
// AutoFlush setter in an abandoned Task or create subprocesses here.
internal static class OwnedHandshakeProbe
{
    private const string Request = "{\"fixture\":\"owned-handshake-request\",\"text\":\"한글😀\"}";
    private const string Response = "{\"fixture\":\"owned-handshake-response\",\"text\":\"한글😀\"}";
    private static readonly UTF8Encoding NoBom = new UTF8Encoding(false, true);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool GetNamedPipeServerProcessId(SafePipeHandle pipe, out uint pid);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool GetNamedPipeClientProcessId(SafePipeHandle pipe, out uint pid);

    public static int RunServer(string path)
    {
        var spec = ReadSpec(path);
        string mode = Text(spec, "mode");
        if (mode != "eager" && mode != "lazy") throw new ArgumentException("invalid owned handshake server mode");
        int requested = Convert.ToInt32(spec["buffer_size"]);
        if (requested != 0 && requested != 512) throw new ArgumentException("owned handshake buffer must be 0 or 512");
        int timeout = ConnectTimeout(spec);
        int pid = Process.GetCurrentProcess().Id;
        string name = "cucp-helper-" + pid;
        var trace = new PhaseTrace("server");
        Dictionary<string, object> pending = null;
        trace.Mark("pipe_create_begin");
        // Preserve the exact five-argument constructor in the original case.
        // Its zero buffer arguments are advisory, not proof of zero capacity.
        using (var pipe = requested == 0
            ? new NamedPipeServerStream(name, PipeDirection.InOut, 1, PipeTransmissionMode.Byte, PipeOptions.Asynchronous)
            : new NamedPipeServerStream(name, PipeDirection.InOut, 1, PipeTransmissionMode.Byte, PipeOptions.Asynchronous, requested, requested))
        {
            trace.Mark("pipe_create_complete");
            var ready = State(pipe, "server", mode, requested, 0);
            ready["pipe_name"] = name;
            File.WriteAllText(Text(spec, "ready"), LegacyHelperService.NewJson().Serialize(ready), NoBom);
            trace.State(ready);
            trace.Mark("ready_published");
            using (var cancellation = new CancellationTokenSource())
            {
                trace.Mark("connect_begin");
                var wait = pipe.WaitForConnectionAsync(cancellation.Token);
                if (!wait.Wait(timeout))
                {
                    trace.Mark("connect_timeout");
                    cancellation.Cancel();
                    pipe.Dispose();
                    // Observe cancellation without an unbounded EndWait or a
                    // manually disposed native completion event.
                    try
                    {
                        if (!wait.Wait(1000)) throw new TimeoutException("owned handshake cancellation did not complete");
                    }
                    catch (AggregateException) { var observed = wait.Exception; }
                    throw new TimeoutException("owned handshake connection timeout");
                }
                wait.GetAwaiter().GetResult();
            }
            trace.Mark("connect_complete");
            uint clientPid;
            if (!GetNamedPipeClientProcessId(pipe.SafePipeHandle, out clientPid))
                throw new IOException("owned handshake client PID unavailable: " + Marshal.GetLastWin32Error());
            trace.State(State(pipe, "server", mode, requested, clientPid));
            pending = ObserveOperation(pipe, trace, () =>
            {
              using (var reader = new StreamReader(pipe, Encoding.UTF8, true, 1024, true))
              {
                StreamWriter eager = null;
                LegacyHelperResponseWriter lazy = null;
                trace.Mark("writer_construct_begin");
                if (mode == "eager") eager = new StreamWriter(pipe, Encoding.UTF8, 1024, true);
                else lazy = new LegacyHelperResponseWriter(pipe);
                trace.Mark("writer_construct_complete");
                if (eager != null)
                {
                    trace.Mark("autoflush_begin");
                    eager.AutoFlush = true;
                    trace.Mark("autoflush_complete");
                }
                trace.Mark("request_read_begin");
                string request = reader.ReadLine();
                if (request == null) throw new EndOfStreamException("owned handshake request stream closed");
                if (request != Request) throw new InvalidDataException("owned handshake request mismatch");
                trace.Mark("request_read_complete");
                trace.Mark("response_write_begin");
                if (eager != null) eager.WriteLine(Response);
                else lazy.WriteLine(Response);
                trace.Mark("response_write_complete");
                if (eager != null)
                {
                    trace.Mark("writer_dispose_begin");
                    eager.Dispose();
                    trace.Mark("writer_dispose_complete");
                }
              }
            });
            trace.Mark("pipe_dispose_begin");
        }
        trace.Mark("pipe_dispose_complete");
        Complete("server", mode, trace, pending);
        return 0;
    }

    public static int RunClient(string path)
    {
        var spec = ReadSpec(path);
        string mode = Text(spec, "mode");
        if (mode != "legacy" && mode != "bytes" && mode != "drain-bom")
            throw new ArgumentException("invalid owned handshake client mode");
        int expectedPid = Convert.ToInt32(spec["server_pid"]);
        string name = Text(spec, "pipe");
        if (expectedPid <= 0 || name != "cucp-helper-" + expectedPid)
            throw new ArgumentException("owned handshake pipe must match the retained server PID");
        var trace = new PhaseTrace("client");
        Dictionary<string, object> pending = null;
        using (var pipe = new NamedPipeClientStream(".", name, PipeDirection.InOut, PipeOptions.Asynchronous))
        {
            trace.Mark("connect_begin");
            pipe.Connect(ConnectTimeout(spec));
            trace.Mark("connect_complete");
            uint serverPid;
            if (!GetNamedPipeServerProcessId(pipe.SafePipeHandle, out serverPid))
                throw new IOException("owned handshake server PID unavailable: " + Marshal.GetLastWin32Error());
            if (serverPid != expectedPid) throw new IOException("owned handshake connected to an unexpected server PID");
            trace.State(State(pipe, "client", mode, null, serverPid));
            pending = ObserveOperation(pipe, trace, () =>
            {
              if (mode == "drain-bom")
            {
                // Counterfactual for an eager server: posting the first read
                // should release its isolated preamble write before a request.
                trace.Mark("preamble_read_begin");
                byte[] preamble = new byte[3];
                int length = 0;
                while (length < preamble.Length)
                {
                    int count = pipe.ReadAsync(preamble, length, preamble.Length - length).GetAwaiter().GetResult();
                    if (count == 0) throw new EndOfStreamException("owned handshake preamble stream closed");
                    length += count;
                }
                if (preamble[0] != 0xef || preamble[1] != 0xbb || preamble[2] != 0xbf)
                    throw new InvalidDataException("owned handshake unexpected preamble");
                trace.Mark("preamble_read_complete");
            }
              using (var reader = new StreamReader(pipe, Encoding.UTF8, true, 1024, true))
            {
                StreamWriter writer = null;
                if (mode == "legacy")
                {
                    trace.Mark("writer_construct_begin");
                    writer = new StreamWriter(pipe, Encoding.UTF8, 1024, true);
                    trace.Mark("writer_construct_complete");
                    trace.Mark("autoflush_begin");
                    writer.AutoFlush = true;
                    trace.Mark("autoflush_complete");
                    trace.Mark("request_write_begin");
                    writer.WriteLine(Request);
                }
                else
                {
                    byte[] request = NoBom.GetBytes(Request + "\n");
                    trace.Mark("request_write_begin");
                    Task write = pipe.WriteAsync(request, 0, request.Length);
                    trace.Mark("request_write_async_returned");
                    write.GetAwaiter().GetResult();
                }
                trace.Mark("request_write_complete");
                trace.Mark("response_read_begin");
                string response = reader.ReadLine();
                if (response == null) throw new EndOfStreamException("owned handshake response stream closed");
                if (response != Response) throw new InvalidDataException("owned handshake response mismatch");
                trace.Mark("response_read_complete");
                if (writer != null)
                {
                    trace.Mark("writer_dispose_begin");
                    writer.Dispose();
                    trace.Mark("writer_dispose_complete");
                }
              }
            });
            trace.Mark("pipe_dispose_begin");
        }
        trace.Mark("pipe_dispose_complete");
        Complete("client", mode, trace, pending);
        return 0;
    }

    private static IDictionary<string, object> ReadSpec(string path)
    {
        if (Environment.OSVersion.Platform != PlatformID.Win32NT)
            throw new PlatformNotSupportedException("owned handshake requires Windows .NET Framework");
        return (IDictionary<string, object>)LegacyHelperService.NewJson().DeserializeObject(File.ReadAllText(path, Encoding.UTF8));
    }

    private static string Text(IDictionary<string, object> spec, string name) { return Convert.ToString(spec[name]); }
    private static int ConnectTimeout(IDictionary<string, object> spec)
    {
        int value = spec.ContainsKey("connect_timeout_ms") ? Convert.ToInt32(spec["connect_timeout_ms"]) : 2000;
        if (value <= 0 || value > 3000) throw new ArgumentException("invalid owned handshake connect timeout");
        return value;
    }

    private static Dictionary<string, object> State(PipeStream pipe, string role, string mode, int? requested, uint peerPid)
    {
        return new Dictionary<string, object>
        {
            ["role"] = role, ["mode"] = mode, ["pid"] = Process.GetCurrentProcess().Id,
            ["peer_pid"] = peerPid, ["requested_buffer_bytes"] = requested,
            ["actual_in_buffer_bytes"] = pipe.InBufferSize, ["actual_out_buffer_bytes"] = pipe.OutBufferSize,
            ["is_async"] = pipe.IsAsync, ["clr_version"] = Environment.Version.ToString(),
            ["os_version"] = Environment.OSVersion.VersionString
        };
    }

    private static Dictionary<string, object> ObserveOperation(PipeStream pipe, PhaseTrace trace, Action operation)
    {
        Exception failure = null;
        string failedPhase = null;
        var deadline = new PendingIoDeadline(pipe, trace);
        try { operation(); }
        catch (IOException e) { failure = e; failedPhase = trace.Current; }
        catch (ObjectDisposedException e) { failure = e; failedPhase = trace.Current; }
        catch (OperationCanceledException e) { failure = e; failedPhase = trace.Current; }
        finally { deadline.Dispose(); }
        if (failure == null)
        {
            if (deadline.Expired) throw new TimeoutException("owned handshake operation exceeded its deadline");
            return null;
        }
        string phase = deadline.Expired ? deadline.PhaseAtCancellation : failedPhase;
        if (Array.IndexOf(new[] { "autoflush_begin", "request_read_begin", "response_write_begin", "preamble_read_begin",
            "request_write_begin", "request_write_async_returned", "response_read_begin" }, phase) < 0)
            throw new IOException("owned handshake failed outside a known pending I/O phase", failure);
        int nativeError = failure.HResult & 0xffff;
        // A peer cancelled first can break this pipe before its own timer fires.
        // The supervisor must corroborate this observation with the other
        // endpoint's cancellation; it is never a standalone deadlock verdict.
        bool peerClosed = failure is EndOfStreamException || (failure is IOException &&
            (nativeError == 109 || nativeError == 232 || nativeError == 233 || nativeError == 995));
        // Framework also maps ERROR_OPERATION_ABORTED to this exception rather
        // than IOException. It is admissible only after our own deadline fired.
        bool locallyCancelled = deadline.Expired && (failure is ObjectDisposedException || failure is OperationCanceledException ||
            (failure is IOException && nativeError == 6));
        if (!peerClosed && !locallyCancelled) throw new IOException("unexpected owned handshake I/O error", failure);
        return new Dictionary<string, object>
        {
            ["status"] = deadline.Expired ? "fixture_cancelled_pending_io" : "fixture_peer_closed_pending_io",
            ["pending_phase"] = phase, ["exception_type"] = failure.GetType().Name,
            ["native_error"] = nativeError, ["operation_timeout_ms"] = PendingIoDeadline.TimeoutMs,
            ["deadline_expired"] = deadline.Expired
        };
    }

    private static void Complete(string role, string mode, PhaseTrace trace, Dictionary<string, object> pending)
    {
        trace.Mark(pending == null ? "complete" : "pending_io_observed");
        var result = pending ?? new Dictionary<string, object> { ["status"] = "complete" };
        result["role"] = role;
        result["mode"] = mode;
        result["pid"] = Process.GetCurrentProcess().Id;
        result["verified_frames"] = pending == null ? 1 : 0;
        result["elapsed_ms"] = trace.ElapsedMilliseconds;
        Console.Out.WriteLine(LegacyHelperService.NewJson().Serialize(result));
        Console.Out.Flush();
    }

    private sealed class PendingIoDeadline : IDisposable
    {
        public const int TimeoutMs = 750;
        private readonly Timer timer;
        private int state; // 0 armed, 1 expired, 2 disarmed
        private Exception cancellationFailure;
        public string PhaseAtCancellation { get; private set; }
        public bool Expired { get { return state == 1; } }
        public PendingIoDeadline(PipeStream pipe, PhaseTrace trace)
        {
            timer = new Timer(_ =>
            {
                if (Interlocked.CompareExchange(ref state, 1, 0) != 0) return;
                PhaseAtCancellation = trace.Current;
                trace.Mark("operation_deadline_expired");
                try { pipe.Dispose(); }
                catch (Exception e) { cancellationFailure = e; }
            }, null, TimeoutMs, Timeout.Infinite);
        }
        public void Dispose()
        {
            Interlocked.CompareExchange(ref state, 2, 0);
            var stopped = new ManualResetEvent(false);
            if (!timer.Dispose(stopped) || !stopped.WaitOne(1000))
            {
                // Do not close an event while a pending callback may signal it.
                // This failure exits the fixture; its process evidence cannot
                // qualify as a successful pending-I/O observation.
                throw new TimeoutException("owned handshake cancellation callback did not finish");
            }
            stopped.Dispose();
            if (cancellationFailure != null) throw new IOException("owned handshake pipe cancellation failed", cancellationFailure);
        }
    }

    private sealed class PhaseTrace
    {
        private readonly string role;
        private readonly Stopwatch elapsed = Stopwatch.StartNew();
        private readonly object gate = new object();
        private string current;
        private int events;
        public PhaseTrace(string role) { this.role = role; }
        public long ElapsedMilliseconds { get { return elapsed.ElapsedMilliseconds; } }
        public string Current { get { lock (gate) return current; } }
        public void Mark(string phase)
        {
          lock (gate)
          {
            if (++events > 48) throw new IOException("owned handshake phase limit exceeded");
            current = phase;
            Console.Error.WriteLine("helper_handshake_phase=" + phase + " role=" + role + " elapsed_ms=" + elapsed.ElapsedMilliseconds);
            Console.Error.Flush();
          }
        }
        public void State(IDictionary<string, object> state)
        {
            Console.Error.WriteLine("helper_handshake_state=" + LegacyHelperService.NewJson().Serialize(state));
            Console.Error.Flush();
        }
    }
}
