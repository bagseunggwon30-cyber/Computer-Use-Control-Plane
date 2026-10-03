"""Inert launch recorder and isolated-console driver for autostart CMD tests.

This file never imports CUCP, installs a launcher, or starts a helper. The driver
accepts only test-owned temporary paths and refuses to change a shared console.
The capture mode records interpreter arguments and exits with a requested code.
"""
from __future__ import annotations

import json
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import time


OWNERSHIP = 'owned-temporary-autostart-launch-fixture/v1'
OUTPUT_ENV = 'CUCP_AUTOSTART_CAPTURE_OUTPUT'
EXIT_ENV = 'CUCP_AUTOSTART_CAPTURE_EXIT'
STREAM_LIMIT = 65536


def _evidence_helper():
    # Only the original test driver calls this. The copied inert bootstrap does
    # not import repository code. The source location is fixed by this fixture,
    # never supplied through request JSON, PYTHONPATH, or an executable argument.
    source = Path(__file__).resolve().parents[1] / 'python/helper_process_evidence.py'
    spec = importlib.util.spec_from_file_location('_autostart_owned_evidence', source)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    return helper


def _run_bounded_command(command, *, directory, cwd=None, env=None, timeout=20):
    # Kept separate for portable overflow/deadline regression tests. The only
    # command the JSON driver accepts is its internally constructed cmd fixture.
    return _evidence_helper().run_evidence(
        command, directory=directory, label='autostart-inner-command', cwd=cwd,
        env=env, timeout=timeout, limit=STREAM_LIMIT,
    )


def _control_command(python_exe, bootstrap, idle_timeout_ms, desktop):
    # Independent direct launch uses only the same fixed, validated fixture argv.
    if type(idle_timeout_ms) is not int or not 0<idle_timeout_ms<=2147483647 or type(desktop) is not bool:
        raise ValueError('Invalid direct-control fixture arguments')
    command=[str(python_exe),'-E','-s',str(bootstrap),'--staged-unqualified','--idle-timeout-ms',str(idle_timeout_ms)]
    if desktop: command.append('--allow-readonly-desktop')
    return command


def _write_json(path, value):
    # Exclusive creation also detects an accidental second bootstrap launch.
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=True, indent=2)
        stream.write('\n')


def _kernel():
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    for name in ('GetConsoleCP', 'GetConsoleOutputCP'):
        function = getattr(kernel, name)
        function.argtypes = []
        function.restype = wintypes.UINT
    for name in ('SetConsoleCP', 'SetConsoleOutputCP'):
        function = getattr(kernel, name)
        function.argtypes = [wintypes.UINT]
        function.restype = wintypes.BOOL
    kernel.GetConsoleProcessList.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.DWORD]
    kernel.GetConsoleProcessList.restype = wintypes.DWORD
    kernel.GetCommandLineW.argtypes = []
    kernel.GetCommandLineW.restype = wintypes.LPWSTR
    return kernel


def _codepages(kernel):
    return {'input': kernel.GetConsoleCP(), 'output': kernel.GetConsoleOutputCP()}


def capture():
    output = Path(os.environ[OUTPUT_ENV])
    exit_code = int(os.environ[EXIT_ENV])
    record = {
        'schema': 'cucp.helper-autostart-launch-capture/v1',
        'argv': sys.argv,
        'original_argv': sys.orig_argv,
        'executable': sys.executable,
        'ignore_environment': sys.flags.ignore_environment,
        'no_user_site': sys.flags.no_user_site,
        'exit_code': exit_code,
        'console': None,
        'command_line': None,
    }
    if os.name == 'nt':
        kernel = _kernel()
        record['console'] = _codepages(kernel)
        record['command_line'] = kernel.GetCommandLineW()
    _write_json(output, record)
    print('legacy-helper-autostart-capture', flush=True)
    return exit_code


def drive(request_path):
    if os.name != 'nt':
        raise RuntimeError('The isolated console driver requires native Windows')
    import ctypes
    from ctypes import wintypes

    request_path = Path(request_path).resolve(strict=True)
    request = json.loads(request_path.read_text(encoding='utf-8'))
    root = Path(request['owned_root']).resolve(strict=True)
    # A caller must create both a disposable TemporaryDirectory and its marker.
    root.relative_to(Path(tempfile.gettempdir()).resolve(strict=True))
    request_path.relative_to(root)
    marker = root / '.autostart-launch-fixture'
    if marker.read_text(encoding='ascii') != OWNERSHIP:
        raise RuntimeError('Missing owned temporary fixture marker')

    def owned_path(name, *, exists=False):
        path = Path(request[name]).resolve(strict=exists)
        path.relative_to(root)
        return path

    shim = owned_path('shim', exists=True)
    bootstrap = owned_path('bootstrap', exists=True)
    python_exe = owned_path('python_exe', exists=True)
    output = owned_path('capture_output')
    control_output = owned_path('control_output')
    report_path = owned_path('driver_output')
    if shim.name != 'cucp-helper-autostart.cmd' or python_exe.name.lower() != 'python.exe':
        raise RuntimeError('Unexpected fixture launch target')
    if bootstrap.read_bytes() != Path(__file__).read_bytes():
        raise RuntimeError('Bootstrap must be an exact copy of this inert capture fixture')
    if output.exists() or control_output.exists() or report_path.exists():
        raise RuntimeError('Fixture outputs must not already exist')

    kernel = _kernel()
    processes = (wintypes.DWORD * 8)()
    count = kernel.GetConsoleProcessList(processes, len(processes))
    # This check occurs before either codepage setter. The test parent starts
    # this driver using CREATE_NEW_CONSOLE; its own console is never modified.
    if count != 1 or processes[0] != os.getpid():
        raise RuntimeError('Refusing to alter a shared or unverified console')
    original = _codepages(kernel)
    requested = int(request['codepage'])
    if requested not in (437, 949, 65001):
        raise RuntimeError('Unexpected fixture codepage')
    delayed = request['delayed_expansion']
    if delayed not in ('on', 'off'):
        raise RuntimeError('Unexpected delayed expansion setting')
    extensions = request.get('command_extensions', 'on')
    if extensions not in ('on', 'off'):
        raise RuntimeError('Unexpected command extensions setting')
    inherited_errorlevel = request['inherited_errorlevel']
    if inherited_errorlevel not in (None, '0', '999'):
        raise RuntimeError('Unexpected fixture ERRORLEVEL value')
    # The caller-supplied arguments intentionally look like unsupported helper
    # options. They contain no shell syntax and must never reach the bootstrap.
    extra = request['extra_args']
    if not isinstance(extra, list) or any(
        arg not in ('--allow-live-control', '--ignored-caller-option', '123') for arg in extra
    ):
        raise RuntimeError('Unexpected fixture caller arguments')

    direct_command=_control_command(python_exe,bootstrap,request['idle_timeout_ms'],request['desktop'])
    report = {
        'schema': 'cucp.helper-autostart-launch-driver/v1',
        'owned_console': True,
        'original_console': original,
        'returncode': None,
        'before': None,
        'after': None,
        'stdout': '',
        'stderr': '',
        'error': None,
    }
    try:
        if not kernel.SetConsoleCP(requested) or not kernel.SetConsoleOutputCP(requested):
            raise RuntimeError('Could not set the owned console codepage')
        report['before'] = _codepages(kernel)
        if report['before'] != {'input': requested, 'output': requested}:
            raise RuntimeError('Requested owned console codepage is not active')
        environment = dict(os.environ)
        environment[OUTPUT_ENV] = str(output)
        environment[EXIT_ENV] = str(request['exit_code'])
        environment['CUCP_CAPTURE_EXPANSION'] = 'WRONG_IF_PERCENT_EXPANDED'
        environment['bang'] = 'WRONG_IF_DELAYED_EXPANDED'
        environment['_CUCP_CP'] = 'inherited-value-must-not-be-used'
        environment['_CUCP_EXIT'] = 'inherited-value-must-not-be-used'
        environment.pop('ERRORLEVEL', None)
        if inherited_errorlevel is not None:
            environment['ERRORLEVEL'] = inherited_errorlevel
        cmd = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/cmd.exe'
        # The /c tail is a fixed ASCII basename plus allowlisted ASCII options,
        # all without spaces, quotes, or shell metacharacters. An argv list is
        # safe for this specific tail; never use this for arbitrary cmd strings.
        # cwd carries the fixture's %, ! and Unicode without caller expansion.
        command = [str(cmd), '/d', f'/e:{extensions}', '/s', f'/v:{delayed}', '/c', shim.name, *extra]
        deadline=time.monotonic()+20
        completed = _run_bounded_command(
            command, directory=report_path.parent / 'inner-command-evidence',
            cwd=shim.parent, env=environment,
        )
        report['returncode'] = completed['exit_code']
        # Retain exact raw prefixes once, plus byte counts and every incomplete
        # state. Display previews stay small even for malformed UTF-8 output.
        report['stdout_base64'] = completed['stdout_base64']
        report['stderr_base64'] = completed['stderr_base64']
        report['stdout'] = completed['stdout'][:512].decode('utf-8', errors='backslashreplace')
        report['stderr'] = completed['stderr'][:512].decode('utf-8', errors='backslashreplace')
        report['command_evidence'] = {
            key: value for key, value in completed.items()
            if key not in {'stdout', 'stderr', 'stdout_base64', 'stderr_base64'}
        }
        report['after'] = _codepages(kernel)
        _evidence_helper().require_success(completed, expected_exit=int(request['exit_code']))
        # Windows venv redirectors may rewrite original_argv[0] to their base
        # interpreter. Capture an independent direct invocation, never normalize
        # the generated launch or assume index zero equals sys.executable.
        remaining=deadline-time.monotonic()
        if remaining<=0: raise TimeoutError('Combined fixture deadline exhausted before direct control')
        control_environment=dict(environment);control_environment[OUTPUT_ENV]=str(control_output)
        control=_run_bounded_command(direct_command,directory=report_path.parent/'direct-control-evidence',
            cwd=shim.parent,env=control_environment,timeout=remaining)
        report['control_command_evidence']={key:value for key,value in control.items() if key not in {'stdout','stderr'}}
        report['after_control']=_codepages(kernel)
        _evidence_helper().require_success(control,expected_exit=int(request['exit_code']))
    except Exception as exc:
        report['error'] = f'{type(exc).__name__}: {exc}'
        report['after'] = _codepages(kernel)
    finally:
        kernel.SetConsoleCP(original['input'])
        kernel.SetConsoleOutputCP(original['output'])
        _write_json(report_path, report)
    return 0 if report['error'] is None else 1


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--owned-console-driver':
        raise SystemExit(drive(sys.argv[2]))
    raise SystemExit(capture())
