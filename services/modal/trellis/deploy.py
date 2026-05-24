#!/usr/bin/env python3
"""Deploy the TRELLIS.2 inference app and persist both web endpoint URLs.

Uniform with flux/sharp: every app uses spawn-poll so dispatch never
trips Modal's ~60s sync gateway cap on cold starts.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from common.cli import deploy_submit_poll  # noqa: E402


if __name__ == "__main__":
    deploy_submit_poll(
        app_path="trellis/app.py",
        endpoint_file=".endpoint-trellis",
        app_name="demo-hub-trellis",
        submit_env="MODAL_TRELLIS_SUBMIT_URL",
        poll_env="MODAL_TRELLIS_POLL_URL",
    )
