#!/usr/bin/env bash
# Deploy the SHARP inference app and persist the web endpoint URL.

set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/_lib.sh

run_deploy ./apps/sharp.py .endpoint-sharp MODAL_SHARP_ENDPOINT_URL
