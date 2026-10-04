"""Native helper source entrypoint; supports the classic -Action option names."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pcucp-next/python'))
from pcucp_cli.legacy_native_entry import main

if __name__ == '__main__':
    raise SystemExit(main())
