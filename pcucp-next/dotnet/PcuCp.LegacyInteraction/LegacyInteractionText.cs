using System.Globalization;
using System.Runtime.InteropServices;

// PS5/.NET Framework uses Windows NLS, while modern .NET normally uses ICU.
// Reuse the qualified app-profile comparison boundary for target text; these
// pure string APIs cannot acquire a desktop or grant input authority.
// Signature/locale contract: https://learn.microsoft.com/en-us/windows/win32/api/winnls/nf-winnls-findnlsstringex
internal static class LegacyInteractionText
{
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern int CompareStringEx(string locale, uint flags, string left, int leftLength, string right, int rightLength,
        IntPtr version, IntPtr reserved, IntPtr parameter);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern int FindNLSStringEx(string locale, uint flags, string source, int sourceLength, string value, int valueLength,
        out int foundLength, IntPtr version, IntPtr reserved, IntPtr parameter);
    internal static bool Equal(string left, string right)
    {
        if (left.Length == 0 || right.Length == 0) return left.Length == right.Length;
        if (!OperatingSystem.IsWindows()) return CultureInfo.InvariantCulture.CompareInfo.Compare(left, right, CompareOptions.IgnoreCase) == 0;
        int result = CompareStringEx("", 1u, left, left.Length, right, right.Length, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero);
        if (result == 0) throw new InvalidOperationException("Windows NLS interaction comparison failed.");
        return result == 2;
    }
    internal static bool ContainsPrefix(string source, string prefix)
    {
        if (prefix.Length == 0) return true; if (source.Length == 0) return false;
        if (!OperatingSystem.IsWindows()) return CultureInfo.CurrentCulture.CompareInfo.IndexOf(source, prefix, CompareOptions.None) >= 0;
        return FindNLSStringEx(CultureInfo.CurrentCulture.Name, 0x00400000u, source, source.Length, prefix, prefix.Length,
            out _, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero) >= 0;
    }
}
