"""Byte-for-byte history/cache fixtures, including clocks and failed writes."""
import base64
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from test_legacy_precision_parity import BASELINE_TREE, ROOT, runner_command, run_batch

STORAGE_RUNNER=r'''
param([string]$Source,[string]$InputPath)
$ErrorActionPreference='Stop';[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$t=$null;$e=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$t,[ref]$e)
foreach($name in @('_AnchorHistory-Append','_PointPlan-CachePath','_PointPlan-ReadCache','_PointPlan-WriteCache')){
 $n=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true));if($n.Count -ne 1){throw $name};. ([scriptblock]::Create($n[0].Extent.Text))
}
$clock=New-Object DateTime(2026,10,2,1,2,3);function Get-Date {$clock}
$all=New-Object Collections.ArrayList
foreach($fixture in (Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8|ConvertFrom-Json)){
 $root=$fixture.root;[void][IO.Directory]::CreateDirectory($root)
 $Script:AnchorHistoryFile=Join-Path $root 'history.jsonl';$Script:AnchorHistoryMax=[int]$fixture.maximum;$Script:CacheDir=Join-Path $root 'cache'
 if($fixture.create_cache){[void][IO.Directory]::CreateDirectory($Script:CacheDir)}
 if($null -ne $fixture.initial_lines){[IO.File]::WriteAllLines($Script:AnchorHistoryFile,[string[]]$fixture.initial_lines,(New-Object Text.UTF8Encoding($true)))}
 $appended=New-Object Collections.ArrayList;$serialized=New-Object Collections.ArrayList
 foreach($record in @($fixture.records)){
  [void]$serialized.Add(($record|ConvertTo-Json -Compress -Depth 10))
  [void]$appended.Add((_AnchorHistory-Append -Record $record))
 }
 $serializedCache=$null;$key='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';$cacheFile=_PointPlan-CachePath -Key $key
 if($null -ne $fixture.cache_payload){$serializedCache=$fixture.cache_payload|ConvertTo-Json -Depth 14;_PointPlan-WriteCache -Key $key -Payload $fixture.cache_payload}
 if(Test-Path -LiteralPath $cacheFile){[IO.File]::SetLastWriteTime($cacheFile,$clock.AddMilliseconds(-[double]$fixture.age_ms))}
 $hit=_PointPlan-ReadCache -Key $key -MaxAgeSeconds ([int]$fixture.ttl)
 $lines=@();$historyBytes=$null;$cacheBytes=$null
 if(Test-Path -LiteralPath $Script:AnchorHistoryFile){$lines=@(Get-Content -LiteralPath $Script:AnchorHistoryFile -Encoding UTF8);$historyBytes=[Convert]::ToBase64String([IO.File]::ReadAllBytes($Script:AnchorHistoryFile))}
 if(Test-Path -LiteralPath $cacheFile){$cacheBytes=[Convert]::ToBase64String([IO.File]::ReadAllBytes($cacheFile))}
 [void]$all.Add(@{expected=@{appended=@($appended);lines=$lines;hit=$hit;history_bytes=$historyBytes;cache_bytes=$cacheBytes};request=@{operation='storage-fixture';args=@{root=$root;maximum=[int]$fixture.maximum;create_cache=[bool]$fixture.create_cache;initial_lines=@($fixture.initial_lines);serialized_records=@($serialized);serialized_cache=$serializedCache;age_ms=[double]$fixture.age_ms;ttl=[int]$fixture.ttl}}})
}
[Console]::Out.WriteLine((ConvertTo-Json -InputObject @($all) -Depth 100 -Compress))
'''


@unittest.skipUnless(sys.platform=='win32','Requires Windows PowerShell filesystem oracle')
class PrecisionStorageWindowsTests(unittest.TestCase):
    maxDiff=None
    def test_filesystem_fixture_bytes_clock_and_trim(self):
        with tempfile.TemporaryDirectory(prefix='CUCP precision storage oracle ') as tmp:
            root=Path(tmp);source=root/'original.ps1';source.write_bytes(subprocess.check_output(['git','show',f'{BASELINE_TREE}:scripts/cucp.ps1'],cwd=ROOT))
            cases=[];paths=[]
            try:
                for maximum,count,age,ttl,create in ((500,0,0,5,True),(500,1,5000,5,True),(500,1,5001,5,True),(500,2,-1000,1,True),(500,2,0,0,True),(50,51,0,5,True),(1,2,0,5,True),(500,1,0,5,False)):
                    path=Path(tempfile.mkdtemp(prefix='CUCP-precision-storage-'));paths.append(path)
                    cases.append(dict(root=str(path),maximum=maximum,initial_lines=[],records=[dict(n=n,text='한글 <x> 😀',nested={'array':[1,None,True]}) for n in range(count)],cache_payload=dict(status='ok',items=[1,None,'한글']),age_ms=age,ttl=ttl,create_cache=create))
                data=root/'fixtures.json';data.write_text(json.dumps(cases,ensure_ascii=True),encoding='utf-8-sig');runner=root/'storage.ps1';runner.write_text(STORAGE_RUNNER,encoding='utf-8-sig')
                old=subprocess.run(['powershell.exe','-NoProfile','-File',str(runner),'-Source',str(source),'-InputPath',str(data)],capture_output=True,timeout=90)
                self.assertEqual(old.returncode,0,old.stderr.decode(errors='replace'));captured=json.loads(old.stdout.decode('utf-8-sig'))
                for path in paths:shutil.rmtree(path)
                actual=run_batch(runner_command(root),[c['request'] for c in captured])
                for case,before,after in zip(cases,captured,actual):
                    with self.subTest(case=case):self.assertEqual(after,before['expected'])
            finally:
                for path in paths:shutil.rmtree(path,ignore_errors=True)
