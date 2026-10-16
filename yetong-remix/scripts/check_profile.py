#!/usr/bin/env python3
"""Delegate to the existing copy gate; never read or print profile content here."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


def main() -> int:
    gate = Path(__file__).resolve().parents[2] / "yetong-copy/scripts/check_profile.py"
    if not gate.is_file() or gate.is_symlink():
        print("dependency missing: verified yetong-copy profile gate not available", file=sys.stderr)
        return 4
    runpy.run_path(str(gate), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
