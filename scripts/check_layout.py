#!/usr/bin/env python3
"""Canonical project layout for **myjupyter**.

The repository organises per-environment dependency sets as::

    <platform>/<distro>/<python-version>/

    platform       : windows | unix
    distro         : winxp win7 win10 win11 macos ubuntu debian archlinux guix nixos
    python-version : 3.10, 3.11, 3.12, 3.13, 3.14 (3.10 .. latest)

Why a ``distro`` layer exists
-----------------------------
The same logical prerequisite is named and installed differently on every
distribution.  ``pychm`` is the canonical example: it is sdist-only and links
against the system *chmlib*, which is ``chmlib`` on Arch, ``libchm-dev`` on
Debian/Ubuntu, ``chmlib`` on Guix/Nix, and ``chmlib`` on macOS via Homebrew.
Encoding that in a ``distro`` layer keeps the per-distro package manager
(``pacman``/``apt``/``guix``/``nix``/``brew``/``choco``) explicit instead of
guessing at runtime.

This module is both a **library** (imported by tests and the CI matrix
generator) and a **CLI** (``python3 scripts/check_layout.py``).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Iterable, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------------
# Vocabularies
# --------------------------------------------------------------------------

PLATFORMS: tuple[str, ...] = ("windows", "unix")

DISTROS: tuple[str, ...] = (
    "winxp",
    "win7",
    "win10",
    "win11",
    "macos",
    "ubuntu",
    "debian",
    "archlinux",
    "guix",
    "nixos",
)

PYTHON_VERSIONS: tuple[str, ...] = (
    "3.10",
    "3.11",
    "3.12",
    "3.13",
    "3.14",
)

DISTRO_PLATFORM: dict[str, str] = {
    "winxp": "windows",
    "win7": "windows",
    "win10": "windows",
    "win11": "windows",
    "macos": "unix",
    "ubuntu": "unix",
    "debian": "unix",
    "archlinux": "unix",
    "guix": "unix",
    "nixos": "unix",
}

#: Native package manager per distribution.
DISTRO_PACKAGE_MANAGER: dict[str, str] = {
    "winxp": "choco",
    "win7": "choco",
    "win10": "choco",
    "win11": "choco",
    "macos": "brew",
    "ubuntu": "apt",
    "debian": "apt",
    "archlinux": "pacman",
    "guix": "guix",
    "nixos": "nix",
}

#: GitHub-hosted runner label per distribution.
DISTRO_RUNNER: dict[str, str] = {
    "winxp": "windows-2022",
    "win7": "windows-2022",
    "win10": "windows-2022",
    "win11": "windows-2022",
    "macos": "macos-14",
    "ubuntu": "ubuntu-24.04",
    "debian": "ubuntu-24.04",
    "archlinux": "ubuntu-24.04",
    "guix": "ubuntu-24.04",
    "nixos": "ubuntu-24.04",
}

#: Distribution package providing the ``chm`` library that ``pychm`` links to.
DISTRO_LIBCHM_PACKAGE: dict[str, str] = {
    "winxp": "chmlib",
    "win7": "chmlib",
    "win10": "chmlib",
    "win11": "chmlib",
    "macos": "chmlib",
    "ubuntu": "libchm-dev",
    "debian": "libchm-dev",
    "archlinux": "chmlib",
    "guix": "chmlib",
    "nixos": "chmlib",
}

PACKAGE_MANAGERS: tuple[str, ...] = ("choco", "brew", "apt", "pacman", "guix", "nix")

#: Python packages that need a system C library to build from source.
#: ``pychm`` is sdist-only, so ``pip install pychm`` *always* compiles and
#: fails with ``fatal error: chm_lib.h: No such file or directory`` when the
#: native ``chmlib`` is missing.
NATIVE_BUILD_REQUIREMENTS: dict[str, dict[str, str]] = {
    "pychm": {
        "library": "chm",
        "header": "chm_lib.h",
        "reason": "sdist-only; _chmlib.c includes <chm_lib.h> and links -lchm",
    },
}

#: Directories that never take part in the target layout.
IGNORED_TOP_LEVEL: frozenset[str] = frozenset(
    {
        ".git",
        ".github",
        ".devcontainer",
        ".venv",
        ".ci",
        "scripts",
        "tests",
        "docs",
        "site",
        "_site",
        "dist",
        "build",
        "node_modules",
    }
)

_SEGMENT_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


# --------------------------------------------------------------------------
# Lookups
# --------------------------------------------------------------------------

def platform_for_distro(distro: str) -> str:
    """Return the platform owning *distro*, or raise :class:`ValueError`."""
    try:
        return DISTRO_PLATFORM[distro]
    except KeyError:
        raise ValueError(f"unknown distro: {distro!r}") from None


def package_manager_for_distro(distro: str) -> str:
    """Return the native package manager for *distro*."""
    try:
        return DISTRO_PACKAGE_MANAGER[distro]
    except KeyError:
        raise ValueError(f"unknown distro: {distro!r}") from None


def runner_for_distro(distro: str) -> str:
    """Return the GitHub Actions runner label for *distro*."""
    try:
        return DISTRO_RUNNER[distro]
    except KeyError:
        raise ValueError(f"unknown distro: {distro!r}") from None


def libchm_package_for_distro(distro: str) -> str:
    """Return the distro package that provides the ``chm`` system library."""
    try:
        return DISTRO_LIBCHM_PACKAGE[distro]
    except KeyError:
        raise ValueError(f"unknown distro: {distro!r}") from None


def latest_python_version() -> str:
    """Return the newest supported python version."""
    return max(
        PYTHON_VERSIONS, key=lambda v: tuple(int(p) for p in v.split("."))
    )


def target_parts(platform: str, distro: str, python: str) -> tuple[str, str, str]:
    """Return the canonical three-segment relative path."""
    return (platform, distro, python)


def target_path(platform: str, distro: str, python: str) -> Path:
    """Return the absolute canonical path for a target triple."""
    return REPO_ROOT.joinpath(*target_parts(platform, distro, python))


def all_targets() -> list[tuple[str, str, str]]:
    """Return every valid ``(platform, distro, python)`` triple."""
    return [
        (DISTRO_PLATFORM[distro], distro, version)
        for distro in DISTROS
        for version in PYTHON_VERSIONS
    ]


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

def validate_target(platform: str, distro: str, python: str) -> list[str]:
    """Validate one target triple, returning **all** problems found."""
    errors: list[str] = []

    if platform not in PLATFORMS:
        errors.append(
            f"unknown platform {platform!r}; expected one of {', '.join(PLATFORMS)}"
        )

    if distro not in DISTROS:
        errors.append(
            f"unknown distro {distro!r}; expected one of {', '.join(DISTROS)}"
        )
    elif platform in PLATFORMS:
        expected = DISTRO_PLATFORM[distro]
        if expected != platform:
            errors.append(
                f"platform {platform!r} does not match distro {distro!r} "
                f"(expected platform {expected!r})"
            )

    if python not in PYTHON_VERSIONS:
        errors.append(
            f"unknown python version {python!r}; expected one of "
            f"{', '.join(PYTHON_VERSIONS)} (3.10 to latest)"
        )

    for name, value in (("platform", platform), ("distro", distro)):
        if not _SEGMENT_RE.match(value):
            errors.append(f"{name} segment {value!r} is not a valid path segment")

    return errors


def iter_target_dirs(root: Path) -> Iterable[tuple[Path, tuple[str, ...]]]:
    """Yield ``(path, relative_parts)`` for every ``<platform>/<distro>/<py>``.

    Only directories exactly three levels below *root* whose first segment is a
    known platform are yielded; everything else is traversal scaffolding and is
    validated separately.
    """
    platform_dirs = sorted(
        p for p in root.iterdir() if p.is_dir() and p.name in PLATFORMS
    )
    for platform_dir in platform_dirs:
        for distro_dir in sorted(p for p in platform_dir.iterdir() if p.is_dir()):
            for py_dir in sorted(p for p in distro_dir.iterdir() if p.is_dir()):
                yield py_dir, (platform_dir.name, distro_dir.name, py_dir.name)


def scan_tree(root: Path | str = REPO_ROOT) -> list[str]:
    """Return every layout violation in the repository tree at *root*."""
    root = Path(root)
    errors: list[str] = []

    if not root.is_dir():
        return [f"not a directory: {root}"]

    # 1. Every three-level target directory must be a valid triple.
    for path, parts in iter_target_dirs(root):
        rel = path.relative_to(root).as_posix()
        errors.extend(f"{rel}: {err}" for err in validate_target(*parts))

    # 2. The legacy <python-version>/<dir> layout must be reported, so the
    #    migration cannot silently regress.
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or entry.name in IGNORED_TOP_LEVEL:
            continue
        if entry.name.startswith("."):
            continue
        if entry.name in PLATFORMS:
            # Valid nesting is checked above; only look for stray segment counts.
            for distro_dir in sorted(p for p in entry.iterdir() if p.is_dir()):
                if distro_dir.name not in DISTROS:
                    errors.append(
                        f"{entry.name}/{distro_dir.name}: unknown distro "
                        f"{distro_dir.name!r}; expected one of "
                        f"{', '.join(DISTROS)}"
                    )
                    continue
                for py_dir in sorted(p for p in distro_dir.iterdir() if p.is_dir()):
                    if py_dir.name not in PYTHON_VERSIONS:
                        errors.append(
                            f"{entry.name}/{distro_dir.name}/{py_dir.name}: "
                            f"unknown python version {py_dir.name!r}; expected "
                            f"one of {', '.join(PYTHON_VERSIONS)}"
                        )
            continue

        # Anything else at top level that is not a known ignored dir is wrong.
        errors.append(
            f"{entry.name}: unexpected top-level directory; expected one of "
            f"{', '.join(PLATFORMS)}"
        )

    return errors


# --------------------------------------------------------------------------
# CI matrix
# --------------------------------------------------------------------------

def build_matrix(full: bool = False) -> list[dict]:
    """Build the CI matrix.

    *fast* (``full=False``) — one python version per distro; used by ``dev``.
    *full* (``full=True``)  — every supported python version per distro; used
    by ``main`` and release tags.
    """
    rows: list[dict] = []
    for distro in DISTROS:
        platform = DISTRO_PLATFORM[distro]
        versions: Sequence[str] = (
            PYTHON_VERSIONS if full else (latest_python_version(),)
        )
        for version in versions:
            rows.append(
                {
                    "platform": platform,
                    "distro": distro,
                    "python": version,
                    "os": DISTRO_RUNNER[distro],
                    "pm": DISTRO_PACKAGE_MANAGER[distro],
                    "full": full,
                }
            )
    return rows


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=str(REPO_ROOT))
    parser.add_argument(
        "--matrix",
        choices=("fast", "full"),
        help="emit the CI matrix as JSON instead of validating the tree",
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    if args.matrix:
        print(json.dumps(build_matrix(full=args.matrix == "full")))
        return 0

    errors = scan_tree(args.root)
    if errors:
        for err in errors:
            print(f"layout error: {err}", file=sys.stderr)
        return 1

    if not args.quiet:
        targets = sorted(iter_target_dirs(Path(args.root)))
        print(f"layout OK: {len(targets)} target(s)")
        for path, parts in targets:
            print(f"  {'/'.join(parts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
