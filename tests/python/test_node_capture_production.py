"""Actual old/new Node capture delegates with owned executable fixtures."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
BASE='500246d42332fa8ec4952b99b107bae01e67a46c'
HANDLERS=('Invoke-Cucp',)

def project(value):
    if isinstance(value,dict):
        result={}
        for key,item in value.items():
            if key in ('ElapsedMs','elapsed_ms','CommandId','command_id'):continue
            if key=='FilePath':result[key]=item is not None
            elif key=='Err' and isinstance(item,str):
                result[key]=re.sub(r'id=[a-f0-9]+, elapsed=\d+ms','id=ID, elapsed=Nms',item)
            else:result[key]=project(item)
        return result
    if isinstance(value,list):return [project(item) for item in value]
    return value

@unittest.skipUnless(os.name=='nt' and shutil.which('powershell.exe') and shutil.which('node'),'Actual Windows Node capture')
class NodeCaptureParityTests(unittest.TestCase):
    def test_original_and_production_capture_shapes_utf8_timeout_and_json_dialects(self):
        with tempfile.TemporaryDirectory(prefix='CUCP Node capture 한글 ') as folder:
            owned=Path(folder);source=owned/'original.ps1';cli=owned/'cli.mjs';inputs=owned/'cases.json';driver=owned/'driver.ps1'
            source.write_bytes(subprocess.check_output(['git','show',BASE+':scripts/cucp.ps1'],cwd=ROOT))
            cli.write_text("""
const op=process.argv[2];
if(op==='slow'){process.stdout.write('partial owned\\n');setTimeout(()=>process.exit(0),10000);}
else if(op==='bad'){process.stdout.write('not JSON');process.stderr.write('2026-10-05T01:00:00.000+09:00');process.exitCode=2;}
else if(op==='empty'){}
else if(op==='array'){process.stdout.write('[{"status":"ok"},{"value":2}]');}
else if(op==='singleton'){process.stdout.write('[{"status":"ok"}]');}
else if(op==='null'){process.stdout.write('null');}
else if(op==='scalar'){process.stdout.write('"owned"');}
else if(op==='bom'){process.stdout.write(Buffer.from([239,187,191]));process.stdout.write('{"status":"ok"}');}
else if(op==='error'){process.stdout.write('{"status":"error","summary":"owned error"}');process.exitCode=3;}
else {process.stdout.write(JSON.stringify({status:'ok',args:process.argv.slice(2),generated_at:'2026-10-05T01:00:00.000+09:00'}));}
""",encoding='utf-8')
            rows=[dict(argv=[op,'한글😀','with spaces'],timeout=30000,missing=False)
                  for op in ('owned','bad','empty','array','singleton','null','scalar','bom','error')]
            rows+= [dict(argv=['slow'],timeout=1500,missing=False),dict(argv=['owned'],timeout=0,missing=False),
                    dict(argv=['owned'],timeout=-1,missing=False),dict(argv=[],timeout=30000,missing=True)]
            inputs.write_text(json.dumps(rows),encoding='utf-8-sig')
            driver.write_text(r'''
param([string]$Source,[string]$Cases,[string]$Cli,[string]$Cache)
$ErrorActionPreference='Stop';[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$t=$null;$e=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$t,[ref]$e)
$f=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Invoke-Cucp'},$true))
. ([scriptblock]::Create($f[0].Extent.Text))
$PSScriptRoot=Split-Path -Parent $Source
$Script:LegacyCdpSourceRoot=Split-Path -Parent (Split-Path -Parent $Source)
function Write-WrapperLog {param([string]$Message)}
$Script:CacheDir=$Cache;$Script:WrapperLog=Join-Path $Cache 'wrapper.log'
$output=New-Object Collections.ArrayList
foreach($case in (Get-Content -LiteralPath $Cases -Raw -Encoding UTF8|ConvertFrom-Json)){
 $Script:CliPath=if($case.missing){''}else{$Cli};$Script:InvokeTimeoutMs=[int]$case.timeout
 $result=Invoke-Cucp -ArgList ([string[]]$case.argv) -CaptureJson
 [void]$output.Add($result)
}
[Console]::WriteLine((ConvertTo-Json -InputObject @($output) -Depth 32 -Compress))
''',encoding='utf-8-sig')
            for host in filter(None,(shutil.which('powershell.exe'),shutil.which('pwsh.exe'))):
                def capture(path):
                    result=subprocess.run([host,'-NoProfile','-NonInteractive','-File',str(driver),'-Source',str(path),
                        '-Cases',str(inputs),'-Cli',str(cli),'-Cache',str(owned)],capture_output=True,timeout=90)
                    self.assertEqual(result.returncode,0,result.stderr.decode('utf-8',errors='replace'))
                    return json.loads(result.stdout.decode('utf-8-sig'))
                before=capture(source);after=capture(ROOT/'scripts/cucp.ps1')
                for row,old,new in zip(rows,before,after):
                    with self.subTest(host=Path(host).name,row=row):
                        original,candidate=project(old),project(new)
                        # PS5 Start-Process loses the exit handle here; the
                        # migration intentionally returns Node's real status.
                        loss={'bad':(0,2),'empty':(None,0),'error':(0,3)}
                        operation=row['argv'][0] if row['argv'] else None
                        if Path(host).name.lower()=='powershell.exe' and operation in loss:
                            old_code,new_code=loss[operation]
                            self.assertEqual(original['ExitCode'],old_code)
                            self.assertEqual(candidate['ExitCode'],new_code)
                            original['ExitCode']=new_code
                        self.assertEqual(candidate,original)

if __name__=='__main__':unittest.main()
