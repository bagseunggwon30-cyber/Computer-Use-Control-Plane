"""Typed native boundary and owned image/kernel integration; no user-app input."""
import json
import os
from pathlib import Path
import sys
import tempfile
import subprocess
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'pcucp-next/python'))
from pcucp_cli.legacy_native_desktop import DesktopSession, prepare_desktop
from pcucp_cli.legacy_host_protocol import Authority, LegacyHostError
from pcucp_cli.legacy_native_kernel import ocr_match


class BindingTests(unittest.TestCase):
    def test_typed_classic_options_keep_literals_coordinates_and_conversion(self):
        result = prepare_desktop(['-Action', 'click', '-X', '-1', '-Y', '0x00000000', '-TargetMatch', '-AllowLiveControl'])
        self.assertEqual(result['X'], -1)
        self.assertEqual(result['Y'], 0)
        self.assertEqual(result['TargetMatch'], '-AllowLiveControl')
        self.assertEqual(prepare_desktop(['-A', 'type', '-Text', '한글 " ; $(x)', '-ClearFirst'])['Text'], '한글 " ; $(x)')

    def test_unknown_duplicate_ambiguous_and_authority_looking_options_fail(self):
        for rest in (['-X', '1', '-x', '2'], ['-M', 'ambiguous'], ['-CdpStartup', 'true'], ['-AllowLiveControl'], ['-Text']):
            with self.subTest(rest=rest), self.assertRaises(LegacyHostError):
                prepare_desktop(['-Action', 'type', *rest])


@unittest.skipUnless(os.name == 'nt' and os.environ.get('CUCP_LEGACY_DESKTOP_EXE') and os.environ.get('CUCP_DIAGNOSTIC_PROVIDER_NATIVE'),
                     'Explicit actual Windows desktop and native matcher gate')
class DesktopTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='CUCP desktop 한글 ')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        env = patch.dict(os.environ, CUCP_NATIVE_HOST=os.environ['CUCP_DIAGNOSTIC_PROVIDER_NATIVE'])
        env.start(); self.addCleanup(env.stop)

    def invoke(self, *args):
        return DesktopSession(os.environ['CUCP_LEGACY_DESKTOP_EXE']).run(list(args))

    def test_actual_windows_health_focused_and_missing_image_results(self):
        for args in (('-Action', 'windows', '-Match', 'CUCP-no-such-owned-test-window'), ('-Action', 'health'), ('-Action', 'focused'),
                     ('-Action', 'uia-find', '-Label', 'fixture', '-Match', 'CUCP-no-such-owned-test-window'),
                     ('-Action', 'ocr-image', '-OcrPath', str(self.root / 'missing.png'))):
            with self.subTest(args=args):
                reply = self.invoke(*args)
                self.assertIn(reply['ExitCode'], (0, 1, 2))
                self.assertEqual(reply['Json']['action'], args[1])
                self.assertIsInstance(reply['Json']['elapsed_ms'], int)
                if args[1] == 'windows':
                    self.assertEqual(reply['Json']['windows'], [])
                    self.assertEqual(reply['Json']['count'], 0)

    def test_input_cannot_acquire_an_executable_without_startup_authority(self):
        session = DesktopSession(os.environ['CUCP_LEGACY_DESKTOP_EXE'])
        with self.assertRaisesRegex(LegacyHostError, 'startup authority'):
            session.run(['-Action', 'type', '-Text', 'must not enter any app'])
        self.assertIsNone(session._process)

    def test_matching_uses_the_original_native_kernel_and_typed_stdin(self):
        body = dict(text='Save Message', line_count=1, word_count=2, lines=[dict(text='Save Message', x=10, y=20, w=120, h=30,
            cx=70, cy=35, word_count=2, words=[dict(text='Save', x=10, y=20, w=40, h=30, cx=30, cy=35),
                                             dict(text='Message', x=55, y=20, w=70, h=30, cx=90, cy=35)])])
        rows = ocr_match(body, 'Save Message', 'contains')
        self.assertGreater(len(rows), 0)
        self.assertEqual(rows[0]['score'], 100)

    def test_actual_ocr_image_and_matching_dialogue_use_owned_png_only(self):
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            self.skipTest('Pillow is required only to generate the owned OCR fixture')
        path = self.root / 'fixture.png'
        image = Image.new('RGB', (600, 140), 'white')
        font = ImageFont.truetype(str(Path(os.environ['WINDIR']) / 'Fonts/arial.ttf'), 42)
        ImageDraw.Draw(image).text((20, 30), 'CUCP Save Message 123', fill='black', font=font)
        image.save(path)
        health = self.invoke('-Action', 'health')['Json']
        if not health['ocr']:
            self.skipTest('Actual OCR unavailable: ' + str(health['ocr_error']))
        image_reply = self.invoke('-Action', 'ocr-image', '-OcrPath', str(path))
        self.assertEqual(image_reply['ExitCode'], 0)
        self.assertGreater(image_reply['Json']['word_count'], 0)
        match = self.invoke('-Action', 'ocr-find-text', '-OcrPath', str(path), '-OcrText', 'Save')
        self.assertEqual(match['ExitCode'], 0)
        self.assertGreater(match['Json']['candidate_count'], 0)
        self.assertGreaterEqual(match['Json']['top']['score'], 60)

    @unittest.skipUnless(os.environ.get('CUCP_LEGACY_DESKTOP_FIXTURE'), 'Explicit owned UIA/input acceptance surface')
    def test_patterns_unicode_input_clipboard_restore_and_guard_only_touch_owned_form(self):
        process = subprocess.Popen([os.environ['CUCP_LEGACY_DESKTOP_FIXTURE'], '--state-directory', str(self.root)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
        def current():
            return json.loads((self.root / 'state.json').read_text(encoding='utf-8'))
        def wait_for(predicate):
            end = time.monotonic() + 5
            while time.monotonic() < end:
                if process.poll() is not None:
                    self.fail('Owned fixture exited before acceptance: ' + process.stderr.read().decode('utf-8', errors='replace'))
                try:
                    value = current()
                    if predicate(value):
                        return value
                except (OSError, ValueError):
                    pass
                time.sleep(.04)
            self.fail('Owned fixture did not reach its expected state.')
        def act(*args):
            return DesktopSession(os.environ['CUCP_LEGACY_DESKTOP_EXE'], authority=Authority(live=True)).run(list(args))
        try:
            initial = wait_for(lambda value: value['hwnd'] > 0)
            title = initial['title']
            result = act('-Action', 'uia-set-value', '-Match', title, '-Label', 'Fixture Text', '-Value', 'CUCP 한글 😀')
            self.assertEqual(result['ExitCode'], 0)
            wait_for(lambda value: value['text'] == 'CUCP 한글 😀')
            self.assertFalse(result['Json']['keyboard_used'])
            result = act('-Action', 'uia-invoke', '-Match', title, '-Label', 'Save Message')
            self.assertEqual(result['ExitCode'], 0)
            wait_for(lambda value: value['clicks'] == 1)
            self.assertFalse(result['Json']['mouse_moved'])
            result = act('-Action', 'uia-toggle', '-Match', title, '-Label', 'Fixture Enabled')
            self.assertEqual(result['ExitCode'], 0)
            wait_for(lambda value: value['toggled'])
            focus = act('-Action', 'focus', '-WindowHwnd', str(initial['hwnd']))
            self.assertEqual(focus['ExitCode'], 0)
            # Coordinate acquisition from UIA is followed by a target guard; the
            # only physical destination is this disposable form's text field.
            found = self.invoke('-Action', 'uia-find', '-Match', title, '-Label', 'Fixture Text')['Json']
            point = found['top']['center']
            act('-Action', 'click', '-X', str(point['x']), '-Y', str(point['y']), '-TargetHwnd', str(initial['hwnd']))
            typed = act('-Action', 'type', '-Text', '실제 Unicode 입력 😀', '-ClearFirst', '-TargetHwnd', str(initial['hwnd']))
            self.assertEqual(typed['ExitCode'], 0)
            wait_for(lambda value: value['text'] == '실제 Unicode 입력 😀')
            blocked = act('-Action', 'type', '-Text', 'must not be entered', '-TargetHwnd', str(initial['hwnd'] + 1))
            self.assertEqual(blocked['ExitCode'], 3)
            self.assertEqual(current()['text'], '실제 Unicode 입력 😀')
            if initial['clipboard_safe']:
                act('-Action', 'shortcut', '-Keys', 'ctrl+a', '-TargetHwnd', str(initial['hwnd']))
                paste = act('-Action', 'ime-paste', '-Text', 'IME 붙여넣기 😀', '-TargetHwnd', str(initial['hwnd']))
                self.assertEqual(paste['ExitCode'], 0)
                self.assertTrue(paste['Json']['restored_clipboard'])
                wait_for(lambda value: value['text'] == 'IME 붙여넣기 😀' and value['clipboard_restored'])
            point = current()['button']
            clicked = act('-Action', 'click', '-X', str(point['x']), '-Y', str(point['y']), '-TargetHwnd', str(initial['hwnd']))
            self.assertEqual(clicked['ExitCode'], 0)
            self.assertTrue(clicked['Json']['post_click']['accurate'])
            wait_for(lambda value: value['clicks'] == 2)
        finally:
            (self.root / 'shutdown').write_text('owned fixture complete', encoding='utf-8')
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=1)
            process.stderr.close()


if __name__ == '__main__':
    unittest.main()
