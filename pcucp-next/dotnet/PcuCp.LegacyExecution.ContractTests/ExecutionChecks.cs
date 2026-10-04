using System.Text.Json;

internal static class ExecutionChecks
{
    internal static void Run()
    {
        int checks = 0;
        void Check(bool ok, string message) { checks++; if (!ok) throw new InvalidOperationException(message); }
        static JsonElement J(object? x) => JsonSerializer.SerializeToElement(x);
        static JsonElement Evaluate(object value) => J(ExecutionFixture.Evaluate(J(value)));
        static object Reply(object? json, int exit = 0) => new { json, exit, raw = "raw 한글" };
        static object Plan(int count = 1, bool live = false) => new { safe_to_run = true, step_count = count, live_step_count = live ? count : 0, sensitive_step_count = 0,
            steps = Enumerable.Range(1, count).Select(i => new { index = i, macro = "windows", live_required = live, command = new[] { "macro", "windows" } }).ToArray() };
        foreach (var value in new object?[] { null, false, true, "", "한글", 2, new object[0], new object?[] { null }, new[] { "single" }, new { value = new[] { "data" }, Count = 1 }, new object[] { new object[0], new[] { 1 } } })
        {
            var original = J(value); var decoded = LegacyExecutionWire.Decode(J(LegacyExecutionWire.Encode(original)));
            Check(original.GetRawText() == decoded.GetRawText(), "Tagged runtime values must preserve shape and scalar kind");
        }
        foreach (var bad in new[] { "{\"kind\":\"scalar\",\"value\":[]}", "{\"kind\":\"array\",\"items\":null}", "{\"kind\":\"object\",\"properties\":[],\"live\":true}", "{\"kind\":\"scalar\",\"value\":1,\"value\":2}", "{\"kind\":\"object\",\"properties\":[{\"name\":\"x\",\"value\":{\"kind\":\"scalar\",\"value\":1}},{\"name\":\"x\",\"value\":{\"kind\":\"scalar\",\"value\":2}}]}" })
        {
            bool rejected = false; try { using var parsed = JsonDocument.Parse(bad); LegacyExecutionWire.Decode(parsed.RootElement); } catch (LegacyExecutionProtocolException) { rejected = true; }
            Check(rejected, "Malformed typed wire accepted");
        }
        foreach (var live in new[] { false, true }) foreach (var retryLive in new[] { false, true }) foreach (var retries in new[] { 0, 1, 5, 99 })
        {
            var rest = new List<string> { "--retry-failed-step", retries.ToString() }; if (retryLive) rest.Add("--retry-live-steps");
            var captures = new List<object> { Plan(live: live) }; captures.AddRange(Enumerable.Repeat(Reply(new { status = "partial" }, 2), 6));
            var r = Evaluate(new { operation = "workflow-run", rest, allow_live = true, replies = captures });
            Check(r.GetProperty("state").GetString() == "complete", "Retry fixture failed");
            int expected = live && !retryLive ? 1 : 1 + Math.Min(retries, 5);
            Check(r.GetProperty("payload").GetProperty("steps")[0].GetProperty("attempt_count").GetInt32() == expected, "Explicit live retry restriction or six-attempt limit changed");
            Check(r.GetProperty("exit").GetInt32() == 2, "Failed attempts became success");
        }
        foreach (var operation in new[] { "workflow-run", "form-run", "recovery-run", "smart-click" })
        {
            var r = Evaluate(new { operation, rest = new[] { "--label", "Name" }, allow_live = false, replies = new[] { Plan(live: true) } });
            Check(r.GetProperty("state").GetString() == "error", "Missing authority must reject");
            Check(!r.GetProperty("effects").EnumerateArray().Any(e => e.GetProperty("live").GetBoolean()), "A plan granted live authority");
        }
        foreach (var option in new[] { "--label", "--text", "--type-text", "--field", "--match", "--click-label", "--send-label", "--step", "--failed-step", "--args", "--app-args", "--selector" })
        {
            Check(!LegacyExecutionConsent.HasStandaloneConfirmation([option, "--confirm-sensitive"]), "An option value became sensitive consent");
            Check(LegacyExecutionConsent.HasStandaloneConfirmation([option, "--confirm-sensitive", "--confirm-sensitive"]), "A genuine following flag was lost");
        }
        Check(LegacyExecutionConsent.HasStandaloneConfirmation(["--CONFIRM-SENSITIVE"]), "Original case-insensitive genuine flag changed");
        foreach (var operation in new[] { "task-run", "form-run" })
        {
            var blocked = Evaluate(new { operation, rest = new[] { "--include-plan" }, allow_live = true, replies = new[] { Reply(new { }, 2) } });
            var payload = blocked.GetProperty("payload");
            Check(payload.GetProperty("plan_errors").GetRawText() == "[null]", "Direct report array must preserve the absent errors value as one null");
            if (operation == "form-run") Check(payload.GetProperty("unsafe_steps").GetRawText() == "[null]", "Direct report array must preserve absent unsafe steps");
        }
        foreach (bool dry in new[] { false, true }) foreach (bool brief in new[] { false, true })
        {
            var missing = Evaluate(new { operation = "task-run", rest = dry ? new[] { "--include-plan", "--dry-run" } : new[] { "--include-plan" }, brief,
                replies = new[] { Reply(new { safe_to_run = true, live_step_count = 0, recommended_command = new object?[] { null }, dry_run_command = new object?[] { null } }) } });
            Check(missing.GetProperty("payload").GetProperty("reason").GetString() == "missing_recommended_command", "Singleton null pipeline command must be blocked");
            Check(missing.GetProperty("consumed").GetInt32() == 1 && missing.GetProperty("effects").GetArrayLength() == 1, "Singleton null command must not execute or append trajectory");
        }
        var largeCaptures = new List<object> { Plan(256) }; largeCaptures.AddRange(Enumerable.Repeat(Reply(new { status = "partial", blob = new string('x', 1024) }, 2), 1536));
        var large = Evaluate(new { operation = "workflow-run", rest = new[] { "--continue-on-error", "--retry-failed-step", "5" }, replies = largeCaptures });
        Check(large.GetProperty("consumed").GetInt32() == 1537, "Large workflow capture schedule truncated");
        Check(large.GetProperty("payload").GetRawText().Length > 1048576, "Large workflow did not exceed old bridge limit");
        foreach (var step in large.GetProperty("payload").GetProperty("steps").EnumerateArray()) Check(step.GetProperty("attempt_count").GetInt32() == 6, "Large workflow lost attempts");
        // Read-only session fixture requests one workflow plan, then emits the dry-run report.
        object Envelope(object? value) => new { state = "ok", value = LegacyExecutionWire.Encode(J(value)) };
        string Frames(long id, object value)
        {
            var bytes = JsonSerializer.SerializeToUtf8Bytes(value); var lines = new List<string>();
            for (int i = 0; i < bytes.Length; i += 49152) lines.Add(JsonSerializer.Serialize(new { kind = "part", id, data = Convert.ToBase64String(bytes, i, Math.Min(49152, bytes.Length - i)) }));
            lines.Add(JsonSerializer.Serialize(new { kind = "end", id })); return string.Join("\n", lines) + "\n";
        }
        var input = Frames(1, Envelope(0)) + Frames(2, Envelope(Plan())) + Frames(3, Envelope(37));
        var writer = new StringWriter(); var session = new LegacyExecutionSession(new StringReader(input), writer);
        Check(session.Run("workflow-run", ["--dry-run"], new(false, false)) == 0, "Stateful dry-run failed");
        Check(writer.ToString().Contains("\"target\":\"complete\""), "Session omitted completion");
        writer = new StringWriter(); session = new(new StringReader(Frames(2, Envelope(0))), writer);
        Check(session.Run("workflow-run", [], new(false, false)) == 1, "Out-of-order effect reply accepted");
        writer = new StringWriter(); session = new(new StringReader(""), writer);
        Check(session.Run("workflow-run", [], new(false, false)) == 1, "Disconnected effect stream must fail without retry");
        SessionDispatchChecks.Run(Check);
        Console.WriteLine($"Passed {checks} execution family checks; no live input, child command, history write or sleep executed.");
    }
}
