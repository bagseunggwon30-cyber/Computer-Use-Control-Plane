"""Inert adapter-bootstrap capture. Never imports runtime or changes files."""
import argparse
import json
import sys

parser=argparse.ArgumentParser()
parser.add_argument('--staged-unqualified',action='store_true',required=True)
parser.add_argument('--lock-file',required=True)
parser.add_argument('--startup-directory',required=True)
parser.add_argument('--metadata-directory',required=True)
parser.add_argument('--allow-autostart-change',action='store_true')
parser.add_argument('--allow-readonly-desktop',action='store_true')
parser.add_argument('--default-autostart',action='store_true')
args=parser.parse_args()
raw=sys.stdin.buffer.read(1048577)
if len(raw)>1048576: raise ValueError('fixture request too large')
request=json.loads(raw)
if (not isinstance(request,dict) or set(request)!={'operation','arguments'} or
        request['operation'] not in ('autostart-install','autostart-uninstall','autostart-status')):
    raise ValueError('unexpected fixture request')
data=dict(operation=request['operation'],arguments=request['arguments'],startup_directory=args.startup_directory,
          metadata_directory=args.metadata_directory,allow_change=args.allow_autostart_change,
          desktop=args.allow_readonly_desktop,default=args.default_autostart)
sys.stdout.buffer.write((json.dumps(dict(schema='cucp.staged-helper-bridge/v1',status='ok',data=data),
    ensure_ascii=False,separators=(',',':'))+'\n').encode('utf-8'))
