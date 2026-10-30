from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from packaging.tags import Tag
from packaging.version import Version

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "pypi_index", REPO_ROOT / "scripts" / "pypi_index.py"
)
assert SPEC and SPEC.loader
pi = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = pi
SPEC.loader.exec_module(pi)

GENERATOR_SPEC = importlib.util.spec_from_file_location(
    "generate_pypi_index", REPO_ROOT / "scripts" / "generate_pypi_index.py"
)
assert GENERATOR_SPEC and GENERATOR_SPEC.loader
generator = importlib.util.module_from_spec(GENERATOR_SPEC)
sys.modules[GENERATOR_SPEC.name] = generator
GENERATOR_SPEC.loader.exec_module(generator)


def test_read_requirements_omits_comments_and_inactive_markers(tmp_path):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text(
        "# comment\npychm\nwindows-only; sys_platform == 'not-real'\n"
        "https://example.test/source.tar.gz\n",
        encoding="utf-8",
    )

    parsed = pi.read_requirements(requirements)

    assert [raw for raw, _ in parsed] == ["pychm", "https://example.test/source.tar.gz"]
    assert parsed[0][1].name == "pychm"
    assert parsed[1][1] is None


def test_release_needs_build_when_latest_release_has_only_sdist():
    project = {
        "releases": {
            "1.0": [
                {
                    "filename": "example-1.0-py3-none-any.whl",
                    "packagetype": "bdist_wheel",
                    "yanked": False,
                }
            ],
            "2.0": [
                {
                    "filename": "example-2.0.tar.gz",
                    "packagetype": "sdist",
                    "url": "https://files.pythonhosted.org/example-2.0.tar.gz",
                    "yanked": False,
                }
            ],
        }
    }

    selected = pi.release_needs_build(
        "example", "", project, {Tag("cp314", "cp314", "win_amd64")}, Version("3.14")
    )

    assert selected == (
        "2.0",
        "https://files.pythonhosted.org/example-2.0.tar.gz",
    )


def test_release_does_not_need_build_when_latest_has_compatible_wheel():
    project = {
        "releases": {
            "2.0": [
                {
                    "filename": "example-2.0-cp314-cp314-win_amd64.whl",
                    "packagetype": "bdist_wheel",
                    "yanked": False,
                }
            ]
        }
    }

    selected = pi.release_needs_build(
        "example", "", project, {Tag("cp314", "cp314", "win_amd64")}, Version("3.14")
    )

    assert selected is None


def test_generate_index_creates_pep503_project_page_and_hash(tmp_path):
    wheel_dir = tmp_path / "wheels"
    wheel_dir.mkdir()
    wheel = wheel_dir / "sample_pkg-1.0-py3-none-any.whl"
    wheel.write_bytes(b"wheel fixture")

    count = generator.generate_index(wheel_dir, tmp_path / "site")

    root_page = (tmp_path / "site/simple/index.html").read_text(encoding="utf-8")
    project_page = (tmp_path / "site/simple/sample-pkg/index.html").read_text(
        encoding="utf-8"
    )
    assert count == 1
    assert 'href="sample-pkg/"' in root_page
    assert "../../packages/sample_pkg-1.0-py3-none-any.whl#sha256=" in project_page