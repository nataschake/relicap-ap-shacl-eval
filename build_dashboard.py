#!/usr/bin/env python3
"""Stable command-line entry point for the configurable SHACL cube."""
from __future__ import annotations

import sys

from cube_dashboard import build


def main() -> int:
    output = build()
    print(f"Dashboard: {output}")
    print(f"  Details: {output.parent / 'dashboard'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
