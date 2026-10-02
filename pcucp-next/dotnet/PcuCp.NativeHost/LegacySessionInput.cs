using System.IO;
using System.Text;

internal static class LegacySessionInput
{
    // A redirected parent can retain an OEM console code page. These protocols
    // carry UTF-8 bytes regardless of that process setting. Keep one reader for
    // startup and replies, and let the startup parser accept its single BOM.
    internal static StreamReader Open(Stream stream) =>
        new(stream, new UTF8Encoding(false, true), detectEncodingFromByteOrderMarks: false);
}
