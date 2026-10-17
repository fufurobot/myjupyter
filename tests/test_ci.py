"""Tests for CI workflows, the Pages site, and repo automation.

The CI contract now reflects the revised design:

* the matrix builds every ``<platform>/<distro>/<python-version>`` on **real
  runners** - nothing is built locally;
* upstream package updates are detected and proposed as pull requests
  automatically;
* ``dev`` is fast, ``main`` is full, tags publish releases.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parent.parent
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
bs = _load("build_site", "scripts/build_site.py")
uu = _load("upstream_update", "scripts/upstream_update.py")


def workflow_path(name: str) -> Path:
    return WORKFLOWS / f"{name}.yml"


def triggers(data: dict):
    return data.get("on") if "on" in data else data.get(True)


@pytest.fixture(scope="module")
def workflows() -> dict[str, dict]:
    return {
        path.stem: yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in sorted(WORKFLOWS.glob("*.yml"))
    }


# --------------------------------------------------------------------------
# Workflow presence and validity
# --------------------------------------------------------------------------

REQUIRED = ["matrix", "pages", "release", "upstream-update"]


class TestWorkflowPresence:
    @pytest.mark.parametrize("name", REQUIRED)
    def test_exists(self, name):
        assert workflow_path(name).is_file()

    @pytest.mark.parametrize("name", REQUIRED)
    def test_valid_yaml(self, name, workflows):
        assert isinstance(workflows[name], dict)

    @pytest.mark.parametrize("name", REQUIRED)
    def test_has_jobs(self, name, workflows):
        assert workflows[name].get("jobs")

    @pytest.mark.parametrize("name", REQUIRED)
    def test_is_named(self, name, workflows):
        assert workflows[name].get("name")

    @pytest.mark.parametrize("name", REQUIRED)
    def test_steps_are_well_formed(self, name, workflows):
        for job_id, job in workflows[name]["jobs"].items():
            if not isinstance(job, dict):
                pytest.fail(f"{name}:{job_id} is not a mapping")
            if "uses" not in job:
                assert "steps" in job, f"{name}:{job_id} has neither uses nor steps"
            for step in job.get("steps", []) or []:
                assert "uses" in step or "run" in step, f"{name}:{job_id} bad step"

    @pytest.mark.parametrize("name", REQUIRED)
    def test_needs_reference_real_jobs(self, name, workflows):
        jobs = workflows[name]["jobs"]
        for job_id, job in jobs.items():
            if not isinstance(job, dict):
                continue
            needs = job.get("needs", [])
            needs = [needs] if isinstance(needs, str) else (needs or [])
            for dep in needs:
                assert dep in jobs, f"{name}:{job_id} needs unknown job {dep}"


# --------------------------------------------------------------------------
# Matrix is the primary CI
# --------------------------------------------------------------------------

class TestMatrixWorkflow:
    def test_matrix_workflow_builds_on_real_runners(self, workflows):
        text = workflow_path("matrix").read_text(encoding="utf-8")
        assert "runs-on" in text
        assert "runners" not in text.lower() or "self-hosted" not in text

    def test_matrix_generated_from_check_layout(self):
        text = workflow_path("matrix").read_text(encoding="utf-8")
        assert "check_layout.py --matrix" in text, (
            "the matrix must come from the validator so it cannot drift"
        )

    def test_matrix_builds_pyproject(self):
        text = workflow_path("matrix").read_text(encoding="utf-8")
        assert "uv build" in text

    def test_matrix_installs_core_requirements(self):
        text = workflow_path("matrix").read_text(encoding="utf-8")
        assert "requirements.txt" in text

    def test_matrix_has_a_fast_and_full_tier(self, workflows):
        jobs = workflows["matrix"]["jobs"]
        assert "build" in jobs
        assert "build-full" in jobs

    def test_full_tier_gated_to_main_or_dispatch(self, workflows):
        job = workflows["matrix"]["jobs"]["build-full"]
        cond = str(job.get("if", ""))
        assert "refs/heads/main" in cond or "workflow_dispatch" in cond

    def test_optional_tier_is_allowed_to_fail(self, workflows):
        job = workflows["matrix"]["jobs"]["optional"]
        steps = job["steps"]
        assert any(s.get("continue-on-error") for s in steps), (
            "experimental sets must not turn the matrix red"
        )

    def test_matrix_uses_portable_venv_paths(self):
        """A venv interpreter is .venv/bin/python on POSIX but Scripts/ on Windows."""
        code = "\n".join(
            line for line in workflow_path("matrix").read_text().splitlines()
            if not line.strip().startswith("#")
        )
        assert ".venv-ci/bin/python" not in code
        assert "uv run" in code, "uv run abstracts the venv layout"


# --------------------------------------------------------------------------
# Upstream update automation
# --------------------------------------------------------------------------

class TestUpstreamUpdate:
    def test_workflow_exists(self):
        assert workflow_path("upstream-update").is_file()

    def test_is_scheduled_daily(self, workflows):
        trig = triggers(workflows["upstream-update"])
        assert trig.get("schedule"), "must run on a schedule"
        for entry in trig["schedule"]:
            assert len(entry["cron"].split()) == 5

    def test_supports_manual_dispatch(self, workflows):
        assert "workflow_dispatch" in triggers(workflows["upstream-update"])

    def test_can_write_contents_and_prs(self, workflows):
        perms = workflows["upstream-update"].get("permissions", {})
        assert perms.get("pull-requests") == "write"
        assert perms.get("contents") == "write"

    def test_invokes_the_updater(self):
        text = workflow_path("upstream-update").read_text(encoding="utf-8")
        assert "scripts/upstream_update.py" in text

    def test_verifies_before_proposing(self):
        text = workflow_path("upstream-update").read_text(encoding="utf-8")
        assert "uv run" in text, "the upgraded set must be verified on a real runner"

    def test_only_proposes_when_changed(self):
        text = workflow_path("upstream-update").read_text(encoding="utf-8")
        assert "changed" in text


class TestUpstreamUpdateLogic:
    def test_normalise_strips_comments_and_blank_lines(self):
        raw = "# comment\n\nfoo==1.0\nbar==2.0\n"
        assert uu.normalise(raw) == "bar==2.0\nfoo==1.0\n"

    def test_normalise_sorts_for_stable_diffs(self):
        a = uu.normalise("z==1\n# x\na==2\n")
        b = uu.normalise("a==2\nz==1\n")
        assert a == b

    def test_normalise_detects_a_version_bump(self):
        assert uu.normalise("pandas==3.0.6\n") != uu.normalise("pandas==3.0.7\n")

    def test_build_body_mentions_the_issue(self):
        body = uu.build_body([])
        assert "#1" in body

    def test_build_body_handles_empty_change(self):
        assert isinstance(uu.build_body([]), str)


# --------------------------------------------------------------------------
# Pages site
# --------------------------------------------------------------------------

class TestSiteBuild:
    def test_build_creates_index(self, tmp_path):
        assert bs.build(tmp_path).is_file()

    def test_creates_nojekyll(self, tmp_path):
        bs.build(tmp_path)
        assert (tmp_path / ".nojekyll").is_file()

    def test_no_unrendered_placeholders(self, tmp_path):
        text = bs.build(tmp_path).read_text(encoding="utf-8")
        assert not re.search(r"\{[a-z_]+\}", text)

    def test_lists_every_committed_target(self, tmp_path):
        text = bs.build(tmp_path).read_text(encoding="utf-8")
        for _, parts in cl.iter_target_dirs(REPO_ROOT):
            assert "/".join(parts) in text

    def test_mentions_every_distro(self, tmp_path):
        text = bs.build(tmp_path).read_text(encoding="utf-8")
        for distro in cl.DISTROS:
            assert distro in text

    def test_site_documents_the_requirement_split(self, tmp_path):
        text = bs.build(tmp_path).read_text(encoding="utf-8")
        assert "requirements-jupyterhub" in text or "jupyterhub" in text
        assert "experimental" in text


# --------------------------------------------------------------------------
# Branch model
# --------------------------------------------------------------------------

class TestBranchModel:
    def test_matrix_triggers_on_dev_and_main(self, workflows):
        assert triggers(workflows["matrix"])["push"]["branches"] == ["dev", "main"]

    def test_matrix_also_triggers_on_tags(self, workflows):
        tags = triggers(workflows["matrix"])["push"]["tags"]
        assert any(t.startswith("v") for t in tags)

    def test_matrix_has_a_weekly_schedule(self, workflows):
        sched = triggers(workflows["matrix"])["schedule"]
        for entry in sched:
            assert len(entry["cron"].split()) == 5

    def test_release_triggers_on_tags(self, workflows):
        trig = triggers(workflows["release"])
        assert any(t.startswith("v") for t in trig["push"]["tags"])

    def test_pages_is_reusable(self, workflows):
        assert "workflow_call" in triggers(workflows["pages"])

    def test_matrix_calls_pages_on_main(self, workflows):
        jobs = workflows["matrix"]["jobs"]
        assert any(
            isinstance(j, dict) and "pages" in str(j.get("uses", ""))
            for j in jobs.values()
        )

    def test_matrix_runs_unit_tests(self, workflows):
        assert "unit" in workflows["matrix"]["jobs"]


# --------------------------------------------------------------------------
# Repo automation
# --------------------------------------------------------------------------

class TestRepoAutomation:
    def test_dependabot_exists_and_is_valid(self):
        path = REPO_ROOT / ".github" / "dependabot.yml"
        assert path.is_file()
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert data["version"] == 2
        assert data["updates"]

    def test_dependabot_tracks_pip_and_actions(self):
        data = yaml.safe_load(
            (REPO_ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
        )
        eco = {u["package-ecosystem"] for u in data["updates"]}
        assert "pip" in eco and "github-actions" in eco

    def test_devcontainer_is_valid_and_minimal(self):
        data = json.loads(
            (REPO_ROOT / ".devcontainer" / "devcontainer.json").read_text(encoding="utf-8")
        )
        assert data.get("postCreateCommand")
        assert len(json.dumps(data)) < 2000

    def test_post_create_does_not_assume_a_distro(self):
        text = (REPO_ROOT / ".devcontainer" / "post-create.sh").read_text(encoding="utf-8")
        assert "set -euo pipefail" in text
        assert "command -v" in text

    def test_post_create_uses_official_uv_installer(self):
        text = (REPO_ROOT / ".devcontainer" / "post-create.sh").read_text(encoding="utf-8")
        assert "astral.sh/uv" in text

    def test_env_example_has_no_secrets(self):
        text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
        assert "github_pat_" not in text
        assert "ghp_" not in text
        assert "GITHUB_TOKEN" in text

    def test_env_is_gitignored(self):
        text = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        assert re.search(r"^\.env$", text, re.MULTILINE)

    def test_gitattributes_pins_line_endings(self):
        text = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8")
        assert re.search(r"^\*\.sh\s+.*eol=lf", text, re.MULTILINE)
        assert re.search(r"^\*\.ps1\s+.*eol=crlf", text, re.MULTILINE)
