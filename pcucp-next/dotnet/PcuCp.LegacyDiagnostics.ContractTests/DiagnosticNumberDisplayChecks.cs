using System.Globalization;

// Source-derived numerical display checks, not Windows observations. The raw
// PS5.1 original/current/pure/actual-adapter differential remains mandatory.
internal static class DiagnosticNumberDisplayChecks
{
    private static int checks;
    private static void Check(bool condition, string message)
    { checks++; if (!condition) throw new InvalidOperationException(message); }
    private static string IntError(string raw)
    {
        try { _ = LegacyDiagnosticJson.ParseValue(raw).Int32(); }
        catch (NativeFailure error) { return error.Message; }
        throw new InvalidOperationException("Expected object Int32 cast error.");
    }
    internal static void Run()
    {
        (string Raw, string Expected)[] values =
        [
            ("1.2345678901234567e0", "1.23456789012346"),
            ("-1.2345678901234567e0", "-1.23456789012346"),
            ("1e14", "100000000000000"), ("1e15", "1E+15"), ("1e16", "1E+16"),
            ("1e-4", "0.0001"), ("1e-5", "1E-05"), ("0e0", "0"), ("-0e0", "0"),
            ("123456789012344.5e0", "123456789012345"),
            ("-123456789012344.5e0", "-123456789012345"),
            ("123456789012345.5e0", "123456789012346"),
            ("999999999999999.5e0", "1E+15"),
            ("123456789012344.484375e0", "123456789012344"),
            ("123456789012344.515625e0", "123456789012345"),
            ("5e-324", "4.94065645841247E-324"), ("-5e-324", "-4.94065645841247E-324"),
            ("2.2250738585072014e-308", "2.2250738585072E-308"),
            ("1.7976931348623157e308", "1.79769313486232E+308"),
        ];
        foreach (var (raw, expected) in values)
        {
            Check(LegacyDiagnosticJson.ParseValue(raw).Text == expected, "Finite Double display changed: " + raw);
            Check(LegacyDiagnosticJson.ParseValue("{\"value\":" + raw + "}").Text == "@{value=" + expected + "}", "Shallow object display changed: " + raw);
            Check(LegacyDiagnosticJson.ParseValue("[" + raw + ",\"typed\"]").Text == expected + " typed", "Array display changed: " + raw);
        }
        Check(LegacyDiagnosticJson.ParseValue("\"1e16\"").Text == "1e16", "String token was reinterpreted as a Double.");
        Check(LegacyDiagnosticJson.ParseValue("1.2345678901234567").Text == "1.2345678901234567", "Decimal precision changed.");
        Check(LegacyDiagnosticJson.ParseValue("0.00").Text == "0.00", "Decimal scale changed.");
        Check(LegacyDiagnosticJson.ParseValue("Infinity").Text == "Infinity", "Nonfinite invariant display changed.");
        var saved = CultureInfo.CurrentCulture;
        try
        {
            CultureInfo.CurrentCulture = CultureInfo.GetCultureInfo("de-DE");
            Check(LegacyDiagnosticJson.ParseValue("{\"value\":1.2345678901234567e0}").Text == "@{value=1.23456789012346}", "Audit adopted current-culture Double punctuation.");
            Check(IntError("{\"value\":1.2345678901234567e0}").Contains("@{value=1,23456789012346}"), "Object error lost current-culture punctuation.");
            var custom = (CultureInfo)CultureInfo.InvariantCulture.Clone();
            custom.NumberFormat.NumberDecimalSeparator = ",";
            custom.NumberFormat.PositiveSign = "plus";
            custom.NumberFormat.NegativeSign = "minus";
            CultureInfo.CurrentCulture = custom;
            Check(IntError("{\"value\":-1.2345678901234567e16}").Contains("@{value=minus1,23456789012346Eplus16}"), "Object error ignored supplied signs or separator.");
            Check(IntError("{\"value\":-0e0}").Contains("@{value=0}"), "Object error retained the negative-zero sign.");
            Check(custom.NumberFormat.NegativeSign == "minus", "Formatting mutated the supplied culture.");
        }
        finally { CultureInfo.CurrentCulture = saved; }
        Check(ReferenceEquals(CultureInfo.CurrentCulture, saved), "Formatting changed ambient culture.");
        Console.WriteLine($"Passed {checks} source-derived finite-Double display assertions; Windows parity remains pending.");
    }
}
