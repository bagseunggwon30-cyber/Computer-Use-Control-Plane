using System.Text.Json;

// A closed acquisition surface. No arbitrary command, script, write path, process
// mutation, registry, registration or authenticated model capability is exposed.
internal enum LegacyDiagnosticEffectKind
{
    Clock, Timestamp, FileExists, ListFiles, FileStat, ReadLines, ReadText, TailBytes, ResolvePath,
    NodeVersion, Cli, Native, Macro, AuditProbe, EnsureWin32, EnsureUia, HelperUp,
    FindCodex, Processes, ProcessorCount, Windows, Sleep, ClearAppshotCache,
    AssertAuthorized, Appshot, CacheKey, Uia, Notice
}
internal sealed record LegacyDiagnosticEffect(LegacyDiagnosticEffectKind Kind, string Name, string[] Argv, JsonElement Data);
internal interface ILegacyDiagnosticEffects { JsonElement Invoke(LegacyDiagnosticEffect effect); }
internal sealed class LegacyDiagnosticEffectException(string message) : Exception(message);
internal sealed record LegacyDiagnosticResult(JsonElement Payload, int Exit, int JsonDepth, string? Brief, bool EmitJson, string[] HashtablePaths);

// Immutable owned-path ceilings originate at the trusted host, never in replies.
// The optional perf cache clear is allowed only for the original invocation flag.
internal sealed record LegacyDiagnosticContext(string AuditDirectory, string CacheDirectory,
    string WrapperLog, string CliPath, string ChangelogPath, string TempRoot,
    string BenchmarkSchema = "cucp.benchmark/v1", string ReleaseSchema = "cucp.release-notes/v1");
