#!/usr/bin/env bash
# Deploy the FLUX inference app and persist the web endpoint URL.

set -euo pipefail

cd "$(dirname "$0")/.."

echo "Deploying $(basename "$PWD")/./apps/flux.py..."
modal deploy ./apps/flux.py | tee /tmp/modal-deploy.out

URL="$(grep -Eo 'https://[^[:space:]]+\.modal\.run' /tmp/modal-deploy.out | head -n1 || true)"
if [ -z "${URL}" ]; then
    echo "Failed to extract endpoint URL from modal output." >&2
    exit 1
fi

echo "${URL}" > .endpoint
echo
echo "Deployed."
echo "  Endpoint: ${URL}"
echo "  Stored at: $(pwd)/.endpoint-flux"
echo
echo "Set on the dispatch worker:"
echo "  MODAL_GENERATIVE_ENDPOINT_URL=${URL}"
