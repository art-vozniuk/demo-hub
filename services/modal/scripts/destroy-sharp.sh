#!/usr/bin/env bash
# Stop the deployed SHARP app. Volume + secrets are kept.

set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/_lib.sh

run_destroy demo-hub-sharp sharp-models
