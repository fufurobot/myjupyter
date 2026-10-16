# TODO

## Sprint 1 — platform/distro/python matrix + pychm build fix — DONE

- [x] Restructure to `<platform>/<distro>/<python-version>`
      (`windows`/`unix` × `winxp win7 win10 win11 macos ubuntu debian
      archlinux guix nixos` × Python `3.10`…latest).
      Enforced by `scripts/check_layout.py`; the legacy two-segment layout is
      now rejected so it cannot regress.
- [x] GitHub CI matrix that opens a daily pull request **only when the remote
      actually changed** (`.github/workflows/daily.yml` +
      `scripts/daily_pr.py`, manifest at `.ci/targets.json`).
- [x] Fix the `pychm` build error on this machine and append it to
      `preinstall.sh`.
      Root cause: pychm ships no wheels, so it compiles `_chmlib.c`, which
      needs the native `chmlib` (`chm_lib.h` + `-lchm`). Fixed per-distro in
      `scripts/libchm.sh`, wired into every `preinstall.sh`/`preinstall.ps1`.

## Backlog

- [ ] Fill in the remaining `<distro>/<python-version>` target directories.
      Today only `unix/archlinux/3.14` and `windows/win11/3.13` exist; the
      validator and matrices already cover all 50 combinations, so a target
      only needs to be created when its dependency set is actually curated.
- [ ] Enable GitHub Pages once (Settings → Pages → Source: GitHub Actions).
      The API refused it: the current token lacks the Pages admin scope
      (`403 Resource not accessible by personal access token`).
- [ ] Add a `DAILY_PR_TOKEN` repository secret if branch protection blocks the
      default `GITHUB_TOKEN` from pushing the `ci/daily-*` branch.
