#!/usr/bin/env python3
"""Populate the flux-t2i-models volume with FLUX.1 [schnell] weights.

Runs on a Modal CPU container. Idempotent — re-run anytime.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from common.cli import preload  # noqa: E402


if __name__ == "__main__":
    preload("flux_t2i/app.py")
