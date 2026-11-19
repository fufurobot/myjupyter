"""Build wheels for root requirements without a compatible PyPI wheel."""

from __future__ import annotations

import argparse
import functools
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.tags import Tag, sys_tags
from packaging.utils import canonicalize_name, parse_wheel_filename
from packaging.version import InvalidVersion, Version


def read_requirements(path: Path) -> list[tuple[str, Requirement | None]]:
    """Return active named requirements and direct archive URLs."""
    requirements: list[tuple[str, Requirement | None]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "-")):
            continue
        if line.startswith(("http://", "https://", "git+")):
            requirements.append((line, None))
            continue
        line = re.split(r"\s+#", line, maxsplit=1)[0].strip()
        requirement = Requirement(line)
        if requirement.marker and not requirement.marker.evaluate():
            continue
        requirements.append((line, requirement))
    return requirements


def release_needs_build(
    name: str,
    specifier: str,
    project_data: dict[str, Any],
    compatible_tags: set[Tag],
    python_version: Version,
) -> tuple[str, str] | None:
    """Select the newest matching PyPI release and report its source archive."""
    allowed = SpecifierSet(specifier)
    releases = project_data.get("releases", {})
    candidates: list[tuple[Version, str]] = []
    for raw_version, files in releases.items():
        try:
            version = Version(raw_version)
        except InvalidVersion:
            continue
        if not allowed.contains(version):
            continue
        usable_files = [
            file for file in files
            if not file.get("yanked", False)
            and (
                not file.get("requires_python")
                or SpecifierSet(file["requires_python"]).contains(python_version)
            )
        ]
        if usable_files:
            candidates.append((version, raw_version))

    if not candidates:
        raise ValueError(f"no PyPI release matches {name}{specifier}")

    version, raw_version = max(candidates)
    files = releases[raw_version]
    usable_files = [
        file for file in files
        if not file.get("yanked", False)
        and (
            not file.get("requires_python")
            or SpecifierSet(file["requires_python"]).contains(python_version)
        )
    ]
    for file in usable_files:
        filename = file.get("filename", "")
        if filename.endswith(".whl"):
            _, _, _, wheel_tags = parse_wheel_filename(filename)
            if compatible_tags.intersection(wheel_tags):
                return None

    source = next(
        (file for file in usable_files if file.get("packagetype") == "sdist"),
        None,
    )
    if source is None:
        raise ValueError(f"{name}=={version} has no compatible wheel or source archive")
    return str(version), source["url"]


@functools.cache
def pypi_project(name: str) -> dict[str, Any]:
    normalized = canonicalize_name(name)
    url = f"https://pypi.org/pypi/{normalized}/json"
    request = urllib.request.Request(url, headers={"User-Agent": "myjupyter-wheel-index"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise ValueError(f"{name} is not a PyPI project") from error
        raise


def build_missing(
    requirements_path: Path,
    wheel_dir: Path,
    skipped: set[str] | None = None,
) -> list[str]:
    """Build only active requirements whose selected PyPI release is sdist-only."""
    wheel_dir.mkdir(parents=True, exist_ok=True)
    tags = set(sys_tags())
    python_version = Version(".".join(map(str, sys.version_info[:3])))
    built: list[str] = []
    skipped = {canonicalize_name(name) for name in (skipped or set())}

    for original, requirement in read_requirements(requirements_path):
        if requirement is None:
            print(f"BUILD non-PyPI source: {original}")
            build_spec = original
        else:
            try:
                selected = release_needs_build(
                    requirement.name,
                    str(requirement.specifier),
                    pypi_project(requirement.name),
                    tags,
                    python_version,
                )
            except ValueError as error:
                if "is not a PyPI project" not in str(error):
                    raise
                print(f"NOT ON PYPI; no wheel to index: {original}")
                continue
            else:
                if selected is None:
                    print(f"PYPI wheel available: {requirement}")
                    continue
                if canonicalize_name(requirement.name) in skipped:
                    print(
                        "SKIP source build without compatible PyPI wheel: "
                        f"{requirement.name}"
                    )
                    continue
                version, _source_url = selected
                extras = f"[{','.join(sorted(requirement.extras))}]" if requirement.extras else ""
                build_spec = f"{requirement.name}{extras}=={version}"
                print(f"BUILD missing compatible PyPI wheel: {build_spec}")

        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                "--no-deps",
                "--wheel-dir",
                str(wheel_dir),
                build_spec,
            ],
            check=True,
        )
        built.append(build_spec)
    return built


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requirements", type=Path, default=Path("requirements.txt"))
    parser.add_argument("--wheel-dir", type=Path, default=Path("dist"))
    parser.add_argument("--skip", action="append", default=[], metavar="NAME")
    args = parser.parse_args(argv)
    built = build_missing(args.requirements, args.wheel_dir, set(args.skip))
    print(f"Built {len(built)} wheel(s) needing the supplemental index")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())