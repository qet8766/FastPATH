"""Entry point for FastPATH viewer."""

import sys

from fastpath.ui.app import run_app


def main() -> int:
    """Run the FastPATH viewer application."""
    return run_app(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
