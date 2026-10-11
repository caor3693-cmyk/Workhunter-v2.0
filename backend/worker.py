"""Explicit one-shot collection; no timer or natural scheduling in M1."""

import sys
from backend.cli import main as cli_main


def main() -> int:
    return cli_main(['refresh', *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
