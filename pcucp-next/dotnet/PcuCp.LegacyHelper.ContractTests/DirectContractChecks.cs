using System;
using System.Collections.Generic;
using System.Linq;
using PcuCp.LegacyHelper;

internal static class DirectContractChecks
{
    private static int checks;
    private static void Check(bool value, string reason) { checks++; if (!value) throw new Exception("direct contract: " + reason); }
    private static void Reject(Action action)
    {
        bool rejected = false;
        try { action(); } catch (ArgumentException) { rejected = true; }
        Check(rejected, "invalid direct option was accepted");
    }
    internal static void Run()
    {
        foreach (string name in new[] { "owned-direct", "한글 공백 (a) %!&^_+=", "MiXeD_Case", "contains.anonymous", "A" + Char.ConvertFromUtf32(0x1f600), new string('a', 247) })
            Check(LegacyHelperDirect.PipeName(name) == name, "name spelling changed");
        foreach (string name in new[] { null, "", "Anonymous", "aNoNyMoUs", ".", "..", "ends.", "ends ", "\\\\.\\pipe\\name",
            "a/b", "a\\b", "a:b", "a\n", "a\r", "a\t", "a\0", "a\x007f", "a\"b", "a<b", "a>b", "a|b", "\ud800", "\udc00", new string('a', 248), new string('a', 246) + Char.ConvertFromUtf32(0x1f600) }) Reject(() => LegacyHelperDirect.PipeName(name));
        Check(LegacyHelperDirect.LockLeaf("owned-한글.pid") == "owned-한글.pid", "lock leaf changed");
        foreach (string name in new[] { "helper.pid", "HELPER-STAGED.PID", "helper.pid::$DATA", "owned.pid:stream", "NUL", "con.txt", "CON .txt", "PRN", "AUX",
            "COM1.pid", "LPT9.pid", "COM¹.pid", "LPT²", "CLOCK$", "CONIN$", "CONOUT$", "ends.", "ends ", "a/b", "a\\b", "a?b", "a*b", "a\n" }) Reject(() => LegacyHelperDirect.LockLeaf(name));
        foreach (string path in new[] { @"C:\owned.pid", @"c:\Users\RUNNER~1\Temp\owned.pid", @"C:\한글 공백\MiXeD.pid", @"C:\helper.pid\owned.pid" })
            Check(String.Join("\\", LegacyHelperDirect.LockPathParts(path)) == path.Substring(3), "raw path spelling changed");
        foreach (string path in new[] { null, "", "owned.pid", @"C:owned.pid", @"C:\", @"C:\\owned.pid", @"C:\a\.\owned.pid", @"C:\a\..\owned.pid",
            @"C:\a\", @"C:/a/owned.pid", @"C:\a/owned.pid", @"C:\a \owned.pid", @"C:\a.\owned.pid", @"C:\a:stream\owned.pid",
            @"C:\NUL\owned.pid", @"C:\COM1.log\owned.pid", @"C:\a\helper.pid", @"C:\a\HELPER-STAGED.PID", @"C:\owned.pid:stream",
            @"\\server\share\owned.pid", @"\\?\C:\owned.pid", @"\\.\C:\owned.pid", "C:\\a\n\\owned.pid", "C:\\\ud800\\owned.pid" })
            Reject(() => LegacyHelperDirect.LockPathParts(path));
        var rows = new List<string>();
        var log = new LegacyHelperDebugLog(rows.Add);
        log.Event("server.start");
        log.Request("TOP_SECRET_TOKEN", "unknown\nTOP_SECRET_PAYLOAD");
        log.Response(99);
        log.Request(new Dictionary<string, object> { ["secret"] = "TOP_SECRET_PAYLOAD" }, "HEALTH");
        log.Response(0);
        Check(rows[1] == "helper_debug event=request sequence=1 action=other id_kind=string", "untrusted request data escaped into debug");
        Check(rows[3] == "helper_debug event=request sequence=2 action=health id_kind=other", "known action/type metadata changed");
        Check(!String.Join("\n", rows).Contains("TOP_SECRET"), "debug leaked data");
        foreach (int code in new[] { 0, 1, 2, 99 }) log.Response(code);
        Reject(() => log.Event("unknown-event"));
        Reject(() => log.Response(3));
        for (int i = 0; i < 1000; i++) { log.Request("secret", "secret"); log.Event("client.connected"); log.Response(0); }
        Check(rows.Count == LegacyHelperDebugLog.MaxEvents + 1, "debug event cap");
        Check(rows.Last() == "helper_debug event=limit", "one fixed limit marker");
        Check(rows.All(row => row.Length <= LegacyHelperDebugLog.MaxLineCharacters && !row.Contains("\r") && !row.Contains("\n")), "debug line/control bound");
        Console.WriteLine("Legacy helper direct contracts: " + checks + " passed");
    }
}
