#!/usr/bin/env bash
# Expose local nginx (:8080) via ngrok, push the URL into the dev Modal
# `pushgateway` secret. Detached; kills any running ngrok first.
set -euo pipefail

PORT="${NGROK_PORT:-8080}"
MODAL_ENV="${MODAL_ENVIRONMENT:-dev}"
LOG="${TMPDIR:-/tmp}/ngrok-dev.log"

command -v ngrok >/dev/null 2>&1 || { echo "ngrok not found (brew install ngrok)"; exit 1; }
command -v modal >/dev/null 2>&1 || { echo "modal CLI not found (activate your venv)"; exit 1; }

# 1. kill any running ngrok
if pgrep -x ngrok >/dev/null 2>&1; then
  echo "==> ngrok already running — stopping it"
  pkill -x ngrok || true
  for _ in $(seq 1 10); do pgrep -x ngrok >/dev/null 2>&1 || break; sleep 0.5; done
fi

# 2. start ngrok detached
echo "==> starting ngrok http ${PORT} (detached; log: ${LOG})"
nohup ngrok http "${PORT}" --log=stdout >"${LOG}" 2>&1 &
disown 2>/dev/null || true

# 3. read the public https URL from ngrok's local API
URL=""
for _ in $(seq 1 30); do
  URL="$(curl -s http://127.0.0.1:4040/api/tunnels 2>/dev/null \
    | python3 -c 'import sys,json; ts=json.load(sys.stdin).get("tunnels",[]); print(next((t["public_url"] for t in ts if t.get("public_url","").startswith("https")), ""))' 2>/dev/null || true)"
  [ -n "${URL}" ] && break
  sleep 1
done
[ -n "${URL}" ] || { echo "ERROR: no ngrok https URL after 30s (see ${LOG}; is the authtoken set?)"; exit 1; }
echo "==> ngrok URL: ${URL}"

# 4. push into the dev pushgateway secret (no token: local /pushgateway/ has no auth)
echo "==> updating Modal secret 'pushgateway' (env=${MODAL_ENV})"
modal secret create pushgateway "PUSHGATEWAY_URL=${URL}/pushgateway" --env "${MODAL_ENV}" --force
echo "==> done — dev flux_opt pushes metrics to ${URL}/pushgateway (stop tunnel: pkill -x ngrok)"
