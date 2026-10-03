using System.Globalization;
using System.Runtime.InteropServices;
using System.Text;

// A fixed, read-only NLS metadata boundary for diagnostic conversion messages.
// No global culture/runtime switch, file/provider access, or request capability.
internal static class LegacyDiagnosticCulture
{
    private const uint NoUserOverride = 0x80000000;
    private const uint ShortDate = 0x1f, LongTime = 0x1003, Am = 0x28, Pm = 0x29;

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern int GetLocaleInfoEx(string locale, uint type, [Out] char[]? value, int size);

    private static string LocaleValue(CultureInfo culture, uint type)
    {
        uint flags = type | (culture.UseUserOverride ? 0 : NoUserOverride);
        int count = GetLocaleInfoEx(culture.Name, flags, null, 0);
        if (count is < 1 or > 1024) throw new NativeFailure("legacy_locale_format_failed", "Windows NLS diagnostic locale data was unavailable or exceeded its bound.");
        var buffer = new char[count];
        int written = GetLocaleInfoEx(culture.Name, flags, buffer, count);
        if (written != count || buffer[^1] != '\0') throw new NativeFailure("legacy_locale_format_failed", "Windows NLS diagnostic locale data changed during capture.");
        return new string(buffer, 0, count - 1);
    }

    internal static string DateTimeErrorText(DateTime value, CultureInfo culture)
    {
        // Framework G = short-date + one space + long-time. Modern Windows .NET
        // may use ICU data instead. Model only the numeric Gregorian domain;
        // named months/weekdays/eras and non-Gregorian calendars remain outside
        // this boundary's qualification claim. All DateTime years are retained.
        if (OperatingSystem.IsWindows() && culture.Name.Length != 0 && culture.Calendar is GregorianCalendar)
        {
            var format = NumericGregorianFormat(LocaleValue(culture, ShortDate), LocaleValue(culture, LongTime),
                LocaleValue(culture, Am), LocaleValue(culture, Pm));
            if (format is not null) return value.ToString("G", format);
        }
        return value.ToString(culture);
    }

    internal static DateTimeFormatInfo? NumericGregorianFormat(string date, string time, string am, string pm)
    {
        date = Reescape(date); time = Reescape(time);
        bool quoted = false;
        for (int index = 0; index < date.Length; index++)
        {
            char c = date[index];
            if (c == '\\') { index++; continue; }
            if (c == '\'') { quoted = !quoted; continue; }
            if (quoted || !char.IsLetter(c)) continue;
            if (c is not ('y' or 'M' or 'd')) return null;
            int start = index;
            while (index + 1 < date.Length && date[index + 1] == c) index++;
            if (c is 'M' or 'd' && index - start + 1 > 2) return null;
        }
        if (quoted) return null;
        var format = (DateTimeFormatInfo)CultureInfo.InvariantCulture.DateTimeFormat.Clone();
        format.ShortDatePattern = date; format.LongTimePattern = time;
        format.DateSeparator = Separator(date, "dyM"); format.TimeSeparator = Separator(time, "Hhms");
        format.AMDesignator = am; format.PMDesignator = pm;
        return format;
    }

    // NLS and .NET custom patterns have different literal escaping. This is the
    // bounded string transformation used by the runtime's NLS CultureData path.
    internal static string Reescape(string pattern)
    {
        var output = new StringBuilder(); bool quoted = false;
        for (int index = 0; index < pattern.Length; index++)
        {
            char c = pattern[index];
            if (c == '\\') { output.Append("\\\\"); continue; }
            if (c == '\'')
            {
                if (quoted && index + 1 < pattern.Length && pattern[index + 1] == '\'')
                { output.Append("\\'"); index++; continue; }
                quoted = !quoted;
            }
            output.Append(c);
        }
        return output.ToString();
    }

    // Framework derives separators from the selected, reescaped patterns, not
    // from a process-wide setting. Quoted/escaped literals stay ordinary text.
    private static string Separator(string pattern, string parts)
    {
        bool quoted = false, found = false; var separator = new StringBuilder();
        for (int index = 0; index < pattern.Length; index++)
        {
            char c = pattern[index];
            if (c == '\\')
            {
                if (index + 1 < pattern.Length && found) separator.Append(pattern[index + 1]);
                index++; continue;
            }
            if (c == '\'') { quoted = !quoted; continue; }
            if (!quoted && parts.Contains(c))
            {
                if (found) break;
                found = true;
                while (index + 1 < pattern.Length && pattern[index + 1] == c) index++;
                continue;
            }
            if (found) separator.Append(c);
        }
        return separator.ToString();
    }
}
