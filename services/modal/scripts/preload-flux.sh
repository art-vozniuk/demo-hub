#!/usr/bin/env bash
# Populate the flux-models volume with FLUX.2 klein 4B weights.
# Runs on a Modal CPU container (no local GPU needed). Idempotent.

set -euo pipefail

cd "$(dirname "$0")/.."

modal run app.py::preload_weights
echo "Volume populated successfully."
