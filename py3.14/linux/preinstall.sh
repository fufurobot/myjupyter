# preinstall.sh - Carefully install configurable-http-proxy with fallback package managers
# Priority: bun > deno > pnpm > yarn > npm

set -euo pipefail

PKG="configurable-http-proxy"

log()  { printf '\033[1;34m[preinstall]\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[1;33m[preinstall]\033[0m %s\n' "$*" >&2; }
err()  { printf '\033[1;31m[preinstall]\033[0m %s\n' "$*" >&2; }

have() { command -v "$1" >/dev/null 2>&1; }

# --- 1. Check if already installed -----------------------------------------
if have configurable-http-proxy; then
  log "configurable-http-proxy already installed at: $(command -v configurable-http-proxy)"
  exit 0
fi

# --- 2. Pick the best available package manager ----------------------------
# bun > deno > pnpm > yarn > npm
PM=""
INSTALL_CMD=""

if have bun; then
  PM="bun"
  INSTALL_CMD="bun install -g $PKG"
elif have deno; then
  PM="deno"
  # deno doesn't have a true "global install" like npm; use install -gfn
  # which installs an executable into $DENO_INSTALL_ROOT/bin (default ~/.deno/bin)
  INSTALL_CMD="deno install -gfn configurable-http-proxy npm:$PKG"
elif have pnpm; then
  PM="pnpm"
  INSTALL_CMD="pnpm add -g $PKG"
elif have yarn; then
  PM="yarn"
  INSTALL_CMD="yarn global add $PKG"
elif have npm; then
  PM="npm"
  INSTALL_CMD="npm install -g $PKG"
else
  err "No supported package manager found (bun, deno, pnpm, yarn, npm)."
  err "Please install one of them first."
  exit 1
fi

log "Using package manager: $PM"
log "Running: $INSTALL_CMD"

# --- 3. Verify the install root is on PATH --------------------------------
if [ "$PM" = "deno" ] && ! echo ":$PATH:" | grep -q ":$HOME/.deno/bin:"; then
  warn "\$HOME/.deno/bin is not on your PATH."
  warn "Add this to your shell rc:  export PATH=\"\$HOME/.deno/bin:\$PATH\""
fi

# --- 4. Run the install -----------------------------------------------------
# shellcheck disable=SC2086
if ! $INSTALL_CMD; then
  err "Install failed with $PM."
  exit 1
fi

# --- 5. Verify ---------------------------------------------------------------
# Refresh command hash table in case PATH entry was just added
hash -r 2>/dev/null || true

if have configurable-http-proxy; then
  log "Success: $(command -v configurable-http-proxy)"
else
  # Try common fallback locations
  for p in "$HOME/.deno/bin/configurable-http-proxy" \
           "$HOME/.bun/bin/configurable-http-proxy" \
           "$(npm bin -g 2>/dev/null)/configurable-http-proxy" \
           /usr/local/bin/configurable-http-proxy; do
    if [ -x "$p" ]; then
      warn "Installed at $p but not on PATH."
      warn "Add its directory to PATH, e.g.:  export PATH=\"$(dirname "$p"):\$PATH\""
      exit 0
    fi
  done
  err "Install reported success but binary not found on PATH."
  exit 1
fi
