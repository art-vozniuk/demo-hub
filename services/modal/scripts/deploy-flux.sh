#!/usr/bin/env bash
# Deploy the FLUX inference app and persist the web endpoint URL.

set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/_lib.sh

run_deploy ./apps/flux_app.py .endpoint-flux MODAL_GENERATIVE_ENDPOINT_URL
