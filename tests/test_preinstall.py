"""Unit tests for the per-distro ``preinstall.sh`` scripts.

The scripts must be **idempotent**, **shellcheck-clean in spirit**, and must
provision the native ``chmlib`` that ``pychm`` links against, using each
distro's *own* package manager (that is the whole reason the ``<distro>``
layer exists).
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_check_layout():
    path = REPO_ROOT / "scripts" / "check_layout.py"
    spec = importlib.util.spec_from_file_location("check_layout", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_layout"] = module
    spec.loader.exec_module(module)
    return module


cl = _load_check_layout()

TARGETS = [(d, cl.platform_for_distro(d)) for d in cl.DISTROS]


def target_dir(distro: str) -> Path:
    """Return the existing ``<platform>/<distro>/<python-version>`` directory.

    Any supported python version is acceptable: a distro may target several,
    and the preinstall script then lives in each of them.
    """
    base = REPO_ROOT / cl.platform_for_distro(distro) / distro
    for version in cl.PYTHON_VERSIONS:
        candidate = base / version
        if candidate.is_dir():
            return candidate
    pytest.fail(f"no <python-version> directory under {base}")


def preinstall_path(distro: str) -> Path:
    return target_dir(distro) / "preinstall.sh"


# --------------------------------------------------------------------------
# Existence and basic shell hygiene
# --------------------------------------------------------------------------

class TestScriptPresence:
    @pytest.mark.parametrize("distro", cl.DISTROS)
    def test_preinstall_script_exists(self, distro):
        assert preinstall_path(distro).is_file(), (
            f"missing preinstall.sh for {distro}"
        )

    @pytest.mark.parametrize("distro", cl.DISTROS)
    def test_script_is_non_empty(self, distro):
        assert preinstall_path(distro).read_text(encoding="utf-8").strip()

    @pytest.mark.parametrize("distro", cl.DISTROS)
    def test_script_starts_with_a_shebang(self, distro):
        first = preinstall_path(distro).read_text(encoding="utf-8").splitlines()[0]
        assert first.startswith("#!"), f"{distro} preinstall.sh has no shebang"

    @pytest.mark.parametrize("distro", cl.DISTROS)
    def test_script_uses_strict_mode(self, distro):
        text = preinstall_path(distro).read_text(encoding="utf-8")
        assert "set -euo pipefail" in text, f"{distro} does not use strict mode"

    @pytest.mark.parametrize("distro", cl.DISTROS)
    def test_script_has_no_crlf_line_endings(self, distro):
        raw = preinstall_path(distro).read_bytes()
        assert b"\r\n" not in raw, (
            f"{distro} preinstall.sh has CRLF endings and will not run on unix"
        )

    @pytest.mark.parametrize("distro", cl.DISTROS)
    def test_script_is_parseable_by_bash(self, distro):
        result = subprocess.run(
            ["bash", "-n", str(preinstall_path(distro))],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr


# --------------------------------------------------------------------------
# The pychm / libchm fix
# --------------------------------------------------------------------------

class TestLibchmProvisioning:
    @pytest.mark.parametrize("distro", cl.DISTROS)
    def test_script_mentions_pychm(self, distro):
        text = preinstall_path(distro).read_text(encoding="utf-8")
        assert "pychm" in text, f"{distro} preinstall.sh does not handle pychm"

    @pytest.mark.parametrize("distro", cl.DISTROS)
    def test_script_installs_the_distro_libchm_package(self, distro):
        text = preinstall_path(distro).read_text(encoding="utf-8")
        package = cl.libchm_package_for_distro(distro)
        assert package in text, (
            f"{distro} preinstall.sh does not install its libchm package "
            f"{package!r}"
        )

    @pytest.mark.parametrize("distro", cl.DISTROS)
    def test_script_uses_its_own_package_manager(self, distro):
        text = preinstall_path(distro).read_text(encoding="utf-8")
        pm = cl.package_manager_for_distro(distro)
        assert pm in text, (
            f"{distro} preinstall.sh does not use its package manager {pm!r}"
        )

    @pytest.mark.parametrize("distro", cl.DISTROS)
    def test_script_guards_against_missing_sudo_interactively(self, distro):
        """Non-interactive sudo must fail fast with guidance, not hang."""
        text = preinstall_path(distro).read_text(encoding="utf-8")
        assert "sudo" in text
        assert "-n" in text, (
            f"{distro} must probe sudo non-interactively (sudo -n) to avoid "
            "hanging on a password prompt"
        )

    @pytest.mark.parametrize("distro", ["archlinux", "ubuntu", "debian", "macos"])
    def test_script_verifies_the_header_not_just_the_package(self, distro):
        text = preinstall_path(distro).read_text(encoding="utf-8")
        assert "chm_lib.h" in text, (
            f"{distro} must verify chm_lib.h exists, since the package name "
            "does not guarantee the header"
        )

    @pytest.mark.parametrize("distro", cl.DISTROS)
    def test_script_reports_actionable_failure(self, distro):
        text = preinstall_path(distro).read_text(encoding="utf-8")
        assert re.search(r"\berr\b|error", text), (
            f"{distro} has no error reporting"
        )

    @pytest.mark.parametrize("distro", cl.DISTROS)
    def test_script_is_idempotent_by_checking_before_installing(self, distro):
        text = preinstall_path(distro).read_text(encoding="utf-8")
        assert "have " in text or "command -v" in text, (
            f"{distro} does not check whether things are already installed"
        )


# --------------------------------------------------------------------------
# Per-distro package manager correctness
# --------------------------------------------------------------------------

class TestPackageManagerCommands:
    def test_archlinux_uses_pacman_sync_and_needed(self):
        text = preinstall_path("archlinux").read_text(encoding="utf-8")
        assert "pacman" in text
        assert "--needed" in text

    def test_debian_and_ubuntu_use_apt_get(self):
        for distro in ("debian", "ubuntu"):
            text = preinstall_path(distro).read_text(encoding="utf-8")
            assert "apt-get" in text, f"{distro} should use apt-get"
            assert "DEBIAN_FRONTEND" in text, (
                f"{distro} must set DEBIAN_FRONTEND to stay non-interactive"
            )

    def test_macos_uses_brew(self):
        text = preinstall_path("macos").read_text(encoding="utf-8")
        assert "brew" in text

    def test_guix_uses_guix_install(self):
        text = preinstall_path("guix").read_text(encoding="utf-8")
        assert "guix" in text

    def test_nixos_mentions_nix_or_configuration(self):
        text = preinstall_path("nixos").read_text(encoding="utf-8")
        assert "nix" in text

    def test_windows_distros_reference_choco_or_vcpkg(self):
        for distro in ("winxp", "win7", "win10", "win11"):
            text = preinstall_path(distro).read_text(encoding="utf-8")
            assert "choco" in text or "vcpkg" in text, (
                f"{distro} must use a windows package manager"
            )

    def test_windows_scripts_do_not_require_bash_only_features(self):
        """A .ps1 sibling must exist so Windows can actually run the logic."""
        for distro in ("winxp", "win7", "win10", "win11"):
            assert (preinstall_path(distro).parent / "preinstall.ps1").is_file()

    @pytest.mark.parametrize("distro", cl.DISTROS)
    def test_no_hardcoded_root_only_path(self, distro):
        text = preinstall_path(distro).read_text(encoding="utf-8")
        assert "/root/" not in text, f"{distro} hardcodes /root"
