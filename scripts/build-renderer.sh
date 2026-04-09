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
RENDERER_DIR="$ROOT_DIR/services/external/OpenGL-Renderer"
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

# Build
JOBS=$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)
echo "==> Building with $JOBS threads..."
cmake --build "$BUILD_DIR" --parallel "$JOBS"

# Patch Sandbox.html with postMessage hook (same as CI does).
# This lets the parent React frame know when the renderer is ready.
echo "==> Patching Sandbox.html with postMessage hook..."
python3 - <<'PYEOF'
import sys, os
html_path = os.path.join(sys.argv[1], "Sandbox.html")
with open(html_path) as f:
    html = f.read()

# Hide Emscripten UI, make canvas fill the viewport
style_patch = """<style>
#emscripten_logo, .spinner, #status, #progress, #controls, #output { display: none !important; }
.emscripten_border { border: none !important; position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; display: flex; align-items: center; justify-content: center; background: transparent; }
canvas.emscripten { max-width: 100vw !important; max-height: 100vh !important; width: auto !important; height: auto !important; display: block; object-fit: contain; outline: none !important; }
body { margin: 0; overflow: hidden; background: transparent; }
</style>"""
html = html.replace("</head>", style_patch + "\n</head>", 1)

patch = """<script>
(function () {
  // Route .data files to /renderer/data/ (proxied to GitHub Releases in prod)
  function hookLocateFile() {
    if (typeof Module !== 'undefined') {
      var origLocate = Module.locateFile || function(p) { return p; };
      Module.locateFile = function(path, prefix) {
        if (path.endsWith('.data')) {
          return '/renderer/data/' + path;
        }
        return origLocate(path, prefix);
      };
    } else {
      requestAnimationFrame(hookLocateFile);
    }
  }
  hookLocateFile();

  function hookSetStatus() {
    if (typeof Module !== 'undefined' && typeof Module.setStatus === 'function') {
      var orig = Module.setStatus;
      Module.setStatus = function (text) {
        orig.call(Module, text);
        if (window.parent === window) return;
        if (text === '') {
          window.parent.postMessage({ type: 'renderer-ready' }, '*');
          Module.setStatus = orig;
        } else {
          var m = text.match(/\((\d+(?:\.\d+)?)\/(\d+)\)/);
          if (m) {
            window.parent.postMessage({
              type: 'renderer-progress',
              loaded: parseFloat(m[1]),
              total: parseFloat(m[2])
            }, '*');
          }
        }
      };
    } else {
      requestAnimationFrame(hookSetStatus);
    }
  }
  hookSetStatus();
})();
</script>"""

if "renderer-ready" not in html:
    assert "</body>" in html, "Could not find </body> in Sandbox.html"
    html = html.replace("</body>", patch + "\n</body>", 1)
    with open(html_path, "w") as f:
        f.write(html)
    print("  Patched successfully.")
else:
    print("  Already patched, skipping.")
PYEOF
"$BUILD_DIR"

echo ""
echo "==> Build complete! Output in $BUILD_DIR"
echo "    Sandbox.html  Sandbox.js  Sandbox.wasm  Sandbox.data"
echo ""
echo "To preview locally:"
echo "  cd services/web && RENDERER_LOCAL=true npm run dev"
