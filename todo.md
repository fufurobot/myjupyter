# TODO

## Sprint 1 — platform/distro/python matrix — DONE

- [x] `<platform>/<distro>/<python-version>` layout
      (`windows`/`unix` × `winxp win7 win10 win11 macos ubuntu debian
      archlinux guix nixos` × Python `3.10`…latest), enforced by
      `scripts/check_layout.py`.
- [x] All 50 targets scaffolded with a buildable `pyproject.toml`
      (`scripts/scaffold_targets.py`).
- [x] CI matrix (`matrix.yml`) builds every target **on real runners**; nothing
      is built locally.
- [x] Automated upstream-update PRs (`.github/workflows/upstream-update.yml`)
      that open a pull request only when upstream packages actually changed.
- [x] Requirement split by buildability: core / unix-only jupyterhub /
      experimental.
- [x] `pychm` isolated in `requirements.experimental.txt` instead of fought.
      (PyPI has published exactly one pychm wheel ever: `cp27`, macOS.)

## Sprint 2 — startability, per-distro reqs, releases — DONE

- [x] **Broad, per-distro requirements.** `requirements.txt` carries what is
      installable only under that distro (unix: jupyterhub + jupyterlab;
      windows: jupyterlab). The leaf `pyproject.toml` adds them
      (`uv add -r` semantics) and every target commits `uv.lock`, so
      `uv sync --upgrade` can turn upstream drift into a PR on `dev`.
- [x] **Jupyter startability proven in CI** — `jupyter lab` on Windows,
      `jupyterhub` on Unix, each polled until the server answers.
- [x] **Dependabot targets `dev`** (`target-branch: dev` on every updater).
- [x] **Version-keyed releases** on every push to `main`: unchanged version
      updates the release in place, a changed version creates a new one.
- [x] **GitHub Pages removed** (not needed).

## Backlog

- [ ] Expand the core requirement lists beyond the portable baseline. The
      original `requirements.txt` was very broad; anything that turns out to
      be non-portable should move to `requirements.experimental.txt` rather
      than block the matrix.
- [ ] Add a `DAILY_PR_TOKEN` repository secret if branch protection blocks the
      default `GITHUB_TOKEN` from pushing `deps/upstream-*` branches.
- [ ] Verify each distro's `preinstall.sh` on its native runner (currently only
      `unix/archlinux` is exercised on the real Arch user machine; the rest are
      verified for structure and package-manager correctness by unit tests).
