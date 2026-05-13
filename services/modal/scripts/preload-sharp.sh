#!/usr/bin/env bash
# Populate the sharp-models volume with the Apple ml-sharp checkpoint.
# Runs on a Modal CPU container (no local GPU needed). Idempotent.

set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/_lib.sh

run_preload ./apps/sharp_app.py
