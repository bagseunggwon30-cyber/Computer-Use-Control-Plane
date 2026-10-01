"""Source-only entrypoint for generated launchers; no model, shell or legacy fallback."""
from pcucp_cli.cli import main

if __name__ == '__main__':
    raise SystemExit(main())
