using System.Text.Json;

// Explicit wire tags preserve runtime arrays, including empty/singleton arrays.
// An ordinary object with properties named value/Count is always an object.
internal static class LegacyExecutionWire
{
    internal static object Encode(JsonElement value) => value.ValueKind switch
    {
        JsonValueKind.Array => new { kind = "array", items = value.EnumerateArray().Select(Encode).ToArray() },
        JsonValueKind.Object => new { kind = "object", properties = value.EnumerateObject().Select(p => new { name = p.Name, value = Encode(p.Value) }).ToArray() },
        _ => new { kind = "scalar", value }
    };
    internal static JsonElement Decode(JsonElement wire)
    {
        static void Fields(JsonElement value, params string[] expected)
        {
            if (value.ValueKind != JsonValueKind.Object) throw new LegacyExecutionProtocolException("Expected a tagged wire object.");
            var seen = new HashSet<string>(StringComparer.Ordinal);
            foreach (var p in value.EnumerateObject()) if (!seen.Add(p.Name) || !expected.Contains(p.Name)) throw new LegacyExecutionProtocolException("Unknown or duplicate wire property.");
            if (seen.Count != expected.Length) throw new LegacyExecutionProtocolException("Missing wire property.");
        }
        if (wire.ValueKind != JsonValueKind.Object || !wire.TryGetProperty("kind", out var kind) || kind.ValueKind != JsonValueKind.String) throw new LegacyExecutionProtocolException("Missing wire tag.");
        switch (kind.GetString())
        {
            case "scalar":
                Fields(wire, "kind", "value"); var scalar = wire.GetProperty("value");
                if (scalar.ValueKind is JsonValueKind.Object or JsonValueKind.Array or JsonValueKind.Undefined) throw new LegacyExecutionProtocolException("A scalar wire value cannot contain an object or array.");
                return scalar.Clone();
            case "array":
                Fields(wire, "kind", "items"); if (wire.GetProperty("items").ValueKind != JsonValueKind.Array) throw new LegacyExecutionProtocolException("Wire items must be an array.");
                return JsonSerializer.SerializeToElement(wire.GetProperty("items").EnumerateArray().Select(Decode).ToArray());
            case "object":
                Fields(wire, "kind", "properties"); if (wire.GetProperty("properties").ValueKind != JsonValueKind.Array) throw new LegacyExecutionProtocolException("Wire properties must be an array.");
                var properties = new Dictionary<string, JsonElement>(StringComparer.OrdinalIgnoreCase);
                foreach (var p in wire.GetProperty("properties").EnumerateArray())
                {
                    Fields(p, "name", "value"); if (p.GetProperty("name").ValueKind != JsonValueKind.String || !properties.TryAdd(p.GetProperty("name").GetString()!, Decode(p.GetProperty("value")))) throw new LegacyExecutionProtocolException("Invalid or duplicate object property.");
                }
                return JsonSerializer.SerializeToElement(properties);
            default: throw new LegacyExecutionProtocolException("Unknown wire tag.");
        }
    }
}

internal sealed class LegacyExecutionProtocolException(string message) : Exception(message);
