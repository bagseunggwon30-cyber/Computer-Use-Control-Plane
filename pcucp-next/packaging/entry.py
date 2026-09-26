"""Console entry point for the portable engine (stdout stays available for JSONL)."""
import sys
from pcucp_cli.cli import main

if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="strict")
    raise SystemExit(main())
