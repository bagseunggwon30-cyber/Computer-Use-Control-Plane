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
                "plan-from-parsed" => LegacyWorkflowKernel.PlanFromParsed(JsonSerializer.SerializeToElement(new
                {
                    rest = fixture.GetProperty("rest"), parsed_steps = fixture.GetProperty("parsed_steps")
                })),
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
Reject("macro windows --", "unsupported_token");
Check(LegacyWorkflowKernel.ParseStep("macro windows '--'").Tokens.Last() == "--", "Quoted double dash stays literal");
Check(LegacyWorkflowKernel.ParseStep("macro windows `--").Tokens.Last() == "--", "Escaped double dash stays literal");
Reject("macro windows $env:PATH", "unsupported_token");
Reject("macro windows $(anything)", "unsupported_token");
Reject("macro type-native --text \"unterminated", "parse_error");
Reject("'macro' windows", "parse_error");
var empty = Plan("--step", "", "--step", "macro windows");
Check(empty.GetProperty("step_count").GetInt32() == 1 && empty.GetProperty("errors")[0].GetProperty("index").GetInt32() == 1, "Preserve raw indices after rejected step");
Check(!empty.GetProperty("safe_to_run").GetBoolean(), "Rejected parse invalidates plan");
try { Plan(); throw new Exception("Missing --step accepted"); } catch (NativeFailure) { checks++; }
JsonElement FromParsed(object value) => JsonSerializer.SerializeToElement(LegacyWorkflowKernel.PlanFromParsed(JsonSerializer.SerializeToElement(value)), options);
var originalDetail = "원래 오류: '$name'\nline 1, character 20";
var fromParsed = FromParsed(new
{
    rest = new[] { "--name", "actual parser", "--step", "broken original", "--step", "macro type-native --text \"hello $name\"" },
    parsed_steps = new object[]
    {
        new { ok = false, error = "parse_error", detail = originalDetail, tokens = Array.Empty<string>() },
        new { ok = true, error = "", detail = "", tokens = new[] { "macro", "type-native", "--text", "hello $name" } }
    }
});
Check(fromParsed.GetProperty("errors")[0].GetProperty("message").GetString() == originalDetail, "Preserve exact original parser diagnostic");
Check(fromParsed.GetProperty("errors")[0].GetProperty("code").GetString() == "parse_error", "Preserve parser error code");
Check(fromParsed.GetProperty("steps")[0].GetProperty("index").GetInt32() == 2, "Preserve actual parser index");
Check(fromParsed.GetProperty("steps")[0].GetProperty("command")[3].GetString() == "hello $name", "Use actual parser tokens without candidate reinterpretation");
Check(!fromParsed.GetProperty("safe_to_run").GetBoolean(), "Parser failure still blocks plan");
void RejectParsed(string json)
{
    using var doc = JsonDocument.Parse(json);
    try { LegacyWorkflowKernel.PlanFromParsed(doc.RootElement); throw new Exception("Malformed parsed result accepted: " + json); }
    catch (NativeFailure failure) { Check(failure.Code == "invalid_arguments", "Malformed parsed code"); }
}
foreach (var json in new[]
{
    "{}", "[]", "{\"rest\":[],\"parsed_steps\":[]}",
    "{\"rest\":[\"--step\",\"macro windows\"],\"parsed_steps\":[]}",
    "{\"rest\":[\"--step\",\"macro windows\"],\"parsed_steps\":[{\"ok\":true,\"ok\":false,\"error\":\"\",\"detail\":\"\",\"tokens\":[\"windows\"]}]}",
    "{\"rest\":[\"--step\",\"macro windows\"],\"parsed_steps\":[{\"ok\":true,\"error\":\"\",\"detail\":\"\",\"tokens\":[]}]}",
    "{\"rest\":[\"--step\",\"macro windows\"],\"parsed_steps\":[{\"ok\":true,\"error\":\"\",\"detail\":\"\",\"tokens\":[\"\"]}]}",
    "{\"rest\":[\"--step\",\"macro windows\"],\"parsed_steps\":[{\"ok\":false,\"error\":\"not_in_baseline\",\"detail\":\"\",\"tokens\":[]}]}",
    "{\"rest\":[\"--step\",\"macro windows\"],\"parsed_steps\":[{\"ok\":false,\"error\":\"parse_error\",\"detail\":\"\",\"tokens\":[\"windows\"]}]}",
    "{\"rest\":[\"--step\",\"macro windows\"],\"parsed_steps\":[{\"ok\":1,\"error\":\"\",\"detail\":\"\",\"tokens\":[\"windows\"]}]}",
    "{\"rest\":[\"--step\",\"macro windows\"],\"parsed_steps\":[{\"ok\":true,\"error\":\"parse_error\",\"detail\":\"\",\"tokens\":[\"windows\"]}]}",
    "{\"rest\":[\"--step\",\"macro windows\"],\"parsed_steps\":[{\"ok\":true,\"error\":\"\",\"detail\":\"\",\"tokens\":[3]}]}"
}) RejectParsed(json);
RejectParsed(JsonSerializer.Serialize(new { rest = new[] { "--step", "macro windows" },
    parsed_steps = new[] { new { ok = true, error = "", detail = "", tokens = new[] { new string('x', 65537) } } } }));
RejectParsed(JsonSerializer.Serialize(new { rest = new[] { "--step", "macro windows" },
    parsed_steps = new[] { new { ok = true, error = "", detail = "", tokens = Enumerable.Repeat("x", 4097).ToArray() } } }));

bool Matches(LegacyWorkflowKernel.ParsedStep actual, JsonElement expected) =>
    actual.Ok == expected.GetProperty("ok").GetBoolean() &&
    actual.Error == expected.GetProperty("error").GetString() &&
    actual.Tokens.SequenceEqual(expected.GetProperty("tokens").EnumerateArray().Select(token => token.GetString()!));
using var observations = JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "workflow-ps51-observed.json")));
var observed = observations.RootElement;
Check(observed.GetProperty("provenance").GetProperty("evidence").GetString() == "observed-windows-powershell-5.1", "Observed evidence label");
var targets = observed.GetProperty("batch_target_steps").EnumerateArray().Select(value => value.GetString()!).ToHashSet(StringComparer.Ordinal);
var historicalCount = 0;
var resolvedCount = 0;
foreach (var fixture in observed.GetProperty("historical_gaps").EnumerateArray())
{
    historicalCount++;
    var step = fixture.GetProperty("step").GetString()!;
    var expected = fixture.GetProperty("before");
    var actual = LegacyWorkflowKernel.ParseStep(step);
    var matches = Matches(actual, expected);
    if (matches) resolvedCount++;
    Check(!actual.Ok || matches, "Do not relax or reinterpret an observed PS5.1 result: " + step);
    if (targets.Contains(step)) Check(matches, "Observed literal batch regression: " + step);
}
Check(historicalCount == 25 && targets.Count == 6, "Immutable historical gap and batch target counts");
Console.WriteLine($"Historical PS5.1 replay: {resolvedCount}/{historicalCount} known gaps now match; {historicalCount - resolvedCount} remain. This is not a new Windows qualification run.");

using var inferences = JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "workflow-literal-inferred.json")));
Check(inferences.RootElement.GetProperty("evidence").GetString() == "inferred-unqualified", "Inferred evidence remains distinct");
var inferredCount = 0;
foreach (var fixture in inferences.RootElement.GetProperty("cases").EnumerateArray())
{
    inferredCount++;
    var actual = LegacyWorkflowKernel.ParseStep(fixture.GetProperty("step").GetString()!);
    Check(Matches(actual, fixture.GetProperty("candidate")), "Inferred managed contract: " + fixture.GetProperty("id").GetString());
}
Reject("macro type-native --text \"a\0b\"", "unsupported_token");
Reject("macro type-native --text @'\na\0b\n'@", "unsupported_token");
Reject("macro type-native --text @'\n" + new string('x', 65536) + "\n'@", "unsupported_token");
var dollarPlan = Plan("--step", "macro type-native --text \"$env:PATH $(inspect)\"");
Check(dollarPlan.GetProperty("steps")[0].GetProperty("command")[3].GetString() == "$env:PATH $(inspect)", "Dollar text stays literal plan data");
Console.WriteLine($"Inferred managed literal contracts: {inferredCount}; Windows PowerShell 5.1 qualification remains required.");
Console.WriteLine($"PASS: {checks} pure workflow candidate checks; no plan was executed. Full PowerShell parser parity is not established.");
return 0;
