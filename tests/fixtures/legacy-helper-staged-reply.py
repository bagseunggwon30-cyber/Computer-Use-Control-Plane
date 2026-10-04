"""Inert bridge reply for the shared async completion regression; never a service."""
import argparse
import json
import sys

parser=argparse.ArgumentParser()
parser.add_argument('--staged-unqualified',action='store_true',required=True)
parser.add_argument('--lock-file',required=True)
args=parser.parse_args()
raw=sys.stdin.buffer.read(1048577)
if len(raw)>1048576: raise ValueError('fixture request too large')
request=json.loads(raw)
expected={'status':{},'read':{},'stale':{'snapshot':None},'delete':{'snapshot':None}}
if (not isinstance(request,dict) or set(request)!={'operation','arguments'}
        or request['operation'] not in expected or request['arguments']!=expected[request['operation']]):
    raise ValueError('unexpected fixture request')
# Codec fixture only: even the delete label has no file/process/pipe operation.
data={'status':dict(marker='owned-scalar-reply',empty=[],number=0,flag=False),
      'read':None,'stale':False,'delete':True}[request['operation']]
payload=dict(schema='cucp.staged-helper-bridge/v1',status='ok',data=data)
sys.stdout.buffer.write((json.dumps(payload,separators=(',',':'))+'\n').encode('utf-8'))
