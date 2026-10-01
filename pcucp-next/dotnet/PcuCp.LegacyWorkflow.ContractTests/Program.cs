using System.Text.Json;

var options = new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };
if (args.SequenceEqual(new[] { "--fixtures" }))
{
    // Test-only data protocol, entirely independent of native desktop dispatch.
    var buffer = new char[1024 * 1024 + 1];
    var count = 0;
    while (count < buffer.Length)
    {
        var read = Console.In.Read(buffer, count, buffer.Length - count);
        if (read == 0) break;
        count += read;
    }
    if (count == buffer.Length) return 2;
    using var doc = JsonDocument.Parse(new string(buffer, 0, count));
    var results = new List<object>();
    foreach (var fixture in doc.RootElement.EnumerateArray())
    {
        try
        {
            results.Add(fixture.GetProperty("kind").GetString() switch
            {
                "parse" => LegacyWorkflowKernel.ParseStep(fixture.GetProperty("step").GetString()!),
                "specs" => new { specs = LegacyWorkflowKernel.ReadStepSpecs(fixture.GetProperty("rest").EnumerateArray().Select(v => v.GetString()!).ToArray()) },
                "plan" => LegacyWorkflowKernel.Plan(JsonSerializer.SerializeToElement(new { rest = fixture.GetProperty("rest") })),
                _ => throw CommandOptions.Invalid("Unsupported test fixture kind.")
            });
        }
        catch (NativeFailure failure) { results.Add(new { threw = true, error = failure.Code }); }
    }
    Console.WriteLine(JsonSerializer.Serialize(results, options));
    return 0;
}
if (args.Length != 0) return 2;

var checks = 0;
void Check(bool value, string message) { if (!value) throw new Exception(message); checks++; }
JsonElement Plan(params string[] rest) => JsonSerializer.SerializeToElement(LegacyWorkflowKernel.Plan(JsonSerializer.SerializeToElement(new { rest })), options);
void Reject(string text, string code)
{
    var result = LegacyWorkflowKernel.ParseStep(text);
    Check(!result.Ok && result.Error == code && result.Tokens.Length == 0, "Expected rejection: " + text);
}
var plan = Plan("--name", "Example", "--step", "macro windows", "--step", "macro type-native --text 'hello'", "--step", "macro registry --read");
Check(plan.GetProperty("schema").GetString() == "cucp.workflow-plan/v1", "Plan schema");
Check(plan.GetProperty("name").GetString() == "Example", "Plan name");
Check(plan.GetProperty("safe_to_run").GetBoolean(), "Structurally valid live plan remains a plan");
Check(plan.GetProperty("live_step_count").GetInt32() == 2, "Live count");
Check(plan.GetProperty("sensitive_step_count").GetInt32() == 1, "Sensitive count");
Check(plan.GetProperty("requires_sensitive_confirmation").GetBoolean(), "Sensitive confirmation");
foreach (var action in new[] { "info", "helper-status", "autostart-status", "INFO" })
    Check(Plan("--step", "macro session " + action).GetProperty("safe_to_run").GetBoolean(), "Read-only session action");
foreach (var action in new[] { "start", "stop", "restart", "autostart-enable", "--json-only" })
{
    var blocked = Plan("--step", "macro session " + action);
    Check(!blocked.GetProperty("safe_to_run").GetBoolean(), "Mutating session blocked");
    Check(blocked.GetProperty("live_step_count").GetInt32() == 1, "Blocked session still counted live");
}
foreach (var name in new[] { "workflow-plan", "workflow-run", "WORKFLOW-RUN", "unknown", "task-run" })
    Check(!Plan("--step", "macro " + name).GetProperty("safe_to_run").GetBoolean(), "No allowlist expansion");
var parsed = LegacyWorkflowKernel.ParseStep("macro type-native --text '한글 it''s' --empty \"\" --next `" + "\"quoted`\"");
Check(parsed.Ok && parsed.Tokens.Contains("한글 it's") && !parsed.Tokens.Contains(""), "Quotes/empty strings");
Check(LegacyWorkflowKernel.ParseStep("macro type-native --text \"a`nb\"").Tokens.Last() == "a\nb", "PS5 escape");
Check(LegacyWorkflowKernel.ParseStep("macro type-native --text \"`e`u{41}\"").Tokens.Last() == "eu{41}", "No PS6 escape semantics");
Check(LegacyWorkflowKernel.ParseStep("macro windows `\n --json-only").Ok, "Whitespace line continuation");
Check(LegacyWorkflowKernel.ReadStepSpecs(["ignored", "--STEP", "macro", "windows", "--step", ""]).SequenceEqual(new[] { "macro windows", "" }), "Rest grouping");
Reject("", "empty_step");
Reject("''", "empty_step");
Reject("macro windows; macro registry", "unsupported_token");
Reject("macro windows | anything", "unsupported_token");
Reject("macro windows > file", "unsupported_token");
Reject("macro windows -Name value", "unsupported_token");
Reject("macro windows $env:PATH", "unsupported_token");
Reject("macro windows $(anything)", "unsupported_token");
Reject("macro type-native --text \"unterminated", "parse_error");
Reject("'macro' windows", "parse_error");
var empty = Plan("--step", "", "--step", "macro windows");
Check(empty.GetProperty("step_count").GetInt32() == 1 && empty.GetProperty("errors")[0].GetProperty("index").GetInt32() == 1, "Preserve raw indices after rejected step");
Check(!empty.GetProperty("safe_to_run").GetBoolean(), "Rejected parse invalidates plan");
try { Plan(); throw new Exception("Missing --step accepted"); } catch (NativeFailure) { checks++; }
Console.WriteLine($"PASS: {checks} pure workflow candidate checks; no plan was executed. Full PowerShell parser parity is not established.");
return 0;
