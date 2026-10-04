using System.Text;

// Qualification pipe bytes are UTF-8 regardless of an inherited Windows console
// code page. This never changes a console, user locale or system setting.
internal static class HistoryTransport
{
    internal const int MaxInputBytes = 16 * 1024 * 1024;
    internal static readonly UTF8Encoding Utf8 = new(false, true);
    internal static string Read(Stream source)
    {
        using var bytes = new MemoryStream();
        var buffer = new byte[8192];
        int count;
        while ((count = source.Read(buffer, 0, Math.Min(buffer.Length, MaxInputBytes - (int)bytes.Length + 1))) != 0)
        {
            if (bytes.Length + count > MaxInputBytes) throw new ArgumentException("Fixture input exceeds 16 MiB.");
            bytes.Write(buffer, 0, count);
        }
        // Throw on malformed UTF-8. No ambient-codepage or replacement fallback.
        return Utf8.GetString(bytes.GetBuffer(), 0, (int)bytes.Length);
    }
}
