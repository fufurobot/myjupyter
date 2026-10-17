#!/usr/bin/env python3
"""Detect and propose upstream dependency updates.

This replaces the earlier manifest-hash approach, which only noticed that a
*directory* had changed and could never tell you that, say, pandas moved from
3.0.6 to 3.0.7 upstream.

Behaviour
---------
``upgrade``
    Resolve the newest compatible version of every package in each target's
    ``requirements.txt`` using ``uv pip compile``. Write the pinned resolution
    to ``.ci/resolved/<target>.txt``. Report ``changed=true`` (to
    ``$GITHUB_OUTPUT``) when any resolved set differs from what is committed.

``propose``
    Commit the updated resolutions on a dated branch and open a pull request -
    but only when ``changed`` is true and no PR is already open for that
    branch.

Why resolutions rather than editing ``requirements.txt``
-------------------------------------------------------
``requirements.txt`` stays human-curated and unpinned (it expresses intent).
The resolution file captures the concrete upstream state (it expresses
reality). Diffing reality is what tells you an upstream package moved.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import importlib.util
import os
import pathlib
import subprocess
import sys
import tempfile

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
RESOLVED_DIR = REPO_ROOT / ".ci" / "resolved"
API = "https://api.github.com"
TRACKING_ISSUE = 1


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


cl = _load("check_layout", "scripts/check_layout.py")


# --------------------------------------------------------------------------
# Resolution
# --------------------------------------------------------------------------

def resolve_requirements(req_file: pathlib.Path, python: str) -> str:
    """Return a pinned resolution of *req_file* for *python*, or raise."""
    with tempfile.NamedTemporaryFile("w+", suffix=".txt", delete=False) as out:
        out_path = out.name
    try:
        result = subprocess.run(
            [
                "uv", "pip", "compile", str(req_file),
                "--python", python,
                "--python-platform", "linux" if os.name != "nt" else "windows",
                "--no-header", "--no-annotate", "--quiet",
                "-o", out_path,
            ],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"uv pip compile failed for {req_file}:\n{result.stderr[-2000:]}"
            )
        return pathlib.Path(out_path).read_text(encoding="utf-8")
    finally:
        pathlib.Path(out_path).unlink(missing_ok=True)


def normalise(resolution: str) -> str:
    """Drop comments/blank lines so diffs reflect versions only."""
    lines = [
        line.strip()
        for line in resolution.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    return "\n".join(sorted(lines)) + "\n"


def upgrade_all(python: str = "3.13") -> tuple[bool, list[str]]:
    """Resolve every target's core requirements; return (changed, targets)."""
    RESOLVED_DIR.mkdir(parents=True, exist_ok=True)
    changed_targets: list[str] = []

    for platform, distro, version in cl.all_targets():
        target_dir = REPO_ROOT / platform / distro / version
        req = target_dir / "requirements.txt"
        if not req.is_file():
            continue

        key = f"{platform}-{distro}-{version}"
        out_file = RESOLVED_DIR / f"{key}.txt"
        old = out_file.read_text(encoding="utf-8") if out_file.is_file() else ""

        try:
            new = normalise(resolve_requirements(req, version))
        except RuntimeError as exc:
            print(f"warning: {key}: {exc}", file=sys.stderr)
            continue

        if new != normalise(old):
            out_file.write_text(new, encoding="utf-8")
            changed_targets.append(f"{platform}/{distro}/{version}")
            print(f"updated resolution: {key}")

    return bool(changed_targets), changed_targets


def resolution_diff(target: str) -> tuple[list[str], list[str]]:
    """Return (added/upgraded, removed) package lines for a target."""
    key = target.replace("/", "-")
    path = RESOLVED_DIR / f"{key}.txt"
    added: list[str] = []
    removed: list[str] = []
    if not path.is_file():
        return added, removed
    result = subprocess.run(
        ["git", "diff", "--unified=0", "--", str(path.relative_to(REPO_ROOT))],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    for line in result.stdout.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added.append(line[1:].strip())
        elif line.startswith("-"):
            removed.append(line[1:].strip())
    return added, removed


# --------------------------------------------------------------------------
# PR proposal
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# GitHub helpers (self-contained; no dependency on other scripts)
# --------------------------------------------------------------------------

def load_token() -> str | None:
    """Read a GitHub token from the environment or a gitignored ``.env``."""
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        return token.strip()
    env = REPO_ROOT / ".env"
    if env.is_file():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip() in {"GITHUB_TOKEN", "GH_TOKEN"}:
                return value.strip().strip('"').strip("'")
    return None


def api(method: str, path: str, token: str | None, data: dict | None = None):
    """Minimal GitHub REST call; never logs the token."""
    import json
    import urllib.error
    import urllib.request

    body = None if data is None else json.dumps(data).encode()
    url = path if path.startswith("http") else API + path
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "myjupyter-upstream-update")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read())
        except Exception:
            return exc.code, {}


def daily_branch_name(date: str) -> str:
    """Deterministic branch name for the upstream update of *date*."""
    return f"deps/upstream-{date}"


def should_open_pr(diff_lines: int, open_prs: int, force: bool = False) -> bool:
    """Open a PR only when something changed and none is already open."""
    if open_prs > 0:
        return False
    if force:
        return True
    return diff_lines > 0


def count_open_prs(repo: str, token: str | None, head_branch: str | None = None) -> int:
    query = f"/repos/{repo}/pulls?state=open&per_page=100"
    if head_branch:
        owner = repo.split("/")[0]
        query += f"&head={owner}:{head_branch}"
    status, payload = api("GET", query, token)
    if status != 200 or not isinstance(payload, list):
        print(f"warning: could not list PRs (status {status})", file=sys.stderr)
        return 0
    return len(payload)


def build_body(targets: list[str]) -> str:
    lines = [
        "Automated **upstream dependency update**.",
        "",
        "Generated by `.github/workflows/upstream-update.yml` via",
        "`scripts/upstream_update.py`, which re-resolves every target's core",
        "requirement set against current upstream and diffs the pins.",
        "",
        f"Refs #{TRACKING_ISSUE}",
        "",
    ]
    for target in targets:
        added, removed = resolution_diff(target)
        lines.append(f"### `{target}`")
        lines.append("")
        if not (added or removed):
            lines.append("_resolution unchanged_")
            lines.append("")
            continue
        if added:
            lines.append("Added / upgraded:")
            lines.append("")
            lines += [f"- `{a}`" for a in added if a]
            lines.append("")
        if removed:
            lines.append("Removed:")
            lines.append("")
            lines += [f"- `{r}`" for r in removed if r]
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def propose(repo: str, base: str, date: str, targets: list[str]) -> int:
    token = load_token()
    branch = daily_branch_name(date)

    open_prs = count_open_prs(repo, token, head_branch=branch)
    if not should_open_pr(diff_lines=len(targets), open_prs=open_prs):
        print("no upstream change or a PR is already open - not opening a PR")
        return 0

    git = lambda *a: subprocess.run(
        ["git", *a], cwd=REPO_ROOT, check=True, capture_output=True, text=True
    )
    git("config", "user.name", "github-actions[bot]")
    git("config", "user.email",
        "41898282+github-actions[bot]@users.noreply.github.com")
    git("checkout", "-B", branch)
    git("add", ".ci/resolved")
    git("commit", "-m", f"chore(deps): upstream dependency update {date}")
    git("push", "--force-with-lease", "-u", "origin", branch)

    status, payload = api(
        "POST", f"/repos/{repo}/pulls", token,
        {
            "title": f"chore(deps): upstream dependency update {date}",
            "head": branch,
            "base": base,
            "body": build_body(targets),
        },
    )
    if status in (200, 201):
        print("opened PR:", payload.get("html_url"))
        return 0
    if status == 422:
        print("a pull request for this branch already exists")
        return 0
    print(f"failed to open PR (status {status}): {payload}", file=sys.stderr)
    return 1


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _set_output(name: str, value: str) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"{name}={value}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("upgrade", "propose"))
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--python", default="3.13")
    parser.add_argument("--repo")
    parser.add_argument("--base", default="dev")
    parser.add_argument("--date", default=_dt.date.today().isoformat())
    args = parser.parse_args(argv)

    if args.command == "upgrade":
        changed, targets = upgrade_all(python=args.python)
        _set_output("changed", "true" if changed else "false")
        _set_output("targets", ",".join(targets))
        print(f"changed: {changed} ({len(targets)} target(s))")
        return 0

    if not args.repo:
        parser.error("propose requires --repo owner/name")
    # Recompute the target list from the working tree diff.
    result = subprocess.run(
        ["git", "status", "--porcelain", "--", ".ci/resolved"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    targets = sorted({
        line.split("resolved/")[-1].removesuffix(".txt").replace("-py", "/py")
        .replace("unix-", "unix/").replace("windows-", "windows/")
        for line in result.stdout.splitlines() if "resolved/" in line
    })
    return propose(args.repo, args.base, args.date, targets)


if __name__ == "__main__":
    raise SystemExit(main())
