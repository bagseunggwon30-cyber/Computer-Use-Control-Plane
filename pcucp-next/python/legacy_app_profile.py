"""Fixed JSON-line adapter for the retained app-profile acquisition ports."""
import argparse
import base64
import sys

from pcucp_cli.legacy_app_profile_runtime import AppProfileRuntime
from pcucp_cli.legacy_host_protocol import exact, json_bytes, parse_json, require

SCHEMA = 'cucp.app-profile-runtime/v1'
# The retained kernel allows 16 MiB of response characters. JSON-line ASCII
# escaping and UTF-8 transport must not impose a smaller 4 MiB reply ceiling.
MAX_FRAME = 64 * 1024 * 1024


def read():
    raw = sys.stdin.buffer.readline(MAX_FRAME + 1)
    require(raw and len(raw) <= MAX_FRAME, 'App-profile reply is missing or exceeds its limit.')
    return parse_json(raw.removeprefix(b'\xef\xbb\xbf'))


def write(value):
    raw = json_bytes(dict(schema=SCHEMA, **value)) + b'\n'
    require(len(raw) <= MAX_FRAME, 'App-profile output exceeds its limit.')
    sys.stdout.buffer.write(raw)
    sys.stdout.buffer.flush()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--history-file-base64', required=True)
    parser.add_argument('--culture-base64', required=True)
    parser.add_argument('--timeout-s', required=True, type=float)
    options = parser.parse_args(argv)
    try:
        history = parse_json(base64.b64decode(options.history_file_base64, validate=True))
        culture = base64.b64decode(options.culture_base64, validate=True).decode('utf-8')
        request = read()
        exact(request, ('rest', 'brief'))
        def kernel(args):
            write(dict(kind='kernel', args=args))
            reply = read()
            exact(reply, ('state', 'score_is_integer'))
            require(type(reply['score_is_integer']) is bool, 'Invalid app-profile scalar type fact.')
            if reply['state'].get('query', {}).get('kind') == 'record':
                require(reply['score_is_integer'], 'App-profile record lacks a valid explicit authorization.')
            return reply['state']
        def acquire(query):
            write(dict(kind='acquire', query=query))
            return read()
        runtime = AppProfileRuntime(acquire, history_file=history, culture=culture,
                                    timeout_s=options.timeout_s, kernel=kernel)
        result = runtime.run(request['rest'], brief=request['brief'])
        write(dict(kind='complete', data=result))
        return 0
    except Exception as error:
        # No replay, including a disconnected pipe after a dispatched append.
        write(dict(kind='error', error=str(error)[:2048]))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
