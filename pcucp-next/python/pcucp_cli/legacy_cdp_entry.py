"""Process bridge for a trusted legacy host; no PowerShell implementation dependency.

Usage: python -m pcucp_cli.legacy_cdp_entry --endpoint http://127.0.0.1:9222
Pass --allow-live-control only from immutable human-authorized host startup.
Stdin is one bounded JSON object {"action": "cdp-detect", "args": {}}. Stdout is
the native-helper payload and the process exits with its original helper code.
"""
from __future__ import annotations
import argparse
import json
import sys
from .cdp import CdpError, MAX_BODY, _json
from .legacy_cdp import LegacyCdpAdapter


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--endpoint',required=True)
    parser.add_argument('--allow-live-control',action='store_true')
    parser.add_argument('--timeout-s',type=float,default=8)
    options=parser.parse_args(argv)
    adapter=None
    try:
        adapter=LegacyCdpAdapter(options.endpoint,allow_live_control=options.allow_live_control,timeout_s=options.timeout_s)
        frame=sys.stdin.buffer.readline(MAX_BODY+1)
        if len(frame)>MAX_BODY: raise ValueError('request exceeds byte limit')
        request=_json(frame)
        if not isinstance(request,dict) or set(request)!={'action','args'}:
            raise ValueError('request must contain exactly action and args')
        result=adapter.execute(request['action'],request['args'])
        payload,code=result.payload,result.exit_code
    except (ValueError,CdpError) as exc:
        payload,code=dict(status='error',reason=getattr(exc,'code','invalid_argument'),detail=str(exc)),1
    finally:
        if adapter:adapter.close()
    encoded=json.dumps(payload,ensure_ascii=True,allow_nan=False,separators=(',',':'))+'\n'
    sys.stdout.write(encoded)
    return code


if __name__=='__main__':raise SystemExit(main())
