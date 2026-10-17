#!/usr/bin/env python3
"""Reusable GitHub REST API client.

Reads GITHUB_TOKEN from environment or from .env next to the repo root.
Never prints the token.

Usage:
    python3 scripts/gh_api.py GET /repos/{owner}/{repo}
    python3 scripts/gh_api.py POST /repos/{owner}/{repo}/issues --data '{"title":"x"}'
    python3 scripts/gh_api.py PATCH /repos/... --data-file body.json
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

API = "https://api.github.com"
ROOT = pathlib.Path(__file__).resolve().parent.parent


def load_token() -> str:
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        return tok.strip()
    env = ROOT / ".env"
    if env.is_file():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            if k.strip() in {"GITHUB_TOKEN", "GH_TOKEN"}:
                return v.strip().strip('"').strip("'")
    sys.exit("error: no GITHUB_TOKEN found in environment or .env")


def request(method: str, path: str, data: object | None = None,
            token: str | None = None, accept: str = "application/vnd.github+json"):
    url = path if path.startswith("http") else API + path
    body = None if data is None else json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Accept", accept)
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "myjupyter-ci")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            payload = json.loads(raw)
        except Exception:
            payload = raw.decode(errors="replace")
        return e.code, payload


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("method")
    ap.add_argument("path")
    ap.add_argument("--data")
    ap.add_argument("--data-file")
    ap.add_argument("--no-auth", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    data = None
    if a.data_file:
        data = json.loads(pathlib.Path(a.data_file).read_text(encoding="utf-8"))
    elif a.data:
        data = json.loads(a.data)

    token = None if a.no_auth else load_token()
    status, payload = request(a.method.upper(), a.path, data, token)
    if not a.quiet:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if 200 <= status < 300 else 1


if __name__ == "__main__":
    raise SystemExit(main())
