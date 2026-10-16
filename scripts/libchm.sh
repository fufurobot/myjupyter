#!/usr/bin/env bash
# scripts/libchm.sh - shared, distro-agnostic libchm provisioning helper.
#
# WHY THIS EXISTS
# ---------------
# `pychm` publishes no wheels, so `pip install pychm` ALWAYS compiles
# `chm/_chmlib.c`, which does:
#
#     #include <chm_lib.h>      /* from the native chmlib library */
#     ...  -lchm               /* links the native chmlib shared object */
#
# On a machine without the native library the build dies with:
#
#     chm/chmlib_search.h:4:10: fatal error: chm_lib.h: No such file or directory
#
# The library is NOT named the same everywhere, which is exactly why this
# project has a <distro> layer instead of guessing at runtime:
#
#     Arch Linux      chmlib
#     Debian/Ubuntu   libchm-dev      (dev headers; `libchm1` is runtime only)
#     Guix            chmlib
#     NixOS           chmlib          (nixpkgs; also nix-shell -p chmlib)
#     macOS           chmlib          (Homebrew)
#     Windows         chmlib          (vcpkg / MSYS2)
#
# USAGE (from a distro preinstall.sh)
# -----------------------------------
#     . "$(dirname "$0")/../../../scripts/libchm.sh"
#     ensure_libchm
#
# The helper is written to be safe to source repeatedly and to never hang on
# an interactive sudo prompt: it probes with `sudo -n` first.

set -euo pipefail

LIBCHM_LOG_PREFIX="${LIBCHM_LOG_PREFIX:-libchm}"

libchm_log()  { printf '\033[1;34m[%s]\033[0m %s\n' "$LIBCHM_LOG_PREFIX" "$*" >&2; }
libchm_warn() { printf '\033[1;33m[%s]\033[0m %s\n' "$LIBCHM_LOG_PREFIX" "$*" >&2; }
libchm_err()  { printf '\033[1;31m[%s]\033[0m %s\n' "$LIBCHM_LOG_PREFIX" "$*" >&2; }

have() { command -v "$1" >/dev/null 2>&1; }

# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

# libchm_header_present -> 0 when chm_lib.h is on the default include path
libchm_header_present() {
  for dir in /usr/include /usr/local/include /opt/homebrew/include \
             /opt/local/include "${CHMLIB_PREFIX:-/nonexistent}/include"; do
    [ -f "$dir/chm_lib.h" ] && return 0
  done
  return 1
}

# libchm_library_present -> 0 when the linker can resolve -lchm
libchm_library_present() {
  if have ldconfig && ldconfig -p 2>/dev/null | grep -q 'libchm\.so'; then
    return 0
  fi
  for dir in /usr/lib /usr/lib64 /usr/local/lib /opt/homebrew/lib \
             /opt/local/lib "${CHMLIB_PREFIX:-/nonexistent}/lib"; do
    ls "$dir"/libchm.so* >/dev/null 2>&1 && return 0
  done
  return 1
}

# libchm_ok -> 0 when pychm can actually be compiled
libchm_ok() {
  libchm_header_present && libchm_library_present
}

# ---------------------------------------------------------------------------
# Privilege handling
# ---------------------------------------------------------------------------

# Set SUDO to "sudo" when we are not root and passwordless sudo works,
# to "" when we are already root, and leave it unset when we cannot elevate.
libchm_detect_sudo() {
  if [ "$(id -u)" -eq 0 ]; then
    SUDO=""
    return 0
  fi
  if have sudo && sudo -n true 2>/dev/null; then
    SUDO="sudo"
    return 0
  fi
  SUDO=""
  return 1
}

libchm_cannot_elevate() {
  libchm_err "cannot install the native chmlib: not root and passwordless sudo is unavailable."
  libchm_err "run this script with elevated privileges, or install the headers manually:"
  libchm_err "  archlinux : sudo pacman -S --needed chmlib"
  libchm_err "  debian    : sudo apt-get install -y libchm-dev"
  libchm_err "  ubuntu    : sudo apt-get install -y libchm-dev"
  libchm_err "  guix      : guix install chmlib"
  libchm_err "  nixos     : nix profile install nixpkgs#chmlib"
  libchm_err "  macos     : brew install chmlib"
}

# ---------------------------------------------------------------------------
# Per-distro installers
# ---------------------------------------------------------------------------

install_libchm_archlinux() {
  have pacman || { libchm_err "pacman not found"; return 1; }
  libchm_detect_sudo || { libchm_cannot_elevate; return 1; }
  # shellcheck disable=SC2086
  $SUDO pacman -S --needed --noconfirm chmlib
}

install_libchm_debian() {
  have apt-get || { libchm_err "apt-get not found"; return 1; }
  libchm_detect_sudo || { libchm_cannot_elevate; return 1; }
  # `libchm-dev` carries chm_lib.h; `libchm1` is the runtime-only library.
  # shellcheck disable=SC2086
  $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends libchm-dev
}

install_libchm_guix() {
  have guix || { libchm_err "guix not found"; return 1; }
  guix install chmlib
}

install_libchm_nixos() {
  if have nix; then
    # `nix profile install` works on both NixOS and plain Nix.
    nix profile install nixpkgs#chmlib
  elif have nix-shell; then
    libchm_warn "nix profile unavailable; use: nix-shell -p chmlib"
    return 1
  else
    libchm_err "nix not found"
    return 1
  fi
}

install_libchm_macos() {
  have brew || { libchm_err "Homebrew not found; see https://brew.sh"; return 1; }
  brew install chmlib
}

install_libchm_windows() {
  if have vcpkg; then
    vcpkg install chmlib
  elif have choco; then
    choco install -y chmlib
  elif have pacman; then           # MSYS2
    pacman -S --needed --noconfirm mingw-w64-ucrt-x86_64-chmlib
  else
    libchm_err "no vcpkg/choco/MSYS2 pacman found to provide chmlib"
    return 1
  fi
}

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

# ensure_libchm [distro]
#   Installs the native chmlib when absent, then verifies chm_lib.h is visible.
#   Returns 0 when pychm can be built, 1 otherwise.
ensure_libchm() {
  local distro="${1:-${DISTRO:-}}"

  if [ -z "$distro" ]; then
    libchm_err "ensure_libchm: distro not specified (pass it or set \$DISTRO)"
    return 1
  fi

  if libchm_ok; then
    libchm_log "native chmlib already present (headers + library); pychm can build"
    return 0
  fi

  libchm_log "native chmlib missing (this is the pychm build failure); installing for $distro"

  case "$distro" in
    archlinux)          install_libchm_archlinux ;;
    debian|ubuntu)      install_libchm_debian ;;
    guix)               install_libchm_guix ;;
    nixos)              install_libchm_nixos ;;
    macos)              install_libchm_macos ;;
    winxp|win7|win10|win11) install_libchm_windows ;;
    *) libchm_err "no libchm installer for distro '$distro'"; return 1 ;;
  esac || true

  # Refresh the linker cache when we can, so -lchm resolves immediately.
  if have ldconfig && libchm_detect_sudo; then
    # shellcheck disable=SC2086
    $SUDO ldconfig 2>/dev/null || true
  fi

  # Homebrew/MacPorts/Nix put things outside the default search path; export
  # the flags pychm's build needs so the compile step can find them.
  local brew_prefix=""
  if have brew; then brew_prefix="$(brew --prefix 2>/dev/null || true)"; fi
  for prefix in "$brew_prefix" "${CHMLIB_PREFIX:-}" /usr/local /opt/homebrew /opt/local; do
    [ -n "$prefix" ] || continue
    if [ -f "$prefix/include/chm_lib.h" ]; then
      export CFLAGS="${CFLAGS:-} -I$prefix/include"
      export LDFLAGS="${LDFLAGS:-} -L$prefix/lib"
      export CPATH="$prefix/include${CPATH:+:$CPATH}"
      export LIBRARY_PATH="$prefix/lib${LIBRARY_PATH:+:$LIBRARY_PATH}"
      libchm_log "exported CFLAGS/LDFLAGS for prefix $prefix"
      break
    fi
  done

  if libchm_ok; then
    libchm_log "success: chm_lib.h is available; pychm will compile"
    return 0
  fi

  libchm_err "chmlib still not visible after install; pychm will fail to build."
  libchm_err "hint: the header must exist at one of /usr/include, /usr/local/include,"
  libchm_err "      /opt/homebrew/include, /opt/local/include, or \$CHMLIB_PREFIX/include"
  return 1
}
