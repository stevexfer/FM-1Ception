#!/usr/bin/env python3
"""The firmware facts' first step: every FM-1 firmware's repository the Cloud lists name, its GitHub metadata (the
fork's parent and source, when it was made, its languages, its licence) and a shallow clone of its default branch.

  harvest.py [--work DIR] [--jobs N] [--only OWNER/REPO ...]

DIR (default ~/FirmwareFacts) gets repos.json (each repository and the list entries naming it), meta/<key>.json
and repos/<key>/ (key: owner__repo, lower case). The lists are read from FM-1Ception's kept copies
(~/Library/Application Support/Xfer Records/FM-1Ception/CloudCatalog*.json). GitHub's token: GITHUB_TOKEN, else
git's credential for github.com. Already harvested repositories are skipped (their meta and clone kept).
"""
import argparse
import concurrent.futures as cf
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

SUPPORT = Path.home() / "Library/Application Support/Xfer Records/FM-1Ception"


def token():
    t = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if t:
        return t
    out = subprocess.run(["git", "credential", "fill"], input="protocol=https\nhost=github.com\n\n",
                         capture_output=True, text=True).stdout
    m = re.search(r"^password=(.+)$", out, re.M)
    return m.group(1) if m else None


def repo_of(url):
    """owner/repo from 'owner/repo' or a github.com URL, else None"""
    if not url:
        return None
    u = url.strip().removesuffix(".git").rstrip("/")
    m = re.match(r"^(?:https?://)?(?:www\.)?github\.com/([^/]+)/([^/#?]+)", u)
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    if re.match(r"^[\w.-]+/[\w.-]+$", u):
        return u
    return None


def listed():
    """{owner/repo (as listed): [entries]}: mutant.cloud's FM-1 firmwares, fm1-emu's list and the Hub's"""
    repos = {}

    def add(r, entry):
        key = repo_of(r)
        if key:
            repos.setdefault(key, []).append(entry)

    m = json.loads((SUPPORT / "CloudCatalog.json").read_text())
    for e in m.get("entries", []):
        if e.get("kind") == "firmware" and "fm1" in (e.get("devices") or []):
            add(e.get("repo"), {"list": "mutant", "id": e.get("id"), "name": e.get("name"), "base": e.get("base"),
                                "license": e.get("license"), "tags": e.get("tags")})
    emu = SUPPORT / "CloudCatalog-2.json"
    if emu.exists():
        for e in json.loads(emu.read_text()).get("firmwares", []):
            add(e.get("repo"), {"list": "fm1-emu", "id": e.get("id"), "name": e.get("name")})
    hub = SUPPORT / "CloudCatalog-hub.json"
    if hub.exists():
        for e in json.loads(hub.read_text()).get("firmwares", []):
            add(e.get("repo"), {"list": "hub", "id": e.get("id"), "name": e.get("name")})
    return repos


def key_of(repo):
    return repo.lower().replace("/", "__")


def api(path, tok):
    req = urllib.request.Request(f"https://api.github.com{path}", headers={
        "Accept": "application/vnd.github+json", "User-Agent": "FM-1Ception-facts",
        **({"Authorization": f"Bearer {tok}"} if tok else {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return {"error": e.code}


def harvest_one(repo, work, tok):
    k = key_of(repo)
    meta_file = work / "meta" / f"{k}.json"
    clone = work / "repos" / k
    if meta_file.exists():
        meta = json.loads(meta_file.read_text())
    else:
        info = api(f"/repos/{repo}", tok)
        meta = {"repo": repo, "error": info.get("error")} if "error" in info else {
            "repo": info["full_name"],
            "listed_as": repo,
            "default_branch": info.get("default_branch"),
            "created": info.get("created_at"),
            "pushed": info.get("pushed_at"),
            "size_kb": info.get("size"),
            "fork": info.get("fork"),
            "parent": (info.get("parent") or {}).get("full_name"),
            "source": (info.get("source") or {}).get("full_name"),
            "license": (info.get("license") or {}).get("spdx_id"),
            "description": info.get("description"),
            "homepage": info.get("homepage"),
            "topics": info.get("topics"),
            "archived": info.get("archived"),
            "stars": info.get("stargazers_count"),
            "languages": api(f"/repos/{repo}/languages", tok),
        }
        meta_file.write_text(json.dumps(meta, indent=1))
    if "error" not in meta or not meta["error"]:
        if not (clone / ".git").exists():
            r = subprocess.run(["git", "clone", "--quiet", "--depth", "1", "--no-tags", f"https://github.com/{meta['repo']}.git",
                                str(clone)], capture_output=True, text=True, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
            if r.returncode:
                meta["clone_error"] = r.stderr.strip()[-300:]
                meta_file.write_text(json.dumps(meta, indent=1))
        if (clone / ".git").exists() and "commit" not in meta:
            meta["commit"] = subprocess.run(["git", "-C", str(clone), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
            meta["commit_date"] = subprocess.run(["git", "-C", str(clone), "log", "-1", "--format=%cI"], capture_output=True, text=True).stdout.strip()
            meta_file.write_text(json.dumps(meta, indent=1))
    return repo, meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default=str(Path.home() / "FirmwareFacts"))
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    work = Path(a.work)
    (work / "meta").mkdir(parents=True, exist_ok=True)
    (work / "repos").mkdir(parents=True, exist_ok=True)
    repos = listed()
    (work / "repos.json").write_text(json.dumps(repos, indent=1, sort_keys=True))
    todo = [r for r in repos if not a.only or r in a.only]
    tok = token()
    print(f"{len(repos)} repositories listed; harvesting {len(todo)} ({'with' if tok else 'without'} a GitHub token)")
    done = errors = 0
    with cf.ThreadPoolExecutor(a.jobs) as ex:
        for repo, meta in ex.map(lambda r: harvest_one(r, work, tok), todo):
            done += 1
            if meta.get("error") or meta.get("clone_error"):
                errors += 1
                print(f"  {repo}: {meta.get('error') or meta.get('clone_error')}", file=sys.stderr)
            if done % 50 == 0:
                print(f"  {done}/{len(todo)}")
    print(f"done: {done}, {errors} with errors -> {work}")


if __name__ == "__main__":
    main()
