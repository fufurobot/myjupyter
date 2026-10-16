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

Committed targets today:

```
unix/archlinux/3.14
windows/win11/3.13
```

## Why a `<distro>` layer?

Because the *same* prerequisite is a *different* package on every
distribution, installed by a *different* package manager. `pychm` is the
canonical example.

`pychm` publishes **no wheels**, so installing it always compiles
`chm/_chmlib.c`, which includes `<chm_lib.h>` and links `-lchm` against the
**native chmlib**. Without it the build dies with:

```
chm/chmlib_search.h:4:10: fatal error: chm_lib.h: No such file or directory
```

The library is not named the same anywhere:

| distro | package manager | libchm package |
| --- | --- | --- |
| archlinux | `pacman` | `chmlib` |
| debian / ubuntu | `apt-get` | `libchm-dev` (not `libchm1`, which is runtime-only) |
| guix | `guix` | `chmlib` |
| nixos | `nix` | `nixpkgs#chmlib` |
| macos | `brew` | `chmlib` |
| win10 / win11 | `vcpkg` / `choco` / MSYS2 | `chmlib` |

`scripts/libchm.sh` encodes that table, probes privileges with `sudo -n` so it
can never hang on a password prompt, and exports `CFLAGS`/`LDFLAGS` for
non-standard prefixes such as Homebrew or vcpkg.

## Layout validator

`scripts/check_layout.py` is the single source of truth for the vocabulary,
the runner mapping and the CI matrices. It also *rejects the legacy layout*, so
the migration cannot silently regress.

```console
$ python3 scripts/check_layout.py
layout OK: 2 target(s)
  unix/archlinux/3.14
  windows/win11/3.13

$ python3 scripts/check_layout.py --matrix fast   # JSON for CI
```

## Getting started

```console
$ cd unix/archlinux/3.14      # or windows/win11/3.13
$ ./preinstall.sh             # native deps, incl. chmlib for pychm
$ uv sync                     # or: uv pip install -r ../../../requirements.txt
```

On Windows use the PowerShell script, which is the native path there:

```powershell
cd windows\win11\3.13
.\preinstall.ps1
```

## Tests

```console
$ python3 -m pytest tests/ -q
```

The suite is written test-first (red commit → green commit):

| File | Covers |
| --- | --- |
| `tests/test_layout.py` | vocabularies, platform/distro pairing, tree scanning, matrices |
| `tests/test_preinstall.py` | every distro's `preinstall.sh`, libchm provisioning |
| `tests/test_daily_pr.py` | the "open a PR only when something changed" rule |
| `tests/test_ci.py` | pages site generation, workflow YAML, dependabot, devcontainer |

## CI

Branch model:

| Branch | Workflow | Scope |
| --- | --- | --- |
| `dev` | `dev.yml` | fast matrix — one Python per distro |
| `main` | `full.yml` | full matrix — every distro × every Python; publishes Pages |
| tags `v*.*.*` | `release.yml` | full verify, then publishes release artifacts |
| schedule | `daily.yml` | daily matrix; opens a PR **only if content actually changed** |

The daily job implements:

> submit pull requests for this project daily (if no remote update, do not
> submit pull request)

`scripts/daily_pr.py` content-hashes every target, compares against
`.ci/targets.json`, and exits without touching the remote when nothing changed.

## Secrets

Never commit `.env`. Copy the template and fill it in:

```console
$ cp .env.example .env
$ git check-ignore -v .env     # must print .gitignore:...:.env
```

`GITHUB_TOKEN` needs repository admin for this repository (CI, Pages,
Dependabot, releases).

## License

See [LICENSE](LICENSE).
