#!/usr/bin/env python3
"""Deploy the FLUX inference app and persist both web endpoint URLs.

Uniform with sharp: every app uses spawn-poll so dispatch never trips
Modal's ~60s sync gateway cap on cold starts.
"""

# Path bootstrap MUST precede the `from common.cli import ...` below —
# common/ lives at the parent of this script's dir.
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from common.cli import deploy_submit_poll  # noqa: E402


if __name__ == "__main__":
    deploy_submit_poll(
        app_path="flux/app.py",
        endpoint_file=".endpoint-flux",
        app_name="demo-hub-flux",
        submit_env="MODAL_GENERATIVE_SUBMIT_URL",
        poll_env="MODAL_GENERATIVE_POLL_URL",
    )
