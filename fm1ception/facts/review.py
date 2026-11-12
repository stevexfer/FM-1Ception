#!/usr/bin/env python3
"""The hand review: which repositories need a person's (or an agent's) reading, a brief of each one's automatic report
to start from, and a check of the reviews written back.

  review.py queue [--work DIR] [--batch N]   -> DIR/review/queue.json, DIR/review/briefs/<key>.txt, DIR/review/batches/NN.txt
  review.py check [--work DIR] [--batch NN]  -> what's missing or malformed in DIR/review/done/<key>.json

A repository is queued when its list gives no base or says it is original, the base its code says differs from its list's, it holds a
reference project's code in its own files, or its licence and that code's disagree.

A review, DIR/review/done/<key>.json, is the facts a reader can stand behind, each with its evidence:

{
  "repo": "owner/name",
  "summary": "one or two plain sentences: what the firmware is and what makes its sound",
  "original": true,                      # its own code, built on no other firmware (the hardware layer aside)
  "base": {"repo": "owner/name", "name": "Felucca", "how": "fork|copy|submodule|stated|code",
           "confidence": "high|medium|low", "evidence": "..."} or null,
  "hardware": "fm1-base|felucca-bsp|fm1_open|own|other: ...",
  "engines": [{"name": "the engine as the firmware calls it", "kind": "FM|wavetable|virtual analog|samples|granular|
               physical modelling|additive|formant / speech|chip emulation|drum synthesis|other",
               "origin": "own|<project>", "evidence": "file paths", "confidence": "high|medium|low"}],
  "origins": [{"project": "Mutable Instruments Plaits", "author": "Emilie Gillet", "license": "MIT",
               "what": "the parts taken", "how": "code|port|credited|technique",
               "evidence": "file paths, the credit's words", "confidence": "high|medium|low"}],
  "techniques": ["Zavalishin TPT state-variable filter", ...],      # named algorithms its code implements
  "assets": "samples, wavetables, fonts and where they come from, '' for none",
  "findings": [{"kind": "licence|uncredited|ai|other", "text": "a finding, not an accusation",
                "evidence": "...", "confidence": "high|medium|low"}]
}
"""
import argparse
import json
import sys
from pathlib import Path

LICENCE_OF = {  # the reference projects' code licences (their licence files; README where the repository has none)
    "airwindows": "MIT", "audible-instruments": "GPL-3.0", "befaco": "GPL-3.0", "chowdsp": "BSD-3-Clause / GPL-3.0 (per module)",
    "cmsis-dsp": "Apache-2.0", "daisysp": "MIT", "dexed": "GPL-3.0", "freeverb": "public domain", "gme": "LGPL-2.1",
    "helm": "GPL-3.0", "kissfft": "BSD-3-Clause", "msfa": "Apache-2.0", "mutable-ambika": "GPL-3.0",
    "mutable-avril": "GPL-3.0", "mutable-eurorack": "MIT (STM32 modules) / GPL-3.0 (AVR)", "mutable-shruthi": "GPL-3.0",
    "mutable-stmlib": "MIT", "mverb": "GPL-3.0", "nuked-opl3": "LGPL-2.1", "nuked-opm": "LGPL-2.1", "nuked-opn2": "LGPL-2.1",
    "obxd": "GPL-3.0", "q": "MIT", "resid": "GPL-2.0", "sam": "none (abandonware)", "signalsmith-dsp": "MIT",
    "soundpipe": "MIT", "stk": "STK (MIT-like)", "surge": "GPL-3.0", "surge-sst-basic-blocks": "GPL-3.0",
    "surge-sst-effects": "GPL-3.0", "surge-sst-filters": "GPL-3.0", "tal-noisemaker": "GPL-2.0", "teensy-audio": "MIT",
    "vcv-fundamental": "GPL-3.0", "vital": "GPL-3.0", "ymfm": "BSD-3-Clause", "zynaddsubfx": "GPL-2.0",
}
COPYLEFT = ("GPL", "LGPL")
KINDS = {"FM", "wavetable", "virtual analog", "samples", "granular", "physical modelling", "additive", "formant / speech",
         "chip emulation", "drum synthesis", "other"}
LEVELS = {"high", "medium", "low"}


def licence_clash(repo_licence, refs):
    """the reference projects whose copyleft code a repository under another licence holds"""
    mine = (repo_licence or "").upper()
    out = []
    for r in refs:
        theirs = LICENCE_OF.get(r.split("/")[0] if r.startswith("distrho/") else r, "")
        if r.startswith("distrho/"):
            theirs = "GPL (DISTRHO port)"
        if any(c in theirs for c in COPYLEFT) and not mine.startswith(("GPL", "AGPL")):
            out.append((r, theirs))
    return out


def brief(k, r, s):
    """the report in a page: what a reviewer starts from"""
    gh = r.get("github") or {}
    lin = r["lineage"]
    out = [f"{r['repo']}  (key {k})", f"  scanned commit {r.get('commit')} of {r.get('commit_date')}, created {r.get('created')}",
           f"  GitHub: {gh.get('description') or ''!s}  licence {gh.get('license')}  languages {gh.get('languages')}"]
    for e in r.get("listed") or []:
        out.append(f"  listed ({e.get('list')}): {e.get('name')}  base {e.get('base')}  tags {e.get('tags')}  licence {e.get('license')}")
    out.append(f"  fork of {lin.get('fork_parent')} (source {lin.get('fork_source')})" if lin.get("fork_parent") else "  not a GitHub fork")
    subs = r.get("submodules") or []
    if subs:
        out.append("  submodules: " + ", ".join(f"{x.get('path')} = {x.get('url')}" for x in subs))
    out.append(f"  nearest bases by code: {lin.get('nearest_bases')}")
    for o in lin.get("code_in_bases", [])[:5]:
        out.append(f"    {o['base']}: {o['share']:.0%} of its code is the base's, {o['distinctive']:.0%} of the base's distinctive code")
    out.append(f"  platform: {r['platform']}")
    if r["matches"]:
        out.append("  reference code it holds (files; own files):")
        for ref, m in sorted(r["matches"].items(), key=lambda x: -x[1]["files"]):
            out.append(f"    {ref} ({LICENCE_OF.get(ref, '?')}): {m['files']} files, {m['own_files']} own")
            for e in m["examples"][:4]:
                out.append(f"      {e['file']} [{e['where']}] ~ {e['ref_file']} ({e['share']:.0%})")
    if r["signatures"]:
        out.append("  names its files mention:")
        for n, v in r["signatures"].items():
            own = [x for x in v if x["where"] == "own"]
            x = (own or v)[0]
            out.append(f"    {n}: {len(own)} own / {len(v)} places, e.g. {x['file']}:{x['line']}  …{x['text'][:120]}…")
    if r["readme_origin_lines"]:
        out.append("  README lines on origins:")
        out += [f"    {x['file']}: {x['text'][:240]}" for x in r["readme_origin_lines"][:12]]
    if r["credits"]:
        out.append("  licence and credit files: " + ", ".join(x["file"] for x in r["credits"][:12]))
    out.append(f"  synthesis words: {dict(list(r['synthesis'].items())[:10])}")
    out.append(f"  assets: {r['assets']}")
    ai = r["ai"]
    out.append(f"  AI: files {ai['files']}; {len(ai['mentions'])} mentions" + ("" if ai.get("own") else " (none in its own files)"))
    out += [f"    {x['file']} [{x['where']}]: …{x['text'][:160]}…" for x in ai["mentions"][:4]]
    clash = licence_clash(gh.get("license"), s.get("own_refs", {}))
    if clash:
        out.append(f"  licence check: its licence is {gh.get('license')}, it holds copyleft code from " +
                   ", ".join(f"{a} ({b})" for a, b in clash))
    return "\n".join(out) + "\n"


def queue(work, batch):
    auto = work / "auto"
    summary = json.loads((auto / "summary.json").read_text())
    rv = work / "review"
    (rv / "briefs").mkdir(parents=True, exist_ok=True)
    (rv / "batches").mkdir(exist_ok=True)
    (rv / "done").mkdir(exist_ok=True)
    q = {}
    for k, s in sorted(summary.items()):
        r = json.loads((auto / f"{k}.json").read_text())
        why = []
        listed = [b.lower() for b in s["listed_base"]]
        if not listed:
            why.append("no base listed")
        elif listed == ["original"]:
            why.append("listed as original")
        near = [b.split("/")[-1].lower() for b in s.get("nearest_bases") or []]
        if listed and near and not any(any(l in n or n in l for n in near) for l in listed):
            why.append(f"listed base {s['listed_base']} but code says {s['nearest_bases']}")
        if s.get("own_refs"):
            why.append("holds reference code: " + ", ".join(s["own_refs"]))
        if licence_clash((r.get("github") or {}).get("license"), s.get("own_refs", {})):
            why.append("licence check")
        if why:
            q[k] = why
        (rv / "briefs" / f"{k}.txt").write_text(brief(k, r, s))
    (rv / "queue.json").write_text(json.dumps(q, indent=1))
    keys = sorted(q, key=lambda k: -summary[k]["lines"])
    for old in (rv / "batches").glob("*.txt"):
        old.unlink()
    # big ones spread over the batches so each takes about as long
    n = max(1, (len(keys) + batch - 1) // batch)
    for i in range(n):
        (rv / "batches" / f"{i + 1:02}.txt").write_text("\n".join(keys[i::n]) + "\n")
    print(f"{len(q)} of {len(summary)} queued, in {n} batches -> {rv}")
    reasons = {}
    for why in q.values():
        for w in why:
            reasons[w.split(":")[0].split(" [")[0]] = reasons.get(w.split(":")[0].split(" [")[0], 0) + 1
    for w, c in sorted(reasons.items(), key=lambda x: -x[1]):
        print(f"  {c:4}  {w}")


def check(work, batch=None):
    rv = work / "review"
    q = json.loads((rv / "queue.json").read_text())
    if batch:
        q = (rv / "batches" / f"{int(batch):02}.txt").read_text().split()
    bad = 0
    for k in sorted(q):
        p = rv / "done" / f"{k}.json"
        if not p.exists():
            print(f"missing  {k}")
            bad += 1
            continue
        try:
            v = json.loads(p.read_text())
        except ValueError as e:
            print(f"bad JSON {k}: {e}")
            bad += 1
            continue
        errs = []
        for f in ("repo", "summary", "original", "base", "hardware", "engines", "origins", "techniques", "assets", "findings"):
            if f not in v:
                errs.append(f"no {f}")
        for e in v.get("engines") or []:
            if e.get("kind") not in KINDS:
                errs.append(f"engine kind {e.get('kind')!r}")
        for e in (v.get("origins") or []) + (v.get("findings") or []) + ([v["base"]] if v.get("base") else []):
            if e.get("confidence") not in LEVELS:
                errs.append(f"confidence {e.get('confidence')!r}")
        if errs:
            print(f"malformed {k}: {'; '.join(errs[:5])}")
            bad += 1
    print(f"{len(q) - bad} of {len(q)} reviews good")
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["queue", "check"])
    ap.add_argument("--work", default=str(Path.home() / "FirmwareFacts"))
    ap.add_argument("--batch", type=int, help="queue: repositories a batch (15); check: only this batch's")
    a = ap.parse_args()
    work = Path(a.work)
    if a.what == "queue":
        queue(work, a.batch or 15)
    else:
        sys.exit(1 if check(work, a.batch) else 0)


if __name__ == "__main__":
    main()
