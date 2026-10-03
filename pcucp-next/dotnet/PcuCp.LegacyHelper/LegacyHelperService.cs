using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Pipes;
using System.Runtime.InteropServices;
using System.Security.Principal;
using System.Text;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using Microsoft.Win32.SafeHandles;

namespace PcuCp.LegacyHelper
{
    // Separate detached legacy service. Intentionally no parent/stdin lifetime guard.
    public sealed class LegacyHelperService
    {
        private readonly LegacyHelperActions actions;
        private readonly Func<DateTime> clock;
        private readonly Action<string> log;
        private readonly Action<string> phase;
        private readonly Action<Dictionary<string, object>> aclEvidence;
        private readonly string pipeName;
        private readonly string lockPath;
        private readonly int pid;
        private readonly int idleMs;
        private readonly JavaScriptSerializer json = NewJson();

        public LegacyHelperService(LegacyHelperActions actions, int pid, string pipeName, string lockPath,
            int idleMs, Func<DateTime> clock, Action<string> log, Action<string> phase = null,
            Action<Dictionary<string, object>> aclEvidence = null)
        {
            this.actions = actions; this.pid = pid; this.pipeName = pipeName;
            this.lockPath = lockPath; this.idleMs = idleMs; this.clock = clock; this.log = log;
            this.phase = phase ?? (_ => { });
            this.aclEvidence = aclEvidence;
        }
        public static JavaScriptSerializer NewJson()
        {
            return new JavaScriptSerializer { MaxJsonLength = 16 * 1024 * 1024, RecursionLimit = 100 };
        }
        public static object Field(IDictionary<string, object> value, string name)
        {
            if (value == null) return null;
            foreach (var entry in value) if (String.Equals(entry.Key, name, StringComparison.OrdinalIgnoreCase)) return entry.Value;
            return null;
        }
        public Dictionary<string, object> Respond(string line, out bool shutdown)
        {
            shutdown = false;
            object id = null, result = null;
            string error = null, action;
            IDictionary<string, object> args;
            try
            {
                var request = json.DeserializeObject(line) as IDictionary<string, object>;
                // Explicit candidate correction: scalar/array envelopes are rejected,
                // rather than emulating PowerShell member-enumeration coercion.
                if (request == null) throw new FormatException("request must be a JSON object");
                id = Field(request, "id");
                action = Convert.ToString(Field(request, "action"), System.Globalization.CultureInfo.InvariantCulture);
                var supplied = Field(request, "args");
                args = supplied as IDictionary<string, object>;
                if (supplied != null && args == null) throw new FormatException("args must be an object or null");
                args = args ?? new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase);
            }
            catch (Exception exception)
            {
                return new Dictionary<string, object> { ["id"] = id, ["exit_code"] = 1, ["result"] = null,
                    ["error"] = "invalid_json: " + exception.Message };
            }
            int exitCode = 0;
            try
            {
                result = actions.Dispatch(action, args);
                var status = Convert.ToString(Field((IDictionary<string, object>)result, "status"));
                if (String.Equals(status, "error", StringComparison.OrdinalIgnoreCase)) exitCode = 1;
                else if (String.Equals(status, "partial", StringComparison.OrdinalIgnoreCase)) exitCode = 2;
                else if (String.Equals(status, "fallback_required", StringComparison.OrdinalIgnoreCase)) exitCode = 99;
            }
            catch (LegacyHelperFixtureException) { throw; }
            catch (Exception exception) { error = exception.Message; exitCode = 1; }
            shutdown = String.Equals(action, "shutdown", StringComparison.OrdinalIgnoreCase);
            return new Dictionary<string, object> { ["id"] = id, ["exit_code"] = exitCode, ["result"] = result, ["error"] = error };
        }
        public void Run()
        {
            var ownerSid = WindowsIdentity.GetCurrent().User;
            var lockData = new Dictionary<string, object> {
                ["pid"] = pid, ["pipe_name"] = pipeName, ["started_at"] = actions.StartedAt.ToString("o"),
                ["helper_version"] = "2.0.0", ["owner_user"] = Environment.UserName,
                ["owner_sid"] = ownerSid == null ? null : ownerSid.Value
            };
            // Candidate-only safety correction: never overwrite a discovered lock.
            // The caller must provide an isolated, absent candidate lock path.
            string expectedLockText = json.Serialize(lockData) + Environment.NewLine;
            byte[] body = Encoding.UTF8.GetBytes(expectedLockText);
            if (body.Length + 3 > 16384) throw new IOException("candidate lock exceeds bounded metadata limit");
            byte[] expectedLockBytes = new byte[body.Length + 3];
            expectedLockBytes[0] = 0xef; expectedLockBytes[1] = 0xbb; expectedLockBytes[2] = 0xbf;
            Buffer.BlockCopy(body, 0, expectedLockBytes, 3, body.Length);
            FileIdentity identity;
            using (var file = new FileStream(lockPath, FileMode.CreateNew, FileAccess.Write, FileShare.Read))
            {
                if (!GetFileInformationByHandle(file.SafeFileHandle, out identity)) throw new IOException("candidate lock identity unavailable");
                file.Write(expectedLockBytes, 0, expectedLockBytes.Length);
            }
            phase("lock.written");
            var lastActivity = clock();
            bool running = true;
            try
            {
                while (running)
                {
                    try
                    {
                        using (var pipe = LegacyHelperPipeSecurity.Create(pipeName, ownerSid, aclEvidence))
                        {
                            phase("pipe.created");
                            phase("pipe.acl.verified");
                            using (var cancellation = new System.Threading.CancellationTokenSource())
                            {
                                // Task owns the overlapped completion; never close an
                                // AsyncWaitHandle while its cancellation callback can signal.
                                phase("connection.wait.start");
                                var wait = pipe.WaitForConnectionAsync(cancellation.Token);
                                while (!wait.IsCompleted)
                                {
                                    if ((clock() - lastActivity).TotalMilliseconds > idleMs)
                                    {
                                        running = false;
                                        cancellation.Cancel();
                                        pipe.Dispose();
                                        break;
                                    }
                                    System.Threading.Thread.Sleep(100);
                                }
                                if (!running)
                                {
                                    try
                                    {
                                        if (!wait.Wait(1000))
                                        {
                                            wait.ContinueWith(task => { var ignored = task.Exception; }, TaskContinuationOptions.OnlyOnFaulted | TaskContinuationOptions.ExecuteSynchronously);
                                            throw new TimeoutException("candidate connection cancellation did not complete");
                                        }
                                    }
                                    catch (AggregateException) { var observed = wait.Exception; }
                                    continue;
                                }
                                wait.GetAwaiter().GetResult();
                                phase("connection.wait.complete");
                            }
                            using (var reader = new StreamReader(pipe, Encoding.UTF8, true, 1024, true))
                            {
                                var writer = new LegacyHelperResponseWriter(pipe);
                                phase("connection.reader.ready");
                                while (pipe.IsConnected)
                                {
                                    string line;
                                    phase("request.read.start");
                                    try { line = reader.ReadLine(); } catch (IOException) { break; }
                                    phase("request.read.complete");
                                    // Legacy idle timeout is deliberately not a ReadLine deadline.
                                    if (String.IsNullOrEmpty(line)) break;
                                    lastActivity = clock();
                                    bool shutdown;
                                    var response = Respond(line, out shutdown);
                                    phase("response.write.start");
                                    try { writer.WriteLine(json.Serialize(response)); } catch (IOException) { break; }
                                    phase("response.write.complete");
                                    if (shutdown) { running = false; break; }
                                }
                            }
                        }
                    }
                    catch (LegacyHelperFixtureException) { throw; }
                    catch (IOException e)
                    {
                        log("pipe error: " + e.Message);
                        if ((clock() - lastActivity).TotalMilliseconds > idleMs) running = false;
                        else System.Threading.Thread.Sleep(25);
                    }
                }
            }
            finally
            {
                phase("lock.cleanup.start");
                TryCleanupOwnedLock(lockPath, pid, identity, expectedLockBytes, json, log);
                phase("lock.cleanup.complete");
            }
        }
        // Lock contents are checked under an exclusive-write/delete native handle;
        // SetFileInformationByHandle targets that same file, not a replaced path.
        private static bool TryCleanupOwnedLock(string path, int expectedPid, FileIdentity expectedIdentity, byte[] expectedBytes, JavaScriptSerializer json, Action<string> log)
        {
            try
            {
                using (var handle = CreateFileW(path, 0x80000000u | 0x10000u, 1, IntPtr.Zero, 3, 0, IntPtr.Zero))
                {
                    if (handle.IsInvalid) return false;
                    FileIdentity current;
                    if (!GetFileInformationByHandle(handle, out current) || current.VolumeSerial != expectedIdentity.VolumeSerial
                        || current.IndexHigh != expectedIdentity.IndexHigh || current.IndexLow != expectedIdentity.IndexLow) return false;
                    using (var stream = new FileStream(handle, FileAccess.Read))
                    {
                        // Bound reads to the original byte length. No decoder/BOM
                        // normalization may turn a same-file edit into equality.
                        if (stream.Length != expectedBytes.Length) return false;
                        byte[] contents = new byte[expectedBytes.Length];
                        int offset = 0;
                        while (offset < contents.Length)
                        {
                            int read = stream.Read(contents, offset, contents.Length - offset);
                            if (read == 0) return false;
                            offset += read;
                        }
                        for (int i = 0; i < contents.Length; i++) if (contents[i] != expectedBytes[i]) return false;
                        string text = new UTF8Encoding(false, true).GetString(contents, 3, contents.Length - 3);
                        var data = json.DeserializeObject(text) as IDictionary<string, object>;
                        if (data == null || Convert.ToInt32(Field(data, "pid")) != expectedPid) return false;
                        var delete = new Disposition { DeleteFile = true };
                        return SetFileInformationByHandle(handle, 4, ref delete, 1);
                    }
                }
            }
            catch (Exception e) { log("lock cleanup skipped: " + e.Message); return false; }
        }
        [StructLayout(LayoutKind.Sequential)] private struct FileIdentity
        {
            public uint Attributes; public System.Runtime.InteropServices.ComTypes.FILETIME CreationTime, AccessTime, WriteTime;
            public uint VolumeSerial, SizeHigh, SizeLow, Links, IndexHigh, IndexLow;
        }
        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool GetFileInformationByHandle(SafeFileHandle file, out FileIdentity information);
        [StructLayout(LayoutKind.Sequential)] private struct Disposition { [MarshalAs(UnmanagedType.U1)] public bool DeleteFile; }
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern SafeFileHandle CreateFileW(string name, uint access, uint share, IntPtr security, uint creation, uint flags, IntPtr template);
        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool SetFileInformationByHandle(SafeFileHandle file, int infoClass, ref Disposition data, uint size);

        public static string Exchange(string name, string request, int connectMs, int readMs, Action<string> phase = null)
        {
            phase = phase ?? (_ => { });
            if (!System.Text.RegularExpressions.Regex.IsMatch(name ?? "", "^cucp-helper-[0-9]+$"))
                throw new ArgumentException("candidate pipe must be cucp-helper-<pid>");
            if (connectMs <= 0 || readMs <= 0) throw new ArgumentOutOfRangeException("bounded connection and I/O timeouts required");
            byte[] frame = LegacyHelperWire.RequestBytes(request);
            using (var pipe = new NamedPipeClientStream(".", name, PipeDirection.InOut, PipeOptions.Asynchronous))
            {
                phase("client.connect.start");
                pipe.Connect(connectMs);
                phase("client.connect.complete");
                return LegacyHelperWire.ExchangeConnected(pipe, frame, readMs, phase);
            }
        }
    }
}
