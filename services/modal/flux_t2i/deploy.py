#!/usr/bin/env python3
"""Deploy flux_t2i and persist its submit/poll endpoint URLs."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from common.cli import deploy_submit_poll  # noqa: E402


if __name__ == "__main__":
    deploy_submit_poll(
        app_path="flux_t2i/app.py",
        endpoint_file=".endpoint-flux-t2i",
        app_name="demo-hub-flux-t2i",
        submit_env="MODAL_GENERATIVE_T2I_SUBMIT_URL",
        poll_env="MODAL_GENERATIVE_T2I_POLL_URL",
    )
