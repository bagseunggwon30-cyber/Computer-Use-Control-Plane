"""Pinned real gate predicates, precedence and notices; all dispatch stays inert."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from pcucp_cli.legacy_authorization import authorize,predicates
from pcucp_cli.legacy_cdp_bridge import handle
from pcucp_cli.legacy_host_protocol import LegacyHostError

ROOT=Path(__file__).resolve().parents[2]
BASE='afd880b86df996a7f970ef106b2a19b98efe7fc9'
HANDLERS=('Test-LiveControlRequest','Test-CoordinateMissingObservation','Assert-Authorized')

CASES=[None,[],['observe','windows'],['ACT'],['act','click','--x','1','--y','2'],
    ['act','click','--x','1','--after','owned'],['act','drag','--from-x','1','--force'],
    ['act','type','--text','owned'],['act','scroll','--x','1'],
    ['app','switch'],['app','inspect'],['plan','run'],['plan','show'],
    ['scenario','run'],['scenario','run','--execute'],
    ['desktop','benchmark','runbook'],['desktop','benchmark','runbook','--allow-live-control'],
    ['desktop','benchmark','runbook','--allow-live-control','--verify-only'],
    ['desktop','benchmark','runbook','--allow-live-control','--preflight-only'],
    ['desktop','benchmark','runbook','--allow-live-control','--dry-run'],
    ['desktop','benchmark','run','--live'],['desktop','benchmark','run','--live','--preflight-only'],
    ['desktop','benchmark','collect','--live'],['desktop','benchmark','collect','--live','--verify-only'],
    ['desktop','benchmark','collect','--live','--dry-run'],
    ['l5','run'],['l5','resume'],['l5','resume','--allow-control'],['l5','live-eval','--allow-control'],
    ['L5','RESUME','--ALLOW-CONTROL'],['macro','click-point'],['act','click','--x',None],
    ['act','click','--x','1','--after'],['scenario','run','--text','--execute']]

class AuthorizationBoundaryTests(unittest.TestCase):
    def test_command_data_and_json_fields_cannot_grant_startup_authority(self):
        words=['act','click','--x','1','--after','owned','--allow-live-control','--confirm-sensitive']
        result=handle('surface-macro',dict(name='authorization',argv=words))
        self.assertTrue(result['live']);self.assertIsNotNone(result['error'])
        self.assertIsNone(handle('surface-macro',dict(name='authorization',argv=words),allow_live_control=True)['error'])
        for extra in ('allow_live_control','authority','timeout_s'):
            with self.assertRaises(LegacyHostError):
                handle('surface-macro',dict(name='authorization',argv=words,**{extra:True}))
        with self.assertRaises(LegacyHostError):predicates(['act',True])

@unittest.skipUnless(os.name=='nt' and shutil.which('powershell.exe'),'Actual pinned Windows gate functions')
class AuthorizationParityTests(unittest.TestCase):
    def test_predicates_and_complete_gate_match_original_in_both_shells(self):
        rows=[dict(argv=words,live=live) for words in CASES for live in (False,True)]
        with tempfile.TemporaryDirectory(prefix='CUCP authorization oracle ') as directory:
            owned=Path(directory);source=owned/'original.ps1';inputs=owned/'cases.json';oracle=owned/'oracle.ps1'
            source.write_bytes(subprocess.check_output(['git','show',BASE+':scripts/cucp.ps1'],cwd=ROOT))
            inputs.write_text(json.dumps(rows),encoding='utf-8-sig')
            oracle.write_text(r'''
param([string]$Source,[string]$Cases,[switch]$Current)
$ErrorActionPreference='Stop';[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$t=$null;$e=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$t,[ref]$e)
foreach($name in @('Test-LiveControlRequest','Test-CoordinateMissingObservation','Assert-Authorized')){
 $f=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true))
 . ([scriptblock]::Create($f[0].Extent.Text))
}
if($Current){$Script:LegacyCdpSourceRoot=Split-Path -Parent (Split-Path -Parent $Source);. (Join-Path $Script:LegacyCdpSourceRoot 'scripts/cucp-legacy-cdp-adapter.ps1')}
function Write-Notice {param([string]$Level,[string]$Message) [void]$script:notices.Add(@{level=$Level;message=$Message})}
$output=New-Object Collections.ArrayList
foreach($case in (Get-Content -LiteralPath $Cases -Raw -Encoding UTF8|ConvertFrom-Json)){
 $AllowLiveControl=[bool]$case.live;$args=if($null -eq $case.argv){$null}else{[string[]]$case.argv}
 $live=Test-LiveControlRequest -ArgList $args;$missing=Test-CoordinateMissingObservation -ArgList $args
 $script:notices=New-Object Collections.ArrayList;$errorText=$null
 try{Assert-Authorized -ArgList $args}catch{$errorText=$_.Exception.Message}
 [void]$output.Add(@{live=[bool]$live;missing_observation=[bool]$missing;error=$errorText;notices=@($script:notices)})
}
[Console]::WriteLine((ConvertTo-Json -InputObject @($output) -Depth 16 -Compress))
''',encoding='utf-8-sig')
            for host in filter(None,(shutil.which('powershell.exe'),shutil.which('pwsh.exe'))):
                def capture(path,current=False):
                    command=[host,'-NoProfile','-NonInteractive','-File',str(oracle),'-Source',str(path),'-Cases',str(inputs)]
                    if current:command+=['-Current']
                    process=subprocess.run(command,capture_output=True,timeout=180)
                    self.assertEqual(process.returncode,0,process.stderr.decode('utf-8',errors='replace'))
                    return json.loads(process.stdout.decode('utf-8-sig'))
                before=capture(source);after=capture(ROOT/'scripts/cucp.ps1',True)
                self.assertEqual(len(before),len(after))
                for row,original,current in zip(rows,before,after):
                    with self.subTest(host=Path(host).name,argv=row['argv'],authority=row['live']):
                        self.assertEqual(current,original)
                        self.assertEqual(authorize(row['argv'],allow_live_control=row['live']),original)
                        self.assertEqual(predicates(row['argv']),{key:original[key] for key in ('live','missing_observation')})

if __name__=='__main__':unittest.main()
