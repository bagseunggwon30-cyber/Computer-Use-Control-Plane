using System.Globalization;
using System.Text.Json;

// Assertions use actual Windows log fragments where marked, not reconstructed
// raw route arrays (the first failed run did not retain those arrays).
internal static class DiagnosticJsonObservedChecks
{
    private static int checks;
    private static void Check(bool condition, string message)
    { checks++; if (!condition) throw new InvalidOperationException(message); }
    private static string IntError(string raw)
    {
        try { _ = LegacyDiagnosticJson.ParseValue(raw).Int32(); }
        catch (NativeFailure error) { return error.Message; }
        throw new InvalidOperationException("Expected an Int32 conversion error.");
    }
    internal static void Run()
    {
        // Independent no-engine checks are separate from error-message equality.
        var assembly = typeof(LegacyDiagnosticCoordinator).Assembly;
        Check(assembly.GetReferencedAssemblies().All(name => name.Name != "System.Management.Automation"), "Diagnostic assembly references the PowerShell engine.");
        Check(assembly.GetTypes().All(type => type.Namespace != "System.Management.Automation"), "Diagnostic assembly defines or imports engine types.");
        const string suffix = " value of type \"System.Management.Automation.PSCustomObject\" to type \"System.Int32\".";
        Check(IntError("{}") == "Cannot convert the \"\"" + suffix, "Observed empty custom-object cast changed.");
        Check(IntError("{\"value\":1}") == "Cannot convert the \"@{value=1}\"" + suffix, "Observed scalar-member cast changed.");
        Check(IntError("{\"items\":[1,2]}") == "Cannot convert the \"@{items=System.Object[]}\"" + suffix, "Observed array-member cast changed.");
        Check(LegacyDiagnosticJson.ParseValue("true").Double() == 1, "Diagnostic Boolean true became a numeric string.");
        Check(LegacyDiagnosticJson.ParseValue("false").Double() == 0, "Diagnostic Boolean false became a numeric string.");
        Check(LegacyDiagnosticJson.ParseValue("{}").Text == "", "Observed empty object interpolation changed.");
        Check(LegacyDiagnosticJson.ParseValue("{\"nested\":{\"value\":1},\"items\":[1,2]}").Text == "@{nested=; items=System.Object[]}", "Observed shallow interpolation changed.");
        Check(LegacyDiagnosticJson.ParseValue("[[1,2],{},null,0]").Text == "System.Object[]   0", "Nested array interpolation must remain shallow.");
        Check(LegacyDiagnosticJson.ParseValue("\"1e2\"").Double() == 100, "Invariant scientific Double conversion changed.");
        Check(LegacyDiagnosticJson.ParseValue("\"1,000\"").Double() == 1000, "Invariant grouping Double conversion changed.");
        Check(LegacyDiagnosticJson.ParseValue("\" 1 \"").Double() == 1, "Whitespace numeric Double conversion changed.");
        Check(LegacyDiagnosticJson.ParseValue("\"0x10\"").Int32() == 16, "Hexadecimal integer conversion changed.");
        try { _ = LegacyDiagnosticJson.ParseValue("\"0x10\"").Double(); throw new InvalidOperationException("Double cast incorrectly accepted hexadecimal text."); }
        catch (NativeFailure error)
        { Check(error.Message == "Cannot convert value \"0x10\" to type \"System.Double\". Error: \"Input string was not in a correct format.\"", "Source-derived hexadecimal Double error changed."); }
        var saved = CultureInfo.CurrentCulture;
        try
        {
            CultureInfo.CurrentCulture = CultureInfo.GetCultureInfo("de-DE");
            Check(LegacyDiagnosticJson.ParseValue("{\"value\":1.5}").Text == "@{value=1.5}", "Audit interpolation adopted current culture.");
            Check(IntError("{\"value\":1.5}") == "Cannot convert the \"@{value=1,5}\"" + suffix, "Object error display lost current culture.");
            CultureInfo.CurrentCulture = CultureInfo.GetCultureInfo("en-US");
            Check(IntError("Infinity").Contains("\"" + double.PositiveInfinity.ToString(CultureInfo.CurrentCulture) + "\""), "Nonfinite error display lost current culture.");
            Check(LegacyDiagnosticJson.ParseValue("Infinity").Text == "Infinity", "Audit nonfinite interpolation lost invariant culture.");
            Check(IntError("\"Infinity\"").Contains("Input string was not in a correct format."), "A textual nonfinite value impersonated a Double.");
        }
        finally { CultureInfo.CurrentCulture = saved; }
        var format = LegacyDiagnosticCulture.NumericGregorianFormat("yyyy-MM-dd", "tt h:mm:ss", "오전", "오후")!;
        Check(DateTime.UnixEpoch.ToString("G", format) == "1970-01-01 오전 12:00:00", "Synthetic NLS numeric Gregorian formatting changed.");
        Check(DateTime.MinValue.ToString("G", format) == "0001-01-01 오전 12:00:00", "NLS metadata formatting acquired the Win32 1601 date floor.");
        Check(DateTime.MaxValue.ToString("G", format) == "9999-12-31 오후 11:59:59", "Upper DateTime domain changed.");
        Check(LegacyDiagnosticCulture.NumericGregorianFormat("dd MMM yyyy", "HH:mm:ss", "", "") is null, "Named month patterns must remain outside the bounded formatter.");
        Check(LegacyDiagnosticCulture.NumericGregorianFormat("gg y/M/d", "HH:mm:ss", "", "") is null, "Era patterns must remain outside the bounded formatter.");
        Check(LegacyDiagnosticCulture.Reescape("h 'o''clock' mm") == "h 'o\\'clock' mm", "Win32 quote reescaping changed.");
        Check(LegacyDiagnosticCulture.Reescape("yyyy\\MM") == "yyyy\\\\MM", "Win32 literal backslash reescaping changed.");
        Check(ReferenceEquals(saved, CultureInfo.CurrentCulture), "Diagnostic formatting changed CurrentCulture.");
        if (OperatingSystem.IsWindows())
        {
            var korean = CultureInfo.GetCultureInfo("ko-KR");
            var before = korean.DateTimeFormat;
            Check(LegacyDiagnosticCulture.DateTimeErrorText(DateTime.UnixEpoch, korean) == "1970-01-01 오전 12:00:00", "Observed Windows NLS error display changed.");
            Check(ReferenceEquals(before, korean.DateTimeFormat), "Diagnostic formatting mutated the shared culture object.");
        }
        Console.WriteLine($"Passed {checks} diagnostic observed/source-boundary assertions; full Windows route parity remains separate.");
    }
}
