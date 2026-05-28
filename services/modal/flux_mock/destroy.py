#!/usr/bin/env python3
"""Stop the deployed flux-mock app."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from common.cli import destroy  # noqa: E402


if __name__ == "__main__":
    destroy("demo-hub-flux-mock", "flux-models")
