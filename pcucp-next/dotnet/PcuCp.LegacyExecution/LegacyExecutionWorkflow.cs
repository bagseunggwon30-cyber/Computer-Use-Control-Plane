using System.Text.Json;

internal sealed partial class LegacyExecutionCoordinator
{
    private LegacyExecutionResult Workflow()
    {
        bool dry = F("--dry-run"), include = F("--include-plan"), confirm = Confirm, verify = F("--verify-after-step"), observe = F("--observe-after-step") || verify;
        bool retryLive = F("--retry-live-steps"), keepGoing = F("--continue-on-error");
        string? match = V("--observe-match"), verifyMatch = V("--verify-match"), label = V("--verify-label-after-step"), labelWindow = V("--verify-label-window");
        if (!Has(label)) label = V("--verify-after-label"); if (!Has(match) && Has(verifyMatch)) match = verifyMatch;
        int settle = Math.Clamp(I(V("--settle-ms")), 0, 10000), retries = Math.Clamp(I(V("--retry-failed-step")), 0, 5), delay = Math.Clamp(I(V("--retry-delay-ms")), 0, 10000);
        int timeout = Math.Clamp(Has(V("--verify-label-timeout-ms")) ? I(V("--verify-label-timeout-ms")) : 1500, 100, 30000);
        int interval = Math.Clamp(Has(V("--verify-label-interval-ms")) ? I(V("--verify-label-interval-ms")) : 250, 50, 5000);
        Start("total"); var plan = Effect(LegacyExecutionEffectKind.WorkflowPlan, argv: PlanArgs(true));
        if (!dry && I(P(plan, "live_step_count")) > 0) Live("macro workflow-run requires -AllowLiveControl when live steps are present");
        var steps = A(P(plan, "steps")); var sensitive = steps.Where(s => T(P(s, "requires_sensitive_confirmation"))).ToArray();
        if (!dry && sensitive.Length > 0 && !confirm)
        {
            int elapsed = Stop("total"); var issues = sensitive.Select(s => D("index", P(s, "index"), "macro", P(s, "macro"), "command", P(s, "command"),
                "risk_level", P(P(s, "safety"), "risk_level"), "risk_score", I(P(P(s, "safety"), "risk_score")), "categories", A(P(P(s, "safety"), "categories")), "recommended_action", P(P(s, "safety"), "recommended_action"))).ToArray();
            return Result(D("schema", "cucp.workflow-run/v1", "status", "blocked", "reason", "sensitive_action_requires_confirmation", "dry_run", dry,
                "confirm_sensitive", confirm, "confirmation_flag", "--confirm-sensitive", "executed_count", 0, "failed_count", 0, "verify_failed_count", 0,
                "retry_count", 0, "sensitive_step_count", sensitive.Length, "safety_issues", issues, "elapsed_ms", elapsed, "plan", include ? plan : null,
                "steps", Array.Empty<object>(), "next_action", "Re-run with --confirm-sensitive only if the user explicitly approved these exact sensitive live actions."), 3, 14,
                $"blocked workflow-run reason=sensitive_action_requires_confirmation sensitive={sensitive.Length}");
        }
        void Options(Dictionary<string, object?> p)
        {
            p.Add("retry_failed_step", retries); p.Add("retry_delay_ms", delay); p.Add("retry_live_steps", retryLive); p.Add("confirm_sensitive", confirm);
            p.Add("verify_label_after_step", label); p.Add("verify_label_window", labelWindow); p.Add("verify_label_timeout_ms", timeout); p.Add("verify_label_interval_ms", interval);
            p.Add("settle_ms", settle); p.Add("observe_after_step", observe); p.Add("verify_after_step", verify); p.Add("observe_match", match);
        }
        if (!T(P(plan, "safe_to_run")) || dry)
        {
            int elapsed = Stop("total"); bool safe = T(P(plan, "safe_to_run"));
            var p = D("schema", "cucp.workflow-run/v1", "status", safe ? "ready" : "blocked", "reason", safe ? "dry_run" : "plan_not_safe", "dry_run", dry,
                "executed_count", 0, "failed_count", 0, "verify_failed_count", 0, "retry_count", 0);
            Options(p); p.Add("elapsed_ms", elapsed); p.Add("plan", safe || include ? plan : null); if (!safe) p.Add("errors", A(P(plan, "errors"))); p.Add("steps", Array.Empty<object>());
            return Result(p, safe ? 0 : 3, 12, safe ? $"ready workflow-run dry-run steps={S(P(plan, "step_count"))} live={S(P(plan, "live_step_count"))}" : $"blocked workflow-run reason=plan_not_safe errors={A(P(plan, "errors")).Length}");
        }
        var results = new List<Dictionary<string, object?>>(); int executed = 0, failed = 0, verifyFailed = 0, retryCount = 0;
        foreach (var step in steps)
        {
            Start("step"); var attempts = new List<Dictionary<string, object?>>(); bool live = T(P(step, "live_required")); string skipped = "";
            JsonElement last = Null, observation = Null, observationRaw = Null, observationExit = Null, labelExit = Null, labelRaw = Null;
            string verificationStatus = "not_requested", labelStatus = "not_requested"; bool stepFailed;
            do
            {
                int attempt = attempts.Count + 1; Start("attempt"); var child = Strings(P(step, "command")).ToList(); if (live && confirm) child.Add("--confirm-sensitive");
                last = Child(child, live, confirm: live && confirm); bool uncertain = Uncertain(last); if (!uncertain && settle > 0) Sleep(settle);
                observation = observationRaw = observationExit = labelExit = labelRaw = Null; verificationStatus = labelStatus = "not_requested";
                if (observe && !uncertain)
                {
                    var args = new List<string> { "macro", "windows", "--json-only" }; if (Has(match)) args.AddRange(["--match", match!]);
                    var obs = Child(args); observationExit = J(I(P(obs, "exit"))); if (T(Parsed(obs))) observation = Parsed(obs); else observationRaw = P(obs, "raw");
                    verificationStatus = verify ? I(observationExit) == 0 ? "ok" : "partial" : I(observationExit) == 0 ? "observed" : "observe_partial";
                }
                if (Has(label) && !uncertain)
                {
                    var args = new List<string> { "macro", "wait-label", "--label", label!, "--timeout-ms", timeout.ToString(), "--interval-ms", interval.ToString() };
                    if (Has(labelWindow)) args.AddRange(["--window", labelWindow!]); else if (Has(match)) args.AddRange(["--window", match!]);
                    var lr = Child(args, childBrief: true); labelExit = J(I(P(lr, "exit"))); labelRaw = P(lr, "raw"); labelStatus = I(labelExit) == 0 ? "ok" : "partial";
                }
                int elapsed = Stop("attempt"); stepFailed = uncertain || I(P(last, "exit")) != 0 || verify && observationExit.ValueKind != JsonValueKind.Null && I(observationExit) != 0 || Has(label) && labelExit.ValueKind != JsonValueKind.Null && I(labelExit) != 0;
                attempts.Add(D("attempt", attempt, "status", stepFailed ? "partial" : "ok", "exit", P(last, "exit"), "elapsed_ms", elapsed,
                    "result", Parsed(last), "raw", Raw(last), "verification_status", verificationStatus, "post_observation_exit", observationExit,
                    "post_observation", observation, "post_observation_raw", observationRaw, "label_verification_status", labelStatus, "label_verification_exit", labelExit, "label_verification_raw", labelRaw));
                if (uncertain) { skipped = "mutation_may_have_occurred"; break; }
                if (!stepFailed || retries <= 0 || attempt - 1 >= retries) break;
                if (live && !retryLive) { skipped = "live_step_retry_requires_retry_live_steps"; break; }
                retryCount++; if (delay > 0) Sleep(delay);
            } while (true);
            int stepElapsed = Stop("step"); executed++; if (stepFailed) failed++;
            if (stepFailed && (verify && observationExit.ValueKind != JsonValueKind.Null && I(observationExit) != 0 || Has(label) && labelExit.ValueKind != JsonValueKind.Null && I(labelExit) != 0)) verifyFailed++;
            results.Add(D("index", P(step, "index"), "macro", P(step, "macro"), "live_required", live, "command", A(P(step, "command")), "status", stepFailed ? "partial" : "ok",
                "exit", P(last, "exit"), "elapsed_ms", stepElapsed, "attempt_count", attempts.Count, "retry_count", Math.Max(0, attempts.Count - 1), "retry_skipped_reason", skipped,
                "attempts", attempts, "result", Parsed(last), "raw", Raw(last), "settle_ms", settle, "verification_status", verificationStatus, "post_observation_exit", observationExit,
                "post_observation", observation, "post_observation_raw", observationRaw, "label_verification_status", labelStatus, "label_verification_exit", labelExit, "label_verification_raw", labelRaw));
            if (Uncertain(last) || stepFailed && !keepGoing) break;
        }
        int total = Stop("total"); string status = failed == 0 && executed == I(P(plan, "step_count")) ? "ok" : "partial", next = ""; object? failureSummary = null;
        if (status != "ok")
        {
            var failedStep = results.FirstOrDefault(r => (string)r["status"]! != "ok");
            if (failedStep is not null)
            {
                var f = J(failedStep); string kind = "command_failed", evidence = "";
                if (Eq(P(f, "retry_skipped_reason"), "mutation_may_have_occurred"))
                {
                    kind = "mutation_may_have_occurred"; evidence = "mutation_may_have_occurred=True";
                    next = "Inspect the target and re-ground before deciding whether another action is safe.";
                }
                else if (P(f, "label_verification_exit").ValueKind != JsonValueKind.Null && I(P(f, "label_verification_exit")) != 0)
                {
                    kind = "label_verification_failed"; evidence = S(P(f, "label_verification_raw"));
                    next = $"Run macro find-label --label '{label}' with the right --match/--window, or increase --verify-label-timeout-ms after confirming the expected UI label should appear.";
                }
                else if (P(f, "post_observation_exit").ValueKind != JsonValueKind.Null && I(P(f, "post_observation_exit")) != 0)
                {
                    kind = "window_verification_failed"; evidence = $"post_observation_exit={S(P(f, "post_observation_exit"))}";
                    next = $"Run macro windows --match '{(Has(match) ? match : verifyMatch)}' to confirm the target window, or adjust --verify-match/--observe-match before retrying.";
                }
                else if (T(P(f, "retry_skipped_reason")))
                {
                    kind = "retry_skipped"; evidence = S(P(f, "retry_skipped_reason")); next = "Live step retry was skipped. Use --retry-live-steps only if repeating this action is safe and idempotent.";
                }
                else
                {
                    var errors = A(P(P(f, "result"), "recoverable_errors")); string recommendation = errors.Length > 0 ? S(P(errors[0], "recommended_action")) : "";
                    next = Has(recommendation) ? recommendation : "Inspect the failed step result, then run macro windows or list-affordances to re-ground before retrying the workflow.";
                }
                failureSummary = D("step_index", P(f, "index"), "macro", P(f, "macro"), "failure_kind", kind, "exit", P(f, "exit"), "status", P(f, "status"),
                    "attempt_count", P(f, "attempt_count"), "retry_count", P(f, "retry_count"), "retry_exhausted", retries > 0 && I(P(f, "retry_count")) >= retries,
                    "verification_status", P(f, "verification_status"), "label_verification_status", P(f, "label_verification_status"), "evidence", evidence, "next_action", next);
            }
            else next = "No failed step was captured. Re-run with --include-plan and inspect raw workflow output.";
        }
        var payload = D("schema", "cucp.workflow-run/v1", "status", status, "reason", status == "ok" ? "" : "step_failed_or_stopped", "next_action", next, "failure_summary", failureSummary,
            "dry_run", false, "executed_count", executed, "failed_count", failed, "verify_failed_count", verifyFailed, "retry_count", retryCount,
            "retry_failed_step", retries, "retry_delay_ms", delay, "retry_live_steps", retryLive, "confirm_sensitive", confirm, "sensitive_step_count", I(P(plan, "sensitive_step_count")),
            "verify_label_after_step", label, "verify_label_window", labelWindow, "verify_label_timeout_ms", timeout, "verify_label_interval_ms", interval,
            "total_steps", P(plan, "step_count"), "settle_ms", settle, "observe_after_step", observe, "verify_after_step", verify, "observe_match", match, "elapsed_ms", total, "plan", include ? plan : null, "steps", results);
        Append("workflow-run", D("status", status, "executed_count", executed, "failed_count", failed, "total_steps", P(plan, "step_count"), "elapsed_ms", total));
        return Result(payload, status == "ok" ? 0 : 2, 14, $"{status} workflow-run executed={executed} failed={failed} total={S(P(plan, "step_count"))} elapsed_ms={total}");
    }
}
