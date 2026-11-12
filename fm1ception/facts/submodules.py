#!/usr/bin/env python3
"""The harvested repositories' submodules, shallow (an engine or a hardware layer is often one: Felucca's are),
and each submodule's repository and commit noted in meta/<key>.json under "submodules".

  submodules.py [--work DIR] [--jobs N]
"""
import argparse
import concurrent.futures as cf
import json
import os
import subprocess
from pathlib import Path

ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}


def one(clone, meta_file):
    if not (clone / ".gitmodules").exists():
        return clone.name, None
    r = subprocess.run(["git", "-C", str(clone), "submodule", "update", "--init", "--depth", "1", "--recursive", "--jobs", "4"],
                       capture_output=True, text=True, env=ENV, timeout=900)
    status = subprocess.run(["git", "-C", str(clone), "submodule", "status", "--recursive"], capture_output=True, text=True).stdout
    urls = subprocess.run(["git", "-C", str(clone), "config", "-f", ".gitmodules", "--get-regexp", r"submodule\..*\.url"],
                          capture_output=True, text=True).stdout
    url_of = {}
    for line in urls.splitlines():
        k, _, v = line.partition(" ")
        url_of[k.split(".", 1)[1].rsplit(".", 1)[0]] = v
    subs = []
    for line in status.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2:
            sha, path = parts[0].lstrip("-+U"), parts[1]
            subs.append({"path": path, "commit": sha, "url": url_of.get(path) or next((u for n, u in url_of.items() if path.endswith(n)), None),
                         "fetched": not line.startswith("-")})
    meta = json.loads(meta_file.read_text())
    meta["submodules"] = subs
    if r.returncode:
        meta["submodule_error"] = r.stderr.strip()[-300:]
    meta_file.write_text(json.dumps(meta, indent=1))
    return clone.name, (len(subs), r.returncode)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default=str(Path.home() / "FirmwareFacts"))
    ap.add_argument("--jobs", type=int, default=6)
    a = ap.parse_args()
    work = Path(a.work)
    clones = [c for c in sorted((work / "repos").iterdir()) if (c / ".gitmodules").exists()]
    print(f"{len(clones)} repositories with submodules")
    failed = 0
    with cf.ThreadPoolExecutor(a.jobs) as ex:
        for name, res in ex.map(lambda c: one(c, work / "meta" / f"{c.name}.json"), clones):
            if res and res[1]:
                failed += 1
                print(f"  {name}: some submodules not fetched")
    print(f"done; {failed} with submodules not fetched")


if __name__ == "__main__":
    main()
