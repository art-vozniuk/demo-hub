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
  libomp
  colmap
  uv
)

log "Installing/updating brew packages: ${BREW_PACKAGES[*]}"
brew install "${BREW_PACKAGES[@]}"

# 3. GLOMAP — no longer a separate build step. -----------------------------
# As of COLMAP 4.x, the GLOMAP global SfM pipeline ships as a first-class
# subcommand `colmap global_mapper`. We invoke it directly from
# pipeline/run_sfm.py and don't need to compile the standalone glomap repo.
# (Previous versions of this script built it from source against bundled
# COLMAP, which produced binaries that crashed on a SQLite schema mismatch
# when reading the database written by brew's colmap.)
#
# Clean up any artefacts from prior runs of those older scripts so a re-run
# doesn't leave a stale, broken binary on PATH:
GLOMAP_BIN="$(brew --prefix)/bin/glomap"
if [[ -x "$GLOMAP_BIN" ]]; then
  warn "removing legacy standalone glomap install at $GLOMAP_BIN (now using colmap global_mapper instead)"
  rm -f "$GLOMAP_BIN"
fi
if [[ -d "$SCRIPT_DIR/.build/glomap" ]]; then
  warn "removing legacy glomap source tree at $SCRIPT_DIR/.build/glomap"
  rm -rf "$SCRIPT_DIR/.build/glomap"
fi

# 4. Brush (Rust GS trainer; download prebuilt release) --------------------
BRUSH_BIN="$SCRIPT_DIR/.bin/brush_app"
if [[ -x "$BRUSH_BIN" ]]; then
  log "brush already present at $BRUSH_BIN"
else
  log "installing brush"
  mkdir -p "$(dirname "$BRUSH_BIN")"
  case "$ARCH" in
    arm64)  BRUSH_ASSET="brush-app-aarch64-apple-darwin" ;;
    x86_64) BRUSH_ASSET="brush-app-x86_64-apple-darwin"  ;;
    *) err "unsupported arch: $ARCH"; exit 1 ;;
  esac
  # Brush ships .tar.xz from GitHub Releases (asset name is brush-app-* with
  # a hyphen; the binary INSIDE may be either brush_app or brush-app).
  LATEST_URL="https://github.com/ArthurBrussee/brush/releases/latest/download/${BRUSH_ASSET}.tar.xz"
  TMPDIR="$(mktemp -d)"
  trap 'rm -rf "$TMPDIR"' EXIT

  if curl -fSL -o "$TMPDIR/brush.tar.xz" "$LATEST_URL"; then
    log "downloaded prebuilt brush release"
    tar -xJf "$TMPDIR/brush.tar.xz" -C "$TMPDIR"
    # Find the actual binary — could be at top level or inside a subdir,
    # named brush_app (Rust default) or brush-app (Cargo crate name).
    FOUND="$(find "$TMPDIR" -type f \( -name "brush_app" -o -name "brush-app" \) | head -n1)"
    if [[ -z "$FOUND" ]]; then
      err "brush archive did not contain a brush_app/brush-app executable; contents:"
      find "$TMPDIR" -maxdepth 3 -print
      exit 1
    fi
    install -m 0755 "$FOUND" "$BRUSH_BIN"
    log "brush installed at $BRUSH_BIN"
  else
    warn "couldn't download $LATEST_URL — building from source via cargo"
    if ! command -v cargo >/dev/null 2>&1; then
      log "cargo not found; bootstrapping rust toolchain via brew rustup-init"
      brew install rustup
      rustup-init -y --no-modify-path --default-toolchain stable
      # Make cargo visible for the rest of this run without forcing the user
      # to source ~/.cargo/env or restart their shell.
      export PATH="$HOME/.cargo/bin:$PATH"
    fi
    cargo install --git https://github.com/ArthurBrussee/brush \
        --root "$SCRIPT_DIR" \
        --bin brush_app
    SRC="$(find "$SCRIPT_DIR/bin" -maxdepth 1 -type f -name "brush*" | head -n1)"
    if [[ -z "$SRC" ]]; then
      err "cargo install did not produce a brush binary under $SCRIPT_DIR/bin"
      exit 1
    fi
    install -m 0755 "$SRC" "$BRUSH_BIN"
    log "brush built via cargo at $BRUSH_BIN"
  fi
fi

# 5. Python env via uv -----------------------------------------------------
log "syncing Python virtualenv via uv"
cd "$SCRIPT_DIR"
uv sync

log "all dependencies ready."
log "next:  cd $SCRIPT_DIR && uv run python -m pipeline.cli run --video <path> --output <dir>"
