# myjupyter

My preferred Python toolchain, arranged by **platform → distribution → Python
version**.

```
<platform>/<distro>/<python-version>/
```

| Segment | Allowed values |
| --- | --- |
| `platform` | `windows`, `unix` |
| `distro` | `winxp`, `win7`, `win10`, `win11`, `macos`, `ubuntu`, `debian`, `archlinux`, `guix`, `nixos` |
| `python-version` | `3.10` … latest (`3.14`) |

All 50 combinations exist, and **every one holds a `pyproject.toml` that
builds**. That is the acceptance bar, and it is verified by CI on real
machines — nothing is built locally.

## What each target contains

| File | Purpose |
| --- | --- |
| `pyproject.toml` | A real, buildable package. CI requires `uv build` to pass. |
| `requirements.txt` | Core toolchain — portable, expected to build everywhere. |
| `requirements-jupyterhub.txt` | **Unix only.** jupyterhub needs PAM via `pamela`; its `PAMAuthenticator` has no Windows implementation. |
| `requirements.experimental.txt` | Packages not worth fighting. Failures here are expected and non-fatal. |
| `preinstall.sh` | Native build prerequisites via this distro's own package manager. |
| `preinstall.ps1` | Windows equivalent (PowerShell is native there). |
| `toolchain.py` | Marker module so the package is importable. |

## Requirements are split by buildability

One stubborn package must never turn the whole matrix red, so the files are
split by whether they are expected to build:

* **`requirements.txt`** — portable core. The matrix fails if this fails.
* **`requirements-jupyterhub.txt`** — unix-only. Absent on Windows by design;
  that is *why* the old tree had such different `linux/` and `windows/`
  folders, and the `<distro>` layer makes the reason explicit.
* **`requirements.experimental.txt`** — allowed to fail.

### Why `pychm` is isolated rather than fixed

`pychm` publishes **no wheels for Python 3**. PyPI has exactly one `pychm`
wheel in its entire history:

```
pychm-0.8.4.1-cp27-none-macosx_10_9_x86_64.whl     # Python 2.7, macOS only
```

So every Python 3 `pip install pychm` compiles `chm/_chmlib.c`, which needs
the native chmlib (`<chm_lib.h>` and `-lchm`). Getting it to build on Windows
means vendoring the library and then discovering that its sources test
`#ifdef WIN32` while MSVC defines only `_WIN32` — that is a lot of effort for
a package that is not important to this toolchain.

It therefore lives in `requirements.experimental.txt`. If you do want it,
install your distro's chmlib first:

| distro | package manager | package |
| --- | --- | --- |
| archlinux | `pacman` | `chmlib` |
| debian / ubuntu | `apt` | `libchm-dev` (not `libchm1`, which is runtime only) |
| guix / nixos | `guix` / `nix` | `chmlib` |
| macos | `brew` | `chmlib` |

## Usage

```console
$ cd unix/archlinux/3.14                  # or windows/win11/3.13
$ ./preinstall.sh                         # native build prerequisites
$ python -m pip install -r requirements.txt
$ python -m build                         # CI's acceptance check
```

Optional extras:

```console
$ python -m pip install -r requirements-jupyterhub.txt     # unix only
$ python -m pip install -r requirements.experimental.txt   # may fail, by design
```

## Layout validator

`scripts/check_layout.py` is the single source of truth for the vocabulary,
the runner mapping, and the CI matrices. It also rejects the legacy
`<python-version>/<platform>` layout so migration cannot regress.

```console
$ python3 scripts/check_layout.py
$ python3 scripts/check_layout.py --matrix fast   # JSON for CI
```

## Scaffolding

```console
$ python3 scripts/scaffold_targets.py          # fill in missing target files
$ python3 scripts/scaffold_targets.py --force  # regenerate everything
```

## CI

| Workflow | Trigger | Purpose |
| --- | --- | --- |
| `matrix.yml` | push / PR | **Primary CI.** Builds every target on real runners: `uv build` + core requirements. Fast tier on `dev`/PRs, full tier (all 50) on `main`. |
| `upstream-update.yml` | daily 04:41 UTC | Re-resolves every target's core requirements against upstream and opens a PR **only when packages actually changed**. |
| `dev.yml` | push to `dev` | Fast checks. |
| `full.yml` | push to `main` | Full checks + Pages. |
| `pages.yml` | reusable | Publishes the matrix site. |
| `release.yml` | tag `v*.*.*` | Full verify, then publishes release artifacts. |

The matrix is generated from `check_layout.py`, so it can never drift from the
directory layout. Experimental and unix-only sets run in an `optional` tier
with `continue-on-error`, because they are *expected* to have gaps.

### Upstream updates

`scripts/upstream_update.py upgrade` re-resolves each target's core
requirements with `uv pip compile` and records the pins under
`.ci/resolved/`. Diffing the resolved pins is what tells you an upstream
package actually moved — a directory hash never could. The workflow verifies
the upgraded set on a real runner before proposing the PR.

## Tests

```console
$ python3 -m pytest tests/ -q
```

| File | Covers |
| --- | --- |
| `tests/test_layout.py` | vocabularies, pairing, tree scanning, matrix generation |
| `tests/test_targets.py` | every target's pyproject builds; requirement split |
| `tests/test_preinstall.py` | per-distro scripts use their own package manager |
| `tests/test_ci.py` | workflows, upstream updater, site, repo automation |

## Secrets

Never commit `.env`.

```console
$ cp .env.example .env
$ git check-ignore -v .env     # must print .gitignore:...:.env
```

`GITHUB_TOKEN` needs repository admin for this repository (CI, Pages,
Dependabot, releases).

## License

See [LICENSE](LICENSE).
