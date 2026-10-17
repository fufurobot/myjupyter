"""Sprint 2 tests: per-distro requirements, startability, releases, dependabot.

Encodes the backlog clarifications:

1. ``requirements.txt`` is **broad by design** and per-distro: it holds what is
   installable only under that distro. The leaf ``pyproject.toml`` must *add*
   those requirements (``uv add -r requirements.txt``) so CI's
   ``uv sync --upgrade`` can turn upstream drift into a PR against ``dev``.
2. GitHub Pages is out. What matters is that **Jupyter actually starts**:
   ``jupyter lab`` on Windows, ``jupyterhub`` on Unix — proven in CI.
3. Dependabot must target ``dev`` so its PRs land on the dev branch.
4. Every push to ``main`` publishes a release of everything under ``uv build``;
   an unchanged ``pyproject.toml`` version updates the release **in place**,
   a changed version creates a **new** release.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import tomllib

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOWS = REPO_ROOT / ".github" / "workflows"


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

ALL_TARGETS = cl.all_targets()
UNIX_TARGETS = [t for t in ALL_TARGETS if t[0] == "unix"]
WIN_TARGETS = [t for t in ALL_TARGETS if t[0] == "windows"]


# ==========================================================================
# 1. Per-distro requirements, added into the leaf pyproject
# ==========================================================================

class TestPyprojectAddsRequirements:
    """The leaf pyproject must *add* requirements.txt (uv add -r semantics)."""

    @pytest.mark.parametrize("platform,distro,version", ALL_TARGETS)
    def test_declares_dependencies(self, platform, distro, version):
        data = tomllib.loads(
            (REPO_ROOT / platform / distro / version / "pyproject.toml").read_text(
                encoding="utf-8"
            )
        )
        deps = data["project"].get("dependencies") or []
        assert deps, (
            f"{platform}/{distro}/{version} declares no dependencies; "
            "CI's `uv sync --upgrade` would have nothing to resolve"
        )

    @pytest.mark.parametrize("platform,distro,version", ALL_TARGETS)
    def test_dependencies_match_requirements_txt(self, platform, distro, version):
        """Every name in requirements.txt must appear in project.dependencies."""
        d = REPO_ROOT / platform / distro / version
        data = tomllib.loads((d / "pyproject.toml").read_text(encoding="utf-8"))
        declared = {
            _canonical(dep) for dep in data["project"].get("dependencies") or []
        }
        for name in _requirement_names(d / "requirements.txt"):
            assert name in declared, (
                f"{platform}/{distro}/{version}: {name!r} is in requirements.txt "
                "but not added to pyproject.toml"
            )

    @pytest.mark.parametrize("platform,distro,version", ALL_TARGETS)
    def test_no_extra_dependencies_beyond_requirements(self, platform, distro, version):
        d = REPO_ROOT / platform / distro / version
        data = tomllib.loads((d / "pyproject.toml").read_text(encoding="utf-8"))
        declared = {
            _canonical(dep) for dep in data["project"].get("dependencies") or []
        }
        listed = _requirement_names(d / "requirements.txt")
        assert declared <= listed, (
            f"{platform}/{distro}/{version} declares {declared - listed} "
            "which is not in requirements.txt"
        )

    @pytest.mark.parametrize("platform,distro,version", ALL_TARGETS)
    def test_requires_python_is_pinned_to_the_target(self, platform, distro, version):
        data = tomllib.loads(
            (REPO_ROOT / platform / distro / version / "pyproject.toml").read_text(
                encoding="utf-8"
            )
        )
        assert data["project"]["requires-python"] == f">={version}"

    @pytest.mark.parametrize("platform,distro,version", ALL_TARGETS)
    def test_has_a_lockfile_or_can_produce_one(self, platform, distro, version):
        """uv.lock is what `uv sync --upgrade` updates and diffs."""
        d = REPO_ROOT / platform / distro / version
        assert (d / "uv.lock").is_file(), (
            f"{platform}/{distro}/{version} has no uv.lock; "
            "`uv sync --upgrade` needs one to detect drift"
        )


def _canonical(name: str) -> str:
    """Normalise a dependency spec to its bare distribution name."""
    name = name.split(";")[0].strip()
    for sep in ("==", ">=", "<=", "~=", "!=", ">", "<", "[", " ", "@"):
        if sep in name:
            name = name.split(sep)[0]
    return name.strip().lower().replace("_", "-")


def _requirement_names(path: pathlib.Path) -> set[str]:
    if not path.is_file():
        return set()
    names = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if not line or line.startswith("-") or line.startswith("http"):
            continue
        names.add(_canonical(line))
    return names


class TestRequirementsAreBroad:
    def test_core_is_substantially_broad(self):
        """The broad list is intentional; a token list would be wrong."""
        d = REPO_ROOT / "unix" / "ubuntu" / "3.10"
        assert len(_requirement_names(d / "requirements.txt")) >= 25


class TestPerDistroRequirements:
    """Each distro folder holds items installable only under that distro."""

    def test_unix_requirements_mention_their_distro(self):
        for distro, version in _distro_versions("unix"):
            d = REPO_ROOT / "unix" / distro / version
            notes = (d / "requirements.txt").read_text(encoding="utf-8")
            assert distro in notes, (
                f"unix/{distro} requirements.txt should document its "
                "distro-specific packages"
            )

    def test_windows_requirements_mention_their_distro(self):
        for distro, version in _distro_versions("windows"):
            d = REPO_ROOT / "windows" / distro / version
            notes = (d / "requirements.txt").read_text(encoding="utf-8")
            assert distro in notes

    def test_windows_never_lists_jupyterhub(self):
        for distro, version in _distro_versions("windows"):
            text = (REPO_ROOT / "windows" / distro / version / "requirements.txt").read_text(
                encoding="utf-8"
            )
            code = "\n".join(
                l for l in text.splitlines() if l.strip() and not l.strip().startswith("#")
            )
            assert "jupyterhub" not in code

    def test_unix_lists_jupyterhub(self):
        for distro, version in _distro_versions("unix"):
            text = (REPO_ROOT / "unix" / distro / version / "requirements.txt").read_text(
                encoding="utf-8"
            )
            assert "jupyterhub" in text

    def test_windows_lists_jupyterlab(self):
        for distro, version in _distro_versions("windows"):
            text = (REPO_ROOT / "windows" / distro / version / "requirements.txt").read_text(
                encoding="utf-8"
            )
            assert "jupyterlab" in text, "Windows must be able to run jupyter lab"


def _distro_versions(platform: str):
    for p, distro, version in ALL_TARGETS:
        if p == platform and _is_curated(platform, distro):
            yield distro, version


def _is_curated(platform: str, distro: str) -> bool:
    """Only the version directories that actually carry requirement files."""
    base = REPO_ROOT / platform / distro
    return any(
        (base / v / "requirements.txt").is_file() for v in cl.PYTHON_VERSIONS
    )


# ==========================================================================
# 2. Jupyter must actually start (Pages is gone)
# ==========================================================================

class TestNoPages:
    def test_pages_workflow_is_removed(self):
        assert not (WORKFLOWS / "pages.yml").exists(), (
            "the project does not need GitHub Pages"
        )

    def test_no_pages_action_in_any_workflow(self):
        for path in WORKFLOWS.glob("*.yml"):
            text = path.read_text(encoding="utf-8")
            assert "deploy-pages" not in text, f"{path.name} still deploys Pages"

    def test_site_generator_is_removed(self):
        assert not (REPO_ROOT / "scripts" / "build_site.py").exists()


class TestJupyterStartability:
    """The acceptance bar: jupyter lab on Windows, jupyterhub on Unix."""

    def _workflow(self) -> str:
        return (WORKFLOWS / "matrix.yml").read_text(encoding="utf-8")

    def test_windows_smoke_tests_jupyter_lab(self):
        text = self._workflow()
        assert "jupyter lab" in text or "jupyter-lab" in text, (
            "CI must start jupyter lab on Windows"
        )

    def test_unix_smoke_tests_jupyterhub(self):
        text = self._workflow()
        assert "jupyterhub" in text, "CI must start jupyterhub on Unix"

    def test_startability_is_gated_per_platform(self):
        text = self._workflow()
        assert "matrix.platform == 'windows'" in text
        assert "matrix.platform == 'unix'" in text

    def test_jupyter_lab_check_waits_for_the_url(self):
        """Starting must be *observed*, not merely launched."""
        text = self._workflow()
        lower = text.lower()
        assert "lab" in lower and ("curl" in lower or "invoke-webrequest" in lower
                                   or "requests" in lower or "wait" in lower), (
            "the smoke test should confirm the server actually answered"
        )

    def test_jupyterhub_check_uses_configurable_http_proxy(self):
        text = self._workflow()
        assert "configurable-http-proxy" in text or "node" in text, (
            "jupyterhub needs configurable-http-proxy (Node.js)"
        )


# ==========================================================================
# 3. Dependabot targets dev
# ==========================================================================

class TestDependabotTargetsDev:
    @pytest.fixture(scope="class")
    def config(self):
        return yaml.safe_load(
            (REPO_ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
        )

    def test_every_update_targets_dev(self, config):
        for update in config["updates"]:
            assert update.get("target-branch") == "dev", (
                f"{update['package-ecosystem']} "
                f"({update['directory']}) does not target dev"
            )

    def test_commit_messages_are_recognisable(self, config):
        for update in config["updates"]:
            msg = update.get("commit-message") or {}
            assert msg.get("prefix"), "each updater needs a commit prefix"


# ==========================================================================
# 4. Version-keyed releases on every main push
# ==========================================================================

class TestReleaseWorkflow:
    def _release(self) -> dict:
        return yaml.safe_load(
            (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
        )

    def test_release_triggers_on_main_push(self):
        data = self._release()
        triggers = data.get("on") or data.get(True)
        branches = triggers["push"].get("branches") or []
        assert "main" in branches, "every push to main must publish a release"

    def test_release_uses_uv_build(self):
        assert "uv build" in (WORKFLOWS / "release.yml").read_text(encoding="utf-8")

    def test_release_needs_write_permissions(self):
        perms = self._release().get("permissions", {})
        assert perms.get("contents") == "write"

    def test_release_is_keyed_on_the_pyproject_version(self):
        text = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
        assert "version" in text.lower()
        assert "pyproject" in text.lower()

    def test_release_has_a_decision_step(self):
        """In-place update vs new release must be an explicit decision."""
        text = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
        assert "scripts/release.py" in text or "gh release" in text


class TestReleaseLogic:
    @pytest.fixture(scope="class")
    def rel(self):
        return _load("release", "scripts/release.py")

    def test_same_version_updates_in_place(self, rel):
        assert rel.should_create_release("0.1.0", "0.1.0") is False

    def test_changed_version_creates_a_new_release(self, rel):
        assert rel.should_create_release("0.1.0", "0.2.0") is True

    def test_no_previous_release_creates_one(self, rel):
        assert rel.should_create_release(None, "0.1.0") is True

    def test_tag_names_are_prefixed(self, rel):
        assert rel.tag_for("0.1.0") == "v0.1.0"

    def test_version_is_read_from_pyproject(self, rel):
        assert rel.read_version(REPO_ROOT / "unix" / "ubuntu" / "3.10") == "0.1.0"

    def test_collects_built_artifacts(self, rel, tmp_path):
        (tmp_path / "a-0.1.0-py3-none-any.whl").write_bytes(b"x")
        (tmp_path / "a-0.1.0.tar.gz").write_bytes(b"x")
        (tmp_path / "notes.txt").write_bytes(b"x")
        found = rel.collect_artifacts([tmp_path])
        assert len(found) == 2
        assert all(p.suffix in {".whl", ".gz"} for p in found)

    def test_decides_update_vs_create(self, rel):
        assert rel.plan_release("0.1.0", "0.1.0") == "update"
        assert rel.plan_release("0.1.0", "0.2.0") == "create"
        assert rel.plan_release(None, "0.1.0") == "create"
