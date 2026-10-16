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


def find_real_bash() -> str | None:
    """Return a POSIX bash that can actually parse a script.

    On Windows runners the bare ``bash`` on PATH is the **WSL stub**, which
    prints "Distributions can be installed by visiting the Microsoft Store"
    and exits 1 for any argument. Git for Windows ships the real bash; prefer
    it explicitly, then fall back to a verified bare ``bash``.
    """
    candidates = [
        # Git for Windows (the real thing on a Windows runner).
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files\Git\usr\bin\bash.exe",
        r"C:\Program Files (x86)\Git\bin\bash.exe",
        # MSYS2.
        r"C:\msys64\usr\bin\bash.exe",
        r"C:\msys64\ucrt64\bin\bash.exe",
        # Everything else.
        "bash",
    ]
    for candidate in candidates:
        if candidate != "bash" and not Path(candidate).is_file():
            continue
        try:
            probe = subprocess.run(
                [candidate, "-c", "echo ok"],
                capture_output=True, text=True, timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if probe.returncode == 0 and "ok" in probe.stdout:
            return candidate
    return None


REAL_BASH = find_real_bash()


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
        if REAL_BASH is None:
            pytest.skip("no usable POSIX bash available (Windows WSL stub only)")
        result = subprocess.run(
            [REAL_BASH, "-n", str(preinstall_path(distro))],
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


# --------------------------------------------------------------------------
# Line endings (regression: CI on Windows checked .sh files out as CRLF)
# --------------------------------------------------------------------------

class TestLineEndingsPinned:
    """Shell scripts must stay LF even when checked out on Windows.

    Without ``.gitattributes`` Git's ``core.autocrlf`` rewrites ``*.sh`` to CRLF
    on Windows runners, and ``bash script.sh`` then fails with
    ``$'\\r': command not found``. The repository must pin this, not rely on
    each developer's Git configuration.
    """

    def test_gitattributes_exists(self):
        assert (REPO_ROOT / ".gitattributes").is_file(), (
            "a .gitattributes is required to pin line endings across platforms"
        )

    def test_gitattributes_pins_sh_to_lf(self):
        text = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8")
        assert re.search(r"^\*\.sh\s+.*eol=lf", text, re.MULTILINE), (
            "*.sh must be pinned to eol=lf"
        )

    def test_gitattributes_pins_ps1_to_crlf(self):
        text = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8")
        assert re.search(r"^\*\.ps1\s+.*eol=crlf", text, re.MULTILINE), (
            "*.ps1 must be pinned to eol=crlf for PowerShell"
        )

    def test_gitattributes_pins_python_to_lf(self):
        text = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8")
        assert re.search(r"^\*\.py\s+.*eol=lf", text, re.MULTILINE)

    def test_gitattributes_marks_shell_scripts_as_text(self):
        text = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8")
        assert "text" in text

    @pytest.mark.parametrize("distro", cl.DISTROS)
    def test_git_index_stores_sh_with_lf(self, distro):
        """The blob in Git must contain no CR, whatever the working tree has."""
        rel = preinstall_path(distro).relative_to(REPO_ROOT).as_posix()
        result = subprocess.run(
            ["git", "show", f"HEAD:{rel}"],
            cwd=REPO_ROOT, capture_output=True,
        )
        if result.returncode != 0:
            pytest.skip(f"{rel} not committed yet")
        assert b"\r\n" not in result.stdout, (
            f"{rel} is stored in Git with CRLF and will break on unix"
        )


# --------------------------------------------------------------------------
# Windows provisioning robustness (regression: vcpkg's chmlib port is broken)
# --------------------------------------------------------------------------

class TestWindowsLibchmRobustness:
    """The vcpkg ``chmlib`` port currently fails: upstream jedrea.com 404s.

    Windows provisioning therefore must not depend on a single source, and
    must not hard-fail the whole preinstall when only chmlib is unavailable.
    """

    def test_ps1_falls_back_beyond_a_single_source(self):
        text = (REPO_ROOT / "windows" / "win11" / "3.13" / "preinstall.ps1").read_text(
            encoding="utf-8"
        )
        sources = sum(
            marker in text.lower()
            for marker in ("vcpkg", "choco", "pacman", "winget", "msys")
        )
        assert sources >= 3, (
            "preinstall.ps1 must try several providers, since any one can be broken"
        )

    def test_ps1_does_not_hard_fail_when_chmlib_is_unavailable(self):
        text = (REPO_ROOT / "windows" / "win11" / "3.13" / "preinstall.ps1").read_text(
            encoding="utf-8"
        )
        # It must warn and continue rather than `exit 1` on a merely optional dep.
        assert "Write-Warn" in text

    def test_ps1_exports_include_and_lib_paths_for_pip(self):
        text = (REPO_ROOT / "windows" / "win11" / "3.13" / "preinstall.ps1").read_text(
            encoding="utf-8"
        )
        assert "INCLUDE" in text or "CFLAGS" in text, (
            "pip needs INCLUDE/CFLAGS pointing at chmlib to compile pychm"
        )

    def test_ps1_documents_the_known_broken_port(self):
        text = (REPO_ROOT / "windows" / "win11" / "3.13" / "preinstall.ps1").read_text(
            encoding="utf-8"
        )
        assert "jedrea" in text or "404" in text or "known" in text.lower(), (
            "the broken upstream vcpkg port should be documented to save debugging"
        )

    def test_ps1_targets_a_real_chmlib_artifact(self):
        """If it downloads chmlib itself, the URL must not be the dead one.

        Only *code* is inspected: the dead URL is deliberately documented in a
        comment so the next person does not repeat the investigation.
        """
        text = (REPO_ROOT / "windows" / "win11" / "3.13" / "preinstall.ps1").read_text(
            encoding="utf-8"
        )
        code_lines = [
            line for line in text.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        code = "\n".join(code_lines)
        assert "jedrea.com/chmlib/chmlib-0.40.zip" not in code, (
            "the download URL is dead (404); do not use it in live code"
        )

    def test_ps1_download_url_is_used_in_code(self):
        """The replacement source must actually be wired into executable code."""
        text = (REPO_ROOT / "windows" / "win11" / "3.13" / "preinstall.ps1").read_text(
            encoding="utf-8"
        )
        code_lines = [
            line for line in text.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        assert any("Invoke-WebRequest" in line for line in code_lines), (
            "expected an actual download call for the source fallback"
        )


class TestWindowsDiagnostics:
    """A silent failure is worse than a loud one.

    In CI run 38858291896 the source build reported only "produced no
    chm_lib.h". After making the output visible, CI run 38858735096 revealed
    the real cause: jedwing/CHMLib has no CMakeLists.txt at all (it is
    autotools), so the whole CMake strategy was wrong.
    """

    def _ps1(self) -> str:
        return (REPO_ROOT / "windows" / "win11" / "3.13" / "preinstall.ps1").read_text(
            encoding="utf-8"
        )

    def test_checks_compiler_exit_codes(self):
        text = self._ps1()
        assert "$LASTEXITCODE" in text, (
            "the build must check the compiler's exit code explicitly"
        )

    def test_surfaces_the_failure_reason(self):
        text = self._ps1()
        assert "Write-Warn" in text
        # Every failure path must explain itself.
        assert "failed" in text.lower()

    def test_does_not_use_cmake_for_chmlib(self):
        """CHMLib is autotools-only; invoking CMake on it cannot work."""
        text = self._ps1()
        body = text.split("function Install-LibchmFromSource")[1]
        body = body.split("function Install-Libchm(")[0]
        assert "cmake -S" not in body and "cmake --build" not in body, (
            "jedwing/CHMLib has no CMakeLists.txt; do not drive it with CMake"
        )

    def test_compiles_the_real_chmlib_sources(self):
        text = self._ps1()
        assert "chm_lib.c" in text
        assert "lzx.c" in text, "chmlib needs lzx.c for LZX decompression"

    def test_documents_why_cmake_is_unusable(self):
        text = self._ps1()
        assert "CMakeLists.txt" in text or "autotools" in text, (
            "the reason CMake is avoided should be recorded"
        )

    def test_reports_the_known_broken_vcpkg_port(self):
        text = self._ps1()
        assert "jedrea" in text or "404" in text

    def test_does_not_swallow_the_compiler_output(self):
        text = self._ps1()
        bad = [
            line.strip() for line in text.splitlines()
            if ("cl.exe" in line or "lib.exe" in line) and "Out-Null" in line
        ]
        assert not bad, f"compiler output is discarded on: {bad}"

    def test_exports_paths_pip_needs(self):
        text = self._ps1()
        assert "INCLUDE" in text and "LIB" in text, (
            "pip needs INCLUDE/LIB pointing at chmlib to compile pychm"
        )

    def test_imports_the_msvc_environment_before_compiling(self):
        """A bare PowerShell session has no cl.exe on PATH.

        CI run 38859143235 proved this: the sources downloaded correctly and
        then died with "The term 'cl.exe' is not recognized". cl.exe/lib.exe
        live behind vcvars64.bat, so the script must import that environment
        (via vswhere) before compiling.
        """
        text = self._ps1()
        assert "vswhere" in text, (
            "must locate Visual Studio with vswhere to find vcvarsall"
        )
        assert "vcvars64.bat" in text, (
            "must import the MSVC environment from vcvars64.bat"
        )

    def test_reports_a_missing_compiler_clearly(self):
        text = self._ps1()
        assert "no C compiler found" in text, (
            "a missing compiler must be reported with remediation"
        )

    def test_offers_a_non_msvc_compiler_fallback(self):
        text = self._ps1()
        assert "clang" in text.lower() or "gcc" in text.lower(), (
            "clang/gcc should be accepted when MSVC is unavailable"
        )

    def test_defines_win32_for_msvc(self):
        """chm_lib.c tests `#ifdef WIN32`, but MSVC predefines only `_WIN32`.

        Without an explicit /DWIN32 the upstream code takes the Linux branch
        and does `#include <unistd.h>`, which does not exist on MSVC, so
        cl.exe exits 2. Verified by preprocessing the real sources:

            gcc -E            chm_lib.c  -> includes unistd.h
            gcc -E -DWIN32    chm_lib.c  -> includes windows.h
        """
        text = self._ps1()
        assert "/DWIN32" in text, (
            "cl.exe must be given /DWIN32 or chmlib compiles the POSIX branch"
        )

    def test_documents_why_win32_is_needed(self):
        text = self._ps1()
        assert "unistd.h" in text, (
            "the reason /DWIN32 is required should be documented"
        )
