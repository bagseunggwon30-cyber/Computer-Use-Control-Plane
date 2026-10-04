"""Original direct desktop macro arguments, reports and trajectory effects."""
from datetime import datetime
from .legacy_cdp_contract import _ps_equal, ps_string, utf16_length
from .legacy_diagnostic_provider import option, owned_path
from .legacy_host_protocol import Authority, require
from .legacy_storage import append_trajectory
from .legacy_values import int32

OPERATIONS = frozenset(('native-health', 'native-windows', 'native-screenshot', 'type-native', 'shortcut-native',
    'uia-click-label', 'uia-invoke', 'uia-set-value', 'uia-toggle', 'ocr-screen', 'ocr-image', 'ocr-find-text',
    'ocr-uia-fuse', 'ocr-uia-invoke', 'screenshot-diff', 'ime-paste', 'modal-detect'))
LIVE = frozenset(('type-native', 'shortcut-native', 'uia-click-label', 'uia-invoke', 'uia-set-value', 'uia-toggle',
    'ocr-uia-invoke', 'ime-paste'))


def _get(row, name, default=None):
    return row.get(name, default) if type(row) is dict else default


class NativeMacros:
    def __init__(self, native, *, cache_directory, audit_directory, authority=Authority()):
        self.native, self.authority = native, authority
        self.cache, self.audit = owned_path(str(cache_directory)), owned_path(str(audit_directory))

    def run(self, name, rest, *, brief=False):
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
        if name == 'native-health':
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
        reply = self.native(argv, Authority(self.authority.live and name in LIVE))
        require(type(reply) is dict and type(reply.get('ExitCode')) is int and type(reply.get('Raw')) is str,
            'Invalid direct native macro reply.')
        payload = reply['Json']; ok = _get(payload, 'status') == 'ok'
        elapsed, code = reply['ElapsedMs'], reply['ExitCode']
        v = lambda key: ps_string(_get(payload, key))
        line, schema = '', None
        if name == 'native-health':
            line = f"ok native-health win32={v('win32')} uia={v('uia')} ocr={v('ocr')} ocr_languages={','.join(_get(payload, 'ocr_languages', []) or [])} elapsed_ms={elapsed}" if ok else 'err native-health helper_unavailable raw=' + reply['Err']
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
