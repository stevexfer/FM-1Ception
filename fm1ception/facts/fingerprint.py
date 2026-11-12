#!/usr/bin/env python3
"""Code fingerprints (MOSS's winnowing): each C, C++ or Rust file's comments and spacing taken out, its tokens
hashed 25 at a time, and the least hash of every 8 in a row kept. Two files that share many of them share code,
whatever their names, comments or formatting. Identical files are fingerprinted once.

  fingerprint.py [--work DIR] [--jobs N]

Writes DIR/fp/refs.pkl and DIR/fp/repos.pkl: {"files": [(owner, path, sha1)], "fps": {sha1: array of hashes}}, the
owner a reference's name (refs.py) or a repository's key (harvest.py).
"""
import argparse
import array
import hashlib
import multiprocessing as mp
import os
import pickle
import re
from pathlib import Path

EXTS = {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".inl", ".rs"}
MAX_BYTES = 1_500_000
K, W = 25, 8
MASK = (1 << 61) - 1
COMMENTS = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)
TOKENS = re.compile(r"[A-Za-z_]\w*|0[xX][0-9A-Fa-f]+|\d+(?:\.\d*)?(?:[eE][-+]?\d+)?[fFuUlL]*|[^\s\w]")


def fingerprints(text):
    toks = TOKENS.findall(COMMENTS.sub(" ", text))
    if len(toks) < K:
        return array.array("Q")
    # each token's hash, then a rolling hash of K of them
    th = [int.from_bytes(hashlib.blake2b(t.encode(), digest_size=8).digest(), "little") & MASK for t in toks]
    base = 1_000_003
    top = pow(base, K - 1, MASK)
    h = 0
    for t in th[:K]:
        h = (h * base + t) % MASK
    grams = [h]
    for i in range(K, len(th)):
        h = ((h - th[i - K] * top) * base + th[i]) % MASK
        grams.append(h)
    # winnowing: the least of each window of W (the rightmost on ties), each kept once
    out, last = array.array("Q"), -1
    for i in range(0, max(1, len(grams) - W + 1)):
        win = grams[i:i + W]
        m = min(win)
        j = i + (len(win) - 1 - win[::-1].index(m))
        if j != last:
            out.append(m)
            last = j
    return out


def sources(root):
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != ".git" and d != "node_modules"]
        for f in files:
            if os.path.splitext(f)[1].lower() in EXTS:
                p = os.path.join(dirpath, f)
                try:
                    if os.path.getsize(p) <= MAX_BYTES:
                        yield p
                except OSError:
                    pass


def read_and_hash(p):
    try:
        b = open(p, "rb").read()
    except OSError:
        return p, None, None
    return p, hashlib.sha1(b).hexdigest(), b


def fp_of(item):
    sha, b = item
    return sha, fingerprints(b.decode("utf-8", "replace"))


def index(owners, jobs, out):
    files, todo = [], {}
    for owner, root in owners:
        for p in sources(root):
            _, sha, b = read_and_hash(p)
            if sha is None:
                continue
            files.append((owner, os.path.relpath(p, root), sha))
            if sha not in todo:
                todo[sha] = b
    print(f"  {len(files)} files, {len(todo)} distinct")
    with mp.Pool(jobs) as pool:
        fps = dict(pool.imap_unordered(fp_of, todo.items(), chunksize=64))
    with open(out, "wb") as f:
        pickle.dump({"files": files, "fps": fps}, f, protocol=pickle.HIGHEST_PROTOCOL)
    print(f"  -> {out} ({sum(len(v) for v in fps.values())} fingerprints)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default=str(Path.home() / "FirmwareFacts"))
    ap.add_argument("--jobs", type=int, default=max(1, mp.cpu_count() - 2))
    ap.add_argument("--only", choices=["refs", "repos"])
    a = ap.parse_args()
    work = Path(a.work)
    (work / "fp").mkdir(exist_ok=True)
    if a.only != "repos":
        print("references")
        index([(d.name, str(d)) for d in sorted((work / "refs").iterdir()) if d.is_dir()], a.jobs, work / "fp" / "refs.pkl")
    if a.only != "refs":
        print("firmware repositories")
        index([(d.name, str(d)) for d in sorted((work / "repos").iterdir()) if d.is_dir()], a.jobs, work / "fp" / "repos.pkl")


if __name__ == "__main__":
    main()
