"""Read-only PowerShell 5 pitfall census for remaining scripts; never evaluates source."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys
import tempfile
import uuid


def findings(root):
    result = []
    for file in sorted((Path(root) / 'scripts').glob('*.ps1')):
        if file.is_symlink() or not file.is_file(): continue
        for number, line in enumerate(file.read_text(encoding='utf-8-sig').splitlines(), 1):
            def add(category, risk): result.append(dict(file=file.name,line=number,category=category,risk=risk,snippet=line.strip()))
            def matches(pattern): return bool(re.search(pattern, line, re.I))
            if matches(r'^\s*\$\w+\s*=\s*if\s*\('):
                if matches(r'else\s*\{\s*\d+(\.\d+)?\s*\}|else\s*\{\s*0\.0\s*\}'):
                    add('inline_if_numeric','high (numeric return — known to break in PS5)')
                elif matches(r'else\s*\{\s*"[^"]*"\s*\}'):
                    add('inline_if_string','low (string return — usually OK)')
                else: add('inline_if_other','medium (review recommended)')
            if matches(r'\$args\b') and not matches(r'#.*\$args|\$argList'):
                add('args_automatic_var','medium ($args is auto var — prefer $argList)')
            if matches(r'\$\w+\s*=\s*Get-Content\b') and not matches(r'@\(Get-Content'):
                add('getcontent_single_line','low (use @(Get-Content ...) for array safety)')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--script-root', '-ScriptRoot', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--out', type=Path)
    args = parser.parse_args(argv)
    if hasattr(sys.stdout,'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
    found = findings(args.script_root)
    if not found:
        print('OK no PS5 pitfalls detected'); return 0
    counts = Counter(item['risk'].split()[0] for item in found)
    summary = dict(total=len(found),high=counts['high'],medium=counts['medium'],low=counts['low'],findings=found)
    print('='*78 + '\nPS5 PITFALL AUDIT — ' + str(len(found)) + ' findings\n' + '='*78)
    for risk in sorted({item['risk'] for item in found}):
        group = [item for item in found if item['risk'] == risk]
        print(f'\n[{risk}] {len(group)} findings')
        for item in sorted(group,key=lambda item:(item['file'],item['line'])):
            print(f"  {item['file']:<30} L{item['line']:5}  {item['category']}\n    > {item['snippet']}")
    output = args.out or Path(tempfile.gettempdir()) / ('cucp-ps5-audit-' + uuid.uuid4().hex + '.json')
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print('\nNote: high-risk findings should be reviewed and fixed.\n      low-risk usually safe. medium-risk needs context check.\n\nJSON report: ' + str(output))
    return 0


if __name__ == '__main__': raise SystemExit(main())
