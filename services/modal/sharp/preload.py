#!/usr/bin/env python3
"""Populate the sharp-models volume with the Apple ml-sharp checkpoint.

Runs on a Modal CPU container (no local GPU needed). Idempotent.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from common.cli import preload  # noqa: E402


if __name__ == "__main__":
    preload("sharp/app.py")
