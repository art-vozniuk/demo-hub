#!/usr/bin/env bash
# Populate the flux-models volume with FLUX.2 klein 4B weights.
# Runs on a Modal CPU container (no local GPU needed). Idempotent.

set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/_lib.sh

run_preload ./apps/flux.py
