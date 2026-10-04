using System.Globalization;
using System.Text;
using System.Text.Json;
int passed = 0;
void Check(bool ok, string name) { if (!ok) throw new Exception(name); passed++; }
void Reject(Action action, string name) { try { action(); } catch (NativeFailure) { passed++; return; } catch (JsonException) { passed++; return; } catch (DecoderFallbackException) { passed++; return; } throw new Exception(name); }
Dictionary<string,object?> Payload(params string[] rest) => new() { ["schema"]="cucp.execution-start/v1",["operation"]="workflow-run",["rest"]=rest,["brief"]=false,["cache_seconds"]=2,["vision_available"]=false,["culture"]="en-US" };
string Frames(byte[] bytes) {
    var s = new StringBuilder();
    for (int i=0;i<bytes.Length;i+=49152) s.AppendLine(JsonSerializer.Serialize(new {kind="part",id=0,data=Convert.ToBase64String(bytes,i,Math.Min(49152,bytes.Length-i))}));
    return s.AppendLine("{\"kind\":\"end\",\"id\":0}").ToString();
}
string Wire(object payload) => Frames(JsonSerializer.SerializeToUtf8Bytes(payload));
LegacyExecutionStartup Read(object payload, params string[] options) => LegacyExecutionStartup.Read(options,new StringReader(Wire(payload)));
var ordinary = Read(Payload("--step","windows"));
Check(!ordinary.Authority.AllowLiveControl && !ordinary.Authority.ConfirmSensitive,"Default authority changed");
using (var byteInput = LegacySessionInput.Open(new MemoryStream(Encoding.UTF8.GetBytes("\uFEFF" + Wire(Payload("--label", "한글😀")) + "reply 한글😀\n"))))
{
    var decoded = LegacyExecutionStartup.Read([], byteInput);
    Check(decoded.Rest[1] == "한글😀", "Protocol inherited a console code page");
    Check(byteInput.ReadLine() == "reply 한글😀", "Startup did not preserve the shared UTF8 reply reader");
}
Reject(() => { using var invalid = LegacySessionInput.Open(new MemoryStream([255,10])); LegacyExecutionStartup.Read([], invalid); }, "Protocol accepted malformed UTF8 bytes");
Reject(() => { using var utf16 = LegacySessionInput.Open(new MemoryStream([255,254,123,0,10,0])); LegacyExecutionStartup.Read([], utf16); }, "Protocol auto-detected unsupported UTF16");
var framed = Wire(Payload("--label", "--confirm-sensitive"));
var prefixed = LegacyExecutionStartup.Read(["--confirm-sensitive"], new StringReader("\uFEFF" + framed));
Check(!prefixed.Authority.AllowLiveControl && !prefixed.Authority.ConfirmSensitive, "Encoding preamble granted authority");
Check(prefixed.Rest.SequenceEqual(new[]{"--label", "--confirm-sensitive"}), "Encoding preamble changed argv");
Reject(()=>LegacyExecutionStartup.Read([],new StringReader("\uFEFF\uFEFF"+framed)),"Repeated encoding preamble accepted");
Reject(()=>LegacyExecutionStartup.Read([],new StringReader(" \uFEFF"+framed)),"Embedded encoding preamble accepted");
Reject(()=>LegacyExecutionStartup.Read([],new StringReader(framed.Replace("{\"kind\":\"end\"", "\uFEFF{\"kind\":\"end\""))),"Later-frame encoding preamble accepted");
var prefixedPayload = Frames(Encoding.UTF8.GetBytes("\uFEFF" + JsonSerializer.Serialize(Payload())));
Reject(()=>LegacyExecutionStartup.Read([],new StringReader(prefixedPayload)),"Decoded payload encoding marker accepted");
foreach(var option in new[]{"--label","--text","--type-text","--field","--step","--pre-shortcut","--window"}) {
    var value=Read(Payload(option,"--confirm-sensitive"),"--allow-live-control","--confirm-sensitive");
    Check(value.Authority.AllowLiveControl && !value.Authority.ConfirmSensitive,"Value granted confirmation: "+option);
    Check(Read(Payload(option,"x","--confirm-sensitive"),"--confirm-sensitive").Authority.ConfirmSensitive,"Standalone confirmation lost");
}
Check(!Read(Payload("--confirm-sensitive")).Authority.ConfirmSensitive,"JSON argv minted process authority");
Check(!Read(Payload(),"--confirm-sensitive").Authority.ConfirmSensitive,"Process ceiling minted argv consent");
Check(Read(Payload("--confirm-sensitive"),"--confirm-sensitive").Authority.ConfirmSensitive,"Real consent rejected");
Reject(()=>Read(Payload(),"--confirm-sensitive","--confirm-sensitive"),"Duplicate flags accepted");
Reject(()=>Read(Payload(),"--operation=workflow-run"),"Arbitrary process flags accepted");
foreach(var field in new[]{"allow_live","confirm_sensitive","authority","effects"}) {var p=Payload();p[field]=true;Reject(()=>Read(p),"Startup escalation field accepted");}
foreach(var field in new[]{"schema","operation","rest","brief","cache_seconds","vision_available","culture"}) {var p=Payload();p.Remove(field);Reject(()=>Read(p),"Missing field accepted");}
foreach(var field in new[]{"brief","vision_available","cache_seconds","rest"}) {var p=Payload();p[field]="true";Reject(()=>Read(p),"String coercion accepted");}
var duplicate=JsonSerializer.Serialize(Payload()).Replace("\"brief\":false","\"brief\":false,\"brief\":true");
Reject(()=>LegacyExecutionStartup.Read([],new StringReader(Frames(Encoding.UTF8.GetBytes(duplicate)))),"Duplicate request key accepted");
foreach(var invalid in new[]{"{\"kind\":\"end\",\"id\":1}","{\"kind\":\"end\",\"id\":0,\"live\":true}","{\"kind\":\"part\",\"id\":0,\"data\":\"!\"}","{\"kind\":\"part\",\"id\":0,\"data\":\"\",\"id\":0}"})
    Reject(()=>LegacyExecutionStartup.Read([],new StringReader(invalid+"\n")),"Invalid frame accepted");
Reject(()=>LegacyExecutionStartup.Read([],new StringReader(new string('x',66001)+"\n")),"Unbounded startup line accepted");
Reject(()=>LegacyExecutionStartup.Read([],new StringReader("")),"Closed stream accepted");
Reject(()=>LegacyExecutionStartup.Read([],new StringReader(Frames([255]))),"Invalid UTF8 accepted");
var large=Read(Payload("--step",new string('x',1200000)));Check(large.Rest[1].Length==1200000,"Large startup was truncated or limited to 1MiB");
var originalCulture=CultureInfo.CurrentCulture;Read(Payload());Check(ReferenceEquals(originalCulture,CultureInfo.CurrentCulture),"Parsing changed process culture");
var confirmed=JsonSerializer.SerializeToElement(LegacyExecutionStartup.Confirmation(JsonSerializer.SerializeToElement(new{original_argv=new[]{"--label","--confirm-sensitive"}})));
Check(!confirmed.GetProperty("confirmed").GetBoolean(),"Pure confirmation helper granted data consent");
// The process entry point chooses the family; request data cannot cross it.
Dictionary<string, object?> FamilyPayload(string family, string operation)
{
    var p = Payload("--label", "--confirm-sensitive"); p["operation"] = operation;
    p["schema"] = family == "interaction" ? "cucp.interaction-start/v1" : "cucp.diagnostic-start/v1";
    if (family == "interaction") { p["double"] = false; p["right_click"] = false; }
    else p["context"] = new Dictionary<string, object?> { ["audit_directory"] = @"C:\owned\audit", ["cache_directory"] = @"C:\owned\cache",
        ["wrapper_log"] = @"C:\owned\wrapper.log", ["cli_path"] = null, ["changelog_path"] = @"C:\source\CHANGELOG.md", ["temp_root"] = @"C:\temp",
        ["benchmark_schema"] = "cucp.benchmark/v1", ["release_schema"] = "cucp.release-notes/v1" };
    return p;
}
LegacyExecutionStartup ReadFamily(object value, string family, params string[] options) => LegacyExecutionStartup.Read(options, new StringReader(Wire(value)), family);
foreach (var family in new[] { "interaction", "diagnostics" })
{
    var op = family == "interaction" ? "find-label" : "health-quick";
    var p = FamilyPayload(family, op);
    var v = ReadFamily(p, family, "--allow-live-control", "--confirm-sensitive");
    Check(v.Family == family && v.Operation == op && v.Authority.AllowLiveControl && !v.Authority.ConfirmSensitive, "Family startup changed consent semantics");
    Reject(() => Read(p), "A new family entered legacy execution startup");
    Reject(() => ReadFamily(Payload(), family), "Old execution request entered a new family");
    foreach (var authorityField in new[] { "live", "authority", "confirm_sensitive", "family" })
    { var modified = FamilyPayload(family, op); modified[authorityField] = true; Reject(() => ReadFamily(modified, family), "Reply-style authority field accepted"); }
    p["operation"] = "workflow-run"; Reject(() => ReadFamily(p, family), "Cross-family operation accepted");
}
foreach (var name in new[] { "double", "right_click" })
{
    foreach (var bad in new object?[] { "true", 1, null, new[] { true } })
    { var p = FamilyPayload("interaction", "click-label"); p[name] = bad; Reject(() => ReadFamily(p, "interaction"), "Coerced click flag accepted"); }
    var valid = FamilyPayload("interaction", "click-label"); valid[name] = true;
    Check(name == "double" ? ReadFamily(valid, "interaction").Double : ReadFamily(valid, "interaction").RightClick, "Explicit click option lost");
    valid["operation"] = "find-label"; Reject(() => ReadFamily(valid, "interaction"), "Click option applied outside click-label");
}
var diagnostic = FamilyPayload("diagnostics", "health-quick");
Check(ReadFamily(diagnostic, "diagnostics").Context.GetProperty("cli_path").ValueKind == JsonValueKind.Null, "Missing CLI path became empty string");
foreach (var name in new[] { "audit_directory", "cache_directory", "wrapper_log", "cli_path", "changelog_path", "temp_root", "benchmark_schema", "release_schema" })
{
    var p = FamilyPayload("diagnostics", "health-quick"); var context = (Dictionary<string, object?>)p["context"]!;
    context[name] = 12; Reject(() => ReadFamily(p, "diagnostics"), "Numeric owned context accepted");
    context[name] = "bad\0path"; Reject(() => ReadFamily(p, "diagnostics"), "NUL owned context accepted");
    context.Remove(name); Reject(() => ReadFamily(p, "diagnostics"), "Missing owned context accepted");
}
Reject(() => ReadFamily(FamilyPayload("diagnostics", "health-quick"), "arbitrary"), "Unknown trusted entry family accepted");
Console.WriteLine($"PASS: {passed} execution startup authority and framing checks; no effects executed.");
