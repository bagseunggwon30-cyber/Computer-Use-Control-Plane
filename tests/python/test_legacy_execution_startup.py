"""Actual host startup and direct-gate probes never invoke a desktop action."""
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
HOST = os.environ.get('CUCP_EXECUTION_STARTUP_TEST_HOST') or os.environ.get('CUCP_EXECUTION_TEST_HOST', '')


def startup_wire(value):
    data = json.dumps(value, ensure_ascii=False).encode('utf-8')
    return ''.join(json.dumps({'kind': 'part', 'id': 0, 'data': base64.b64encode(data[i:i + 49152]).decode('ascii')}) + '\n'
                   for i in range(0, len(data), 49152)) + '{"kind":"end","id":0}\n'


@unittest.skipUnless(sys.platform == 'win32' and HOST, 'Actual execution startup adapter is not enabled')
class ExecutionStartupTests(unittest.TestCase):
    def test_utf8_bom_reaches_first_read_request_without_executing_it(self):
        executable = ['dotnet', HOST] if HOST.endswith('.dll') else [HOST]
        root = dict(schema='cucp.execution-start/v1', operation='recovery-plan', rest=['--match', '한글😀'],
                    brief=False, cache_seconds=2, vision_available=False, culture='en-US')
        wire = b'\xef\xbb\xbf' + startup_wire(root).encode('utf-8')
        process = subprocess.run(executable + ['legacy-execution-session'], input=wire,
                                 capture_output=True, timeout=20)
        # stdin closes before any effect reply; the native process can only
        # describe a request. No PowerShell effect dispatcher is present.
        first = json.loads(process.stdout.decode('utf-8-sig').splitlines()[0])
        self.assertEqual(first.get('kind'), 'part', process.stdout)
        self.assertEqual(first.get('target'), 'effect', process.stdout)
        self.assertEqual(first.get('id'), 1, process.stdout)

    def test_forged_startup_authority_is_rejected_before_any_effect(self):
        executable = ['dotnet', HOST] if HOST.endswith('.dll') else [HOST]
        root = dict(schema='cucp.execution-start/v1', operation='workflow-run', rest=[], brief=False,
                    cache_seconds=2, vision_available=False, culture='en-US')
        for field in ('authority', 'allow_live', 'confirm_sensitive'):
            with self.subTest(field=field):
                p = subprocess.run(executable + ['legacy-execution-session'], input=startup_wire(dict(root, **{field: True})),
                                   text=True, encoding='utf-8', capture_output=True, timeout=20)
                self.assertEqual(p.returncode, 2, p.stderr)
                reply = json.loads(p.stdout.lstrip('\ufeff'))
                self.assertEqual(reply['status'], 'error')
                self.assertNotIn('"target":"effect"', p.stdout)

    def test_top_level_gate_does_not_treat_option_values_as_confirmation(self):
        cases = [(['--label', 'password', '--text', '--confirm-sensitive'], 'none', 3),
                 (['--label', '--confirm-sensitive'], 'none', 3),
                 (['--text', '--confirm-sensitive', '--confirm-sensitive'], 'none', 0),
                 (['--confirm-sensitive'], 'false', 3),
                 (['--confirm-sensitive'], 'mutable', 3),
                 (['--confirm-sensitive'], 'true', 0),
                 (['--label', 'password', '--confirm-sensitive'], 'none', 0)]
        with tempfile.TemporaryDirectory(prefix='CUCP startup consent ') as temp:
            d = Path(temp)
            runner = d / 'gate.ps1'
            runner.write_text(GATE_RUNNER, encoding='utf-8-sig')
            env = dict(os.environ, CUCP_NATIVE_HOST=HOST)
            for rest, ceiling, expected in cases:
                with self.subTest(rest=rest, ceiling=ceiling):
                    data = d / 'args.json'
                    data.write_text(json.dumps(rest, ensure_ascii=False), encoding='utf-8-sig')
                    p = subprocess.run([shutil.which('powershell.exe'), '-NoProfile', '-NonInteractive', '-File',
                                        str(runner), '-Source', str(ROOT / 'scripts/cucp.ps1'), '-InputPath', str(data),
                                        '-Ceiling', ceiling], env=env, capture_output=True, timeout=30)
                    self.assertEqual(p.returncode, 0, p.stderr.decode(errors='replace'))
                    reply = json.loads(p.stdout.decode('utf-8-sig'))
                    self.assertEqual(reply['exit'], expected)
                    self.assertEqual(reply['calls'], 1 if expected == 0 else 0)
                    if expected == 3:
                        self.assertEqual(json.loads(reply['console'])['reason'], 'sensitive_action_requires_confirmation')


GATE_RUNNER = r'''
param([string]$Source,[string]$InputPath,[string]$Ceiling)
$ErrorActionPreference='Stop';[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$t=$null;$e=$null;$a=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$t,[ref]$e)
foreach($name in @('_Read-StandaloneConfirmation','_Invoke-LegacyCompatibility','Invoke-Macro')) {
 $f=@($a.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true))
 if($f.Count -ne 1){throw "Missing exact gate function $name"};. ([scriptblock]::Create($f[0].Extent.Text))
}
if($Ceiling -eq 'false'){Set-Variable -Name CUCP_EXECUTION_SENSITIVE_CEILING -Scope Global -Option Constant -Value $false}
if($Ceiling -eq 'true'){Set-Variable -Name CUCP_EXECUTION_SENSITIVE_CEILING -Scope Global -Option Constant -Value $true}
if($Ceiling -eq 'mutable'){Set-Variable -Name CUCP_EXECUTION_SENSITIVE_CEILING -Scope Global -Value $true}
$AllowLiveControl=$true;$Brief=$false;$script:calls=0
function _Classify-SafetyFromText {param($Text,$MacroName) return @{requires_explicit_confirmation=$true;risk_level='high'}}
function Invoke-MacroSmartClick {param($Rest) $script:calls++;return 0}
$rest=Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8|ConvertFrom-Json
$old=[Console]::Out;$writer=New-Object IO.StringWriter
try {[Console]::SetOut($writer);$rc=Invoke-Macro -ArgList (@('macro','smart-click')+@($rest))} finally {[Console]::SetOut($old)}
[Console]::Out.WriteLine((ConvertTo-Json -InputObject @{exit=$rc;calls=$script:calls;console=$writer.ToString()} -Compress))
'''
