using System.Globalization;

internal sealed record NativeError(string Code, string Message);
internal sealed record NativeResult(string Schema, string Status, string Kind, object Data, IReadOnlyList<NativeError> Errors)
{
    private static string SchemaFor(string kind) => kind switch { "windows" => "pcucp.observation/v1", "uia-tree" => "pcucp.uia-tree/v1", _ => "pcucp.native/v1" };
    public static NativeResult Ok(string kind, object data) => new(SchemaFor(kind), "ok", kind, data, Array.Empty<NativeError>());
    public static NativeResult Error(string kind, string code, string message) => new(SchemaFor(kind), "error", kind, new { }, new[] { new NativeError(code, message) });
    public static NativeResult Observation(string kind, object data, IReadOnlyList<NativeError> errors) => new(SchemaFor(kind), errors.Count == 0 ? "ok" : "partial", kind, data, errors);
}

internal sealed class NativeFailure(string code, string message, int exitCode = 1) : Exception(message)
{
    public string Code { get; } = code;
    public int ExitCode { get; } = exitCode;
}

internal sealed record RectInfo(double X, double Y, double Width, double Height);
internal sealed record PixelRect(int X, int Y, int Width, int Height)
{
    public bool Contains(int x, int y) => x >= X && y >= Y && (long)x < (long)X + Width && (long)y < (long)Y + Height;
}

internal sealed class CommandOptions
{
    private readonly Dictionary<string, string?> values = new(StringComparer.OrdinalIgnoreCase);
    public CommandOptions(string[] args)
    {
        for (var i = 0; i < args.Length; i++)
        {
            var name = args[i];
            if (!name.StartsWith('-') || values.ContainsKey(name)) throw Invalid($"Unexpected or duplicate option: {name}");
            if (string.Equals(name, "--allow-live-control", StringComparison.OrdinalIgnoreCase)) values.Add(name, null);
            else
            {
                if (++i >= args.Length || args[i].StartsWith("--", StringComparison.Ordinal)) throw Invalid($"Missing value for {name}");
                values.Add(name, args[i]);
            }
        }
    }
    public bool Has(string name) => values.ContainsKey(name);
    public string? Get(string name) => values.GetValueOrDefault(name);
    public string Required(string name) => Get(name) ?? throw Invalid($"Missing {name}");
    public int Integer(string name, int fallback, int min, int max)
    {
        if (!Has(name)) return fallback;
        if (!int.TryParse(Required(name), NumberStyles.Integer, CultureInfo.InvariantCulture, out var value) || value < min || value > max)
            throw Invalid($"{name} must be an integer from {min} to {max}.");
        return value;
    }
    public int RequiredInteger(string name, int min = int.MinValue, int max = int.MaxValue)
    {
        _ = Required(name);
        return Integer(name, 0, min, max);
    }
    public void Allow(params string[] allowed)
    {
        var set = new HashSet<string>(allowed, StringComparer.OrdinalIgnoreCase);
        foreach (var key in values.Keys) if (!set.Contains(key)) throw Invalid($"Unsupported option: {key}");
    }
    public static NativeFailure Invalid(string message) => new("invalid_arguments", message, 2);
}
