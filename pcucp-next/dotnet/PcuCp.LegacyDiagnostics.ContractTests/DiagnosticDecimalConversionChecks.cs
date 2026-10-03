internal static class DiagnosticDecimalConversionChecks
{
    internal static void Run()
    {
        (string Raw, int? Expected)[] vectors = [
            ("-0.5000000000000000000000000001", -1), ("0.5", 0),
            ("0.5000000000000000000000000001", 1), ("1.4999999999999999999999999999", 1),
            ("1.5", 2), ("2.5", 2), ("-1.5", -2), ("-2.5", -2),
            ("2147483647.4999999999999999999", int.MaxValue), ("2147483647.5", null),
            ("-2147483648.5", int.MinValue), ("-2147483648.5000000000000000001", null),
            ("0.5000000000000000000000000001e0", 0), ("1.4999999999999999999999999999e0", 2),
            ("2147483647.4999999999999999999e0", null),
            ("\"0.5000000000000000000000000001\"", 0), ("\"1.4999999999999999999999999999\"", 2),
            ("\"2147483647.4999999999999999999\"", null)
        ];
        foreach (var (raw, expected) in vectors)
        {
            int? actual = null;
            try { actual = LegacyDiagnosticJson.ParseValue(raw).Int32(); }
            catch (NativeFailure) when (expected is null) { }
            if (actual != expected) throw new InvalidOperationException("Typed diagnostic Int32 conversion changed for " + raw);
        }
        Console.WriteLine($"Passed {vectors.Length} source-derived diagnostic Decimal/Double/string conversion checks; Windows pairing remains separate.");
    }
}
