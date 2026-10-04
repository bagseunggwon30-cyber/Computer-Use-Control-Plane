"""Source and frozen hosts share the same bounded CDP bridge entry."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'pcucp-next/python'))
from pcucp_cli import cli


class LegacyCdpLaunchTests(unittest.TestCase):
    def test_fixed_cli_dispatch_preserves_arguments_and_exit(self):
        argv = ['--operation', 'native', '--endpoint', 'http://127.0.0.1:9']
        with patch('pcucp_cli.legacy_cdp_bridge.main', return_value=37) as bridge:
            self.assertEqual(cli.main(['legacy-cdp-bridge', *argv]), 37)
        bridge.assert_called_once_with(argv)

    def test_source_process_rejects_live_action_before_network(self):
        env = dict(os.environ, PYTHONPATH=str(ROOT / 'pcucp-next/python'))
        p = subprocess.run([sys.executable, '-m', 'pcucp_cli', 'legacy-cdp-bridge', '--operation', 'native',
                            '--endpoint', 'http://127.0.0.1:9'], env=env, input=json.dumps({
                                'action': 'cdp-click', 'args': {'selector': '#never-click'}}) + '\n',
                           capture_output=True, text=True, encoding='utf-8', timeout=10)
        self.assertEqual(p.returncode, 0, p.stderr)
        reply = json.loads(p.stdout)
        self.assertEqual(reply['data']['exit_code'], 3)
        self.assertEqual(reply['data']['payload']['reason'], 'live_control_required')
