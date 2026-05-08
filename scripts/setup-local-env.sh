#!/usr/bin/env bash
# Creates .env.docker files needed by docker-compose.local.yml.
# Run once before the first `docker compose -f docker-compose.local.yml up --build`.
# Safe to re-run — skips files that already exist.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

die() { echo "ERROR: $1" >&2; exit 1; }

portable_sed() {
    # sed -i behaves differently on macOS vs Linux; .bak workaround is portable.
    local pattern="$1" file="$2"
    sed -i.bak "$pattern" "$file" && rm -f "${file}.bak"
}

# The Dockerfile CMDs do `export $(cat /app/.env | xargs)`. xargs concatenates
# everything on one line, so any `#commented` line becomes an argument like
# `#KEY=val` — `export` rejects that as an invalid identifier and the whole
# CMD exits before uvicorn/python starts. Strip comments + blanks to avoid it.
strip_comments_and_blanks() {
    local file="$1"
    sed -i.bak -e '/^[[:space:]]*#/d' -e '/^[[:space:]]*$/d' "$file" && rm -f "${file}.bak"
}

echo "==> Setting up local docker env files"

# ── core ──────────────────────────────────────────────────────────────────────
CORE_SRC="${ROOT}/services/core/.env"
CORE_DST="${ROOT}/services/core/.env.docker"

[ -f "$CORE_SRC" ] || die "services/core/.env not found. Fill it in first."

if [ -f "$CORE_DST" ]; then
    echo "    services/core/.env.docker already exists — skipping"
else
    cp "$CORE_SRC" "$CORE_DST"

    portable_sed 's|^RABBITMQ_URL=.*|RABBITMQ_URL=amqp://guest:guest@rabbitmq:5672/|' "$CORE_DST"

    if grep -q "^REDIS_URL=" "$CORE_DST"; then
        portable_sed 's|^REDIS_URL=.*|REDIS_URL=redis://redis:6379|' "$CORE_DST"
    else
        echo "REDIS_URL=redis://redis:6379" >> "$CORE_DST"
    fi

    # Allow requests from both the nginx proxy (8080) and direct web dev server (5173)
    portable_sed 's|^ALLOWED_ORIGINS=.*|ALLOWED_ORIGINS=http://localhost:5173,http://localhost:8080|' "$CORE_DST"

    strip_comments_and_blanks "$CORE_DST"

    echo "    created services/core/.env.docker"
fi

# ── compute ───────────────────────────────────────────────────────────────────
COMPUTE_SRC="${ROOT}/services/compute/.env"
COMPUTE_DST="${ROOT}/services/compute/.env.docker"

[ -f "$COMPUTE_SRC" ] || die "services/compute/.env not found. Fill it in first."

if [ -f "$COMPUTE_DST" ]; then
    echo "    services/compute/.env.docker already exists — skipping"
else
    cp "$COMPUTE_SRC" "$COMPUTE_DST"

    portable_sed 's|^RABBITMQ_URL=.*|RABBITMQ_URL=amqp://guest:guest@rabbitmq:5672/|' "$COMPUTE_DST"

    strip_comments_and_blanks "$COMPUTE_DST"

    echo "    created services/compute/.env.docker"
fi

# ── web ───────────────────────────────────────────────────────────────────────
WEB_SRC="${ROOT}/services/web/.env.local"
WEB_DST="${ROOT}/services/web/.env.docker"

[ -f "$WEB_SRC" ] || die "services/web/.env.local not found. Fill it in first."

if [ -f "$WEB_DST" ]; then
    echo "    services/web/.env.docker already exists — skipping"
else
    cp "$WEB_SRC" "$WEB_DST"

    # Point app at nginx (port 8080) as the single entry point
    portable_sed 's|^VITE_APP_URL=.*|VITE_APP_URL=http://localhost:8080|' "$WEB_DST"
    # Route API calls through nginx so browser origin matches the app URL
    portable_sed 's|^VITE_CORE_API_URL=.*|VITE_CORE_API_URL=http://localhost:8080/api/v1|' "$WEB_DST"

    strip_comments_and_blanks "$WEB_DST"

    echo "    created services/web/.env.docker"
fi

echo ""
echo "Done. Run:"
echo "  docker compose -f docker-compose.local.yml up --build"
echo ""
echo "Tip: add http://localhost:8080 to Supabase auth redirect URLs so OAuth works locally."
