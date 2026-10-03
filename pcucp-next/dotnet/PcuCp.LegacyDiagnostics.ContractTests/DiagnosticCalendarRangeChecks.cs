using System.Globalization;

internal static class DiagnosticCalendarRangeChecks
{
    internal static void Run()
    {
        var culture = CultureInfo.GetCultureInfo("fa-IR");
        var format = culture.DateTimeFormat;
        var date = new DateTime(1, 1, 2, 0, 0, 0, DateTimeKind.Utc);
        if (LegacyDiagnosticCulture.DateTimeErrorText(date, culture) != date.ToString("O", CultureInfo.InvariantCulture))
            throw new InvalidOperationException("Calendar-range diagnostic did not use its bounded invariant fallback.");
        var valid = new DateTime(1970, 1, 1);
        if (LegacyDiagnosticCulture.DateTimeErrorText(valid, culture) != valid.ToString(culture))
            throw new InvalidOperationException("An in-range culture diagnostic changed.");
        if (!ReferenceEquals(format, culture.DateTimeFormat))
            throw new InvalidOperationException("Calendar-range formatting mutated its culture.");
        Console.WriteLine("Passed 3 benchmark calendar-range containment checks; original Windows comparison remains separate.");
    }
}
