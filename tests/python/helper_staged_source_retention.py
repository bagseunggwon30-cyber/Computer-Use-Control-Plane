"""Normalize only reviewed staging additions for the exact retained-body guard.

Historical source bytes, extents and fixtures are never rewritten. This view is
only for checking that each default branch still contains its entire original
body. Actual staged branches have separate portable and Windows route checks.
"""
from __future__ import annotations

NAMES = ('_Read-LockSafely','_Is-StaleLock','_Try-Delete-Lock','Get-HelperServerStatus',
         'Invoke-HelperPipe','Start-HelperServer','Stop-HelperServer')


def retained_original_view(current):
    for name in NAMES:
        start=current.index('function '+name+' {')
        end=current.index('\nfunction ',start+1)
        body=current[start:end]
        marker='  if ($Script:StagedCompiledHelper) {'
        if body.count(marker)!=1: raise AssertionError('Expected one staged delegate: '+name)
        beginning=body.index(marker)
        if name=='Invoke-HelperPipe':
            ending=body.index('\n  }\n',beginning)+len('\n  }\n')
        else:
            ending=body.index('\n',beginning)+1
        body=body[:beginning]+body[ending:]
        if name=='Invoke-HelperPipe':
            before='    [int]$TimeoutMs = 30000,\n    $ExpectedLock = $null\n'
            if body.count(before)!=1: raise AssertionError('Expected optional invoke snapshot')
            body=body.replace(before,'    [int]$TimeoutMs = 30000\n',1)
        if name=='_Try-Delete-Lock':
            if body.count('  param($ExpectedLock)\n')!=1: raise AssertionError('Expected cleanup snapshot parameter')
            body=body.replace('  param($ExpectedLock)\n','',1)
        current=current[:start]+body+current[end:]
    before='if ($lock2 -and (_Is-StaleLock -Lock $lock2)) { _Try-Delete-Lock -ExpectedLock $lock }'
    after='if ($lock2 -and (_Is-StaleLock -Lock $lock2)) { _Try-Delete-Lock }'
    if current.count(before)!=1: raise AssertionError('Expected one snapshot-bound failure cleanup')
    current=current.replace(before,after,1)
    before='Invoke-HelperPipe -Action $hAction -ArgsHash $hArgs -TimeoutMs $tm -ExpectedLock $lock'
    after='Invoke-HelperPipe -Action $hAction -ArgsHash $hArgs -TimeoutMs $tm'
    if current.count(before)!=1: raise AssertionError('Expected snapshot-bound pipe call')
    return current.replace(before,after,1)
