using System.Text.Json;

internal sealed partial class LegacyExecutionCoordinator
{
    private LegacyExecutionResult Watch()
    {
        int interval = I(V("--interval-ms")), maximum = I(V("--max-cycles"));
        string? until = V("--until-label"), match = V("--match");
        if (interval <= 0) interval = 500; if (maximum <= 0) maximum = 20;
        var cycles = new List<object>(); var lines = new List<string>(); string previousTitle = ""; long previousHwnd = 0; bool found = false;
        for (int i = 1; i <= maximum; i++)
        {
            var focused = Parsed(Native("-Action", "focused")); string title = ""; long hwnd = 0;
            if (T(focused) && T(P(focused, "foreground"))) { title = S(P(P(focused, "foreground"), "title")); var raw = P(P(focused, "foreground"), "hwnd"); hwnd = raw.ValueKind == JsonValueKind.Null ? 0 : Convert.ToInt64(S(raw), System.Globalization.CultureInfo.InvariantCulture); }
            string delta = i == 1 ? "init" : Comparer.Equals(title, previousTitle) && hwnd == previousHwnd ? "same" : "changed";
            bool has = false;
            if (Has(until)) has = Eq(P(Parsed(Native("-Action", "uia-find", "-Match", Has(match) ? match! : title, "-Label", until!)), "status"), "ok");
            if (brief) { var line = $"cycle={i} title='{title}' delta={delta}" + (Has(until) ? $" until='{until}'={has}" : ""); lines.Add(line); Effect(LegacyExecutionEffectKind.Console, data: line); }
            cycles.Add(D("cycle", i, "title", title, "hwnd", hwnd, "delta", delta, "until_label_present", Has(until) ? has : null,
                "collected_at", Effect(LegacyExecutionEffectKind.Timestamp, "o")));
            if (Has(until) && has) { found = true; break; }
            previousTitle = title; previousHwnd = hwnd; if (i < maximum) Sleep(interval);
        }
        int exit = Has(until) && !found ? 2 : 0;
        var payload = D("schema", "cucp.watch/v1", "status", exit == 0 ? "ok" : "partial", "until_label", until, "until_label_found", found, "cycles", cycles);
        return new(J(payload), exit, 6, null, !brief);
    }
    private JsonElement Modal(string? match)
    {
        try { var args = new List<string> { "-Action", "modal-detect" }; if (Has(match)) args.AddRange(["-Match", match!]); var value = Parsed(Native(args.ToArray())); return T(value) ? value : Null; }
        catch (LegacyExecutionEffectException) { return Null; }
    }
    private static JsonElement ModalTop(JsonElement modal) => T(modal) && T(P(modal, "candidate_count")) && I(P(modal, "candidate_count")) > 0 ? A(P(modal, "modal_candidates")).FirstOrDefault(Null) : Null;
    private LegacyExecutionResult RecoveryPlan()
    {
        var modal = Modal(V("--match")); JsonElement foreground = Null;
        try { var raw = Parsed(Native("-Action", "focused")); if (T(raw)) foreground = raw; } catch (LegacyExecutionEffectException) { }
        var candidates = new List<object>(); var top = ModalTop(modal); int score = T(P(top, "score")) ? I(P(top, "score")) : 0;
        object Candidate(int rank, string action, string method, string command, bool live, string evidence) => D("rank", rank, "action", action, "method", method, "command", command, "live", live, "sensitive", live, "evidence", evidence);
        if (T(top))
        {
            if (T(P(top, "is_modal")) || score >= 100)
            {
                candidates.Add(Candidate(1, "dismiss_modal", "shortcut", "macro shortcut --keys \"escape\"", true, $"modal:{S(P(top, "title"))} score:{score}"));
                candidates.Add(Candidate(2, "confirm_modal", "shortcut", "macro shortcut --keys \"enter\"", true, $"modal:{S(P(top, "title"))}"));
            }
            else if (score >= 60)
            {
                candidates.Add(Candidate(1, "observe_dialog", "modal-detect", "macro modal-detect", false, $"dialog_class:{S(P(top, "class"))}"));
                candidates.Add(Candidate(2, "find_dialog_button", "find-label", "macro find-label --label \"OK\" --explain", false, $"dialog_score:{score}"));
            }
        }
        if (candidates.Count == 0)
        {
            candidates.Add(Candidate(1, "re_observe", "windows", "macro windows", false, "no_modal_detected"));
            if (Has(V("--failed-step"))) candidates.Add(Candidate(2, "retry_failed_step", "as_provided", V("--failed-step")!, true, "user_provided_step"));
        }
        string next = S(P(J(candidates[0]), "action"));
        return Result(D("schema", "cucp.recovery-plan/v1", "status", "ok", "modal", modal, "foreground", foreground,
            "failed_step", V("--failed-step"), "failed_reason", V("--failed-reason"), "recovery_candidates", candidates,
            "candidate_count", candidates.Count, "recommended", candidates[0], "next_action", next), 0, 10,
            $"ok recovery-plan candidates={candidates.Count} next={next}", brief);
    }
    private LegacyExecutionResult RecoveryRun()
    {
        bool dry = F("--dry-run"), confirm = Confirm; if (!dry) Live("macro recovery-run requires -AllowLiveControl (or --dry-run)");
        var modal = Modal(V("--match")); var top = ModalTop(modal); int score = T(P(top, "score")) ? I(P(top, "score")) : 0;
        bool live = T(top) && (T(P(top, "is_modal")) || score >= 100); string action = live ? "dismiss_modal" : "observe", command = live ? "shortcut:escape" : "macro windows";
        if (live && !confirm && !dry) return Result(D("schema", "cucp.recovery-run/v1", "status", "blocked", "reason", "sensitive_recovery_requires_confirmation",
            "recommended_action", action, "recommended_command", command, "next_action", "Re-run with --confirm-sensitive only after explicit user approval."), 3, 10,
            "blocked recovery-run reason=sensitive_recovery_requires_confirmation", brief);
        if (dry) return Result(D("schema", "cucp.recovery-run/v1", "status", "ready", "dry_run", true, "recommended_action", action,
            "recommended_command", command, "requires_live", live, "modal_candidate_count", T(P(modal, "candidate_count")) ? I(P(modal, "candidate_count")) : 0), 0, 10,
            $"ready recovery-run dry-run action={action}", brief);
        object execution;
        if (live)
        {
            try { Effect(LegacyExecutionEffectKind.SendEscape, live: true, confirm: true); Sleep(80); execution = D("method", "sendkeys_esc", "status", "ok"); }
            catch (LegacyExecutionEffectException error) { execution = D("method", "sendkeys_esc", "status", "error", "detail", error.Message); }
        }
        else execution = D("method", "observe_only", "status", "ok");
        string status = Eq(P(J(execution), "status"), "ok") ? "ok" : "partial";
        return Result(D("schema", "cucp.recovery-run/v1", "status", status, "executed_action", action, "execution", execution, "modal_before", modal), status == "ok" ? 0 : 2, 10, $"{status} recovery-run action={action}", brief);
    }
}
