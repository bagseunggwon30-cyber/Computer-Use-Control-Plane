"""Safety regressions for the execution boundary; children are disposable echoes."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
BASELINE_TREE="bf895d3120dd5e145f360cb1c41e1d79a061d048"


@unittest.skipUnless(sys.platform=="win32","Windows PowerShell diagnostic contract")
class ExecutionAdapterDiagnosticTests(unittest.TestCase):
    def test_adapter_diagnostic_is_opt_in_bounded_and_limited(self):
        from test_legacy_execution_parity import adapter_source
        with tempfile.TemporaryDirectory(prefix="CUCP protocol diagnostic ") as temp:
            runner=Path(temp)/"diagnostic.ps1"
            runner.write_text(r'''
param([string]$Source)
$ErrorActionPreference='Stop';[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
$definition=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq '_Execution-WriteDiagnostic'},$true))
if($errors.Count -or $definition.Count -ne 1){throw 'Expected one diagnostic helper'}
. ([scriptblock]::Create($definition[0].Extent.Text))
$state=@{diagnostic_phase='parse-frame';diagnostic_expected_id=1;diagnostic_frame=([string][char]0xFEFF+('x'*100000))}
$env:CUCP_EXECUTION_DIAGNOSTICS='0';_Execution-WriteDiagnostic $state $null $null ('e'*3000)
$env:CUCP_EXECUTION_DIAGNOSTICS='1'
1..8|ForEach-Object {_Execution-WriteDiagnostic $state $null $null ('e'*3000)}
''',encoding="utf-8-sig")
            p=subprocess.run([shutil.which("powershell.exe"),"-NoProfile","-NonInteractive","-File",str(runner),"-Source",str(adapter_source())],capture_output=True,timeout=30)
            self.assertEqual(p.returncode,0,p.stderr.decode(errors="replace"))
            lines=p.stderr.decode("utf-8-sig",errors="replace").splitlines()
            self.assertEqual(len(lines),4)
            self.assertLess(len(p.stderr),10000)
            for line in lines:
                self.assertTrue(line.startswith("[execution-protocol] "))
                row=json.loads(line.removeprefix("[execution-protocol] "))
                self.assertEqual(row["prefix_codepoints"][0],"U+FEFF")
                self.assertEqual(row["frame_characters"],100001)
                self.assertEqual(len(row["frame_prefix"]),256)
                self.assertEqual(len(row["error"]),512)
                self.assertEqual(row["expected_id"],1)


@unittest.skipUnless(sys.platform=="win32","Windows PowerShell argument binding characterization")
class ExecutionOriginalDefectTests(unittest.TestCase):
    def test_framework_redirected_stdin_can_emit_bom_before_explicit_no_bom_writer(self):
        """Characterize Framework Process.StandardInput with an inert byte echo."""
        with tempfile.TemporaryDirectory(prefix="CUCP stdin bytes ") as temp:
            runner=Path(temp)/"bytes.ps1"
            runner.write_text(r'''
$ErrorActionPreference='Stop'
$previous=[Console]::InputEncoding;$process=$null;$writer=$null
try {
 [Console]::InputEncoding=New-Object Text.UTF8Encoding($true)
 [Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
 $echo='$buffer=New-Object IO.MemoryStream;[Console]::OpenStandardInput().CopyTo($buffer);[Console]::Out.Write([Convert]::ToBase64String($buffer.ToArray()))'
 $psi=New-Object Diagnostics.ProcessStartInfo
 $psi.FileName=(Get-Command powershell.exe -CommandType Application).Source
 $psi.Arguments='-NoProfile -NonInteractive -EncodedCommand '+[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($echo))
 $psi.UseShellExecute=$false;$psi.RedirectStandardInput=$true;$psi.RedirectStandardOutput=$true;$psi.RedirectStandardError=$true
 $process=New-Object Diagnostics.Process;$process.StartInfo=$psi;[void]$process.Start()
 $stdout=$process.StandardOutput.ReadToEndAsync();$stderr=$process.StandardError.ReadToEndAsync()
 $utf8=New-Object Text.UTF8Encoding($false,$true)
 $writer=New-Object IO.StreamWriter -ArgumentList @($process.StandardInput.BaseStream,$utf8,4096,$true)
 $writer.WriteLine('{"kind":"end","id":0}');$writer.Flush();$writer.Dispose();$writer=$null
 $process.StandardInput.Close();$process.WaitForExit()
 if($process.ExitCode -ne 0){throw $stderr.GetAwaiter().GetResult()}
 [Console]::Out.WriteLine($stdout.GetAwaiter().GetResult())
} finally {
 if($null -ne $writer){$writer.Dispose()}
 if($null -ne $process){try {if(-not $process.HasExited){$process.Kill()}}catch {};$process.Dispose()}
 [Console]::InputEncoding=$previous
}
''',encoding="utf-8-sig")
            p=subprocess.run([shutil.which("powershell.exe"),"-NoProfile","-NonInteractive","-File",str(runner)],capture_output=True,timeout=30)
            self.assertEqual(p.returncode,0,p.stderr.decode(errors="replace"))
            import base64
            self.assertEqual(base64.b64decode(p.stdout.strip()),b'\xef\xbb\xbf{"kind":"end","id":0}\r\n')

    def test_original_literal_value_is_misclassified_as_consent(self):
        with tempfile.TemporaryDirectory(prefix="CUCP consent fixture ") as temp:
            d=Path(temp);source=d/"source.ps1";runner=d/"check.ps1"
            source.write_bytes(subprocess.check_output(["git","show",f"{BASELINE_TREE}:scripts/cucp.ps1"],cwd=ROOT))
            runner.write_text(r'''
param([string]$Source)
$ErrorActionPreference='Stop';$t=$null;$e=$null
$a=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$t,[ref]$e)
$f=@($a.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq '_Read-Switch'},$true))
if($f.Count -ne 1){throw 'Expected original switch reader'}
. ([scriptblock]::Create($f[0].Extent.Text))
$result=@(foreach($name in @('--label','--text','--type-text','--field','--step')){
 [ordered]@{name=$name;incorrect_consent=(_Read-Switch -Rest @($name,'--confirm-sensitive') -Name '--confirm-sensitive')}
})
[Console]::Out.WriteLine((ConvertTo-Json -InputObject $result -Compress))
''',encoding="utf-8-sig")
            p=subprocess.run([shutil.which("powershell.exe"),"-NoProfile","-NonInteractive","-File",str(runner),"-Source",str(source)],capture_output=True,timeout=30)
            self.assertEqual(p.returncode,0,p.stderr.decode(errors="replace"));observed=json.loads(p.stdout.decode("utf-8-sig"))
            self.assertTrue(all(x["incorrect_consent"] for x in observed))
    def test_original_native_file_invocation_rebinds_literal_control_flag(self):
        with tempfile.TemporaryDirectory(prefix="CUCP rebinding fixture ") as temp:
            echo=Path(temp)/"echo.ps1";echo.write_text(ECHO_CHILD,encoding="utf-8-sig")
            p=subprocess.run([shutil.which("powershell.exe"),"-NoProfile","-NonInteractive","-File",str(echo),"-Quiet","macro","windows","--match","-AllowLiveControl"],capture_output=True,timeout=30)
            self.assertEqual(p.returncode,0,p.stderr.decode(errors="replace"));r=json.loads(p.stdout.decode("utf-8-sig"))
            self.assertTrue(r["live"],"This test explicitly characterizes the original binder defect")
            self.assertNotIn("-AllowLiveControl",r["argv"])


@unittest.skipUnless(sys.platform=="win32" and bool(os.environ.get("CUCP_EXECUTION_TEST_HOST")),"Actual execution adapter is not enabled")
class ExecutionActualTransportTests(unittest.TestCase):
    def test_named_argv_and_immutable_sensitive_context_with_inert_child(self):
        vectors=[[],["macro","windows","--match","-AllowLiveControl"],
                 ["macro","windows","--match","-Brief"],
                 ["macro","windows","--match","-CucpArgs"],
                 ["macro","windows","--match","--confirm-sensitive"],
                 ["macro","windows","--match","' \" ` $() 한글😀"],
                 ["macro","windows","--match",""]]
        fixtures=[dict(argv=v,live=live,quiet=True,brief=False,confirm_sensitive=False) for v in vectors for live in (False,True)]
        with tempfile.TemporaryDirectory(prefix="CUCP typed child 한글 ") as temp:
            d=Path(temp);echo=d/"echo.ps1";echo.write_text(ECHO_CHILD,encoding="utf-8-sig")
            inputs=d/"inputs.json";inputs.write_text(json.dumps(fixtures),encoding="utf-8-sig")
            runner=d/"check.ps1";runner.write_text(ACTUAL_ADAPTER_RUNNER,encoding="utf-8-sig")
            p=subprocess.run([shutil.which("powershell.exe"),"-NoProfile","-NonInteractive","-File",str(runner),"-Source",os.environ.get("CUCP_EXECUTION_ADAPTER_SOURCE",str(ROOT/"scripts/cucp.ps1")),"-Child",str(echo),"-InputPath",str(inputs)],capture_output=True,timeout=120)
            self.assertEqual(p.returncode,0,p.stderr.decode(errors="replace"));results=json.loads(p.stdout.decode("utf-8-sig"))
            self.assertEqual(len(results),len(fixtures))
            for f,r in zip(fixtures,results):
                self.assertEqual(r["exit"],0);self.assertEqual(r["json"]["argv"],f["argv"])
                self.assertEqual(r["json"]["live"],f["live"]);self.assertTrue(r["json"]["quiet"])
                self.assertFalse(r["json"]["brief"]);self.assertFalse(r["json"]["sensitive_ceiling"])
                self.assertFalse(r["json"]["sensitive"])

    def test_parent_permission_does_not_upgrade_ungranted_child_effect(self):
        fixtures=[dict(argv=["macro","windows","--confirm-sensitive"],live=True,quiet=True,brief=False,confirm_sensitive=grant) for grant in (False,True)]
        with tempfile.TemporaryDirectory(prefix="CUCP per effect ceiling ") as temp:
            d=Path(temp);echo=d/"echo.ps1";echo.write_text(ECHO_CHILD,encoding="utf-8-sig")
            inputs=d/"input.json";inputs.write_text(json.dumps(fixtures),encoding="utf-8-sig")
            runner=d/"check.ps1";runner.write_text(ACTUAL_ADAPTER_RUNNER,encoding="utf-8-sig")
            p=subprocess.run([shutil.which("powershell.exe"),"-NoProfile","-NonInteractive","-File",str(runner),"-Source",os.environ.get("CUCP_EXECUTION_ADAPTER_SOURCE",str(ROOT/"scripts/cucp.ps1")),"-Child",str(echo),"-InputPath",str(inputs),"-SensitiveCeiling"],capture_output=True,timeout=60)
            self.assertEqual(p.returncode,0,p.stderr.decode(errors="replace"));results=json.loads(p.stdout.decode("utf-8-sig"))
            for grant,result in zip((False,True),results):
                self.assertEqual(result["exit"],0);self.assertEqual(result["json"]["sensitive_ceiling"],grant)
                self.assertEqual(result["json"]["sensitive"],grant);self.assertEqual(result["json"]["argv"],fixtures[0]["argv"])

    def test_old_child_without_support_marker_is_refused_before_execution(self):
        with tempfile.TemporaryDirectory(prefix="CUCP old child ") as temp:
            d=Path(temp);echo=d/"old.ps1";echo.write_text(ECHO_CHILD.replace("cucp.execution-sensitive-ceiling/v1","old-unsupported"),encoding="utf-8-sig")
            inputs=d/"input.json";inputs.write_text(json.dumps([dict(argv=["macro","windows"],live=False,quiet=True,brief=False,confirm_sensitive=False)]),encoding="utf-8-sig")
            runner=d/"check.ps1";runner.write_text(ACTUAL_ADAPTER_RUNNER,encoding="utf-8-sig")
            p=subprocess.run([shutil.which("powershell.exe"),"-NoProfile","-NonInteractive","-File",str(runner),"-Source",os.environ.get("CUCP_EXECUTION_ADAPTER_SOURCE",str(ROOT/"scripts/cucp.ps1")),"-Child",str(echo),"-InputPath",str(inputs)],capture_output=True,timeout=30)
            self.assertNotEqual(p.returncode,0)
            self.assertIn("does not support",p.stderr.decode(errors="replace"))


ECHO_CHILD=r'''
[CmdletBinding(PositionalBinding=$false)]
param([switch]$AllowLiveControl,[switch]$Quiet,[switch]$Brief,[Parameter(ValueFromRemainingArguments=$true)][string[]]$CucpArgs)
$ErrorActionPreference='Stop';[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
function _Read-Switch {
 param([string[]]$Rest,[string]$Name)
 # cucp.execution-sensitive-ceiling/v1
 if($Name -eq '--confirm-sensitive') {
  $ceiling=Get-Variable -Name CUCP_EXECUTION_SENSITIVE_CEILING -Scope Global -ErrorAction SilentlyContinue
  if($ceiling -and ($ceiling.Value -isnot [bool] -or -not [bool]$ceiling.Value -or -not ($ceiling.Options -band [Management.Automation.ScopedItemOptions]::Constant))){return $false}
 }
 return $Rest -contains $Name
}
$ceiling=Get-Variable -Name CUCP_EXECUTION_SENSITIVE_CEILING -Scope Global -ErrorAction SilentlyContinue
$sensitive=_Read-Switch -Rest $CucpArgs -Name '--confirm-sensitive'
[Console]::Out.WriteLine((ConvertTo-Json -InputObject ([ordered]@{live=[bool]$AllowLiveControl;quiet=[bool]$Quiet;brief=[bool]$Brief;argv=@($CucpArgs);sensitive_ceiling=if($ceiling){[bool]$ceiling.Value}else{$null};sensitive=$sensitive}) -Compress))
$global:LASTEXITCODE=0
'''

ACTUAL_ADAPTER_RUNNER=r'''
param([string]$Source,[string]$Child,[string]$InputPath,[switch]$SensitiveCeiling)
$ErrorActionPreference='Stop';[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$t=$null;$e=$null;$a=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$t,[ref]$e)
$f=@($a.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq '_Invoke-LegacyExecutionChild'},$true))
if($f.Count -ne 1){throw 'Expected the qualified execution child adapter'}
. ([scriptblock]::Create($f[0].Extent.Text))
$result=@(foreach($fixture in (Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8|ConvertFrom-Json)){
 $fixture|Add-Member NoteProperty kind 'Child'
 _Invoke-LegacyExecutionChild -ScriptPath $Child -Effect $fixture -LiveCeiling $true -SensitiveCeiling ([bool]$SensitiveCeiling) -SensitiveCeilingContractVerified
})
[Console]::Out.WriteLine((ConvertTo-Json -InputObject $result -Depth 32 -Compress))
'''


def wire(value):
    if isinstance(value,list):return {"kind":"array","items":[wire(x) for x in value]}
    if isinstance(value,dict):return {"kind":"object","properties":[{"name":k,"value":wire(v)} for k,v in value.items()]}
    return {"kind":"scalar","value":value}


def unwire(value):
    if value["kind"]=="array":return [unwire(x) for x in value["items"]]
    if value["kind"]=="object":return {x["name"]:unwire(x["value"]) for x in value["properties"]}
    return value["value"]


@unittest.skipUnless(sys.platform=="win32","Windows PowerShell tagged codec")
class ExecutionWireWindowsTests(unittest.TestCase):
    def test_true_arrays_and_genuine_value_count_objects_keep_identity(self):
        from test_legacy_execution_parity import adapter_source
        values=[None,False,0,"",[],[1],[None],["한글 😀"],[[],[1],[None]],
                dict(empty=[],one=[1],nested=dict(items=[None,True,"x"])),
                dict(value=[],Count=0),dict(value=["macro","click-point"],Count=2),
                [dict(value=[1],Count=1)],dict(Count=2,value=dict(Count=0,value=[]))]
        with tempfile.TemporaryDirectory(prefix="CUCP execution codec ") as temp:
            root=Path(temp);inputs=root/"wire.json";inputs.write_text(json.dumps([wire(v) for v in values]),encoding="utf-8-sig")
            runner=root/"codec.ps1";runner.write_text(r'''
param([string]$Source,[string]$InputPath)
$ErrorActionPreference='Stop';[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Execution adapter did not parse'}
foreach($name in @('_Execution-Require','_Execution-Fields','_Execution-EncodeWire','_Execution-DecodeWire')){
 $f=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true))
 if($f.Count -ne 1){throw "Expected one function $name"};. ([scriptblock]::Create($f[0].Extent.Text))
}
$rows=New-Object Collections.ArrayList
foreach($wire in (Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8|ConvertFrom-Json)){
 $decoded=_Execution-DecodeWire $wire
 $isArray=$decoded -is [array];$count=if($isArray){$decoded.Count}else{$null}
 [void]$rows.Add(@{decoded=$decoded;is_array=$isArray;count=$count;encoded=(_Execution-EncodeWire $decoded)})
}
[Console]::Out.WriteLine((ConvertTo-Json -InputObject @($rows) -Depth 100 -Compress))
''',encoding="utf-8-sig")
            source=str(adapter_source())
            p=subprocess.run([shutil.which("powershell.exe"),"-NoProfile","-NonInteractive","-File",str(runner),"-Source",source,"-InputPath",str(inputs)],capture_output=True,timeout=30)
            self.assertEqual(p.returncode,0,p.stderr.decode(errors="replace"))
            rows=json.loads(p.stdout.decode("utf-8-sig"));self.assertEqual(len(rows),len(values))
            for value,row in zip(values,rows):
                with self.subTest(value=value):
                    self.assertEqual(row,dict(decoded=value,is_array=isinstance(value,list),count=len(value) if isinstance(value,list) else None,encoded=wire(value)))


class ExecutionStreamProcessTests(unittest.TestCase):
    def test_disposable_child_stream_preserves_large_reports_without_transcript_replay(self):
        import base64
        from test_legacy_execution_parity import PROJECT, run_candidate, workflow, reply
        run_candidate([])  # Build once if the SDK is present.
        dotnet=os.environ.get("DOTNET") or shutil.which("dotnet")
        dll=PROJECT/"bin/Release/net8.0/PcuCp.LegacyExecution.ContractTests.dll"
        startup=dict(operation="workflow-run",rest=["--continue-on-error","--retry-failed-step","5"],allow_live=False,confirm_sensitive=False)
        proc=subprocess.Popen([dotnet,str(dll),"--session-fixture"],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding="utf-8")
        def send(frame):proc.stdin.write(json.dumps(frame,separators=(",",":"))+"\n");proc.stdin.flush()
        effects=0;children=0;max_frame=0;completion=None
        try:
            send(startup)
            while True:
                data=bytearray();target=None;identifier=None
                while True:
                    line=proc.stdout.readline();self.assertTrue(line,"Stream terminated without a terminal report")
                    max_frame=max(max_frame,len(line));frame=json.loads(line)
                    if target is None:target=frame["target"];identifier=frame["id"]
                    self.assertEqual((frame["target"],frame["id"]),(target,identifier))
                    if frame["kind"]=="end":break
                    self.assertEqual(frame["kind"],"part");chunk=base64.b64decode(frame["data"]);self.assertLessEqual(len(chunk),49152);data.extend(chunk)
                message=json.loads(data)
                if target=="complete":completion=message;break
                self.assertEqual(target,"effect",message);effects+=1
                self.assertEqual(identifier,effects)
                self.assertNotIn("captured_replies",message)
                if message["kind"]=="Clock":value=0 if message["name"]=="start" else 37
                elif message["kind"]=="WorkflowPlan":value=workflow(256)
                elif message["kind"]=="Child":
                    children+=1;self.assertFalse(message["live"]);value=reply(dict(status="partial",blob="한글"*512),exit=2)
                elif message["kind"]=="TrajectoryAppend":value=None
                else:self.fail("Unexpected stream effect: "+message["kind"])
                encoded=json.dumps(dict(state="ok",value=wire(value)),ensure_ascii=False,separators=(",",":")).encode()
                for i in range(0,len(encoded),49152):send(dict(kind="part",id=identifier,data=base64.b64encode(encoded[i:i+49152]).decode()))
                send(dict(kind="end",id=identifier))
            proc.stdin.close();self.assertEqual(proc.wait(timeout=15),2,proc.stderr.read())
            payload=unwire(completion["payload"])
            self.assertEqual(children,1536);self.assertEqual(payload["executed_count"],256)
            self.assertEqual(payload["retry_count"],1280);self.assertGreater(len(json.dumps(payload)),1048576)
            self.assertLess(max_frame,66000)
        finally:
            if proc.poll() is None:proc.kill();proc.wait(timeout=15)
            for stream in (proc.stdin,proc.stdout,proc.stderr):
                if stream and not stream.closed:stream.close()


@unittest.skipUnless(sys.platform=="win32","Windows constant-ceiling guard fixture")
class ExecutionCurrentCeilingTests(unittest.TestCase):
    def test_current_reader_rejects_false_nonboolean_and_nonconstant_ceilings(self):
        with tempfile.TemporaryDirectory(prefix="CUCP ceiling guard ") as temp:
            runner=Path(temp)/"ceiling.ps1"
            runner.write_text(r'''
param([string]$Source,[string]$Mode)
$ErrorActionPreference='Stop';$t=$null;$e=$null
$a=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$t,[ref]$e)
$f=@($a.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq '_Read-Switch'},$true))
if($f.Count -ne 1 -or -not $f[0].Extent.Text.Contains('cucp.execution-sensitive-ceiling/v1')){throw 'Missing current ceiling contract'}
. ([scriptblock]::Create($f[0].Extent.Text))
switch($Mode){
 'false'{Set-Variable -Name CUCP_EXECUTION_SENSITIVE_CEILING -Scope Global -Option Constant -Value $false}
 'true'{Set-Variable -Name CUCP_EXECUTION_SENSITIVE_CEILING -Scope Global -Option Constant -Value $true}
 'string'{Set-Variable -Name CUCP_EXECUTION_SENSITIVE_CEILING -Scope Global -Option Constant -Value 'true'}
 'mutable'{Set-Variable -Name CUCP_EXECUTION_SENSITIVE_CEILING -Scope Global -Value $true}
}
$r=[ordered]@{sensitive=(_Read-Switch -Rest @('--confirm-sensitive') -Name '--confirm-sensitive');ordinary=(_Read-Switch -Rest @('--json-only') -Name '--json-only')}
[Console]::Out.WriteLine((ConvertTo-Json -InputObject $r -Compress))
''',encoding="utf-8-sig")
            for mode,expected in (("absent",True),("false",False),("true",True),("string",False),("mutable",False)):
                with self.subTest(mode=mode):
                    p=subprocess.run([shutil.which("powershell.exe"),"-NoProfile","-NonInteractive","-File",str(runner),"-Source",str(ROOT/"scripts/cucp.ps1"),"-Mode",mode],capture_output=True,timeout=30)
                    self.assertEqual(p.returncode,0,p.stderr.decode(errors="replace"));r=json.loads(p.stdout.decode("utf-8-sig"))
                    self.assertEqual(r["sensitive"],expected);self.assertTrue(r["ordinary"])
