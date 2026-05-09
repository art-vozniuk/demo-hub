#!/usr/bin/env bash
# One-time Modal setup: install CLI, log in, create proxy-auth secret.
# Idempotent — safe to re-run.

set -euo pipefail

if ! command -v modal >/dev/null 2>&1; then
    echo "Installing modal CLI..."
    pip install --user --upgrade modal
fi

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

echo "Ensuring 'modal-proxy-auth' secret exists..."
if ! modal secret list 2>/dev/null | awk '{print $1}' | grep -qx "modal-proxy-auth"; then
    TOKEN_ID="dh_$(openssl rand -hex 8)"
    TOKEN_SECRET="$(openssl rand -hex 32)"
    modal secret create modal-proxy-auth \
        "MODAL_PROXY_AUTH_TOKEN_ID=${TOKEN_ID}" \
        "MODAL_PROXY_AUTH_TOKEN_SECRET=${TOKEN_SECRET}"
    echo
    echo "Generated proxy-auth pair (also stored as a Modal Secret):"
    echo "  MODAL_PROXY_AUTH_TOKEN_ID=${TOKEN_ID}"
    echo "  MODAL_PROXY_AUTH_TOKEN_SECRET=${TOKEN_SECRET}"
    echo
    echo "Copy these into services/dispatch/.env.docker."
fi

echo "Modal setup complete."
