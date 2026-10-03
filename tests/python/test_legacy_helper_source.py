"""Published source pin and counted oracle driver guards; never run a desktop."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from helper_process_evidence import run_evidence, require_success

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / 'tests/fixtures/legacy-helper'
MANIFEST = json.loads((FIXTURES / 'source-manifest.json').read_text())


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
        text = (FIXTURES / 'source-manifest.json').read_text()
        self.assertNotIn('function ', text)
        self.assertNotIn('scriptblock', text.lower())
        self.assertTrue((FIXTURES / 'oracle.ps1').is_file())
        candidate = ROOT / 'pcucp-next/dotnet/PcuCp.LegacyHelper'
        for path in candidate.glob('*.cs'):
            source = path.read_text()
            for denied in ('System.Management.Automation', 'EncodedCommand', 'powershell.exe', 'ParentLifetimeGuard', 'SendInput(', 'Process.Start('):
                self.assertNotIn(denied, source, path.name)

    def test_oracle_facades_cannot_silently_resolve_real_desktop_types(self):
        stub = (FIXTURES / 'OracleAcquisition.cs').read_text()
        driver = (FIXTURES / 'oracle.ps1').read_text()
        for denied in ('DllImport', 'LibraryImport', 'Process.Start', 'File.ReadAll', 'File.WriteAll', 'System.Net', 'GetForegroundWindow();'):
            self.assertNotIn(denied, stub)
        self.assertIn("$type.Assembly -ne [HelperFixture].Assembly", driver)
        for guarded in ('System.Drawing.Graphics', 'System.Drawing.Bitmap', 'System.Windows.Automation.AutomationElement',
                        'System.Windows.Forms.SystemInformation', 'Windows.Media.Ocr.OcrEngine', 'Windows.Storage.StorageFile'):
            self.assertIn("'" + guarded + "'", driver)
        transport = (ROOT / 'tests/python/test_legacy_helper_transport.py').read_text()
        self.assertNotIn('--allow-readonly-desktop', transport)
