#!/usr/bin/env bash
# preinstall.sh - native prerequisites for nixos (unix), Python 3.14.
#
# Scope: ONLY what a compiler and a few C extensions need to build. Nothing
# here fights a stubborn package; anything that cannot be built is isolated in
# requirements.experimental.txt instead.
#
# pychm is deliberately NOT installed here. PyPI has exactly one pychm wheel
# in its history (cp27, macOS), so every Python 3 install compiles it against
# the native chmlib. That is a per-package problem, not a toolchain problem.
set -euo pipefail

DISTRO="nixos"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log()  { printf '\033[1;34m[preinstall:nixos]\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[1;33m[preinstall:nixos]\033[0m %s\n' "$*" >&2; }
have() { command -v "$1" >/dev/null 2>&1; }

SUDO=""
detect_sudo() {
  if [ "$(id -u)" -eq 0 ]; then SUDO=""; return 0; fi
  if have sudo && sudo -n true 2>/dev/null; then SUDO="sudo"; return 0; fi
  SUDO=""; return 1
}

install_deps() {
  if have nix; then
    # Ad-hoc shell is enough; do not mutate a declarative system profile.
    log "nix available; use: nix-shell -p gcc git"
  else
    warn "nix not found; skipping"
  fi
}

main() {
  install_deps
  log "preinstall complete for $DISTRO"
}

main "$@"
