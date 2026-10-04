"""Production cold route and public Python entrypoint; no user-app input."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'pcucp-next/python'))
from pcucp_cli.legacy_native_entry import startup
from pcucp_cli.legacy_host_protocol import LegacyHostError

RUNNER = r'''
param([string]$Root,[string]$Python,[string]$Request)
$ErrorActionPreference='Stop';[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
function Load-One($Path,$Name){
 $tokens=$null;$errors=$null
 $ast=[Management.Automation.Language.Parser]::ParseFile($Path,[ref]$tokens,[ref]$errors)
 if($errors.Count){throw 'Source parse failed'}
 $nodes=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $Name},$true))
 if($nodes.Count -ne 1){throw 'Expected one function'}
 Set-Item -Path "Function:script:$Name" -Value ([scriptblock]::Create($nodes[0].Body.Extent.Text.Substring(1,$nodes[0].Body.Extent.Text.Length-2)))
}
Load-One (Join-Path $Root 'scripts/cucp.ps1') 'Invoke-NativeHelper'
Load-One (Join-Path $Root 'scripts/cucp-legacy-cdp-adapter.ps1') '_Invoke-LegacyCdpBridge'
function Write-WrapperLog {param([string]$Message)}
$Script:LegacyCdpSourceRoot=$Root;$Script:NativeHelperPath=Join-Path $Root 'scripts/cucp-native-helper.py'
$env:CUCP_LEGACY_CDP_PYTHON=$Python;$env:CUCP_LEGACY_CDP_HOST=$null
$Script:CacheSeconds=0;$AllowLiveControl=$false
$data=Get-Content -LiteralPath $Request -Raw -Encoding UTF8|ConvertFrom-Json
$reply=Invoke-NativeHelper -ArgList @($data.argv) -ForceChild -TimeoutMs ([int]$data.timeout_ms)
[Console]::Out.WriteLine((ConvertTo-Json -InputObject $reply -Depth 32 -Compress))
'''


class StartupTests(unittest.TestCase):
    def test_text_cannot_mint_authority_and_startup_is_explicit(self):
        rest, authority, timeout = startup(['-Action', 'type', '-Text', '--allow-live-control'])
        self.assertFalse(authority.live)
        self.assertEqual(rest[-1], '--allow-live-control')
        self.assertEqual(timeout, 30)
        self.assertTrue(startup(['--allow-live-control', '-Action', 'type', '-Text', 'fixture'])[1].live)
        for args in (['--timeout-s', 'nan'], ['--timeout-s', '0'], ['--allow-live-control', '--allow-live-control']):
            with self.assertRaises((ValueError, LegacyHostError)): startup(args)


@unittest.skipUnless(os.name == 'nt' and os.environ.get('CUCP_LEGACY_DESKTOP_EXE') and os.environ.get('CUCP_DIAGNOSTIC_PROVIDER_NATIVE'),
    'Explicit real Windows worker gate')
class ActualNativeEntryTests(unittest.TestCase):
    def test_public_python_native_health_and_input_gate(self):
        for argv, code in ((['-Action', 'health'], 0), (['-Action', 'windows', '-Match', 'CUCP-owned-fixture-absent'], 0),
                           (['-Action', 'type', '-Text', '--allow-live-control'], 3)):
            result = subprocess.run([sys.executable, '-X', 'utf8', str(ROOT / 'scripts/cucp-native-helper.py'), *argv],
                capture_output=True, text=True, encoding='utf-8', timeout=15)
            self.assertEqual(result.returncode, code, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload['action'], argv[1])
            if argv[1] == 'windows': self.assertEqual(payload['windows'], [])
            if code == 3: self.assertEqual(payload['status'], 'blocked')

    def test_actual_production_cold_delegate_and_owned_timeout(self):
        with tempfile.TemporaryDirectory(prefix='CUCP cold 한글 ') as folder:
            folder = Path(folder)
            runner, request = folder / 'runner.ps1', folder / 'request.json'
            runner.write_text(RUNNER, encoding='utf-8-sig')
            for argv, timeout, code in ((['-Action', 'health'], 30000, 0),
                    (['-Action', 'windows', '-Match', 'CUCP-owned-fixture-absent'], 30000, 0),
                    (['-Action', 'ocr-image', '-OcrPath', str(folder / 'missing.png')], 30000, 1),
                    (['-Action', 'health'], 1, 124)):
                request.write_text(json.dumps(dict(argv=argv, timeout_ms=timeout)), encoding='utf-8')
                result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(runner),
                    '-Root', str(ROOT), '-Python', sys.executable, '-Request', str(request)],
                    capture_output=True, text=True, encoding='utf-8', timeout=40)
                self.assertEqual(result.returncode, 0, result.stderr)
                reply = json.loads(result.stdout)
                self.assertEqual(reply['ExitCode'], code, reply.get('Err'))
                if timeout > 1:
                    self.assertEqual(reply['Route'], 'child')
                    self.assertEqual(reply['Json']['action'], argv[1])
                    self.assertEqual(json.loads(reply['Raw']), reply['Json'])
