#!/usr/bin/env bash
# preinstall.sh - Arch Linux (unix) preinstall for myjupyter.
#
# Layered by distro on purpose: native package managers and package NAMES
# differ per distribution. The canonical example is the `pychm` build.
set -euo pipefail

DISTRO="archlinux"
PYTHON_VERSION="3.14"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../../.." && pwd)"

log()  { printf '\033[1;34m[preinstall:archlinux]\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[1;33m[preinstall:archlinux]\033[0m %s\n' "$*" >&2; }
err()  { printf '\033[1;31m[preinstall:archlinux]\033[0m %s\n' "$*" >&2; }
have() { command -v "$1" >/dev/null 2>&1; }

SUDO=""
detect_sudo() {
  if [ "$(id -u)" -eq 0 ]; then SUDO=""; return 0; fi
  if have sudo && sudo -n true 2>/dev/null; then SUDO="sudo"; return 0; fi
  SUDO=""
  return 1
}

require_elevation() {
  err "cannot install system packages: not root and passwordless sudo is unavailable."
  err "re-run with elevated privileges, or pre-install the packages listed above."
  exit 1
}

# ---------------------------------------------------------------------------
# 1. Native chmlib - REQUIRED to build pychm (see scripts/libchm.sh)
# ---------------------------------------------------------------------------
# Without it: chm/chmlib_search.h:4:10: fatal error: chm_lib.h: No such file or directory
# shellcheck source=/dev/null
. "$REPO_ROOT/scripts/libchm.sh"
LIBCHM_LOG_PREFIX="preinstall:archlinux"

install_native_deps() {
  if ensure_libchm "$DISTRO"; then
    log "chmlib OK"
  else
    err "chmlib unavailable; pychm will fail to compile."
    exit 1
  fi

  # Extra system libraries that some wheels need to build/link on Arch.
  local pkgs=()
  have node || pkgs+=(nodejs)
  have npm  || pkgs+=(npm)
  if [ ${#pkgs[@]} -gt 0 ]; then
    detect_sudo || require_elevation
    # shellcheck disable=SC2086
    $SUDO pacman -S --needed --noconfirm "${pkgs[@]}"
  fi
}

# ---------------------------------------------------------------------------
# 2. Main
# ---------------------------------------------------------------------------
main() {
  install_native_deps
  log "preinstall complete for $DISTRO (python $PYTHON_VERSION)"
}

main "$@"
