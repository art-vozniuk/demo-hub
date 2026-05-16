#!/usr/bin/env python3
"""Populate the flux-models volume with FLUX.2 klein 4B weights.

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
    preload("flux/app.py")
