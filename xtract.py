#!/usr/bin/env python3
"""xTRACT CLI entry point."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
src_dir = str(ROOT / "src")
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

# Allow xtract to act as a package pointing to src/xtract
__path__ = [str(ROOT / "src" / "xtract")]

from xtract.cli import main

if __name__ == "__main__":
    sys.exit(main())
