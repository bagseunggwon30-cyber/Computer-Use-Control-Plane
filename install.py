"""CUCP source installer. Python 3.10+; legacy switches remain accepted."""
from pathlib import Path
import runpy
import sys

if __name__ == '__main__':
    root = Path(__file__).resolve().parent
    arguments = sys.argv[1:]
    plan_only = '--plan' in arguments
    sys.argv = [sys.argv[0], '--root', str(root), *([] if plan_only else ['--apply']),
                *(value for value in arguments if value != '--plan')]
    runpy.run_path(str(root / 'pcucp-next/packaging/install_runtime.py'), run_name='__main__')
