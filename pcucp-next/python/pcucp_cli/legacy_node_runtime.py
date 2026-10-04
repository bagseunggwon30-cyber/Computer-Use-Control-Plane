"""Owned literal-argv Node forwarding; no shell, PS, build, or action replay."""
from datetime import datetime
import math
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
import uuid

from .legacy_diagnostic_provider import owned_path,read_regular
from .legacy_host_protocol import LegacyHostError,require
from .legacy_host_session import Cancellation
from . import native_host

def _text(path):
    if not path.exists():return ''
    raw,_=read_regular(path,maximum=64*1024*1024)
    return raw.decode('utf-8-sig',errors='replace')

class NodeRuntime:
    def __init__(self, *, cli_path,cache_directory,wrapper_log,timeout_ms=30000,
                 parent_deadline=math.inf,cancelled=None,node=None,log=None):
        require(type(timeout_ms) is int and -1<=timeout_ms<2**31,'Node timeout must be -1 or a nonnegative Int32.')
        self.cli_path=str(cli_path) if cli_path else None
        self.cache=owned_path(str(cache_directory))
        self.wrapper_log=owned_path(str(wrapper_log))
        self.timeout_ms,self.parent_deadline=timeout_ms,parent_deadline
        self._closed=threading.Event()
        self.cancelled=Cancellation(self._closed,cancelled) if cancelled is not None else self._closed
        self.node=node or shutil.which('node') or 'node'
        self.log_port=log
        self._process=None
        self._lock=threading.RLock()
        self._serial=threading.Lock()

    def close(self):
        self._closed.set()
        with self._lock:process=self._process
        if process is not None and process.poll() is None:native_host._terminate_process_tree(process)

    def _log(self,message):
        if self.log_port is not None:
            try:self.log_port(message)
            except Exception:pass
            return
        try:
            stamp=datetime.now().astimezone().isoformat(timespec='milliseconds')
            with self.wrapper_log.open('ab') as output:output.write(('['+stamp+'] '+message+'\r\n').encode('utf-8'))
        except OSError:pass

    def invoke(self,argv,*,capture_json=True,parse_reply=None):
        require(self._serial.acquire(blocking=False),'Node owner already has an invocation; no queued replay.')
        try:
            return self._invoke(argv,capture_json=capture_json,parse_reply=parse_reply)
        finally:
            self._serial.release()

    def _invoke(self,argv,*,capture_json,parse_reply):
        require(type(argv) is list and all(type(word) is str and '\0' not in word for word in argv) and
                type(capture_json) is bool,'Node argv must be inert strings.')
        require(not self.cancelled.is_set(),'Node owner cancelled before dispatch; no retry.')
        started=time.monotonic();command_id=uuid.uuid4().hex[:12]
        self._log(f"INVOKE [{command_id}] "+' '.join(argv))
        if not self.cli_path or not Path(self.cli_path).is_file():
            self._log(f"INVOKE [{command_id}] aborted: cli.mjs not found")
            return dict(ExitCode=1,Json=dict(status='error',error_type='cli_missing',
                summary='CUCP control-plane CLI (cli.mjs) was not found',
                recommended_action="Set CUCP_CLI_PATH env var to the desktop control cli.mjs, or use 'macro native-*' commands which require no external CLI."),
                Raw='',Err='cli.mjs not found',FilePath=None,CommandId=command_id,ElapsedMs=0)
        require(self.parent_deadline>time.monotonic(),'Inherited Node deadline expired before dispatch; no retry.')
        deadline=min(self.parent_deadline,started+self.timeout_ms/1000) if capture_json and self.timeout_ms>=0 else self.parent_deadline
        stdout_path=None
        try:
            command=[self.node,self.cli_path,*argv]
            options=dict(shell=False,close_fds=True)
            if os.name=='nt':options['creationflags']=subprocess.CREATE_NO_WINDOW if capture_json else 0
            else:options['start_new_session']=True
            if capture_json:
                self.cache.mkdir(parents=True,exist_ok=True)
                stdout_path=self.cache/('invoke-'+uuid.uuid4().hex+'.json')
                stderr_path=self.cache/('invoke-'+uuid.uuid4().hex+'.stderr.txt')
                with stdout_path.open('xb') as out,stderr_path.open('xb') as err:
                    process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=out,stderr=err,**options)
                    code,timed_out=self._wait(process,deadline)
                elapsed=round((time.monotonic()-started)*1000)
                raw,error=_text(stdout_path),_text(stderr_path)
                if timed_out:
                    self._log(f"TIMEOUT [{command_id}] "+' '.join(argv)+f" after {self.timeout_ms}ms (elapsed={elapsed}ms)")
                    payload=dict(status='error',error_type='invoke_timeout',command_id=command_id,elapsed_ms=elapsed,
                        timeout_ms=self.timeout_ms,summary=f'CUCP command timed out after {self.timeout_ms}ms',
                        recommended_action="Increase -InvokeTimeoutMs or run 'cucp macro ensure-helper'. Failing command: "+' '.join(argv))
                    return dict(ExitCode=124,Json=payload,Raw=raw,
                        Err=f'CUCP command timed out after {self.timeout_ms}ms (id={command_id}, elapsed={elapsed}ms)',
                        FilePath=str(stdout_path),CommandId=command_id,ElapsedMs=elapsed)
                payload=None
                if raw.strip() and parse_reply is not None:
                    try:payload=parse_reply(raw)
                    except (ValueError,LegacyHostError):pass
                return dict(ExitCode=code,Json=payload,Raw=raw,Err=error,FilePath=str(stdout_path),
                            CommandId=command_id,ElapsedMs=elapsed)
            process=subprocess.Popen(command,stdin=subprocess.DEVNULL,**options)
            code,timed_out=self._wait(process,deadline)
            require(not timed_out,'Inherited Node streaming deadline expired; command not replayed.')
            return dict(ExitCode=code,Json=None,Raw='',FilePath=None,CommandId=command_id,
                        ElapsedMs=round((time.monotonic()-started)*1000))
        except (OSError,ValueError) as error:
            # Cancellation is terminal rather than a fabricated successful reply.
            if self.cancelled.is_set():raise LegacyHostError('Node owner cancelled; command not replayed.') from error
            return dict(ExitCode=1,Json=None,Raw=str(error),Err='',FilePath=None,CommandId=command_id,
                        ElapsedMs=round((time.monotonic()-started)*1000))

    def _wait(self,process,deadline):
        with self._lock:self._process=process
        with native_host._PROCESS_LOCK:native_host._PROCESSES.add(process)
        timed_out=False
        try:
            while process.poll() is None:
                if self.cancelled.is_set():raise OSError('Node owner cancelled; no retry.')
                if time.monotonic()>=deadline:
                    timed_out=True;native_host._terminate_process_tree(process);break
                time.sleep(.005)
            try:process.wait(timeout=1)
            except subprocess.TimeoutExpired:raise OSError('Owned Node worker did not stop; no retry.')
            return process.returncode,timed_out
        finally:
            if process.poll() is None:native_host._terminate_process_tree(process)
            with native_host._PROCESS_LOCK:native_host._PROCESSES.discard(process)
            with self._lock:self._process=None
