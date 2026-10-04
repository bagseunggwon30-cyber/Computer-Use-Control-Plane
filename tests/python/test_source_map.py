"""Independent AST/hash parity and inert parsing; historical PS is test-only."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('source_map',ROOT/'pcucp-next/packaging/source_map.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class SourceMapCollectionTests(unittest.TestCase):
    def test_source_collection_preserves_bare_cr_and_normalizes_bom_crlf(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'scripts').mkdir()
            (root/'scripts/a.ps1').write_bytes(b'\xef\xbb\xbf# heading\r\nfunction A {}\r# bare CR\n')
            value=module.collect(root)
            self.assertEqual(value,dict(schema='cucp.source-map-input/v1',files=[dict(path='scripts/a.ps1',text='# heading\nfunction A {}\r# bare CR\n')]))

    def test_no_source_or_missing_published_parser_is_a_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError): module.collect(Path(folder))
            with self.assertRaises(ValueError): module.source_map(Path(folder),Path(folder)/'missing.exe')


@unittest.skipUnless(os.name=='nt' and os.environ.get('CUCP_SOURCE_MAP_TEST_EXE'),'Explicit built Windows AST parser gate')
class SourceMapWindowsTests(unittest.TestCase):
    def setUp(self): self.exe=Path(os.environ['CUCP_SOURCE_MAP_TEST_EXE']).resolve()

    def oracle(self, root, output):
        raw=subprocess.check_output(['git','show','f5dbbc103699a539b2e1630bd811b0c407d34a33:tests/fixtures/migration-source-map.ps1'],cwd=ROOT,timeout=15)
        self.assertEqual(hashlib.sha256(raw).hexdigest(),'0d34f9042b2ea20c54d1032940c8712d7fde68e47a7eee43bd886ff6cbf2fe7e')
        driver=output.parent/'historical-source-map.ps1';driver.write_bytes(raw)
        result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-File',str(driver),'-Root',str(root),'-OutputPath',str(output)],capture_output=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        return json.loads(output.read_bytes())

    def test_all_current_sources_match_original_ast_extents_and_hashes(self):
        with tempfile.TemporaryDirectory() as folder:
            expected=self.oracle(ROOT,Path(folder)/'original.json')
        self.assertEqual(module.source_map(ROOT,self.exe),expected)

    def test_nested_unicode_functions_and_inert_side_effects_match_original(self):
        with tempfile.TemporaryDirectory(prefix='CUCP-source-map-') as folder:
            root=Path(folder);scripts=root/'scripts';scripts.mkdir();sentinel=root/'must-not-exist'
            (root/'tests/fixtures').mkdir(parents=True)
            text="function 한글 { function Nested { '😀' }; [IO.File]::WriteAllText('"+str(sentinel)+"','unsafe') }\n"
            (scripts/'a.ps1').write_text(text,encoding='utf-8')
            expected=self.oracle(root,root/'original.json')
            actual=module.source_map(root,self.exe)
            self.assertEqual(actual,expected)
            self.assertEqual([v['parent_function'] for v in actual['files'][0]['functions']],[None,'한글'])
            self.assertFalse(sentinel.exists())

    def test_invalid_ast_duplicate_names_and_extra_authority_fail(self):
        requests=[dict(schema='cucp.source-map-input/v1',files=[dict(path='scripts/a.ps1',text='function A {')]),
                  dict(schema='cucp.source-map-input/v1',files=[dict(path='scripts/a.ps1',text='')]*2),
                  dict(schema='cucp.source-map-input/v1',files=[dict(path='../a.ps1',text='')]),
                  dict(schema='cucp.source-map-input/v1',files=[dict(path='scripts/a.ps1',text='')],allow_live_control=True)]
        for value in requests:
            result=subprocess.run([str(self.exe)],input=json.dumps(value).encode(),capture_output=True,timeout=10)
            self.assertNotEqual(result.returncode,0);self.assertEqual(result.stdout,b'')
        raw=b'{"schema":"cucp.source-map-input/v1","files":[],"files":[]}'
        result=subprocess.run([str(self.exe)],input=raw,capture_output=True,timeout=10)
        self.assertNotEqual(result.returncode,0);self.assertIn(b'Duplicate syntax JSON property',result.stderr)
