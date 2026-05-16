#!/usr/bin/env python3
"""Deploy the SHARP inference app and persist both web endpoint URLs.

Uniform with flux: every app uses spawn-poll so dispatch never trips
Modal's ~60s sync gateway cap on cold starts.
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
        app_path="sharp/app.py",
        endpoint_file=".endpoint-sharp",
        app_name="demo-hub-sharp",
        submit_env="MODAL_SHARP_SUBMIT_URL",
        poll_env="MODAL_SHARP_POLL_URL",
    )
