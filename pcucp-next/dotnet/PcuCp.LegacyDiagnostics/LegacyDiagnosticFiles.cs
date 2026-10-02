using System.Globalization;
using System.Text.Json;
using System.Text.RegularExpressions;

internal sealed partial class LegacyDiagnosticCoordinator
{
    private LegacyDiagnosticResult AuditSummary()
    {
        string? sinceMinutes = V("--since-minutes");
        DateTimeOffset? cutoff = null;
        string? cutoffText = null;
        if (Has(sinceMinutes))
        {
            try
            {
                // Get-Date is evaluated even when the following integer cast fails.
                string timestamp = Now();
                cutoff = DateTimeOffset.Parse(timestamp, CultureInfo.InvariantCulture,
                    DateTimeStyles.AllowWhiteSpaces).AddMinutes(-(double)I(sinceMinutes));
                cutoffText = cutoff.Value.ToString(timestamp.EndsWith('Z') ? "yyyy-MM-ddTHH:mm:ss.fff'Z'" : "yyyy-MM-ddTHH:mm:ss.fffzzz", CultureInfo.InvariantCulture);
            }
            catch (LegacyDiagnosticEffectException) { cutoff = null; }
            catch (Exception ex) when (ex is FormatException or OverflowException or ArgumentException or InvalidCastException or NativeFailure)
            { cutoff = null; }
        }

        JsonElement[] files = [];
        string auditDirectory = S(P(context, "audit_dir"));
        if (Exists(auditDirectory))
        {
            files = A(Files(auditDirectory, recurse: true, filter: "trajectory*.ndjson", file: false))
                .OrderByDescending(f => DiagnosticFileDate(P(f, "last_write_time")))
                .Take(20).ToArray();
        }
        int totalEvents = 0, sensitiveCount = 0, blockedCount = 0;
        var byMacro = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        var byExit = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        string? earliest = null, latest = null;
        foreach (var file in files)
        {
            JsonElement lines;
            try { lines = Effect(LegacyDiagnosticEffectKind.ReadLines, data: S(P(file, "full_name"))); }
            catch (LegacyDiagnosticEffectException) { continue; }
            foreach (var lineElement in A(lines))
            {
                string line = S(lineElement);
                if (string.IsNullOrWhiteSpace(line)) continue;
                JsonElement ev;
                DateTime? timestamp;
                try { ev = LegacyDiagnosticJson.Parse(line, out timestamp); }
                catch (JsonException) { continue; }
                var ts = DiagnosticEventProperty(ev, "ts");
                // Legacy /Date(...)/ values are real DateTime objects. Compare
                // their clock ticks as PowerShell's [datetime] comparison does;
                // their string form above is only for output/interpolation.
                if (cutoff is not null && T(ts) && (timestamp is DateTime date
                    ? date.Ticks < cutoff.Value.DateTime.Ticks
                    : DiagnosticTryDate(ts, out var eventTime) && eventTime < cutoff.Value))
                    continue;
                totalEvents++;
                string macro = S(DiagnosticEventProperty(ev, "macro"));
                if (macro.Length == 0) macro = S(DiagnosticEventProperty(ev, "action"));
                if (macro.Length != 0) byMacro[macro] = byMacro.GetValueOrDefault(macro) + 1;
                string exitCode = S(DiagnosticEventProperty(ev, "exit_code"));
                if (exitCode.Length != 0) byExit[exitCode] = byExit.GetValueOrDefault(exitCode) + 1;
                if (T(DiagnosticEventProperty(ev, "sensitive")) || Regex.IsMatch(S(DiagnosticEventProperty(ev, "reason")), "sensitive", RegexOptions.IgnoreCase))
                    sensitiveCount++;
                if (DiagnosticEventEquals(DiagnosticEventProperty(ev, "status"), "blocked") || Comparer.Equals(exitCode, "3"))
                    blockedCount++;
                if (T(ts))
                {
                    string text = S(ts);
                    if (string.IsNullOrEmpty(earliest) || Comparer.Compare(text, earliest) < 0) earliest = text;
                    if (string.IsNullOrEmpty(latest) || Comparer.Compare(text, latest) > 0) latest = text;
                }
            }
        }
        string status = totalEvents == 0 ? "empty" : "ok";
        return Result(D("schema", "cucp.audit-summary/v1", "status", status,
            "file_count", files.Length, "event_count", totalEvents, "earliest_ts", earliest, "latest_ts", latest,
            "by_macro", byMacro, "by_exit_code", byExit, "sensitive_count", sensitiveCount,
            "blocked_count", blockedCount, "since_cutoff", cutoff is null ? null : cutoffText), 0, 8,
            $"{status} audit-summary files={files.Length} events={totalEvents} sensitive={sensitiveCount} blocked={blockedCount}");
    }

    private static bool DiagnosticTryDate(JsonElement value, out DateTimeOffset date)
    {
        // PowerShell's [datetime] conversion uses invariant parsing, rather than
        // lexicographic ordering; the original earliest/latest fields do not.
        return value.ValueKind == JsonValueKind.String
            ? DateTimeOffset.TryParse(S(value), CultureInfo.InvariantCulture, DateTimeStyles.AllowWhiteSpaces, out date)
            : DiagnosticNoDate(out date);
    }

    private static bool DiagnosticNoDate(out DateTimeOffset date) { date = default; return false; }
    private static DateTimeOffset DiagnosticFileDate(JsonElement value) =>
        DiagnosticTryDate(value, out var date) ? date : DateTimeOffset.MinValue;

    private static JsonElement DiagnosticEventProperty(JsonElement value, string property)
    {
        if (value.ValueKind != JsonValueKind.Array) return P(value, property);
        // Member enumeration in PowerShell preserves each present property's
        // scalar/array contents, then interpolation joins them with spaces.
        var values = new List<JsonElement>();
        foreach (var member in A(value))
        {
            var found = DiagnosticEventProperty(member, property);
            if (found.ValueKind is not (JsonValueKind.Null or JsonValueKind.Undefined)) values.AddRange(A(found));
        }
        return values.Count switch { 0 => Null, 1 => values[0], _ => J(values) };
    }

    private static bool DiagnosticEventEquals(JsonElement value, string expected) =>
        value.ValueKind == JsonValueKind.Array ? A(value).Any(v => Eq(v, expected) && T(v)) : Eq(value, expected);

    private static readonly Regex DiagnosticLogErrorFilter = new("ERROR|TIMEOUT|FAIL|throw|exit\\s+(?:1|2|3|124)", RegexOptions.Compiled);
    private static readonly Regex DiagnosticLogErrorCount = new("ERROR|TIMEOUT|FAIL", RegexOptions.Compiled);
    private static readonly Regex[] DiagnosticLogRedactors = new[]
    {
        @"password\s*=\s*\S{1,256}", @"passwd\s*=\s*\S{1,256}", @"pwd\s*=\s*\S{1,256}",
        @"secret\s*=\s*\S{1,256}", @"token\s*=\s*\S{1,256}", @"apikey\s*=\s*\S{1,256}",
        @"api_key\s*=\s*\S{1,256}", @"authorization:\s*\S{1,256}", @"Bearer\s+\S{1,256}",
        @"eyJ[A-Za-z0-9_\-]{20,512}\.[A-Za-z0-9_\-]{1,512}\.[A-Za-z0-9_\-]{1,512}"
    }.Select(pattern => new Regex(pattern, RegexOptions.Compiled | RegexOptions.IgnoreCase)).ToArray();

    private LegacyDiagnosticResult LogTail()
    {
        int requestedLines = I(V("--lines"));
        if (requestedLines <= 0) requestedLines = 50;
        int maxBytes = I(V("--max-bytes"));
        if (maxBytes <= 0) maxBytes = 262144;
        string? pathOverride = V("--path");
        string path = Has(pathOverride) ? pathOverride! : S(P(context, "wrapper_log"));
        bool errorsOnly = F("--errors-only");
        if (!Exists(path))
        {
            if (RenderBrief) return Result(null, 2, 6, $"partial log-tail no-log-file path='{path}'");
            return Result(DiagnosticLogEnvelope("partial", 0, D("path", path, "lines", Array.Empty<string>()),
                [D("code", "log_missing", "message", $"log not found: {path}", "recommended_action",
                    "Run any cucp command first to materialize the audit log, or pass --path <file>.")]), 2, 6);
        }

        Start("log-tail");
        JsonElement tail;
        try { tail = Effect(LegacyDiagnosticEffectKind.TailBytes, data: D("path", path, "max_bytes", maxBytes)); }
        catch (LegacyDiagnosticEffectException ex)
        {
            if (RenderBrief) return Result(null, 2, 6, $"partial log-tail read_failed: {ex.Message}");
            return Result(DiagnosticLogEnvelope("partial", Elapsed("log-tail"), D("path", path),
                [D("code", "log_read_failed", "message", ex.Message, "recommended_action", "Verify file is readable and not exclusively locked.")]), 2, 6);
        }
        long totalBytes = L(P(tail, "total_bytes"));
        int tailBytes = I(P(tail, "tail_bytes"));
        IEnumerable<string> allLines = Regex.Split(S(P(tail, "text")), @"(?:\r\n|\n|\r)");
        if (totalBytes > tailBytes) allLines = allLines.Skip(1);
        var rawLines = allLines.Where(line => line.Length != 0).TakeLast(requestedLines);
        if (errorsOnly) rawLines = rawLines.Where(line => DiagnosticLogErrorFilter.IsMatch(line));

        int redactedCount = 0;
        var cleaned = new List<string>();
        foreach (string line in rawLines)
        {
            string current = line;
            foreach (var pattern in DiagnosticLogRedactors)
            {
                if (!pattern.IsMatch(current)) continue;
                current = pattern.Replace(current, "[redacted]");
                // The legacy counter counts matching pattern/line pairs, not
                // replacement occurrences (or unique redacted lines).
                redactedCount++;
            }
            cleaned.Add(current);
        }
        int errorCount = cleaned.Count(DiagnosticLogErrorCount.IsMatch);
        int elapsed = Stop("log-tail");
        if (RenderBrief)
        {
            string line = $"ok log-tail lines={cleaned.Count} bytes_read={tailBytes} errors={errorCount} redacted={redactedCount} elapsed_ms={elapsed}";
            if (cleaned.Count != 0) line += Environment.NewLine + string.Join(Environment.NewLine, cleaned.Select(value => "  | " + value));
            return Result(null, 0, 6, line);
        }
        return Result(DiagnosticLogEnvelope("ok", elapsed, D("path", path, "total_bytes", totalBytes,
            "bytes_read", tailBytes, "max_bytes", maxBytes, "requested_lines", requestedLines,
            "returned_lines", cleaned.Count, "errors_only", errorsOnly, "error_count", errorCount,
            "redacted_count", redactedCount, "lines", cleaned.ToArray()), []), 0, 6);
    }

    private object DiagnosticLogEnvelope(string status, int elapsed, object data, object[] recoverableErrors) =>
        D("schema", "cucp.observation/v1", "kind", "log-tail", "status", status,
            "collected_at", Now(), "elapsed_ms", elapsed, "sources", new[] { "file" }, "provenance", null,
            "observation_id", "", "foreground", null, "active_hwnd", 0L, "focused_title", "",
            "desktop", null, "windows", null, "data", data, "cache", null, "stale", false,
            "confidence", "high", "warnings", Array.Empty<string>(), "recoverable_errors", recoverableErrors,
            "degraded_helper_empty", false);

    private static readonly (string Pattern, string Replacement)[] DiagnosticReleaseRedactors =
    [
        (@"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{16,}", "[REDACTED:github_pat]"),
        (@"\bsk-[A-Za-z0-9]{20,}", "[REDACTED:openai_key]"),
        (@"\bAKIA[A-Z0-9]{16}\b", "[REDACTED:aws_key]"),
        (@"(?i)bearer\s+[A-Za-z0-9_\-\.=]{20,}", "[REDACTED:bearer]"),
        (@"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}", "[REDACTED:jwt]"),
        (@"-----BEGIN [A-Z ]+PRIVATE KEY-----", "[REDACTED:pem_block]")
    ];

    private LegacyDiagnosticResult ReleaseNotes()
    {
        string? version = V("--version"), since = V("--since");
        string changelogPath = S(P(context, "changelog_path"));
        var resolved = Effect(LegacyDiagnosticEffectKind.ResolvePath, data: changelogPath);
        if (!T(resolved)) throw new InvalidOperationException($"macro release-notes: CHANGELOG.md not found at {changelogPath}");
        string path = S(resolved);
        var raw = A(Effect(LegacyDiagnosticEffectKind.ReadLines, data: path));
        var sections = new List<(string Version, List<string> Body)>();
        foreach (var rawLine in raw)
        {
            string line = S(rawLine);
            var match = Regex.Match(line, @"^##\s+v?(\d+\.\d+\.\d+)", RegexOptions.IgnoreCase);
            if (match.Success) sections.Add((match.Groups[1].Value, new List<string>()));
            else if (sections.Count != 0) sections[^1].Body.Add(line);
        }
        IEnumerable<(string Version, List<string> Body)> filtered = [];
        if (Has(version)) filtered = sections.Where(section => Comparer.Equals(section.Version, version));
        else if (Has(since))
        {
            string[] parts = since!.Split('.');
            if (parts.Length >= 3)
            {
                long minimum = DiagnosticVersionNumber(parts);
                filtered = sections.Where(section => DiagnosticVersionNumber(section.Version.Split('.')) >= minimum);
            }
        }
        else filtered = sections.Take(1);

        var notes = new List<object>();
        var versions = new List<string>();
        foreach (var section in filtered)
        {
            var added = new List<string>();
            var improved = new List<string>();
            var verified = new List<string>();
            var fixedItems = new List<string>();
            string? current = null;
            foreach (string line in section.Body)
            {
                var category = Regex.Match(line, @"^###\s+(Added|Improved|Verified|Fixed|Why|Internal|Documentation|Tests|Limits)", RegexOptions.IgnoreCase);
                if (category.Success) { current = category.Groups[1].Value; continue; }
                var bullet = Regex.Match(line, @"^-\s+(.+)$", RegexOptions.IgnoreCase);
                if (!bullet.Success) continue;
                string item = bullet.Groups[1].Value;
                foreach (var (pattern, replacement) in DiagnosticReleaseRedactors) item = Regex.Replace(item, pattern, replacement);
                if (Comparer.Equals(current, "Added")) added.Add(item);
                else if (Comparer.Equals(current, "Improved")) improved.Add(item);
                else if (Comparer.Equals(current, "Verified")) verified.Add(item);
                else if (Comparer.Equals(current, "Fixed")) fixedItems.Add(item);
            }
            versions.Add(section.Version);
            notes.Add(D("version", section.Version, "highlights", added.Take(3).Concat(improved.Take(2)).Take(5).ToArray(),
                "added", added.ToArray(), "improved", improved.ToArray(), "verified", verified.ToArray(), "fixed", fixedItems.ToArray()));
        }
        string filter = Has(version) ? $"version={version}" : Has(since) ? $"since={since}" : "latest";
        const string migration = "v1.4.0: 새 매크로 9개 추가 (cdp-deep-find, ime-paste, safe-type-ime, modal-detect, recovery-plan, recovery-run, precision-validate, benchmark, release-notes). 기존 매크로 호환성 영향 없음. DOM bridge v2 (Shadow DOM/iframe traversal) 자동 적용.";
        const string usage = "AI agent loop: Observe (windows/find-label) -> Plan (smart-plan/task-plan) -> Act (-AllowLiveControl + safety gate -> click-label/safe-type-ime) -> Verify (modal-detect/precision-validate) -> Recover (recovery-run --confirm-sensitive).";
        return Result(D("schema", P(context, "release_schema"), "status", "ok", "changelog_path", path,
            "total_versions_in_changelog", sections.Count, "filter", filter, "note_count", notes.Count, "notes", notes.ToArray(),
            "migration_notes", migration, "external_agent_usage", usage), 0, 10,
            $"ok release-notes notes={notes.Count} versions={string.Join(",", versions)}", renderBrief: brief);
    }

    private static long DiagnosticVersionNumber(string[] parts) => (long)I(parts[0]) * 10000 + (long)I(parts[1]) * 100 + I(parts[2]);
}
