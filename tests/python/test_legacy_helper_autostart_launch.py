"""Independent generated-CMD launch capture; only disposable inert fixtures run.

Portable checks are not Windows qualification. Native cases use an owned hidden
console, a disposable standard-library venv, and the capture fixture in place of
the real bootstrap. No Startup discovery, apply/install API, or helper runs here.
"""
from __future__ import annotations

import json
import base64
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import venv

from pcucp_cli.legacy_helper_autostart import plan_autostart


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / 'tests/fixtures/legacy-helper-autostart-capture.py'
OWNERSHIP = 'owned-temporary-autostart-launch-fixture/v1'
STRESS_SEGMENT = '한글 space %CUCP_CAPTURE_EXPANSION% !bang! ^ & (round)'
DEFAULT_IDLE = 28800000


def assert_argument_pair(test, captured, control, expected, executable):
    # Entire raw vectors must agree, including the venv redirector's index zero.
    test.assertEqual(captured['original_argv'],control['original_argv'],(captured,control))
    for record in (captured,control):
        test.assertEqual(record['original_argv'][1:],expected[1:],record)
        test.assertEqual(record['argv'],expected[3:],record)
        test.assertTrue(Path(record['executable']).samefile(executable),record)
        test.assertEqual(record['ignore_environment'],1)
        test.assertEqual(record['no_user_site'],1)


class AutostartLaunchFixtureTests(unittest.TestCase):
    def run_bounded_fixture(self, root, source, *, timeout=20):
        # Exercise the same collector used by the native driver, against only
        # a short, test-authored Python program in an owned temporary directory.
        spec = importlib.util.spec_from_file_location('_autostart_capture_fixture', FIXTURE)
        fixture = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixture)
        script = root / 'inert-output.py'
        script.write_text(source, encoding='utf-8')
        result = fixture._run_bounded_command(
            [sys.executable, '-E', '-s', str(script)], directory=root / 'evidence',
            cwd=root, timeout=timeout,
        )
        return fixture, result

    def test_inner_collector_bounds_both_raw_streams_and_rejects_overflow(self):
        with tempfile.TemporaryDirectory(prefix='cucp-autostart-overflow-') as temporary:
            root = Path(temporary)
            fixture, result = self.run_bounded_fixture(root,
                "import os\nos.write(1, b'out\\xff' + b'x' * 200000)\n"
                "os.write(2, b'err\\xfe' + b'y' * 200000)\n")
            for stream, prefix in (('stdout', b'out\xff'), ('stderr', b'err\xfe')):
                expected = prefix + (b'x' if stream == 'stdout' else b'y') * (fixture.STREAM_LIMIT - len(prefix))
                self.assertEqual(result[stream], expected)
                self.assertEqual(base64.b64decode(result[stream + '_base64'], validate=True), expected)
                self.assertEqual(Path(result['evidence_path']).with_suffix('.' + stream + '.bin').read_bytes(), expected)
                self.assertEqual(result['bytes_observed'][stream], 200004)
                self.assertTrue(result['truncated'][stream])
            with self.assertRaises(AssertionError):
                fixture._evidence_helper().require_success(result)

    def test_inner_collector_preserves_prefixes_before_timeout(self):
        with tempfile.TemporaryDirectory(prefix='cucp-autostart-deadline-') as temporary:
            started = time.monotonic()
            fixture, result = self.run_bounded_fixture(Path(temporary),
                "import os,time\nos.write(1,b'before-timeout\\xff')\n"
                "os.write(2,b'before-timeout\\xfe')\ntime.sleep(10)\n", timeout=.5)
            self.assertLess(time.monotonic() - started, 4)
            self.assertTrue(result['timed_out'])
            self.assertEqual(result['stdout'], b'before-timeout\xff')
            self.assertEqual(result['stderr'], b'before-timeout\xfe')
            with self.assertRaises(AssertionError):
                fixture._evidence_helper().require_success(result, expected_exit=result['exit_code'])

    def test_inner_collector_does_not_wait_for_inherited_pipe_eof(self):
        with tempfile.TemporaryDirectory(prefix='cucp-autostart-drain-') as temporary:
            started = time.monotonic()
            # The inert descendant only sleeps and inherits pipe handles. Its
            # cwd is outside this owned directory so Windows can remove it
            # after collection, before the child finishes naturally.
            fixture, result = self.run_bounded_fixture(Path(temporary),
                "import os,subprocess,sys\nos.write(1,b'parent-prefix')\n"
                "subprocess.Popen([sys.executable,'-E','-s','-c','import time; time.sleep(3)'], cwd='..')\n", timeout=1)
            self.assertLess(time.monotonic() - started, 2.5)
            self.assertEqual(result['stdout'], b'parent-prefix')
            self.assertTrue(result['drain_incomplete'])
            self.assertFalse(result['timed_out'])
            with self.assertRaises(AssertionError):
                fixture._evidence_helper().require_success(result)

    def test_pair_comparison_keeps_index_zero_tail_flags_and_executable_identity_strict(self):
        import copy
        with tempfile.TemporaryDirectory(prefix='cucp-autostart-paired-proof-') as temporary:
            root=Path(temporary);exe=root/'owned-python.exe';exe.write_bytes(b'inert')
            other=root/'other.exe';other.write_bytes(b'inert')
            expected=[str(exe),'-E','-s',str(root/'inert.py'),'--staged-unqualified','--idle-timeout-ms','12345']
            record=dict(original_argv=['observed-base-interpreter.exe',*expected[1:]],argv=expected[3:],
                        executable=str(exe),ignore_environment=1,no_user_site=1)
            assert_argument_pair(self,record,copy.deepcopy(record),expected,exe)
            for field,value in [('original_argv',['different-base.exe',*expected[1:]]),
                                ('original_argv',[record['original_argv'][0],'-I',*expected[2:]]),
                                ('argv',expected[3:]+['extra']),('executable',str(other)),
                                ('ignore_environment',0),('no_user_site',0)]:
                changed=copy.deepcopy(record);changed[field]=value
                for first,second in ((changed,record),(record,changed)):
                    with self.subTest(field=field):
                        with self.assertRaises(AssertionError): assert_argument_pair(self,first,second,expected,exe)

    def test_original_venv_argument_mismatch_remains_exact_hash_pinned(self):
        import hashlib
        directory=ROOT/'tests/fixtures/legacy-helper'
        raw_manifest=(directory/'observed-autostart-venv-manifest.json').read_bytes()
        self.assertEqual(hashlib.sha256(raw_manifest).hexdigest(),'8bbbef74c211bd1fc89c4c6f188717a936de98a30ba5b34cb1b817aeedbabd7e')
        manifest=json.loads(raw_manifest)
        self.assertEqual(manifest['status'],'failed-test-expectation-unqualified')
        for name,record in manifest['files'].items():
            raw=(directory/name).read_bytes()
            self.assertEqual(len(raw),record['bytes'])
            self.assertEqual(hashlib.sha256(raw).hexdigest(),record['sha256'])
            self.assertIn('tests/fixtures/legacy-helper/'+name+' -text',(ROOT/'.gitattributes').read_text())
        request=json.loads((directory/'observed-autostart-venv-request.json').read_bytes())
        captured=json.loads((directory/'observed-autostart-venv-capture.json').read_bytes())
        self.assertNotEqual(captured['original_argv'][0],request['python_exe'])
        self.assertEqual(captured['executable'],request['python_exe'])
        self.assertEqual(captured['original_argv'][1:4],['-E','-s',request['bootstrap']])

    def test_direct_control_command_is_closed_and_independent_of_capture(self):
        spec=importlib.util.spec_from_file_location('owned_control_capture',FIXTURE)
        fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
        self.assertEqual(fixture._control_command('python.exe','inert.py',12345,True),
                         ['python.exe','-E','-s','inert.py','--staged-unqualified','--idle-timeout-ms','12345','--allow-readonly-desktop'])
        for idle,desktop in ((0,False),(-1,False),(True,False),(2**31,False),(12345,1),(12345,'true')):
            with self.assertRaises(ValueError): fixture._control_command('python.exe','inert.py',idle,desktop)

    def test_inert_capture_records_full_interpreter_argv_and_exit(self):
        with tempfile.TemporaryDirectory(prefix='cucp-autostart-fixture-') as temporary:
            root = Path(temporary).resolve()
            bootstrap = root / 'capture 한글 % ! ^ & (test).py'
            shutil.copyfile(FIXTURE, bootstrap)
            output = root / 'captured.json'
            argv = [sys.executable, '-E', '-s', str(bootstrap), '--staged-unqualified',
                    '--idle-timeout-ms', '12345', '--allow-readonly-desktop']
            environment = dict(os.environ, CUCP_AUTOSTART_CAPTURE_OUTPUT=str(output),
                               CUCP_AUTOSTART_CAPTURE_EXIT='37')
            completed = subprocess.run(argv, env=environment, stdin=subprocess.DEVNULL,
                                       capture_output=True, timeout=20, check=False)
            self.assertEqual(completed.returncode, 37, completed.stderr)
            captured = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(captured['argv'], argv[3:])
            self.assertEqual(captured['original_argv'], argv)
            self.assertEqual(captured['exit_code'], 37)
            self.assertEqual(captured['ignore_environment'], 1)
            self.assertEqual(captured['no_user_site'], 1)
            self.assertEqual(completed.stdout.strip(), b'legacy-helper-autostart-capture')
            self.assertEqual(completed.stderr, b'')

    def test_plan_has_utf8_crlf_fixed_synchronous_command(self):
        with tempfile.TemporaryDirectory(prefix='cucp-autostart-plan-') as temporary:
            root = Path(temporary).resolve() / STRESS_SEGMENT
            root.mkdir()
            python_exe = root / 'python.exe'
            python_exe.write_bytes(b'inert, never executed')
            bootstrap = root / 'capture bootstrap.py'
            shutil.copyfile(FIXTURE, bootstrap)
            startup = root / 'startup fixture'
            plan = plan_autostart(startup, python_exe, bootstrap)
            self.assertFalse(startup.exists(), 'Planning must not install a Startup entry')
            raw = plan['shim']
            self.assertIsInstance(raw, bytes)
            self.assertFalse(raw.startswith(b'\xef\xbb\xbf'))
            self.assertNotIn(b'\n', raw.replace(b'\r\n', b''))
            text = raw.decode('utf-8', errors='strict')
            lines = text.splitlines()
            cp_line = next(i for i, line in enumerate(lines)
                           if line.strip().lower() == 'chcp 65001 >nul')
            self.assertTrue(all(line.isascii() for line in lines[:cp_line + 1]))
            self.assertIn('DisableDelayedExpansion', text)
            self.assertIn('setlocal EnableExtensions DisableDelayedExpansion', lines)
            clear_errorlevel = lines.index('set "ERRORLEVEL="')
            local_scope = next(i for i, line in enumerate(lines)
                               if line.lower().startswith('setlocal '))
            self.assertLess(local_scope, clear_errorlevel)
            self.assertLess(clear_errorlevel, cp_line)
            self.assertNotIn('powershell', text.lower())
            self.assertNotIn('pwsh', text.lower())
            self.assertNotIn('%*', text)
            self.assertNotIn('\nstart ', '\n' + text.lower())
            self.assertNotIn('\ncall ', '\n' + text.lower())
            self.assertIn('%%CUCP_CAPTURE_EXPANSION%%', text)
            self.assertEqual(Path(plan['shim_path']), startup / 'cucp-helper-autostart.cmd')
            self.assertEqual(tuple(plan['command']), (
                str(python_exe), '-E', '-s', str(bootstrap), '--staged-unqualified',
                '--idle-timeout-ms', str(DEFAULT_IDLE),
            ))


@unittest.skipUnless(os.name == 'nt' and os.environ.get('CUCP_REQUIRE_STAGED_AUTOSTART') == '1',
                     'Requires explicit owned Windows autostart gate; no simulated quoting pass')
class AutostartWindowsLaunchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='cucp-autostart-launch-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name).resolve()
        (cls.root / '.autostart-launch-fixture').write_text(OWNERSHIP, encoding='ascii')
        cls.venv_root = cls.root / ('python ' + STRESS_SEGMENT)
        # A temp venv tests a real executable path containing every quoted-path
        # hazard without copying a DLL-dependent python.exe incorrectly.
        venv.EnvBuilder(with_pip=False, symlinks=False).create(cls.venv_root)
        cls.python_exe = cls.venv_root / 'Scripts/python.exe'
        if not cls.python_exe.is_file():
            raise AssertionError('The disposable Windows Python fixture was not created')
        cls.serial = 0

    def run_capture(self, *, segment=STRESS_SEGMENT, idle_timeout_ms=None, desktop=False,
                    codepage=437, delayed_expansion='off', exit_code=37, extra_args=(),
                    inherited_errorlevel=None, command_extensions='on'):
        type(self).serial += 1
        case = self.root / f'case-{self.serial}'
        fixture_dir = case / segment
        fixture_dir.mkdir(parents=True)
        bootstrap = fixture_dir / 'capture bootstrap.py'
        shutil.copyfile(FIXTURE, bootstrap)
        startup = fixture_dir / 'startup fixture'
        kwargs = {'desktop': desktop}
        if idle_timeout_ms is not None:
            kwargs['idle_timeout_ms'] = idle_timeout_ms
        plan = plan_autostart(startup, self.python_exe, bootstrap, **kwargs)
        # Do not call install/apply. These are bytes in a test-owned directory,
        # unrelated to the user's real Startup folder, registry, or login.
        shim = Path(plan['shim_path'])
        self.assertEqual(shim, startup / 'cucp-helper-autostart.cmd')
        shim.relative_to(self.root)
        shim.parent.mkdir()
        shim.write_bytes(plan['shim'])
        capture_output, control_output, driver_output = case/'capture.json', case/'control.json', case/'driver.json'
        request = {
            'owned_root': str(self.root), 'shim': str(shim), 'bootstrap': str(bootstrap),
            'python_exe': str(self.python_exe), 'capture_output': str(capture_output),
            'driver_output': str(driver_output), 'codepage': codepage,
            'delayed_expansion': delayed_expansion, 'exit_code': exit_code,
            'extra_args': list(extra_args), 'inherited_errorlevel': inherited_errorlevel,
            'command_extensions': command_extensions, 'control_output':str(control_output),
            'idle_timeout_ms':DEFAULT_IDLE if idle_timeout_ms is None else idle_timeout_ms,'desktop':desktop,
        }
        request_path = case / 'request.json'
        request_path.write_text(json.dumps(request, ensure_ascii=True), encoding='utf-8')
        from helper_process_evidence import run_evidence, require_success
        logs=Path(os.environ.get('CUCP_HELPER_EVIDENCE_DIR',case/'evidence'))
        completed=run_evidence(
            [sys.executable,'-E','-s',str(FIXTURE),'--owned-console-driver',str(request_path)],
            directory=logs,label='autostart-launch-'+str(self.serial),timeout=40,limit=262144,
            creationflags=subprocess.CREATE_NEW_CONSOLE,hide_window=True)
        # Preserve the inner command/capture records before any assertion or
        # TemporaryDirectory cleanup. Unexpected oversized data cannot pass.
        for source, label in ((request_path,'request'),(capture_output,'capture'),(control_output,'control'),(driver_output,'driver')):
            if source.is_file():
                with source.open('rb') as stream: raw=stream.read(262145)
                Path(completed['evidence_path']).with_suffix('.'+label+'.json').write_bytes(raw[:262144])
                self.assertLessEqual(len(raw),262144,'Owned launch evidence exceeded bound')
        require_success(completed)
        driver = json.loads(driver_output.read_text(encoding='utf-8'))
        self.assertTrue(driver['owned_console'])
        self.assertIsNone(driver['error'], driver)
        require_success(driver['command_evidence'], expected_exit=exit_code)
        self.assertEqual(driver['returncode'], exit_code, driver)
        self.assertEqual(driver['before'], {'input': codepage, 'output': codepage}, driver)
        self.assertEqual(driver['after'], driver['before'], driver)
        self.assertEqual(driver['after_control'],driver['after'],driver)
        require_success(driver['control_command_evidence'],expected_exit=exit_code)
        self.assertEqual(base64.b64decode(driver['control_command_evidence']['stdout_base64'],validate=True).strip(),b'legacy-helper-autostart-capture')
        self.assertEqual(base64.b64decode(driver['control_command_evidence']['stderr_base64'],validate=True),b'')
        self.assertEqual(driver['stdout'].strip(), 'legacy-helper-autostart-capture', driver)
        self.assertEqual(driver['stderr'], '', driver)
        self.assertEqual(base64.b64decode(driver['stdout_base64'], validate=True).strip(),
                         b'legacy-helper-autostart-capture', driver)
        self.assertEqual(base64.b64decode(driver['stderr_base64'], validate=True), b'', driver)
        self.assertTrue(capture_output.is_file(), 'Synchronous bootstrap capture must exist on return')
        captured = json.loads(capture_output.read_text(encoding='utf-8'))
        control = json.loads(control_output.read_text(encoding='utf-8'))
        expected = [str(self.python_exe), '-E', '-s', str(bootstrap), '--staged-unqualified',
                    '--idle-timeout-ms', str(DEFAULT_IDLE if idle_timeout_ms is None else idle_timeout_ms)]
        if desktop:
            expected.append('--allow-readonly-desktop')
        self.assertEqual(tuple(plan['command']), tuple(expected))
        assert_argument_pair(self,captured,control,expected,self.python_exe)
        self.assertEqual(control['exit_code'],exit_code)
        self.assertEqual(control['console'],{'input':codepage,'output':codepage})
        self.assertIsInstance(control['command_line'],str)
        self.assertEqual(captured['exit_code'], exit_code)
        self.assertEqual(captured['console'], {'input': 65001, 'output': 65001})
        self.assertIsInstance(captured['command_line'], str)
        self.assertNotIn('--allow-live-control', captured['argv'])
        return captured, driver

    def test_special_paths_are_received_literally(self):
        for segment in ('plain', 'space path', '한국어 경로', 'percent %CUCP_CAPTURE_EXPANSION%',
                        'literal %% percent %1', 'exclamation !bang!', 'caret ^ character',
                        'ampersand & character', 'parentheses (value)', STRESS_SEGMENT):
            with self.subTest(segment=segment):
                self.run_capture(segment=segment)

    def test_default_custom_idle_and_optional_readonly_desktop(self):
        for idle_timeout_ms in (None, 12345):
            for desktop in (False, True):
                with self.subTest(idle_timeout_ms=idle_timeout_ms, desktop=desktop):
                    self.run_capture(idle_timeout_ms=idle_timeout_ms, desktop=desktop)

    def test_inherited_delayed_expansion_does_not_change_exclamation_paths(self):
        for delayed in ('on', 'off'):
            with self.subTest(delayed=delayed):
                self.run_capture(delayed_expansion=delayed)

    def test_inherited_disabled_extensions_do_not_break_codepage_or_exit(self):
        self.run_capture(command_extensions='off')

    def test_normal_console_codepage_pairs_are_restored(self):
        # chcp saves one active codepage. This specifically qualifies normal
        # equal input/output pairs; it does not claim split-codepage restoration.
        for codepage in (437, 949, 65001):
            with self.subTest(codepage=codepage):
                self.run_capture(codepage=codepage)

    def test_bootstrap_exit_code_is_returned_after_codepage_restore(self):
        for exit_code in (0, 37, 193):
            with self.subTest(exit_code=exit_code):
                self.run_capture(exit_code=exit_code)

    def test_inherited_errorlevel_cannot_override_bootstrap_exit_code(self):
        for inherited, actual in (('0', 37), ('999', 0)):
            with self.subTest(inherited_errorlevel=inherited, exit_code=actual):
                self.run_capture(inherited_errorlevel=inherited, exit_code=actual)

    def test_caller_arguments_cannot_enable_live_control_or_change_fixed_command(self):
        self.run_capture(extra_args=('--allow-live-control', '--ignored-caller-option', '123'))


if __name__ == '__main__':
    unittest.main()
