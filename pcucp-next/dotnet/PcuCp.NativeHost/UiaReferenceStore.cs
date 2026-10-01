using System.Diagnostics;
using System.Security.Cryptography;

/// <summary>Session-local, expiring, single-use capabilities; no raw runtime IDs accepted.</summary>
internal sealed class UiaReferenceStore<T>(Func<double>? clock = null) where T : class
{
    private readonly Func<double> now = clock ?? (() => (double)Stopwatch.GetTimestamp() / Stopwatch.Frequency);
    private readonly Dictionary<string, T> entries = new(StringComparer.Ordinal);
    private double created;
    internal void Clear() => entries.Clear();
    internal void Begin() { Clear(); created = now(); }
    internal string Add(T value)
    {
        if (entries.Count >= 2000) throw CommandOptions.Invalid("UIA reference budget exceeded.");
        var token = Convert.ToHexString(RandomNumberGenerator.GetBytes(24));
        entries.Add(token, value);
        return token;
    }
    internal T Consume(string token)
    {
        var valid = now() - created <= 60 && entries.TryGetValue(token, out _);
        entries.TryGetValue(token, out var entry);
        Clear(); // Every attempt consumes the generation, including wrong/expired tokens.
        if (!valid || entry is null) throw new NativeFailure("stale_element_reference", "Observe the target UI again before acting.");
        return entry;
    }
}
