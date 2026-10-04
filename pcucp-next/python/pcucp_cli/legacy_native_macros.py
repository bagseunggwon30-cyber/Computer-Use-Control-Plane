"""Original direct desktop macro arguments, reports and trajectory effects."""
from datetime import datetime
import time
from .legacy_cdp_contract import _ps_equal, ps_string, utf16_length
from .legacy_diagnostic_provider import option, owned_path
from .legacy_host_protocol import Authority, require
from .legacy_storage import append_trajectory
from .legacy_values import int32

OPERATIONS = frozenset(('native-health', 'native-windows', 'native-screenshot', 'type-native', 'shortcut-native',
    'uia-click-label', 'uia-invoke', 'uia-set-value', 'uia-toggle', 'ocr-screen', 'ocr-image', 'ocr-find-text',
    'ocr-uia-fuse', 'ocr-uia-invoke', 'screenshot-diff', 'ime-paste', 'modal-detect', 'hit-test', 'hit-scan'))
LIVE = frozenset(('type-native', 'shortcut-native', 'uia-click-label', 'uia-invoke', 'uia-set-value', 'uia-toggle',
    'ocr-uia-invoke', 'ime-paste'))


def _get(row, name, default=None):
    return row.get(name, default) if type(row) is dict else default


def _truth(value):
    if type(value) is dict:
        return True
    if type(value) is list:
        return len(value) > 1 or bool(value) and _truth(value[0])
    return bool(value)


class NativeMacros:
    def __init__(self, native, *, cache_directory, audit_directory, authority=Authority(), fast_hit=None):
        self.native, self.authority = native, authority
        self.cache, self.audit = owned_path(str(cache_directory)), owned_path(str(audit_directory))
        self.fast_hit = fast_hit

    def run(self, name, rest, *, brief=False):
        prepared=self.prepare(name,rest)
        if name == 'hit-test' and prepared['context']['fast']:
            require(self.fast_hit is not None, 'Read-only fast hit provider is unavailable.')
            started = time.monotonic()
            context = prepared['context']
            payload = self.fast_hit(context['x'], context['y'], context['target_hwnd'], context['target_match'])
            require(type(payload) is dict, 'Invalid fast hit acquisition.')
            payload = {**payload, 'elapsed_ms': round((time.monotonic() - started) * 1000)}
            reply = dict(Json=payload, Raw='', Err='', ExitCode=2 if payload.get('status') == 'partial' else 0,
                         ElapsedMs=payload['elapsed_ms'])
        else:
            reply=self.native(prepared['argv'],Authority(prepared['live']))
        return self.complete(name,rest,reply,prepared['context'],brief=brief)

    def prepare(self, name, rest):
        require(name in OPERATIONS and type(rest) is list and all(type(word) is str for word in rest), 'Unknown direct native macro.')
        if name in LIVE and not self.authority.live:
            raise PermissionError(f'macro {name} requires -AllowLiveControl')
        value = lambda key, default=None: option(rest, '--' + key, default)
        flag = lambda key: any(_ps_equal(word, '--' + key) for word in rest)
        argv, context = [], {}
        def add(key, item):
            if item:
                argv.extend(['-' + key, item])
        def region():
            raw = value('region')
            if raw and len(raw.split(',')) == 4:
                for key, item in zip(('ScreenshotX', 'ScreenshotY', 'ScreenshotW', 'ScreenshotH'), raw.split(',')):
                    argv.extend(['-' + key, item.strip()])
        def required(key):
            item = value(key)
            if not item:
                raise ValueError(f'macro {name} requires --{key}')
            return item
        if name in {'hit-test', 'hit-scan'}:
            x, y = int32(value('x')), int32(value('y'))
            target, hwnd = value('target-match'), int32(value('target-hwnd'))
            inset = int32(value('click-inset')); inset = inset if inset > 0 else 3
            # Preserve parse-before-coordinate-validation order.
            radius_raw, step_raw = value('radius'), value('step')
            radius = int32(radius_raw) if name == 'hit-scan' and radius_raw else 0
            step = int32(step_raw) if name == 'hit-scan' and step_raw else 6
            if x <= 0 or y <= 0:
                raise ValueError(f'macro {name} requires --x and --y')
            context = dict(x=x, y=y)
            argv = ['-Action', name, '-X', str(x), '-Y', str(y)]
            if name == 'hit-test':
                context.update(fast=flag('fast'), target_hwnd=hwnd, target_match=target or '')
                add('TargetMatch', target)
                if hwnd > 0: add('TargetHwnd', str(hwnd))
                add('ClickInset', str(inset))
                if flag('fast') or flag('no-uia'): argv.append('-SkipUia')
            else:
                argv += ['-ClickInset', str(inset), '-ScanRadius', str(max(0, radius)), '-ScanStep', str(step if step > 0 else 6)]
                add('TargetMatch', target)
                if hwnd > 0: add('TargetHwnd', str(hwnd))
        elif name == 'native-health':
            argv = ['-Action', 'health']
        elif name == 'native-windows':
            argv = ['-Action', 'windows']; add('Match', value('match'))
        elif name == 'native-screenshot':
            out = value('out-path') or value('out')
            if not out:
                self.cache.mkdir(parents=True, exist_ok=True)
                out = str(self.cache / ('native-shot-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f')[:-3] + '.png'))
            argv = ['-Action', 'screenshot', '-OutPath', out]
            for key, old in (('ScreenshotX', 'x'), ('ScreenshotY', 'y'), ('ScreenshotW', 'width'), ('ScreenshotH', 'height')):
                add(key, value(old))
        elif name == 'type-native':
            text, clear, enter = value('text'), flag('clear'), flag('enter')
            if not text and not clear and not enter:
                raise ValueError('macro type-native requires --text or --clear or --enter')
            argv = ['-Action', 'type']; add('Text', text)
            if clear: argv.append('-ClearFirst')
            if enter: argv.append('-PressEnter')
            context = dict(length=utf16_length(text or ''), clear=clear, enter=enter)
        elif name == 'shortcut-native':
            context['keys'] = required('keys'); argv = ['-Action', 'shortcut', '-Keys', context['keys']]
        elif name.startswith('uia-'):
            label = required('label'); context['label'] = label
            argv = ['-Action', 'uia-click' if name == 'uia-click-label' else name, '-Label', label]
            if name == 'uia-click-label':
                context['button'] = value('button') or 'left'; add('Button', context['button'])
            if name == 'uia-set-value':
                raw = value('value')
                if raw is None: raise ValueError('macro uia-set-value requires --value')
                argv += ['-Value', raw]
            add('Match', value('match')); add('Role', value('role'))
        elif name == 'ocr-screen':
            argv = ['-Action', 'ocr-screen']; region(); add('OcrLanguage', value('language'))
        elif name == 'ocr-image':
            context['path'] = required('path'); argv = ['-Action', 'ocr-image', '-OcrPath', context['path']]
            add('OcrLanguage', value('language'))
        elif name in {'ocr-find-text', 'ocr-uia-fuse', 'ocr-uia-invoke'}:
            context = dict(text=required('text'), match=value('match') or 'contains')
            argv = ['-Action', name, '-OcrText', context['text'], '-OcrMatch', context['match']]
            if name == 'ocr-find-text':
                maximum = int32(value('max-candidates'))
                if maximum > 0: add('OcrMaxCandidates', str(maximum))
                add('OcrLanguage', value('language'))
                path = value('path')
                if path: add('OcrPath', path)
                else: add('Match', value('target-match'))
            else:
                add('Match', value('match-window')); add('OcrLanguage', value('language'))
            if name != 'ocr-uia-invoke': region()
        elif name == 'screenshot-diff':
            before, after = value('before'), value('after')
            if not before or not after: raise ValueError('macro screenshot-diff requires --before and --after')
            argv = ['-Action', name, '-DiffBefore', before, '-DiffAfter', after]
            threshold = int32(value('threshold'))
            if threshold > 0: add('DiffThreshold', str(threshold))
            add('DiffIgnoreRegions', value('ignore-region')); region()
        elif name in {'ime-paste', 'modal-detect'}:
            argv = ['-Action', name]
            if name == 'ime-paste':
                argv += ['-Text', required('text')]
                if flag('press-enter'): argv.append('-PressEnter')
                add('TargetMatch', value('target-match'))
            else:
                add('Match', value('match'))
            try: hwnd = int32(value('target-hwnd'))
            except RuntimeError: hwnd = 0
            if hwnd > 0: add('TargetHwnd', str(hwnd))
        else:
            require(False, 'Unknown direct native operation.')
        return dict(argv=argv,context=context,live=self.authority.live and name in LIVE)

    def complete(self,name,rest,reply,context,*,brief=False):
        require(name in OPERATIONS and type(rest) is list and all(type(word) is str for word in rest), 'Unknown direct native macro.')
        require(type(context) is dict and type(reply) is dict, 'Invalid native macro completion.')
        if name in LIVE and not self.authority.live:
            raise PermissionError(f'macro {name} requires -AllowLiveControl')
        fields=({'x','y','fast','target_hwnd','target_match'} if name=='hit-test' else {'x','y'} if name=='hit-scan' else
            {'length','clear','enter'} if name=='type-native' else {'keys'} if name=='shortcut-native' else
            {'label','button'} if name=='uia-click-label' else {'label'} if name.startswith('uia-') else
            {'path'} if name=='ocr-image' else {'text','match'} if name in {'ocr-find-text','ocr-uia-fuse','ocr-uia-invoke'} else set())
        require(set(context)==fields,'Unexpected native macro completion context.')
        for key,item in context.items():
            require(type(item) is bool if key in ('clear','enter','fast') else
                type(item) is int and 0 < item < 2**31 if key in ('x','y') else
                type(item) is int and -(2**31) <= item < 2**31 if key=='target_hwnd' else
                type(item) is int and item>=0 if key=='length' else type(item) is str,
                'Invalid native macro completion context value.')
        require(type(reply) is dict and type(reply.get('ExitCode')) is int and type(reply.get('Raw')) is str,
            'Invalid direct native macro reply.')
        payload = reply['Json']; ok = _get(payload, 'status') == 'ok'
        elapsed, code = reply['ElapsedMs'], reply['ExitCode']
        v = lambda key: ps_string(_get(payload, key))
        line, schema = '', None
        if name == 'hit-test':
            point = f"@({context['x']},{context['y']})"
            if context['fast']:
                require(type(payload) is dict, 'Invalid fast hit completion.')
                tag = 'partial' if payload.get('status') == 'partial' else 'ok'
                line = f"{tag} hit-test {point} hwnd={v('root_hwnd')} title='{v('root_title')}' process={v('process_name')} matched={v('matched')} reason={v('match_reason')} uia=skipped source=wrapper_fast elapsed_ms={v('elapsed_ms')}"
                code = 2 if payload.get('status') == 'partial' else 0
                return dict(payload=payload, exit=code, json_depth=8, brief=line if brief else None, emit_json=not brief, raw=None)
            if payload is not None:
                tag = 'partial' if payload.get('status') == 'partial' else 'ok'
                suffix = ''
                if _truth(_get(payload, 'uia_point')):
                    uia = payload['uia_point']; u = lambda key: ps_string(_get(uia, key))
                    suffix = f" uia_refine=({u('refined_x')},{u('refined_y')}) role='{u('role')}' score={u('score')} source={u('point_source')}"
                elif _truth(_get(payload, 'uia_skipped')): suffix = ' uia=skipped'
                line = f"{tag} hit-test {point} hwnd={v('root_hwnd')} title='{v('root_title')}' process={v('process_name')} matched={v('matched')} reason={v('match_reason')}{suffix}"
            else:
                line = f"err hit-test {point} helper_failed exit={code}"
        elif name == 'hit-scan':
            point = f"@({context['x']},{context['y']})"
            if payload is not None and ok:
                best, recommended = _get(payload, 'best'), _get(payload, 'recommended_point')
                b = lambda key: ps_string(_get(best, key))
                p = lambda key: ps_string(_get(recommended, key))
                line = f"ok hit-scan {point} best=({p('x')},{p('y')}) confidence={p('confidence')} role='{b('role')}' score={b('final_score')} support={b('support')} source={p('point_source')} samples={v('sample_count')}"
            elif payload is not None:
                line = f"partial hit-scan {point} reason={v('reason') or 'no_candidate'} samples={v('sample_count')} matched={v('target_matched_samples')}"
            else:
                line = f"err hit-scan {point} helper_failed exit={code}"
        elif name == 'native-health':
            line = f"ok native-health win32={v('win32')} uia={v('uia')} ocr={v('ocr')} ocr_languages={','.join(_get(payload, 'ocr_languages', []) or [])} elapsed_ms={elapsed}" if ok else 'err native-health helper_unavailable raw=' + ps_string(reply['Err'])
            code = 0 if ok else 1
        elif name == 'native-windows':
            line = f"ok native-windows count={v('count')} elapsed_ms={elapsed}" if ok else 'err native-windows helper_failed'
        elif name == 'native-screenshot':
            line = f"ok native-screenshot path='{v('out_path')}' bytes={v('bytes')} elapsed_ms={elapsed}" if ok else 'err native-screenshot'
        elif name == 'type-native':
            line = f"ok type-native length={context['length']} clear={ps_string(context['clear'])} enter={ps_string(context['enter'])} elapsed_ms={elapsed}" if ok else f'err type-native exit={code}'
        elif name == 'shortcut-native':
            line = f"ok shortcut-native keys='{context['keys']}' elapsed_ms={elapsed}" if ok else f'err shortcut-native exit={code}'
        elif name == 'uia-click-label':
            line = f"ok uia-click-label '{context['label']}' @({v('x')},{v('y')}) matched='{v('matched_text')}' elapsed_ms={elapsed}" if ok else f"err uia-click-label '{context['label']}' exit={code} reason={v('reason')}"
            append_trajectory(self.audit, 'click', dict(label=context['label'], source='native_uia_click_label', button=context['button'], exit=code))
        elif name == 'uia-invoke':
            line = f"ok uia-invoke '{context['label']}' method={v('method')} mouse_moved={v('mouse_moved')} elapsed_ms={elapsed}" if ok else f"partial uia-invoke '{context['label']}' reason={v('reason')} exit={code}"
            append_trajectory(self.audit, 'click', dict(label=context['label'], source='native_uia_invoke', method=v('method'),
                mouse_moved=bool(_get(payload, 'mouse_moved')) if payload else True, exit=code))
        elif name == 'uia-set-value':
            line = f"ok uia-set-value '{context['label']}' length={v('value_length')} keyboard_used={v('keyboard_used')} elapsed_ms={elapsed}" if ok else f"partial uia-set-value '{context['label']}' reason={v('reason')} exit={code}"
        elif name == 'uia-toggle':
            line = f"ok uia-toggle '{context['label']}' previous={v('previous_state')} elapsed_ms={elapsed}" if ok else f"partial uia-toggle '{context['label']}' reason={v('reason')} exit={code}"
        elif name == 'ocr-screen':
            line = f"ok ocr-screen lines={v('line_count')} words={v('word_count')} language={v('engine_language')} elapsed_ms={elapsed}" if ok else f"err ocr-screen reason={v('reason')} exit={code}"
        elif name == 'ocr-image':
            line = f"ok ocr-image path='{context['path']}' lines={v('line_count')} words={v('word_count')} language={v('engine_language')} elapsed_ms={elapsed}" if ok else f"err ocr-image path='{context['path']}' reason={v('reason')} exit={code}"
        elif name == 'ocr-find-text':
            top = _get(payload, 'top')
            t = lambda key: ps_string(_get(top, key))
            line = f"ok ocr-find-text '{context['text']}' match='{context['match']}' top='{t('text')}' score={t('score')} cx={t('cx')} cy={t('cy')} candidates={v('candidate_count')} elapsed_ms={elapsed}" if ok else f"partial ocr-find-text '{context['text']}' reason={v('reason')} exit={code}"
        elif name == 'ocr-uia-fuse':
            top = _get(payload, 'ocr_top')
            line = f"ok ocr-uia-fuse '{context['text']}' top='{ps_string(_get(top, 'text'))}' score={ps_string(_get(top, 'score'))} can_invoke={v('can_invoke')} pattern={v('invoke_pattern') or 'n/a'} recommend={v('recommendation')} elapsed_ms={elapsed}" if ok else f"partial ocr-uia-fuse '{context['text']}' reason={v('reason')} recommend={v('recommendation')}"
        elif name == 'ocr-uia-invoke':
            label = next((key + "='" + v('uia_' + key) + "'" for key in ('name', 'automation_id', 'class_name') if v('uia_' + key)), 'n/a')
            label = label.replace('automation_id=', 'id=', 1).replace('class_name=', 'class=', 1)
            line = f"ok ocr-uia-invoke '{context['text']}' method={v('method')} {label} score={v('ocr_score')} mouse_moved=False elapsed_ms={elapsed}" if ok else f"partial ocr-uia-invoke '{context['text']}' reason={v('reason')} exit={code}"
            append_trajectory(self.audit, 'click', dict(source='ocr_uia_invoke', text=context['text'], method=v('method'),
                uia_name=v('uia_name'), uia_automation_id=v('uia_automation_id'), exit=code))
        elif name == 'screenshot-diff':
            ignored = f" ignored={v('ignored_pixels')}" if _get(payload, 'ignored_pixels', 0) > 0 else ''
            line = f"ok screenshot-diff changed={v('changed')} ratio={v('changed_ratio')} pixels={v('changed_pixels')}/{v('effective_pixels')}{ignored} elapsed_ms={elapsed}" if ok else f"err screenshot-diff reason={v('reason')} exit={code}"
        elif name == 'ime-paste':
            schema = 'cucp.ime-paste/v1'
            status = _get(payload, 'status')
            line = f"ok ime-paste len={v('text_len')} restored={v('restored_clipboard')}" if ok else (
                f"blocked ime-paste reason={v('reason')}" if status == 'blocked' else 'partial ime-paste reason=' + (v('reason') or 'helper_failed'))
            code = {'ok': 0, 'blocked': 3}.get(status, 2) if payload else 1
        elif name == 'modal-detect':
            schema = 'cucp.modal-detect/v1'
            line = f"ok modal-detect candidates={v('candidate_count') or '0'} recommended={v('recommended_action') or 'observe'}"
            code = 0
        if schema:
            payload = {'schema': schema, **(payload or dict(status='error', reason='helper_failed'))}
        return dict(payload=payload, exit=code, json_depth=10, brief=line if brief else None,
            emit_json=not brief, raw=reply['Raw'] if not brief and not schema else None)
