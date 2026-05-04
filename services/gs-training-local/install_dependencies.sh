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

# 3. GLOMAP (no brew formula — build from source if missing) ---------------
# We pin the build to the *system* colmap and poselib (both from brew) via
# FETCH_COLMAP/FETCH_POSELIB=OFF, otherwise GLOMAP bundles its own COLMAP
# via FetchContent and the resulting glomap binary speaks a slightly
# different SQLite schema than the brew `colmap` binary that wrote the
# database — which crashes with "SQLite error: SQL logic error" at the
# very start of `glomap mapper`.
GLOMAP_BIN="$(brew --prefix)/bin/glomap"
GLOMAP_MARKER="$SCRIPT_DIR/.build/glomap/.installed-against-system-colmap"
if [[ -x "$GLOMAP_BIN" && -f "$GLOMAP_MARKER" ]]; then
  log "glomap already installed at $GLOMAP_BIN"
else
  if [[ -x "$GLOMAP_BIN" ]]; then
    warn "removing previous glomap install (missing system-colmap marker)"
    rm -f "$GLOMAP_BIN"
  fi
  log "building glomap from source"
  GLOMAP_SRC="$SCRIPT_DIR/.build/glomap"
  mkdir -p "$(dirname "$GLOMAP_SRC")"
  if [[ ! -d "$GLOMAP_SRC" ]]; then
    git clone --depth=1 https://github.com/colmap/glomap.git "$GLOMAP_SRC"
  fi
  pushd "$GLOMAP_SRC" >/dev/null

  # AppleClang doesn't ship with OpenMP. CMake's FindOpenMP can't locate the
  # Homebrew libomp on its own — we have to spell out where it lives.
  # Without these flags configure fails with:
  #   "Could NOT find OpenMP_C (missing: OpenMP_C_FLAGS OpenMP_C_LIB_NAMES)"
  LIBOMP_PREFIX="$(brew --prefix libomp)"
  if [[ ! -d "$LIBOMP_PREFIX" ]]; then
    err "libomp not found at expected brew prefix; reinstall via 'brew install libomp'"
    exit 1
  fi

  # --fresh forces a clean configure even if a previous failed (or
  # successfully-but-with-bundled-colmap) run left a stale CMakeCache.txt.
  cmake -B build -GNinja --fresh \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX="$(brew --prefix)" \
    -DFETCH_COLMAP=OFF \
    -DFETCH_POSELIB=OFF \
    -DOpenMP_C_FLAGS="-Xpreprocessor -fopenmp -I${LIBOMP_PREFIX}/include" \
    -DOpenMP_CXX_FLAGS="-Xpreprocessor -fopenmp -I${LIBOMP_PREFIX}/include" \
    -DOpenMP_C_LIB_NAMES=omp \
    -DOpenMP_CXX_LIB_NAMES=omp \
    -DOpenMP_omp_LIBRARY="${LIBOMP_PREFIX}/lib/libomp.dylib"
  cmake --build build --target install
  popd >/dev/null
  touch "$GLOMAP_MARKER"
  log "glomap installed at $GLOMAP_BIN (linked against system colmap)"
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
