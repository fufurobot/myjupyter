#!/usr/bin/env python3
"""Version-keyed release publishing.

Requirement: every push to ``main`` publishes everything produced by
``uv build`` as a release artifact, keyed by the ``pyproject.toml`` version:

* version **unchanged** since the existing release -> update that release
  **in place** (re-upload / refresh its assets)
* version **changed** -> create a **new** release

The decision logic lives here rather than in YAML so it can be unit-tested;
``.github/workflows/release.yml`` only has to call it.

Usage
-----
    python3 scripts/release.py plan   --dist dist
    python3 scripts/release.py publish --dist dist --repo owner/name
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import tomllib
import urllib.error
import urllib.parse
import urllib.request

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
API = "https://api.github.com"

#: The canonical target whose pyproject version keys the release.
VERSION_SOURCE = pathlib.Path("unix") / "ubuntu" / "3.10"


# --------------------------------------------------------------------------
# Pure decision logic (unit-tested)
# --------------------------------------------------------------------------

def tag_for(version: str) -> str:
    """Return the release tag for *version* (``0.1.0`` -> ``v0.1.0``)."""
    return f"v{version.lstrip('v')}"


def should_create_release(existing_tag: str | None, version: str) -> bool:
    """True when a *new* release is needed rather than an in-place update.

    *existing_tag* is the tag of the release already published, if any. It is
    compared in normalised ``vX.Y.Z`` form, so a bare ``1.2.3`` is treated the
    same as ``v1.2.3``.
    """
    if existing_tag is None:
        return True
    return tag_for(existing_tag) != tag_for(version)


def plan_release(existing_tag: str | None, version: str) -> str:
    """Return ``"create"`` or ``"update"`` for the given state."""
    return "create" if should_create_release(existing_tag, version) else "update"


def read_version(target: pathlib.Path) -> str:
    """Read ``project.version`` from the target's ``pyproject.toml``."""
    data = tomllib.loads((target / "pyproject.toml").read_text(encoding="utf-8"))
    version = data.get("project", {}).get("version")
    if not version:
        raise SystemExit(f"error: no [project].version in {target}/pyproject.toml")
    return str(version)


def collect_artifacts(dirs: list[pathlib.Path]) -> list[pathlib.Path]:
    """Return built distributions (wheels and sdists) from *dirs*."""
    found: list[pathlib.Path] = []
    for directory in dirs:
        if not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            if path.is_file() and (path.suffix == ".whl" or path.name.endswith(".tar.gz")):
                found.append(path)
    return found


# --------------------------------------------------------------------------
# GitHub helpers
# --------------------------------------------------------------------------

def load_token() -> str | None:
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
    body = None if data is None else json.dumps(data).encode()
    url = path if path.startswith("http") else API + path
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "myjupyter-release")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw)
        except Exception:
            return exc.code, {"message": raw.decode(errors="replace")}


def existing_release_tag(repo: str, version: str, token: str | None) -> str | None:
    """Return the tag of the release matching *version*, if any."""
    wanted = tag_for(version)
    status, payload = api("GET", f"/repos/{repo}/releases/tags/{wanted}", token)
    if status == 200 and isinstance(payload, dict):
        return payload.get("tag_name")
    return None


def latest_release_tag(repo: str, token: str | None) -> str | None:
    status, payload = api("GET", f"/repos/{repo}/releases/latest", token)
    if status == 200 and isinstance(payload, dict):
        return payload.get("tag_name")
    return None


def upload_asset(upload_url: str, path: pathlib.Path, token: str | None) -> int:
    """Upload (or replace) one release asset."""
    # upload_url looks like https://uploads.github.com/repos/o/r/releases/1/assets{?name,label}
    base = upload_url.split("{")[0]
    req = urllib.request.Request(
        f"{base}?name={urllib.parse.quote(path.name)}",
        data=path.read_bytes(),
        method="POST",
    )
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Content-Type", "application/octet-stream")
    req.add_header("User-Agent", "myjupyter-release")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def can_write_releases(repo: str, token: str | None) -> bool:
    """Check whether *token* may actually publish releases for *repo*.

    ``permissions.push`` is NOT sufficient evidence: a fine-grained token can
    report ``admin: true`` on the repository yet still be refused by the
    releases API when its own Contents/Pull-requests scopes do not include the
    needed access (observed on this repo). So the check probes the real
    endpoint instead of trusting the permission block.

    The probe is deliberately *read-shaped*: it creates nothing.
    """
    if not token:
        return False

    # 1. The repo must be readable at all.
    status, payload = api("GET", f"/repos/{repo}", token)
    if status != 200 or not isinstance(payload, dict):
        print(f"error: cannot read repository {repo} (status {status})", file=sys.stderr)
        return False
    perms = payload.get("permissions") or {}
    if not perms.get("push"):
        print(
            f"error: token cannot push to {repo} (permissions: {perms}). "
            "Release publishing needs Contents: write.",
            file=sys.stderr,
        )
        return False

    # 2. Probe the release write path without mutating anything: an empty
    #    POST is rejected for validation reasons (422) when the token is
    #    *allowed*, but refused with 403/404 when it is not.
    status, body = api("POST", f"/repos/{repo}/releases", token, {"__probe__": True})
    if status in (401, 403, 404):
        print(
            f"error: token may not write releases to {repo} (status {status}: "
            f"{(body or {}).get('message', '')}). Give the token "
            "Contents: write (and, for a fine-grained token, Releases access).",
            file=sys.stderr,
        )
        return False
    # 201 would mean we accidentally created something - clean it up.
    if status == 201 and isinstance(body, dict) and body.get("id"):
        api("DELETE", f"/repos/{repo}/releases/{body['id']}", token)
        print("warning: probe created a release, removed it again", file=sys.stderr)
    return True


def preflight(repo: str | None, token: str | None) -> bool:
    """Return True when a release can realistically be published."""
    if not token:
        print(
            "error: no GitHub token found (set GITHUB_TOKEN or DAILY_PR_TOKEN)",
            file=sys.stderr,
        )
        return False
    if not repo:
        print("error: no repository specified", file=sys.stderr)
        return False
    return can_write_releases(repo, token)


def upload_assets(
    release: dict, artifacts: list[pathlib.Path], token: str | None
) -> int:
    """Upload every artifact; return the number of failures."""
    failures = 0
    total = len(artifacts)
    for index, artifact in enumerate(artifacts, 1):
        code = upload_asset(release["upload_url"], artifact, token)
        if code in (200, 201):
            print(f"[{index}/{total}] uploaded {artifact.name}")
        else:
            failures += 1
            print(
                f"[{index}/{total}] FAILED {artifact.name}: HTTP {code}",
                file=sys.stderr,
            )
    return failures


def publish(repo: str, dist: pathlib.Path, token: str | None) -> int:
    version = read_version(REPO_ROOT / VERSION_SOURCE)
    tag = tag_for(version)
    artifacts = collect_artifacts([dist])
    print(f"version={version} tag={tag} artifacts={len(artifacts)}")

    found_tag = existing_release_tag(repo, version, token)
    action = plan_release(found_tag, version)
    print(f"planned action: {action}")

    body = (
        f"Artifacts built by `uv build` for version {version}.\n\n"
        f"Generated by `.github/workflows/release.yml`."
    )

    if action == "create":
        status, payload = api(
            "POST", f"/repos/{repo}/releases", token,
            {"tag_name": tag, "name": tag, "body": body, "draft": False},
        )
        if status not in (200, 201):
            print(f"failed to create release ({status}): {payload}", file=sys.stderr)
            return 1
    else:
        release_id = payload_id = None
        status, payload = api("GET", f"/repos/{repo}/releases/tags/{tag}", token)
        if status != 200:
            print(f"failed to read release ({status}): {payload}", file=sys.stderr)
            return 1
        release_id = payload["id"]
        # Refresh the body in place.
        api("PATCH", f"/repos/{repo}/releases/{release_id}", token, {"body": body})
        # Replace existing assets so the release reflects the new build.
        for asset in payload.get("assets", []):
            api("DELETE", f"/repos/{repo}/releases/assets/{asset['id']}", token)
        payload_id = release_id

    status, release = api("GET", f"/repos/{repo}/releases/tags/{tag}", token)
    if status != 200:
        print(f"could not reload release: {release}", file=sys.stderr)
        return 1

    failures = upload_assets(release, artifacts, token)
    if failures:
        print(f"::error::{failures}/{len(artifacts)} asset uploads failed", file=sys.stderr)
        return 1

    print(f"release {tag} published ({action}, {len(artifacts)} assets)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("plan", "publish", "preflight"))
    parser.add_argument("--dist", default="dist")
    parser.add_argument("--repo")
    args = parser.parse_args(argv)

    version = read_version(REPO_ROOT / VERSION_SOURCE)
    tag = tag_for(version)

    if args.command == "preflight":
        ok = preflight(args.repo, load_token())
        print("preflight:", "ok" if ok else "FAILED")
        return 0 if ok else 1

    if args.command == "plan":
        token = load_token()
        found = existing_release_tag(args.repo, version, token) if args.repo else None
        action = plan_release(found, version)
        out = os.environ.get("GITHUB_OUTPUT")
        if out:
            with open(out, "a", encoding="utf-8") as fh:
                fh.write(f"version={version}\n")
                fh.write(f"tag={tag}\n")
                fh.write(f"action={action}\n")
        print(f"version={version} tag={tag} action={action}")
        return 0

    if not args.repo:
        parser.error("publish requires --repo owner/name")
    return publish(args.repo, pathlib.Path(args.dist), load_token())


if __name__ == "__main__":
    raise SystemExit(main())
