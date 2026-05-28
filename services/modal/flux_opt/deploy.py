#!/usr/bin/env python3
"""Deploy the optimised FLUX app (A10G + H100 variants in one app)."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from common.cli import deploy_multi_endpoint  # noqa: E402


if __name__ == "__main__":
    deploy_multi_endpoint(
        app_path="flux_opt/app.py",
        endpoint_file=".endpoint-flux-opt",
        app_name="demo-hub-flux-opt",
        endpoints=[
            ("submit_a10g", "MODAL_FLUX_OPT_A10G_SUBMIT_URL"),
            ("poll_a10g",   "MODAL_FLUX_OPT_A10G_POLL_URL"),
            ("submit_h100", "MODAL_FLUX_OPT_H100_SUBMIT_URL"),
            ("poll_h100",   "MODAL_FLUX_OPT_H100_POLL_URL"),
        ],
    )
