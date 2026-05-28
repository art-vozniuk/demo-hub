#!/usr/bin/env python3
"""Deploy the flux mock app (CPU-only, used by the MOCK_MODAL bench tier)."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from common.cli import deploy_submit_poll  # noqa: E402


if __name__ == "__main__":
    deploy_submit_poll(
        app_path="flux_mock/app.py",
        endpoint_file=".endpoint-flux-mock",
        app_name="demo-hub-flux-mock",
        submit_env="MODAL_FLUX_MOCK_SUBMIT_URL",
        poll_env="MODAL_FLUX_MOCK_POLL_URL",
    )
