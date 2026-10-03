// Test-only sparse timing evidence. No Windows/UIA references or runtime hooks.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Text;

internal sealed class OwnedProviderProgress : IDisposable
{
    internal const int MaxRecords = 2048, MaxBytes = 1024 * 1024;
    private readonly FileStream stream;
    private readonly Func<object, string> serialize;
    private readonly string group;
    private readonly Stopwatch clock = Stopwatch.StartNew();
    private string request;
    private long requestStart, writeTicks, bytes;
    private int sequence;
    internal long ProviderTicks, DiagnosticTicks;

    internal OwnedProviderProgress(string path, string group, Func<object, string> serialize)
    {
        this.group = group; this.serialize = serialize;
        // Unique owned path only. Never overwrite a previous run's evidence.
        stream = new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.Read);
    }
    internal void StartRequest(string name)
    {
        if (request != null) throw new InvalidOperationException("Progress request already active");
        request = name; requestStart = clock.ElapsedTicks; ProviderTicks = DiagnosticTicks = 0;
        Emit("request.start");
    }
    internal void FinishRequest()
    {
        Emit("request.end"); request = null; ProviderTicks = DiagnosticTicks = 0;
    }
    internal void Emit(string phase, string operation = null, int index = 0)
    {
        if (sequence >= MaxRecords) throw new InvalidOperationException("Owned progress record limit exceeded");
        long started = Stopwatch.GetTimestamp(), elapsed = clock.ElapsedTicks;
        var record = new Dictionary<string, object> {
            { "schema", "cucp.helper-provider-progress/v1" }, { "sequence", sequence + 1 },
            { "group", group }, { "request", request }, { "phase", phase }, { "operation", operation }, { "index", index },
            { "elapsed_ticks", elapsed }, { "request_ticks", request == null ? 0 : elapsed - requestStart },
            { "provider_ticks", ProviderTicks }, { "diagnostic_ticks", DiagnosticTicks },
            { "write_ticks", writeTicks }, { "frequency", Stopwatch.Frequency }
        };
        byte[] encoded = Encoding.UTF8.GetBytes(serialize(record) + "\n");
        if (encoded.Length > MaxBytes - bytes) throw new InvalidOperationException("Owned progress byte limit exceeded");
        stream.Write(encoded, 0, encoded.Length); stream.Flush();
        bytes += encoded.Length; sequence++;
        // Includes formatting/write/flush cost of prior markers, never UIA time.
        writeTicks += Stopwatch.GetTimestamp() - started;
    }
    public void Dispose() { stream.Dispose(); }
}
