#!/usr/bin/env bash
# preinstall.sh - native prerequisites for ubuntu (unix), Python 3.14.
#
# Scope: ONLY what a compiler and a few C extensions need to build. Nothing
# here fights a stubborn package; anything that cannot be built is isolated in
# requirements.experimental.txt instead.
#
# pychm is deliberately NOT installed here. PyPI has exactly one pychm wheel
# in its history (cp27, macOS), so every Python 3 install compiles it against
# the native chmlib. That is a per-package problem, not a toolchain problem.
set -euo pipefail

DISTRO="ubuntu"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log()  { printf '\033[1;34m[preinstall:ubuntu]\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[1;33m[preinstall:ubuntu]\033[0m %s\n' "$*" >&2; }
have() { command -v "$1" >/dev/null 2>&1; }

SUDO=""
detect_sudo() {
  if [ "$(id -u)" -eq 0 ]; then SUDO=""; return 0; fi
  if have sudo && sudo -n true 2>/dev/null; then SUDO="sudo"; return 0; fi
  SUDO=""; return 1
}

install_deps() {
  have apt-get || {{ warn "apt-get not found; skipping system packages"; return 0; }}
  detect_sudo || {{ warn "no passwordless sudo; skipping system packages"; return 0; }}
  # shellcheck disable=SC2086
  $SUDO env DEBIAN_FRONTEND=noninteractive apt-get update -qq
  # shellcheck disable=SC2086
  $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    build-essential ca-certificates curl git
  log "system build prerequisites present"
}

main() {
  install_deps
  log "preinstall complete for $DISTRO"
}

main "$@"
