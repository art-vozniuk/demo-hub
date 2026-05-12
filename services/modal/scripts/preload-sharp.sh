#!/usr/bin/env bash
# Populate the sharp-models volume with the Apple ml-sharp checkpoint.
# Runs on a Modal CPU container (no local GPU needed). Idempotent.

set -euo pipefail

cd "$(dirname "$0")/.."

modal run sharp_app.py::preload_weights
echo "Volume populated successfully."
