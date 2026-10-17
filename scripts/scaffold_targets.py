#!/usr/bin/env python3
"""Generate the per-target packaging for every ``<platform>/<distro>/<python>``.

Design (revised after CI proved the old approach wrong):

* **Every target must hold a ``pyproject.toml`` that actually builds.** That is
  the acceptance bar, verified by CI on real machines, not locally.
* Requirements are **split by buildability**, not dumped into one file:

  - ``requirements.txt``              core, expected to build everywhere
  - ``requirements-jupyterhub.txt``   unix only (jupyterhub needs PAM/pamela)
  - ``requirements-experimental.txt`` things that need native libraries we do
                                     not want to fight (``pychm``)

* ``pychm`` is deliberately **out of the core set**. PyPI has exactly one
  ``pychm`` wheel ever published (cp27, macOS); every Python 3 install
  compiles from source against system chmlib. It is not important enough to
  gate the toolchain on, so it lives in the experimental file where a failure
  is expected and non-fatal.

Run: ``python3 scripts/scaffold_targets.py``
"""

from __future__ import annotations

import argparse
import importlib.util
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load_check_layout():
    spec = importlib.util.spec_from_file_location(
        "check_layout", REPO_ROOT / "scripts" / "check_layout.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_layout"] = module
    spec.loader.exec_module(module)
    return module


cl = _load_check_layout()

# --------------------------------------------------------------------------
# Requirement sets
# --------------------------------------------------------------------------

#: Core, portable toolchain. Verified to build on real runners by CI.
CORE = """\
# Core toolchain - expected to build on every supported target.
# Keep this list portable: nothing here may require an OS-specific native
# library, or the matrix will be red for reasons that are not the point.

# --- dev tooling -----------------------------------------------------------
ruff
mypy
flake8
pytest
pytest-asyncio
pytest-cov
pytest-mock
pytest-xdist
pylint
pyright

# --- cli / tui -------------------------------------------------------------
typer
rich
tqdm

# --- networking ------------------------------------------------------------
requests
dnspython
graphql-core
fastapi
uvicorn
openai

# --- data ------------------------------------------------------------------
pandas
pyarrow
openpyxl
lxml
beautifulsoup4
html5lib
python-docx
pdfplumber

# --- nlp -------------------------------------------------------------------
regex
pypinyin
nltk
tree-sitter-language-pack

# --- math ------------------------------------------------------------------
sympy
networkx

# --- imaging / plotting ----------------------------------------------------
pillow
plotly
matplotlib
segno

# --- automation ------------------------------------------------------------
playwright
asyncssh
asyncvnc
pynput
"""

#: Unix only. jupyterhub pulls `pamela` (PAM) on non-Windows; PAMAuthenticator
#: has no Windows implementation, which is exactly why the old tree had such
#: different linux/ and windows/ folders.
JUPYTERHUB = """\
# Unix-only: jupyterhub requires PAM via `pamela` on non-Windows, and its
# PAMAuthenticator has no Windows implementation. Do not add these to
# requirements.txt or the Windows matrix will fail by design.
jupyterhub
jupyter
marimo
streamlit
"""

#: Known-unbuildable / not worth fighting. Failures here are expected.
EXPERIMENTAL = """\
# Experimental / not worth fighting.
#
# These are intentionally EXCLUDED from requirements.txt so that one stubborn
# package cannot turn the whole matrix red.
#
# --- pychm -----------------------------------------------------------------
# `pip install pychm` ALWAYS compiles from source on Python 3:
# PyPI has exactly one pychm wheel in its whole history
# (pychm-0.8.4.1-cp27-none-macosx_10_9_x86_64.whl) - Python 2.7 only.
# Building requires the native chmlib (chm_lib.h + -lchm and, on MSVC,
# -DWIN32 because the sources test `#ifdef WIN32` while MSVC defines only
# _WIN32). Install your distro's chmlib first if you actually want it:
#   archlinux: pacman -S chmlib        debian/ubuntu: apt install libchm-dev
#   guix/nix:  chmlib                  macos: brew install chmlib
pychm

# --- heavy / platform-bound ------------------------------------------------
# torch is deliberately not listed: install the CUDA-matched build by checking
# `nvidia-smi`, otherwise you get the CPU wheel you probably did not want.
# jupyterhub is in requirements-jupyterhub.txt (unix only).
# cudf: install via the rapidsai conda channel.
# MahjongGB: requires the MSVC C++ build tools on Windows.
# xlwings: drives Microsoft Excel; not supported on linux.
"""

PYPROJECT = """\
[build-system]
requires = ["setuptools>=64"]
build-backend = "setuptools.build_meta"

[project]
name = "{name}"
version = "0.1.0"
description = "myjupyter toolchain for {platform}/{distro} on Python {python}"
readme = "README.md"
requires-python = ">={python},<{next_minor}"
authors = [{{ name = "fufu", email = "fufurobot@outlook.com" }}]
license = {{ text = "MIT" }}

# NOTE: runtime dependencies are intentionally NOT declared here.
# They live in requirements*.txt so they can be split by buildability, and
# because this package is only a buildable anchor for the target directory:
# CI's acceptance bar is that `python -m build` succeeds for every target.

[project.optional-dependencies]
dev = ["ruff", "mypy", "pytest"]

[tool.setuptools]
packages = []
py-modules = ["{module}"]
"""

MODULE = '''\
"""Toolchain marker for the {platform}/{distro}/{python} target.

This module exists so that every target directory is a real, importable,
buildable Python project: CI requires `python -m build` to succeed for each
``<platform>/<distro>/<python-version>`` combination.
"""

__all__ = ["TARGET"]

TARGET = {{
    "platform": "{platform}",
    "distro": "{distro}",
    "python": "{python}",
}}
'''

README = """\
# {platform}/{distro}/{python}

Toolchain target for **{distro}** on the **{platform}** platform, Python
**{python}**.

| File | Purpose |
| --- | --- |
| `pyproject.toml` | Buildable package; CI requires `python -m build` to pass. |
| `requirements.txt` | Core toolchain, expected to build everywhere. |
| `requirements-jupyterhub.txt` | Unix only (jupyterhub needs PAM). |
| `requirements.experimental.txt` | Not worth fighting; failures expected. |
| `preinstall.sh` | Native prerequisites via this distro's package manager. |
| `preinstall.ps1` | Windows equivalent. |

## Usage

```console
$ ./preinstall.sh                      # native prerequisites
$ python -m pip install -r requirements.txt
$ python -m build                      # CI's acceptance check
```

Install the optional extras only if you need them:

```console
$ python -m pip install -r requirements-jupyterhub.txt        # unix only
$ python -m pip install -r requirements.experimental.txt      # may fail, by design
```
"""


def next_minor(version: str) -> str:
    major, minor = (int(p) for p in version.split("."))
    return f"{major}.{minor + 1}"


def scaffold(root: pathlib.Path, force: bool = False) -> list[pathlib.Path]:
    """Create the packaging files for every target triple."""
    written: list[pathlib.Path] = []
    for platform, distro, python in cl.all_targets():
        target = root / platform / distro / python
        target.mkdir(parents=True, exist_ok=True)

        files = {
            "pyproject.toml": PYPROJECT.format(
                name=f"{distro}-py{python.replace('.', '')}",
                platform=platform,
                distro=distro,
                python=python,
                next_minor=next_minor(python),
                module="toolchain",
            ),
            "toolchain.py": MODULE.format(
                platform=platform, distro=distro, python=python
            ),
            "README.md": README.format(
                platform=platform, distro=distro, python=python
            ),
            "requirements.txt": CORE,
            "requirements.experimental.txt": EXPERIMENTAL,
        }
        # jupyterhub only where it can possibly work.
        if platform == "unix":
            files["requirements-jupyterhub.txt"] = JUPYTERHUB

        for name, content in files.items():
            path = target / name
            if path.exists() and not force:
                continue
            path.write_text(content, encoding="utf-8", newline="\n")
            written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true",
                        help="overwrite existing files")
    args = parser.parse_args(argv)
    written = scaffold(REPO_ROOT, force=args.force)
    print(f"wrote {len(written)} file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
