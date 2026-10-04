"""Original command gate predicates; command data cannot grant startup consent."""
from .legacy_cdp_contract import _ps_equal
from .legacy_host_protocol import require

def argv_values(argv):
    if argv is None:return []
    require(type(argv) is list and all(word is None or type(word) is str for word in argv),
            'Authorization argv must be inert strings.')
    return [word or '' for word in argv]

def predicates(argv):
    words=argv_values(argv)
    has=lambda value:any(_ps_equal(word,value) for word in words)
    prefix=lambda *parts:len(words)>=len(parts) and all(_ps_equal(word,part) for word,part in zip(words,parts))
    live=prefix('act') or prefix('app','switch') or prefix('plan','run') or prefix('scenario','run') and has('--execute')
    if prefix('desktop','benchmark') and len(words)>=3:
        operation=words[2]
        preflight,verify,dry=has('--preflight-only'),has('--verify-only'),has('--dry-run')
        if _ps_equal(operation,'runbook') and not (dry or verify or preflight) and has('--allow-live-control'):
            live=True
        if any(_ps_equal(operation,name) for name in ('run','collect')) and has('--live') and not preflight:
            live=True
    if prefix('l5') and len(words)>=2:
        if _ps_equal(words[1],'run'):live=True
        if any(_ps_equal(words[1],name) for name in ('resume','live-eval')) and has('--allow-control'):live=True
    coordinate=prefix('act') and len(words)>=2 and any(_ps_equal(words[1],name) for name in
        ('click','right-click','drag','scroll','type')) and (has('--x') or has('--from-x'))
    return dict(live=bool(live),missing_observation=bool(coordinate and not has('--after') and not has('--force')))

def authorize(argv, *, allow_live_control=False):
    require(type(allow_live_control) is bool,'Authorization startup permission must be boolean.')
    words=argv_values(argv);result=predicates(words);command=' '.join(words)
    if result['missing_observation']:
        return dict(**result,error='Coordinate-based act command requires --after <observation-id>.',
            notices=[dict(level='ERROR',message="좌표 기반 act 명령은 --after <observation-id>가 필요합니다. 'observe appshot'을 먼저 실행하거나 매크로(click-label 등)를 사용하세요.")])
    if result['live'] and not allow_live_control:
        return dict(**result,error='Live desktop control blocked. Re-run with -AllowLiveControl after explicit user authorization.',
            notices=[dict(level='ERROR',message='라이브 데스크톱 조작이 차단되었습니다. 사용자가 명시 허락한 경우만 -AllowLiveControl 와 함께 다시 실행하세요.'),
                     dict(level='WARN',message='차단된 명령: '+command)])
    return dict(**result,error=None,notices=[dict(level='WARN' if result['live'] else 'INFO',
        message=('라이브 컨트롤 모드: ' if result['live'] else '관찰/시뮬레이션 모드: ')+command)])
