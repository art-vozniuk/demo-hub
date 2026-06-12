
#!/usr/bin/env bash
# One-time setup for the `dev` Modal environment — laptop development against
# the docker-compose.local.yml stack. Idempotent where it can be.
#
# This is run BY YOU. By project rule, deploy/account-mutating Modal commands
# are never run automatically; this script creates a Modal environment and
# (interactively) Modal secrets, so read it before running.
#
# Prereqs: modal CLI installed + logged in (services/modal/setup.sh).

set -euo pipefail

ENV_NAME="dev"

command -v modal >/dev/null 2>&1 || {
    echo "modal CLI not found — run services/modal/setup.sh first."; exit 1;
}

echo "==> Checking Modal auth..."
modal token list >/dev/null 2>&1 || {
    echo "Not logged in. Run: modal token new"; exit 1;
}

echo "==> Ensuring the '${ENV_NAME}' Modal environment exists..."
if modal environment list 2>/dev/null | grep -qw "${ENV_NAME}"; then
    echo "    '${ENV_NAME}' already exists — skipping."
else
    modal environment create "${ENV_NAME}" || echo "    (create failed — it may already exist)"
fi

# NOTE: no metrics secret needed. Containers return their timings inside
# generate() responses (dispatch records them), and Modal's workspace-level
# OpenTelemetry integration pushes system metrics straight to the prod
# Prometheus — dev runs are visible there under environment_name="dev".

# ---- supabase-s3 + huggingface secrets (dev) -------------------------------
# These mirror the values already used in main. The script doesn't know them,
# so create them yourself (same keys as services/modal/README.md):
cat <<EOF

==> dev 'supabase-s3' and 'huggingface' secrets
    Create them in the dev env with the SAME values you use in main:

      modal secret create supabase-s3 \\
        S3_ACCESS_KEY_ID=... S3_ACCESS_KEY_SECRET=... \\
        S3_ENDPOINT=... S3_REGION=... S3_PUBLIC_BUCKETS_ENDPOINT=... \\
        --env ${ENV_NAME}

      modal secret create huggingface HF_TOKEN=... --env ${ENV_NAME}

EOF

cat <<EOF
==> Next steps (full detail in docs/DEPLOY.md):

  export MODAL_ENVIRONMENT=${ENV_NAME}
  make -C services/modal preload-dev        # weights into the dev volume
  make -C services/modal deploy-dev         # flux_opt into dev (gateway resolves it by name)
  make -C services/modal serve-gateway-dev  # ephemeral gateway; prints submit/poll URLs

  # Paste those two URLs into services/dispatch/.env.docker:
  #   MODAL_GATEWAY_SUBMIT_URL=...
  #   MODAL_GATEWAY_POLL_URL=...
  # then restart the local stack and run a flux_opt_a10g generation.
  # Pipeline metrics land in the local Grafana at http://localhost:3000
  # (recorded by dispatch from the timings Modal returns — no tunnel).

Done.
EOF
