#!/usr/bin/env python3
"""Create a static PEP 503 index from built wheel files."""

from __future__ import annotations

import argparse
import hashlib
import html
import shutil
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote

from packaging.utils import canonicalize_name, parse_wheel_filename


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def generate_index(wheel_dir: Path, output_dir: Path) -> int:
    """Copy wheels and write PEP 503 project pages; return wheel count."""
    package_files: dict[str, list[tuple[str, str]]] = defaultdict(list)
    package_dir = output_dir / "packages"
    package_dir.mkdir(parents=True, exist_ok=True)

    for wheel in sorted(wheel_dir.rglob("*.whl")):
        name, _, _, _ = parse_wheel_filename(wheel.name)
        destination = package_dir / wheel.name
        if destination.exists():
            if sha256(destination) != sha256(wheel):
                raise ValueError(f"different wheels share filename {wheel.name}")
        else:
            shutil.copy2(wheel, destination)
        package_files[canonicalize_name(name)].append((wheel.name, sha256(destination)))

    simple_dir = output_dir / "simple"
    simple_dir.mkdir(parents=True, exist_ok=True)
    root_links = "\n".join(
        f'<a href="{html.escape(name)}/">{html.escape(name)}</a>'
        for name in sorted(package_files)
    )
    (simple_dir / "index.html").write_text(
        f"<!DOCTYPE html>\n<html><body>\n{root_links}\n</body></html>\n",
        encoding="utf-8",
    )

    for name, files in sorted(package_files.items()):
        project_dir = simple_dir / name
        project_dir.mkdir(parents=True, exist_ok=True)
        links = "\n".join(
            f'<a href="../../packages/{quote(filename, safe="")}#sha256={digest}">'
            f"{html.escape(filename)}</a>"
            for filename, digest in sorted(set(files))
        )
        (project_dir / "index.html").write_text(
            f"<!DOCTYPE html>\n<html><body>\n{links}\n</body></html>\n",
            encoding="utf-8",
        )
    return sum(len(set(files)) for files in package_files.values())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    count = generate_index(args.wheel_dir, args.output_dir)
    if count == 0:
        parser.error("no wheels found; refusing to publish an empty package index")
    print(f"Indexed {count} wheel(s) for {len(list((args.output_dir / 'simple').iterdir())) - 1} project(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())