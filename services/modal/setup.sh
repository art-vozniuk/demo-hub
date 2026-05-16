#!/usr/bin/env bash
# One-time Modal setup: install CLI, log in, create huggingface secret.
# Idempotent — safe to re-run.
#
# Note: proxy-auth tokens for the web endpoint are NOT created here.
# Modal manages those server-side; create one in the dashboard at
# https://modal.com/settings/proxy-auth-tokens and copy the Token ID +
# Token Secret into services/dispatch/.env.docker.

set -euo pipefail

#if ! command -v modal >/dev/null 2>&1; then
#    echo "Installing modal CLI..."
#    pip install --user --upgrade modal
#fi

echo "Checking Modal auth..."
if ! modal token list >/dev/null 2>&1; then
    echo "No Modal token found. Launching browser flow..."
    modal token new
fi

echo "Ensuring 'huggingface' secret exists (HF_TOKEN, optional for ungated repos)..."
if ! modal secret list 2>/dev/null | awk '{print $1}' | grep -qx "huggingface"; then
    read -rp "Enter HF_TOKEN (leave empty to skip): " HF_TOKEN
    if [ -n "${HF_TOKEN}" ]; then
        modal secret create huggingface "HF_TOKEN=${HF_TOKEN}"
    else
        modal secret create huggingface "HF_TOKEN=unset"
        echo "Created 'huggingface' secret with placeholder. Update later if the repo becomes gated."
    fi
fi

cat <<'EOF'

Modal setup complete.

Next: create a proxy-auth token for the web endpoint.

  1. Open https://modal.com/settings/proxy-auth-tokens
  2. Click "Create new token"
  3. Copy the Token ID and Token Secret
  4. Paste them into services/dispatch/.env.docker:

       MODAL_PROXY_AUTH_TOKEN_ID=<Token ID from dashboard>
       MODAL_PROXY_AUTH_TOKEN_SECRET=<Token Secret from dashboard>

These are validated by Modal directly — they do NOT need to be stored
as a Modal Secret on this side.
EOF
