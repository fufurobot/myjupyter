"""Tests for the per-target packaging and the buildability split.

The design bar (set after CI proved the older approach wrong):

* every ``<platform>/<distro>/<python-version>`` holds a ``pyproject.toml``
  that is a real, buildable project;
* requirements are split by *buildability*, so one stubborn package can never
  turn the whole matrix red;
* ``pychm`` is isolated, not fought: PyPI has published exactly one pychm
  wheel in its history (cp27, macOS), so every Python 3 install compiles it
  against native chmlib.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import tomllib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load(name: str, rel: str):
    path = REPO_ROOT / rel
    if not path.is_file():
        pytest.fail(f"missing implementation file: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


cl = _load("check_layout", "scripts/check_layout.py")
st = _load("scaffold_targets", "scripts/scaffold_targets.py")

ALL_TARGETS = cl.all_targets()


def target_dir(platform: str, distro: str, version: str) -> pathlib.Path:
    return REPO_ROOT / platform / distro / version


# --------------------------------------------------------------------------
# Every target must be a real, buildable project
# --------------------------------------------------------------------------

class TestEveryTargetBuildable:
    def test_all_50_targets_exist(self):
        assert len(ALL_TARGETS) == 50

    @pytest.mark.parametrize("platform,distro,version", ALL_TARGETS)
    def test_has_pyproject(self, platform, distro, version):
        path = target_dir(platform, distro, version) / "pyproject.toml"
        assert path.is_file(), f"{platform}/{distro}/{version} has no pyproject.toml"

    @pytest.mark.parametrize("platform,distro,version", ALL_TARGETS)
    def test_pyproject_is_valid_toml(self, platform, distro, version):
        path = target_dir(platform, distro, version) / "pyproject.toml"
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        assert data["project"]["name"]
        assert data["build-system"]["build-backend"]

    @pytest.mark.parametrize("platform,distro,version", ALL_TARGETS)
    def test_pyproject_requires_the_target_python(self, platform, distro, version):
        path = target_dir(platform, distro, version) / "pyproject.toml"
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        assert data["project"]["requires-python"].startswith(f">={version}")

    @pytest.mark.parametrize("platform,distro,version", ALL_TARGETS)
    def test_has_a_buildable_module(self, platform, distro, version):
        d = target_dir(platform, distro, version)
        data = tomllib.loads((d / "pyproject.toml").read_text(encoding="utf-8"))
        modules = data.get("tool", {}).get("setuptools", {}).get("py-modules", [])
        assert modules, "setuptools needs at least one py-module to build"
        for module in modules:
            assert (d / f"{module}.py").is_file()

    @pytest.mark.parametrize("platform,distro,version", ALL_TARGETS)
    def test_readme_referenced_by_pyproject_exists(self, platform, distro, version):
        d = target_dir(platform, distro, version)
        data = tomllib.loads((d / "pyproject.toml").read_text(encoding="utf-8"))
        readme = data["project"].get("readme")
        if readme:
            assert (d / readme).is_file()

    @pytest.mark.parametrize("platform,distro,version", ALL_TARGETS)
    def test_module_records_its_target(self, platform, distro, version):
        d = target_dir(platform, distro, version)
        text = (d / "toolchain.py").read_text(encoding="utf-8")
        assert f'"distro": "{distro}"' in text
        assert f'"python": "{version}"' in text


# --------------------------------------------------------------------------
# Requirement split
# --------------------------------------------------------------------------

class TestRequirementSplit:
    @pytest.mark.parametrize("platform,distro,version", ALL_TARGETS)
    def test_core_requirements_exist(self, platform, distro, version):
        assert (target_dir(platform, distro, version) / "requirements.txt").is_file()

    @pytest.mark.parametrize("platform,distro,version", ALL_TARGETS)
    def test_experimental_requirements_exist(self, platform, distro, version):
        d = target_dir(platform, distro, version)
        assert (d / "requirements.experimental.txt").is_file()

    @pytest.mark.parametrize("platform,distro,version", ALL_TARGETS)
    def test_core_never_contains_pychm(self, platform, distro, version):
        """pychm always compiles on Python 3; it must not gate the matrix."""
        text = (target_dir(platform, distro, version) / "requirements.txt").read_text(
            encoding="utf-8"
        )
        assert "pychm" not in text

    @pytest.mark.parametrize("platform,distro,version", ALL_TARGETS)
    def test_pychm_lives_in_the_experimental_set(self, platform, distro, version):
        text = (target_dir(platform, distro, version)
                / "requirements.experimental.txt").read_text(encoding="utf-8")
        code = "\n".join(
            line for line in text.splitlines()
            if line.strip() and not line.strip().startswith("#")
        )
        assert "pychm" in code

    @pytest.mark.parametrize("platform,distro,version", ALL_TARGETS)
    def test_core_never_contains_jupyterhub(self, platform, distro, version):
        text = (target_dir(platform, distro, version) / "requirements.txt").read_text(
            encoding="utf-8"
        )
        assert "jupyterhub" not in text

    @pytest.mark.parametrize(
        "distro,version",
        [(d, "3.14") for d in ("ubuntu", "debian", "archlinux", "macos", "guix", "nixos")],
    )
    def test_unix_targets_have_a_jupyterhub_set(self, distro, version):
        d = target_dir("unix", distro, version)
        assert (d / "requirements-jupyterhub.txt").is_file()

    @pytest.mark.parametrize(
        "distro,version",
        [("winxp", "3.10"), ("win7", "3.10"), ("win10", "3.13"), ("win11", "3.13")],
    )
    def test_windows_targets_have_no_jupyterhub_set(self, distro, version):
        """jupyterhub needs PAM (pamela) and has no Windows authenticator."""
        d = target_dir("windows", distro, version)
        assert not (d / "requirements-jupyterhub.txt").exists()

    @pytest.mark.parametrize("platform,distro,version", ALL_TARGETS)
    def test_no_duplicate_packages_across_sets(self, platform, distro, version):
        d = target_dir(platform, distro, version)

        def pkgs(name):
            p = d / name
            if not p.is_file():
                return set()
            out = set()
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.split("#")[0].strip()
                if line and not line.startswith("-"):
                    out.add(line.split("=")[0].split(">")[0].split("<")[0].strip().lower())
            return out

        core = pkgs("requirements.txt")
        for other in ("requirements-jupyterhub.txt", "requirements.experimental.txt"):
            assert not (core & pkgs(other)), f"{other} overlaps requirements.txt"


# --------------------------------------------------------------------------
# Scaffolder as source of truth
# --------------------------------------------------------------------------

class TestScaffoldScript:
    def test_scaffold_covers_every_target(self, tmp_path):
        st.scaffold(tmp_path)
        for platform, distro, version in ALL_TARGETS:
            assert (tmp_path / platform / distro / version / "pyproject.toml").is_file()

    def test_scaffold_is_idempotent(self, tmp_path):
        st.scaffold(tmp_path)
        before = (tmp_path / "unix/ubuntu/3.14/requirements.txt").read_text()
        st.scaffold(tmp_path)
        after = (tmp_path / "unix/ubuntu/3.14/requirements.txt").read_text()
        assert before == after

    def test_scaffold_force_overwrites(self, tmp_path):
        st.scaffold(tmp_path)
        p = tmp_path / "unix/ubuntu/3.14/requirements.txt"
        p.write_text("local edit\n", encoding="utf-8")
        st.scaffold(tmp_path, force=True)
        assert "local edit" not in p.read_text()

    def test_scaffold_writes_new_lines_only(self, tmp_path):
        st.scaffold(tmp_path)
        raw = (tmp_path / "unix/ubuntu/3.14/preinstall.sh")
        if raw.exists():
            assert b"\r\n" not in raw.read_bytes()

    def test_next_minor(self):
        assert st.next_minor("3.10") == "3.11"
        assert st.next_minor("3.14") == "3.15"
