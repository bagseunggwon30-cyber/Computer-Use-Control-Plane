using System.Globalization;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

// QUALIFICATION ONLY. The PS5 reader is a pinned copy of the existing diagnostic
// reader at 12d0cc2, retaining CLR values here instead of flattening DateTime to
// strings. It is NOT shared with or wired into production diagnostics/history.
// It models the Framework JavaScriptSerializer dialect; Windows observations,
// not these inferred rules, decide parity. PS7 uses a separate candidate reader.
internal static class HistoryJson
{
    private const int MaxDepth = 102;
    internal static object? Parse(string text, string runtime)
    {
        object? value;
        if (runtime == "ps51")
        {
            var reader = new Reader(text);
            value = reader.ReadValue(0);
            reader.CheckEnd();
        }
        else
        {
            if (string.IsNullOrWhiteSpace(text)) return null;
            using var document = JsonDocument.Parse(text, new JsonDocumentOptions {
                MaxDepth = 102, AllowTrailingCommas = true, CommentHandling = JsonCommentHandling.Skip });
            value = ReadModern(document.RootElement);
        }
        CheckProperties(value);
        // PS7 normally enumerates the root array; assigning its pipeline output
        // collapses a singleton and turns no output into null. PS5 root arrays
        // are one pipeline object. Keep both profiles explicitly testable.
        if (runtime == "ps7" && value is List<object?> values)
            return values.Count switch { 0 => null, 1 => values[0], _ => values };
        return value;
    }

    private static object? ReadModern(JsonElement node)
    {
        switch (node.ValueKind)
        {
            case JsonValueKind.Object:
                var properties = new Dictionary<string, object?>(StringComparer.Ordinal);
                foreach (var member in node.EnumerateObject()) properties[member.Name] = ReadModern(member.Value);
                return properties;
            case JsonValueKind.Array: return node.EnumerateArray().Select(ReadModern).ToList();
            case JsonValueKind.String:
                string text = node.GetString()!;
                // JSON.NET's default DateParseHandling is DateTime. Exact
                // overflow, offset and version behavior remains a Windows gate.
                if (Regex.IsMatch(text, @"^\d{4}-\d\d-\d\dT") && DateTime.TryParse(text,
                        CultureInfo.InvariantCulture, DateTimeStyles.RoundtripKind, out DateTime date)) return date;
                return text;
            case JsonValueKind.Number:
                if (node.TryGetInt64(out long wide)) return wide;
                double number = node.GetDouble();
                if (!double.IsFinite(number)) throw new JsonException("Non-finite candidate JSON number.");
                return number;
            case JsonValueKind.True: return true;
            case JsonValueKind.False: return false;
            default: return null;
        }
    }

    private static void CheckProperties(object? value)
    {
        if (value is Dictionary<string, object?> members)
        {
            var names = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            foreach (var member in members)
            {
                if (member.Key.Length == 0) throw new JsonException("Empty PSObject property name.");
                if (names.TryGetValue(member.Key, out string? previous))
                    throw new JsonException($"Cannot convert the JSON string because a dictionary that was converted from the string contains the duplicated keys '{previous}' and '{member.Key}'.");
                // Validate only retained values, after every exact duplicate was
                // replaced. An overwritten object's case collision is irrelevant.
                CheckProperties(member.Value);
                names.Add(member.Key, member.Key);
            }
        }
        else if (value is List<object?> elements)
            foreach (object? element in elements) CheckProperties(element);
    }

    private sealed class Reader(string text)
    {
        private int position;
        private static readonly Regex DateLiteral = new("^\"\\\\/Date\\((?<milliseconds>-?[0-9]+)(?:[a-zA-Z]|[+-][0-9]{4})?\\)\\\\/\"", RegexOptions.CultureInvariant);
        private const string InvalidObject = "Invalid object passed in, ':' or '}' expected.";
        private JsonException Error(string message) => new($"{message} ({position.ToString(CultureInfo.InvariantCulture)}): {text}");
        private static JsonException PrimitiveError(string token) => new($"Invalid JSON primitive: {token}.");
        private char? Next() => position < text.Length ? text[position++] : null;
        private char? NextNonWhiteSpace()
        {
            while (Next() is char c) if (!char.IsWhiteSpace(c)) return c;
            return null;
        }
        internal void CheckEnd()
        {
            if (NextNonWhiteSpace() is not null) throw PrimitiveError(text[position..]);
        }

        internal object? ReadValue(int depth)
        {
            if (++depth > MaxDepth) throw Error("RecursionLimit exceeded.");
            char? c = NextNonWhiteSpace();
            if (c is null) return null;
            position--;
            if (c == '"' && text.AsSpan(position).StartsWith("\"\\/Date(", StringComparison.Ordinal))
            {
                var match = DateLiteral.Match(text[position..]);
                if (match.Success && long.TryParse(match.Groups["milliseconds"].Value, NumberStyles.Integer, CultureInfo.InvariantCulture, out long milliseconds))
                {
                    position += match.Length;
                    long ticks = unchecked(milliseconds * TimeSpan.TicksPerMillisecond + DateTime.UnixEpoch.Ticks);
                    if (ticks < DateTime.MinValue.Ticks || ticks > DateTime.MaxValue.Ticks)
                        throw new JsonException("Ticks must be between DateTime.MinValue.Ticks and DateTime.MaxValue.Ticks.\r\nParameter name: ticks");
                    return new DateTime(ticks, DateTimeKind.Utc);
                }
            }
            return c switch
            {
                '{' => ReadObject(depth), '[' => ReadArray(depth),
                '"' or '\'' => ReadString(), _ => ReadPrimitive()
            };
        }

        private Dictionary<string, object?> ReadObject(int depth)
        {
            position++; // Opening brace was selected by ReadValue.
            var members = new Dictionary<string, object?>(StringComparer.Ordinal);
            char? c;
            while ((c = NextNonWhiteSpace()) is not null)
            {
                position--;
                if (c == ':') throw Error("Invalid object passed in, member name expected.");
                string? name = null;
                if (c != '}')
                {
                    name = c is '"' or '\'' ? ReadString() : ReadToken();
                    if (NextNonWhiteSpace() != ':') throw Error(InvalidObject);
                }
                else if (members.Count == 0)
                {
                    position++;
                    return CompleteObject(members);
                }
                object? value = ReadValue(depth);
                // A closing brace after a comma has already failed ReadValue as
                // an empty primitive, just as the reference reader does.
                members[name!] = value;
                c = NextNonWhiteSpace();
                if (c == '}') return CompleteObject(members);
                if (c != ',') throw Error(InvalidObject);
            }
            throw Error(InvalidObject);
        }

        private static Dictionary<string, object?> CompleteObject(Dictionary<string, object?> members)
        {
            // The desktop JsonObjectTypeResolver always returns a dictionary.
            // ObjectConverter removes a non-null __type before PSObject checks;
            // case variants remain normal properties. No CLR type is activated.
            if (members.TryGetValue("__type", out object? type) && type is not null)
            {
                if (type is Dictionary<string, object?>) throw new JsonException("No parameterless constructor defined for type of 'System.String'.");
                if (type is List<object?>) throw new JsonException("Type 'System.String' is not supported for deserialization of an array.");
                members.Remove("__type");
            }
            return members;
        }

        private List<object?> ReadArray(int depth)
        {
            position++;
            var elements = new List<object?>();
            bool afterComma = false;
            char? c;
            while ((c = NextNonWhiteSpace()) is not null && c != ']')
            {
                position--;
                elements.Add(ReadValue(depth));
                afterComma = false;
                c = NextNonWhiteSpace();
                if (c == ']') return elements;
                afterComma = true;
                if (c != ',') throw Error("Invalid array passed in, ',' expected.");
            }
            if (afterComma) throw Error("Invalid array passed in, extra trailing ','.");
            if (c != ']') throw Error("Invalid array passed in, ']' expected.");
            return elements;
        }

        private string ReadToken()
        {
            int start = position;
            while (position < text.Length &&
                (char.IsLetterOrDigit(text[position]) || text[position] is '.' or '-' or '_' or '+')) position++;
            return text[start..position];
        }

        private object? ReadPrimitive()
        {
            string token = ReadToken();
            if (token == "null") return null;
            if (token == "true") return true;
            if (token == "false") return false;
            if (!token.Contains('e', StringComparison.OrdinalIgnoreCase))
            {
                if (!token.Contains('.'))
                {
                    if (int.TryParse(token, NumberStyles.Integer, CultureInfo.InvariantCulture, out int integer)) return integer;
                    if (long.TryParse(token, NumberStyles.Integer, CultureInfo.InvariantCulture, out long wide)) return wide;
                }
                if (decimal.TryParse(token, NumberStyles.Number, CultureInfo.InvariantCulture, out decimal number)) return number;
            }
            // Framework TryParse rejects overflow; modern .NET returns infinity.
            if (double.TryParse(token, NumberStyles.Float, CultureInfo.InvariantCulture, out double real) && double.IsFinite(real)) return real;
            throw PrimitiveError(token);
        }

        private string ReadString()
        {
            char quote = text[position++];
            var value = new StringBuilder();
            while (Next() is char c)
            {
                // Framework validation replaces unpaired UTF-16 surrogates
                // before dictionary keys are compared, including exact keys.
                if (c == quote) return Encoding.Unicode.GetString(Encoding.Unicode.GetBytes(value.ToString()));
                if (c != '\\') { value.Append(c); continue; }
                if (Next() is not char escaped) break;
                switch (escaped)
                {
                    case '\\': case '/': case '\'': case '"': value.Append(escaped); break;
                    case 'b': value.Append('\b'); break;
                    case 'f': value.Append('\f'); break;
                    case 'n': value.Append('\n'); break;
                    case 'r': value.Append('\r'); break;
                    case 't': value.Append('\t'); break;
                    case 'u':
                        if (position + 4 > text.Length) throw new JsonException("Value cannot be null.\r\nParameter name: s");
                        string digits = text.Substring(position, 4);
                        position += 4;
                        if (!ushort.TryParse(digits, NumberStyles.HexNumber, CultureInfo.InvariantCulture, out ushort code))
                            throw new JsonException("Input string was not in a correct format.");
                        value.Append((char)code);
                        break;
                    default: throw Error("Unrecognized escape sequence.");
                }
            }
            throw Error("Unterminated string passed in.");
        }
    }
}
