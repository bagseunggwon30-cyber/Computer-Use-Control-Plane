using System.Globalization;
using System.Text.Json;
// Test-only process culture; never changes OS/user locale or launches a target app.
CultureInfo.CurrentCulture = CultureInfo.GetCultureInfo(args[0]);
using var document = JsonDocument.Parse(Console.In.ReadToEnd());
var root = document.RootElement;
var operation = root.GetProperty("operation").GetString();
var input = root.GetProperty("args");
object data = operation == "strategy-score" ? LegacyStrategyKernel.Score(input)
    : operation == "strategy-normalize" ? LegacyStrategyKernel.Normalize(input)
    : throw new ArgumentException("Unsupported fixture operation");
Console.WriteLine(JsonSerializer.Serialize(new { status = "ok", data }));
