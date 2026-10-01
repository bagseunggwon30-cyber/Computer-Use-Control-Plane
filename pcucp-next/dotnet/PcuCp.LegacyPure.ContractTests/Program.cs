using System.Text.Json;

var count = 0;
void Check(bool condition, string message) { if (!condition) throw new Exception(message); count++; }
void Reject(Action action, string message)
{
    try { action(); } catch (NativeFailure) { count++; return; }
    throw new Exception(message);
}
JsonElement Args(object value) => JsonSerializer.SerializeToElement(value);
JsonElement Classify(string? text, string? macro = "") => JsonSerializer.SerializeToElement(LegacySafetyKernel.Classify(Args(new { text, macro })));
Check(Classify("").GetProperty("risk_score").GetInt32() == 0, "Empty input became sensitive");
foreach (var term in new[] { "password", "PASSWORD", "api key", "토큰", "비밀번호", "인증번호" })
{
    var value = Classify(term);
    Check(value.GetProperty("risk_score").GetInt32() == 85, "Credential score changed");
    Check(value.GetProperty("requires_explicit_confirmation").GetBoolean() && value.GetProperty("blocked_by_default").GetBoolean(), "Credential confirmation weakened");
}
foreach (var (term, score) in new[] { ("결제", 80), ("삭제", 85), ("send", 55), ("여권", 80), ("방화벽", 70), ("settings", 50) })
    Check(Classify(term).GetProperty("risk_score").GetInt32() == score, "Rule score changed");
var registry = Classify("", "REGISTRY");
Check(registry.GetProperty("risk_score").GetInt32() == 80, "Macro maximum weight lost");
Check(registry.GetProperty("categories")[0].GetProperty("weight").GetInt32() == 70 && registry.GetProperty("matches").GetArrayLength() == 2, "Duplicate category semantics changed");
Check(Classify("", "process").GetProperty("risk_score").GetInt32() == 65, "Process control weakened");
Check(Classify("", "notify").GetProperty("risk_score").GetInt32() == 45, "Notification confirmation weakened");
Check(Classify("--force", "app-close").GetProperty("risk_score").GetInt32() == 70, "Forced close weakened");
Check(Classify("checkout password delete upload").GetProperty("risk_score").GetInt32() == 100, "Combined score cap changed");
Check(LegacySafetyKernel.TruncateValue("abcdef", 3) == "abc...", "Truncation changed");
Check(LegacySafetyKernel.TruncateValue("abc", 3) == "abc", "Exact truncation boundary changed");
Check(LegacySafetyKernel.TruncateValue(null, 3) == "", "Null truncation changed");
Check(LegacySafetyKernel.TruncateValue("😀x", 2) == "😀...", "UTF16 truncation changed");
Reject(() => LegacySafetyKernel.Classify(Args(new { text = 1 })), "Non-string safety input accepted");
Reject(() => LegacySafetyKernel.Classify(Args(new { text = new string('x', 262145) })), "Unbounded input accepted");
Reject(() => LegacySafetyKernel.Classify(Args(new { text = "password", disable = true })), "Unknown safety bypass accepted");
Reject(() => LegacySafetyKernel.TruncateValue("x", -1), "Negative truncate accepted");
CoordinateContractChecks.Run(Check);
StrategyContractChecks.Run(Check);
Console.WriteLine($"PASS: {count} pure legacy safety/coordinate/strategy checks; no PowerShell or OS actions executed.");
