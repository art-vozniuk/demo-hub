#!/usr/bin/env bash
set -euo pipefail

# Build the OpenGL Renderer with Emscripten for local development.
#
# Usage:
#   ./scripts/build-renderer.sh          # full build (configure + compile)
#   ./scripts/build-renderer.sh --quick  # compile only (skip configure)
#
# Prerequisites:
#   brew install cmake
#   ~/emsdk/emsdk install latest && ~/emsdk/emsdk activate latest
#
# After building, start the web app with RENDERER_LOCAL=true:
#   cd services/web && RENDERER_LOCAL=true npm run dev

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
RENDERER_DIR="$ROOT_DIR/services/external/renderer"
BUILD_DIR="$RENDERER_DIR/build-web"

# Activate emsdk
EMSDK_DIR="${EMSDK:-$HOME/emsdk}"
if [ ! -f "$EMSDK_DIR/emsdk_env.sh" ]; then
  echo "Error: emsdk not found at $EMSDK_DIR"
  echo "Install: git clone https://github.com/emscripten-core/emsdk.git ~/emsdk"
  echo "         ~/emsdk/emsdk install latest && ~/emsdk/emsdk activate latest"
  exit 1
fi
source "$EMSDK_DIR/emsdk_env.sh" 2>/dev/null

# Configure (skip with --quick if build dir already exists)
if [ "${1:-}" != "--quick" ] || [ ! -d "$BUILD_DIR" ]; then
  echo "==> Configuring (emcmake cmake)..."
  emcmake cmake -S "$RENDERER_DIR" -B "$BUILD_DIR" -DCMAKE_BUILD_TYPE=Release
fi

JOBS=$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)
echo "==> Building with $JOBS threads..."
cmake --build "$BUILD_DIR" --parallel "$JOBS"

echo ""
echo "==> Build complete! Output in $BUILD_DIR"
echo "    Sandbox.html  Sandbox.js  Sandbox.wasm  Sandbox.data"
echo ""
echo "To preview locally:"
echo "  cd services/web && RENDERER_LOCAL=true npm run dev"
