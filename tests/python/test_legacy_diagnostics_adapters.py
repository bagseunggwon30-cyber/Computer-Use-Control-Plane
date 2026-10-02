"""Exact retained diagnostic adapter, closed guards, and captured acquisition tests.

Windows tests require the matching NativeHost configured by the qualification job.
Original macro bodies remain present until these adapter gates pass.
"""
import json
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from test_legacy_diagnostics_parity import ACCEPTED_TREE, ROOT, FILE_OPERATIONS, cases, decode_wire

ADAPTER = ROOT / "scripts/cucp-legacy-diagnostic-adapter.ps1"
BRIDGE = ROOT / "scripts/cucp.ps1"
GUARDS = ROOT / "tests/fixtures/legacy-diagnostics-adapter-guards.ps1"
NO_REPLY = {"Clock", "Timestamp", "Sleep", "Notice"}
UNCERTAIN_MESSAGE = "mutation_may_have_occurred=true; automatic_retry=false; Diagnostic owned-state effect outcome is uncertain; automatic retry is disabled."


MIGRATED_DIAGNOSTICS = {
    'perf':'Invoke-MacroPerf', 'diagnose-lag':'Invoke-MacroDiagnoseLag',
    'health-quick':'Invoke-MacroHealthQuick', 'health-detail':'Invoke-MacroHealthDetail',
    'log-tail':'Invoke-MacroLogTail', 'self-test':'Invoke-MacroSelfTest',
    'release-notes':'Invoke-MacroReleaseNotes',
}
RETAINED_DIAGNOSTICS = {'benchmark','audit-summary'}
KNOWN_ADAPTER_FAMILIES = ('execution','precision','cdp','interaction','diagnostics','file-images')


def diagnostic_adapter_mode(root=ROOT):
    manifest=json.loads((root/'.github/migration-adapters.json').read_text(encoding='utf-8'))
    if not isinstance(manifest,dict) or set(manifest)!={'test_adapters'}:
        raise ValueError('Invalid diagnostic adapter selection manifest')
    values=manifest['test_adapters']
    if not isinstance(values,list) or any(type(v) is not str or v not in KNOWN_ADAPTER_FAMILIES for v in values) or len(values)!=len(set(values)):
        raise ValueError('Invalid diagnostic adapter selection manifest')
    return 'production' if 'diagnostics' in values else 'draft'


def actual_adapter_arguments(pinned_source, mode):
    if mode not in {'draft','production'}:raise ValueError('Unknown diagnostic entry mode')
    return ['-Source',str(BRIDGE if mode=='production' else pinned_source),
        '-AdapterSource',str(ADAPTER),'-BridgeSource',str(BRIDGE)]+(['-ProductionEntry'] if mode=='production' else [])


def diagnostic_uses_session(operation, mode):
    if mode not in {'draft','production'}:raise ValueError('Unknown diagnostic entry mode')
    if operation not in MIGRATED_DIAGNOSTICS and operation not in RETAINED_DIAGNOSTICS:
        raise ValueError('Unknown diagnostic operation')
    return mode=='draft' or operation in MIGRATED_DIAGNOSTICS


def changes_owned_state(effect):
    if effect["kind"] in {"AuditProbe", "ClearAppshotCache", "Appshot", "Notice", "Native", "Cli", "HelperUp", "AssertAuthorized"}:
        return True
    if effect["kind"] == "Macro" and effect["name"] in {"health-quick", "find-label"}:
        return True
    if effect["kind"] == "Macro" and effect["name"] == "windows" and effect["argv"] == ["--rich"]:
        return True
    return False


def captured_failures(fixture, effects):
    result=[];reply_index=0
    for trace_index,effect in enumerate(effects):
        if effect["kind"] in NO_REPLY:continue
        if reply_index < len(fixture["replies"]):
            reply=fixture["replies"][reply_index]
            if isinstance(reply,dict) and "throw" in reply:
                result.append(dict(trace_index=trace_index,reply_index=reply_index,effect=effect,message=reply["throw"]))
        reply_index += 1
    return result


def first_difference(actual, expected, path="$"):
    if type(actual) is not type(expected):return f"{path}: {type(actual).__name__} != {type(expected).__name__}"
    if isinstance(actual,dict):
        for key,value in expected.items():
            if key not in actual:return f"{path}.{key}: missing"
            if actual[key]!=value:return first_difference(actual[key],value,f"{path}.{key}")
        for key in actual:
            if key not in expected:return f"{path}.{key}: unexpected"
    elif isinstance(actual,list):
        if len(actual)!=len(expected):return f"{path}: lengths {len(actual)} != {len(expected)}"
        for index,(left,right) in enumerate(zip(actual,expected)):
            if left!=right:return first_difference(left,right,f"{path}[{index}]")
    elif actual!=expected:return f"{path}: {repr(actual)[:240]} != {repr(expected)[:240]}"
    return None


ACCEPTED_GUARDS = [{'op': 'perf', 'kind': 'Clock', 'name': 'start', 'value': 'perf-sample'},
 {'op': 'benchmark', 'kind': 'Clock', 'name': 'stop', 'value': 'benchmark-sample'},
 {'op': 'log-tail', 'kind': 'Clock', 'name': 'elapsed', 'value': 'log-tail'},
 {'op': 'health-quick', 'kind': 'Timestamp', 'name': 'o'},
 {'op': 'health-detail', 'kind': 'NodeVersion'},
 {'op': 'self-test', 'kind': 'Cli', 'argv': ['observe', 'windows']},
 {'op': 'health-detail', 'kind': 'Cli', 'argv': ['version']},
 {'op': 'perf', 'kind': 'Cli', 'argv': ['observe', 'appshot', '--match', 'unlikely-perf-target-window']},
 {'op': 'perf', 'rest': ['--include-live-ish'], 'kind': 'Cli', 'argv': ['observe', 'appshot']},
 {'op': 'benchmark', 'kind': 'Native', 'argv': ['-Action', 'windows']},
 {'op': 'benchmark', 'kind': 'Native', 'argv': ['-Action', 'health']},
 {'op': 'benchmark', 'kind': 'Native', 'argv': ['-Action', 'focused']},
 {'op': 'benchmark', 'kind': 'Native', 'argv': ['-Action', 'modal-detect']},
 {'op': 'perf', 'kind': 'Macro', 'name': 'metrics'},
 {'op': 'perf', 'kind': 'Macro', 'name': 'windows', 'argv': ['--rich']},
 {'op': 'perf',
  'rest': ['--quick'],
  'kind': 'Macro',
  'name': 'find-label',
  'argv': ['--label', '__cucp_unlikely_label__', '--match', 'unlikely-perf-target-window', '--fast']},
 {'op': 'health-quick', 'kind': 'FileExists', 'value': 'C:\\fixture\\wrapper.log'},
 {'op': 'health-quick', 'kind': 'FileStat', 'value': 'C:\\fixture\\wrapper.log'},
 {'op': 'health-quick',
  'kind': 'ListFiles',
  'value': {'path': 'C:\\fixture\\cache', 'recurse': False, 'filter': None, 'file': True}},
 {'op': 'audit-summary',
  'kind': 'ListFiles',
  'value': {'path': 'C:\\fixture\\audit', 'recurse': True, 'filter': 'trajectory*.ndjson', 'file': False}},
 {'op': 'benchmark',
  'rest': ['--baseline', 'C:\\fixture\\baseline.json'],
  'kind': 'ReadText',
  'value': 'C:\\fixture\\baseline.json'},
 {'op': 'release-notes', 'kind': 'ResolvePath', 'value': 'C:\\fixture\\CHANGELOG.md'},
 {'op': 'health-quick',
  'kind': 'TailBytes',
  'value': {'path': 'C:\\fixture\\wrapper.log', 'max_bytes': 65536}},
 {'op': 'log-tail',
  'rest': ['--path', 'C:\\fixture\\custom.log', '--max-bytes', '123'],
  'kind': 'TailBytes',
  'value': {'path': 'C:\\fixture\\custom.log', 'max_bytes': 123}},
 {'op': 'health-quick', 'kind': 'AuditProbe', 'name': '.health-quick-probe-', 'value': 'C:\\fixture\\audit'},
 {'op': 'health-detail', 'kind': 'AuditProbe', 'name': '.health-probe-', 'value': 'C:\\fixture\\audit'},
 {'op': 'perf',
  'rest': ['--include-live-ish'],
  'kind': 'ClearAppshotCache',
  'name': 'appshot-*.json',
  'value': 'C:\\fixture\\cache'},
 {'op': 'health-quick', 'kind': 'EnsureWin32'},
 {'op': 'health-detail', 'kind': 'EnsureUia'},
 {'op': 'health-detail', 'kind': 'HelperUp'},
 {'op': 'health-detail', 'kind': 'FindCodex'},
 {'op': 'diagnose-lag', 'kind': 'Processes'},
 {'op': 'diagnose-lag', 'kind': 'Windows'},
 {'op': 'self-test',
  'kind': 'AssertAuthorized',
  'argv': ['act', 'click', '--x', '0', '--y', '0', '--after', 'fake']},
 {'op': 'self-test', 'kind': 'AssertAuthorized', 'argv': ['act', 'click', '--x', '100', '--y', '100']},
 {'op': 'self-test',
  'kind': 'Appshot',
  'value': {'match': 'selftest-cache', 'semantic': False, 'no_cache': True, 'cache_max_seconds': None}},
 {'op': 'self-test',
  'kind': 'Appshot',
  'value': {'match': 'selftest-cache', 'semantic': False, 'no_cache': False, 'cache_max_seconds': 600}},
 {'op': 'self-test',
  'rest': ['--deep'],
  'kind': 'Appshot',
  'value': {'match': '', 'semantic': True, 'no_cache': True, 'cache_max_seconds': None}},
 {'op': 'self-test', 'kind': 'CacheKey', 'value': 'selftest-cache'},
 {'op': 'self-test', 'rest': ['--deep'], 'kind': 'Uia', 'value': {'focused_window': '', 'max_elements': 50}}]

DENIED_GUARDS = [{'op': 'benchmark', 'kind': 'Native', 'argv': ['-Action', 'click']},
 {'op': 'benchmark', 'kind': 'Native', 'argv': ['-Action', 'Windows']},
 {'op': 'benchmark', 'kind': 'Native', 'argv': ['-Action', 'windows', '-OutPath', 'C:\\unowned']},
 {'op': 'perf', 'kind': 'Native', 'argv': ['-Action', 'windows']},
 {'op': 'health-detail', 'kind': 'Cli', 'argv': ['observe', 'context']},
 {'op': 'self-test', 'kind': 'Cli', 'argv': ['act', 'click']},
 {'op': 'self-test', 'kind': 'Cli', 'argv': ['Version']},
 {'op': 'self-test', 'kind': 'Cli', 'argv': ['version', '--output', 'C:\\unowned']},
 {'op': 'perf', 'rest': ['--quick'], 'kind': 'Cli', 'argv': ['health']},
 {'op': 'perf', 'kind': 'Cli', 'argv': ['observe', 'appshot']},
 {'op': 'perf', 'kind': 'Macro', 'name': 'click-point', 'argv': ['--x', '1', '--y', '1']},
 {'op': 'perf', 'kind': 'Macro', 'name': 'Metrics'},
 {'op': 'perf', 'kind': 'Macro', 'name': 'metrics', 'argv': ['--live']},
 {'op': 'perf', 'kind': 'Macro', 'name': 'windows', 'argv': ['--match', 'real-window']},
 {'op': 'perf', 'rest': ['--quick'], 'kind': 'Macro', 'name': 'windows', 'argv': ['--rich']},
 {'op': 'perf',
  'kind': 'Macro',
  'name': 'find-label',
  'argv': ['--label', 'real-label', '--match', 'unlikely-perf-target-window', '--fast']},
 {'op': 'health-quick', 'kind': 'Macro', 'name': 'metrics'},
 {'op': 'health-quick', 'kind': 'FileExists', 'value': 'C:\\unowned\\wrapper.log'},
 {'op': 'health-quick', 'kind': 'FileStat', 'value': 'C:\\fixture\\WRAPPER.log'},
 {'op': 'health-quick', 'kind': 'FileStat', 'value': 12},
 {'op': 'health-quick',
  'kind': 'ListFiles',
  'value': {'path': 'C:\\fixture\\cache', 'recurse': True, 'filter': None, 'file': True}},
 {'op': 'audit-summary',
  'kind': 'ListFiles',
  'value': {'path': 'C:\\fixture\\audit', 'recurse': True, 'filter': '*', 'file': False}},
 {'op': 'health-quick',
  'kind': 'ListFiles',
  'value': {'path': 'C:\\fixture\\cache', 'recurse': 'false', 'filter': None, 'file': True}},
 {'op': 'health-quick',
  'kind': 'ListFiles',
  'value': {'path': 'C:\\fixture\\cache', 'recurse': False, 'filter': None, 'file': True, 'extra': 1}},
 {'op': 'audit-summary', 'kind': 'ReadLines', 'value': 'C:\\unowned\\trajectory.ndjson'},
 {'op': 'release-notes', 'kind': 'ReadLines', 'value': 'C:\\fixture\\CHANGELOG.md'},
 {'op': 'benchmark',
  'rest': ['--baseline', 'C:\\fixture\\baseline.json'],
  'kind': 'ReadText',
  'value': 'C:\\unowned\\baseline.json'},
 {'op': 'release-notes', 'kind': 'ResolvePath', 'value': 'C:\\unowned\\CHANGELOG.md'},
 {'op': 'health-quick',
  'kind': 'TailBytes',
  'value': {'path': 'C:\\fixture\\wrapper.log', 'max_bytes': 65537}},
 {'op': 'health-quick',
  'kind': 'TailBytes',
  'value': {'path': 'C:\\fixture\\wrapper.log', 'max_bytes': '65536'}},
 {'op': 'log-tail',
  'rest': ['--path', 'C:\\fixture\\custom.log'],
  'kind': 'TailBytes',
  'value': {'path': 'C:\\fixture\\wrapper.log', 'max_bytes': 262144}},
 {'op': 'health-quick', 'kind': 'AuditProbe', 'name': '.health-quick-probe-', 'value': 'C:\\unowned\\audit'},
 {'op': 'health-quick', 'kind': 'AuditProbe', 'name': '.health-probe-', 'value': 'C:\\fixture\\audit'},
 {'op': 'health-detail', 'kind': 'AuditProbe', 'name': '..\\escape-', 'value': 'C:\\fixture\\audit'},
 {'op': 'perf', 'kind': 'ClearAppshotCache', 'name': 'appshot-*.json', 'value': 'C:\\fixture\\cache'},
 {'op': 'perf',
  'rest': ['--include-live-ish'],
  'kind': 'ClearAppshotCache',
  'name': '*',
  'value': 'C:\\fixture\\cache'},
 {'op': 'perf',
  'rest': ['--include-live-ish'],
  'kind': 'ClearAppshotCache',
  'name': 'appshot-*.json',
  'value': 'C:\\unowned\\cache'},
 {'op': 'self-test',
  'kind': 'Appshot',
  'value': {'match': 'real-window', 'semantic': False, 'no_cache': True, 'cache_max_seconds': None}},
 {'op': 'self-test',
  'kind': 'Appshot',
  'value': {'match': '', 'semantic': True, 'no_cache': True, 'cache_max_seconds': None}},
 {'op': 'self-test',
  'kind': 'Appshot',
  'value': {'match': 'selftest-cache', 'semantic': False, 'no_cache': 'true', 'cache_max_seconds': None}},
 {'op': 'self-test',
  'kind': 'Appshot',
  'value': {'match': 'selftest-cache', 'semantic': False, 'no_cache': False, 'cache_max_seconds': '600'}},
 {'op': 'self-test', 'kind': 'CacheKey', 'value': '..\\escape'},
 {'op': 'self-test', 'kind': 'Uia', 'value': {'focused_window': '', 'max_elements': 50}},
 {'op': 'self-test',
  'rest': ['--deep'],
  'kind': 'Uia',
  'value': {'focused_window': 'real-window', 'max_elements': 50}},
 {'op': 'self-test', 'kind': 'AssertAuthorized', 'argv': ['act', 'click', '--x', '1', '--y', '1']}]


# Guard cases and assertions are Python data/code. The PowerShell fixture only
# invokes the actual Windows boundary and reports raw observations.
GUARD_CONTEXT = dict(audit_directory=r'C:\fixture\audit', cache_directory=r'C:\fixture\cache',
    wrapper_log=r'C:\fixture\wrapper.log', cli_path=r'C:\fixture\cli.mjs',
    changelog_path=r'C:\fixture\CHANGELOG.md', temp_root=r'C:\fixture\temp',
    benchmark_schema='cucp.benchmark/v1', release_schema='cucp.release-notes/v1')
GUARD_GROUP_COUNTS = dict(accepted=40, general=37, constrained=45, bounded=13,
    ordinals=18, payload=15, getters=14, paths=13, owned=1)
GUARD_OLD_BLOB = 'cba1ae30ad482b5271faf7617e95113ea537fcce'


def encode_guard_wire(value):
    if isinstance(value, dict):
        return dict(kind='object', properties=[dict(name=k, value=encode_guard_wire(v)) for k,v in value.items()])
    if isinstance(value, list):return dict(kind='array', items=[encode_guard_wire(v) for v in value])
    return dict(kind='scalar', value=value)


def guard_effect(kind='NodeVersion', name='', value=None, argv=None):
    return dict(kind='Diagnostic', name=kind, argv=[] if argv is None else argv,
        data=encode_guard_wire(dict(name=name,value=value)), live=False,quiet=False,brief=False,confirm_sensitive=False)


def diagnostic_guard_cases():
    from copy import deepcopy
    result=[]
    def add(name,group,mode='validate',op='health-quick',rest=None,**extra):
        row=dict(id=len(result)+1,name=name,group=group,mode=mode,op=op,
            rest=rest or [],context=deepcopy(GUARD_CONTEXT),expected_state='ok',**extra)
        result.append(row);return row
    def validate(name,group,effect=None,accept=False,**extra):
        return add(name,group,steps=[dict(action='effect',effect=effect or guard_effect())],
            expected_steps=['ok' if accept else 'error'],**extra)
    def literal(item):return guard_effect(item['kind'],item.get('name',''),item.get('value'),item.get('argv',[]))
    def sequence(name,group,effects,statuses,**extra):
        return add(name,group,steps=[dict(action='effect',effect=e) if e is not None else dict(action='snapshot') for e in effects],expected_steps=statuses,**extra)
    for item in ACCEPTED_GUARDS:
        validate('accept '+item['op']+'/'+item['kind']+'/'+item.get('name',''),'accepted',literal(item),True,op=item['op'],rest=item.get('rest'))
    row=add('reject unknown invocation operation','general',op='health-Quick',steps=[])
    row['expected_state']='error'
    add('state captures independent context and argv copies','general','state-copy','perf',['--quick'],
        changed_cache=r'C:\unowned',changed_arg='--include-live-ish')
    for value in ('Unknown','diagnostic','DIAGNOSTIC','Native','Child'):
        effect=guard_effect();effect['kind']=value
        validate('reject outer kind '+value,'general',effect)
    for value in ('Unknown','nodeversion','NODEVERSION','RemoveFile','SendEscape'):
        validate('reject diagnostic kind '+value,'general',guard_effect(value))
    for flag in ('live','quiet','brief','confirm_sensitive'):
        for value,prefix in ((True,'reject authority flag '),('false','reject nonboolean flag ')):
            effect=guard_effect();effect[flag]=value;validate(prefix+flag,'general',effect)
    effect=guard_effect();effect.update(live=True,confirm_sensitive=True)
    validate('diagnostic family independently forbids elevated startup authority','general',effect,seed=dict(live=True,sensitive=True))
    outer=(('extra outer field','path',r'C:\unowned'),('absent outer field','brief',None),
        ('wrong typed outer kind','kind',7),('wrong typed outer name','name',7),('scalar argv','argv','version'))
    for name,key,value in outer:
        effect=guard_effect()
        if name=='absent outer field':del effect[key]
        else:effect[key]=value
        validate('reject '+name,'general',effect)
    validate('reject nonstring argv item','general',guard_effect('Cli',argv=[12]),op='self-test')
    for name,data in (('extra diagnostic data field',dict(name='',value=None,path=r'C:\unowned')),
        ('absent diagnostic data field',dict(name='')),('wrong typed diagnostic suboperation',dict(name=7,value=None))):
        effect=guard_effect();effect['data']=encode_guard_wire(data);validate('reject '+name,'general',effect)
    effect=guard_effect();effect['data']=dict(name='',value=None);validate('reject untagged diagnostic data','general',effect)
    effect=guard_effect();effect['data']['kind']='Object';validate('reject case shifted wire tag','general',effect)
    effect=guard_effect();effect['data']['extra']=1;validate('reject extra wire field','general',effect)
    effect=guard_effect();effect['data']['properties'].append(deepcopy(effect['data']['properties'][0]));validate('reject duplicate wire property','general',effect)
    validate('reject unexpected suboperation','general',guard_effect(name='version'))
    validate('reject unexpected argv','general',guard_effect(argv=['--anything']))
    validate('reject null-only payload changed','general',guard_effect(value='node'))
    for item in DENIED_GUARDS:
        validate('reject constrained '+item['op']+'/'+item['kind']+'/'+str(len(result)),'constrained',literal(item),op=item['op'],rest=item.get('rest'))
    repeated=[ACCEPTED_GUARDS[i] for i in (24,26,18,22,38,21,35)]
    for item in repeated:
        sequence('reject repeated owned effect '+item['kind'],'bounded',[literal(item),literal(item)],['ok','error'],op=item['op'],rest=item.get('rest'))
    sequence('native count is bounded by immutable iters','bounded',[guard_effect('Native',argv=['-Action','windows'])]*2,['ok','error'],op='benchmark',rest=['--iters','1'])
    sequence('macro count is bounded by immutable iters','bounded',[guard_effect('Macro',name='metrics')]*2,['ok','error'],op='perf',rest=['--iters','1'])
    sequence('cold appshot CLI count allows exactly two batches','bounded',[guard_effect('Cli',argv=['observe','appshot'])]*3,['ok','ok','error'],op='perf',rest=['--iters','1','--include-live-ish'])
    audit=r'C:\fixture\audit\trajectory.ndjson';resolved=r'C:\fixture\resolved\CHANGELOG.md';cache=r'C:\fixture\cache\appshot-fixture.json'
    sequence('audit lines require exact retained acquisition','bounded',[guard_effect('ReadLines',value=audit),guard_effect('ReadLines',value=r'C:\fixture\audit\other.ndjson')],['ok','error'],op='audit-summary',seed=dict(audit_files=[audit]))
    sequence('release lines require resolved retained path','bounded',[guard_effect('ReadLines',value=resolved),guard_effect('ReadLines',value=GUARD_CONTEXT['changelog_path'])],['ok','error'],op='release-notes',seed=dict(changelog=resolved))
    sequence('self-test file probe requires generated cache path','bounded',[guard_effect('FileExists',value=cache),guard_effect('FileExists',value=r'C:\fixture\cache\appshot-other.json')],['ok','error'],op='self-test',seed=dict(cache_path=cache))
    metric_seed=dict(rows=[[dict(id=42),dict(id=9),dict(id=42)],[dict(id=9,name='node'),dict(id=77,name='chrome'),dict(id=42,name='codex')]],order=[2,0,1],counts={'processor-count':1})
    def metric(current=2,previous=2):return guard_effect('ProcessMetrics',value=dict(current_ordinal=current,previous_ordinal=previous))
    sequence('metrics accept grouped order and last duplicate previous ID','ordinals',[metric(),metric(0,1),metric(1,None),metric(1,None)],['ok','ok','ok','error'],op='diagnose-lag',seed=deepcopy(metric_seed),expected_cursors=[1,2,3,3])
    invalid=[dict(current_ordinal=c,previous_ordinal=p) for c,p in ((-1,2),(3,2),(0,1),('2',2),(2,'2'),(2,0),(2,-1),(2,3),(2,None))]
    invalid += [dict(current_ordinal=2,previous_ordinal=2,pid=42),dict(current_ordinal=2)]
    for value in invalid:
        validate('reject ordinal contract '+str(len(result)),'ordinals',guard_effect('ProcessMetrics',value=value),op='diagnose-lag',seed=deepcopy(metric_seed),expected_cursors=[0])
    validate('metrics reject missing snapshots','ordinals',metric(0,None),op='diagnose-lag')
    seed=deepcopy(metric_seed);seed['counts']={}
    validate('metrics reject missing processor count','ordinals',metric(),op='diagnose-lag',seed=seed)
    seed=deepcopy(metric_seed);seed['cursor']=2
    validate('metrics reject invented previous for new process','ordinals',metric(1,0),op='diagnose-lag',seed=seed)
    sequence('metrics reject repeated current ordinal before exhaustion','ordinals',[metric(),metric()],['ok','error'],op='diagnose-lag',seed=deepcopy(metric_seed))
    sequence('snapshot sequence requires sampling delay','ordinals',[guard_effect('Processes'),None,guard_effect('Processes'),guard_effect('Sleep',value=3000),guard_effect('Processes'),None,guard_effect('ProcessorCount'),guard_effect('ProcessorCount'),guard_effect('Processes')],['ok','error','ok','ok','ok','error','error'],op='diagnose-lag')
    sequence('sampling delay rejects changed value and repeated effect','ordinals',[guard_effect('Sleep',value=v) for v in (101,'100',100,100)],['error','error','ok','error'],op='diagnose-lag',rest=['--sample-ms','100'],seed=dict(rows=[[]]))
    def payload(name,op,data,rule=None,reject=False):
        row=add(name,'payload','payload',op,payload=data,rule=rule)
        if reject:row['expected_state']='error'
    payload('audit completion converts only operation-owned counter maps','audit-summary',dict(schema='cucp.audit-summary/v1',by_macro=dict(perf=2),by_exit_code={'0':2},unrelated=dict(stay='object')),'audit')
    payload('lag completion restores each priority Hashtable','diagnose-lag',dict(schema='cucp.diagnose-lag/v1',processes=[dict(priority_classes=dict(Normal=2),unrelated=dict(a=1)),dict(priority_classes={})]),'lag')
    payload('other operations cannot claim audit formatting through schema or annotations','perf',dict(schema='cucp.audit-summary/v1',by_macro=dict(perf=2),by_exit_code={'0':2},format_paths=['by_macro','by_exit_code'],hashtable_paths=['by_macro']),'unclaimed')
    payload('audit annotation cannot convert arbitrary nested object','audit-summary',dict(schema='cucp.audit-summary/v1',by_macro={},by_exit_code={},arbitrary=dict(nested=dict(v=1)),hashtable_paths=['arbitrary.nested']),'nested')
    for value in (None,'text',12,[1,2]):
        payload('reject malformed audit counter '+str(len(result)),'audit-summary',dict(schema='cucp.audit-summary/v1',by_macro=value,by_exit_code={}),reject=True)
        payload('reject malformed lag priority map '+str(len(result)),'diagnose-lag',dict(schema='cucp.diagnose-lag/v1',processes=[dict(priority_classes=value)]),reject=True)
    payload('audit completion rejects wrong schema','audit-summary',dict(schema='cucp.diagnose-lag/v1'),reject=True)
    payload('lag completion rejects scalar processes','diagnose-lag',dict(schema='cucp.diagnose-lag/v1',processes=dict(priority_classes={})),reject=True)
    payload('lag completion permits empty process array','diagnose-lag',dict(schema='cucp.diagnose-lag/v1',processes=[]),'empty')
    def process(failures=(),nulls=(),kind='Utc',text='2024-01-02 03:04:05'):
        return dict(failures=list(failures),nulls=list(nulls),start=dict(kind=kind,text=text))
    def getters(name,rule,current=None,previous=True):
        return add(name,'getters','metrics','diagnose-lag',current=current or process(),previous=process() if previous is True else previous,rule=rule)
    getters('native metrics retain original getter order and values','values')
    getters('new process does not read either CPU getter','new',previous=None)
    for failed in ('memory','start','cpu','priority','previous-cpu'):
        getters('independent inaccessible getter '+failed,failed,current=process(failures=[failed] if failed!='previous-cpu' else []),previous=process(failures=['cpu'] if failed=='previous-cpu' else []))
    getters('null getters preserve PowerShell casts and independent reads','nulls',current=process(nulls=['memory','start','priority']))
    getters('null CPU getter does not prevent priority getter','null-cpu',current=process(nulls=['cpu']))
    for kind in ('Utc','Local','Unspecified'):
        getters('start timestamp preserves DateTimeKind '+kind,'date-kind',current=process(kind=kind),previous=None)
    for offset in ('+05:30','-07:00'):
        getters('start timestamp preserves explicit offset '+offset,'offset',current=process(kind='offset',text='2024-01-02T03:04:05.0000000'+offset),previous=None)
    def entry(path,attributes=16,container=True):return dict(FullName=path,Attributes=attributes,PSIsContainer=container)
    entries=[entry(path) for path in ('C:\\',r'C:\fixture',r'C:\fixture\audit',r'C:\fixture\cache')]
    def pathcase(name,action,path=r'C:\fixture\audit',reject=False,**extra):
        row=add(name,'paths','captured-path',action=action,path=path,entries=deepcopy(entries),cache_entries=[],**extra)
        if reject:row['expected_state']='error'
        return row
    pathcase('owned root checks every existing ancestor','root',rule='ancestors')
    pathcase('owned path equality tolerates case and trailing separators','equal','C:\\FiXtUrE\\CACHE\\',other=r'c:\fixture\cache',rule='equality')
    for spelling in (r'C:\FIXTURE\AUDIT','c:\\FiXtUrE\\AuDiT\\'):
        pathcase('captured probe normalizes owned spelling '+spelling,'probe',spelling,prefix='.health-probe-',rule='normalized')
    pathcase('owned root rejects relative path','root',r'.\audit',True,rule='relative')
    for path in (r'C:\fixture\audit',r'C:\fixture','C:\\'):
        row=pathcase('audit probe rejects reparse ancestor '+path,'probe',reject=True,prefix='.health-quick-probe-',rule='no-mutation')
        next(e for e in row['entries'] if e['FullName']==path)['Attributes']=16|1024
    pathcase('audit probe captures exactly one owned write and removal','probe',prefix='.health-quick-probe-',rule='write-remove')
    row=pathcase('missing audit directory creation is captured','probe',prefix='.health-probe-',rule='create')
    row['entries']=[e for e in row['entries'] if e['FullName']!=r'C:\fixture\audit']
    row=pathcase('cache cleanup removes only retained regular owned files','clear',r'C:\fixture\cache',rule='remove-regular')
    row['cache_entries']=[entry(r'C:\fixture\cache\appshot-safe.json',128,False),entry(r'C:\fixture\cache\appshot-directory.json'),entry(r'C:\fixture\cache\appshot-link.json',1024,False)]
    row=pathcase('cache cleanup rejects escaped entry before removal','clear',r'C:\fixture\cache',True,rule='escaped')
    row['cache_entries']=[entry(r'C:\fixture\other\appshot-escape.json',128,False)]
    row=pathcase('cache cleanup rejects reparse root before enumeration','clear',r'C:\fixture\cache',True,rule='reparse-cache')
    next(e for e in row['entries'] if e['FullName']==r'C:\fixture\cache')['Attributes']=16|1024
    add('actual disposable owned helpers preserve unrelated files and reparse targets','owned','actual-owned')
    return result



def guard_requests(row):
    """Flatten inert boundary requests without sending expectations to PowerShell."""
    from copy import deepcopy
    descriptor={key:deepcopy(value) for key,value in row.items()
        if key not in {'name','group','rule'} and not key.startswith('expected_')}
    if row.get('rule')=='equality':
        pairs=[(row['path'],row['other']), (r'C:\fixture\cache-other',r'C:\fixture\cache'),
            (r'C:\fixture\cache\child',r'C:\fixture\cache')]
        return [{**descriptor,'id':f"{row['id']}/{i}",'path':left,'other':right} for i,(left,right) in enumerate(pairs)]
    return [descriptor]


def run_guard_driver(test, requests):
    with tempfile.TemporaryDirectory(prefix='cucp-diagnostic-driver-') as temporary:
        inputs=Path(temporary)/'cases.json'
        inputs.write_text(json.dumps(requests,ensure_ascii=False),encoding='utf-8-sig')
        command=[shutil.which('powershell.exe'),'-NoProfile','-NonInteractive','-File',str(GUARDS),
            '-BridgeSource',str(BRIDGE),'-AdapterSource',str(ADAPTER),'-InputPath',str(inputs)]
        process=subprocess.run(command,capture_output=True,timeout=180)
    test.assertEqual(process.returncode,0,process.stderr.decode(errors='replace'))
    result=json.loads(process.stdout.decode('utf-8-sig'))
    test.assertIsInstance(result,list)
    test.assertEqual([r['id'] for r in result],[r['id'] for r in requests])
    return result


def assert_guard_observations(test,row,results):
    result=results[0];mode=row['mode'];rule=row.get('rule')
    for observed in results:
        test.assertEqual(observed['state'],row['expected_state'],observed)
        if observed['state']=='error':test.assertIsInstance(observed['error'],str);test.assertTrue(observed['error'])
        else:test.assertIsNone(observed['error'])
    value=result['value']
    if mode=='validate' and row['expected_state']=='ok':
        steps=value['steps']
        test.assertEqual([v['state'] for v in steps],row['expected_steps'],steps)
        for step in steps:
            if step['state']=='ok':
                test.assertEqual(step['wire_kind'],'object')
                test.assertEqual(step['decoded_fields'],['name','value'])
                test.assertIsNone(step['error'])
            else:test.assertIsInstance(step['error'],str);test.assertTrue(step['error'])
        if 'expected_cursors' in row:test.assertEqual([v['cursor'] for v in steps],row['expected_cursors'])
    elif mode=='state-copy':
        test.assertEqual(value['context'],GUARD_CONTEXT)
        test.assertEqual(value['rest'],['--quick'])
    elif mode=='payload' and row['expected_state']=='ok':
        # Preserve every value, container shape, specific .NET map type and the
        # retained object's reference identity. Caller paths confer no authority.
        test.assertEqual(value['payload'],row['payload'])
        test.assertTrue(value['same_reference'])
        types=value['types']
        if rule=='audit':
            test.assertEqual(types['$.by_macro'],'hashtable');test.assertEqual(types['$.by_exit_code'],'hashtable')
            test.assertEqual(types['$.unrelated'],'object')
        elif rule=='lag':
            for i in (0,1):test.assertEqual(types[f'$.processes[{i}].priority_classes'],'hashtable')
            test.assertEqual(types['$.processes[0].unrelated'],'object')
        elif rule=='unclaimed':
            test.assertEqual(types['$.by_macro'],'object');test.assertEqual(types['$.by_exit_code'],'object')
        elif rule=='nested':test.assertEqual(types['$.arbitrary.nested'],'object')
        elif rule=='empty':test.assertEqual(types['$.processes'],'array')
        else:test.fail('Unknown payload assertion rule '+str(rule))
    elif mode=='metrics':
        metrics=value['metrics'];events=result['events']
        full=['current.memory','current.start','current.cpu','previous.cpu','current.priority']
        expected=full if row['previous'] is not None else ['current.memory','current.start','current.priority']
        if rule=='cpu':test.assertIn(events,[full,['current.memory','current.start','current.cpu','current.priority']])
        else:test.assertEqual(events,expected)
        standard=dict(private_bytes=4096,started_at='2024-01-02T03:04:05.0000000Z',current_cpu_ms=2300,previous_cpu_ms=1200,priority='Normal')
        if rule=='values':test.assertEqual(metrics,standard)
        elif rule=='new':test.assertEqual(metrics,{k:v for k,v in standard.items() if k not in {'current_cpu_ms','previous_cpu_ms'}})
        elif rule in {'memory','start','cpu','priority','previous-cpu'}:
            for key,failed in (('private_bytes','memory'),('started_at','start'),('priority','priority')):
                if rule!=failed:test.assertEqual(metrics[key],standard[key])
            if rule not in {'cpu','previous-cpu'}:
                test.assertEqual(metrics['current_cpu_ms'],2300);test.assertEqual(metrics['previous_cpu_ms'],1200)
        elif rule=='nulls':
            test.assertEqual(metrics,dict(private_bytes=0,current_cpu_ms=2300,previous_cpu_ms=1200,priority=''))
        elif rule=='null-cpu':
            test.assertEqual(metrics.get('current_cpu_ms'),None)
            test.assertEqual(metrics['previous_cpu_ms'],1200);test.assertEqual(metrics['priority'],'Normal')
        elif rule in {'date-kind','offset'}:
            test.assertEqual(metrics['started_at'],value['source_start'])
            kind=row['current']['start']['kind']
            if kind=='Unspecified':test.assertEqual(metrics['started_at'],'2024-01-02T03:04:05.0000000')
            elif kind=='Utc':test.assertEqual(metrics['started_at'],'2024-01-02T03:04:05.0000000Z')
            elif kind=='Local':test.assertRegex(metrics['started_at'],r'^2024-01-02T03:04:05\.0000000[+-]\d\d:\d\d$')
            else:test.assertEqual(metrics['started_at'],row['current']['start']['text'])
        else:test.fail('Unknown getter assertion rule '+str(rule))
    elif mode=='captured-path':
        events=result['events'];select=lambda command:[e for e in events if e['command']==command]
        # Former assertions inside stub cmdlets also remain explicit here.
        for event in select('Get-ChildItem'):
            test.assertEqual(event,dict(command='Get-ChildItem',path=r'C:\fixture\cache',filter='appshot-*.json'))
        for event in select('New-Item'):
            test.assertEqual(event,dict(command='New-Item',path=r'C:\fixture\audit',item_type='Directory'))
        if rule=='ancestors':
            test.assertEqual(value,r'C:\fixture\audit')
            test.assertEqual([e['path'] for e in select('Get-Item')],[r'C:\fixture\audit',r'C:\fixture','C:\\',r'C:\fixture\audit'])
        elif rule=='equality':test.assertEqual([r['value'] for r in results],[True,False,False])
        elif rule=='normalized':
            writes=select('Set-Content');test.assertEqual(len(writes),1)
            test.assertTrue(writes[0]['path'].startswith('C:\\fixture\\audit\\'))
        elif rule=='relative':test.assertEqual(events,[])
        elif rule=='no-mutation':test.assertEqual([e for e in events if e['command'] in {'New-Item','Set-Content','Remove-Item'}],[])
        elif rule=='write-remove':
            writes=select('Set-Content');removes=select('Remove-Item')
            test.assertEqual(len(writes),1);test.assertEqual(len(removes),1)
            test.assertEqual(writes[0]['path'],removes[0]['path'])
            test.assertRegex(writes[0]['path'],r'^C:\\fixture\\audit\\\.health-quick-probe-[0-9a-f-]{36}$')
            test.assertEqual(writes[0]['value'],'ok');test.assertEqual(writes[0]['encoding'],'UTF8')
        elif rule=='create':test.assertEqual(len(select('New-Item')),1)
        elif rule=='remove-regular':test.assertEqual(select('Remove-Item'),[dict(command='Remove-Item',path=r'C:\fixture\cache\appshot-safe.json')])
        elif rule=='escaped':test.assertEqual(select('Remove-Item'),[])
        elif rule=='reparse-cache':test.assertEqual([e for e in events if e['command'] in {'Get-ChildItem','Remove-Item'}],[])
        else:test.fail('Unknown path assertion rule '+str(rule))


def assert_owned_guard_files(test,row):
    import stat
    import uuid
    root=None;junction=None
    with tempfile.TemporaryDirectory(prefix='cucp-diagnostic-guards-') as temporary:
        root=Path(temporary);nonce=uuid.uuid4().hex
        (root/'.fixture-owner').write_text(nonce,encoding='utf-8')
        audit=root/'audit';cache=root/'cache';target=root/'junction-target'
        for directory in (audit,cache,target):directory.mkdir()
        unrelated=cache/'preserve.txt';unrelated.write_text('unrelated fixture',encoding='utf-8')
        regular=cache/'appshot-owned.json';regular.write_text('{}',encoding='utf-8')
        matching_directory=cache/'appshot-directory.json';matching_directory.mkdir()
        directory_child=matching_directory/'preserve.txt';directory_child.write_text('directory fixture',encoding='utf-8')
        target_child=target/'preserve.txt';target_child.write_text('junction target fixture',encoding='utf-8')
        junction=cache/'appshot-junction.json'
        test.assertFalse(junction.exists())
        def invoke(action,expected='ok'):
            request=dict(id=f"{row['id']}/{action}",mode='actual-owned',root=str(root),nonce=nonce,action=action)
            observed=run_guard_driver(test,[request])[0]
            test.assertEqual(observed['state'],expected,observed)
            if expected=='error':test.assertIsInstance(observed['error'],str);test.assertTrue(observed['error'])
            else:test.assertIsNone(observed['error'])
            return observed
        try:
            observed=invoke('junction')
            test.assertTrue(observed['value'] & stat.FILE_ATTRIBUTE_REPARSE_POINT)
            test.assertTrue(junction.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
            for action in ('probe','probe-upper','probe-trailing'):
                invoke(action);test.assertEqual(list(audit.iterdir()),[])
            invoke('probe-escape','error')
            test.assertEqual(list(target.iterdir()),[target_child])
            test.assertEqual(target_child.read_text(encoding='utf-8'),'junction target fixture')
            invoke('root-junction','error')
            invoke('clear-upper')
            test.assertFalse(regular.exists())
            test.assertEqual(unrelated.read_text(encoding='utf-8'),'unrelated fixture')
            test.assertTrue(matching_directory.is_dir())
            test.assertEqual(directory_child.read_text(encoding='utf-8'),'directory fixture')
            test.assertTrue(junction.is_dir())
            test.assertTrue(junction.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
            test.assertEqual(target_child.read_text(encoding='utf-8'),'junction target fixture')
        finally:
            # Remove this test-created junction non-recursively before stdlib
            # TemporaryDirectory cleanup. Never traverse its target for cleanup.
            if os.path.lexists(junction):os.rmdir(junction)
    test.assertFalse(root.exists())


class DiagnosticAdapterPortableTests(unittest.TestCase):
    def test_manifest_selects_current_public_entries_and_retained_boundaries(self):
        with tempfile.TemporaryDirectory(prefix='cucp-diagnostic-mode-') as temporary:
            root=Path(temporary);(root/'.github').mkdir();manifest=root/'.github/migration-adapters.json'
            self.assertEqual(KNOWN_ADAPTER_FAMILIES,('execution','precision','cdp','interaction','diagnostics','file-images'))
            for mask in range(1 << len(KNOWN_ADAPTER_FAMILIES)):
                selected=[name for index,name in enumerate(KNOWN_ADAPTER_FAMILIES) if mask & (1 << index)]
                manifest.write_text(json.dumps(dict(test_adapters=selected)),encoding='utf-8')
                self.assertEqual(diagnostic_adapter_mode(root),'production' if 'diagnostics' in selected else 'draft')
            invalid=[None,True,17,'test_adapters',[],[{}],{},
                {'test_adapters':[],'extra':True}]
            invalid += [dict(test_adapters=value) for value in (None,False,3,'diagnostics',{},
                [True],[1],[None],[[]],[{}],['unknown'],['Diagnostics'],['diagnostics','diagnostics'],['cdp','cdp'])]
            for value in invalid:
                with self.subTest(manifest=value):
                    manifest.write_text(json.dumps(value),encoding='utf-8')
                    with self.assertRaises(ValueError):diagnostic_adapter_mode(root)
        pinned=Path('pinned-original.ps1')
        for mode in ('draft','production'):
            arguments=actual_adapter_arguments(pinned,mode)
            self.assertEqual(arguments[arguments.index('-Source')+1],str(BRIDGE if mode=='production' else pinned))
            self.assertEqual('-ProductionEntry' in arguments,mode=='production')
            for operation in MIGRATED_DIAGNOSTICS:self.assertTrue(diagnostic_uses_session(operation,mode))
            for operation in RETAINED_DIAGNOSTICS:self.assertEqual(diagnostic_uses_session(operation,mode),mode=='draft')
        self.assertEqual(len(MIGRATED_DIAGNOSTICS),7)
        for name in ('file','runtime'):
            source=(ROOT/f'tests/fixtures/legacy-diagnostics-{name}-oracle.ps1').read_text(encoding='utf-8-sig')
            self.assertIn('[switch]$ProductionEntry',source)
            self.assertIn('Production entries must come from current main with support hooks',source)
            self.assertIn('if($ProductionEntry){& $',source)
            self.assertIn('Fixture-ValidatePublicDelegate $',source)
            self.assertIn('elseif($AdapterSource){_Invoke-LegacyDiagnosticFamily',source)

    def test_guard_inventory_preserves_all_196_original_checks(self):
        from collections import Counter
        inventory=diagnostic_guard_cases()
        self.assertEqual(len(inventory),196)
        self.assertEqual(Counter(row['group'] for row in inventory),GUARD_GROUP_COUNTS)
        identities=[[row['id'],row['name']] for row in inventory]
        digest=hashlib.sha256(json.dumps(identities,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        self.assertEqual(digest,'3aa0794743a65d25937d7d9778c90a7dd0e413e5763f7e97da03e333cc21c2c3')
        # This digest records the separately expanded original blob inventory.
        # Exact IDs disambiguate original duplicate names; no floor can hide loss.
        requests=[request for row in inventory if row['mode']!='actual-owned' for request in guard_requests(row)]
        self.assertEqual(len(requests),197)
        self.assertEqual(len({str(r['id']) for r in requests}),197)
        self.assertEqual(json.loads(json.dumps(requests)),requests)
        equality=next(row for row in inventory if row.get('rule')=='equality')
        self.assertEqual([r['path'] for r in guard_requests(equality)],
            ['C:\\FiXtUrE\\CACHE\\',r'C:\fixture\cache-other',r'C:\fixture\cache\child'])
        for request in requests:
            self.assertNotIn('rule',request)
            self.assertFalse(any(k.startswith('expected_') for k in request))
    def test_guard_driver_contains_only_closed_native_boundaries(self):
        source=GUARDS.read_text(encoding='utf-8-sig')
        self.assertNotIn('function Check(',source)
        self.assertNotIn('function Assert(',source)
        self.assertNotIn('$accepted=',source)
        self.assertNotIn('$denied=',source)
        self.assertIn('Loaded helper did not resolve captured leaves',source)
        self.assertIn('Captured and actual owned fixture modes cannot be mixed',source)
        self.assertIn('Disposable fixture ownership mismatch',source)
        self.assertIn('[scriptblock]::Create($definitions[0].Extent.Text)',source)
        for forbidden in ('Invoke-Expression','Start-Process','Get-Process','Invoke-NativeHelper','Invoke-Cucp','Remove-FixtureTree'):
            self.assertNotIn(forbidden,source)
    def test_windows_source_is_explicit_utf8(self):
        for path in (ADAPTER,GUARDS,ROOT/"tests/fixtures/legacy-diagnostics-file-oracle.ps1",ROOT/"tests/fixtures/legacy-diagnostics-runtime-oracle.ps1"):
            self.assertTrue(path.read_bytes().startswith(b"\xef\xbb\xbf"),str(path))
            path.read_bytes()[3:].decode("utf-8",errors="strict")
    def test_adapter_reuses_one_transport_and_preserves_original_bodies(self):
        source=ADAPTER.read_text(encoding="utf-8")
        self.assertIn("_Invoke-LegacyExecutionHost -EntryPoint 'legacy-diagnostic-session'",source)
        for forbidden in ("ProcessStartInfo","StandardInput","StandardOutput","FromBase64String","WriteChunks","CUCP_NATIVE_HOST"):
            self.assertNotIn(forbidden,source)
        self.assertEqual(len(re.findall(r"^function Invoke-Macro",source,re.M)),0)
        for name in ("Perf","DiagnoseLag","HealthQuick","HealthDetail","LogTail","Benchmark","SelfTest","AuditSummary","ReleaseNotes"):
            self.assertIn("function Invoke-Macro"+name+" {",BRIDGE.read_text(encoding="utf-8"))
    def test_context_and_mutation_classification_are_closed(self):
        source=ADAPTER.read_text(encoding="utf-8")
        self.assertIn("$State.operation -ceq 'audit-summary'",source)
        self.assertIn("$State.operation -ceq 'diagnose-lag'",source)
        self.assertNotIn("HashtablePaths",source)
        self.assertNotIn("hashtable_paths",source)
        self.assertIn("diagnostic_metric_order",source)
        self.assertIn("$State.diagnostic_process_lists[1][$CurrentOrdinal]",source)
        self.assertNotIn("Get-Process -Id",source)
        self.assertIn("try{$process.Dispose()}catch{}",source)
        for e in (dict(kind="AuditProbe"),dict(kind="ClearAppshotCache"),dict(kind="Appshot"),dict(kind="Macro",name="health-quick"),dict(kind="Cli",argv=["observe","screenshot"]),dict(kind="Cli",argv=["version"]),dict(kind="Native",argv=["-Action","health"])):
            self.assertTrue(changes_owned_state(e))
        for e in (dict(kind="Processes"),dict(kind="ProcessMetrics"),dict(kind="Macro",name="metrics"),dict(kind="NodeVersion")):
            self.assertFalse(changes_owned_state(e))
    def test_actual_capture_intercepts_owned_and_native_leaves(self):
        for name in ("file","runtime"):
            source=(ROOT/f"tests/fixtures/legacy-diagnostics-{name}-oracle.ps1").read_text(encoding="utf-8")
            for leaf in ("_Diagnostic-Clock","_Diagnostic-NodeVersion","_Diagnostic-TailBytes","_Diagnostic-AuditProbe","_Diagnostic-ClearAppshotCache","_Diagnostic-ProcessorCount","_Diagnostic-ProcessMetrics"):
                self.assertIn("function "+leaf,source)
            self.assertIn("elseif($AdapterSource){_Invoke-LegacyDiagnosticFamily",source)
            self.assertIn("$node.Extent.Text",source)
            self.assertNotIn("$fixtures=@(",source,"PS5 ConvertFrom-Json already preserves the root array; do not nest the case corpus")
        self.assertGreaterEqual(len(cases()),303)
    def test_failure_partition_uses_current_effect_then_terminal_history(self):
        effects=[dict(kind="AuditProbe",name=".health-probe-",argv=[],data="owned"),dict(kind="TailBytes",name="",argv=[],data={"path":"owned","max_bytes":65536})]
        f=dict(replies=[None,dict(throw="read failed")])
        failure=captured_failures(f,effects)[0]
        self.assertFalse(changes_owned_state(failure["effect"]))
        self.assertTrue(any(changes_owned_state(e) for e in effects))
        # This read may be caught normally. Prior owned-state dispatch affects an
        # uncaught terminal failure, not every later read-only acquisition reply.
        self.assertEqual(failure["trace_index"],1)


@unittest.skipUnless(sys.platform=="win32","Windows PowerShell 5.1 actual diagnostic adapter qualification")
class DiagnosticActualAdapterTests(unittest.TestCase):
    maxDiff=1500
    def test_production_public_delegates_forward_once(self):
        if diagnostic_adapter_mode()!='production':self.skipTest('Public delegate probe applies only after manifest promotion')
        rest=['--fixture','한국어','literal; $(inert)']
        requests=[dict(id=f'{operation}/{brief}',mode='public-delegate',operation=operation,rest=rest if brief else [],brief=brief) for operation in MIGRATED_DIAGNOSTICS for brief in (False,True)]
        observations=run_guard_driver(self,requests)
        self.assertEqual(len(observations),14)
        for request,observed in zip(requests,observations):
            with self.subTest(operation=request['operation'],brief=request['brief']):
                self.assertEqual(observed['state'],'ok',observed)
                self.assertIsNone(observed['error'])
                self.assertEqual(observed['events'],[])
                self.assertEqual(observed['value'],dict(exit=31,calls=[dict(operation=request['operation'],rest=request['rest'],brief=request['brief'])]))
    def test_exact_retained_adapter_all_cases(self):
        host=os.environ.get("CUCP_DIAGNOSTICS_TEST_HOST")
        self.assertTrue(host,"Qualification must supply CUCP_DIAGNOSTICS_TEST_HOST; actual adapter gate cannot silently skip")
        self.assertTrue(Path(host).is_file(),"Matching diagnostic NativeHost does not exist")
        mode=diagnostic_adapter_mode()
        fixtures=cases();original=[None]*len(fixtures);actual=[None]*len(fixtures)
        with tempfile.TemporaryDirectory(prefix="CUCP diagnostic adapter 한국어 ") as temporary:
            temp=Path(temporary);source=temp/"original.ps1";inputs=temp/"cases.json"
            source.write_bytes(subprocess.check_output(["git","show",f"{ACCEPTED_TREE}:scripts/cucp.ps1"],cwd=ROOT))
            for file_group in (True,False):
                selected=[(i,f) for i,f in enumerate(fixtures) if (f["operation"] in FILE_OPERATIONS)==file_group]
                inputs.write_text(json.dumps([f for _,f in selected]),encoding="utf-8-sig")
                runner=ROOT/("tests/fixtures/legacy-diagnostics-file-oracle.ps1" if file_group else "tests/fixtures/legacy-diagnostics-runtime-oracle.ps1")
                command=[shutil.which("powershell.exe"),"-NoProfile","-NonInteractive","-File",str(runner),"-InputPath",str(inputs)]
                before=subprocess.run(command+["-Source",str(source)],capture_output=True,timeout=300)
                self.assertEqual(before.returncode,0,before.stderr.decode(errors="replace"))
                after=subprocess.run(command+actual_adapter_arguments(source,mode),
                    env={**os.environ,"CUCP_NATIVE_HOST":str(Path(host).resolve()),"CUCP_EXECUTION_DIAGNOSTICS":"1"},capture_output=True,timeout=900)
                self.assertEqual(after.returncode,0,after.stderr.decode(errors="replace"))
                if after.stderr:print("Diagnostic adapter stderr (first 16 KiB):\n"+after.stderr.decode(errors="replace")[:16384],flush=True)
                left=json.loads(before.stdout.decode("utf-8-sig"));right=json.loads(after.stdout.decode("utf-8-sig"))
                self.assertEqual(len(left),len(selected));self.assertEqual(len(right),len(selected))
                for (index,_),old,new in zip(selected,left,right):original[index]=old;actual[index]=new
        exact=owned_failure=terminal_failure=0;diagnostic_shown=False
        for index,(fixture,before,after) in enumerate(zip(fixtures,original,actual)):
            with self.subTest(index=index,operation=fixture["operation"],rest=fixture["rest"],brief=fixture.get("brief")):
                old_effects=decode_wire(before["effects"]);new_effects=decode_wire(after["effects"])
                failures=captured_failures(fixture,old_effects)
                # The two retained production bodies do not enter the shared
                # session: preserve their ordinary errors through full equality.
                uses_session=diagnostic_uses_session(fixture['operation'],mode)
                # The assertion leaf converts its original catch-any rejection
                # into a completed Boolean policy result. It still counts as an
                # owned write for terminal loss, but is not an error reply.
                uncertain=next((f for f in failures if changes_owned_state(f["effect"]) and f["effect"]["kind"]!="AssertAuthorized"),None) if uses_session else None
                if uncertain is not None:
                    owned_failure+=1;stop=uncertain["trace_index"]+1
                    self.assertEqual(new_effects,old_effects[:stop])
                    self.assertEqual(after["consumed"],uncertain["reply_index"]+1)
                    self.assertEqual(after["state"],"error")
                    self.assertEqual(after["error"],UNCERTAIN_MESSAGE)
                    self.assertEqual(after["console"],"")
                    continue
                if uses_session and before["state"]=="error" and any(changes_owned_state(e) for e in old_effects):
                    terminal_failure+=1
                    self.assertEqual(new_effects,old_effects);self.assertEqual(after["consumed"],before["consumed"])
                    self.assertEqual(after["state"],"error")
                    self.assertEqual(after["error"],"mutation_may_have_occurred=true; automatic_retry=false; "+before["error"])
                    self.assertEqual(after["console"],before["console"])
                    continue
                if before!=after and not diagnostic_shown:
                    diagnostic_shown=True
                    print(f"First diagnostic adapter mismatch case {index}: "+str(first_difference(after,before)),flush=True)
                self.assertEqual(after,before)
                exact+=1
        self.assertGreater(exact,0);self.assertGreater(owned_failure,0)
        print(f"Compared all {len(fixtures)} diagnostic {mode} entry cases: {exact} exact, {owned_failure} current owned-write failures, {terminal_failure} terminal postdispatch failures",flush=True)
    def test_decoded_effect_guards_and_native_getter_order(self):
        self.assertTrue(GUARDS.is_file(),"Diagnostic guard driver is required")
        inventory=diagnostic_guard_cases()
        self.assertEqual(len(inventory),196)
        requests=[request for row in inventory if row['mode']!='actual-owned' for request in guard_requests(row)]
        observations=run_guard_driver(self,requests)
        by_id={r['id']:r for r in observations}
        checked=[]
        for row in inventory:
            with self.subTest(index=row['id'],check=row['name']):
                if row['mode']=='actual-owned':assert_owned_guard_files(self,row)
                else:assert_guard_observations(self,row,[by_id[request['id']] for request in guard_requests(row)])
                checked.append(row['id'])
        self.assertEqual(checked,list(range(1,197)))
        print('Verified all 196 diagnostic guards, including owned temporary files and raw getter order',flush=True)

if __name__=="__main__":unittest.main()
