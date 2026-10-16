"""Tests for the generated GitHub Pages site and the CI workflow files.

The site must stay in lockstep with ``scripts/check_layout.py`` (single source
of truth), and the workflows must be valid YAML with the branch model wired up:
``dev`` fast, ``main`` full, tags release.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = REPO_ROOT / ".github" / "workflows"


def _load(name: str, relative: str):
    path = REPO_ROOT / relative
    if not path.is_file():
        pytest.fail(f"missing implementation file: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


bs = _load("build_site", "scripts/build_site.py")
cl = _load("check_layout", "scripts/check_layout.py")


# --------------------------------------------------------------------------
# Site generation
# --------------------------------------------------------------------------

class TestSiteBuild:
    def test_build_creates_index(self, tmp_path):
        index = bs.build(tmp_path)
        assert index.is_file()

    def test_build_creates_nojekyll(self, tmp_path):
        bs.build(tmp_path)
        assert (tmp_path / ".nojekyll").is_file()

    def test_index_is_valid_ish_html(self, tmp_path):
        index = bs.build(tmp_path)
        text = index.read_text(encoding="utf-8")
        assert text.startswith("<!DOCTYPE html>")
        assert text.rstrip().endswith("</html>")

    def test_index_has_no_unrendered_placeholders(self, tmp_path):
        index = bs.build(tmp_path)
        text = index.read_text(encoding="utf-8")
        assert not re.search(r"\{[a-z_]+\}", text), "unrendered format placeholder"

    def test_index_lists_every_committed_target(self, tmp_path):
        index = bs.build(tmp_path)
        text = index.read_text(encoding="utf-8")
        for _, parts in cl.iter_target_dirs(REPO_ROOT):
            assert "/".join(parts) in text

    def test_index_mentions_every_distro(self, tmp_path):
        index = bs.build(tmp_path)
        text = index.read_text(encoding="utf-8")
        for distro in cl.DISTROS:
            assert distro in text, f"{distro} missing from the site"

    def test_index_documents_the_libchm_package_names(self, tmp_path):
        index = bs.build(tmp_path)
        text = index.read_text(encoding="utf-8")
        assert "libchm-dev" in text   # debian/ubuntu
        assert "chmlib" in text       # arch/macos/guix/nix

    def test_index_escapes_html(self, tmp_path):
        """Distro/vendor strings must be escaped, never injected raw."""
        index = bs.build(tmp_path)
        text = index.read_text(encoding="utf-8")
        assert "<script>" not in text


# --------------------------------------------------------------------------
# Workflows
# --------------------------------------------------------------------------

def workflow_path(name: str) -> Path:
    return WORKFLOWS / f"{name}.yml"


@pytest.fixture(scope="module")
def workflows() -> dict[str, dict]:
    parsed = {}
    for path in sorted(WORKFLOWS.glob("*.yml")):
        parsed[path.stem] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return parsed


class TestWorkflowPresence:
    @pytest.mark.parametrize("name", ["dev", "full", "daily", "pages", "release"])
    def test_workflow_exists(self, name):
        assert workflow_path(name).is_file()

    @pytest.mark.parametrize("name", ["dev", "full", "daily", "pages", "release"])
    def test_workflow_is_valid_yaml(self, name):
        data = yaml.safe_load(workflow_path(name).read_text(encoding="utf-8"))
        assert isinstance(data, dict)

    @pytest.mark.parametrize("name", ["dev", "full", "daily", "pages", "release"])
    def test_workflow_has_jobs(self, name, workflows):
        assert workflows[name].get("jobs"), f"{name} has no jobs"

    @pytest.mark.parametrize("name", ["dev", "full", "daily", "pages", "release"])
    def test_workflow_is_named(self, name, workflows):
        assert workflows[name].get("name")


class TestBranchModel:
    def test_dev_runs_on_dev_branch(self, workflows):
        text = workflow_path("dev").read_text(encoding="utf-8")
        assert "dev" in text

    def test_full_runs_on_main(self, workflows):
        triggers = workflows["full"][True] if True in workflows["full"] else workflows["full"]["on"]
        assert triggers["push"]["branches"] == ["main"]

    def test_release_runs_on_tags(self, workflows):
        data = workflows["release"]
        triggers = data.get("on") or data.get(True)
        assert any(t.startswith("v") for t in triggers["push"]["tags"])

    def test_daily_has_a_schedule(self, workflows):
        data = workflows["daily"]
        triggers = data.get("on") or data.get(True)
        assert triggers.get("schedule"), "daily workflow must be scheduled"

    def test_daily_schedule_is_valid_cron(self, workflows):
        data = workflows["daily"]
        triggers = data.get("on") or data.get(True)
        for entry in triggers["schedule"]:
            fields = entry["cron"].split()
            assert len(fields) == 5, f"bad cron: {entry['cron']}"

    def test_pages_is_reusable_and_callable(self, workflows):
        data = workflows["pages"]
        triggers = data.get("on") or data.get(True)
        assert "workflow_call" in triggers

    def test_full_calls_the_pages_workflow(self, workflows):
        jobs = workflows["full"]["jobs"]
        assert any(
            isinstance(job, dict) and "uses" in job and "pages" in str(job["uses"])
            for job in jobs.values()
        )


class TestDailyPrWorkflowContract:
    def test_daily_invokes_the_pr_script(self):
        text = workflow_path("daily").read_text(encoding="utf-8")
        assert "scripts/daily_pr.py" in text

    def test_daily_uses_a_dry_run_plan_step(self):
        text = workflow_path("daily").read_text(encoding="utf-8")
        assert "--dry-run" in text

    def test_daily_reports_back_to_the_issue(self, workflows):
        text = workflow_path("daily").read_text(encoding="utf-8")
        assert "/issues/1/comments" in text

    def test_daily_declares_pr_write_permission(self, workflows):
        perms = workflows["daily"].get("permissions", {})
        assert perms.get("pull-requests") == "write"
        assert perms.get("contents") == "write"

    def test_daily_supports_manual_force_dispatch(self, workflows):
        data = workflows["daily"]
        triggers = data.get("on") or data.get(True)
        assert "workflow_dispatch" in triggers
        assert "force" in triggers["workflow_dispatch"]["inputs"]


class TestMatrixWorkflows:
    def test_dev_matrix_covers_all_distros(self, workflows):
        text = workflow_path("dev").read_text(encoding="utf-8")
        for distro in cl.DISTROS:
            assert distro in text, f"{distro} missing from the dev matrix"

    def test_full_matrix_covers_all_python_versions(self, workflows):
        text = workflow_path("full").read_text(encoding="utf-8")
        for version in cl.PYTHON_VERSIONS:
            assert f'python: "{version}"' in text, f"{version} missing from full matrix"

    def test_workflows_are_keyed_by_platform_distro_python(self):
        for name in ("dev", "full", "daily", "release"):
            text = workflow_path(name).read_text(encoding="utf-8")
            assert "matrix.distro" in text
            assert "matrix.python" in text

    def test_preinstall_is_invoked_by_the_matrix(self):
        for name in ("dev", "full", "daily", "release"):
            text = workflow_path(name).read_text(encoding="utf-8")
            assert "preinstall.sh" in text, f"{name} never runs preinstall.sh"

    def test_windows_targets_use_powershell_preinstall(self):
        for name in ("dev", "full", "daily", "release"):
            text = workflow_path(name).read_text(encoding="utf-8")
            if "windows" in text:
                assert "preinstall.ps1" in text, (
                    f"{name} has windows targets but never runs preinstall.ps1"
                )

    def test_layout_validator_runs_in_ci(self):
        for name in ("dev", "full", "daily", "release"):
            text = workflow_path(name).read_text(encoding="utf-8")
            assert "check_layout.py" in text, f"{name} does not validate the layout"


# --------------------------------------------------------------------------
# Dependabot / devcontainer / env template
# --------------------------------------------------------------------------

class TestRepoAutomation:
    def test_dependabot_config_exists(self):
        assert (REPO_ROOT / ".github" / "dependabot.yml").is_file()

    def test_dependabot_is_valid_yaml(self):
        data = yaml.safe_load(
            (REPO_ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
        )
        assert data["version"] == 2
        assert data["updates"]

    def test_dependabot_tracks_pip_and_actions(self):
        data = yaml.safe_load(
            (REPO_ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
        )
        ecosystems = {u["package-ecosystem"] for u in data["updates"]}
        assert "pip" in ecosystems
        assert "github-actions" in ecosystems

    def test_devcontainer_json_exists(self):
        assert (REPO_ROOT / ".devcontainer" / "devcontainer.json").is_file()

    def test_devcontainer_json_is_valid(self):
        import json

        data = json.loads(
            (REPO_ROOT / ".devcontainer" / "devcontainer.json").read_text(
                encoding="utf-8"
            )
        )
        assert data.get("postCreateCommand")

    def test_devcontainer_keeps_json_minimal(self):
        import json

        data = json.loads(
            (REPO_ROOT / ".devcontainer" / "devcontainer.json").read_text(
                encoding="utf-8"
            )
        )
        # Delegate heavy lifting to the script, not inline JSON.
        assert len(json.dumps(data)) < 2000

    def test_devcontainer_calls_post_create_script(self):
        import json

        data = json.loads(
            (REPO_ROOT / ".devcontainer" / "devcontainer.json").read_text(
                encoding="utf-8"
            )
        )
        assert "post-create.sh" in json.dumps(data)

    def test_post_create_script_exists_and_is_strict(self):
        script = REPO_ROOT / ".devcontainer" / "post-create.sh"
        assert script.is_file()
        assert "set -euo pipefail" in script.read_text(encoding="utf-8")

    def test_post_create_does_not_assume_a_distribution(self):
        text = (REPO_ROOT / ".devcontainer" / "post-create.sh").read_text(
            encoding="utf-8"
        )
        # Must detect rather than assume (no bare `apt-get install` without a guard).
        assert "command -v" in text

    def test_env_example_exists(self):
        assert (REPO_ROOT / ".env.example").is_file()

    def test_env_example_has_no_real_secrets(self):
        text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
        assert "github_pat_" not in text
        assert "ghp_" not in text

    def test_env_example_documents_the_token_variable(self):
        text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
        assert "GITHUB_TOKEN" in text

    def test_env_is_gitignored(self):
        text = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        assert re.search(r"^\.env$", text, re.MULTILINE)
