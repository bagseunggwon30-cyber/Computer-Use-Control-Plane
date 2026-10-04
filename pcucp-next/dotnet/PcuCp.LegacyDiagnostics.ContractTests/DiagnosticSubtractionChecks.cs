using System.Globalization;

// Source-derived arithmetic contracts, separate from Windows oracle evidence.
// Keep both numeric value and boxed type: PS widens Int32 overflow to Double.
internal static class DiagnosticSubtractionChecks
{
    internal static void Run()
    {
        (int Left, int Right)[] cases = [
            (37, int.MinValue), (37, int.MaxValue),
            (0, int.MinValue), (0, int.MaxValue),
            (int.MinValue, 0), (int.MaxValue, 0),
            (int.MinValue, 1), (int.MaxValue, -1),
            (int.MinValue, -1), (int.MaxValue, 1),
            (int.MaxValue, int.MinValue), (int.MinValue, int.MaxValue)
        ];
        int checks = 0;
        foreach (var (left, right) in cases)
        {
            long expected = (long)left - right;
            object actual = LegacyDiagnosticCoordinator.DiagnosticSubtractInt32(left, right);
            bool promote = expected < int.MinValue || expected > int.MaxValue;
            if (actual.GetType() != (promote ? typeof(double) : typeof(int)))
                throw new InvalidOperationException($"Subtraction changed numeric type for {left} - {right}.");
            checks++;
            if (Convert.ToDouble(actual, CultureInfo.InvariantCulture) != expected)
                throw new InvalidOperationException($"Subtraction wrapped or rounded {left} - {right}.");
            checks++;
        }
        Console.WriteLine($"Passed {checks} source-derived diagnostic subtraction assertions; Windows oracle parity remains separate.");
    }
}
