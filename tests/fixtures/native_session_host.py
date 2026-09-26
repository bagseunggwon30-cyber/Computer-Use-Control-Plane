"""Deterministic native JSONL stand-in. Never sends desktop input."""
import json
import os
from pathlib import Path
import sys
import time
mode = sys.argv[1]
log = Path(sys.argv[2])
for line in sys.stdin:
    r = json.loads(line)
    with log.open('a') as file:
        file.write(json.dumps({'pid':os.getpid(), 'command':r['command'], 'args':r['args'], 'live':'--allow-live-control' in sys.argv}) + '\n')
    if mode == 'hang':
        time.sleep(60)
    if mode == 'exit':
        sys.exit(5)
    if mode == 'malformed':
        print('bad-json', flush=True)
        continue
    if mode == 'flood':
        print('x' * 8192, flush=True)
        continue
    if mode == 'stderr':
        sys.stderr.write('x' * 8192)
        sys.stderr.flush()
        time.sleep(60)
    if mode == 'delay':
        time.sleep(.04)
    status = 'partial' if mode == 'partial' else 'ok'
    payload = {'schema':'pcucp.native/v1','status':status,'kind':r['command'],
               'data':{'windows':[],'pid':os.getpid()},'errors':[{'code':'truncated','message':'bounded'}] if status == 'partial' else []}
    envelope = {'schema':'pcucp.native.response/v1','id':r['id'] + (1 if mode == 'mismatch' else 0),
                'command':r['command'], 'exit_code':3 if status == 'partial' else 0,'payload':payload}
    print(json.dumps(envelope), flush=True)
