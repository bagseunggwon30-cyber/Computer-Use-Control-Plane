"""Independent owned-fixture expectations. No oracle/candidate normalization.

Acquisition tokens are process-local identity evidence, never substitute labels.
Whole-desktop windows/foreground/modal records remain raw incidental observations;
only exact owned controls/geometry and declared algorithm bounds earn coverage.
"""
from __future__ import annotations
import json
import re

GROUPS = {
    'native': ['health-cold', 'windows-owned', 'windows-empty', 'focused', 'modal', 'unsupported', 'health-warm'],
    'uia': ['uia-missing', 'uia-run', 'uia-edit', 'uia-disabled', 'uia-duplicate', 'uia-cap', 'uia-scan-bound', 'uia-no-match', 'uia-root-fallback', 'uia-run-reused', 'health-uia'],
    'ocr-file': ['ocr-file-text', 'ocr-file-blank', 'ocr-file-defaults', 'ocr-file-corrupt', 'ocr-file-reused', 'ocr-oversize', 'ocr-invalid-size'],
    'ocr-owned': ['ocr-owned-text', 'ocr-owned-reused'],
    'ocr-fallback': ['ocr-language-fallback', 'ocr-language-reused'],
    'ocr-retry': ['ocr-no-language', 'ocr-init-retry'],
}

def require(condition, message):
    if not condition:
        raise AssertionError(message)

def same(actual, expected):
    require(json.dumps(actual, sort_keys=True, ensure_ascii=False, allow_nan=False) == json.dumps(expected, sort_keys=True, ensure_ascii=False, allow_nan=False), f'Exact typed mismatch: {actual!r} != {expected!r}')

def shape(value, fields):
    require(type(value) is dict and set(value) == set(fields.split()), f'Wrong exact schema: expected {fields}; got {value!r}')

def integer(value):
    require(type(value) is int, f'Integer required: {value!r}')

def rect(value):
    shape(value, 'x y w h')
    for item in value.values(): integer(item)

def owned_rect(ready, key):
    r = ready[key]
    return dict(x=r['x'], y=r['y'], w=r['width'], h=r['height'])

def operation(row, name):
    return [call for call in row['calls'] if call['operation'] == name]

def value(row, name):
    calls = operation(row, name)
    require(len(calls) == 1 and 'error' not in calls[0], f'{name} must execute exactly once successfully')
    return calls[0]['result']

def owned_window(ready):
    return dict(hwnd=ready['hwnd'], title=ready['title'], **{'class': ready['window_class']}, pid=ready['pid'], rect=ready['outer'])

def validate_case(row, ready):
    shape(row, 'schema name pid action args result error calls diagnostics state')
    same(row['schema'], 'cucp.helper-provider-case/v1')
    same(row['error'], None)
    integer(row['pid']); require(row['pid'] > 0, 'Probe PID missing')
    shape(row['state'], 'request_count win32_loaded uia_loaded ocr_warm')
    integer(row['state']['request_count'])
    for key in ('win32_loaded', 'uia_loaded', 'ocr_warm'): require(type(row['state'][key]) is bool, 'State flag must be bool')
    require(type(row['calls']) is list and type(row['diagnostics']) is list, 'Evidence arrays missing')
    name, payload = row['name'], row['result']
    expected_action = 'health' if name.startswith('health-') else 'windows' if name.startswith('windows-') else 'modal-detect' if name=='modal' else 'uia-find-fast' if name.startswith('uia-') else 'ocr-screen-fast' if name.startswith('ocr-') else 'not-a-supported-action' if name=='unsupported' else 'focused'
    same(row['action'], expected_action)
    expected_args=None
    if name.startswith('windows-'): expected_args=dict(Match=ready['title']+(' absent' if name=='windows-empty' else ''))
    elif name.startswith('uia-') and name!='uia-missing':
        labels={'uia-run':'Run 한글','uia-run-reused':'Run 한글','uia-edit':'Fixture value','uia-disabled':'Disabled','uia-duplicate':'Duplicate','uia-cap':'Cap target','uia-scan-bound':'Beyond scan'}
        expected_args=dict(Label=labels.get(name,ready['title']+' missing label'),Match=ready['title']+(' absent' if name=='uia-root-fallback' else ''))
    elif name.startswith('ocr-'):
        r=ready['ocr']; expected_args=dict(X=r['x'],Y=r['y'],W=r['width'],H=r['height'])
        if name=='ocr-file-defaults': expected_args=dict(X=0,Y=0,W=0,H=0)
        elif name=='ocr-oversize': expected_args=dict(W=2147483647,H=1)
        elif name=='ocr-invalid-size': expected_args=dict(W=-1,H=1)
    same(row['args'],expected_args)
    if name.startswith('health-'):
        shape(payload, 'status schema helper_mode pid pipe_name uptime_s request_count win32_loaded')
        integer(payload['uptime_s']); require(0 <= payload['uptime_s'] <= 300, 'Unexpected uptime')
        same({k: v for k, v in payload.items() if k != 'uptime_s'}, dict(status='ok', schema='cucp.health/v1', helper_mode='persistent_server', pid=row['pid'], pipe_name='owned-provider-probe', request_count=row['state']['request_count'], win32_loaded=name != 'health-cold'))
        same(row['calls'], [])
    elif name.startswith('windows-'):
        shape(payload, 'status schema kind sources foreground windows count')
        same(payload['status'], 'ok'); same(payload['schema'], 'cucp.observation/v1'); same(payload['kind'], 'windows'); same(payload['sources'], ['win32_helper_server'])
        same(payload['windows'], [owned_window(ready)] if name == 'windows-owned' else [])
        same(payload['count'], len(payload['windows']))
        fg = payload['foreground']
        if fg is not None:
            shape(fg, 'hwnd title'); integer(fg['hwnd']); require(type(fg['title']) is str, 'Foreground title type')
            if fg['hwnd'] == ready['hwnd']: same(fg['title'], ready['title'])
        same(len(operation(row, 'win32.enumerate')), 1)
    elif name == 'focused':
        same(payload, dict(status='ok', schema='cucp.focused/v1', **owned_window(ready)))
        same(value(row, 'win32.foreground'), ready['hwnd'])
    elif name == 'modal':
        shape(payload, 'status schema foreground modal_candidates candidate_count recommended_action')
        same(payload['status'], 'ok'); same(payload['schema'], 'cucp.modal-detect/v1')
        candidates = payload['modal_candidates']; require(type(candidates) is list, 'Modal candidates array required')
        same(payload['candidate_count'], len(candidates))
        scores = []
        for item in candidates:
            shape(item, 'hwnd title class score reason is_modal'); integer(item['score'])
            require(item['hwnd'] is None or type(item['hwnd']) is int, 'Modal HWND type')
            require(type(item['is_modal']) is bool and type(item['title']) is str and type(item['class']) is str, 'Modal typed identity')
            scores.append(item['score'])
        same(scores, sorted(scores, reverse=True))
        children=value(row,'uia.children')
        same(operation(row,'uia.children')[0]['arguments'][1],'window-or-pane')
        acquired=[]
        for element in children:
            def field(op, fallback=None):
                found=[call for call in operation(row,op) if call['arguments']==[element]]
                return found[0].get('result',fallback) if len(found)==1 else fallback
            title,clazz,r=field('uia.name'),field('uia.class'),field('uia.rect')
            if title is None or clazz is None or r is None: continue
            modal=field('uia.isModal',False); score=100 if modal else 0; reason='uia_window_is_modal' if modal else None
            if re.search('#32770|MessageBox|Dialog|TaskDialog|Popup',clazz,re.I):
                score+=60; reason=reason or 'dialog_class_name'
            if 0<r['width']<900 and 0<r['height']<600:
                score+=20; reason=reason or 'small_window_size'
            if score: acquired.append(dict(hwnd=field('uia.handle'),title=title,**{'class':clazz},score=score,reason=reason,is_modal=modal))
        acquired.sort(key=lambda item:-item['score'])
        same(candidates,acquired)
        same([x for x in candidates if x['hwnd'] == ready['hwnd']], [dict(hwnd=ready['hwnd'],title=ready['title'], **{'class':ready['window_class']}, score=20,reason='small_window_size',is_modal=False)])
        top = candidates[0] if candidates else None
        expected = 'observe' if top is None else 'dismiss_or_confirm' if top['is_modal'] or top['score'] >= 100 else 'confirm_dialog' if top['score'] >= 60 else 'wait'
        same(payload['recommended_action'], expected)
        fg = payload['foreground']
        if fg is not None:
            shape(fg, 'hwnd title class'); integer(fg['hwnd']); require(type(fg['title']) is str and type(fg['class']) is str, 'Modal foreground type')
    elif name == 'unsupported':
        same(payload, dict(status='fallback_required',reason='action_not_supported_in_server',action='not-a-supported-action',recommended_action='wrapper should fall back to child process for this action'))
        same(row['calls'], [])
    elif name.startswith('uia-'):
        validate_uia(row, ready)
    elif name.startswith('ocr-'):
        validate_ocr(row, ready)
    else: raise AssertionError('Unknown required case: ' + name)


def validate_uia(row, ready):
    name, p = row['name'], row['result']
    if name == 'uia-missing':
        same(p, dict(status='error',reason='missing_label'))
        require(not operation(row, 'uia.root'), 'Missing label acquired desktop')
        return
    label, match = row['args']['Label'], row['args']['Match']
    root = value(row, 'uia.root'); subtree_calls = operation(row, 'uia.subtree')
    require(len(subtree_calls) == 1, 'Exactly one subtree acquisition required')
    subtree = subtree_calls[0]
    same(subtree['arguments'], [root] if name == 'uia-root-fallback' else [next(call['arguments'][0] for call in operation(row, 'uia.name') if call.get('result') == ready['title'])])
    # Diagnostics include all actual acquired identities, roles and geometry.
    diagnostics = row['diagnostics']; same([x['element'] for x in diagnostics], subtree['result'])
    for diagnostic in diagnostics:
        shape(diagnostic, 'element name control_type hwnd pid rect')
        require(type(diagnostic['name']) is str and type(diagnostic['control_type']) is str, 'UIA identity/role must be strings')
    pos = row['calls'].index(subtree)
    scanned = [x for x in row['calls'][pos+1:] if x['operation'] == 'uia.name']
    require(0 < len(scanned) <= 800, 'UIA scan must be bounded at 800')
    same([x['arguments'][0] for x in scanned], [x['element'] for x in diagnostics[:len(scanned)]])
    require(all('error' not in x for x in scanned), 'Owned names failed acquisition')
    if name in ('uia-scan-bound','uia-no-match','uia-root-fallback'):
        same(p, dict(status='partial',reason='no_match',label=label,match=match,candidate_count=0))
        same(len(scanned), min(800, len(diagnostics)))
        if name == 'uia-scan-bound':
            indexes = [i for i, d in enumerate(diagnostics) if d['name'] == 'Beyond scan']
            require(len(indexes) == 1 and indexes[0] >= 800, 'Owned Beyond scan did not exist after the boundary')
        return
    shape(p, 'status schema label match score best candidates candidate_count uia_warm')
    same(p['status'], 'ok'); same(p['schema'], 'cucp.uia-find/v1'); same(p['label'], label); same(p['match'], match); same(p['uia_warm'], True)
    keys = {'uia-run':['run','run_prefix','run_contains'], 'uia-run-reused':['run','run_prefix','run_contains'], 'uia-edit':['edit'], 'uia-disabled':['disabled'], 'uia-duplicate':['duplicate','duplicate_second']}
    expected_role = 'edit' if name == 'uia-edit' else 'button'
    wanted = [owned_rect(ready, k) for k in keys[name]] if name in keys else [dict(x=r['x'],y=r['y'],w=r['width'],h=r['height']) for r in ready['caps']]
    found = [d for d in diagnostics if label.lower() in d['name'].lower()]
    require(len(found) == len(wanted), 'Owned label population changed')
    expected_names=['Run 한글','Run 한글 extra','prefix Run 한글'] if name in ('uia-run','uia-run-reused') else [label]*len(wanted)
    same(sorted(d['name'] for d in found),sorted(expected_names))
    # Membership checks use geometry only to identify the fixture controls. Output
    # is compared below in actual acquisition order, never sorted/normalized.
    same(sorted([d['rect'] for d in found], key=lambda r:(r['x'],r['y'])), sorted(wanted,key=lambda r:(r['x'],r['y'])))
    require(all(d['control_type'] == expected_role and d['pid'] == ready['pid'] for d in found), 'Owned provider role/process mismatch')
    expected = [dict(name=d['name'],score=100 if d['name']==label else 80 if d['name'].startswith(label) else 50,rect=d['rect'],click_point=dict(x=round(d['rect']['x']+d['rect']['w']/2),y=round(d['rect']['y']+d['rect']['h']/2)),control_type=expected_role) for d in found[:16]]
    expected.sort(key=lambda item:-item['score'])
    if name in ('uia-run','uia-run-reused'): same([item['score'] for item in expected],[100,80,50])
    same(p['candidates'], expected); same(p['candidate_count'],len(expected)); same(p['best'],expected[0]); same(p['score'],100)
    if name == 'uia-cap':
        same(len(expected),16)
        last_id = found[15]['element']; same(scanned[-1]['arguments'],[last_id])


def validate_ocr(row, ready):
    name, p = row['name'], row['result']
    if name == 'ocr-no-language':
        same(p, dict(status='error',reason='ocr_init_failed',detail='no_ocr_language_available'))
        same(row['state']['ocr_warm'],False); require(not operation(row,'ocr.capture'),'Init failure must not capture')
        return
    same(row['state']['ocr_warm'],True)
    if name == 'ocr-oversize':
        maximum=value(row,'ocr.maxDimension'); integer(maximum); require(maximum>0,'Invalid actual OCR maximum')
        same(p,dict(status='error',reason='region_exceeds_max_image_dimension',max_dim=maximum))
        require(not operation(row,'ocr.tempPath') and not operation(row,'ocr.capture'),'Oversize must fail before capture')
        return
    if name in ('ocr-file-corrupt','ocr-invalid-size'):
        shape(p,'status reason detail'); same(p['status'],'error'); same(p['reason'],'ocr_failed' if name=='ocr-file-corrupt' else 'screenshot_failed')
        require(type(p['detail']) is str and len(p['detail'])>0,'Actual error detail missing')
    else:
        r=dict(x=0,y=0,w=800,h=600) if name=='ocr-file-defaults' else owned_rect(ready,'ocr'); text='' if name in ('ocr-file-blank','ocr-file-defaults') else 'HELLO 2468'
        same(p,dict(status='ok',schema='cucp.ocr-screen/v1',region=r,text=text,line_count=0 if not text else 1,lines=[] if not text else [dict(text=text,word_count=2)],engine_warm=True))
    capture=operation(row,'ocr.capture'); same(len(capture),1)
    path=value(row,'ocr.tempPath')
    expected_capture=[0,0,-1,1,path] if name=='ocr-invalid-size' else [0,0,800,600,path] if name=='ocr-file-defaults' else [ready['ocr']['x'],ready['ocr']['y'],ready['ocr']['width'],ready['ocr']['height'],path]
    same(capture[0]['arguments'],expected_capture)
    if name=='ocr-invalid-size':
        require('error' in capture[0] and capture[0]['source']=='actual-provider','Invalid dimensions must reach actual Bitmap refusal')
        require(not operation(row,'ocr.loadFile'),'Invalid capture must not decode')
        return
    same(value(row,'ocr.loadFile'), operation(row,'ocr.openRead')[0]['arguments'][0])
    cleanup=operation(row,'ocr.removeTemp'); same(len(cleanup),1); same(cleanup[0]['arguments'],[path]); same(cleanup[0]['remaining_file'],False)
    require(row['calls'][-1] is cleanup[0],'OCR cleanup must be final acquisition')
    require(type(capture[0].get('image_sha256')) is str and re.fullmatch('[a-f0-9]{64}',capture[0]['image_sha256']) is not None,'Owned image evidence hash missing')
    require(type(capture[0].get('image_bytes')) is int and 0 < capture[0]['image_bytes'] <= 2*1024*1024,'Owned image evidence size missing')
    require(type(capture[0].get('image_artifact')) is str,'Owned image artifact missing')
    same(capture[0]['source'],'actual-provider' if name.startswith('ocr-owned') else 'generated-owned-image')
    if name != 'ocr-file-corrupt':
        same(len(operation(row,'ocr.recognize')),1)
        require('error' not in operation(row,'ocr.recognize')[0],'Actual WinRT recognition failed')


def validate_group(group, rows, ready):
    same([row['name'] for row in rows], GROUPS[group])
    failures=[]
    for index,row in enumerate(rows,1):
        try:
            same(row['state']['request_count'],index)
            validate_case(row,ready)
        except Exception as error: failures.append(dict(case=row['name'],error=str(error)))
    calls=[call for row in rows for call in row['calls']]
    def count(name): return sum(call['operation']==name for call in calls)
    def successful(name):
        values=[call for call in calls if call['operation']==name]
        require(all('error' not in call and call.get('source')=='actual-provider' and 'result' in call for call in values),name+' must be successful actual-provider acquisition')
        return values
    require(count('win32.ensure')==1,'Actual successful Win32 initialization must be reused')
    successful('win32.ensure')
    if group=='uia':
        require(count('uia.load')==1,'Actual successful UIA load must be reused')
        successful('uia.load')
    if group.startswith('ocr-'):
        require(count('ocr.initialize')==(2 if group=='ocr-retry' else 1),'OCR initialization retry/cache count changed')
        require(count('ocr.createProfile')==(2 if group=='ocr-retry' else 1),'OCR engine cache count changed')
        successful('ocr.initialize')
        successful('ocr.createLanguage')
        engines=[call['result'] for call in calls if call['operation'] in ('ocr.createProfile','ocr.createLanguage') and call.get('result') is not None]
        require(len(engines)==1,'Exactly one successful engine must be retained')
        recognize=successful('ocr.recognize')
        require(len(recognize)>0,'No successful actual OCR recognition')
        for call in recognize: same(call['arguments'][0],engines[0])
        profiles=[call for call in calls if call['operation']=='ocr.createProfile']
        require(all('error' not in call and 'actual_result' in call for call in profiles),'Real profile query evidence missing')
        if group not in ('ocr-fallback','ocr-retry'):
            successful('ocr.createProfile')
        if group=='ocr-retry':
            same(profiles[0]['source'],'actual-provider-plus-explicit-profile-null-seam');same(profiles[0]['result'],None)
            same(profiles[1]['source'],'actual-provider');same(profiles[1]['result'],profiles[1]['actual_result'])
            first_languages=operation(rows[0],'ocr.languages');same(len(first_languages),1)
            same(first_languages[0]['source'],'actual-provider-plus-explicit-empty-languages-seam');same(first_languages[0]['result'],[])
            require('actual_result' in first_languages[0] and 'error' not in first_languages[0],'Real language query evidence missing')
            require(not operation(rows[0],'ocr.createLanguage'),'Empty languages must not create an engine')
        if group=='ocr-fallback':
            same(count('ocr.languages'),1);same(count('ocr.createLanguage'),1)
            profile=next(c for c in calls if c['operation']=='ocr.createProfile')
            same(profile['source'],'actual-provider-plus-explicit-profile-null-seam')
            languages=next(c for c in calls if c['operation']=='ocr.languages')['result']; require(len(languages)>0,'No real language available')
            same(next(c for c in calls if c['operation']=='ocr.createLanguage')['arguments'],[languages[0]])
    return failures
