"""Unit tests for the canonical project layout.

Layout contract (from ``todo.md``)::

    <platform>/<distro>/<python-version>/

    platform       : windows | unix
    distro         : winxp win7 win10 win11 macos ubuntu debian archlinux guix nixos
    python-version : 3.10 .. 3.14  (inclusive, "to latest")

These tests are written **before** the implementation (TDD). They define the
behaviour of :mod:`scripts.check_layout` and its importable library module.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_check_layout():
    """Import ``scripts/check_layout.py`` as a module without needing a package."""
    path = REPO_ROOT / "scripts" / "check_layout.py"
    if not path.is_file():
        pytest.fail(f"missing implementation file: {path}")
    spec = importlib.util.spec_from_file_location("check_layout", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_layout"] = module
    spec.loader.exec_module(module)
    return module


cl = _load_check_layout()


# --------------------------------------------------------------------------
# Vocabularies
# --------------------------------------------------------------------------

class TestVocabularies:
    def test_platforms_are_exactly_windows_and_unix(self):
        assert set(cl.PLATFORMS) == {"windows", "unix"}

    @pytest.mark.parametrize(
        "distro",
        ["winxp", "win7", "win10", "win11", "macos",
         "ubuntu", "debian", "archlinux", "guix", "nixos"],
    )
    def test_required_distros_present(self, distro):
        assert distro in cl.DISTROS

    def test_distro_vocabulary_is_exactly_the_todo_list(self):
        assert set(cl.DISTROS) == {
            "winxp", "win7", "win10", "win11", "macos",
            "ubuntu", "debian", "archlinux", "guix", "nixos",
        }

    def test_python_versions_start_at_310(self):
        assert cl.PYTHON_VERSIONS[0] == "3.10"

    def test_python_versions_are_contiguous_from_310(self):
        assert list(cl.PYTHON_VERSIONS) == [
            "3.10", "3.11", "3.12", "3.13", "3.14",
        ]

    def test_latest_python_version_is_the_maximum(self):
        assert cl.latest_python_version() == max(
            cl.PYTHON_VERSIONS, key=lambda v: tuple(int(p) for p in v.split("."))
        )

    def test_no_python_version_below_310(self):
        for version in cl.PYTHON_VERSIONS:
            major, minor = (int(p) for p in version.split("."))
            assert (major, minor) >= (3, 10)


# --------------------------------------------------------------------------
# Platform / distro pairing
# --------------------------------------------------------------------------

class TestPlatformDistroPairing:
    @pytest.mark.parametrize("distro", ["winxp", "win7", "win10", "win11"])
    def test_windows_distros_belong_to_windows(self, distro):
        assert cl.platform_for_distro(distro) == "windows"

    @pytest.mark.parametrize(
        "distro", ["macos", "ubuntu", "debian", "archlinux", "guix", "nixos"]
    )
    def test_unix_distros_belong_to_unix(self, distro):
        assert cl.platform_for_distro(distro) == "unix"

    def test_every_distro_has_a_platform(self):
        for distro in cl.DISTROS:
            assert cl.platform_for_distro(distro) in cl.PLATFORMS

    def test_unknown_distro_is_rejected(self):
        with pytest.raises(ValueError):
            cl.platform_for_distro("plan9")

    @pytest.mark.parametrize(
        "distro", ["winxp", "win7", "win10", "win11", "macos",
                   "ubuntu", "debian", "archlinux", "guix", "nixos"]
    )
    def test_every_distro_declares_a_package_manager(self, distro):
        assert cl.package_manager_for_distro(distro) in cl.PACKAGE_MANAGERS

    def test_distro_package_managers_are_correct(self):
        assert cl.package_manager_for_distro("archlinux") == "pacman"
        assert cl.package_manager_for_distro("ubuntu") == "apt"
        assert cl.package_manager_for_distro("debian") == "apt"
        assert cl.package_manager_for_distro("guix") == "guix"
        assert cl.package_manager_for_distro("nixos") == "nix"
        assert cl.package_manager_for_distro("macos") == "brew"
        assert cl.package_manager_for_distro("win10") == "choco"


# --------------------------------------------------------------------------
# Target path computation
# --------------------------------------------------------------------------

class TestTargetPath:
    def test_target_path_has_three_segments(self):
        parts = cl.target_parts("unix", "archlinux", "3.14")
        assert parts == ("unix", "archlinux", "3.14")

    def test_valid_target_has_no_errors(self):
        assert cl.validate_target("unix", "archlinux", "3.14") == []

    def test_unknown_platform_reported(self):
        errors = cl.validate_target("plan9", "archlinux", "3.14")
        assert any("platform" in e.lower() for e in errors)

    def test_unknown_distro_reported(self):
        errors = cl.validate_target("unix", "plan9", "3.14")
        assert any("distro" in e.lower() for e in errors)

    def test_unknown_python_version_reported(self):
        errors = cl.validate_target("unix", "archlinux", "2.7")
        assert any("python" in e.lower() for e in errors)

    def test_mismatched_platform_and_distro_reported(self):
        errors = cl.validate_target("windows", "archlinux", "3.14")
        assert any("platform" in e.lower() for e in errors)

    def test_mismatched_platform_and_distro_for_windows(self):
        errors = cl.validate_target("unix", "win10", "3.14")
        assert any("platform" in e.lower() for e in errors)

    def test_all_errors_are_collected_not_just_the_first(self):
        errors = cl.validate_target("plan9", "plan9", "2.7")
        assert len(errors) >= 3


# --------------------------------------------------------------------------
# Tree scanning
# --------------------------------------------------------------------------

class TestScanTree:
    def test_scan_finds_a_valid_target(self, tmp_path):
        (tmp_path / "unix" / "archlinux" / "3.14").mkdir(parents=True)
        assert cl.scan_tree(tmp_path) == []

    def test_scan_reports_wrong_segment_count(self, tmp_path):
        (tmp_path / "py3.14" / "linux").mkdir(parents=True)
        errors = cl.scan_tree(tmp_path)
        assert errors, "legacy two-segment layout must be reported"

    def test_scan_reports_unknown_distro(self, tmp_path):
        (tmp_path / "unix" / "plan9" / "3.14").mkdir(parents=True)
        errors = cl.scan_tree(tmp_path)
        assert any("distro" in e.lower() for e in errors)

    def test_scan_reports_unknown_python_version(self, tmp_path):
        (tmp_path / "unix" / "debian" / "2.7").mkdir(parents=True)
        errors = cl.scan_tree(tmp_path)
        assert any("python" in e.lower() for e in errors)

    def test_scan_ignores_non_target_directories(self, tmp_path):
        (tmp_path / ".github" / "workflows").mkdir(parents=True)
        (tmp_path / "scripts").mkdir()
        (tmp_path / "tests").mkdir()
        (tmp_path / "docs").mkdir()
        (tmp_path / "unix" / "nixos" / "3.13").mkdir(parents=True)
        assert cl.scan_tree(tmp_path) == []

    def test_scan_ignores_dot_directories(self, tmp_path):
        (tmp_path / ".venv" / "lib" / "python3.14").mkdir(parents=True)
        assert cl.scan_tree(tmp_path) == []

    def test_scan_of_the_real_repository_is_clean(self):
        assert cl.scan_tree(REPO_ROOT) == []


# --------------------------------------------------------------------------
# Matrix generation
# --------------------------------------------------------------------------

class TestMatrix:
    def test_matrix_rows_are_dicts_with_expected_keys(self):
        rows = cl.build_matrix()
        assert rows, "matrix must not be empty"
        for row in rows:
            assert set(row) == {"platform", "distro", "python", "os", "pm", "full"}

    def test_matrix_covers_every_distro(self):
        covered = {row["distro"] for row in cl.build_matrix()}
        assert covered == set(cl.DISTROS)

    def test_matrix_python_versions_are_valid(self):
        for row in cl.build_matrix():
            assert row["python"] in cl.PYTHON_VERSIONS

    def test_fast_matrix_is_smaller_than_full_matrix(self):
        fast = cl.build_matrix(full=False)
        full = cl.build_matrix(full=True)
        assert len(fast) < len(full)

    def test_fast_matrix_uses_one_python_per_distro(self):
        fast = cl.build_matrix(full=False)
        seen: dict[str, int] = {}
        for row in fast:
            seen[row["distro"]] = seen.get(row["distro"], 0) + 1
        assert all(count == 1 for count in seen.values())

    def test_full_matrix_expands_python_versions_for_unix(self):
        full = cl.build_matrix(full=True)
        versions = {r["python"] for r in full if r["distro"] == "archlinux"}
        assert len(versions) == len(cl.PYTHON_VERSIONS)

    def test_matrix_pairs_each_distro_with_its_runner(self):
        for row in cl.build_matrix(full=True):
            assert row["os"] == cl.runner_for_distro(row["distro"])

    def test_matrix_carries_full_flag(self):
        assert all(r["full"] is False for r in cl.build_matrix(full=False))
        assert all(r["full"] is True for r in cl.build_matrix(full=True))

    def test_unknown_distro_raises(self):
        with pytest.raises(ValueError):
            cl.runner_for_distro("plan9")


class TestRunners:
    def test_windows_distros_use_windows_runners(self):
        for distro in ("winxp", "win7", "win10", "win11"):
            assert cl.runner_for_distro(distro).startswith("windows-")

    def test_macos_uses_a_macos_runner(self):
        assert cl.runner_for_distro("macos").startswith("macos-")

    def test_unix_distros_use_ubuntu_runners(self):
        for distro in ("ubuntu", "debian", "archlinux", "guix", "nixos"):
            assert cl.runner_for_distro(distro).startswith("ubuntu-")

    def test_every_distro_has_a_runner(self):
        for distro in cl.DISTROS:
            assert cl.runner_for_distro(distro)


# --------------------------------------------------------------------------
# libchm / pychm dependency metadata
# --------------------------------------------------------------------------

class TestLibchmPackages:
    """The pychm build needs the system chmlib, named differently per distro."""

    @pytest.mark.parametrize(
        "distro",
        ["archlinux", "ubuntu", "debian", "guix", "nixos", "macos"],
    )
    def test_unix_distros_declare_a_libchm_package(self, distro):
        assert cl.libchm_package_for_distro(distro)

    def test_known_libchm_package_names(self):
        assert cl.libchm_package_for_distro("archlinux") == "chmlib"
        assert cl.libchm_package_for_distro("debian") == "libchm-dev"
        assert cl.libchm_package_for_distro("ubuntu") == "libchm-dev"
        assert cl.libchm_package_for_distro("macos") == "chmlib"

    def test_unknown_distro_raises(self):
        with pytest.raises(ValueError):
            cl.libchm_package_for_distro("plan9")

    def test_pychm_is_declared_as_requiring_libchm(self):
        assert "pychm" in cl.NATIVE_BUILD_REQUIREMENTS
        assert cl.NATIVE_BUILD_REQUIREMENTS["pychm"]["library"] == "chm"
