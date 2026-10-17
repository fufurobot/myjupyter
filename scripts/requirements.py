#!/usr/bin/env python3
"""Generate broad, per-distro requirement lists for every target.

Per the backlog clarification the broad list is **intentional**: it is what I
actually want installed. Each ``<platform>/<distro>/<python-version>`` folder
holds its own ``requirements.txt`` containing the items that are installable
**only under that distro**, plus the shared core.

The leaf ``pyproject.toml`` then *adds* those requirements (``uv add -r
requirements.txt``), so CI can run ``uv sync --upgrade`` and turn upstream
drift into a pull request against ``dev``.

Platform split
--------------
* **unix**   -> ``jupyterhub`` (needs PAM via ``pamela``) and ``jupyterlab``
* **windows** -> ``jupyterlab`` only; ``jupyterhub`` has no Windows
  authenticator, which is exactly why the old tree had such different
  linux/ and windows/ folders.

Run: ``python3 scripts/requirements.py generate``
     ``python3 scripts/requirements.py add-to-pyprojects``
"""

from __future__ import annotations

import argparse
import importlib.util
import pathlib
import re
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


cl = _load("check_layout", "scripts/check_layout.py")

# --------------------------------------------------------------------------
# The broad lists
# --------------------------------------------------------------------------

#: Installable on every platform.
CORE = """\
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
"""

#: Unix-only: jupyterhub requires PAM via `pamela` (sys_platform != win32).
UNIX_ONLY = """\
# --- unix only -------------------------------------------------------------
# jupyterhub declares `pamela` for sys_platform != "win32", and its
# PAMAuthenticator has no Windows implementation. Keep it out of Windows.
jupyterhub
jupyter
jupyterlab
marimo
streamlit

# --- unix native tooling ---------------------------------------------------
# CLI/TUI and system-integration helpers that need POSIX subsystems.
pynput
"""

#: Windows-only additions.
WINDOWS_ONLY = """\
# --- windows only ----------------------------------------------------------
# jupyter lab (not jupyterhub: no Windows authenticator).
jupyter
jupyterlab

# Windows has no POSIX pynput backend guarantee, but the package does support
# Windows via win32 APIs, so it stays available here.
pynput
"""


def build_list(platform: str, distro: str, version: str) -> str:
    """Return the full requirements.txt text for a target."""
    header = f"""\
# Toolchain for {platform}/{distro} on Python {version}.
#
# This list is intentionally BROAD. Each distro folder carries what is
# installable only under that distro; the shared core is repeated below so the
# file is self-contained.
#
# The leaf pyproject.toml ADDS these requirements (uv add -r requirements.txt)
# and commits uv.lock, so CI's `uv sync --upgrade` turns upstream drift into a
# pull request against dev.
#
# Packages that need native libraries and are not worth fighting live in
# requirements.experimental.txt instead.

"""
    if platform == "unix":
        body = CORE + "\n" + UNIX_ONLY
    else:
        body = CORE + "\n" + WINDOWS_ONLY
    return header + body


def generate(force: bool = True) -> list[pathlib.Path]:
    """Write requirements.txt for every target that has a pyproject.toml."""
    written: list[pathlib.Path] = []
    for platform, distro, version in cl.all_targets():
        target = REPO_ROOT / platform / distro / version
        if not (target / "pyproject.toml").is_file():
            continue
        path = target / "requirements.txt"
        text = build_list(platform, distro, version)
        if path.exists() and not force:
            continue
        path.write_text(text, encoding="utf-8", newline="\n")
        written.append(path)
    return written


# --------------------------------------------------------------------------
# uv add -r requirements.txt
# --------------------------------------------------------------------------

def requirement_names(path: pathlib.Path) -> list[str]:
    names: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if not line or line.startswith("-") or line.startswith("http"):
            continue
        name = re.split(r"[=<>!~\[;@ ]", line, maxsplit=1)[0].strip()
        if name:
            names.append(name)
    return names


def declared_dependencies(target: pathlib.Path) -> set[str]:
    """Read ``project.dependencies`` names from the target's pyproject."""
    import tomllib

    data = tomllib.loads((target / "pyproject.toml").read_text(encoding="utf-8"))
    out = set()
    for dep in data.get("project", {}).get("dependencies") or []:
        out.add(re.split(r"[=<>!~\[;@ ]", dep, maxsplit=1)[0].strip().lower())
    return out


def sync_pyproject(target: pathlib.Path) -> bool:
    """Ensure ``project.dependencies`` lists exactly requirements.txt's names.

    This mirrors ``uv add -r requirements.txt``: the *names* are added to the
    pyproject, while version bounds are left to ``uv.lock`` so that
    ``uv sync --upgrade`` is free to move them.
    """
    import tomllib

    pyproject = target / "pyproject.toml"
    reqs = target / "requirements.txt"
    if not pyproject.is_file() or not reqs.is_file():
        return False

    wanted = requirement_names(reqs)
    text = pyproject.read_text(encoding="utf-8")
    data = tomllib.loads(text)
    if sorted(declared_dependencies(target)) == sorted(n.lower() for n in wanted):
        return False

    deps_block = "dependencies = [\n" + "".join(f'    "{n}",\n' for n in wanted) + "]\n"
    if re.search(r"^dependencies\s*=\s*\[.*?^\]", text, re.S | re.M):
        text = re.sub(r"^dependencies\s*=\s*\[.*?^\]\n", deps_block, text, flags=re.S | re.M)
    else:
        text = text.replace("[project]\n", f"[project]\n{deps_block}", 1)
    pyproject.write_text(text, encoding="utf-8", newline="\n")
    return True


def add_to_pyprojects() -> list[pathlib.Path]:
    changed: list[pathlib.Path] = []
    for platform, distro, version in cl.all_targets():
        target = REPO_ROOT / platform / distro / version
        if sync_pyproject(target):
            changed.append(target / "pyproject.toml")
    return changed


# --------------------------------------------------------------------------
# Lockfile generation (uses uv; network required)
# --------------------------------------------------------------------------

def lock_target(target: pathlib.Path, python: str) -> tuple[bool, str]:
    """Create/refresh ``uv.lock`` for one target. Returns (ok, message)."""
    result = subprocess.run(
        ["uv", "lock", "--python", python, "--quiet"],
        cwd=target, capture_output=True, text=True,
    )
    if result.returncode != 0:
        return False, result.stderr.strip()[-400:]
    return True, "ok"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("generate", "add-to-pyprojects", "lock"))
    parser.add_argument("--no-force", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "generate":
        written = generate(force=not args.no_force)
        print(f"wrote {len(written)} requirements.txt file(s)")
        return 0

    if args.command == "add-to-pyprojects":
        changed = add_to_pyprojects()
        print(f"updated {len(changed)} pyproject.toml file(s)")
        return 0

    ok = fail = 0
    for platform, distro, version in cl.all_targets():
        target = REPO_ROOT / platform / distro / version
        success, message = lock_target(target, version)
        if success:
            ok += 1
        else:
            fail += 1
            print(f"::warning::{platform}/{distro}/{version}: {message}", file=sys.stderr)
    print(f"locked {ok} target(s), {fail} failed")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
