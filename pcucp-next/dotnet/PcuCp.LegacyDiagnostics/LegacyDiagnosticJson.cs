using System.Globalization;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;

// Data-only JSON conversion at the two diagnostic file boundaries. Windows
// PowerShell first deserializes into ordinal dictionaries (last exact key wins),
// then builds case-insensitive PSObject properties from the surviving values.
// Syntax and UTF-16 cursor errors follow the .NET Framework reference reader:
// https://github.com/microsoft/referencesource/blob/main/System.Web.Extensions/Script/Serialization/JavaScriptObjectDeserializer.cs
// https://github.com/microsoft/referencesource/blob/main/System.Web.Extensions/Script/Serialization/JavaScriptString.cs
// The non-CORECLR conversion and depth limit are documented in:
// https://github.com/PowerShell/PowerShell/blob/v6.0.0-alpha.9/src/Microsoft.PowerShell.Commands.Utility/commands/utility/WebCmdlet/JsonObject.cs
// Bounded to diagnostic file data, including the legacy DateTime literal and
// inert __type dictionary metadata. Not a general ConvertFrom-Json replacement.
// This does not load CLR types, run script, or perform file/process operations.
internal static class LegacyDiagnosticJson
{
    private const int MaxDepth = 102;
    private const string CustomObjectDisplayType = "System.Management.Automation.PSCustomObject";
    private static readonly JsonSerializerOptions ElementOptions = new()
    { MaxDepth = MaxDepth + 1, Converters = { new InterpolatedDateTimeConverter(), new InterpolatedDoubleConverter() } };

    // Retain source-created CLR scalar types across benchmark property lookup.
    // A JSON string cannot impersonate DateTime or a nonfinite Double. The
    // interpolated Json view is only for the existing report string semantics.
    internal sealed class Value(object? value)
    {
        internal JsonElement Json => JsonSerializer.SerializeToElement(value, ElementOptions);
        internal bool IsNull => value is null;
        internal DateTime? Date => value is DateTime date ? date : null;
        internal bool IsTrue => Truth(value);
        internal string Text => Interpolate(value);
        internal double Double()
        {
            if (value is null || value is string { Length: 0 }) return 0;
            if (value is not string text) return Convert.ToDouble(value, CultureInfo.InvariantCulture);
            // LanguagePrimitives.ConvertStringToReal uses invariant conversion,
            // unlike the integer TypeConverter's hexadecimal acceptance. Retain
            // that distinction and its legacy exception wrapper at this reached
            // diagnostic-data cast; no protocol-number coercion changes here.
            try
            {
                double number = Convert.ToDouble(text, CultureInfo.InvariantCulture);
                if (!double.IsFinite(number) && text.Trim() is not ("NaN" or "Infinity" or "-Infinity"))
                {
                    // Framework rejects extra symbol spellings; modern numeric
                    // overflow instead saturates to infinity. Preserve both
                    // distinct failure classes before wrapping the legacy text.
                    if (double.IsNaN(number) || text.Trim().Any(c => !char.IsDigit(c) && c is not ('+' or '-' or '.' or ',' or 'e' or 'E')))
                        throw new FormatException();
                    throw new OverflowException();
                }
                return number;
            }
            catch (Exception error) when (error is FormatException or OverflowException)
            {
                string detail = error is FormatException ? "Input string was not in a correct format." :
                    "Value was either too large or too small for a Double.";
                throw CommandOptions.Invalid($"Cannot convert value \"{text}\" to type \"System.Double\". Error: \"{detail}\"");
            }
        }
        internal Value Property(string name) => new(EventProperty(value, name));
        internal IEnumerable<Value> Elements => value is List<object?> list
            ? list.Select(item => new Value(item)) : value is null ? [] : [this];
        internal int Int32()
        {
            if (value is DateTime date)
                throw CommandOptions.Invalid($"Cannot convert value \"{LegacyDiagnosticCulture.DateTimeErrorText(date, CultureInfo.CurrentCulture)}\" to type \"System.Int32\". Error: \"Invalid cast from 'DateTime' to 'Int32'.\"");
            if (value is double number && !double.IsFinite(number))
                throw CommandOptions.Invalid($"Cannot convert value \"{number.ToString(CultureInfo.CurrentCulture)}\" to type \"System.Int32\". Error: \"Value was either too large or too small for an Int32.\"");
            // JSON arrays remain Object[] even at length zero or one.
            if (value is List<object?>)
                throw CommandOptions.Invalid("Cannot convert the \"System.Object[]\" value of type \"System.Object[]\" to type \"System.Int32\".");
            if (value is Dictionary<string, object?> members)
            {
                // This is an inert diagnostic type-display name, never a CLR
                // type reference or lookup. Keep the engine dependency absent.
                throw CommandOptions.Invalid($"Cannot convert the \"{ObjectDisplay(members, CultureInfo.CurrentCulture, true)}\" value of type \"{CustomObjectDisplayType}\" to type \"System.Int32\".");
            }
            return LegacyTaskFormKernel.LegacyInt(Json);
        }
    }

    internal static Value ParseValue(string text) => new(Read(text));

    internal static JsonElement Parse(string text) => Parse(text, out _);
    internal static JsonElement Parse(string text, out DateTime? timestamp)
    {
        object? value = Read(text);
        timestamp = EventProperty(value, "ts") is DateTime date ? date : null;
        return JsonSerializer.SerializeToElement(value, ElementOptions);
    }

    private static object? Read(string text)
    {
        var reader = new Reader(text);
        object? value = reader.ReadValue(0);
        reader.CheckEnd();
        CheckProperties(value);
        return value;
    }

    // Keep the typed timestamp until the audit cutoff cast. Other audit uses
    // interpolate values, including dates, using PowerShell's invariant culture.
    private sealed class InterpolatedDateTimeConverter : JsonConverter<DateTime>
    {
        public override DateTime Read(ref Utf8JsonReader reader, Type type, JsonSerializerOptions options) => throw new NotSupportedException();
        public override void Write(Utf8JsonWriter writer, DateTime value, JsonSerializerOptions options) =>
            writer.WriteStringValue(value.ToString(CultureInfo.InvariantCulture));
    }

    private sealed class InterpolatedDoubleConverter : JsonConverter<double>
    {
        public override double Read(ref Utf8JsonReader reader, Type type, JsonSerializerOptions options) => throw new NotSupportedException();
        public override void Write(Utf8JsonWriter writer, double value, JsonSerializerOptions options)
        {
            if (double.IsFinite(value)) writer.WriteNumberValue(value);
            else writer.WriteStringValue(value.ToString(CultureInfo.InvariantCulture));
        }
    }

    // PowerShell interpolation joins a top-level array, but PSObject's own
    // member display is shallow: nested custom objects have an empty base
    // string, and array members retain their CLR array display name.
    private static string Interpolate(object? value) => value switch
    {
        List<object?> elements => string.Join(" ", elements.Select(item => Shallow(item, CultureInfo.InvariantCulture, false))),
        Dictionary<string, object?> members => ObjectDisplay(members, CultureInfo.InvariantCulture, false),
        _ => ScalarDisplay(value, CultureInfo.InvariantCulture, false)
    };

    private static string ObjectDisplay(Dictionary<string, object?> members, CultureInfo culture, bool errorDisplay) => members.Count == 0 ? "" :
        "@{" + string.Join("; ", members.Select(member => member.Key + "=" + Shallow(member.Value, culture, errorDisplay))) + "}";

    private static string Shallow(object? value, CultureInfo culture, bool errorDisplay) => value switch
    {
        Dictionary<string, object?> => "", List<object?> => "System.Object[]",
        _ => ScalarDisplay(value, culture, errorDisplay)
    };

    private static string ScalarDisplay(object? value, CultureInfo culture, bool errorDisplay) => value switch
    {
        null => "", string text => text,
        DateTime date when errorDisplay => LegacyDiagnosticCulture.DateTimeErrorText(date, culture),
        IFormattable formattable => formattable.ToString(null, culture),
        _ => value.ToString() ?? ""
    };

    private static bool Truth(object? value) => value switch
    {
        null => false, bool boolean => boolean, string text => text.Length != 0,
        List<object?> elements => elements.Count > 1 || elements.Count == 1 && Truth(elements[0]),
        int number => number != 0, long number => number != 0,
        decimal number => number != 0, double number => number != 0,
        _ => true
    };

    private static object? EventProperty(object? value, string name)
    {
        if (value is Dictionary<string, object?> members)
            return members.FirstOrDefault(p => StringComparer.OrdinalIgnoreCase.Equals(p.Key, name)).Value;
        if (value is not List<object?> elements) return null;
        var found = new List<object?>();
        foreach (object? element in elements)
        {
            object? property = EventProperty(element, name);
            if (property is List<object?> list) found.AddRange(list);
            else if (property is not null) found.Add(property);
        }
        return found.Count == 1 ? found[0] : found;
    }

    private static void CheckProperties(object? value)
    {
        if (value is Dictionary<string, object?> members)
        {
            var names = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            foreach (var member in members)
            {
                // PSObject.Properties[name] performs these checks before child
                // conversion. PSTypeNames is an existing generated property;
                // the other reserved names below are member sets, not properties.
                if (member.Key.Length == 0)
                    throw new JsonException("Cannot process argument because the value of argument \"name\" is not valid. Change the value of the \"name\" argument and run the operation again.");
                if (StringComparer.OrdinalIgnoreCase.Equals(member.Key, "pstypenames"))
                    throw new JsonException($"Cannot convert the JSON string because a dictionary that was converted from the string contains the duplicated keys 'pstypenames' and '{member.Key}'.");
                if (names.TryGetValue(member.Key, out string? previous))
                    throw new JsonException($"Cannot convert the JSON string because a dictionary that was converted from the string contains the duplicated keys '{previous}' and '{member.Key}'.");
                // Validate only retained values, after every exact duplicate was
                // replaced. An overwritten object's case collision is irrelevant.
                CheckProperties(member.Value);
                // PSNoteProperty construction occurs after nested conversion.
                // These names cannot be added even when their value is null.
                if (new[] { "psbase", "psadapted", "psextended", "psobject" }.Contains(member.Key, StringComparer.OrdinalIgnoreCase))
                    throw new JsonException($"The member name \"{member.Key}\" is reserved.");
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
            // Framework accepts only these exact invariant nonfinite symbols.
            // Do not inherit modern .NET's case-insensitive symbols or overflow
            // saturation: e.g. `nan`, `+Infinity` and `1e999` remain invalid.
            if (token == "NaN") return double.NaN;
            if (token == "Infinity") return double.PositiveInfinity;
            if (token == "-Infinity") return double.NegativeInfinity;
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
