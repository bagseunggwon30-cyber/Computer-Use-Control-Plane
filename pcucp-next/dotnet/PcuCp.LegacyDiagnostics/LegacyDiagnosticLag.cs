using System.Globalization;
using System.Text.Json;
using System.Text.RegularExpressions;

internal sealed partial class LegacyDiagnosticCoordinator
{
    private LegacyDiagnosticResult DiagnoseLag()
    {
        int sample = I(V("--sample-ms")); if (sample <= 0) sample = 3000; if (sample > 8000) sample = 8000;
        Start("diagnose-lag");
        var first = A(Effect(LegacyDiagnosticEffectKind.Processes));
        Effect(LegacyDiagnosticEffectKind.Sleep, data: sample);
        var second = A(Effect(LegacyDiagnosticEffectKind.Processes));
        var byPid = new Dictionary<string, int>(); for (int index = 0; index < first.Length; index++) byPid[S(P(first[index], "id"))] = index;
        // PowerShell subtracts the two DateTime wall-clock values. In particular,
        // it does not normalize a DST-offset change before computing process age.
        DateTime now = DateTimeOffset.Parse(Now(), CultureInfo.InvariantCulture).DateTime;
        int cpu = I(Effect(LegacyDiagnosticEffectKind.ProcessorCount));
        var results = new List<Dictionary<string, object?>>(); long totalBytes = 0;
        foreach (var group in new[] {
            ("codex", new[] {"codex", "Codex"}), ("electron", new[] {"electron", "Code", "Cursor", "Windsurf"}),
            ("node", new[] {"node"}), ("powershell", new[] {"powershell", "pwsh"}),
            ("chrome", new[] {"chrome", "msedge", "brave", "whale"}), ("cucp_helper", new[] {"cucp-helper", "windows-mcp-helper"}) })
        {
            var matching = second.Select((p, index) => (Process: p, Ordinal: index)).Where(row => group.Item2.Contains(S(P(row.Process, "name")), Comparer)).ToArray();
            if (matching.Length == 0) continue;
            long sum = 0; double oldest = 0, deltaSum = 0; var priorities = new Dictionary<string, int>(Comparer);
            foreach (var row in matching)
            {
                int? previous = byPid.TryGetValue(S(P(row.Process, "id")), out int index) ? index : null;
                // Original Process property getters run after the sleep/date/CPU
                // acquisitions, per matching process. Retain host-owned objects;
                // ordinal references cannot reopen an arbitrary process by PID.
                var metrics = Effect(LegacyDiagnosticEffectKind.ProcessMetrics, data: D("current_ordinal", row.Ordinal, "previous_ordinal", previous));
                if (P(metrics, "private_bytes").ValueKind != JsonValueKind.Null) sum += L(P(metrics, "private_bytes"));
                if (DateTimeOffset.TryParse(S(P(metrics, "started_at")), CultureInfo.InvariantCulture, DateTimeStyles.None, out var started)) oldest = Math.Max(oldest, (now - started.DateTime).TotalSeconds);
                if (metrics.ValueKind == JsonValueKind.Object && metrics.TryGetProperty("current_cpu_ms", out var currentCpu) && metrics.TryGetProperty("previous_cpu_ms", out var previousCpu))
                    deltaSum += Math.Max(0, N(currentCpu) - N(previousCpu));
                if (P(metrics, "priority").ValueKind != JsonValueKind.Null)
                {
                    string priority = S(P(metrics, "priority")); if (string.IsNullOrWhiteSpace(priority)) priority = "unknown";
                    priorities[priority] = priorities.GetValueOrDefault(priority) + 1;
                }
            }
            totalBytes += sum; double pct = cpu > 0 ? Math.Round(deltaSum / sample * (100d / cpu), 1) : 0;
            // Pipeline assignment collapses one PID to a scalar in the original.
            object pids = matching.Length == 1 ? P(matching[0].Process, "id") : matching.Select(p => P(p.Process, "id")).ToArray();
            results.Add(D("group", group.Item1, "count", matching.Length, "memory_mb", Math.Round(sum / 1048576d, 1),
                "cpu_delta_pct", pct, "oldest_age_sec", Convert.ToInt32(oldest), "priority_classes", priorities, "pids", pids));
        }
        var foreground = A(Effect(LegacyDiagnosticEffectKind.Windows)).FirstOrDefault(w => T(P(w, "foreground")));
        string title = S(P(foreground, "title")); int tempCount = 0, cacheCount = 0; long tempBytes = 0, cacheBytes = 0, logBytes = 0;
        // Preserve the historical nesting: cache/log stats depend on temp-root existence.
        if (Exists(paths.TempRoot))
        {
            foreach (var file in A(Files(paths.TempRoot, recurse: true))) { tempCount++; tempBytes += L(P(file, "length")); }
            if (Exists(paths.CacheDirectory)) foreach (var file in A(Files(paths.CacheDirectory))) { cacheCount++; cacheBytes += L(P(file, "length")); }
            if (Exists(paths.WrapperLog))
            {
                try { logBytes = L(P(Effect(LegacyDiagnosticEffectKind.FileStat, data: paths.WrapperLog), "length")); }
                catch (LegacyDiagnosticEffectException) { }
            }
        }
        int timeouts = 0;
        if (Exists(paths.WrapperLog))
        {
            try { timeouts = Regex.Matches(S(P(Effect(LegacyDiagnosticEffectKind.TailBytes, data: D("path", paths.WrapperLog, "max_bytes", 65536)), "text")), "TIMEOUT").Count; }
            catch (LegacyDiagnosticEffectException) { }
        }
        double totalMb = Math.Round(totalBytes / 1048576d, 1); var warnings = new List<string>(); var recommended = new List<object>();
        if (totalBytes > 8L * 1024 * 1024 * 1024) warnings.Add($"high_memory_total: tracked processes use {totalMb.ToString(CultureInfo.InvariantCulture)}MB (>8GB)");
        int electron = results.Where(r => (string)r["group"]! is "electron" or "codex" or "chrome").Sum(r => (int)r["count"]!);
        if (electron > 25)
        {
            warnings.Add($"electron_child_count={electron} (>25). Heavy multi-window load.");
            recommended.Add(D("code", "electron_pressure", "message", "Many Electron child processes detected", "recommended_action", "Close unused Electron app/Codex/Chrome windows; consider lowering Electron app priority manually if Codex is the active focus."));
        }
        if (tempCount > 1000)
        {
            warnings.Add($"cucp_temp_files={tempCount} (>1000). Cleanup recommended.");
            recommended.Add(D("code", "temp_pressure", "message", $"CUCP temp directory has {tempCount} files", "recommended_action", "Run 'cucp macro cleanup --dry-run' to preview, then '--execute' to remove stale files."));
        }
        if (logBytes > 64L * 1024 * 1024) warnings.Add($"wrapper_log_bytes={logBytes} (>64MB). Use 'macro log-tail' (bounded) instead of full read.");
        foreach (var r in results) if ((double)r["cpu_delta_pct"]! > 60) warnings.Add($"{r["group"]} cpu_delta_pct={r["cpu_delta_pct"]}% (>60% over {sample}ms sample)");
        if (timeouts > 0)
        {
            warnings.Add($"recent_timeout_count={timeouts} in last 64KB of wrapper log");
            recommended.Add(D("code", "recent_timeouts", "message", $"{timeouts} TIMEOUT entries in recent log tail", "recommended_action", "Run 'cucp macro ensure-helper' or increase -InvokeTimeoutMs."));
        }
        int elapsed = Stop("diagnose-lag");
        var payload = D("schema", "cucp.diagnose-lag/v1", "status", "ok", "collected_at", Now(), "elapsed_ms", elapsed, "sample_ms", sample,
            "cpu_count", cpu, "foreground_title", title, "processes", results, "totals", D("memory_mb", totalMb, "electron_child_count", electron),
            "storage", D("temp_root", paths.TempRoot, "temp_file_count", tempCount, "temp_bytes", tempBytes, "cache_dir", paths.CacheDirectory,
                "cache_file_count", cacheCount, "cache_bytes", cacheBytes, "wrapper_log_bytes", logBytes, "recent_timeout_count", timeouts), "warnings", warnings, "recommended_actions", recommended);
        var lines = new List<string> { $"ok diagnose-lag groups={results.Count} mem_mb={totalMb} electron={electron} temp_files={tempCount} log_mb={Math.Round(logBytes / 1048576d, 1)} warnings={warnings.Count} elapsed_ms={elapsed}" };
        lines.AddRange(results.Select(r => string.Format("  {0,-12} count={1,3} mem_mb={2,7} cpu_pct={3,5} oldest_s={4,5}", r["group"], r["count"], r["memory_mb"], r["cpu_delta_pct"], r["oldest_age_sec"])));
        lines.AddRange(warnings.Select(w => "  [WARN] " + w));
        return Result(payload, 0, 6, string.Join(Environment.NewLine, lines));
    }
}
