"""Pure public version reports and safety macro preparation; no live effects."""
import math
import time

from .legacy_cdp_contract import _ps_equal, ps_string
from .legacy_diagnostic_provider import option
from .legacy_host_protocol import exact, require
from .legacy_native_kernel import compatibility
from .legacy_workflow_plan import tokenize

SAFETY = frozenset(('safety-classify',))

def _flag(rest, name):
    return any(_ps_equal(word, name) for word in rest)

def _all(rest, name):
    values=[];index=0
    while index<len(rest)-1:
        if _ps_equal(rest[index],name):
            values.append(rest[index+1]);index+=1
        index+=1
    return values

def safety_arguments(rest):
    require(type(rest) is list and all(type(word) is str for word in rest),'Safety argv must be inert strings.')
    macro=option(rest,'--macro') or ''
    parts=[value for name in ('--text','--step','--command') for value in _all(rest,name)]
    if not parts:
        skip_next=False
        for word in rest:
            if skip_next:
                skip_next=False;continue
            if _ps_equal(word,'--json-only'):continue
            if any(_ps_equal(word,key) for key in ('--text','--step','--command','--macro')):
                skip_next=True;continue
            parts.append(word)
    return dict(text=' '.join(parts),macro=macro)

def run_safety(rest, *, brief=False, culture='en-US', timeout_s=15, parent_deadline=math.inf, cancelled=None):
    require(type(brief) is bool and type(culture) is str and type(timeout_s) in (int,float) and
            math.isfinite(timeout_s) and timeout_s>0,'Invalid safety startup.')
    deadline=min(parent_deadline,time.monotonic()+timeout_s)
    def remaining():
        require(cancelled is None or not cancelled.is_set(),'Safety owner cancelled; no retry.')
        value=deadline-time.monotonic()
        require(value>0,'Safety deadline expired; no retry.')
        return value
    args=safety_arguments(rest)
    if not args['macro']:
        parsed=tokenize([args['text']],culture=culture,timeout_s=remaining(),cancelled=cancelled)[0]
        if parsed['ok'] and len(parsed['tokens'])>=2 and _ps_equal(parsed['tokens'][0],'macro'):
            args['macro']=parsed['tokens'][1]
    payload=compatibility('safety-classify',args,culture=culture,timeout_s=remaining(),cancelled=cancelled)
    remaining()
    rendered=brief and not _flag(rest,'--json-only')
    line=f"ok safety-classify risk={payload['risk_level']} score={ps_string(payload['risk_score'])} confirm={ps_string(payload['requires_explicit_confirmation'])}"
    return dict(payload=payload,exit=0,json_depth=10,brief=line if rendered else None,emit_json=not rendered)

def version_report(report, rest, *, brief=False):
    require(type(rest) is list and all(type(word) is str for word in rest) and type(brief) is bool,
            'Version argv must be inert strings.')
    exact(report,('schema','status','surface','helper_mode','versions','sources','recoverable_errors','generated_at'))
    require(report['schema']=='cucp.version/v1' and report['status'] in ('ok','partial') and
            type(report['recoverable_errors']) is list and type(report['generated_at']) is str,'Invalid version report.')
    exact(report['versions'],('skill','cli','helper_server'))
    require(all(value is None or type(value) is str for value in report['versions'].values()),'Invalid version scalars.')
    versions=report['versions']
    skill='v'+versions['skill'] if versions['skill'] else 'v?'
    cli='v'+versions['cli'] if versions['cli'] else 'missing'
    helper='v'+versions['helper_server'] if versions['helper_server'] else 'missing'
    line=f"ok cucp {skill} (skill) + {cli} (cli) + {helper} (helper-server, {report['helper_mode']}) surface={report['surface']} status={report['status']}"
    rendered=brief and not _flag(rest,'--json-only')
    return dict(payload=report,exit=2 if report['status']=='partial' else 0,json_depth=8,
                brief=line if rendered else None,emit_json=not rendered)

def build_version(args):
    exact(args,('skill','cli','helper','helper_mode','generated_at'))
    exact(args['cli'],('version','package_path','error'))
    exact(args['helper'],('version','error'))
    require(type(args['skill']) is str and type(args['generated_at']) is str and
            args['helper_mode'] in ('child_only','persistent_server') and
            all(value is None or type(value) is str for value in (*args['cli'].values(),*args['helper'].values())),
            'Invalid captured version facts.')
    errors=[]
    if args['cli']['error']:
        errors.append(dict(code=args['cli']['error'],layer='cli',
            recommended_action='Set CUCP_CLI_PATH or run wrapper-only mode'))
    if args['helper']['error']:
        errors.append(dict(code=args['helper']['error'],layer='helper_server',
            recommended_action='Build and verify pcucp-next/bin/legacy-helper with packaging/publish_legacy_helper.py'))
    return dict(schema='cucp.version/v1',status='partial' if errors else 'ok',
        surface='wrapper+cli' if args['cli']['version'] else 'wrapper_only',helper_mode=args['helper_mode'],
        versions=dict(skill=args['skill'],cli=args['cli']['version'],helper_server=args['helper']['version']),
        sources=dict(skill='scripts/cucp.ps1::Script:SkillVersion',cli=args['cli']['package_path'],
                     helper_server='pcucp-next/bin/legacy-helper/manifest.json'),
        recoverable_errors=errors,generated_at=args['generated_at'])

def handle(request, *, culture='en-US', timeout_s=15, allow_live_control=False):
    require(type(request) is dict and type(request.get('name')) is str,'Invalid public surface request.')
    if request['name'] in ('authorization-predicates','authorization'):
        exact(request,('name','argv'))
        from .legacy_authorization import predicates,authorize
        return predicates(request['argv']) if request['name']=='authorization-predicates' else authorize(request['argv'],allow_live_control=allow_live_control)
    if request['name']=='version-report':
        exact(request,('name','args'))
        return dict(value=build_version(request['args']))
    if request['name']=='safety-classify':
        exact(request,('name','rest','brief'))
        return run_safety(request['rest'],brief=request['brief'],culture=culture,timeout_s=timeout_s)
    require(request['name']=='version','Unknown public surface macro.')
    exact(request,('name','rest','brief','report'))
    return version_report(request['report'],request['rest'],brief=request['brief'])
