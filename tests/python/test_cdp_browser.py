"""Opt-in, sandboxed Chrome tests against an owned local HTML fixture only.

CUCP_CHROME_TEST=1 requires a preinstalled Chrome/Chromium executable on PATH.
The default suite explicitly skips these tests and never launches a browser.
No existing profile, desktop browser, account, external page, or package is used.
"""
from contextlib import ExitStack
import errno
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'pcucp-next' / 'python'))
from pcucp_cli.cdp import CdpAdapter, CdpError


_BROWSER_NAMES = ('google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser')
_SOURCE_SENTINEL = 'fixture-script-token-never-expose'
_HTML = '''<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>CUCP isolated CDP fixture</title>
<style nonce="fixture">body { font-family:sans-serif; padding:20px; }
input, [contenteditable] { display:block; width:420px; min-height:30px; margin:8px; }
[contenteditable] { border:1px solid black; }</style></head><body>
<button id="save" aria-label="Save">Save</button><output id="click-count">0</output>
<button id="other-save" aria-label="Save">Save</button><output id="other-count">0</output>
<label for="message">Write a note</label><input id="message" aria-label="Message">
<output id="message-value"></output><output id="input-count">0</output>
<output id="change-count">0</output>
<div id="editable" contenteditable="true" aria-label="Plain editor">seed</div>
<output id="editable-value">seed</output><output id="editable-events">0</output>
<output id="editable-trusted">false</output>
<div id="prosemirror" class="ProseMirror" contenteditable="true" aria-label="Editor">seed</div>
<output id="prosemirror-value">seed</output><output id="prosemirror-events">0</output>
<output id="prosemirror-trusted">false</output>
<script nonce="fixture">
const sourceOnly = 'fixture-script-token-never-expose';
const el = id => document.getElementById(id);
const increment = id => el(id).textContent = String(Number(el(id).textContent) + 1);
el('save').addEventListener('click', () => increment('click-count'));
el('other-save').addEventListener('click', () => increment('other-count'));
el('message').addEventListener('input', () => {
  increment('input-count'); el('message-value').textContent = el('message').value;
});
el('message').addEventListener('change', () => increment('change-count'));
for (const id of ['editable', 'prosemirror']) {
  el(id).addEventListener('input', event => {
    increment(id + '-events'); el(id + '-value').textContent = el(id).textContent;
    el(id + '-trusted').textContent = String(event.isTrusted);
  });
}
const ready = document.createElement('span'); ready.id = 'fixture-ready';
ready.textContent = 'Fixture ready'; document.body.appendChild(ready);
</script></body></html>'''.encode('utf-8')


class _FixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != self.server.fixture_path:
            self.send_response(404)
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(_HTML)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'nonce-fixture'; "
                         "style-src 'nonce-fixture'; connect-src 'none'; form-action 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(_HTML)

    def log_message(self, *_args):
        pass


def _stop_owned_browser(process):
    """Popen's exact child only: never search for or kill other browsers."""
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _cleanup_owned_browser_directory(root, process, prior_error=None):
    """Remove only this fixture's directory, after its exact child is reaped."""
    if process is not None and process.poll() is None:
        raise RuntimeError('Owned browser is still running; preserving its temporary directory') from prior_error
    failure_path = None

    def failed_removal(_function, path, error_info):
        # Python 3.10/3.11 can report only a basename in OSError.filename.
        # rmtree supplies the qualified path independently to this callback.
        nonlocal failure_path
        failure_path = path
        raise error_info[1]

    deadline = time.monotonic() + 1
    retry_error = None
    for attempt in range(20):
        if retry_error is not None and time.monotonic() >= deadline:
            raise retry_error
        failure_path = None
        try:
            shutil.rmtree(root, onerror=failed_removal)
            return
        except OSError as exc:
            # CI reported profile/Default ENOTEMPTY after child shutdown.
            # Allow bounded settling only for that owned-profile failure;
            # unrelated errors and a profile that never settles remain errors.
            if (process is None or exc.errno != errno.ENOTEMPTY or failure_path is None or
                    not Path(os.path.abspath(failure_path)).is_relative_to(root / 'profile')):
                raise
            remaining = deadline - time.monotonic()
            if remaining <= 0 or attempt == 19:
                raise
            retry_error = exc
            time.sleep(min(.05, remaining))


@unittest.skipUnless(os.environ.get('CUCP_CHROME_TEST') == '1',
                     'Set CUCP_CHROME_TEST=1 for sandboxed, temporary-profile Chrome fixture tests')
class CdpBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.browser = next((path for name in _BROWSER_NAMES if (path := shutil.which(name))), None)
        if cls.browser is None:
            raise RuntimeError('CUCP_CHROME_TEST=1 requires preinstalled official Chrome/Chromium on PATH; '
                               'this suite never installs a browser')
        if hasattr(os, 'geteuid') and os.geteuid() == 0:
            raise RuntimeError('Run Chrome fixture tests as a non-root user with the browser sandbox enabled; '
                               'the suite never uses --no-sandbox')

    def setUp(self):
        self.resources = ExitStack()
        self.addCleanup(self.resources.close)
        process = None
        root = Path(tempfile.mkdtemp(prefix='cucp-cdp-browser-'))
        self.resources.push(lambda _type, error, _tb: _cleanup_owned_browser_directory(root, process, error))
        self.root = root
        profile = root / 'profile'
        profile.mkdir()
        env = os.environ.copy()
        for key, name in (('HOME', 'home'), ('XDG_CONFIG_HOME', 'config'),
                          ('XDG_CACHE_HOME', 'cache'), ('XDG_DATA_HOME', 'data'), ('TMPDIR', 'tmp')):
            directory = root / name
            directory.mkdir()
            env[key] = str(directory)
        for key in ('CHROME_USER_DATA_DIR', 'CHROME_CONFIG_HOME', 'CHROMIUM_FLAGS',
                    'CHROME_FLAGS', 'CHROME_EXTRA_ARGS', 'CHROME_WRAPPER'):
            env.pop(key, None)
        server = ThreadingHTTPServer(('127.0.0.1', 0), _FixtureHandler)
        server.daemon_threads = True
        server.fixture_path = '/fixture-' + secrets.token_hex(12) + '.html'
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.resources.callback(server.server_close)
        self.resources.callback(thread.join, 5)
        self.resources.callback(server.shutdown)
        self.fixture_url = f'http://127.0.0.1:{server.server_port}{server.fixture_path}'
        log = self.resources.enter_context((root / 'chrome.log').open('w+b'))
        command = [self.browser, '--headless=new', '--remote-debugging-address=127.0.0.1',
                   '--remote-debugging-port=0', '--user-data-dir=' + str(profile),
                   '--no-first-run', '--no-default-browser-check', '--disable-background-networking',
                   '--disable-component-update', '--disable-domain-reliability', '--disable-sync',
                   '--disable-extensions', '--disable-default-apps', '--metrics-recording-only',
                   '--disable-breakpad', '--password-store=basic', '--use-mock-keychain',
                   '--no-proxy-server', '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1',
                   '--window-size=1024,768', self.fixture_url]
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                   env=env, close_fds=True)
        self.resources.callback(_stop_owned_browser, process)
        self.endpoint = None
        deadline = time.monotonic() + 60
        phase = "waiting for owned browser DevToolsActivePort"
        last_error = None
        while time.monotonic() < deadline:
            if process.poll() is not None:
                log.seek(0)
                raise RuntimeError('Owned sandboxed Chrome exited during startup: ' +
                                   log.read(8192).decode('utf-8', errors='replace'))
            port_file = profile / 'DevToolsActivePort'
            if self.endpoint is None and port_file.exists():
                lines = port_file.read_text(encoding='utf-8').splitlines()
                if lines and lines[0].isdigit() and 1 <= int(lines[0]) <= 65535:
                    self.endpoint = 'http://127.0.0.1:' + lines[0]
            if self.endpoint:
                phase = "waiting for exact local fixture target"
                probe = CdpAdapter(self.endpoint, timeout_s=2)
                try:
                    targets = probe.execute('cdp-detect')['targets']
                    matching = [item for item in targets if item['url'] == self.fixture_url]
                    if len(matching) == 1:
                        phase = "waiting for fixture readiness sentinel"
                        observed = probe.execute('cdp-observe', {'target_id': matching[0]['id']})
                        if any(node['attributes'].get('id') == 'fixture-ready' for node in observed['nodes']):
                            self.target_id = matching[0]['id']
                            return
                except CdpError as exc:
                    last_error = exc
                finally:
                    probe.close()
            time.sleep(.05)  # Only startup reads are retried; never a browser mutation.
        log.seek(0)
        raise RuntimeError(f'Owned sandboxed Chrome was not ready in 60 seconds (phase={phase}, endpoint_present={self.endpoint is not None}, child_exit={process.poll()}, last_error={last_error}): ' +
                           log.read(8192).decode('utf-8', errors='replace'))

    def adapter(self, live=False):
        adapter = CdpAdapter(self.endpoint, allow_live_control=live, timeout_s=5, snapshot_ttl_s=30)
        self.resources.callback(adapter.close)
        return adapter

    def observe(self, adapter):
        return adapter.execute('cdp-observe', {'target_id': self.target_id, 'max_depth': 12})

    def node(self, observed, element_id):
        matches = [item for item in observed['nodes'] if item['attributes'].get('id') == element_id]
        self.assertEqual(len(matches), 1, element_id)
        return matches[0]

    def action_args(self, observed, element_id, **extra):
        return {'snapshot_id': observed['snapshot_id'],
                'element_ref': self.node(observed, element_id)['element_ref'], **extra}

    def assert_blocked(self, code, call):
        with self.assertRaises(CdpError) as raised:
            call()
        self.assertEqual(raised.exception.code, code)
        self.assertEqual(raised.exception.status, 'blocked')
        self.assertFalse(raised.exception.mutation_may_have_occurred)

    def test_real_dom_observe_query_and_ambiguous_find(self):
        adapter = self.adapter()
        observed = self.observe(adapter)
        self.assertEqual(observed['target']['url'], self.fixture_url)
        self.assertNotIn(_SOURCE_SENTINEL, json.dumps(observed))
        self.assertFalse(any(node['tag_name'] in ('script', 'style') for node in observed['nodes']))
        queried = adapter.execute('cdp-query', {'snapshot_id': observed['snapshot_id'], 'selector': '#save'})
        self.assertEqual(queried['candidate_count'], 1)
        self.assertEqual(queried['candidates'][0]['element_ref'], self.node(observed, 'save')['element_ref'])
        found = adapter.execute('cdp-smart-find', {'snapshot_id': observed['snapshot_id'], 'text': 'Save', 'limit': 1})
        self.assertTrue(found['ambiguous'])
        self.assertFalse(found['automatic_action'])
        labelled = adapter.execute('cdp-smart-type-find', {'snapshot_id': observed['snapshot_id'], 'text': 'Write a note'})
        self.assertEqual(labelled['top']['attributes']['id'], 'message')
        self.assertEqual(self.node(self.observe(adapter), 'click-count')['text'], '0')

    def test_textarea_default_text_is_private_and_labeled_typing_still_works(self):
        live = self.adapter(live=True)
        setup = self.observe(live)
        live.execute('cdp-eval', {'snapshot_id':setup['snapshot_id'], 'expression':"""(()=>{
          const panel=document.createElement('div');panel.id='owned-notes-panel';
          const label=document.createElement('label');label.htmlFor='owned-notes';label.textContent='Owned notes';
          const area=document.createElement('textarea');area.id='owned-notes';
          area.textContent='CANARY-TEXTAREA-DEFAULT-OWNED';area.value='CANARY-TEXTAREA-CURRENT-OWNED';
          panel.append(label,area);document.body.append(panel);return true})()"""})
        adapter = self.adapter()
        with patch.object(adapter, '_call', wraps=adapter._call) as calls:
            observed = self.observe(adapter)
            self.assertNotIn('CANARY-', json.dumps(observed))
            area = self.node(observed, 'owned-notes')
            self.assertEqual(area['text'], '')
            self.assertIn('Owned notes', self.node(observed, 'owned-notes-panel')['text'])
            for command in ('cdp-smart-find', 'cdp-smart-type-find', 'cdp-deep-find'):
                found = adapter.execute(command, {'snapshot_id':observed['snapshot_id'], 'text':'CANARY-TEXTAREA'})
                self.assertEqual(found['candidate_count'], 0)
                self.assertNotIn('CANARY-', json.dumps(found))
            labelled = adapter.execute('cdp-smart-type-find', {'snapshot_id':observed['snapshot_id'], 'text':'Owned notes'})
            self.assertEqual(labelled['top']['element_ref'], area['element_ref'])
            queried = adapter.execute('cdp-query', {'snapshot_id':observed['snapshot_id'], 'selector':'#owned-notes'})
            self.assertEqual(queried['candidates'][0]['element_ref'], area['element_ref'])
            self.assertNotIn('CANARY-', json.dumps(queried))
        self.assertTrue(all(call.args[1].startswith('DOM.') for call in calls.call_args_list))
        typing = self.observe(live)
        result = live.execute('cdp-type', self.action_args(typing, 'owned-notes', text='owned replacement 한글', clear=True))
        self.assertTrue(result['dispatched'])
        after = self.observe(live)
        self.assertNotIn('CANARY-', json.dumps(after))
        proof = live.execute('cdp-eval', {'snapshot_id':after['snapshot_id'], 'expression':
            "({value:document.getElementById('owned-notes').value,defaultText:document.getElementById('owned-notes').textContent})"})
        self.assertEqual(proof['result_value'], {'value':'owned replacement 한글', 'defaultText':'CANARY-TEXTAREA-DEFAULT-OWNED'})

    def test_exact_button_click_once_and_consumed_snapshot(self):
        adapter = self.adapter(live=True)
        observed = self.observe(adapter)
        args = self.action_args(observed, 'save')
        result = adapter.execute('cdp-click', args)
        self.assertTrue(result['dispatched'])
        self.assert_blocked('stale_snapshot', lambda: adapter.execute('cdp-click', args))
        after = self.observe(adapter)
        self.assertEqual(self.node(after, 'click-count')['text'], '1')
        self.assertEqual(self.node(after, 'other-count')['text'], '0')

    def test_unicode_native_input_clear_append_and_events(self):
        adapter = self.adapter(live=True)
        text = '안녕 🙂 café "quote" \\ <tag>'
        observed = self.observe(adapter)
        adapter.execute('cdp-type', self.action_args(observed, 'message', text=text, clear=True))
        after = self.observe(adapter)
        self.assertEqual(self.node(after, 'message-value')['text'], text)
        self.assertEqual(self.node(after, 'input-count')['text'], '1')
        self.assertEqual(self.node(after, 'change-count')['text'], '1')
        adapter.execute('cdp-type', self.action_args(after, 'message', text=' + 덧붙임'))
        after = self.observe(adapter)
        self.assertEqual(self.node(after, 'message-value')['text'], text + ' + 덧붙임')
        adapter.execute('cdp-type', self.action_args(after, 'message', text='새 값', clear=True))
        after = self.observe(adapter)
        self.assertEqual(self.node(after, 'message-value')['text'], '새 값')
        self.assertEqual(self.node(after, 'input-count')['text'], '3')

    def test_contenteditable_and_prosemirror_shaped_browser_insert_text(self):
        adapter = self.adapter(live=True)
        # Local contenteditable fixture only; this does not claim ProseMirror-library compatibility.
        for element_id in ('editable', 'prosemirror'):
            with self.subTest(element_id=element_id):
                text = '브라우저 입력 🙂 <literal>'
                observed = self.observe(adapter)
                result = adapter.execute('cdp-prosemirror-insert', self.action_args(
                    observed, element_id, text=text, clear=True))
                self.assertEqual(result['operation'], 'prosemirror')
                after = self.observe(adapter)
                self.assertEqual(self.node(after, element_id + '-value')['text'], text)
                self.assertEqual(self.node(after, element_id + '-events')['text'], '1')
                self.assertEqual(self.node(after, element_id + '-trusted')['text'], 'true')
                adapter.execute('cdp-prosemirror-insert', self.action_args(after, element_id, text=' 끝'))
                after = self.observe(adapter)
                self.assertEqual(self.node(after, element_id + '-value')['text'], text + ' 끝')
                self.assertEqual(self.node(after, element_id + '-events')['text'], '2')

    def test_replaced_snapshot_and_cross_snapshot_reference_are_blocked(self):
        adapter = self.adapter(live=True)
        old = self.observe(adapter)
        fresh = self.observe(adapter)
        self.assert_blocked('stale_snapshot', lambda: adapter.execute('cdp-click', self.action_args(old, 'save')))
        self.assert_blocked('unknown_element_reference', lambda: adapter.execute('cdp-click', {
            'snapshot_id': fresh['snapshot_id'], 'element_ref': self.node(old, 'save')['element_ref']}))
        self.assertEqual(self.node(self.observe(adapter), 'click-count')['text'], '0')

    def test_actual_element_change_prevents_old_reference_mutation(self):
        adapter = self.adapter(live=True)
        old = self.observe(adapter)
        fixture_editor = self.adapter(live=True)
        setup = self.observe(fixture_editor)
        fixture_editor.execute('cdp-eval', {'snapshot_id': setup['snapshot_id'],
            'expression': "document.getElementById('save').setAttribute('aria-label', 'Changed label')"})
        self.assert_blocked('element_changed', lambda: adapter.execute('cdp-click', self.action_args(old, 'save')))
        self.assertEqual(self.node(self.observe(adapter), 'click-count')['text'], '0')

    def test_read_only_reads_and_mutation_denial_leave_fixture_unchanged(self):
        adapter = self.adapter()
        with patch.object(adapter, '_call', wraps=adapter._call) as calls:
            observed = self.observe(adapter)
            adapter.execute('cdp-query', {'snapshot_id': observed['snapshot_id'], 'selector': 'button'})
            adapter.execute('cdp-deep-find', {'snapshot_id': observed['snapshot_id'], 'text': 'Save'})
            for command, args in (
                ('cdp-click', self.action_args(observed, 'save')),
                ('cdp-type', self.action_args(observed, 'message', text='must not appear')),
                ('cdp-prosemirror-insert', self.action_args(observed, 'prosemirror', text='must not appear')),
                ('cdp-eval', {'snapshot_id': observed['snapshot_id'],
                              'expression': "document.getElementById('save').click()"}),
            ):
                with self.subTest(command=command):
                    self.assert_blocked('live_control_required', lambda: adapter.execute(command, args))
            after = self.observe(adapter)
        self.assertTrue(calls.call_args_list)
        self.assertTrue(all(call.args[1] in {'DOM.getDocument', 'DOM.describeNode', 'DOM.querySelectorAll'}
                            for call in calls.call_args_list))
        for element_id in ('click-count', 'other-count', 'input-count', 'change-count', 'prosemirror-events'):
            self.assertEqual(self.node(after, element_id)['text'], '0')
        self.assertEqual(self.node(after, 'message-value')['text'], '')
        self.assertEqual(self.node(after, 'prosemirror-value')['text'], 'seed')


if __name__ == '__main__':
    unittest.main()
