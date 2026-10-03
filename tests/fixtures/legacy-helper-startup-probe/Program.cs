using System;
using System.IO;
using System.Text;

// Isolated console-boundary comparison only: no desktop, IPC or service logic.
// legacy-setter reproduces the candidate Program.Main setup statement exactly;
// it is not a rebuilt historical helper executable or an action parity oracle.
internal static class Program
{
    private static int Main(string[] args)
    {
        if (args.Length != 1) return 2;
        if (args[0] == "legacy-setter")
        {
            Console.OutputEncoding = new UTF8Encoding(false);
        }
        else if (args[0] == "stream-writers")
        {
            Console.SetOut(new StreamWriter(Console.OpenStandardOutput(), new UTF8Encoding(false)) { AutoFlush = true });
            Console.SetError(new StreamWriter(Console.OpenStandardError(), new UTF8Encoding(false)) { AutoFlush = true });
        }
        else return 2;
        Console.Out.WriteLine("startup-out:한글😀");
        Console.Error.WriteLine("startup-err:한글😀");
        return 0;
    }
}
