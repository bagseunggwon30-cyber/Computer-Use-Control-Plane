using System.Text.Json;
if (args.SequenceEqual(new[] { "--session-fixture" }) || args.SequenceEqual(new[] { "--storage-session-fixture" }))
{
    var startup = LegacyPrecisionSession.ReadStartup(Console.In);
    Environment.ExitCode = args[0] == "--session-fixture" ? new LegacyPrecisionSession(Console.In, Console.Out).Run(startup) : new LegacyPrecisionSession(Console.In, Console.Out).RunStorage(startup); return;
}
if (args.SequenceEqual(new[] { "--self-test" })) { SelfTests.Run(); return; }
var input = Console.In.ReadToEnd();
if (input.Length > 67108864) throw new ArgumentException("Fixture batch exceeds 64MiB.");
using var doc = JsonDocument.Parse(input, new JsonDocumentOptions { MaxDepth = 128 });
object Run(JsonElement value)
{
    try { return value.GetProperty("operation").GetString() == "storage-fixture" ? StorageFixtures.Run(value.GetProperty("args")) : LegacyPrecisionKernel.Advance(value.GetProperty("operation").GetString()!, value.GetProperty("args")); }
    catch (Exception ex) { return new { state = "error", error = ex.Message, queries = Array.Empty<object>() }; }
}
Console.WriteLine(JsonSerializer.Serialize(doc.RootElement.EnumerateArray().Select(Run), new JsonSerializerOptions { MaxDepth = 128 }));
