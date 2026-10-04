"""Actual read-only tokenizer parity, including the previously unresolved grammar."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'pcucp-next/python'))
from pcucp_cli.legacy_workflow_plan import step_specs, tokenize, workflow_plan
from pcucp_cli.legacy_host_protocol import LegacyHostError
import test_legacy_workflow_parity as corpus


class WorkflowDeadlineTests(unittest.TestCase):
    def test_parser_and_policy_share_a_single_deadline(self):
        with patch('pcucp_cli.legacy_workflow_plan.tokenize', return_value=[]), patch(
                'pcucp_cli.legacy_workflow_plan.time.monotonic', side_effect=[10, 11]), patch(
                'pcucp_cli.legacy_workflow_plan.compatibility') as policy:
            with self.assertRaises(LegacyHostError):
                workflow_plan([], timeout_s=.5)
            policy.assert_not_called()


@unittest.skipUnless(os.name == 'nt' and os.environ.get('CUCP_LEGACY_SYNTAX_EXE'), 'Explicit Windows syntax backend')
class ActualSyntaxTests(unittest.TestCase):
    def oracle(self, cases, culture='en-US'):
        with tempfile.TemporaryDirectory(prefix='CUCP inert workflow 한글 ') as folder:
            root = Path(folder)
            source, inputs, runner = root / 'original.ps1', root / 'cases.json', root / 'oracle.ps1'
            source.write_text(corpus.original_source(), encoding='utf-8-sig')
            inputs.write_text(json.dumps(cases, ensure_ascii=True), encoding='utf-8-sig')
            runner.write_text(r'''
param([string]$SourcePath,[string]$InputPath,[string]$Culture)
$ErrorActionPreference='Stop'
[Threading.Thread]::CurrentThread.CurrentCulture=[Globalization.CultureInfo]::GetCultureInfo($Culture)
[Threading.Thread]::CurrentThread.CurrentUICulture=[Globalization.CultureInfo]::GetCultureInfo($Culture)
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$t=$null;$e=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($SourcePath,[ref]$t,[ref]$e)
foreach($name in @('_Read-OptValue','_Safety-Truncate','_Classify-SafetyFromText','_Parse-WorkflowStepTokens','_Read-WorkflowStepSpecs','_Build-WorkflowPlan')) {
  $f=@($ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true))
  if($f.Count -ne 1){throw 'Missing exact baseline pure function'}
  . ([scriptblock]::Create($f[0].Extent.Text))
}
$out=New-Object Collections.ArrayList
foreach($case in (Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8 | ConvertFrom-Json)) {
 if($case.kind -eq 'parse'){$v=_Parse-WorkflowStepTokens -Step $case.step}
 elseif($case.kind -eq 'specs'){$v=@(_Read-WorkflowStepSpecs -Rest $case.rest)}
 else{$v=_Build-WorkflowPlan -Rest $case.rest}
 [void]$out.Add($v)
}
[Console]::Out.WriteLine((ConvertTo-Json -InputObject @($out) -Depth 32 -Compress))
''', encoding='utf-8-sig')
            result = subprocess.run([shutil.which('powershell.exe'), '-NoProfile', '-NonInteractive', '-File', str(runner),
                '-SourcePath', str(source), '-InputPath', str(inputs), '-Culture', culture], capture_output=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))
            return json.loads(result.stdout.decode('utf-8-sig'))

    def test_full_syntax_corpus_and_neighboring_edges_equal_current_ps5_oracle(self):
        cases = [case for case in corpus.supported_cases() + corpus.syntax_probe_cases() if case['kind'] == 'parse']
        for filename, key in [('legacy-workflow-literal-inferred.json', 'cases'), ('legacy-workflow-boundary-candidate.json', 'inferred')]:
            rows = json.loads((ROOT / 'tests/fixtures' / filename).read_text(encoding='utf-8'))[key]
            cases.extend(dict(kind='parse', step=row['step']) for row in rows)
        self.assertGreater(len(cases), 400)
        expected = self.oracle(cases)
        self.assertEqual(tokenize([case['step'] for case in cases]), expected)

    def test_step_acquisition_and_actual_policy_preserve_complete_plans(self):
        cases = [case for case in corpus.supported_cases() if case['kind'] == 'specs']
        expected = self.oracle(cases)
        self.assertEqual([step_specs(case['rest']) for case in cases], expected)
        plans = [dict(kind='plan', rest=['--name', '한글', '--step', text]) for text in (
            'macro windows', 'macro type-native --text "hello $name"', 'macro windows --% | more',
            'macro windows; macro process', 'macro type-native --text @\'\nhello\n\'@')]
        expected = self.oracle(plans)
        actual = [workflow_plan(case['rest']) for case in plans]
        self.assertEqual(actual, expected)

    def test_localized_diagnostics_use_the_invocation_culture(self):
        cases = [dict(kind='parse', step=text) for text in ('macro windows (', 'macro windows >', 'macro type --text "unterminated')]
        expected = self.oracle(cases, culture='ko-KR')
        self.assertEqual(tokenize([case['step'] for case in cases], culture='ko-KR'), expected)

    def test_typed_ingress_rejects_duplicate_names_and_non_string_steps(self):
        for raw in (
            '{"schema":"cucp.legacy-syntax/v1","culture":"en-US","steps":[],"steps":["macro windows"]}',
            '{"schema":"cucp.legacy-syntax/v1","culture":"en-US","steps":[],"st\\u0065ps":[]}',
            '{"schema":"cucp.legacy-syntax/v1","culture":"en-US","steps":[null]}',
        ):
            result = subprocess.run([os.environ['CUCP_LEGACY_SYNTAX_EXE']], input=raw.encode('utf-8'), capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, b'')


if __name__ == '__main__':
    unittest.main()
