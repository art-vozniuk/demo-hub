#!/usr/bin/env python3
"""Deploy the web gateway — the only app that owns web endpoints."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from common.cli import deploy_submit_poll  # noqa: E402


if __name__ == "__main__":
    deploy_submit_poll(
        app_path="gateway/app.py",
        endpoint_file=".endpoint-gateway",
        app_name="demo-hub-gateway",
        submit_env="MODAL_GATEWAY_SUBMIT_URL",
        poll_env="MODAL_GATEWAY_POLL_URL",
    )
