"""Original/current session reports with real cache IO and inert lifecycle ports."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
BASELINE='f86c75def39cb701a3f63b42e8532e5591ee571b'


def fixtures():
    reply=dict(status='ok',reused=True,pid=73,pipe_name='owned-pipe',alive=True,uptime_s=12.5,
               request_count=9,stopped_pid=73,forced=False,shim_path='owned shim 한글.cmd',removed=True,installed=True)
    cases=[]
    def add(rest,**changes):
        row=dict(rest=rest,brief=False,live=True,startup_live=True,culture='en-US',reply=copy.deepcopy(reply),error=None)
        row.update(changes);cases.append(row)
    for name in ('clear-cache','info','start-helper','stop-helper','helper-status','install-autostart','uninstall-autostart','autostart-status'):
        for brief in (False,True):add([name],brief=brief)
    for rest in ([],['unknown'],['INFO','--json-only'],['helper-status','--json-only'],['stop-helper','--force'],['STOP-HELPER','--FORCE']):add(rest,brief=True)
    for name in ('start-helper','install-autostart'):
        for value in ('bad','', ' ', '\t','\u00a0','\x1c','0','-1','1.5','2.5','0xFFFFFFFF','0x100000000','2147483648','1,234'):
            add([name,'--idle-timeout-ms',value])
    for name in ('install-autostart','uninstall-autostart'):
        add([name],live=False,startup_live=False)
        # A lowered invocation ceiling must not inherit the outer live grant.
        add([name],live=False,startup_live=True)
    for name in ('start-helper','stop-helper','install-autostart','uninstall-autostart','helper-status','autostart-status'):
        add([name],brief=True,reply=dict(status='error',reason='owned failure'))
        add([name],brief=False,reply=dict(status='OK',schema='fixture override'))
    for value in (False,None,'false',[],[False],[False,False]):
        changed=copy.deepcopy(reply);changed.update(alive=value,reused=value,installed=value)
        add(['helper-status'],brief=True,reply=changed)
        add(['start-helper'],brief=True,reply=changed)
    for name in ('info','helper-status','start-helper'):add([name],error='owned helper failure')
    add(['helper-status'],brief=True,culture='tr-TR')
    add(['helper-status'],brief=True,culture='ko-KR')
    return cases


RUNNER=r'''
param([string]$Source,[string]$InputPath,[string]$Worker,[string]$Root,[switch]$Current)
$ErrorActionPreference='Stop';[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Session source must parse'}
foreach($name in @('Invoke-MacroSession','_Read-OptValue','_Read-Switch','_Emit-Envelope')){
 $fn=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name},$true))
 if($fn.Count -ne 1){throw 'Exact session function required'}
 . ([scriptblock]::Create($fn[0].Extent.Text))
}
function Write-Notice {param($Message,$Level) [void]$script:notices.Add(@{message=$Message;level=$Level})}
function Fixture-Helper($op,$arguments){
 [void]$script:calls.Add(@{operation=$op;arguments=$arguments})
 if($script:fixture.error){throw [string]$script:fixture.error}
 return $script:fixture.reply
}
function Get-HelperServerStatus {Fixture-Helper 'status' @{}}
function Start-HelperServer {param([int]$IdleTimeoutMs) Fixture-Helper 'start' @{idle_timeout_ms=$IdleTimeoutMs}}
function Stop-HelperServer {param([switch]$Force) Fixture-Helper 'stop' @{force=[bool]$Force}}
function Install-HelperAutostart {param([int]$IdleTimeoutMs) Fixture-Helper 'autostart-install' @{idle_timeout_ms=$IdleTimeoutMs}}
function Uninstall-HelperAutostart {Fixture-Helper 'autostart-uninstall' @{}}
function Get-HelperAutostartStatus {Fixture-Helper 'autostart-status' @{}}
function _Invoke-LegacyCdpBridge {
 param($Operation,$Request,[switch]$LiveAuthority,$TimeoutMs)
 if($Operation -cne 'session'){throw 'Only session operation allowed'}
 $context=@{cache_directory=$Script:CacheDir;audit_directory=$Script:AuditDir;wrapper_log=$Script:WrapperLog;cli_path=$Script:CliPath;
 cache_seconds=[int]$CacheSeconds;lock_file=(Join-Path $Script:AuditDir 'helper.pid');desktop=$false;staged=$true;modern=($PSVersionTable.PSVersion.Major -ge 7);startup_directory=$null;metadata_directory=$null}
 $frame=@{context=$context;rest=$Request.rest;brief=$Request.brief;live=[bool]$LiveAuthority;reply=$script:fixture.reply;error=$script:fixture.error}
 $psi=New-Object Diagnostics.ProcessStartInfo;$psi.FileName=(Get-Command python.exe -CommandType Application -TotalCount 1).Source
 $psi.Arguments='"'+$Worker+'" --fixture';$psi.UseShellExecute=$false;$psi.CreateNoWindow=$true
 $psi.RedirectStandardInput=$true;$psi.RedirectStandardOutput=$true;$psi.RedirectStandardError=$true
 $utf8=New-Object Text.UTF8Encoding($false);$psi.StandardOutputEncoding=$utf8;$psi.StandardErrorEncoding=$utf8
 $p=New-Object Diagnostics.Process;$p.StartInfo=$psi
 try{
  [void]$p.Start();$out=$p.StandardOutput.ReadToEndAsync();$err=$p.StandardError.ReadToEndAsync()
  $bytes=$utf8.GetBytes(($frame|ConvertTo-Json -Depth 24 -Compress));$p.StandardInput.BaseStream.Write($bytes,0,$bytes.Length);$p.StandardInput.Close()
  if(-not $p.WaitForExit(10000)){throw 'Fixture Python timed out'}
  $result=$out.GetAwaiter().GetResult()|ConvertFrom-Json
  foreach($call in @($result.calls)){[void]$script:calls.Add($call)}
  if($result.error){throw [string]$result.error}
  return $result.result
 }finally{if(-not $p.HasExited){$p.Kill()};$p.Dispose()}
}
$Script:CacheDir=Join-Path $Root 'cache';$Script:AuditDir=Join-Path $Root 'audit';$Script:WrapperLog=Join-Path $Root 'wrapper.log'
$Script:CliPath=$null;$Script:InvokeTimeoutMs=30000;$CacheSeconds=2
[void](New-Item -ItemType Directory -Path $Script:CacheDir -Force);[void](New-Item -ItemType Directory -Path $Script:AuditDir -Force)
$rows=New-Object Collections.ArrayList
foreach($fixture in (Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8|ConvertFrom-Json)){
 $script:fixture=$fixture;$script:calls=New-Object Collections.ArrayList;$script:notices=New-Object Collections.ArrayList
 foreach($name in @('appshot-a.json','APPSHOT-UPPER.JSON','point-plan-a.json','keep.txt')){[IO.File]::WriteAllText((Join-Path $Script:CacheDir $name),'{}')}
 [IO.File]::WriteAllText($Script:WrapperLog,'owned-log')
 [Threading.Thread]::CurrentThread.CurrentCulture=[Globalization.CultureInfo]::GetCultureInfo([string]$fixture.culture)
 $Brief=[bool]$fixture.brief;$AllowLiveControl=[bool]$fixture.live;$Script:StagedAutostartLive=[bool]$fixture.startup_live
 $writer=New-Object IO.StringWriter;$previous=[Console]::Out;[Console]::SetOut($writer);$errorText=$null;$exitCode=$null
 try{$exitCode=Invoke-MacroSession -Rest $fixture.rest}catch{$errorText=$_.Exception.Message}finally{[Console]::SetOut($previous)}
 [void]$rows.Add(@{exit=$exitCode;error=$errorText;console=$writer.ToString();calls=@($script:calls);notices=@($script:notices);
 files=@(Get-ChildItem -LiteralPath $Script:CacheDir|Sort-Object Name|ForEach-Object{$_.Name})});$writer.Dispose()
}
[Console]::Out.WriteLine((ConvertTo-Json -InputObject @($rows) -Depth 32 -Compress))
'''


@unittest.skipUnless(os.name=='nt','Requires actual Windows shells')
class SessionProductionTests(unittest.TestCase):
    def test_all_eight_commands_flags_errors_numeric_arguments_console_and_file_effects(self):
        env=dict(os.environ,PYTHONPATH=str(ROOT/'pcucp-next/python'))
        with tempfile.TemporaryDirectory(prefix='CUCP session parity 한글 ') as folder:
            root=Path(folder);source=root/'old.ps1';source.write_bytes(subprocess.check_output(['git','show',BASELINE+':scripts/cucp.ps1'],cwd=ROOT))
            runner=root/'runner.ps1';runner.write_text(RUNNER,encoding='utf-8-sig')
            inputs=root/'fixtures.json';inputs.write_text(json.dumps(fixtures(),ensure_ascii=True),encoding='utf-8-sig')
            for shell in ('powershell.exe','pwsh.exe'):
                self.assertIsNotNone(shutil.which(shell))
                command=[shell,'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(runner),
                         '-InputPath',str(inputs),'-Worker',str(Path(__file__).resolve()),'-Root',str(root/'owned')]
                results=[]
                for path,current in ((source,False),(ROOT/'scripts/cucp.ps1',True)):
                    p=subprocess.run([*command,'-Source',str(path),*(['-Current'] if current else [])],env=env,capture_output=True,timeout=180)
                    self.assertEqual(p.returncode,0,p.stderr.decode('utf-8',errors='replace'))
                    results.append(json.loads(p.stdout.decode('utf-8-sig')))
                self.assertEqual(len(results[0]),len(fixtures()));self.assertEqual(len(results[1]),len(fixtures()))
                for index,(before,after) in enumerate(zip(*results)):
                    with self.subTest(shell=shell,index=index,rest=fixtures()[index]['rest']):
                        self.assertEqual(after,before)


def fixture_worker():
    from pcucp_cli.legacy_host_protocol import parse_json
    from pcucp_cli.legacy_session_runtime import SessionRuntime
    frame=parse_json(sys.stdin.buffer.read());calls=[]
    def helper(operation,args):
        calls.append(dict(operation=operation,arguments=args))
        if frame['error']:raise OSError(frame['error'])
        return frame['reply']
    try:
        result=SessionRuntime(frame['context'],helper=helper,allow_live_control=frame['live']).run(frame['rest'],brief=frame['brief'])
        response=dict(result=result,error=None,calls=calls)
    except Exception as error:response=dict(result=None,error=str(error),calls=calls)
    print(json.dumps(response,ensure_ascii=True))


if __name__=='__main__':
    if sys.argv[1:]==['--fixture']:fixture_worker()
    else:unittest.main()
