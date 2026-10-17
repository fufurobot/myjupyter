#!/usr/bin/env bash
# preinstall.sh - Git Bash / MSYS2 entry point for win10 on Windows.
#
# The native path is preinstall.ps1; this exists so scripts that assume a
# POSIX shell still work. It deliberately does not attempt to build pychm.
set -euo pipefail
DISTRO="win10"
log()  { printf '\033[1;34m[preinstall:%s]\033[0m %s\n' "$DISTRO" "$*" >&2; }
warn() { printf '\033[1;33m[preinstall:%s]\033[0m %s\n' "$DISTRO" "$*" >&2; }

log "Windows targets use preinstall.ps1 for native setup"
if command -v uv >/dev/null 2>&1; then
  log "uv present: $(uv --version)"
else
  warn "uv not found; install it with: powershell -c \"irm https://astral.sh/uv/install.ps1 | iex\""
fi
log "preinstall complete for $DISTRO"
