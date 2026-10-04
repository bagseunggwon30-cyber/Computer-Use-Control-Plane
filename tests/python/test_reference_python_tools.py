"""Owned evidence files and source snippets; no desktop actions or real logs."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'references' / (name + '.py'))
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value); return value
summary = module('live_verify_summary')
audit = module('audit_ps5_pitfalls')


class ReferenceToolTests(unittest.TestCase):
    def test_evidence_summary_preserves_review_and_environment_missing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, value in {'pass':{'status':'ok'}, 'environment':{'status':'partial','reason':'no_matching_window'},
                    'partial':{'status':'partial','reason':'low_confidence'}, 'review':{'warnings':['review me']}}.items():
                (root / (name + '.json')).write_text(json.dumps(value), encoding='utf-8-sig')
            (root / 'invalid.json').write_text('owned invalid JSON', encoding='utf-8')
            (root / 'summary.json').write_text('must not recursively summarize a summary')
            value = summary.summarize(root)
            self.assertEqual(value['status'], 'review')
            self.assertEqual(value['count'], 5)
            self.assertEqual(value['classes'], {'environment_missing':1,'fail':1,'pass':1,'partial_review':1,'needs_review':1})
            self.assertTrue(all(item['length'] > 0 and item['last_write'] for item in value['items']))
            output = root / 'out.json'
            import contextlib, io
            with contextlib.redirect_stdout(io.StringIO()): summary.main(['--root',str(root),'--out',str(output)])
            self.assertFalse(output.read_bytes().startswith(b'\xef\xbb\xbf'))

    def test_reason_deduplicates_and_keeps_nested_failure_details(self):
        value = dict(reason='same',error='same',warnings=['warning','same'],recoverable_errors=[{'code':'code'},{'message':'message'}],
            cassette=[{'reason':'case','status':'partial'}],focus={'reason':'missing'},paste={'reason':'blocked','detail':'한글'},recommendation='inspect')
        self.assertEqual(summary.reason(value),'same | warning | code | message | case | cassette_status=partial | focus=missing | paste=blocked | paste_detail=한글 | inspect')

    def test_audit_reads_remaining_scripts_without_evaluating_them(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / 'scripts').mkdir()
            source = '$x = if ($true) { 2 } else { 0 }\nparam([string[]]$args)\n# $args comment\n$value = Get-Content file\n'
            (root / 'scripts/cucp.ps1').write_text(source,encoding='utf-8-sig')
            found = audit.findings(root)
            self.assertEqual([(item['line'],item['category']) for item in found],[(1,'inline_if_numeric'),(2,'args_automatic_var'),(4,'getcontent_single_line')])
            self.assertEqual((root / 'scripts/cucp.ps1').read_text(encoding='utf-8-sig'),source)
            self.assertEqual(summary.summarize(root / 'missing')['status'],'empty')
