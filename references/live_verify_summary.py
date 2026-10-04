"""Summarize existing live-verification JSON evidence. Does not operate the desktop."""
import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import re
import sys


def text(value):
    if value is None: return ''
    if isinstance(value, bool): return 'True' if value else 'False'
    if isinstance(value, list): return ' '.join(text(item) for item in value)
    if isinstance(value, dict): return '@{' + '; '.join(key + '=' + text(item) for key,item in value.items()) + '}'
    return str(value)


def rows(value):
    return value if isinstance(value, list) else [value]


def reason(value):
    if not isinstance(value, dict): return ''
    parts = [text(value[key]) for key in ('reason', 'error') if value.get(key)]
    parts.extend(text(item) for item in rows(value.get('warnings')) if item)
    for error in rows(value.get('recoverable_errors')):
        if error:
            parts.append(text(error.get('code') or error.get('message')) if isinstance(error, dict) and (error.get('code') or error.get('message'))
                else json.dumps(error, ensure_ascii=False, separators=(',', ':')))
    for item in rows(value.get('cassette')):
        if isinstance(item, dict):
            if item.get('reason'): parts.append(text(item['reason']))
            if item.get('status'): parts.append('cassette_status=' + text(item['status']))
    for key, field, prefix in (('focus','reason','focus='), ('paste','reason','paste='), ('paste','detail','paste_detail=')):
        if isinstance(value.get(key), dict) and value[key].get(field): parts.append(prefix + text(value[key][field]))
    if value.get('recommendation'): parts.append(text(value['recommendation']))
    return ' | '.join(dict.fromkeys(part for part in parts if part))


def classify(status, detail):
    if status.casefold() == 'ok' or not status.strip() and not detail.strip(): return 'pass'
    if not status.strip(): return 'needs_review'
    if re.search('cdp_port_closed|no_window|no_matching_window|no_text_match|hit_test_target_mismatch|missing_target', detail, re.I):
        return 'environment_missing'
    return 'partial_review' if status.casefold() == 'partial' else 'fail'


def summarize(root):
    root = Path(root)
    items = []
    if root.exists():
        for file in sorted(root.rglob('*.json')):
            if file.name.casefold() == 'summary.json' or file.is_symlink() or not file.is_file(): continue
            status, schema, detail = 'invalid', None, ''
            try:
                value = json.loads(file.read_text(encoding='utf-8-sig'))
                status, schema = (text(value.get('status')), value.get('schema')) if isinstance(value, dict) else ('', None)
                detail = reason(value)
            except (OSError, ValueError) as error:
                detail = str(error)
            stat = file.stat()
            items.append(dict(file=str(file.relative_to(root)), status=status, **{'class':classify(status, detail)}, schema=schema,
                reason=detail, length=stat.st_size, last_write=datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat()))
    counts = dict(Counter(item['class'] for item in items))
    overall = 'empty' if not items else 'review' if any(key in counts for key in ('fail','needs_review','partial_review')) else 'ok'
    return dict(schema='cucp.live-verify-summary/v1', status=overall, root=str(root), generated_at=datetime.now().astimezone().isoformat(),
        count=len(items), classes=counts, items=items)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', '-Root', type=Path, default=Path(__file__).resolve().parents[1] / 'live-verify')
    parser.add_argument('--out', '-Out', type=Path)
    parser.add_argument('--json-only', '-JsonOnly', action='store_true')
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
    summary = summarize(args.root)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    if args.json_only:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"live-verify-summary status={summary['status']} count={summary['count']} " + ' '.join(f'{key}={value}' for key,value in sorted(summary['classes'].items())))
        for item in summary['items']:
            if item['class'] != 'pass': print(f"  {item['class']}: {item['file']} status={item['status']} reason={item['reason']}")
    return 0


if __name__ == '__main__': raise SystemExit(main())
