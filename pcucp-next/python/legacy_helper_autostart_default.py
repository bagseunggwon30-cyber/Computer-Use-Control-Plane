"""Fixed default-login bootstrap; uses the original helper.pid discovery path."""
from legacy_helper_autostart_entry import main

if __name__ == '__main__':
    raise SystemExit(main(default_lock=True))
