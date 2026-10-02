using System.Text.Json;

internal sealed partial class LegacyExecutionCoordinator
{
    private LegacyExecutionResult TaskRun()
    {
        bool dry = F("--dry-run"), include = F("--include-plan"), confirm = Confirm;
        Start("total");
        var planReply = Child(new[] { "macro", "task-plan" }.Concat(PlanArgs()).Append("--json-only"));
        var plan = Parsed(planReply);
        Dictionary<string, object?> Base(string status, string reason, int elapsed) => D("schema", "cucp.task-run/v1", "status", status,
            "reason", reason, "dry_run", dry, "confirm_sensitive", confirm, "executed", false, "elapsed_ms", elapsed);
        if (!T(plan))
        {
            var p = Base("error", "task_plan_unparseable", Stop("total")); p.Add("plan_exit", P(planReply, "exit")); p.Add("plan_raw", P(planReply, "raw"));
            return Result(p, 1, 8, renderBrief: false);
        }
        if (!T(P(plan, "safe_to_run")))
        {
            var p = Base("blocked", "task_plan_not_safe", Stop("total")); p.Add("plan", include ? plan : null); p.Add("plan_errors", A(P(plan, "errors")));
            return Result(p, 3, 16, $"blocked task-run reason=task_plan_not_safe errors={A(P(plan, "errors")).Length}");
        }
        bool live = !dry && I(P(plan, "live_step_count")) > 0;
        if (live) Live("macro task-run requires -AllowLiveControl when live steps are present");
        string[] command = Strings(P(plan, dry ? "dry_run_command" : "recommended_command"));
        if (command.Length == 0)
        {
            var p = Base("blocked", "missing_recommended_command", Stop("total")); p.Add("plan", include ? plan : null);
            return Result(p, 3, 12, "blocked task-run reason=missing_recommended_command");
        }
        var child = command.ToList();
        if (F("--continue-on-error") && !dry) child.Add("--continue-on-error");
        if (confirm && !dry) child.Add("--confirm-sensitive");
        if (include) child.Add("--include-plan"); child.Add("--json-only");
        Start("run"); var run = Child(child, live, confirm: confirm && !dry); int runElapsed = Stop("run"), elapsed = Stop("total");
        var json = Parsed(run); int exit = I(P(run, "exit"));
        string runStatus = T(json) && T(P(json, "status")) ? S(P(json, "status")) : exit == 0 ? "ok" : "partial";
        string status = dry ? exit == 0 ? "ready" : "blocked" : exit == 0 && (Comparer.Equals(runStatus, "ok") || Comparer.Equals(runStatus, "ready")) ? "ok" : exit == 3 ? "blocked" : "partial";
        if (Uncertain(run)) status = "partial";
        var payload = Base(status, status is "ok" or "ready" ? "" : "workflow_failed_or_blocked", elapsed);
        payload["executed"] = !dry && exit != 3;
        payload.Add("task_plan", include || dry ? plan : null); payload.Add("workflow_exit", exit); payload.Add("workflow_elapsed_ms", runElapsed);
        payload.Add("workflow_failure_summary", T(json) ? P(json, "failure_summary") : null);
        payload.Add("next_action", T(json) && T(P(json, "next_action")) ? S(P(json, "next_action")) : status is "partial" or "blocked" ? "Inspect workflow_result and re-ground with macro windows/list-affordances before retrying." : "");
        payload.Add("workflow_result", json); payload.Add("workflow_raw", Raw(run));
        Append("task-run", D("status", status, "dry_run", dry, "workflow_exit", exit, "elapsed_ms", elapsed));
        return Result(payload, status is "ok" or "ready" ? 0 : status == "blocked" ? 3 : 2, 18,
            $"{status} task-run dry_run={dry} workflow_exit={exit} elapsed_ms={elapsed}");
    }

    private LegacyExecutionResult FormRun()
    {
        bool dry = F("--dry-run"), include = F("--include-plan"), confirm = Confirm, keepGoing = F("--continue-on-error");
        if (!dry) Live("macro form-run requires -AllowLiveControl");
        Start("total"); var planReply = Child(new[] { "macro", "form-plan" }.Concat(PlanArgs()).Append("--json-only")); var plan = Parsed(planReply);
        Dictionary<string, object?> Base(string status, string reason, int elapsed) => D("schema", "cucp.form-run/v1", "status", status,
            "reason", reason, "dry_run", dry, "confirm_sensitive", confirm, "elapsed_ms", elapsed);
        if (!T(plan))
        {
            var p = Base("error", "plan_unparseable", Stop("total")); p.Add("plan_exit", P(planReply, "exit")); p.Add("plan_raw", P(planReply, "raw")); p.Add("steps", Array.Empty<object>());
            return Result(p, 1, 8, renderBrief: false);
        }
        if (!T(P(plan, "safe_to_act")))
        {
            int elapsed = Stop("total"); var p = Base("blocked", "plan_not_safe", elapsed);
            p.Add("safe_to_act", false); p.Add("executed_count", 0); p.Add("failed_count", 0); p.Add("plan_exit", P(planReply, "exit"));
            p.Add("unsafe_steps", A(P(plan, "unsafe_steps"))); p.Add("plan_errors", A(P(plan, "errors"))); p.Add("plan", include ? plan : null); p.Add("steps", Array.Empty<object>());
            return Result(p, 3, 16, $"blocked form-run reason=plan_not_safe safe={S(P(plan, "safe_step_count"))}/{S(P(plan, "step_count"))} elapsed_ms={elapsed}");
        }
        var commands = A(P(plan, "command_plan"));
        if (dry)
        {
            int elapsed = Stop("total"); var p = Base("ready", "dry_run", elapsed);
            p.Add("safe_to_act", true); p.Add("executed_count", 0); p.Add("failed_count", 0); p.Add("command_plan", commands); p.Add("plan", include ? plan : null); p.Add("steps", Array.Empty<object>());
            return Result(p, 0, 16, $"ready form-run dry-run steps={S(P(plan, "step_count"))} elapsed_ms={elapsed}");
        }
        var sensitive = new List<object>();
        foreach (var step in commands)
        {
            var cmd = A(P(step, "command")); string macro = cmd.Length >= 2 && Eq(cmd[0], "macro") ? S(cmd[1]) : "";
            var safety = J(LegacySafetyKernel.Classify(J(new { text = string.Join(" ", cmd.Select(S).Concat([S(P(step, "kind")), S(P(step, "label"))])), macro })));
            if (T(P(safety, "requires_explicit_confirmation"))) sensitive.Add(D("index", P(step, "index"), "kind", P(step, "kind"), "label", P(step, "label"),
                "macro", macro, "command", cmd, "risk_level", P(safety, "risk_level"), "risk_score", I(P(safety, "risk_score")), "categories", A(P(safety, "categories")), "recommended_action", P(safety, "recommended_action")));
        }
        if (sensitive.Count > 0 && !confirm)
        {
            var p = Base("blocked", "sensitive_action_requires_confirmation", Stop("total")); p.Add("safe_to_act", false); p.Add("executed_count", 0); p.Add("failed_count", 0);
            p.Add("sensitive_step_count", sensitive.Count); p.Add("safety_issues", sensitive); p.Add("confirmation_flag", "--confirm-sensitive"); p.Add("plan", include ? plan : null); p.Add("steps", Array.Empty<object>());
            p.Add("next_action", "Re-run with --confirm-sensitive only if the user explicitly approved these exact sensitive form actions.");
            return Result(p, 3, 16, $"blocked form-run reason=sensitive_action_requires_confirmation sensitive={sensitive.Count}");
        }
        var results = new List<object>(); int executed = 0, failed = 0;
        foreach (var step in commands)
        {
            var cmd = A(P(step, "command")); Start("step");
            Dictionary<string, object?> Step(string status, string reason, object? exit, int ms, object? result, object? raw) =>
                D("index", P(step, "index"), "kind", P(step, "kind"), "label", P(step, "label"), "route", P(step, "route"), "status", status, "reason", reason,
                    "exit", exit, "elapsed_ms", ms, "command", cmd, "result", result, "raw", raw);
            if (!T(P(step, "safe_to_act")) || cmd.Length == 0 || !Eq(cmd[0], "macro"))
            {
                int ms = Stop("step"); failed++; results.Add(Step("blocked", "unsafe_or_invalid_command", 3, ms, null, null));
                if (!keepGoing) break; continue;
            }
            // Legacy form-run did not append the sensitive flag to child argv.
            // Approval remains immutable context for the typed child transport.
            var reply = Child(cmd.Select(S), live: true); int elapsed = Stop("step"); executed++;
            int exit = I(P(reply, "exit")); var json = Parsed(reply); bool uncertain = Uncertain(reply); if (exit != 0 || uncertain) failed++;
            results.Add(Step(exit == 0 && !uncertain ? "ok" : "partial", uncertain ? "mutation_may_have_occurred" : T(json) && T(P(json, "reason")) ? S(P(json, "reason")) : exit == 0 ? "" : "command_failed", P(reply, "exit"), elapsed, json, Raw(reply)));
            if (uncertain || exit != 0 && !keepGoing) break;
        }
        int totalElapsed = Stop("total"); string status = failed == 0 && executed == commands.Length ? "ok" : "partial";
        var payload = Base(status, status == "ok" ? "" : "step_failed_or_stopped", totalElapsed); payload.Add("safe_to_act", true); payload.Add("executed_count", executed); payload.Add("failed_count", failed);
        payload.Add("total_steps", commands.Length); payload.Add("plan_elapsed_ms", I(P(plan, "elapsed_ms"))); payload.Add("command_plan", commands); payload.Add("plan", include ? plan : null); payload.Add("steps", results);
        Append("form-run", D("status", status, "executed_count", executed, "failed_count", failed, "total_steps", commands.Length, "elapsed_ms", totalElapsed));
        return Result(payload, status == "ok" ? 0 : 2, 16, $"{status} form-run executed={executed} failed={failed} total={commands.Length} elapsed_ms={totalElapsed}");
    }
}
