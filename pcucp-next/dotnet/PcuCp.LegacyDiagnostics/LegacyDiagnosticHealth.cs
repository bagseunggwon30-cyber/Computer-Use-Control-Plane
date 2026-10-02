using System.Text.Json;
using System.Text.RegularExpressions;

internal sealed partial class LegacyDiagnosticCoordinator
{
    private (bool Ok, string Version) NodeVersion()
    {
        try
        {
            var reply = Effect(LegacyDiagnosticEffectKind.NodeVersion);
            if (I(P(reply, "exit")) == 0 && T(P(reply, "output"))) return (true, S(P(reply, "output")).Trim());
        }
        catch (LegacyDiagnosticEffectException) { }
        return (false, "");
    }
    private bool AuditProbe(string prefix)
    {
        try { Effect(LegacyDiagnosticEffectKind.AuditProbe, prefix, data: paths.AuditDirectory); return true; }
        catch (LegacyDiagnosticEffectException) { return false; }
    }
    private LegacyDiagnosticResult HealthQuick()
    {
        Start("health-quick"); string now = Now();
        var (nodeOk, nodeVer) = NodeVersion();
        bool cliOk = Has(paths.CliPath) && Exists(paths.CliPath);
        bool auditOk = AuditProbe(".health-quick-probe-");
        bool win32Ok = T(Effect(LegacyDiagnosticEffectKind.EnsureWin32));
        bool pressureOk = true; int cacheFiles = 0, tempFiles = 0; long logBytes = 0;
        try
        {
            if (Exists(paths.CacheDirectory)) cacheFiles = A(Files(paths.CacheDirectory)).Length;
            if (Exists(paths.AuditDirectory)) tempFiles = A(Files(paths.AuditDirectory, recurse: true)).Length;
            if (Exists(paths.WrapperLog)) logBytes = L(P(Effect(LegacyDiagnosticEffectKind.FileStat, data: paths.WrapperLog), "length"));
            if (cacheFiles > 1000 || tempFiles > 2000 || logBytes > 64L * 1024 * 1024) pressureOk = false;
        }
        catch (LegacyDiagnosticEffectException) { }
        int timeouts = 0; bool tailOk = true;
        if (Exists(paths.WrapperLog))
        {
            try { timeouts = Regex.Matches(S(P(Effect(LegacyDiagnosticEffectKind.TailBytes, data: D("path", paths.WrapperLog, "max_bytes", 65536)), "text")), "TIMEOUT").Count; }
            catch (LegacyDiagnosticEffectException) { tailOk = false; }
        }
        int elapsed = Stop("health-quick"); bool ok = nodeOk && cliOk && auditOk && win32Ok;
        string status = ok ? "ok" : "fail";
        var components = D("node", D("ok", nodeOk, "version", nodeVer), "cli", D("ok", cliOk, "path", paths.CliPath),
            "audit_dir", D("ok", auditOk, "path", paths.AuditDirectory), "win32_enum", D("ok", win32Ok),
            "temp_pressure", D("ok", pressureOk, "cache_files", cacheFiles, "temp_files", tempFiles, "wrapper_log_bytes", logBytes,
                "tip", pressureOk ? "" : "Run 'cucp macro cleanup --dry-run' to preview, then '--execute'."),
            "recent_timeouts", D("ok", tailOk && timeouts <= 5, "count", timeouts, "sample_bytes", 65536,
                "tip", timeouts > 5 ? "Run 'cucp macro ensure-helper' or raise -InvokeTimeoutMs." : ""));
        return Result(D("status", status, "collected_at", now, "components", components, "elapsed_ms", elapsed,
            "note", "lightweight surface; for helper/codex/uia checks use macro health-detail"), ok ? 0 : 1, 6,
            $"{status} health-quick node={nodeOk} cli={cliOk} audit={auditOk} win32={win32Ok} cache={cacheFiles} timeouts={timeouts} elapsed_ms={elapsed}");
    }
    private LegacyDiagnosticResult HealthDetail()
    {
        string now = Now(); var (nodeOk, nodeVer) = NodeVersion();
        bool cliOk = Has(paths.CliPath) && Exists(paths.CliPath);
        bool verOk = false; string verNum = "";
        try { var r = Cli("version"); if (T(Parsed(r)) && Eq(P(Parsed(r), "status"), "ok")) { verOk = true; verNum = S(P(Parsed(r), "version")); } }
        catch (LegacyDiagnosticEffectException) { }
        bool helperOk = T(Effect(LegacyDiagnosticEffectKind.HelperUp));
        bool uiaOk = T(Effect(LegacyDiagnosticEffectKind.EnsureUia));
        var codex = Effect(LegacyDiagnosticEffectKind.FindCodex); bool codexOk = codex.ValueKind != JsonValueKind.Null;
        bool auditOk = AuditProbe(".health-probe-");
        var components = D("node", D("ok", nodeOk, "version", nodeVer), "cli", D("ok", cliOk, "path", paths.CliPath),
            "cucp_version", D("ok", verOk, "version", verNum), "helper", D("ok", helperOk, "tip", helperOk ? "" : "run 'cucp ensure-helper' or 'cucp start'"),
            "uia_fallback", D("ok", uiaOk), "codex_vision", D("ok", codexOk, "cli", codex, "tip", codexOk ? "" : "install codex CLI for vision fallback"),
            "audit_dir", D("ok", auditOk, "path", paths.AuditDirectory));
        int passed = new[] { nodeOk, cliOk, verOk, helperOk, uiaOk, codexOk, auditOk }.Count(v => v);
        bool ok = nodeOk && cliOk && verOk && auditOk;
        string status = ok ? passed == 7 ? "ok" : "ok_partial_optional" : "fail";
        return Result(D("status", status, "collected_at", now, "components", components, "required_ok", ok,
            "optional_ok", passed == 7, "passed", passed, "total", 7), ok ? 0 : 1, 6,
            $"{status} health passed={passed}/7 helper={helperOk} codex={codexOk}");
    }
    private LegacyDiagnosticResult SelfTest()
    {
        bool deep = F("--deep"), strict = F("--strict"); var results = new List<object>();
        void Add(string name, string tier, string outcome, string detail) => results.Add(D("name", name, "tier", tier, "outcome", outcome, "detail", detail));
        Effect(LegacyDiagnosticEffectKind.Notice, "INFO", data: $"self-test 시작 (deep={deep}, strict={strict})");
        foreach (var gate in new[] {
            ("live_gate_blocks", new[] { "act", "click", "--x", "0", "--y", "0", "--after", "fake" }, "blocked-without-AllowLiveControl"),
            ("coord_gate_requires_after", new[] { "act", "click", "--x", "100", "--y", "100" }, "blocked-without-after") })
        {
            bool blocked = false;
            try { Effect(LegacyDiagnosticEffectKind.AssertAuthorized, argv: gate.Item2); }
            catch (LegacyDiagnosticEffectException) { blocked = true; }
            Add(gate.Item1, "wrapper", blocked ? "ok" : "fail", gate.Item3);
        }
        try { var r = Cli("version"); Add("cli_version", "cli", Success(r) ? "ok" : "fail", "v" + S(P(Parsed(r), "version"))); }
        catch (LegacyDiagnosticEffectException e) { Add("cli_version", "cli", "fail", e.Message); }
        bool helper = false;
        try
        {
            var r = Cli("tools");
            if (Success(r)) { helper = true; Add("helper_tools", "helper", "ok", "tools available"); }
            else { string error = T(P(Parsed(r), "error_type")) ? S(P(Parsed(r), "error_type")) : "unreachable"; Add("helper_tools", "helper", "skipped", $"helper not running ({error}) - run 'cucp start' to enable helper-tier tests"); }
        }
        catch (LegacyDiagnosticEffectException e) { Add("helper_tools", "helper", "skipped", e.Message); }
        if (helper)
        {
            try { var r = Cli("observe", "windows"); Add("observe_windows", "helper", Success(r) ? "ok" : "fail", "status=" + S(P(Parsed(r), "status"))); }
            catch (LegacyDiagnosticEffectException e) { Add("observe_windows", "helper", "fail", e.Message); }
            try
            {
                Effect(LegacyDiagnosticEffectKind.Appshot, data: D("match", "selftest-cache", "semantic", false, "no_cache", true, "cache_max_seconds", null));
                string key = S(Effect(LegacyDiagnosticEffectKind.CacheKey, data: "selftest-cache"));
                string path = paths.CacheDirectory.TrimEnd('\\', '/') + "\\appshot-" + key + ".json";
                bool exists = Exists(path);
                if (!exists) Add("cache_hit", "helper", "fail", "cache file not written: " + path);
                else
                {
                    var r = Effect(LegacyDiagnosticEffectKind.Appshot, data: D("match", "selftest-cache", "semantic", false, "no_cache", false, "cache_max_seconds", 600));
                    Add("cache_hit", "helper", r.ValueKind != JsonValueKind.Null && T(P(r, "FromCache")) ? "ok" : "fail", "from_cache=" + S(P(r, "FromCache")) + " cacheFile=" + exists);
                }
            }
            catch (LegacyDiagnosticEffectException e) { Add("cache_hit", "helper", "fail", e.Message); }
        }
        else { Add("observe_windows", "helper", "skipped", "skipped: helper not running"); Add("cache_hit", "helper", "skipped", "skipped: helper not running"); }
        if (deep)
        {
            try { int count = Math.Max(1, A(Effect(LegacyDiagnosticEffectKind.Uia, data: D("focused_window", "", "max_elements", 50))).Length); Add("uia_fallback", "uia", count > 0 ? "ok" : "fail", "uia_affordances=" + count); }
            catch (LegacyDiagnosticEffectException e) { Add("uia_fallback", "uia", "fail", e.Message); }
            if (helper)
            {
                try
                {
                    var shot = Effect(LegacyDiagnosticEffectKind.Appshot, data: D("match", "", "semantic", true, "no_cache", true, "cache_max_seconds", null));
                    int count = T(P(shot, "Affordances")) ? A(P(shot, "Affordances")).Length : 0;
                    Add("appshot_fullscreen", "helper", shot.ValueKind != JsonValueKind.Null && T(P(shot, "ObservationId")) ? "ok" : "fail", "affordances=" + count + " obs_id=" + S(P(shot, "ObservationId")));
                }
                catch (LegacyDiagnosticEffectException e) { Add("appshot_fullscreen", "helper", "fail", e.Message); }
            }
            else Add("appshot_fullscreen", "helper", "skipped", "skipped: helper not running");
        }
        int passed = results.Count(v => Eq(P(J(v), "outcome"), "ok")), failed = results.Count(v => Eq(P(J(v), "outcome"), "fail")), skipped = results.Count - passed - failed;
        bool ok = strict ? passed == results.Count : failed == 0; string status = ok ? "ok" : "fail";
        string summary = ok && skipped > 0 ? $"wrapper/cli/uia tiers passing; {skipped} helper-tier test(s) skipped (run 'cucp start' to include)" : ok ? "all tiers passing" : $"{failed} test(s) failed";
        return Result(D("status", status, "summary", summary, "passed", passed, "failed", failed, "skipped", skipped,
            "total", results.Count, "helper_running", helper, "deep", deep, "strict", strict, "results", results), ok ? 0 : 1, 6,
            $"{status} self-test passed={passed}/{results.Count} skipped={skipped} failed={failed}", renderBrief: brief);
    }
}
