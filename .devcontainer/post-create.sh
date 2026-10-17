#!/usr/bin/env bash
# .devcontainer/post-create.sh
#
# Installs the full development toolchain for a GitHub Codespace.
#
# DESIGN NOTES
#   * This script NEVER assumes the distribution. Codespaces images have
#     changed base distro before and may again, so every install is guarded by
#     `command -v` and dispatched to whichever package manager is actually
#     present (apt / dnf / pacman / apk / brew / nix / guix).
#   * Official installers are preferred for the dev toolchain (uv), because
#     distro packages lag badly.
#   * It is idempotent: safe to re-run after a rebuild.
#   * It does NOT install native libraries to force an unbuildable package to
#     compile. Anything that cannot build is isolated in
#     requirements.experimental.txt instead (see the note about pychm there).

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/.." && pwd)"

log()  { printf '\033[1;34m[post-create]\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[1;33m[post-create]\033[0m %s\n' "$*" >&2; }
err()  { printf '\033[1;31m[post-create]\033[0m %s\n' "$*" >&2; }
have() { command -v "$1" >/dev/null 2>&1; }

SUDO=""
if [ "$(id -u)" -ne 0 ]; then
  if have sudo && sudo -n true 2>/dev/null; then
    SUDO="sudo"
  else
    warn "no passwordless sudo; system package installation may be skipped"
  fi
fi

# ---------------------------------------------------------------------------
# 0. Detect the distribution instead of assuming one
# ---------------------------------------------------------------------------
detect_distro() {
  if have brew && [ -z "${CODESPACES:-}" ]; then echo "macos"; return; fi
  if [ -r /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    case "${ID:-}${ID_LIKE:-}" in
      *arch*)                       echo "archlinux"; return ;;
      *alpine*)                     echo "alpine";    return ;;
      *debian*|*ubuntu*)            echo "debian";    return ;;
      *fedora*|*rhel*|*centos*)     echo "fedora";    return ;;
      *nixos*|*nix*)                echo "nixos";     return ;;
    esac
  fi
  if have guix; then echo "guix"; return; fi
  if have nix;  then echo "nixos"; return; fi
  echo "unknown"
}

DISTRO="$(detect_distro)"
log "detected distribution: $DISTRO"

# ---------------------------------------------------------------------------
# 1. System packages via whichever package manager exists
# ---------------------------------------------------------------------------
install_system_packages() {
  case "$DISTRO" in
    debian)
      have apt-get || return 0
      $SUDO env DEBIAN_FRONTEND=noninteractive apt-get update -qq
      $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        build-essential ca-certificates curl git jq unzip zip \
        pkg-config
      ;;
    fedora)
      have dnf || return 0
      $SUDO dnf install -y gcc gcc-c++ make ca-certificates curl git jq unzip zip \
        pkgconf-pkg-config
      ;;
    archlinux)
      have pacman || return 0
      $SUDO pacman -S --needed --noconfirm base-devel ca-certificates curl git jq \
        unzip zip pkgconf
      ;;
    alpine)
      have apk || return 0
      $SUDO apk add --no-cache build-base ca-certificates curl git jq unzip zip \
        pkgconf
      ;;
    macos)
      have brew || return 0
      brew install jq || warn "some brew packages failed"
      ;;
    nixos|guix)
      # Declarative systems: do not mutate global state here.
      log "$DISTRO detected; system packages are expected to be declared"
      ;;
    *)
      warn "unknown distribution; skipping system package installation"
      ;;
  esac
}
install_system_packages || warn "system package installation had failures (continuing)"

# ---------------------------------------------------------------------------
# 2. uv, via the official installer (distro packages lag badly)
# ---------------------------------------------------------------------------
if have uv; then
  log "uv already installed: $(uv --version)"
else
  log "installing uv via the official astral.sh installer"
  if have curl; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
  elif have wget; then
    wget -qO- https://astral.sh/uv/install.sh | sh
  else
    err "neither curl nor wget available; cannot install uv"
    exit 1
  fi
  # shellcheck disable=SC1091
  [ -f "$HOME/.local/bin/env" ] && . "$HOME/.local/bin/env" || true
  export PATH="$HOME/.local/bin:$PATH"
fi
have uv && log "uv ready: $(uv --version)"

# ---------------------------------------------------------------------------
# 3. Python interpreters across the supported range
# ---------------------------------------------------------------------------
if have uv; then
  for version in 3.10 3.11 3.12 3.13 3.14; do
    if uv python install "$version" >/dev/null 2>&1; then
      log "python $version installed"
    else
      warn "python $version unavailable on this platform (skipped)"
    fi
  done
fi

# ---------------------------------------------------------------------------
# 4. Verify a key target builds (buildability is the acceptance bar)
# ---------------------------------------------------------------------------
if have uv && [ -f "$REPO_ROOT/unix/ubuntu/3.14/pyproject.toml" ]; then
  log "checking that a target pyproject builds"
  ( cd "$REPO_ROOT/unix/ubuntu/3.14" && uv build --wheel --quiet ) \
    && log "target builds OK" \
    || warn "target build failed in this codespace"
fi

# ---------------------------------------------------------------------------
# 5. Node (configurable-http-proxy, used by jupyterhub)
# ---------------------------------------------------------------------------
if have node; then
  log "node already installed: $(node --version)"
else
  log "node not found; jupyterhub's proxy needs it. Install Node.js LTS for full use."
fi

# ---------------------------------------------------------------------------
# 6. Verify the repository itself
# ---------------------------------------------------------------------------
cd "$REPO_ROOT"
if have python3; then
  log "validating the canonical layout"
  python3 scripts/check_layout.py || warn "layout validation reported problems"
fi

log "post-create complete (distribution: $DISTRO)"
