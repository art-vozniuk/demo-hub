#!/usr/bin/env bash
# Idempotent installer for gs-training-local pipeline dependencies on macOS.
# Re-running it skips anything already present at the right version.
#
# Usage:  ./install_dependencies.sh

set -euo pipefail

YELLOW='\033[1;33m'
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

log()  { echo -e "${GREEN}[install]${NC} $*"; }
warn() { echo -e "${YELLOW}[install]${NC} $*"; }
err()  { echo -e "${RED}[install]${NC} $*" >&2; }

if [[ "$(uname)" != "Darwin" ]]; then
  err "this installer is macOS-only (Apple Silicon recommended)"
  exit 1
fi

ARCH="$(uname -m)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 1. Homebrew --------------------------------------------------------------
if ! command -v brew >/dev/null 2>&1; then
  err "Homebrew not found. Install from https://brew.sh first."
  exit 1
fi
log "Homebrew present at $(command -v brew)"

# 2. brew packages (brew install is itself idempotent — skips if already installed)
BREW_PACKAGES=(
  ffmpeg
  cmake
  ninja
  pkg-config
  eigen
  ceres-solver
  glog
  gflags
  flann
  freeimage
  metis
  suite-sparse
  colmap
  uv
)

log "Installing/updating brew packages: ${BREW_PACKAGES[*]}"
brew install "${BREW_PACKAGES[@]}"

# 3. GLOMAP (no brew formula — build from source if missing) ---------------
if command -v glomap >/dev/null 2>&1; then
  log "glomap already installed at $(command -v glomap)"
else
  log "building glomap from source"
  GLOMAP_SRC="$SCRIPT_DIR/.build/glomap"
  mkdir -p "$(dirname "$GLOMAP_SRC")"
  if [[ ! -d "$GLOMAP_SRC" ]]; then
    git clone --depth=1 https://github.com/colmap/glomap.git "$GLOMAP_SRC"
  fi
  pushd "$GLOMAP_SRC" >/dev/null
  cmake -B build -GNinja \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX="$(brew --prefix)"
  cmake --build build --target install
  popd >/dev/null
  log "glomap installed at $(command -v glomap)"
fi

# 4. Brush (Rust GS trainer; download prebuilt release) --------------------
BRUSH_BIN="$SCRIPT_DIR/.bin/brush_app"
if [[ -x "$BRUSH_BIN" ]]; then
  log "brush already present at $BRUSH_BIN"
else
  log "downloading brush prebuilt binary"
  mkdir -p "$(dirname "$BRUSH_BIN")"
  case "$ARCH" in
    arm64)  BRUSH_ASSET="brush_app-aarch64-apple-darwin" ;;
    x86_64) BRUSH_ASSET="brush_app-x86_64-apple-darwin"  ;;
    *) err "unsupported arch: $ARCH"; exit 1 ;;
  esac
  # Latest release tarball (versioned releases live on GitHub Releases)
  LATEST_URL="https://github.com/ArthurBrussee/brush/releases/latest/download/${BRUSH_ASSET}.tar.gz"
  TMPDIR="$(mktemp -d)"
  curl -fSL -o "$TMPDIR/brush.tar.gz" "$LATEST_URL" || {
    warn "couldn't download $LATEST_URL — fall back to building from source via cargo"
    if ! command -v cargo >/dev/null 2>&1; then
      err "cargo not found; install Rust toolchain via 'brew install rustup-init && rustup-init -y'"
      exit 1
    fi
    cargo install --git https://github.com/ArthurBrussee/brush --root "$SCRIPT_DIR" brush_app
    [[ -x "$BRUSH_BIN" ]] || ln -sf "$SCRIPT_DIR/bin/brush_app" "$BRUSH_BIN"
    log "brush built via cargo at $BRUSH_BIN"
    exit 0
  }
  tar -xzf "$TMPDIR/brush.tar.gz" -C "$TMPDIR"
  install -m 0755 "$TMPDIR/${BRUSH_ASSET}/brush_app" "$BRUSH_BIN" 2>/dev/null \
    || install -m 0755 "$TMPDIR/brush_app" "$BRUSH_BIN"
  rm -rf "$TMPDIR"
  log "brush installed at $BRUSH_BIN"
fi

# 5. Python env via uv -----------------------------------------------------
log "syncing Python virtualenv via uv"
cd "$SCRIPT_DIR"
uv sync

log "all dependencies ready."
log "next:  cd $SCRIPT_DIR && uv run python -m pipeline.cli run --video <path> --output <dir>"
