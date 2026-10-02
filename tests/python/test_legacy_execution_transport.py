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


@unittest.skipUnless(sys.platform=="win32","Windows PowerShell argument binding characterization")
class ExecutionOriginalDefectTests(unittest.TestCase):
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
