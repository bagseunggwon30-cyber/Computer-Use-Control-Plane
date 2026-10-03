"""Release guards for source and portable entrypoints; no desktop input."""
import io
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'pcucp-next/python'))
from pcucp_cli import cli, protocol
from pcucp_cli.registry import COMMANDS


class PowerShellFreeTests(unittest.TestCase):
    def test_repository_contains_no_powershell_sources_or_linguist_hiding(self):
        tracked = subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=ROOT).decode('utf-8').split('\0')
        retained = [name for name in tracked if Path(name).suffix.lower() in {'.ps1', '.psm1', '.psd1'} and (ROOT / name).exists()]
        self.assertEqual(retained, [], 'Retire actual sources; changing language statistics is insufficient')
        attributes = ROOT / '.gitattributes'
        if attributes.exists():
            self.assertNotIn('linguist-', attributes.read_text(encoding='utf-8'))

    def test_ci_has_no_powershell_steps_or_legacy_regression_dependency(self):
        workflow = (ROOT / '.github/workflows/core.yml').read_text(encoding='utf-8')
        self.assertIn('shell: bash', workflow)
        for retired in ('shell: pwsh', 'shell: powershell', 'powershell.exe', 'Invoke-Pester', '.ps1'):
            self.assertNotIn(retired, workflow)

    def test_source_and_portable_do_not_expose_legacy_execution(self):
        for portable in (False, True):
            with patch.object(sys, 'frozen', portable, create=True), patch('sys.stderr', new_callable=io.StringIO):
                self.assertNotIn('legacy', cli.build_parser().format_help())
                with self.assertRaises(SystemExit) as error:
                    cli.main(['legacy', 'version'])
                self.assertEqual(error.exception.code, 2)
        self.assertNotIn('powershell', protocol.LANGUAGE_ROLES)
        self.assertTrue(all('powershell' not in item.route for item in COMMANDS.values()))

    def test_source_entry_preserves_unicode_argv_and_exit_from_any_cwd(self):
        entry = ROOT / 'pcucp-next/python/run_source.py'
        result = subprocess.run([sys.executable, str(entry), 'plan', '--command', '없는 명령😀', '--json'],
                                cwd=ROOT.parent, capture_output=True, encoding='utf-8', timeout=10)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('없는 명령😀', result.stdout)


if __name__ == '__main__':
    unittest.main()
