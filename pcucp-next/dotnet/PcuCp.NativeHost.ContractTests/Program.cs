using System.IO;
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
foreach (var (down, up) in new[] { (2u, 4u), (8u, 16u), (32u, 64u) })
{
    var clicks = DesktopActions.ClickEvents(down, up, 2);
    Check(clicks.Length == 4, "Double-click must use four events in one dispatch");
    Check(clicks.Select(e => e.Data.Mouse.Flags).SequenceEqual(new[] { down, up, down, up }), "Double-click left a button held or reordered input");
}
Reject(() => DesktopActions.ClickEvents(2, 4, 0), "Zero clicks accepted");
Reject(() => DesktopActions.ClickEvents(2, 4, 3), "Unbounded click count accepted");

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
// The resident wire boundary is testable without calling Windows APIs.
string Request(long id, string command = "version", string[]? args = null) => JsonSerializer.Serialize(new
    { schema = "pcucp.native.request/v1", id, command, args = args ?? Array.Empty<string>() });
Check(NativeSession.Parse(Request(1), false, 0).Id == 1, "First request rejected");
Reject(() => NativeSession.Parse(Request(1), false, 1), "Duplicate request replay accepted");
Reject(() => NativeSession.Parse(Request(0), false, 0), "Zero request ID accepted");
Reject(() => NativeSession.Parse(Request(1, "serve"), true, 0), "Nested server accepted");
Reject(() => NativeSession.Parse(Request(1, "click", ["--allow-live-control"]), false, 0), "Request elevated read-only worker");
Reject(() => NativeSession.Parse(Request(1, "version", ["--ALLOW-LIVE-CONTROL"]), false, 0), "Uppercase authority flag accepted");
Check(NativeSession.Parse(Request(1, "click", ["--allow-live-control"]), true, 0).Command == "click", "Startup opt-in lost");
var dispatched = new List<string>();
Task<DispatchResult> FakeDispatch(string command, string[] args)
{
    dispatched.Add(command);
    return Task.FromResult(new DispatchResult(0, NativeResult.Ok(command, new { process = 123 })));
}
async Task<(int Code, string Output)> RunWire(byte[] bytes, bool allow = false)
{
    using var stream = new MemoryStream(bytes);
    using var writer = new StringWriter();
    var code = await NativeSession.RunAsync(stream, writer, allow, FakeDispatch);
    return (code, writer.ToString());
}
var wire = await RunWire(System.Text.Encoding.UTF8.GetBytes(Request(1) + "\n" + Request(2) + "\n"));
Check(wire.Code == 0 && dispatched.Count == 2, "Sequential wire requests did not execute");
var responses = wire.Output.Split('\n', StringSplitOptions.RemoveEmptyEntries);
using var second = JsonDocument.Parse(responses[1]);
Check(second.RootElement.GetProperty("id").GetInt64() == 2, "Response correlation lost");
Check(second.RootElement.GetProperty("payload").GetProperty("data").GetProperty("process").GetInt32() == 123, "Payload not preserved");
dispatched.Clear();
wire = await RunWire(System.Text.Encoding.UTF8.GetBytes(Request(1) + "\n" + Request(1) + "\n" + Request(2) + "\n"));
Check(wire.Code == 2 && dispatched.Count == 1, "Duplicate did not terminate without replay");
dispatched.Clear();
wire = await RunWire(System.Text.Encoding.UTF8.GetBytes(Request(1, "click", ["--allow-live-control"]) + "\n"));
Check(wire.Code == 2 && dispatched.Count == 0, "Readonly wire dispatched a mutation");
wire = await RunWire(new byte[NativeSession.MaxFrameBytes + 1]);
Check(wire.Code == 2 && dispatched.Count == 0, "Oversized frame executed");
wire = await RunWire(System.Text.Encoding.UTF8.GetBytes(Request(1)));
Check(wire.Code == 2 && dispatched.Count == 0, "Unterminated frame executed");
wire = await RunWire(new byte[] { 0xff, 10 });
Check(wire.Code == 2 && dispatched.Count == 0, "Invalid UTF8 executed");
await AppLifecycleContractChecks.RunAsync(Check);
var startup = ParentLifetimeGuard.Extract(["serve", "--parent-handle", "123", "--allow-live-control"]);
Check(startup.Handle == new IntPtr(123) && startup.Args.SequenceEqual(new[] { "serve", "--allow-live-control" }), "Guard handle extraction failed");
foreach (var bad in new[] { new[] { "--parent-handle" }, new[] { "--parent-handle", "-1" }, new[] { "--parent-handle", "0" }, new[] { "--parent-handle", "1", "--PARENT-HANDLE", "2" } })
    Reject(() => ParentLifetimeGuard.Extract(bad), "Malformed parent handle accepted");
double referenceTime = 0;
var refs = new UiaReferenceStore<string>(() => referenceTime);
refs.Begin();
var firstRef = refs.Add("one");
var siblingRef = refs.Add("two");
Check(firstRef.Length == 48 && firstRef != siblingRef, "Opaque refs not unique");
Check(refs.Consume(firstRef) == "one", "Correct ref failed");
Reject(() => refs.Consume(siblingRef), "Sibling ref replayed after action");
refs.Begin(); var expiredRef = refs.Add("old"); referenceTime = 61;
Reject(() => refs.Consume(expiredRef), "Expired ref accepted");
refs.Begin(); var wrongRef = refs.Add("wrong");
Reject(() => refs.Consume("made-up"), "Arbitrary ref accepted");
Reject(() => refs.Consume(wrongRef), "Failed attempt did not consume generation");
refs.Begin(); var priorRef = refs.Add("prior"); refs.Begin();
Reject(() => refs.Consume(priorRef), "New observation kept old ref");
var path = DesktopActions.DragPoints(-1920, -200, -2, 878, 16);
Check(path.Length == 17 && path[0] == (-1920, -200) && path[^1] == (-2, 878), "Drag path endpoints changed");
Reject(() => DesktopActions.DragPoints(0, 0, 10, 10, 65), "Unbounded drag accepted");
var dragEvents = DesktopActions.DragEvents(path, new PixelRect(-1920, -200, 1920, 1080));
Check(dragEvents.Length == 18 && dragEvents[0].Data.Mouse.Flags == 2 && dragEvents[^1].Data.Mouse.Flags == 4, "Drag is not one down/move/up batch");
for (var accepted = 1; accepted < dragEvents.Length; accepted++)
    Check(DesktopActions.PendingReleases(dragEvents.Take(accepted)).Single().Data.Mouse.Flags == 4, "Partial drag missing release");
Check(DesktopActions.PendingReleases(dragEvents).Length == 0, "Completed drag retained button");
foreach (var mutation in new[] { "drag", "uia-invoke", "uia-set-value" })
    Reject(() => NativeSession.Parse(Request(1, mutation), false, 0), "New mutation escaped read-only authority");
UiaPatternContractChecks.Run(Check);
OcrWindowContractChecks.Run(Check);
Console.WriteLine($"PASS: {count} ABI, geometry, lifecycle and command-authority contract checks (no Windows input or apps executed).");
