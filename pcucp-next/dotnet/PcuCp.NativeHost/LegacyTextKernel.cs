using System.Globalization;
using System.Runtime.InteropServices;
using System.Text;

// Fixed legacy text predicates only; no generic regex language or external action.
internal static class LegacyTextKernel
{
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern int LCMapStringEx(string locale, uint flags, string source, int sourceLength,
        [Out] char[]? destination, int destinationLength, IntPtr version, IntPtr reserved, IntPtr parameter);

    internal static string LowerValue(string value, CultureInfo culture)
    {
        if (value.Length == 0) return value;
        if (!OperatingSystem.IsWindows()) return culture.TextInfo.ToLower(value);
        // Framework invariant casing uses the filesystem casing tables; named
        // cultures use linguistic casing. In particular, invariant Kelvin sign
        // stays unchanged while current-culture Kelvin sign becomes ASCII k.
        uint flags = 0x100u | (culture.Name.Length == 0 ? 0u : 0x01000000u);
        int size = LCMapStringEx(culture.Name, flags, value, value.Length, null, 0, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero);
        if (size == 0) throw new NativeFailure("legacy_casing_failed", "Windows NLS case conversion failed.");
        var buffer = new char[size];
        int written = LCMapStringEx(culture.Name, flags, value, value.Length, buffer, buffer.Length, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero);
        if (written == 0) throw new NativeFailure("legacy_casing_failed", "Windows NLS case conversion failed.");
        return new string(buffer, 0, written);
    }

    private static char LowerCharacter(char value, CultureInfo culture, Dictionary<char, char> cache)
    {
        if (cache.TryGetValue(value, out char cached)) return cached;
        // Regex and PowerShell's wildcard matcher normalize UTF-16 characters,
        // unlike whole-string lowercasing of a supplementary-letter pair.
        string lowered = LowerValue(value.ToString(), culture);
        if (lowered.Length != 1) throw new NativeFailure("legacy_casing_failed", "Windows NLS character case conversion changed UTF-16 length.");
        cache[value] = lowered[0];
        return lowered[0];
    }

    internal static bool IsBareCommandToken(string? value, CultureInfo culture)
    {
        if (string.IsNullOrEmpty(value)) return false;
        // Original ^[A-Za-z0-9_\-\.\/\\:=@]+$ uses Framework range tables and
        // culture-lowercased input. Modern Regex equivalence classes differ for
        // Turkish I/dotless-i and invariant Kelvin sign. Its $ also permits one
        // terminal LF; preserve that historical command-formatting behavior.
        int length = value.Length - (value[^1] == '\n' ? 1 : 0);
        if (length == 0) return false;
        var cache = new Dictionary<char, char>();
        for (int i = 0; i < length; i++)
        {
            char c = LowerCharacter(value[i], culture, cache);
            if (!(c is >= 'a' and <= 'z' or >= '0' and <= '9' or '_' or '-' or '.' or '/' or '\\' or ':' or '=' or '@')) return false;
        }
        return true;
    }

    internal static string SanitizeAppKeyPart(string value, CultureInfo culture)
    {
        // Original [^a-z0-9_.-]+ is also evaluated after culture-sensitive
        // character lowercase, but valid characters keep their original spelling.
        var result = new StringBuilder(value.Length);
        var cache = new Dictionary<char, char>();
        bool replacing = false;
        foreach (char original in value)
        {
            char c = LowerCharacter(original, culture, cache);
            if (c is >= 'a' and <= 'z' or >= '0' and <= '9' or '_' or '.' or '-')
            {
                result.Append(original);
                replacing = false;
            }
            else if (!replacing)
            {
                result.Append('-');
                replacing = true;
            }
        }
        return result.ToString();
    }
}
