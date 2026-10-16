#!/usr/bin/env bash
# preinstall.sh - Windows 7 (windows) preinstall for myjupyter.
#
# Layered by distro on purpose: native package managers and package NAMES
# differ per distribution. The canonical example is the `pychm` build.
set -euo pipefail

DISTRO="win7"
PYTHON_VERSION="3.10"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../../.." && pwd)"

log()  { printf '\033[1;34m[preinstall:win7]\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[1;33m[preinstall:win7]\033[0m %s\n' "$*" >&2; }
err()  { printf '\033[1;31m[preinstall:win7]\033[0m %s\n' "$*" >&2; }
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
LIBCHM_LOG_PREFIX="preinstall:win7"

install_native_deps() {
  # Windows: this bash layer is for Git Bash / MSYS2. The native, fully
  # supported path is preinstall.ps1 next to this file.
  #
  # chmlib is required to compile pychm (see scripts/libchm.sh).
  if ensure_libchm "$DISTRO"; then
    log "chmlib OK"
    return 0
  fi

  warn "chmlib not found via the bash layer; falling back to Windows tools"
  warn "preferred: pwsh -File preinstall.ps1"

  # vcpkg is the canonical source of chmlib on Windows; Chocolatey and MSYS2
  # pacman are accepted alternatives. This mirrors preinstall.ps1.
  if have vcpkg; then
    log "installing chmlib via vcpkg"
    vcpkg install chmlib
    local vcpkg_root="${VCPKG_ROOT:-C:/vcpkg}"
    export CFLAGS="${CFLAGS:-} /I$vcpkg_root/installed/x64-windows/include"
    export LDFLAGS="${LDFLAGS:-} /LIBPATH:$vcpkg_root/installed/x64-windows/lib"
  elif have choco; then
    log "installing chmlib via Chocolatey (choco)"
    choco install -y chmlib
  elif have pacman; then
    log "installing chmlib via MSYS2 pacman"
    pacman -S --needed --noconfirm mingw-w64-ucrt-x86_64-chmlib
  else
    err "no vcpkg, choco, or MSYS2 pacman found to provide chmlib."
    err "pychm will fail to build with: chm_lib.h: No such file or directory"
    err "install vcpkg (https://vcpkg.io) then re-run, or run preinstall.ps1"
    exit 1
  fi

  if ensure_libchm "$DISTRO"; then
    log "chmlib OK"
  else
    warn "chm_lib.h still not visible; set CHMLIB_PREFIX to the chmlib root"
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
