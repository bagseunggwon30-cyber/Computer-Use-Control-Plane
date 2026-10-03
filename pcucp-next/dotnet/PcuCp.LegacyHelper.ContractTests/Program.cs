using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using PcuCp.LegacyHelper;

internal static class Program
{
    private static object Decode(JsonElement value)
    {
        switch (value.ValueKind)
        {
            case JsonValueKind.Null: return null;
            case JsonValueKind.True: return true;
            case JsonValueKind.False: return false;
            case JsonValueKind.String: return value.GetString();
            case JsonValueKind.Number:
                int integer; long wide;
                if (value.TryGetInt32(out integer)) return integer;
                if (value.TryGetInt64(out wide)) return wide;
                return value.GetDouble();
            case JsonValueKind.Array: return value.EnumerateArray().Select(Decode).ToArray();
            case JsonValueKind.Object: return value.EnumerateObject().ToDictionary(x => x.Name, x => Decode(x.Value), StringComparer.Ordinal);
            default: throw new InvalidOperationException("Unsupported JSON value");
        }
    }
    private static int Main(string[] args)
    {
        if (args.SequenceEqual(new[] { "--self-test" })) { HelperContractChecks.Run(); WireContractChecks.Run(); DirectContractChecks.Run(); ProgressContractChecks.Run(); return 0; }
        if (args.SequenceEqual(new[] { "--fixture" }) || args.SequenceEqual(new[] { "--fixtures" }))
        {
            using (var document = JsonDocument.Parse(Console.In.ReadToEnd()))
            {
                var data = Decode(document.RootElement);
                var fixture = data as IDictionary<string, object>;
                object result = fixture != null ? (object)LegacyHelperFixtureRunner.Evaluate(fixture)
                    : ((object[])data).Select(x => (object)LegacyHelperFixtureRunner.Evaluate((IDictionary<string, object>)x)).ToArray();
                Console.WriteLine(JsonSerializer.Serialize(result));
            }
            return 0;
        }
        Console.WriteLine("Use --self-test or --fixtures. Synthetic captures only; no desktop calls.");
        return 0;
    }
}
