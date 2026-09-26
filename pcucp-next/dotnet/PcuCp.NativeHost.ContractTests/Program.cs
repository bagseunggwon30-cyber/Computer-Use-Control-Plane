using System.Runtime.InteropServices;
using System.Text.Json;

var count = 0;
void Check(bool condition, string message) { if (!condition) throw new Exception(message); count++; }
void Reject(Action action, string message)
{
    try { action(); } catch (NativeFailure) { count++; return; }
    throw new Exception(message);
}

// A wrong ABI layout can make SendInput fail or reinterpret keyboard input as mouse input.
Check(Marshal.SizeOf<NativeMethods.INPUT>() == (IntPtr.Size == 8 ? 40 : 28), "INPUT ABI size mismatch");
Check(Marshal.OffsetOf<NativeMethods.INPUT>(nameof(NativeMethods.INPUT.Data)).ToInt32() == (IntPtr.Size == 8 ? 8 : 4), "INPUT union alignment mismatch");
Check(Marshal.SizeOf<NativeMethods.MOUSEINPUT>() == (IntPtr.Size == 8 ? 32 : 24), "MOUSEINPUT ABI size mismatch");

// Validate physical→normalized→physical round trips for every pixel across mixed-monitor desktops.
foreach (var (origin, width) in new[] { (-1920, 3840), (-2560, 6400), (0, 1920), (-1, 2) })
{
    for (var x = origin; x < origin + width; x++)
    {
        var normalized = InputGeometry.Normalize(x, origin, width);
        var physical = (int)((long)normalized * width / 65536) + origin;
        Check(physical == x, $"Pixel {x} became {physical} on desktop {origin}:{width}");
    }
}
Reject(() => InputGeometry.Normalize(-1921, -1920, 3840), "Point left of desktop accepted");
Reject(() => InputGeometry.Normalize(1920, -1920, 3840), "Exclusive desktop end accepted");
Check(new PixelRect(-1920, -1080, 3840, 2160).Contains(0, 0), "Zero coordinate rejected");
Check(new PixelRect(int.MaxValue - 1, 0, 100, 10).Contains(int.MaxValue, 1), "Rect arithmetic overflowed");

// Authority flags cannot be smuggled as positional values or duplicated.
Reject(() => new CommandOptions(["--allow-live-control", "false"]), "Boolean positional value accepted");
Reject(() => new CommandOptions(["--ALLOW-LIVE-CONTROL", "false"]), "Uppercase boolean flag consumed false and enabled authority");
Reject(() => new CommandOptions(["--pid", "1", "--pid", "2"]), "Duplicate process selector accepted");
Reject(() => new CommandOptions(["--hwnd", "--allow-live-control"]), "Flag consumed as target value");
Reject(() => new CommandOptions(["--unsafe", "yes"]).Allow("--pid"), "Unknown option accepted");
var negative = new CommandOptions(["--x", "-1920", "--y", "0"]);
Check(negative.RequiredInteger("--x") == -1920 && negative.RequiredInteger("--y") == 0, "Signed physical coordinates rejected");

// These cases must fail before any platform call or focus mutation, even on Linux.
Reject(() => DesktopActions.Execute("click", new CommandOptions(["--hwnd", "0x1", "--pid", "1", "--x", "0", "--y", "0"])), "Native action without authority accepted");
Reject(() => DesktopActions.Execute("focus", new CommandOptions(["--hwnd", "0x1", "--pid", "1", "--allow-live-control", "--expected-x", "0"])), "Focus geometry reached a mutating path");

var medium = new ProcessPrivileges(1, false, 0x2000, "medium", false);
var high = new ProcessPrivileges(2, true, 0x3000, "high", false);
var system = new ProcessPrivileges(3, true, 0x4000, "system", false);
Check(PrivilegeInspector.AccessStatus(medium, high) == "elevation_required", "Unelevated input into elevated target accepted");
Check(PrivilegeInspector.AccessStatus(high, medium) == "integrity_check_passed", "Elevated input into normal target rejected");
Check(PrivilegeInspector.AccessStatus(medium with { UiAccess = true }, high) == "integrity_check_passed", "Valid UIAccess high-integrity case rejected");
Check(PrivilegeInspector.AccessStatus(medium with { UiAccess = true }, system) == "unsupported_protected_target", "UIAccess allowed SYSTEM target");
Check(PrivilegeInspector.AccessStatus(system, system) == "unsupported_protected_target", "SYSTEM automation scope widened");

var encoded = JsonSerializer.Serialize(NativeResult.Error("click", "target_mismatch", "Changed PID"), new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower });
using var json = JsonDocument.Parse(encoded);
Check(json.RootElement.GetProperty("status").GetString() == "error", "Error presented as success");
Check(json.RootElement.GetProperty("errors")[0].GetProperty("code").GetString() == "target_mismatch", "Machine-readable error lost");
Console.WriteLine($"PASS: {count} ABI, geometry and command-authority contract checks (no Windows input executed).");
