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
Console.WriteLine($"PASS: {passed} execution startup authority and framing checks; no effects executed.");
