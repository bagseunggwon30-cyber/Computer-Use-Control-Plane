using System;
internal static class Program {
    private static int count;
    private static void Check(bool condition, string name) { if (!condition) throw new InvalidOperationException(name); count++; }
    private static int Main() {
        try { PrimitiveContractTests.Run(Check); ActionContractTests.Run(Check); Console.WriteLine("observation contracts: " + count + " passed"); return 0; }
        catch (Exception error) { Console.Error.WriteLine(error); return 1; }
    }
}
