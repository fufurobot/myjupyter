#!/usr/bin/env bash
# preinstall.sh - Ubuntu (unix) preinstall for myjupyter.
#
# Layered by distro on purpose: native package managers and package NAMES
# differ per distribution. The canonical example is the `pychm` build.
set -euo pipefail

DISTRO="ubuntu"
PYTHON_VERSION="3.14"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../../.." && pwd)"

log()  { printf '\033[1;34m[preinstall:ubuntu]\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[1;33m[preinstall:ubuntu]\033[0m %s\n' "$*" >&2; }
err()  { printf '\033[1;31m[preinstall:ubuntu]\033[0m %s\n' "$*" >&2; }
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
LIBCHM_LOG_PREFIX="preinstall:ubuntu"

install_native_deps() {
  if ! have apt-get; then
    err "apt-get not found; this script targets debian/ubuntu"
    exit 1
  fi
  detect_sudo || require_elevation
  # shellcheck disable=SC2086
  $SUDO env DEBIAN_FRONTEND=noninteractive apt-get update -qq
  # libchm-dev provides chm_lib.h; libchm1 alone is not enough to compile pychm.
  # shellcheck disable=SC2086
  $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    build-essential ca-certificates curl git libchm-dev unzip

  if ensure_libchm "$DISTRO"; then
    log "chmlib OK"
  else
    err "chmlib unavailable; pychm will fail to compile."
    exit 1
  fi

  if ! have node; then
    log "installing nodejs via nodesource is distro-specific; using apt fallback"
    # shellcheck disable=SC2086
    $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends nodejs npm
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
