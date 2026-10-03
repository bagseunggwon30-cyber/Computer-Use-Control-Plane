"""Export the JSONL contract from the same schemas exposed by stdio MCP."""
import json
from .mcp_server import SCHEMAS, obj


def request_schema():
    variants = []
    for name in SCHEMAS:
        variants.append(obj({'schema': {'const': 'cucp.request/v1'},
            'id': {'type': 'string', 'minLength': 1, 'maxLength': 128},
            'command': {'const': name}, 'args': {'$ref': f'#/$defs/{name}'}},
            ['schema', 'id', 'command', 'args']))
    return {'$schema': 'https://json-schema.org/draft/2020-12/schema',
            'title': 'CUCP local session request',
            'description': 'Generated from pcucp_cli.mcp_server.SCHEMAS. Startup authority is immutable; plans are data and never grant permission.',
            '$defs': SCHEMAS, 'oneOf': variants}


if __name__ == '__main__':
    print(json.dumps(request_schema(), ensure_ascii=False, indent=2))
