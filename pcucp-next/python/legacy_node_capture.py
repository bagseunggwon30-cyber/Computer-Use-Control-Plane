"""Fixed production Node capture bridge; startup supplies every path."""
import argparse
import base64
import json
import sys

from pcucp_cli.legacy_host_protocol import exact,require
from pcucp_cli.legacy_node_runtime import NodeRuntime

def main(argv=None):
    parser=argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('--cli-path')
    parser.add_argument('--cache-directory',required=True)
    parser.add_argument('--wrapper-log',required=True)
    parser.add_argument('--timeout-ms',type=int,required=True)
    args=parser.parse_args(argv)
    runtime=None
    try:
        raw=sys.stdin.buffer.read(1024*1024+1)
        require(len(raw)<=1024*1024,'Node request exceeds one MiB.')
        request=json.loads(raw.decode('utf-8-sig'));exact(request,('argv',))
        runtime=NodeRuntime(cli_path=args.cli_path,cache_directory=args.cache_directory,
                            wrapper_log=args.wrapper_log,timeout_ms=args.timeout_ms)
        result=runtime.invoke(request['argv'],capture_json=True)
        # Preserve text through PS7's date-shaped-string JSON conversion.
        for key in ('Raw','Err'):
            result[key+'Base64']=base64.b64encode(result.pop(key).encode('utf-8')).decode('ascii')
        sys.stdout.buffer.write(json.dumps(dict(schema='cucp.node-capture/v1',data=result),
                                           ensure_ascii=True,allow_nan=False).encode('utf-8'))
        return 0
    except Exception as error:
        print(str(error),file=sys.stderr);return 1
    finally:
        if runtime is not None:runtime.close()

if __name__=='__main__':raise SystemExit(main())
