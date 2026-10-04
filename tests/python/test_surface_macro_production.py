"""Original public version/safety reports, inert syntax, and fixed production delegates."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from pcucp_cli.legacy_cdp_bridge import handle
from pcucp_cli.legacy_host_protocol import LegacyHostError
from pcucp_cli.legacy_surface_macros import run_safety, version_report, build_version

ROOT=Path(__file__).resolve().parents[2]
BASE='a5da94147d259723333a31fb8d25fd82dccbed9a'
HANDLERS=('Invoke-MacroVersion','Invoke-MacroSafetyClassify')

def cases():
    rests=[[],['--macro','click-point','--text','delete password purchase'],
        ['--text','macro TYPE-NATIVE --text "safe"'],
        ['--text','first','--step','macro app-close','--text','second','--command','approve'],
        ['MACRO','click-point','--x','1','--y','2'],
        ['--macro','type-native','--command','delete','--step','send password'],
        ['--TEXT','hello','--STEP','macro app-close'],
        ['--text',''],['--text'],['--macro'],['--json-only','macro','shortcut','--keys','ctrl+s'],
        ['--text','macro click-point; Remove-Item owned'],
        ['--text','macro "app-close"'],['--text','macro type-native --text 한글😀']]
    rows=[dict(name='safety-classify',rest=rest,brief=brief) for rest in rests for brief in (False,True)]
    rows.append(dict(name='safety-classify',rest=['--text','macro app-close','--json-only'],brief=True))
    for status,skill,cli,helper,mode,surface in [
        ('ok','2.4.1','1.0.0','2.0.0','persistent_server','wrapper+cli'),
        ('partial','2.4.1',None,'2.0.0','child_only','wrapper_only'),
        ('partial','',None,None,'child_only','wrapper_only'),
        ('ok','2.4.1','','','child_only','wrapper_only')]:
        report=dict(schema='cucp.version/v1',status=status,surface=surface,helper_mode=mode,
            versions=dict(skill=skill,cli=cli,helper_server=helper),
            sources=dict(skill='owned skill',cli=None,helper_server='owned manifest'),
            recoverable_errors=[],generated_at='2026-10-05T01:00:00.000+09:00')
        for brief in (False,True):rows.append(dict(name='version',rest=[],brief=brief,report=report))
        rows.append(dict(name='version',rest=['--JSON-ONLY'],brief=True,report=report))
    return rows

class SurfaceBoundaryTests(unittest.TestCase):
    def test_unknown_fields_cannot_select_paths_culture_or_authority(self):
        with patch('pcucp_cli.legacy_surface_macros.compatibility',side_effect=AssertionError('No acquisition')):
            for request in [
                dict(name='type-native',rest=['--text','owned'],brief=False),
                dict(name='safety-classify',rest=[],brief=False,allow_live_control=True),
                dict(name='safety-classify',rest=[],brief=False,culture='tr-TR'),
                dict(name='version',rest=[],brief=False,report={},path='owned')]:
                with self.subTest(request=request),self.assertRaises(LegacyHostError):
                    handle('surface-macro',request)

@unittest.skipUnless(os.name=='nt' and os.environ.get('CUCP_NATIVE_HOST') and os.environ.get('CUCP_LEGACY_SYNTAX_EXE'),
                     'Compiled fixed safety and readonly syntax backend')
class SurfaceParityTests(unittest.TestCase):
    def test_version_builder_preserves_missing_layers_lock_modes_and_text_timestamp(self):
        rows=[]
        for cli in (dict(version='1.0.0',package_path=r'C:\owned\package.json',error=None),
                    dict(version=None,package_path=None,error='cli_path_unresolved'),
                    dict(version='',package_path=r'C:\owned\package.json',error='')):
            for helper in (dict(version='2.0.0',error=None),
                           dict(version=None,error='helper_compiled_runtime_unavailable')):
                for mode in ('child_only','persistent_server'):
                    rows.append(dict(skill='2.4.1',cli=cli,helper=helper,helper_mode=mode,
                                     generated_at='2026-10-05T01:00:00.000+09:00'))
        with tempfile.TemporaryDirectory(prefix='CUCP version facts ') as directory:
            owned=Path(directory);source=owned/'original.ps1';inputs=owned/'cases.json';oracle=owned/'oracle.ps1'
            source.write_bytes(subprocess.check_output(['git','show',BASE+':scripts/cucp.ps1'],cwd=ROOT))
            inputs.write_text(json.dumps(rows),encoding='utf-8-sig')
            oracle.write_text(r'''
param([string]$Source,[string]$Cases,[switch]$Current)
$ErrorActionPreference='Stop';[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$t=$null;$e=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$t,[ref]$e)
foreach($name in @('_Make-RecoverableError','Get-CucpVersionReport')){
 $f=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true))
 . ([scriptblock]::Create($f[0].Extent.Text))
}
if($Current){$Script:LegacyCdpSourceRoot=Split-Path -Parent (Split-Path -Parent $Source);. (Join-Path $Script:LegacyCdpSourceRoot 'scripts/cucp-legacy-cdp-adapter.ps1')}
function _Read-CliVersion {return $script:case.cli}
function _Read-HelperServerVersion {return $script:case.helper}
function _Read-LockSafely {if($script:case.helper_mode -eq 'persistent_server'){return @{pid=42}};return $null}
function _Is-StaleLock {param($Lock) return $false}
function _Now-Iso {return '2026-10-05T01:00:00.000+09:00'}
$values=New-Object Collections.ArrayList
foreach($case in (Get-Content -LiteralPath $Cases -Raw -Encoding UTF8|ConvertFrom-Json)){
 $script:case=$case;$Script:SkillVersion=$case.skill
 $report=Get-CucpVersionReport
 if($report.generated_at -isnot [string]){throw 'Version timestamp changed from text.'}
 [void]$values.Add($report)
}
[Console]::WriteLine((ConvertTo-Json -InputObject @($values) -Depth 32 -Compress))
''',encoding='utf-8-sig')
            for host in filter(None,(shutil.which('powershell.exe'),shutil.which('pwsh.exe'))):
                def capture(path,current=False):
                    command=[host,'-NoProfile','-NonInteractive','-File',str(oracle),'-Source',str(path),'-Cases',str(inputs)]
                    if current:command+=['-Current']
                    result=subprocess.run(command,capture_output=True,timeout=60)
                    self.assertEqual(result.returncode,0,result.stderr.decode('utf-8',errors='replace'))
                    return json.loads(result.stdout.decode('utf-8-sig'))
                before=capture(source);after=capture(ROOT/'scripts/cucp.ps1',True)
                self.assertEqual(before,after)
                self.assertEqual(before,[build_version(row) for row in rows])

    def test_original_and_production_reports_and_safety_arguments_in_both_shells(self):
        with tempfile.TemporaryDirectory(prefix='CUCP surface oracle ') as directory:
            owned=Path(directory);source=owned/'original.ps1'
            source.write_bytes(subprocess.check_output(['git','show',BASE+':scripts/cucp.ps1'],cwd=ROOT))
            rows=cases();inputs=owned/'cases.json';inputs.write_text(json.dumps(rows,ensure_ascii=True),encoding='utf-8-sig')
            oracle=owned/'oracle.ps1'
            oracle.write_text(r'''
param([string]$Source,[string]$Cases,[switch]$Current)
$ErrorActionPreference='Stop';[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$t=$null;$e=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$t,[ref]$e)
$names=@('_Read-OptValue','_Read-AllOptValues','_Read-Switch','_Emit-Envelope','_Classify-SafetyFromText','_Invoke-LegacyCompatibility','_Parse-WorkflowStepTokens','Invoke-MacroVersion','Invoke-MacroSafetyClassify')
if($Current){$names+='_Invoke-LegacySurfaceMacro';$Script:LegacyCdpSourceRoot=Split-Path -Parent (Split-Path -Parent $Source);. (Join-Path $Script:LegacyCdpSourceRoot 'scripts/cucp-legacy-cdp-adapter.ps1')}
foreach($name in $names){$f=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true));if($f.Count -ne 1){throw 'Missing source function.'};. ([scriptblock]::Create($f[0].Extent.Text))}
function Get-CucpVersionReport {$script:report.generated_at='2026-10-05T01:00:00.000+09:00';return $script:report}
$output=New-Object Collections.ArrayList
foreach($row in (Get-Content -LiteralPath $Cases -Raw -Encoding UTF8|ConvertFrom-Json)){
 $Brief=[bool]$row.brief;$script:report=$row.report;$exit=$null
 $writer=New-Object IO.StringWriter;$previous=[Console]::Out
 try{[Console]::SetOut($writer);$name=if($row.name -eq 'version'){'Invoke-MacroVersion'}else{'Invoke-MacroSafetyClassify'};$exit=& $name -Rest ([string[]]$row.rest)}
 finally{[Console]::SetOut($previous)}
 [void]$output.Add(@{exit=$exit;output=$writer.ToString()});$writer.Dispose()
}
[Console]::WriteLine((ConvertTo-Json -InputObject @($output) -Depth 32 -Compress))
''',encoding='utf-8-sig')
            hosts=list(filter(None,(shutil.which('powershell.exe'),shutil.which('pwsh.exe'))))
            for host in hosts:
                def capture(path,current=False):
                    command=[host,'-NoProfile','-NonInteractive','-File',str(oracle),'-Source',str(path),'-Cases',str(inputs)]
                    if current:command+=['-Current']
                    process=subprocess.run(command,capture_output=True,timeout=120)
                    self.assertEqual(process.returncode,0,process.stderr.decode('utf-8',errors='replace'))
                    return json.loads(process.stdout.decode('utf-8-sig'))
                expected=capture(source);actual=capture(ROOT/'scripts/cucp.ps1',True)
                self.assertEqual(len(expected),len(actual))
                for row,before,after in zip(rows,expected,actual):
                    with self.subTest(host=Path(host).name,name=row['name'],rest=row['rest'],brief=row['brief']):
                        self.assertEqual(after['exit'],before['exit'])
                        rendered=row['brief'] and not any(word.lower()=='--json-only' for word in row['rest'])
                        result=version_report(row['report'],row['rest'],brief=row['brief']) if row['name']=='version' else run_safety(row['rest'],brief=row['brief'])
                        self.assertEqual(result['exit'],before['exit'])
                        if rendered:
                            self.assertEqual(after['output'].strip(),before['output'].strip())
                            self.assertEqual(result['brief'],before['output'].strip())
                        else:
                            self.assertEqual(json.loads(after['output']),json.loads(before['output']))
                            self.assertEqual(result['payload'],json.loads(before['output']))

if __name__=='__main__':unittest.main()
