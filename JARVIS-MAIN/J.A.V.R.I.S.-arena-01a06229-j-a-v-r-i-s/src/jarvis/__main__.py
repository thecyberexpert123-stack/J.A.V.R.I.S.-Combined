"""Allow `python -m jarvis` execution (used by the container eval harness)."""

from jarvis.cli.app import main

if __name__ == "__main__":
    raise SystemExit(main())
