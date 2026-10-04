"""Closed-effect interaction qualification against a pinned accepted PS5.1 oracle.

The accepted source includes the authorized SafeType no-probe/no-replay repair.
No captured helper, input, clipboard, IME, process, or model request is executed.
"""
import copy
from functools import lru_cache
import itertools
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
# Same accepted content as local d78, reachable from remote commit 56be343c.
ACCEPTED_TREE = 'c0d15371b60ebf62be45bfa68b90282405f07273'
ACCEPTED_REMOTE_COMMIT = '56be343c786027d27fa3dcb71732157caffc8de0'
BASELINE_TREE = 'bf895d3120dd5e145f360cb1c41e1d79a061d048'
PROJECT = ROOT / 'pcucp-next/dotnet/PcuCp.LegacyInteraction.ContractTests'
ORACLE = ROOT / 'tests/fixtures/legacy-interaction-oracle.ps1'
OPERATIONS = {'find-label', 'click-point', 'click-label', 'safe-type', 'icon-find',
              'icon-click', 'ocr-click', 'precision-validate'}
NON_REPLY = {'Sleep', 'TrajectoryAppend', 'PointCacheWrite', 'Notice', 'Console', 'PipelineOutput'}


def reply(value=None, exit=0, raw='captured 한글\r\nsecond line', elapsed=17):
    """Native helper and CUCP results retain their real case-insensitive PS fields."""
    return dict(ExitCode=exit, ElapsedMs=elapsed, Raw=raw, Json=value)


def element(text='Save', x=10, y=20, width=20, height=20, **kw):
    value=dict(text=text, rect=dict(x=x,y=y,width=width,height=height), window='Editor 한글',
               role='Button', confidence='high', affordance_id='fixture-affordance',
               synonyms=[], tooltip='', class_name='ButtonClass', area=width*height,
               small_icon=True, enabled=True)
    value.update(kw)
    return value


def appshot(grounded=(), fused=(), items=(), **kw):
    value=dict(Grounded=list(grounded), FusedElements=list(fused), Items=list(items),
               ObservationId='fixture-observation', FromCache=False, FocusedWindow='Editor 한글',
               ScreenshotPath='C:\\fixture\\screen 한글.png')
    value.update(kw)
    return value


def precheck(matched=True, **kw):
    value=dict(status='ok',matched=matched,root_hwnd=42,root_title='Editor 한글',
               process_name='fixture',match_reason='title')
    value.update(kw)
    return value


def scan(x=20,y=30, **kw):
    value=dict(status='ok', recommended_point=dict(x=x,y=y,confidence='high',
               point_source='native_clickable',native_clickable=True),
               best=dict(final_score=92), sample_count=49,candidate_count=3)
    value.update(kw)
    return reply(value)


def coord_profile(**kw):
    value=dict(status='ok',coordinate_risk='low',point_inside_target_window=True,
               coord_signature='geometry-one',target_window=dict(hwnd=42,process='fixture',
               **{'class':'Window'},title='Editor 한글',rect=dict(x=0,y=0,width=400,height=200)),
               point_window_relative=dict(norm_x=.25,norm_y=.375))
    value.update(kw)
    return value


def cases():
    """Bounded deterministic matrix, mirrored in brief mode; no random sampling."""
    result=[]
    def add(operation, rest=(), replies=(), label='', **kw):
        f=dict(operation=operation, rest=list(rest), replies=copy.deepcopy(list(replies)),
               allow_live=True, confirm_sensitive=False, case=label or f'{operation}-{len(result):04d}')
        f.update(kw);result.append(f);return f
    good=reply(dict(status='ok', x=20,y=30))
    window=reply(dict(status='ok',windows=[dict(hwnd=42,title='Editor 한글')]))
    focused=reply(dict(status='ok',verified=True,target_hwnd=42))
    point_args=['--x','10','--y','20']
    guarded=point_args+['--target-match','Editor']
    label_args=['--label','Save']
    safe_args=['--text','한글 + ^ % {value}\nsecond line','--target-match','Editor']
    ocr_args=['--text','Save']
    for op in sorted(OPERATIONS):
        add(op, label='missing-required')
        add(op, ['--unknown','ignored'], label='unknown-does-not-supply-required')
    for op,args in [('click-point',point_args),('click-label',label_args),('safe-type',safe_args),
                    ('icon-click',label_args),('ocr-click',ocr_args)]:
        add(op,args,allow_live=False,label='startup-live-denied')
    invalid_options={'find-label':(label_args,'--ambiguity-window'), 'click-point':(point_args,'--target-hwnd'),
                     'click-label':(label_args,'--offset-x'),'safe-type':(safe_args,'--max-attempts'),
                     'icon-find':(label_args,'--limit'),'ocr-click':(ocr_args,'--min-score')}
    for op,(args,opt) in invalid_options.items():
        for value in ('bad','2147483648','1.5','0x10',' '):
            add(op,args+[opt,value],[None]*32,label=f'cast-{opt}-{value!r}')

    # FindLabel: fast guard, exact/substring/prefix, confidence, tier, ambiguity,
    # cache/source provenance, one-vs-many pipeline shape, filters and limits.
    for visible,minimized in itertools.product((False,True),(False,True)):
        add('find-label',label_args+['--fast','--match','Editor'],
            [[dict(visible=visible,minimized=minimized)],appshot([element()])],
            label=f'fast-visible-{visible}-minimized-{minimized}')
    for missing in (None,False,[],{},[False]):
        add('find-label',label_args,[missing],label='unusable-appshot')
    for pool in ('Grounded','FusedElements','Items'):
        for text in ('Save','  sAvE  ','Save  now','Savage','Else','저장','Save\nnow'):
            shot=appshot();shot[pool]=[element(text=text)]
            add('find-label',label_args,[shot],label=f'text-{pool}-{text!r}')
    for confidence in ('high','medium','low','unknown','HIGH',0,.5,1,2,False,None):
        add('find-label',label_args,[appshot([element(confidence=confidence)])],label=f'confidence-{confidence!r}')
    for options in ([],['--explain'],['--json-only'],['--explain','--json-only'],['--window','Editor'],
                    ['--window','Else'],['--role','button'],['--role','Edit'],['--ambiguity-window','0'],
                    ['--ambiguity-window','1'],['--ambiguity-window','200'],['--no-vision']):
        add('find-label',label_args+options,[appshot([element(),element('Save now')],FromCache=True)],label='rank-and-output-options')
    for count in (0,1,2,5,8,12):
        add('find-label',label_args+['--explain'],[appshot([element(affordance_id=str(i)) for i in range(count)])],label=f'explain-count-{count}')
    for malformed in (None,{},dict(text='Save'),dict(rect=dict(x=1,y=2,width=0,height=0)),
                      element(rect={}),element(rect=dict(x=-10,y=0,width=0,height=0)),
                      element(sources={'value':['preserve'],'Count':1}),element(role=None,window=None)):
        add('find-label',label_args,[appshot([malformed])],label='raw-element-shape')
    add('find-label',['--LABEL','Save','--label','Wrong','--window',"Editor O'Brien"],
        [appshot([element(window="Editor O'Brien")])],label='first-case-insensitive-option')

    # IconFind/IconClick: synonym and tooltip scoring, dimensions, near-point
    # rounding, zero/negative near coordinates, radius, limit-before-ambiguity.
    for options in ([],['--json-only'],['--explain'],['--window','Editor'],['--window','Else'],
                    ['--role','Button'],['--role','Edit'],['--max-size','0','--min-size','0','--limit','0'],
                    ['--near-x','0','--near-y','0'],['--near-x','-1','--near-y','-2'],
                    ['--near-x','20','--near-y','30'],['--near-x','1','--near-y','1','--near-radius','2'],
                    ['--limit','1'],['--limit','2'],['--max-size','96']):
        add('icon-find',label_args+options,[[element(),element('Save now',x=40)]],label='icon-options')
    for width,height in ((5,6),(6,6),(63,64),(64,64),(65,64),(96,96),(7,9),(0,0)):
        add('icon-find',label_args,[[element(width=width,height=height)]],label=f'icon-size-{width}-{height}')
    for el in (element(text='x',synonyms=['',' SAVE ','save']),element(text='x',tooltip='Save'),
               element(text='x',synonyms=['savory']),element(text='Save',confidence='unknown'),
               element(text='Save',confidence=1),element(text='',synonyms=['Save']),
               element(text='save',enabled=False),element(window=None,role=None),element(rect={})):
        add('icon-find',label_args,[[el]],label='icon-sources-and-shapes')
    for count in (0,1,2,8,10):
        add('icon-find',label_args,[[element(affordance_id=str(i)) for i in range(count)]],label=f'icon-count-{count}')
    for aff,shot,act in itertools.product(([],[element()],[element(),element()]),
                                         (None,appshot()),(good,reply(None,exit=7))):
        add('icon-click',label_args,[aff,shot,act],label='icon-click-resolution-observation-and-result')
    add('icon-click',label_args+['--limit','1'],[[element(),element()],appshot(ObservationId=''),good],label='synthesized-observation-id')

    # ClickLabel uses real Find-Element and nested IconFind, then optional vision.
    for double,right,exit_code in itertools.product((False,True),(False,True),(0,7)):
        add('click-label',label_args+['--offset-x','2','--offset-y','-3'],
            [appshot([element()]),reply(dict(status='ok'),exit=exit_code),good],
            double=double,right_click=right,label='direct-label-buttons')
        add('click-label',label_args,[appshot(),[element()],reply(None,exit=exit_code),good],
            double=double,right_click=right,label='icon-label-buttons')
    for pool in ('Grounded','FusedElements','Items'):
        shot=appshot();shot[pool]=[element(text='x',synonyms=['Save'])]
        add('click-label',label_args,[shot,good],label=f'label-synonym-{pool}')
    for no_vision,vision_status in itertools.product((False,True),('ok','partial')):
        options=['--window','Editor']+(['--no-vision'] if no_vision else [])
        add('click-label',label_args+options,[appshot(),[],dict(status=vision_status,x=3,y=4,confidence='medium',reason='none'),good],label='vision-fallback')
    add('click-label',label_args,[None],label='appshot-failed')
    add('click-label',label_args,[appshot(),dict(throw='icon crawl failed'),dict(status='ok',x=3,y=4),good],label='icon-failure-continues-vision')
    add('click-label',label_args,[appshot([element(enabled=False,confidence=None)]),good],label='disabled-match-retained')

    # ClickPoint: guard, automatic/explicit scan, cache, clamping, safe fallback,
    # optional anchor history and post-success recording all preserve ordering.
    add('click-point',point_args,[good],label='bare-point')
    for alias in ('--target-match','--match','--window'):
        add('click-point',point_args+[alias,'Editor','--no-micro-refine','--no-anchor-history'],
            [precheck(),good],label=f'guard-alias-{alias}')
    for guard in (precheck(False),precheck(matched='false'),None,{},dict(status='error',matched=False)):
        add('click-point',guarded,[guard,None,scan(),None,good],label='guard-shapes')
    for cached in (None,dict(Json=dict(status='ok',recommended_point=scan()['Json']['recommended_point']),AgeMs=12),
                   dict(Json=dict(status='partial')),dict(Json={'value':['preserve'],'Count':1})):
        captures=[precheck(),cached]
        if not (cached and cached.get('Json',{}).get('status')=='ok'):captures.append(scan())
        captures += [good]
        add('click-point',guarded+['--no-anchor-history'],captures,label='point-cache')
    for options in (['--micro-refine'],['--precision'],['--micro-refine','--no-micro-refine'],
                    ['--precision','--precision-radius','100','--precision-step','100'],
                    ['--precision','--micro-radius','-1','--micro-step','0'],
                    ['--precision','--click-inset','0'],['--no-fast-guard'],['--no-cache'],
                    ['--cache-ttl','0'],['--cache-ttl','-1'],['--no-micro-refine'],
                    ['--no-micro-refine','--uia-safe'],['--no-micro-refine','--click-refine','uia-safe']):
        rest=guarded+options+['--no-anchor-history'];captures=[]
        if '--no-fast-guard' not in options:captures.append(precheck())
        micro=('--micro-refine' in options or '--precision' in options or '--no-micro-refine' not in options)
        if micro:
            if '--no-fast-guard' not in options and '--no-cache' not in options and '--cache-ttl' not in options:captures.append(None)
            captures.append(scan())
        captures.append(good)
        add('click-point',rest,captures,label='point-options')
    for outcome,unrefined in itertools.product((None,{},dict(status='partial',reason='no_sample'),dict(status='ok',recommended_point={})),(False,True)):
        add('click-point',point_args+['--precision']+(['--allow-unrefined'] if unrefined else []),
            [reply(outcome,exit=2),good],label='scan-failure-gate')
    for risk,inside,act in itertools.product(('low','high'),(False,True),(good,reply(dict(status='partial'),exit=2))):
        add('click-point',guarded+['--no-micro-refine'],
            [precheck(),coord_profile(coordinate_risk=risk,point_inside_target_window=inside),dict(score=75,count=2),act,True],label='anchor-record')
    for profile in (None,{},dict(throw='coord unavailable'),coord_profile(target_window=None)):
        add('click-point',guarded+['--no-micro-refine'],[precheck(),profile,good],label='anchor-profile-unavailable')
    add('click-point',guarded+['--no-micro-refine'],[precheck(),coord_profile(),dict(throw='anchor score failed'),good],label='anchor-score-caught')
    for raw in ('raw-no-newline','raw\r\nwith\nnewlines','',None):
        add('click-point',point_args,[reply(None,exit=7,raw=raw)],label='raw-native-output')
    for value in ({'value':['preserve'],'Count':1}, {'status':'ok','deep':{'object':{'values':[None,False,{'Count':1}]}}}):
        add('click-point',point_args,[reply(value)],label='raw-native-object')

    for value in (True,1,'native scalar',[],[False],[dict(status='ok')],[dict(status='ok'),dict(status='partial')]):
        add('click-point',point_args,[reply(value)],label='native-scalar-empty-and-singleton-json')

    # SafeType uses accepted no-probe/no-replay behavior. Only failed focus is
    # retried. Neither a failed click nor type nor submit is replayed.
    for windows in ([],[dict(hwnd=42,title='Other')],[dict(hwnd=42,title='Editor'),dict(hwnd=43,title='Editor')],
                    [dict(hwnd=42,title='EDITOR')],[dict(hwnd=4294967296,title='Editor')]):
        add('safe-type',safe_args,[reply(dict(status='ok',windows=windows)),focused,good],label='safe-target-resolution')
    for options in (['--click-x','1'],['--click-y','2'],['--enter','--ctrl-enter'],['--target-hwnd','bad'],
                    ['--click-x','bad','--click-y','2'],['--text',''],['--target-match','']):
        rest=[x for x in safe_args]
        if options[0] in ('--text','--target-match'):
            i=rest.index(options[0]);rest[i+1]=options[1]
        else:rest+=options
        add('safe-type',rest,[window,focused,good],label='safe-validation')
    for click,send,attempts in itertools.product((False,True),('none','enter','ctrl-enter'),(0,1,3,20)):
        rest=safe_args+['--max-attempts',str(attempts)]
        if click:rest+=['--click-x','0','--click-y','-2']
        if send!='none':rest+=['--'+send]
        captures=[window,focused]+([good] if click else [])+[good]+([good] if send!='none' else [])
        add('safe-type',rest,captures,label='safe-success-options')
    for stage in ('focus','click','type','send'):
        rest=safe_args+['--max-attempts','3','--click-x','1','--click-y','2','--enter']
        prefix={'focus':[window],'click':[window,focused],'type':[window,focused,good],'send':[window,focused,good,good]}[stage]
        for failure in (reply(dict(status='partial'),exit=2),reply(None,exit=0),dict(throw=f'{stage} dispatch failed')):
            add('safe-type',rest,prefix+[failure]+[failure if stage=='focus' else good]*3,label=f'safe-failure-{stage}')
    add('safe-type',safe_args+['--max-attempts','3'],[window,reply(dict(verified=False)),reply(dict(verified=True,target_hwnd=999)),focused,good],label='focus-only-retry')
    add('safe-type',safe_args+['--probe','SHOULD NEVER TYPE','--skip-probe'],[window,focused,good],label='legacy-probe-ignored')
    add('safe-type',['--text','-AllowLiveControl','--target-hwnd','4294967296'],
        [reply(dict(status='ok',windows=[dict(hwnd=4294967296,title='Editor')])),reply(dict(verified=True,target_hwnd=4294967296)),good],label='large-hwnd-control-like-text')

    # OCR threshold edge, malformed region, exact argv forwarding, raw writes.
    for score,min_score in itertools.product((None,0,69,70,71,100),(0,70,90)):
        add('ocr-click',ocr_args+['--min-score',str(min_score)],
            [reply(dict(status='ok',top=dict(score=score,cx=20,cy=30,text='Save now'))),good],label='ocr-threshold')
    for region in ('1, 2, 30, 40','1,2,3','a,b,c,d','','-2,0,4,8'):
        add('ocr-click',ocr_args+['--region',region,'--target-match','Editor','--language','ko','--button','right','--match','exact'],
            [reply(dict(status='ok',top=dict(score=99,cx=1,cy=2,text='Save'))),good],label='ocr-argv')
    for found in (None,{},False,dict(status='partial'),dict(status='ok',top=None)):
        add('ocr-click',ocr_args,[reply(found,exit=2),good],label='ocr-missing-match')
    for raw in ('raw','line\r\nsecond\n',None,''):
        add('ocr-click',ocr_args,[reply(dict(status='ok',top=dict(score=99,cx=1,cy=2,text='Save'))),reply(None,exit=7,raw=raw)],label='ocr-raw-and-error')

    # Precision samples include exception continuation, failed scans, 0/1/20
    # clamp edges, malformed samples default, and 2px/5px drift decisions.
    for sample_option,count in ((None,5),('bad',5),('0',1),('-1',1),('1',1),('2',2),('20',20),('21',20),('1.5',2),('0x10',16)):
        rest=point_args+([] if sample_option is None else ['--samples',sample_option])
        add('precision-validate',rest,[scan()]*count,label=f'precision-samples-{sample_option}')
    for coords in ([(0,0),(0,0)],[(0,0),(4,0)],[(0,0),(5,0)],[(0,0),(10,0)],[(0,0),(11,0)],[(0,0),(3,4),(6,8)]):
        add('precision-validate',point_args+['--samples',str(len(coords)),'--target-match','Editor'],[scan(x,y) for x,y in coords],label='precision-drift-boundaries')
    for bad in (dict(throw='sample failed'),reply(None,exit=2),reply(dict(status='partial')),scan(x=None),scan(recommended_point={})):
        add('precision-validate',point_args+['--samples','3'],[scan(),bad,scan()],label='precision-insufficient-evidence')

    # Explicit PS5.1 unstable-sort and linguistic-comparison probes. Preserve
    # distinct identities even when text, normalized text, or rank ties.
    for count in (2,3,4,7,16,17):
        ties=[element(text='Save',affordance_id=f'tie-{i}',x=i*20,confidence='high') for i in range(count)]
        add('find-label',label_args+['--explain'],[appshot(ties)],label=f'tied-find-{count}')
        add('icon-find',label_args+['--limit','20'],[ties],label=f'tied-icon-{count}')
        add('click-label',label_args,[appshot(ties),good],label=f'tied-click-{count}')
    for needle,other in (('café','cafe\u0301'),('한글','\u1112\u1161\u11ab\u1100\u1173\u11af'),('SAVE','save')):
        same=[element(needle,affordance_id='composed'),element(other,affordance_id='decomposed'),element(needle,affordance_id='duplicate')]
        add('find-label',['--label',needle,'--explain'],[appshot(same)],label=f'collating-find-{needle}')
        add('icon-find',['--label',needle],[same],label=f'collating-icon-{needle}')
        add('click-label',['--label',needle],[appshot(same),good],label=f'collating-click-{needle}')
    for value in ([],[None],[False],[{}],[element()]):
        add('find-label',label_args,[appshot(value)],label='explicit-empty-singleton-pool')
        add('icon-find',label_args,[value],label='explicit-empty-singleton-affordances')
    add('click-point',guarded+['--no-micro-refine','--no-anchor-history'],
        [precheck(False,root_hwnd=99,root_title='Other app',process_name='other',match_reason='identity_changed')],label='changed-guard-identity')
    add('click-point',guarded+['--no-anchor-history'],
        [precheck(True,root_hwnd=99,root_title='Editor second',process_name='other'),None,scan(),good],label='changed-root-cache-identity')
    add('safe-type',safe_args+['--target-hwnd','42'],
        [reply(dict(status='ok',windows=[dict(hwnd=99,title='Editor')])),focused,good],label='changed-pinned-window-identity')
    add('safe-type',safe_args+['--max-attempts','2'],
        [window,reply(dict(verified=True,target_hwnd=99)),reply(dict(verified=True,target_hwnd=99)),good],label='changed-focus-identity')

    # Inject throws at each consuming boundary in representative successful
    # routes. Inert padding supports a legacy caught-failure fallback, while the
    # differential still checks the exact consumed count and dispatch sequence.
    seeds=[next(f for f in result if f['case']==label) for label in
           ('anchor-record','safe-success-options','direct-label-buttons','icon-label-buttons',
            'vision-fallback','ocr-argv','point-cache','precision-drift-boundaries')]
    for seed in seeds:
        for index in range(len(seed['replies'])):
            f=copy.deepcopy(seed);f['case']=f"failure-{seed['case']}-{index}"
            f['replies'][index]=dict(throw='captured effect failure')
            f['replies'] += [None]*24;result.append(f)
    # Every case has a fixed upper bound; no caller can make this corpus loop.
    for f in result:
        f['replies'] += [None]*24
    for f in copy.deepcopy(result):
        f['brief']=True;f['case']+='-brief';result.append(f)
    # Append only the requested confidence conversion/promotion probes, keeping
    # the original 854 fixtures and their indices unchanged. IconFind accepts
    # numeric fields but intentionally boosts only string confidence values.
    for confidence in (429496729,429496730,-429496729,2147483647):
        pool=[element(confidence=confidence,affordance_id='numeric'),element('Save now',affordance_id='ordinary')]
        for operation,captures in (('find-label',[appshot(pool)]),('icon-find',[pool])):
            for brief in (False,True):
                add(operation,label_args,captures+[None]*24,brief=brief,
                    label=f'confidence-int32-boundary-{operation}-{confidence}'+('-brief' if brief else ''))
    return result



def boundary_cases():
    """Explicit execution-boundary corrections, separate from source parity."""
    good=reply(dict(status='ok'))
    uncertain=reply(dict(status='ok',mutation_may_have_occurred=True))
    found=reply(dict(status='ok',top=dict(score=99,cx=10,cy=20,text='Save')))
    windows=reply(dict(status='ok',windows=[dict(hwnd=42,title='Editor')]))
    focus=reply(dict(verified=True,target_hwnd=42))
    live=[
        dict(operation='click-point',rest=['--x','10','--y','20'],prefix=[]),
        dict(operation='click-label',rest=['--label','Save'],prefix=[appshot([element()])],double=True),
        dict(operation='icon-click',rest=['--label','Save'],prefix=[[element()],appshot()]),
        dict(operation='ocr-click',rest=['--text','Save'],prefix=[found]),
        dict(operation='safe-type',rest=['--text','value','--target-match','Editor','--enter'],prefix=[windows,focus]),
    ]
    result=[]
    for seed in live:
        for outcome in (uncertain,dict(throw='uncertain live dispatch',mutation_may_have_occurred=True)):
            f=copy.deepcopy(seed);prefix=f.pop('prefix');f.update(allow_live=True,replies=prefix+[outcome]+[good]*8,
                expected_consumed=len(prefix)+1,boundary='live',case=f"{f['operation']}-live-uncertainty")
            result.append(f)
    for flag in (False,True):
        result.append(dict(operation='click-point',rest=['--x','10','--y','20','--target-match','Editor','--no-micro-refine'],
            allow_live=True,replies=[precheck(),coord_profile(),dict(score=75),good,
                dict(throw='post-click history result lost',mutation_may_have_occurred=flag),good],
            expected_consumed=5,boundary='readback',case=f'post-click-readback-{flag}'))
    return result


def decode_wire(value):
    if value['kind']=='scalar':return value['value']
    if value['kind']=='array':return [decode_wire(x) for x in value['items']]
    return {x['name']:decode_wire(x['value']) for x in value['properties']}


def first_difference(actual,expected,path='$'):
    if type(actual) is not type(expected):return f'{path}: actual {type(actual).__name__}, expected {type(expected).__name__}'
    if isinstance(actual,dict):
        for key in expected:
            if key not in actual:return f'{path}.{key}: missing actual key'
            diff=first_difference(actual[key],expected[key],f'{path}.{key}')
            if diff is not None:return diff
        for key in actual:
            if key not in expected:return f'{path}.{key}: unexpected actual key'
    elif isinstance(actual,list):
        if len(actual)!=len(expected):return f'{path}: actual count {len(actual)}, expected {len(expected)}'
        for i,(a,b) in enumerate(zip(actual,expected)):
            diff=first_difference(a,b,f'{path}[{i}]')
            if diff is not None:return diff
    elif actual!=expected:return f'{path}: actual {repr(actual)[:256]}, expected {repr(expected)[:256]}'
    return None


def captured_failure_effects(fixture,effects):
    result=[];cursor=0
    for index,effect in enumerate(effects):
        if effect['kind'] in NON_REPLY:continue
        if cursor<len(fixture['replies']):
            value=fixture['replies'][cursor]
            if isinstance(value,dict) and 'throw' in value:
                result.append(dict(trace_index=index,reply_index=cursor,effect=effect,message=value['throw']))
        cursor+=1
    return result


@lru_cache(maxsize=1)
def built_candidate():
    dotnet=os.environ.get('CUCP_INTERACTION_DOTNET') or os.environ.get('DOTNET') or shutil.which('dotnet')
    if not dotnet:raise unittest.SkipTest('dotnet SDK not available')
    override=os.environ.get('CUCP_INTERACTION_TEST_DLL')
    if override:
        dll=Path(override)
        if not dll.is_file():raise AssertionError(f'Configured candidate DLL missing: {dll}')
        return dotnet,dll
    if not PROJECT.exists():raise AssertionError(f'Interaction contract project missing: {PROJECT}')
    built=subprocess.run([dotnet,'build',str(PROJECT),'-c','Release'],capture_output=True,timeout=180)
    if built.returncode:raise AssertionError(built.stdout.decode(errors='replace')+built.stderr.decode(errors='replace'))
    return dotnet,PROJECT/'bin/Release/net8.0/PcuCp.LegacyInteraction.ContractTests.dll'


def run_candidate(fixtures):
    dotnet,dll=built_candidate()
    p=subprocess.run([dotnet,str(dll),'--fixtures'],input=json.dumps(fixtures).encode(),capture_output=True,timeout=180)
    if p.returncode:raise AssertionError(p.stderr.decode(errors='replace'))
    return json.loads(p.stdout)


def run_oracle(fixtures,portable=False):
    ps=(os.environ.get('CUCP_INTERACTION_POWERSHELL') or
        (shutil.which('pwsh') if portable else shutil.which('powershell.exe')))
    if not ps:raise unittest.SkipTest('PowerShell oracle host not available')
    with tempfile.TemporaryDirectory(prefix='CUCP interaction 한글 ') as temp:
        d=Path(temp);accepted=d/'accepted.ps1';baseline=d/'original.ps1';inputs=d/'cases.json'
        accepted.write_bytes(subprocess.check_output(['git','show',f'{ACCEPTED_TREE}:scripts/cucp.ps1'],cwd=ROOT))
        baseline.write_bytes(subprocess.check_output(['git','show',f'{BASELINE_TREE}:scripts/cucp.ps1'],cwd=ROOT))
        inputs.write_text(json.dumps(fixtures),encoding='utf-8-sig')
        command=[ps,'-NoProfile','-NonInteractive','-File',str(ORACLE),'-Source',str(accepted),
                 '-BaselineSource',str(baseline),'-InputPath',str(inputs)]
        if portable:command.append('-AllowPortableHost')
        p=subprocess.run(command,capture_output=True,timeout=300)
        if p.returncode:raise AssertionError(p.stderr.decode(errors='replace'))
        return json.loads(p.stdout.decode('utf-8-sig'))


def render_candidate(results):
    """Render with PS5.1 itself, retaining property order, depth and raw writes."""
    ps=os.environ.get('CUCP_INTERACTION_POWERSHELL') or shutil.which('powershell.exe')
    if not ps:raise unittest.SkipTest('Windows PowerShell 5.1 not available')
    with tempfile.TemporaryDirectory(prefix='CUCP render interaction ') as temp:
        d=Path(temp);inputs=d/'results.json';script=d/'render.ps1'
        inputs.write_text(json.dumps(results),encoding='utf-8-sig');script.write_text(PS_RENDER,encoding='utf-8-sig')
        p=subprocess.run([ps,'-NoProfile','-NonInteractive','-File',str(script),'-InputPath',str(inputs)],capture_output=True,timeout=120)
        if p.returncode:raise AssertionError(p.stderr.decode(errors='replace'))
        return json.loads(p.stdout.decode('utf-8-sig'))


class InteractionPortableTests(unittest.TestCase):
    maxDiff=1200
    def test_bounded_corpus_covers_all_eight_functions_and_brief(self):
        fs=cases();self.assertEqual(len(fs),870)
        self.assertEqual({f['operation'] for f in fs},OPERATIONS)
        self.assertEqual(sum(bool(f.get('brief')) for f in fs),len(fs)//2)
        self.assertTrue(all(len(f['replies'])<100 for f in fs))
        self.assertEqual(len(json.dumps(fs)),len(json.dumps(cases())))
    def test_accepted_oracle_differs_from_original_for_authorized_safe_type(self):
        self.assertNotEqual(ACCEPTED_TREE,BASELINE_TREE)
        accepted=subprocess.check_output(['git','show',f'{ACCEPTED_TREE}:scripts/cucp.ps1'],cwd=ROOT).decode('utf-8-sig')
        body=accepted.split('function Invoke-MacroSafeType {',1)[1].split('\nfunction ',1)[0]
        self.assertIn('probe_mode = "disabled"',body)
        self.assertIn('textDispatched = $null',body)
        self.assertIn('Only focus preparation is retried',accepted)
    def test_oracle_captures_all_external_seams_without_loading_script(self):
        source=ORACLE.read_text(encoding='utf-8')
        for seam in ('Invoke-NativeHelper','Invoke-Cucp','Invoke-Appshot','_Get-UIAffordances',
                     '_Invoke-CodexVision','_Native-HitTestPoint','_PointPlan-ReadCache',
                     '_PointPlan-WriteCache','_Build-CoordProfile','_AnchorHistory-Score','_AnchorHistory-Append'):
            self.assertIn('function '+seam+' ',source)
        self.assertNotIn('. $Source',source);self.assertNotIn('& $Source',source)
        self.assertIn("Expected Windows PowerShell 5.1",source)
        self.assertIn('ReferenceEquals',source)
        self.assertIn("'PipelineOutput'",source)
    def test_wire_keeps_value_count_objects_and_empty_arrays(self):
        self.assertEqual(decode_wire(dict(kind='object',properties=[dict(name='Count',value=dict(kind='scalar',value=1)),dict(name='value',value=dict(kind='array',items=[]))])),{'Count':1,'value':[]})
        self.assertEqual(first_difference({'a':[0]},{'a':[1]}),'$.a[0]: actual 0, expected 1')
        self.assertEqual(first_difference({'a':[False]},{'a':[0]}),'$.a[0]: actual bool, expected int')
    def test_failure_binding_skips_non_reply_effects(self):
        f=dict(replies=[dict(throw='failed')])
        effects=[dict(kind='Notice'),dict(kind='Native',live=True),dict(kind='TrajectoryAppend')]
        self.assertEqual(captured_failure_effects(f,effects)[0]['trace_index'],1)
    def test_candidate_corpus_is_closed_and_exhaustion_free(self):
        fs=cases();actual=run_candidate(fs);self.assertEqual(len(actual),len(fs))
        for f,r in zip(fs,actual):
            with self.subTest(case=f['case'],brief=f.get('brief')):
                self.assertNotIn('Fixture exhausted',r.get('error',''))
                if not f['allow_live']:self.assertFalse(any(e['live'] for e in r['effects']))
                if r['state']=='complete':self.assertIn(r['exit'],(0,1,2,3,7))
    def test_explicit_live_and_readback_uncertainty_stops_at_boundary(self):
        fs=boundary_cases()
        for f,r in zip(fs,run_candidate(fs)):
            with self.subTest(case=f['case'],boundary=f['boundary']):
                self.assertEqual(r['consumed'],f['expected_consumed'])
                self.assertTrue(r['effects'])
                if f['boundary']=='live':
                    self.assertTrue(r['effects'][-1]['live'])
                    self.assertEqual(r['state'],'complete');self.assertEqual(r['exit'],2)
                    self.assertIs(r['payload']['mutation_may_have_occurred'],True)
                    self.assertIs(r['payload']['automatic_retry'],False)
                else:
                    self.assertEqual(r['effects'][-1]['kind'],'AnchorAppend')
                    self.assertEqual(r['state'],'error')
                    self.assertIn('post-click history result lost',r['error'])
                self.assertFalse(any(e['kind']=='TrajectoryAppend' for e in r['effects']))
    def test_safe_type_never_types_probe_and_never_replays_uncertain_text(self):
        fs=[f for f in cases() if f['operation']=='safe-type' and
            (f['case']=='legacy-probe-ignored' or f['case'].startswith('safe-failure-type')) and not f.get('brief')]
        for f,r in zip(fs,run_candidate(fs)):
            with self.subTest(case=f['case']):
                types=[e for e in r['effects'] if e['kind']=='Native' and len(e['argv'])>1 and e['argv'][1]=='type']
                self.assertLessEqual(len(types),1)
                self.assertTrue(all('SHOULD NEVER TYPE' not in e['argv'] for e in types))


@unittest.skipUnless(sys.platform=='win32','Windows PowerShell 5.1 differential qualification')
class InteractionWindowsParityTests(unittest.TestCase):
    maxDiff=1200
    def test_oracle_wire_preserves_empty_pipeline_null_array_and_object(self):
        ps=os.environ.get('CUCP_INTERACTION_POWERSHELL') or shutil.which('powershell.exe')
        if not ps:raise unittest.SkipTest('Windows PowerShell 5.1 not available')
        script=r'''
param([string]$OraclePath)
$ErrorActionPreference='Stop';[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
if($PSVersionTable.PSVersion.Major -ne 5 -or $PSVersionTable.PSVersion.Minor -ne 1){throw 'Expected Windows PowerShell 5.1'}
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($OraclePath,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Oracle did not parse'}
$definition=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq 'Encode-Wire'},$true))
if($definition.Count -ne 1){throw 'Expected one wire encoder'}
. ([scriptblock]::Create($definition[0].Extent.Text))
$object=[pscustomobject]@{actual_null=$null;empty_pipeline=(@()|Select-Object -First 8);empty_array=@();empty_object=[pscustomobject]@{}}
$dictionary=[ordered]@{actual_null=$null;empty_pipeline=(@()|Select-Object -First 8);empty_array=@();empty_object=[pscustomobject]@{}}
$rows=@(foreach($value in @($object,$dictionary)){
 @{wire=(Encode-Wire $value);rendered=(Microsoft.PowerShell.Utility\ConvertTo-Json -InputObject $value -Depth 8 -Compress)}
})
[Console]::Out.WriteLine((Microsoft.PowerShell.Utility\ConvertTo-Json -InputObject $rows -Depth 100 -Compress))
'''
        with tempfile.TemporaryDirectory(prefix='CUCP wire interaction ') as temp:
            path=Path(temp)/'probe.ps1';path.write_text(script,encoding='utf-8-sig')
            result=subprocess.run([ps,'-NoProfile','-NonInteractive','-File',str(path),str(ORACLE)],capture_output=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
            rows=json.loads(result.stdout.decode('utf-8-sig'))
        self.assertEqual(len(rows),2)
        expected={'actual_null':None,'empty_pipeline':{},'empty_array':[],'empty_object':{}}
        for row in rows:
            self.assertIsNone(first_difference(decode_wire(row['wire']),expected))
            self.assertIsNone(first_difference(json.loads(row['rendered']),expected))

    def test_accepted_payload_console_effect_order_errors_and_exits(self):
        fixtures=cases();expected=run_oracle(fixtures);actual=run_candidate(fixtures)
        self.assertEqual(len(expected),len(fixtures));self.assertEqual(len(actual),len(fixtures))
        rendered=render_candidate(actual);self.assertEqual(len(rendered),len(fixtures))
        for index,(f,old,new,console) in enumerate(zip(fixtures,expected,actual,rendered)):
            with self.subTest(index=index,case=f['case'],operation=f['operation'],rest=f['rest']):
                self.assertNotIn('Fixture exhausted',old.get('error',''))
                self.assertEqual(new['state'],old['state'])
                expected_effects=decode_wire(old['effects'])
                self.assertIsNone(first_difference(new['effects'],expected_effects))
                self.assertEqual(new['consumed'],old['consumed'])
                self.assertEqual(new.get('pipeline',[]),old['pipeline'])
                self.assertEqual(console,old['console'])
                if old['state']=='error':self.assertEqual(new['error'],old['error'])
                else:
                    self.assertEqual(new['exit'],old['exit'])
                    if old['payload'] is not None:
                        expected_payload=decode_wire(old['payload'])
                        self.assertIsNone(first_difference(new['payload'],expected_payload))


PS_RENDER = r'''
param([string]$InputPath)
$ErrorActionPreference='Stop';[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
if($PSVersionTable.PSVersion.Major -ne 5 -or $PSVersionTable.PSVersion.Minor -ne 1){throw 'Expected Windows PowerShell 5.1'}
$all=New-Object Collections.ArrayList
foreach($r in (Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8|ConvertFrom-Json)){
 $writer=New-Object IO.StringWriter
 if($r.PSObject.Properties['console_chunks']){
  foreach($chunk in @($r.console_chunks)){
   if($chunk.newline){$writer.WriteLine([string]$chunk.text)}else{$writer.Write([string]$chunk.text)}
  }
 }else{foreach($line in @($r.console)){$writer.WriteLine([string]$line)}}
 if($r.emit_json){$writer.WriteLine((ConvertTo-Json -InputObject $r.payload -Depth $r.json_depth))}
 [void]$all.Add($writer.ToString());$writer.Dispose()
}
[Console]::Out.WriteLine((ConvertTo-Json -InputObject @($all) -Depth 100 -Compress))
'''

if __name__=='__main__':unittest.main()
