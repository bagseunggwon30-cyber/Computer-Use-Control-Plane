using System.Globalization;
using System.Text.Json;

using var utf8Output = new StreamWriter(Console.OpenStandardOutput(), HistoryTransport.Utf8) { AutoFlush = true, NewLine = "\n" };
Console.SetOut(utf8Output);

if (args.SequenceEqual(new[] { "--self-test" })) { HistoryContracts.Run(); return; }
if (args.Length != 2 || args[0] != "--runtime" || args[1] is not ("ps51" or "ps7"))
    throw new ArgumentException("Qualification only: --self-test or --runtime ps51|ps7. No file paths or production operations.");
using var inputStream = Console.OpenStandardInput();
string input = HistoryTransport.Read(inputStream);
using var document = JsonDocument.Parse(input, new JsonDocumentOptions { MaxDepth = 110 });
JsonElement envelope = document.RootElement;
if (envelope.ValueKind != JsonValueKind.Object || envelope.EnumerateObject().Select(p => p.Name).Order().SequenceEqual(new[] { "fixtures", "schema" }) == false
    || envelope.GetProperty("schema").GetString() != "cucp.history-reducer-input/v1")
    throw new ArgumentException("Expected a strict fixture envelope.");
JsonElement root = envelope.GetProperty("fixtures");
if (root.ValueKind != JsonValueKind.Array || root.GetArrayLength() is < 1 or > 2048)
    throw new ArgumentException("Expected 1..2048 fixture objects.");
var ids = new HashSet<string>(StringComparer.Ordinal);
var results = new List<object>();
foreach (JsonElement fixture in root.EnumerateArray())
{
    var validated = HistoryContracts.Validate(fixture);
    if (!ids.Add(validated.Id)) throw new ArgumentException("Duplicate fixture identity.");
    var reducer = new HistoryReducer(args[1], CultureInfo.GetCultureInfo(validated.Culture));
    object? value = validated.Operation switch
    {
        "pick" => reducer.Pick(validated.Capture, validated.Label, validated.Match, validated.Lookback),
        "stats" => reducer.Stats(validated.Capture),
        "app-read" => reducer.Read(validated.Capture),
        "last-good" => reducer.LastGood(validated.Capture, validated.AppKey),
        _ => throw new ArgumentException("Unknown operation.")
    };
    string[] jsonItems = HistoryWire.CompactOutput(value, args[1]);
    results.Add(new { id = validated.Id, operation = validated.Operation, wire = HistoryWire.Encode(value),
        compact_json = jsonItems.Length == 0 ? null : jsonItems[0], compact_json_items = jsonItems, console = "", errors = Array.Empty<string>() });
}
Console.WriteLine(JsonSerializer.Serialize(new {
    schema = "cucp.history-reducer-qualification/v2", runtime = args[1], kind = "candidate-inferred",
    host = new { framework = System.Runtime.InteropServices.RuntimeInformation.FrameworkDescription,
        os = System.Runtime.InteropServices.RuntimeInformation.OSDescription, culture = CultureInfo.CurrentCulture.Name,
        wire_encoding = "utf-8-strict" },
    results
}, new JsonSerializerOptions { MaxDepth = 220 }));
