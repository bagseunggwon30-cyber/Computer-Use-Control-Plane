"""Published source pin and counted oracle driver guards; never run a desktop."""
import hashlib
import json
from pathlib import Path
import re
import tempfile
import unittest
from helper_process_evidence import run_evidence, require_success

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / 'tests/fixtures/legacy-helper'
MANIFEST = json.loads((FIXTURES / 'source-manifest.json').read_text(encoding='utf-8'))
FACADE_PREFIX = 'CucpFixture.'
LOADER_NAMES = {'_Ensure-Win32Loaded', '_Server-Ensure-OCR', '_Server-Ensure-UIA'}


def expected_type_seam(raw):
    """Independent census of literal sites in this exact pinned source only.

    This is deliberately not a general PowerShell rewriter. Windows executes
    the driver's AST-based rewriter; this census checks its emitted evidence.
    """
    entry = MANIFEST['files'][0]
    normalized = raw.decode('utf-8-sig').replace('\r\n', '\n')
    if hashlib.sha256(normalized.encode()).hexdigest() != entry['normalized_sha256']:
        raise AssertionError('Published server source hash mismatch')
    encoded = normalized.encode('utf-16-le')
    sites, functions = [], []
    for record in entry['functions']:
        if record['parent_function'] or record['name'] in LOADER_NAMES:
            continue
        body = encoded[2 * record['start_utf16']:2 * record['end_utf16']].decode('utf-16-le')
        edits = []
        for match in re.finditer(r'\[([\w.+]+)\]|New-Object ([\w.+]+)', body):
            group = 1 if match[1] else 2
            name = match[group]
            if not name.startswith(('HelperWin32', 'System.Windows.', 'System.Drawing.', 'Windows.', 'WindowsRuntime')):
                continue
            start, end = match.span(group)
            sites.append(dict(function=record['name'], kind='type' if group == 1 else 'new-object',
                              start_utf16=record['start_utf16'] + len(body[:start].encode('utf-16-le')) // 2,
                              end_utf16=record['start_utf16'] + len(body[:end].encode('utf-16-le')) // 2,
                              original=name, replacement=FACADE_PREFIX + name))
            edits.append((start, end, name))
        for start, end, name in reversed(edits):
            body = body[:start] + FACADE_PREFIX + name + body[end:]
        functions.append(dict(name=record['name'], original_sha256=record['sha256'],
                              substituted_sha256=hashlib.sha256(body.encode()).hexdigest()))
    return dict(schema='cucp.oracle-type-seam/v1', source_sha256=entry['normalized_sha256'],
                facade_sha256=hashlib.sha256((FIXTURES / 'OracleAcquisition.cs').read_text(encoding='utf-8').encode()).hexdigest(),
                type_substitutions=sites, guarded_types=sorted({s['replacement'] for s in sites}), functions=functions)


def expected_args_seam(raw):
    """Independent pinned-text census; all unedited UTF-16 bytes are preserved.

    This never executes or manufactures PowerShell. The counted driver alone
    performs AST rewriting. Its emitted hashes must match this byte census.
    """
    type_seam = expected_type_seam(raw)  # Includes the unchanged source hash pin.
    entry = MANIFEST['files'][0]
    encoded = raw.decode('utf-8-sig').replace('\r\n', '\n').encode('utf-16-le')
    sites, functions = [], []
    for record, typed in zip((f for f in entry['functions']
                             if not f['parent_function'] and f['name'] not in LOADER_NAMES),
                            type_seam['functions']):
        body = encoded[2 * record['start_utf16']:2 * record['end_utf16']]
        text = body.decode('utf-16-le')
        edits = [s for s in type_seam['type_substitutions'] if s['function'] == record['name']]
        for match in re.finditer(r'\$Args\b|-Args\b', text):
            original = match[0]
            kind = ('command-parameter' if original == '-Args' else
                    'parameter' if text[:match.start()].endswith('[hashtable]') else 'variable')
            start = record['start_utf16'] + len(text[:match.start()].encode('utf-16-le')) // 2
            site = dict(function=record['name'], kind=kind, start_utf16=start, end_utf16=start + 5,
                        original=original, replacement=original[0] + 'RequestData')
            sites.append(site)
            edits.append(site)
        # Assemble unchanged intervals once, byte for byte. This independently
        # checks the driver's reverse-offset edits, including cross-seam overlap.
        cursor, pieces = 0, []
        for edit in sorted(edits, key=lambda s: s['start_utf16']):
            start = 2 * (edit['start_utf16'] - record['start_utf16'])
            end = 2 * (edit['end_utf16'] - record['start_utf16'])
            if start < cursor or end > len(body) or start >= end:
                raise AssertionError('Overlapping or out-of-range independent census extent')
            if body[start:end] != edit['original'].encode('utf-16-le'):
                raise AssertionError('Changed independent census extent')
            pieces.extend((body[cursor:start], edit['replacement'].encode('utf-16-le')))
            cursor = end
        pieces.append(body[cursor:])
        corrected = b''.join(pieces).decode('utf-16-le').encode('utf-8')
        functions.append(dict(name=record['name'], original_sha256=record['sha256'],
                              type_only_sha256=typed['substituted_sha256'],
                              corrected_sha256=hashlib.sha256(corrected).hexdigest()))
    return dict(schema='cucp.oracle-corrected-intent-seam/v1', qualification='corrected-intent-only',
                source_sha256=entry['normalized_sha256'], args_substitutions=sites, functions=functions)


def published_source(path, directory):
    evidence = run_evidence(['git', 'show', f"{MANIFEST['published_tree']}:{path}"],
                            cwd=ROOT, directory=directory, label='published-git-source', limit=2 * 1024 * 1024)
    require_success(evidence)
    raw = evidence['stdout']
    pin = next(f for f in MANIFEST['files'] if f['path'] == path)
    if len(raw) != pin['raw_bytes'] or hashlib.sha256(raw).hexdigest() != pin['raw_sha256']:
        raise AssertionError('Published source raw byte/hash mismatch')
    return raw


class HelperSourceTests(unittest.TestCase):
    def test_published_tree_source_and_utf16_ast_spans(self):
        with tempfile.TemporaryDirectory() as directory:
            for pin in MANIFEST['files']:
                raw = published_source(pin['path'], directory)
                normalized = raw.decode('utf-8-sig').replace('\r\n', '\n')
                self.assertEqual(hashlib.sha256(normalized.encode()).hexdigest(), pin['normalized_sha256'])
                encoded = normalized.encode('utf-16-le')
                for function in pin['functions']:
                    with self.subTest(function=function['name']):
                        source = encoded[2 * function['start_utf16']:2 * function['end_utf16']].decode('utf-16-le').encode()
                        self.assertTrue(source.startswith(('function ' + function['name']).encode()))
                        self.assertEqual(len(source), function['utf8_bytes'])
                        self.assertEqual(hashlib.sha256(source).hexdigest(), function['sha256'])

    def test_scope_counts_no_duplicate_nested_function(self):
        server, wrapper = MANIFEST['files']
        self.assertEqual(server['raw_bytes'], 27427)
        self.assertEqual(sum(f['utf8_bytes'] for f in wrapper['functions'] if f['name'] != 'Invoke-NativeHelper'), 8078)
        self.assertEqual(server['raw_bytes'] + sum(f['utf8_bytes'] for f in wrapper['functions'] if f['name'] != 'Invoke-NativeHelper'), 35505)
        self.assertEqual(MANIFEST['published_commit'], '3e892ab02395bdc916a5814e39d4154efd1f6249')

    def test_originals_remain_and_oracle_bodies_are_not_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            for pin in MANIFEST['files']:
                current = (ROOT / pin['path']).read_bytes().decode('utf-8-sig').replace('\r\n', '\n')
                if pin['path'].endswith('server.ps1'):
                    self.assertEqual(hashlib.sha256(current.encode()).hexdigest(), pin['normalized_sha256'])
                else:
                    # Other migration families may legitimately edit unrelated
                    # wrapper functions. Protect this family's exact retained
                    # bodies without freezing the whole monolithic wrapper.
                    original = published_source(pin['path'], directory).decode('utf-8-sig').replace('\r\n', '\n').encode('utf-16-le')
                    for function in pin['functions']:
                        body = original[2 * function['start_utf16']:2 * function['end_utf16']].decode('utf-16-le')
                        self.assertEqual(current.count(body), 1, function['name'])
        text = (FIXTURES / 'source-manifest.json').read_text(encoding='utf-8')
        self.assertNotIn('function ', text)
        self.assertNotIn('scriptblock', text.lower())
        self.assertTrue((FIXTURES / 'oracle.ps1').is_file())
        candidate = ROOT / 'pcucp-next/dotnet/PcuCp.LegacyHelper'
        for path in candidate.glob('*.cs'):
            source = path.read_text(encoding='utf-8')
            for denied in ('System.Management.Automation', 'EncodedCommand', 'powershell.exe', 'ParentLifetimeGuard', 'SendInput(', 'Process.Start('):
                self.assertNotIn(denied, source, path.name)

    def test_oracle_facades_cannot_silently_resolve_real_desktop_types(self):
        stub = (FIXTURES / 'OracleAcquisition.cs').read_text(encoding='utf-8')
        driver = (FIXTURES / 'oracle.ps1').read_text(encoding='utf-8')
        for denied in ('DllImport', 'LibraryImport', 'Process.Start', 'File.ReadAll', 'File.WriteAll', 'System.Net', 'GetForegroundWindow();'):
            self.assertNotIn(denied, stub)
        self.assertIn("$type.Assembly -ne $fixtureAssembly", driver)
        self.assertIn('[object]::ReferenceEquals($type,$expected)', driver)
        self.assertIn("$fixturePrefix='CucpFixture.'", driver)
        self.assertIn('namespace CucpFixture\n{', stub)
        self.assertNotIn('#pragma warning disable 0436', stub)
        self.assertLess(driver.index('Inert oracle facade hash mismatch'), driver.index('Microsoft.PowerShell.Utility\\Add-Type'))
        self.assertLess(driver.index('Unsafe oracle type resolution:'), driver.index('[scriptblock]::Create($function.body)'))
        self.assertEqual(driver.count('$TestWrongBinding'), 2)
        self.assertIn('if($TestWrongBinding){$type=[string]}', driver)
        self.assertLess(driver.index('if($TestWrongBinding)'), driver.index('Unsafe oracle type resolution:'))
        self.assertIn("if(-not $Stubs){throw 'An inert acquisition facade is required'}", driver)
        for guarded in ('System.Drawing.Graphics', 'System.Drawing.Bitmap', 'System.Windows.Automation.AutomationElement',
                        'System.Windows.Forms.SystemInformation', 'Windows.Media.Ocr.OcrEngine', 'Windows.Storage.StorageFile'):
            self.assertIn("'" + guarded + "'", driver)
        transport = (ROOT / 'tests/python/test_legacy_helper_transport.py').read_text(encoding='utf-8')
        self.assertNotIn('--allow-readonly-desktop', transport)

    def test_type_seam_census_and_byte_preservation_are_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            raw = published_source('scripts/cucp-helper-server.ps1', directory)
        seam = expected_type_seam(raw)
        driver = (FIXTURES / 'oracle.ps1').read_text(encoding='utf-8')
        self.assertEqual(len(seam['type_substitutions']), 52)
        self.assertEqual(len(seam['guarded_types']), 23)
        self.assertEqual(len(seam['functions']), 8)
        self.assertEqual({x['kind'] for x in seam['type_substitutions']}, {'type', 'new-object'})
        self.assertIn(seam['facade_sha256'], driver)
        counts = {name: sum(s['original'] == name for s in seam['type_substitutions'])
                  for name in {s['original'] for s in seam['type_substitutions']}}
        table = driver.split('$typeCounts=[ordered]@{', 1)[1].split('\n}', 1)[0]
        self.assertEqual(dict((name, int(count)) for name, count in re.findall(r"'([^']+)'=(\d+)", table)), counts)
        for function in seam['functions']:
            if function['name'] in {'_Log', '_Action-Health', '_Dispatch'}:
                self.assertEqual(function['original_sha256'], function['substituted_sha256'])
            else:
                self.assertNotEqual(function['original_sha256'], function['substituted_sha256'])
        for mutated in (raw.replace(b'[Windows.Storage.StorageFile]', b'[System.String]', 1),
                        raw.replace(b'CopyFromScreen($sx, $sy, 0, 0,', b'CopyFromScreen($sx, $sy, 1, 1,', 1),
                        raw + b'\n# altered source'):
            with self.assertRaisesRegex(AssertionError, 'Published server source hash mismatch'):
                expected_type_seam(mutated)

    def test_type_edits_sort_numeric_dictionary_keys_and_fail_closed(self):
        driver = (FIXTURES / 'oracle.ps1').read_text(encoding='utf-8')
        self.assertIn("Sort-Object -Property {[int]$_['start']} -Descending", driver)
        self.assertNotIn('Sort-Object -Property start -Descending', driver)
        self.assertIn("if($overlap -or $actual -cne $edit.name)", driver)
        self.assertIn("[Math]::Min(128,$actual.Length)", driver)
        diagnostic = driver.index("schema='cucp.oracle-type-extent-refusal/v1'")
        refusal = driver.index("throw 'Overlapping or changed oracle type extent'")
        self.assertLess(diagnostic, refusal)
        self.assertLess(refusal, driver.index('Microsoft.PowerShell.Utility\\Add-Type'))
        self.assertIn("[ValidateSet('none','duplicate','changed')][string]$TestTypeExtentFault='none'", driver)
        self.assertIn("if($TestTypeExtentFault -eq 'duplicate')", driver)
        self.assertIn("else{$first.name='FixtureChangedType'}", driver)

    def test_corrected_intent_is_opt_in_and_its_census_preserves_other_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            raw = published_source('scripts/cucp-helper-server.ps1', directory)
        seam = expected_args_seam(raw)
        sites = seam['args_substitutions']
        self.assertEqual(len(sites), 34)
        self.assertEqual({kind: sum(s['kind'] == kind for s in sites)
                          for kind in ('parameter', 'variable', 'command-parameter')},
                         {'parameter': 7, 'variable': 21, 'command-parameter': 6})
        self.assertEqual({name: sum(s['function'] == name for s in sites) for name in {s['function'] for s in sites}},
                         {'_Action-Windows': 4, '_Action-Health': 1, '_Action-Focused': 1,
                          '_Action-ModalDetect': 1, '_Action-OcrScreenFast': 9, '_Action-UiaFindFast': 5, '_Dispatch': 13})
        self.assertEqual(len({(s['start_utf16'], s['end_utf16']) for s in sites}), 34)
        driver = (FIXTURES / 'oracle.ps1').read_text(encoding='utf-8')
        plan = driver.split('$argsPlan=[ordered]@{', 1)[1].split('\n}', 1)[0]
        tables = re.findall(r"'([^']+)'=@\{([^\n]+)\}", plan)
        self.assertEqual(len(tables), 7)
        self.assertEqual({name for name, _ in tables}, {s['function'] for s in sites})
        for name, table in tables:
            expected = {kind: [s['start_utf16'] for s in sites if s['function'] == name and s['kind'] == kind]
                        for kind in {s['kind'] for s in sites if s['function'] == name}}
            actual = {kind.strip("'"): [int(n) for n in values.split(',')]
                      for kind, values in re.findall(r"([\w'-]+)=@\(([\d,]+)\)", table)}
            self.assertEqual(actual, expected, name)
        for function in seam['functions']:
            if function['name'] == '_Log':
                self.assertEqual(function['corrected_sha256'], function['original_sha256'])
            else:
                self.assertNotEqual(function['corrected_sha256'], function['type_only_sha256'])
        self.assertIn('[switch]$CorrectedIntent', driver)
        self.assertNotIn('$CorrectedIntent=$true', driver)
        self.assertIn("else{$value=_Dispatch -Action ([string]$r.action) -Args (Convert-Case $r.args)}", driver)
        self.assertIn("qualification='corrected-intent-only'", driver)
        self.assertIn("'corrected-intent'}else{'exact-original'", driver)
        self.assertIn("$typeOnlyHash=Hash-Text $body", driver)
        self.assertIn("substituted_sha256=$typeOnlyHash", driver)
        self.assertIn('$owner -ne $node', driver)
        self.assertIn("$extent.EndOffset -ne ($extent.StartOffset+5)", driver)
        self.assertIn("$argsSites.Count -ne 34", driver)
        self.assertIn("$part -is [Management.Automation.Language.VariableExpressionAst]", driver)
        self.assertIn("$part -is [Management.Automation.Language.CommandParameterAst]", driver)
        for mutated in (raw.replace(b'$Args', b'$Else', 1), raw.replace(b'-Args', b'-Else', 1), raw + b'\n'):
            with self.assertRaisesRegex(AssertionError, 'Published server source hash mismatch'):
                expected_args_seam(mutated)

    def test_corrected_intent_rename_faults_refuse_before_import(self):
        driver = (FIXTURES / 'oracle.ps1').read_text(encoding='utf-8')
        self.assertIn("[ValidateSet('none','duplicate','changed','wrongname')][string]$TestArgsExtentFault='none'", driver)
        self.assertIn("if($TestArgsExtentFault -eq 'duplicate')", driver)
        self.assertIn("elseif($TestArgsExtentFault -eq 'changed'){$first.original='$Else'}", driver)
        self.assertIn("else{$first.replacement='$Unplanned'}", driver)
        for guard in ("$reason='overlap_or_order'", "$reason='text_mismatch'", "$reason='wrong_replacement_name'",
                      "Missing planned Args AST extent", "Duplicate Args AST extent", "Unplanned Args AST extent"):
            self.assertIn(guard, driver)
        diagnostic = driver.index("schema='cucp.oracle-args-extent-refusal/v1'")
        refusal = driver.index("throw 'Unsafe corrected-intent Args extent'")
        self.assertLess(diagnostic, refusal)
        self.assertLess(refusal, driver.index('Microsoft.PowerShell.Utility\\Add-Type'))
        self.assertLess(refusal, driver.index('[scriptblock]::Create($function.body)'))

    def test_binding_probe_preserves_original_functions_and_trace_array_shape(self):
        probe = (FIXTURES / 'binding-probe.ps1').read_text(encoding='utf-8')
        self.assertIn("foreach($name in @('_Action-Health','_Dispatch'))", probe)
        self.assertIn("Published server source hash mismatch", probe)
        self.assertIn("Published AST extent changed:", probe)
        self.assertIn('[scriptblock]::Create($node.Extent.Text)', probe)
        self.assertNotIn('[scriptblock]::Create($node.Extent.Text.Replace', probe)
        self.assertIn('param([hashtable]$Args)', probe)
        self.assertIn('param([hashtable]$RequestData)', probe)
        self.assertIn('fully_qualified_error_id=$_.FullyQualifiedErrorId', probe)
        self.assertIn('script_stack_trace=(Limit-Text $_.ScriptStackTrace)', probe)
        self.assertIn('[Math]::Min(2048,$Text.Length)', probe)
        for forbidden in ('Add-Type', 'HelperWin32', 'AutomationElement', 'OcrEngine', 'Start-Process'):
            self.assertNotIn(forbidden, probe)
        driver = (FIXTURES / 'oracle.ps1').read_text(encoding='utf-8')
        self.assertIn('[object[]]$trace=@([CucpFixture.HelperFixture]::Effects.ToArray())', driver)
        self.assertNotIn('$trace=if(', driver)
