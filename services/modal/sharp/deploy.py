#!/usr/bin/env python3
"""Deploy the SHARP inference app. No web endpoints — its class is
invoked by name through the gateway; see services/modal/gateway."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from common.cli import deploy_app  # noqa: E402


if __name__ == "__main__":
    deploy_app("sharp/app.py", "demo-hub-sharp")
