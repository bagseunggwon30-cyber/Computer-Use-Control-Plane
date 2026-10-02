using System.Text;
using System.Text.Json;

internal static class StorageFixtures
{
    internal static object Run(JsonElement args)
    {
        string root = args.GetProperty("root").GetString()!;
        if (!Path.GetFullPath(root).StartsWith(Path.GetFullPath(Path.GetTempPath()), StringComparison.OrdinalIgnoreCase) || !Path.GetFileName(root).StartsWith("CUCP-precision-storage-", StringComparison.Ordinal)) throw new ArgumentException("Storage fixtures require an isolated named temp directory.");
        Directory.CreateDirectory(root);
        string history = Path.Combine(root, "history.jsonl"), cache = Path.Combine(root, "cache");
        DateTime now = DateTime.SpecifyKind(new DateTime(2026, 10, 2, 1, 2, 3), DateTimeKind.Local);
        var store = new LegacyPrecisionStorage(history, cache, () => now);
        var append = new List<bool>();
        if (args.GetProperty("create_cache").GetBoolean()) Directory.CreateDirectory(cache);
        if (args.TryGetProperty("initial_lines", out var lines)) File.WriteAllLines(history, lines.EnumerateArray().Select(s => s.GetString()!), new UTF8Encoding(true));
        foreach (var record in args.GetProperty("serialized_records").EnumerateArray()) append.Add(store.AppendHistory(record.GetString()!, args.GetProperty("maximum").GetInt32()));
        string key = new('a', 32);
        if (args.TryGetProperty("serialized_cache", out var payload) && payload.ValueKind == JsonValueKind.String) store.WriteCache(key, payload.GetString()!);
        if (File.Exists(store.CachePath(key))) File.SetLastWriteTime(store.CachePath(key), now.AddMilliseconds(-args.GetProperty("age_ms").GetDouble()));
        var hit = store.ReadCache(key, args.GetProperty("ttl").GetInt32());
        return new { appended = append.ToArray(), lines = store.HistoryLines(), hit, history_bytes = File.Exists(history) ? Convert.ToBase64String(File.ReadAllBytes(history)) : null,
            cache_bytes = File.Exists(store.CachePath(key)) ? Convert.ToBase64String(File.ReadAllBytes(store.CachePath(key))) : null };
    }
}
