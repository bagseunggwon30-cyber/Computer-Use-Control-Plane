using System.IO;
using System.Text;
using System.Text.Json;

// Fixed-path filesystem effects only. Serialization is an explicit boundary so
// the staged adapter can retain PS5 byte formatting until a serializer qualifies.
internal sealed class LegacyPrecisionStorage(string historyFile, string cacheDirectory, Func<DateTime> now)
{
    private static readonly UTF8Encoding Utf8Bom = new(true);
    internal string CachePath(string key)
    {
        // The original key helper emits exactly 32 lowercase MD5 digits. Keys
        // supplied by an untrusted captured result must not expand authority.
        if (key.Length != 32 || key.Any(c => c is not (>= '0' and <= '9' or >= 'a' and <= 'f'))) throw new ArgumentException("Invalid precision cache key.");
        return Path.Combine(cacheDirectory, "point-plan-" + key + ".json");
    }
    internal string[] HistoryLines()
    {
        if (string.IsNullOrEmpty(historyFile) || !File.Exists(historyFile)) return [];
        try { return File.ReadAllLines(historyFile, Encoding.UTF8); } catch (IOException) { return []; } catch (UnauthorizedAccessException) { return []; }
    }
    internal object? ReadCache(string key, int maxAgeSeconds)
    {
        if (string.IsNullOrEmpty(key) || maxAgeSeconds <= 0) return null;
        string path = CachePath(key); if (!File.Exists(path)) return null;
        var age = now() - File.GetLastWriteTime(path);
        if (age.TotalSeconds > maxAgeSeconds) return null;
        try
        {
            using var json = JsonDocument.Parse(File.ReadAllText(path, Encoding.UTF8), new JsonDocumentOptions { MaxDepth = 1024 });
            return LegacyPrecisionKernel.D("Json", json.RootElement.Clone(), "Path", path, "AgeMs", Convert.ToInt32(age.TotalMilliseconds));
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or JsonException or OverflowException) { return null; }
    }
    internal void WriteCache(string key, string serializedPayload)
    {
        if (string.IsNullOrEmpty(key) || string.IsNullOrEmpty(serializedPayload)) return;
        string path = CachePath(key);
        try { File.WriteAllText(path, serializedPayload + Environment.NewLine, Utf8Bom); }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException) { }
    }
    internal bool AppendHistory(string serializedRecord, int maximum)
    {
        if (string.IsNullOrEmpty(serializedRecord)) return false;
        try
        {
            string? directory = Path.GetDirectoryName(historyFile);
            if (!string.IsNullOrEmpty(directory) && !Directory.Exists(directory)) Directory.CreateDirectory(directory);
            // Add-Content -ErrorAction SilentlyContinue suppresses append errors;
            // the old function can still return true. Keep that odd behavior.
            try { File.AppendAllText(historyFile, serializedRecord + Environment.NewLine, Utf8Bom); }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException) { }
            if (File.Exists(historyFile))
            {
                var all = HistoryLines(); int max = maximum > 0 ? maximum : 500;
                if (all.Length > max)
                {
                    int keep = Math.Max(50, Convert.ToInt32(max * .8)); var tail = new List<string>();
                    // PowerShell negative indexes wrap. A multi-index selection
                    // drops out-of-range entries rather than emitting blanks.
                    for (int i = all.Length - keep; i < all.Length; i++)
                    {
                        int index = i < 0 ? all.Length + i : i;
                        if (index >= 0 && index < all.Length) tail.Add(all[index]);
                    }
                    File.WriteAllLines(historyFile, tail, Utf8Bom);
                }
            }
            return true;
        }
        catch { return false; }
    }
}
