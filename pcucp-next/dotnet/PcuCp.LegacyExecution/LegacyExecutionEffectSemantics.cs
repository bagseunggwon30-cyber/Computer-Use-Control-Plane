using System.Text.Json;

// Outcome accounting only: this never grants AllowLiveControl, sensitive consent,
// a filesystem destination, or permission to retry. Host descriptor validation is
// still mandatory. A read-only desktop observation may write owned audit/cache files.
internal static class LegacyExecutionEffectSemantics
{
    internal static bool MayChangeState(LegacyExecutionEffect effect)
    {
        if (effect.Live) return true;
        return effect.Kind switch
        {
            LegacyExecutionEffectKind.HistoryAppend or LegacyExecutionEffectKind.TrajectoryAppend or
            LegacyExecutionEffectKind.RemoveFile or LegacyExecutionEffectKind.PointCacheWrite or
            LegacyExecutionEffectKind.AnchorAppend or LegacyExecutionEffectKind.Appshot or
            LegacyExecutionEffectKind.Notice => true, // Write-Notice also appends the wrapper log.

            // Child starts the full retained wrapper (including startup/log/cache
            // writes), even for planning/observation argv. Cucp invokes the CLI;
            // Vision writes schema/output files through the retained model helper.
            LegacyExecutionEffectKind.Child or LegacyExecutionEffectKind.Cucp or LegacyExecutionEffectKind.Vision => true,

            // The only proven read-only local macro is direct UIA icon-find. The
            // other registered local macro is click-point; unknown names stay
            // conservative here and remain rejected by the closed host dispatch.
            LegacyExecutionEffectKind.LocalMacro => !Same(effect.Name, "icon-find"),
            // Even read actions may create redirected cache files, append timeout/
            // pipe logs, or remove a stale helper lock in Invoke-NativeHelper.
            // Best-effort cleanup does not establish a retry-safe ephemeral boundary.
            LegacyExecutionEffectKind.Native => true,
            LegacyExecutionEffectKind.Diagnostic => Diagnostic(effect),
            _ => false
        };
    }

    private static bool Same(string? left, string right) => string.Equals(left, right, StringComparison.Ordinal);
    private static bool Diagnostic(LegacyExecutionEffect effect)
    {
        if (Same(effect.Name, "AuditProbe") || Same(effect.Name, "ClearAppshotCache") || Same(effect.Name, "Appshot") || Same(effect.Name, "Notice")) return true;
        // Diagnostic dispatch uses the same retained helpers. Invoke-Cucp logs
        // before path validation and retains stdout/stderr capture files even for
        // version/tools. Their command labels cannot prove absence of owned writes.
        if (Same(effect.Name, "Cli") || Same(effect.Name, "Native") || Same(effect.Name, "HelperUp")) return true;
        // Assert-Authorized emits Notice/log records even for its expected denial.
        // The diagnostic adapter returns that known denial as a completed Boolean;
        // classifying dispatch here only affects lost/failed outcome accounting.
        if (Same(effect.Name, "AssertAuthorized")) return true;
        // Diagnostic adapter wraps the fixed macro name beside its own data.
        // Never scan arbitrary strings/argv values for command or consent tokens.
        if (!Same(effect.Name, "Macro") || effect.Data.ValueKind != JsonValueKind.Object ||
            !effect.Data.TryGetProperty("name", out var name) || name.ValueKind != JsonValueKind.String) return false;
        return Same(name.GetString(), "health-quick") || Same(name.GetString(), "find-label") ||
            (Same(name.GetString(), "windows") && effect.Argv.Length == 1 && Same(effect.Argv[0], "--rich"));
    }
}
