#!/usr/bin/env bash
# Deploy the SHARP inference app and persist the web endpoint URL.

set -euo pipefail

cd "$(dirname "$0")/.."

echo "Deploying $(basename "$PWD")/./apps/sharp.py..."
modal deploy ./apps/sharp.py | tee /tmp/modal-deploy-sharp.out

URL="$(grep -Eo 'https://[^[:space:]]+\.modal\.run' /tmp/modal-deploy-sharp.out | head -n1 || true)"
if [ -z "${URL}" ]; then
    echo "Failed to extract endpoint URL from modal output." >&2
    exit 1
fi

echo "${URL}" > .endpoint-sharp
echo
echo "Deployed."
echo "  Endpoint: ${URL}"
echo "  Stored at: $(pwd)/.endpoint-sharp"
echo
echo "Set on the dispatch worker:"
echo "  MODAL_SHARP_ENDPOINT_URL=${URL}"
