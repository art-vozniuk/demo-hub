#!/usr/bin/env python3
"""Populate the flux-models volume with FLUX.2 klein 4B weights.

Same volume as services/modal/flux/preload.py — re-running either is a
no-op when files are up to date, so deploying flux_opt over an existing
flux deployment doesn't double-download.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from common.cli import preload  # noqa: E402


if __name__ == "__main__":
    preload("flux_opt/app.py")
