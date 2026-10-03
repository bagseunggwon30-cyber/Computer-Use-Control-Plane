"""CUCP user launcher installer. Preview by default; use --apply to install."""
import runpy
from pathlib import Path

if __name__ == '__main__':
    runpy.run_path(str(Path(__file__).resolve().parent / 'pcucp-next/packaging/install_runtime.py'), run_name='__main__')
