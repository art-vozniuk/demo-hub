#!/usr/bin/env bash
# Deploy the SHARP inference app and persist both web endpoint URLs
# (submit + poll). SHARP uses a spawn-poll flow because cold starts
# can exceed Modal's ~60s sync gateway cap.

set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/_lib.sh

out="$(mktemp -t modal-deploy-sharp.XXXXXX.out)"
trap 'rm -f "${out}"' EXIT

echo "Deploying ./apps/sharp_app.py..."
modal deploy ./apps/sharp_app.py | tee "${out}"

# Modal prints "Created web function <name> => <url>" per @fastapi_endpoint.
submit_url="$(grep -Eo 'https://[^[:space:]]+--demo-hub-sharp-submit\.modal\.run' "${out}" | head -n1 || true)"
poll_url="$(grep -Eo 'https://[^[:space:]]+--demo-hub-sharp-poll\.modal\.run' "${out}" | head -n1 || true)"

if [ -z "${submit_url}" ] || [ -z "${poll_url}" ]; then
    echo "Failed to extract submit/poll URLs from modal output." >&2
    exit 1
fi

printf '%s\n%s\n' "${submit_url}" "${poll_url}" > .endpoint-sharp
echo
echo "Deployed."
echo "  Submit: ${submit_url}"
echo "  Poll:   ${poll_url}"
echo "  Stored at: $(pwd)/.endpoint-sharp"
echo
echo "Set on the dispatch worker:"
echo "  MODAL_SHARP_SUBMIT_URL=${submit_url}"
echo "  MODAL_SHARP_POLL_URL=${poll_url}"
