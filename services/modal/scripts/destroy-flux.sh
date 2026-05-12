#!/usr/bin/env bash
# Stop the deployed FLUX app. Volume + secrets are kept.

set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/_lib.sh

run_destroy demo-hub-flux flux-models
