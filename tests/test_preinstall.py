"""Tests for the per-distro ``preinstall`` scripts.

Scope has been deliberately narrowed: the scripts install only native *build
prerequisites*, using each distro's own package manager. They no longer try to
coax a stubborn package (``pychm``/chmlib) into building - anything that
cannot be built is isolated in ``requirements.experimental.txt`` instead.

The distro layer still matters, because the package manager and the package
names differ per distribution.
"""

from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load(name: str, rel: str):
    path = REPO_ROOT / rel
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


cl = _load("check_layout", "scripts/check_layout.py")


def find_real_bash() -> str | None:
    """Return a POSIX bash that can parse a script.

    On Windows runners bare ``bash`` is the WSL stub, which fails for any
    argument ("Distributions can be installed by visiting the Microsoft
    Store"). Prefer Git for Windows / MSYS2 explicitly.
    """
    for candidate in (
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files\Git\usr\bin\bash.exe",
        r"C:\msys64\usr\bin\bash.exe",
        "bash",
    ):
        if candidate != "bash" and not pathlib.Path(candidate).is_file():
            continue
        try:
            probe = subprocess.run(
                [candidate, "-c", "echo ok"], capture_output=True, text=True, timeout=30
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if probe.returncode == 0 and "ok" in probe.stdout:
            return candidate
    return None


REAL_BASH = find_real_bash()


def target_dir(distro: str, filename: str = "preinstall.sh") -> pathlib.Path:
    """Return the ``<platform>/<distro>/<python-version>`` holding *filename*.

    A distro only curates native prerequisites for the python versions it
    actually targets, so prefer the directory that has the file.
    """
    base = REPO_ROOT / cl.platform_for_distro(distro) / distro
    candidates = [
        base / version for version in cl.PYTHON_VERSIONS if (base / version).is_dir()
    ]
    if not candidates:
        pytest.fail(f"no <python-version> directory under {base}")
    for candidate in candidates:
        if (candidate / filename).is_file():
            return candidate
    return candidates[0]


def preinstall_sh(distro: str) -> pathlib.Path:
    return target_dir(distro, "preinstall.sh") / "preinstall.sh"


def preinstall_ps1(distro: str) -> pathlib.Path:
    return target_dir(distro, "preinstall.ps1") / "preinstall.ps1"


# --------------------------------------------------------------------------
# Presence and shell hygiene
# --------------------------------------------------------------------------

class TestPresence:
    @pytest.mark.parametrize("distro", cl.DISTROS)
    def test_sh_exists(self, distro):
        assert preinstall_sh(distro).is_file()

    @pytest.mark.parametrize("distro", cl.DISTROS)
    def test_non_empty(self, distro):
        assert preinstall_sh(distro).read_text(encoding="utf-8").strip()

    @pytest.mark.parametrize("distro", cl.DISTROS)
    def test_has_shebang(self, distro):
        first = preinstall_sh(distro).read_text(encoding="utf-8").splitlines()[0]
        assert first.startswith("#!")

    @pytest.mark.parametrize("distro", cl.DISTROS)
    def test_uses_strict_mode(self, distro):
        assert "set -euo pipefail" in preinstall_sh(distro).read_text(encoding="utf-8")

    @pytest.mark.parametrize("distro", cl.DISTROS)
    def test_no_crlf(self, distro):
        assert b"\r\n" not in preinstall_sh(distro).read_bytes()

    @pytest.mark.parametrize("distro", cl.DISTROS)
    def test_parses_with_bash(self, distro):
        if REAL_BASH is None:
            pytest.skip("no usable POSIX bash available")
        result = subprocess.run(
            [REAL_BASH, "-n", str(preinstall_sh(distro))],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr

    @pytest.mark.parametrize("distro", ("winxp", "win7", "win10", "win11"))
    def test_windows_has_powershell_native_script(self, distro):
        assert preinstall_ps1(distro).is_file()

    @pytest.mark.parametrize("distro", ("winxp", "win7", "win10", "win11"))
    def test_powershell_has_balanced_braces(self, distro):
        text = preinstall_ps1(distro).read_text(encoding="utf-8")
        body = "\n".join(
            line for line in text.splitlines()
            if not line.strip().startswith("#")
        )
        assert body.count("{") == body.count("}")

    @pytest.mark.parametrize("distro", cl.DISTROS)
    def test_does_not_assume_root(self, distro):
        assert "/root/" not in preinstall_sh(distro).read_text(encoding="utf-8")

    @pytest.mark.parametrize("distro", cl.DISTROS)
    def test_never_hangs_on_sudo(self, distro):
        """Elevation must be probed non-interactively."""
        text = preinstall_sh(distro).read_text(encoding="utf-8")
        if "sudo" in text:
            assert "sudo -n" in text, (
                f"{distro} must probe with `sudo -n` so it cannot hang"
            )

    @pytest.mark.parametrize("distro", cl.DISTROS)
    def test_degrades_gracefully(self, distro):
        """A missing package manager must warn, not explode."""
        text = preinstall_sh(distro).read_text(encoding="utf-8")
        assert "warn" in text


# --------------------------------------------------------------------------
# Per-distro package manager correctness
# --------------------------------------------------------------------------

class TestPackageManagers:
    def test_archlinux_uses_pacman(self):
        text = preinstall_sh("archlinux").read_text(encoding="utf-8")
        assert "pacman" in text and "--needed" in text

    @pytest.mark.parametrize("distro", ("debian", "ubuntu"))
    def test_debian_family_uses_apt(self, distro):
        text = preinstall_sh(distro).read_text(encoding="utf-8")
        assert "apt-get" in text
        assert "DEBIAN_FRONTEND" in text, "must stay non-interactive"

    def test_macos_uses_brew(self):
        assert "brew" in preinstall_sh("macos").read_text(encoding="utf-8")

    def test_guix_uses_guix(self):
        text = preinstall_sh("guix").read_text(encoding="utf-8")
        assert "guix install" in text

    def test_nixos_mentions_nix(self):
        assert "nix" in preinstall_sh("nixos").read_text(encoding="utf-8")

    @pytest.mark.parametrize("distro", ("winxp", "win7", "win10", "win11"))
    def test_windows_uses_official_uv_installer(self, distro):
        text = preinstall_ps1(distro).read_text(encoding="utf-8")
        assert "astral.sh/uv/install.ps1" in text, (
            "official install method, not an assumed package manager"
        )

    def test_each_distro_mentions_itself(self):
        for distro in cl.DISTROS:
            text = preinstall_sh(distro).read_text(encoding="utf-8")
            assert distro in text


# --------------------------------------------------------------------------
# pychm is isolated, not fought
# --------------------------------------------------------------------------

class TestNoPychmFighting:
    """The old scripts tried to vendor/build chmlib. That is abandoned."""

    @pytest.mark.parametrize("distro", cl.DISTROS)
    def test_sh_does_not_build_chmlib(self, distro):
        text = preinstall_sh(distro).read_text(encoding="utf-8").lower()
        assert "chm_lib.h" not in text
        assert "cl.exe" not in text
        assert "vcvars" not in text

    @pytest.mark.parametrize("distro", ("winxp", "win7", "win10", "win11"))
    def test_ps1_does_not_build_chmlib(self, distro):
        text = preinstall_ps1(distro).read_text(encoding="utf-8").lower()
        assert "cl.exe" not in text
        assert "vcvars" not in text
        assert "chm_lib.c" not in text

    def test_ps1_documents_why_pychm_is_skipped(self):
        text = preinstall_ps1("win11").read_text(encoding="utf-8")
        assert "experimental" in text.lower(), (
            "the script should point at requirements.experimental.txt"
        )
        assert "cp27" in text or "wheel" in text.lower(), (
            "the reason pychm is excluded should be recorded"
        )
