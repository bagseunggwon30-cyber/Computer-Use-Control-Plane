"""Legacy CDP family with immutable startup authority and exact-origin transport.

Compatibility entrypoint, separate from modern snapshot/reference CDP contracts.
Fixed read algorithms use V8's throwOnSideEffect guard and never escalate. Live
algorithms retain legacy selector/label selection; hosts own action permission.
"""
from __future__ import annotations

import base64
import binascii
import json
from pathlib import Path
import time

from .cdp import CdpError
from .legacy_cdp_contract import (ACTIONS, LIVE_ACTIONS, LegacyCdpResult, dom_bridge_plan,
                                  find_page, utf16_length)
from .legacy_cdp_transport import LegacyCdpTransport

_ASSETS = Path(__file__).with_name('legacy_cdp_assets')
_ARGUMENTS = {
    'cdp-detect': set(), 'cdp-eval': {'expression', 'expression_b64'},
    'cdp-type': {'selector', 'text', 'clear', 'enter'}, 'cdp-click': {'selector'},
    'cdp-smart-find': {'needle'}, 'cdp-smart-type-find': {'needle'},
    'cdp-smart-click': {'needle'}, 'cdp-smart-type': {'needle', 'text', 'clear', 'enter'},
    'cdp-deep-find': {'needle'}, 'cdp-prosemirror-insert': {'selector', 'text'},
}


def _object(value):
    return value if isinstance(value, dict) else {}


def _array(value):
    # Actual JSON arrays only. A value/Count-shaped object is not an array.
    return value if isinstance(value, list) else [value]


def _pipeline_value(value):
    # An if-expression's output is collected: zero -> null, one -> scalar.
    values = _array(value)
    return None if not values else values[0] if len(values) == 1 else values


def _value(response):
    return _object(_object(response.get('result')).get('result')).get('value')


def _expression(asset, args):
    if asset not in ('smart', 'smart_read', 'type', 'click', 'deep_read', 'focus', 'editor_read'):
        raise ValueError('unknown audited asset')
    function = (_ASSETS / (asset + '.js')).read_text(encoding='utf-8')
    return '(' + function + ')(' + json.dumps(args, ensure_ascii=True, allow_nan=False, separators=(',', ':')) + ')'


class LegacyCdpAdapter:
    def __init__(self, endpoint: str, *, allow_live_control=False, timeout_s=8):
        self._transport = LegacyCdpTransport(endpoint, allow_live_control=allow_live_control, timeout_s=timeout_s)
        self._last_page_selection = None

    @property
    def endpoint(self): return self._transport.endpoint
    @property
    def allow_live_control(self): return self._transport.allow_live_control
    @property
    def port(self): return self._transport.origin.port

    def close(self): self._transport.close()
    def invalidate_snapshot(self): self._transport.invalidate_snapshot()

    def port_open(self):
        return self._transport.port_open(time.monotonic() + .12)

    def _discover(self, deadline):
        if not self._transport.port_open(deadline):
            return dict(available=False, port=self.port, error='tcp_port_closed_or_timeout', pages=[])
        try:
            version = self._transport.http_json('/json/version', min(deadline, time.monotonic() + .25))
        except (OSError, CdpError) as exc:
            self._transport._check_operation()
            return dict(available=False, port=self.port, error=str(exc), pages=[])
        pages = []
        try:
            raw = self._transport.http_json('/json/list', min(deadline, time.monotonic() + .25))
            if not isinstance(raw, list) or len(raw) > 256:
                raise CdpError('invalid_discovery', 'Discovery must contain an actual array of at most 256 targets')
            for p in raw:
                if not isinstance(p, dict): raise CdpError('invalid_discovery', 'Target must be an object')
                # Discovery exposes target metadata; only selected page/webview sockets are connectable.
                page = {key: p.get(key) for key in ('id', 'title', 'url', 'type')}
                page['ws_url'] = p.get('webSocketDebuggerUrl')
                pages.append(page)
        except (OSError, CdpError) as exc:
            self._transport._check_operation()
            # Transport/bound failures are not swallowed into a successful empty list.
            raise CdpError('invalid_discovery', str(exc)) from exc
        return dict(available=True, port=self.port, version=version if isinstance(version, dict) else None, pages=pages)

    def _emit(self, payload, code=0):
        return LegacyCdpResult(payload, code)

    def _call(self, page, expression, deadline, *, read=False, await_promise=False):
        params = dict(expression=expression, returnByValue=True, awaitPromise=await_promise,
                      timeout=max(1, int((deadline-time.monotonic()) * 1000)))
        if read:
            params.update(throwOnSideEffect=True, awaitPromise=False)
        return self._transport.call(page, 'Runtime.evaluate', params, deadline, live=not read, audited_read=read)

    def _exception(self, response, page, *, evaluation=False, read=False):
        exception = _object(response.get('result')).get('exceptionDetails')
        if not exception: return None
        exception = _object(exception)
        payload = dict(status='partial' if evaluation or read else 'error', reason='javascript_exception',
                       exception_text=str(exception.get('text') or ''),
                       exception_description=str(_object(exception.get('exception')).get('description') or ''),
                       page_id=page.get('id'))
        if read:
            payload.update(read_only=True, side_effect_guard=True, automatic_fallback=False)
        return self._emit(payload, 2 if evaluation or read else 1)

    def _execute(self, action, args, deadline):
        page_match = args.get('page_match', '')
        text = args.get('text', '')
        needle = args.get('needle', '')
        selector = args.get('selector', '')
        clear, enter = args.get('clear', False), args.get('enter', False)
        expression = args.get('expression', '')
        if action == 'cdp-eval':
            if not expression and args.get('expression_b64'):
                try:
                    # Convert.FromBase64String accepts whitespace; UTF8 replacement fallback is legacy behavior.
                    compact = ''.join(args['expression_b64'].split())
                    expression = base64.b64decode(compact, validate=True).decode('utf-8', errors='replace')
                except (ValueError, binascii.Error) as exc:
                    return self._emit(dict(status='error', reason='b64_decode_failed', detail=str(exc)), 1)
            if not expression:
                return self._emit(dict(status='error', reason='missing_cdp_expr', recommended_action='provide -CdpExpr <javascript> or -CdpExprB64 <base64>'), 1)
        if action in ('cdp-type', 'cdp-click') and not selector:
            return self._emit(dict(status='error', reason='missing_cdp_selector'), 1)
        if action in ('cdp-type', 'cdp-smart-type') and not (text or clear or enter):
            return self._emit(dict(status='error', reason='missing_text_or_action'), 1)
        smart = 'smart' in action
        dom_action = 'type' if 'type' in action else 'click'
        plan = dom_bridge_plan(dom_action, needle, self.port, page_match, text, clear, enter) if smart else None
        if smart and not needle:
            return self._emit(dict(status='error', reason='missing_cdp_text', recommended_action='provide -CdpText <visible text or label>'), 1)
        if action == 'cdp-deep-find' and not needle or action == 'cdp-prosemirror-insert' and not text:
            return self._emit(dict(status='error', reason='missing_text', recommended_action='provide -CdpText'), 1)
        if action == 'cdp-prosemirror-insert' and not selector:
            return self._emit(dict(status='error', reason='missing_selector', recommended_action="provide -CdpSelector (CSS for ProseMirror root, e.g. '.ProseMirror' or '[contenteditable=true]')"), 1)
        detected = self._discover(deadline)
        if not detected['available']:
            payload = dict(status='partial', reason='cdp_port_closed', port=self.port, detail=detected.get('error'))
            if plan: payload['dom_bridge_plan'] = plan
            if action == 'cdp-detect':
                payload['recommended_action'] = f'Start the Electron app with --remote-debugging-port={self.port}. For Electron app: see references/cdp-setup.md'
            if action == 'cdp-prosemirror-insert':
                payload['recommended_action'] = f'launch chrome/electron with --remote-debugging-port={self.port}'
            return self._emit(payload, 2)
        if action == 'cdp-detect':
            version = detected.get('version') or {}
            return self._emit(dict(status='ok', port=self.port, page_count=len(detected['pages']), pages=detected['pages'],
                browser=str(version.get('Browser') or ''), protocol_version=str(version.get('Protocol-Version') or ''),
                user_agent=str(version.get('User-Agent') or '')))
        page, self._last_page_selection = find_page(detected, page_match)
        if not page:
            payload = dict(status='partial', reason='no_matching_page', page_match=page_match)
            if smart or action == 'cdp-eval': payload['available_pages'] = detected['pages']
            if smart: payload.update(page_selection=self._last_page_selection, dom_bridge_plan=plan)
            return self._emit(payload, 2)
        self._transport.page_path(page)  # Validate before any browser domain or evaluation request.
        if action == 'cdp-prosemirror-insert': return self._prosemirror(page, args, deadline)
        read = action in ('cdp-smart-find', 'cdp-smart-type-find', 'cdp-deep-find')
        if smart:
            expression = _expression('smart_read' if read else 'smart',
                dict(action=dom_action, needle=needle, text=text, clear=clear, enter=enter))
        elif action == 'cdp-deep-find': expression = _expression('deep_read', dict(needle=needle))
        elif action in ('cdp-type', 'cdp-click'):
            expression = _expression(action[4:], dict(selector=selector, text=text.replace('\r', ''), clear=clear, enter=enter))
        try:
            response = self._call(page, expression, deadline, read=read, await_promise=action == 'cdp-eval')
        except (OSError, CdpError) as exc:
            if isinstance(exc, CdpError) and exc.status == 'blocked': raise
            payload = dict(status='error', reason='ws_call_failed' if action == 'cdp-deep-find' else 'cdp_call_failed', detail=str(exc))
            if action != 'cdp-click': payload['page_id'] = page.get('id')
            return self._emit(payload, 1)
        if response.get('error'):
            error = _object(response['error'])
            if action == 'cdp-eval':
                return self._emit(dict(status='error', reason='cdp_evaluate_error', cdp_error_code=error.get('code'), cdp_error_message=error.get('message'), page_id=page.get('id')), 1)
            if read:
                return self._emit(dict(status='partial', reason='read_side_effect_guard_unavailable',
                    cdp_error_code=error.get('code'), cdp_error_message=error.get('message'),
                    page_id=page.get('id'), read_only=True, automatic_fallback=False), 2)
        exception = self._exception(response, page, evaluation=action == 'cdp-eval', read=read)
        if exception and action != 'cdp-click': return exception
        value = _value(response)
        if action == 'cdp-eval':
            rv = _object(_object(response.get('result')).get('result'))
            return self._emit(dict(status='ok', expression=expression, result_type=str(rv.get('type') or ''),
                result_value=rv.get('value'), page_id=page.get('id'), page_title=str(page.get('title') or ''), page_url=str(page.get('url') or '')))
        if action == 'cdp-deep-find':
            if not isinstance(value, dict):
                return self._emit(dict(status='partial', reason='no_result', page_id=page.get('id'), page_title=page.get('title')), 2)
            return self._emit(dict(status='ok', page_id=str(page.get('id') or ''), page_url=str(page.get('url') or ''),
                page_title=str(page.get('title') or ''), traversal=value.get('traversal'), found_count=int(value.get('found_count') or 0), top_matches=_array(value.get('top_matches'))))
        value = _object(value)
        if smart: return self._smart_result(page, args, value, dom_action, plan)
        if not value.get('ok'):
            payload = dict(status='partial', reason=str(value.get('reason') or '') if value else 'no_result', selector=selector)
            if action == 'cdp-type': payload['page_id'] = page.get('id')
            return self._emit(payload, 2)
        payload = dict(status='ok', selector=selector)
        if action == 'cdp-type':
            payload.update(text_length=utf16_length(text), cleared=clear, sent_enter=bool(value.get('sent_enter')),
                tag_name=str(value.get('tag_name') or ''), is_content_editable=bool(value.get('is_content_editable')),
                is_input=bool(value.get('is_input')), current_value_length=int(value.get('current_value_length') or 0))
        else: payload['tag_name'] = str(value.get('tag_name') or '')
        payload.update(page_id=page.get('id'), page_title=str(page.get('title') or ''))
        return self._emit(payload)

    def _smart_result(self, page, args, value, dom_action, plan):
        if not value.get('ok'):
            return self._emit(dict(status='partial', reason=str(value.get('reason') or '') if value else 'no_result',
                query=args.get('needle', ''), candidate_count=int(value.get('candidate_count') or 0),
                top_score=int(value.get('top_score') or 0), candidate_summaries=_pipeline_value(value.get('candidate_summaries')) if value else None,
                page_id=page.get('id'), page_title=str(page.get('title') or ''), page_url=str(page.get('url') or ''),
                page_selection=self._last_page_selection, dom_bridge_plan=plan), 2)
        return self._emit(dict(status='ok', dom_action=dom_action, plan_only=bool(value.get('plan_only')),
            query=args.get('needle', ''), matched_text=str(value.get('matched_text') or ''),
            score=int(value.get('score') or 0), match_score=int(value.get('match_score') or 0),
            tag_name=str(value.get('tag_name') or ''), role=str(value.get('role') or ''), rect=value.get('rect'),
            candidate_count=int(value.get('candidate_count') or 0), text_length=int(value.get('text_length') or 0),
            sent_enter=bool(value.get('sent_enter')), page_id=page.get('id'), page_title=str(page.get('title') or ''),
            page_url=str(page.get('url') or ''), page_selection=self._last_page_selection,
            selector_candidates=_array(value.get('selector_candidates')), locator_candidates=_array(value.get('locator_candidates')),
            candidate_summaries=_array(value.get('candidate_summaries')), dom_bridge_plan=plan))

    def _prosemirror(self, page, args, deadline):
        for method in ('DOM.enable', 'Runtime.enable', 'Input.enable'):
            # Optional enable rejection is preserved; a transport loss stops all later phases.
            self._transport.call(page, method, {}, deadline, live=True)
        before_response = self._call(page, _expression('focus', args), deadline)
        exception = self._exception(before_response, page)
        if exception: return exception
        before = _value(before_response)
        if before is None:
            return self._emit(dict(status='partial', reason='selector_not_found', selector=args['selector'],
                page_id=str(page.get('id') or ''), page_title=str(page.get('title') or ''),
                recommended_action='verify selector matches a ProseMirror root or [contenteditable=true]'), 2)
        # The fixed focus asset returns verified target state; no text dispatch after failed focus.
        if not isinstance(before, dict) or not before.get('ok'):
            return self._emit(dict(status='blocked', reason='editor_focus_not_verified', selector=args['selector']), 3)
        response = self._transport.call(page, 'Input.insertText', {'text': args['text']}, deadline, live=True)
        if response.get('error'):
            return self._emit(dict(status='error', reason='input_inserttext_failed', detail=response['error']), 1)
        remaining = deadline - time.monotonic()
        if remaining < .08: raise CdpError('cdp_timeout', 'No budget remains for editor verification')
        if self._transport._cancelled.wait(.08): self._transport._check_operation()
        self._transport._check_operation()
        after_response = self._call(page, _expression('editor_read', args), deadline)
        exception = self._exception(after_response, page)
        if exception: return exception
        after_value = _value(after_response)
        if not isinstance(after_value, str):
            return self._emit(dict(status='partial', reason='editor_verification_failed', selector=args['selector']), 2)
        before_value = str(before.get('value') or '')
        changed = after_value.lower() != before_value.lower() and args['text'].lower() in after_value.lower()
        payload = dict(status='ok' if changed else 'partial', route='cdp_input_inserttext',
            page_id=str(page.get('id') or ''), page_title=str(page.get('title') or ''), selector=args['selector'],
            text_inserted=args['text'], before_value=before_value, after_value=after_value,
            before_length=utf16_length(before_value), after_length=utf16_length(after_value), changed=changed)
        if not changed:
            payload.update(reason='value_unchanged_or_text_not_found', recommended_action='verify ProseMirror is not in IME composition mode; try cdp-type as fallback')
        return self._emit(payload)  # Legacy helper returns 0 even for unchanged partial.

    def execute(self, action: str, args: dict | None = None, *, timeout_s=None) -> LegacyCdpResult:
        started = time.monotonic()
        if not isinstance(action, str) or action not in ACTIONS: raise ValueError('unsupported legacy CDP action')
        args = {} if args is None else args
        if not isinstance(args, dict): raise ValueError('args must be an object')
        if set(args) - (_ARGUMENTS[action] | {'page_match'}): raise ValueError('unknown legacy CDP arguments')
        for key, value in args.items():
            if key in ('clear', 'enter'):
                if type(value) is not bool: raise ValueError(key + ' must be boolean')
            elif not isinstance(value, str) or len(value) > 65536:
                raise ValueError(key + ' must be a string of at most 65536 characters')
        if action in LIVE_ACTIONS and not self.allow_live_control:
            return LegacyCdpResult(dict(status='blocked', reason='live_control_required', action=action, elapsed_ms=0), 3)
        duration = self._transport.timeout_s
        if timeout_s is not None:
            if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)) or not 0 < timeout_s <= 30:
                raise ValueError('timeout_s must be finite, positive, and at most 30')
            duration = min(duration, timeout_s)
        deadline = started + duration
        if not self._transport.lock.acquire(timeout=duration):
            return LegacyCdpResult(dict(status='error', reason='cdp_timeout', action=action, elapsed_ms=round((time.monotonic()-started)*1000)), 1)
        try:
            self._transport.mutation_started = False
            self._transport._operation_epoch = self._transport._epoch
            self._transport._check_operation()
            try:
                result = self._execute(action, args, deadline)
            except (OSError, CdpError) as exc:
                blocked = isinstance(exc, CdpError) and exc.status == 'blocked'
                result = self._emit(dict(status='blocked' if blocked else 'error', reason=getattr(exc, 'code', 'cdp_call_failed'), detail=str(exc)), 3 if blocked else 1)
            payload = dict(result.payload)
            if self._transport.mutation_started and payload.get('status') != 'ok':
                payload['mutation_may_have_occurred'] = True
            payload.update(elapsed_ms=round((time.monotonic()-started)*1000), action=action)
            return LegacyCdpResult(payload, result.exit_code)
        finally:
            self._transport._operation_epoch = None
            self._transport.lock.release()
