#!/usr/bin/env bash
# Tear down the deployed Modal app. Volume + secrets are kept.

set -euo pipefail

cd "$(dirname "$0")/.."

modal app stop demo-hub-flux || true
echo "Stopped demo-hub-flux. Volume 'flux-models' and secrets are preserved."
