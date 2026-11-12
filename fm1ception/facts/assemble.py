#!/usr/bin/env python3
"""The database FM-1Ception embeds: each harvested repository's fixed facts, from its review where it has one
(review.py), else from what the automatic scan (scan.py) can stand behind.

  assemble.py [--work DIR] [--out FILE]   -> FILE (fm1ception/Resources/FirmwareFacts.json)

{"version": 1, "scanned": "2026-11-12", "firmwares": {"owner/name": {...}}}, the key the repository's lowercase
GitHub path. Each firmware has:
  repo, commit (12 hex), committed, created     the repository and the commit the facts are of
  reviewed                                      a person read it (summary, engines, techniques are a review's only)
  summary, original, base, hardware, engines, origins, techniques, assets, findings   as review.py says; a base
                                                without a review has how "fork", "code" or "listed" (its list says),
                                                Dinghy as a starter template "template"
  hardware_note                                 a review's "other: ..." hardware in full, hardware then its short label
  license, midi, languages                      GitHub's licence, the MIDI it handles, its source lines by language
"""
import argparse
import datetime
import json
import re
from pathlib import Path

import review

REF_NAME = {  # reference project -> (name, author)
    "airwindows": ("Airwindows", "Chris Johnson"), "audible-instruments": ("Audible Instruments (VCV)", "VCV"),
    "befaco": ("Befaco Noise Plethora", "Befaco"), "chowdsp": ("chowdsp_utils", "Jatin Chowdhury"),
    "cmsis-dsp": ("CMSIS-DSP", "Arm"), "daisysp": ("DaisySP", "Electrosmith"), "dexed": ("Dexed", "Pascal Gauthier"),
    "freeverb": ("Freeverb", "Jezar at Dreampoint"), "gme": ("Game_Music_Emu", "Shay Green (blargg)"),
    "helm": ("Helm", "Matt Tytel"), "kissfft": ("KISS FFT", "Mark Borgerding"),
    "msfa": ("msfa (Music Synthesizer for Android)", "Raph Levien / Google"),
    "mutable-ambika": ("Mutable Instruments Ambika", "Emilie Gillet"), "mutable-avril": ("avril", "Emilie Gillet"),
    "mutable-eurorack": ("Mutable Instruments", "Emilie Gillet"), "mutable-shruthi": ("Mutable Instruments Shruthi", "Emilie Gillet"),
    "mutable-stmlib": ("Mutable Instruments stmlib", "Emilie Gillet"), "mverb": ("MVerb", "Martin Eastwood"),
    "nuked-opl3": ("Nuked-OPL3", "nukeykt"), "nuked-opm": ("Nuked-OPM", "nukeykt"), "nuked-opn2": ("Nuked-OPN2", "nukeykt"),
    "obxd": ("OB-Xd", "discoDSP / 2DaT"), "q": ("Q audio library", "Joel de Guzman"), "resid": ("reSID", "Dag Lem"),
    "sam": ("SAM (Software Automatic Mouth)", "Don't Ask Software; C port by Sebastian Macke"),
    "signalsmith-dsp": ("Signalsmith DSP", "Geraint Luff"), "soundpipe": ("Soundpipe", "Paul Batchelor"),
    "stk": ("STK (Synthesis ToolKit)", "Perry Cook and Gary Scavone"), "surge": ("Surge XT", "Surge Synth Team"),
    "surge-sst-basic-blocks": ("Surge sst-basic-blocks", "Surge Synth Team"),
    "surge-sst-effects": ("Surge sst-effects", "Surge Synth Team"), "surge-sst-filters": ("Surge sst-filters", "Surge Synth Team"),
    "tal-noisemaker": ("TAL-NoiseMaker", "Patrick Kunz (TAL)"), "teensy-audio": ("Teensy Audio Library", "Paul Stoffregen (PJRC)"),
    "vcv-fundamental": ("VCV Fundamental", "VCV"), "vital": ("Vital", "Matt Tytel"), "ymfm": ("ymfm", "Aaron Giles"),
    "zynaddsubfx": ("ZynAddSubFX", "Nasca Octavian Paul"),
}
MI_MODULES = {"plaits", "braids", "rings", "clouds", "elements", "warps", "tides", "marbles", "stages", "streams", "peaks",
              "yarns", "frames", "grids", "edges", "branches", "shades", "links", "kinks", "ripples", "blinds", "veils"}
LANG = {"c": "C", "h": "C", "cc": "C++", "cpp": "C++", "cxx": "C++", "hpp": "C++", "hh": "C++", "rs": "Rust", "s": "assembly"}
AI_NAMES = re.compile(r"(?i)claude|chatgpt|gpt-?\d|codex|copilot|cursor|gemini|aider|cline|windsurf")
# FM-1 platforms and toolchains an origin may name, beside the lists' firmwares
FM1_PLATFORMS = {"fm1-base", "felucca-bsp", "felucca-engines", "foma", "fm1_open", "fm1 open", "m-vave fm1 open", "fm1-dock",
                 "jieli ac79", "jieli", "m-vave", "pendel-bsp"}
# outside projects whose names a firmware might share: never FM-1 lineage
NOT_FM1 = {"msfa", "daisysp", "open303", "plaits", "rings", "braids", "clouds", "elements", "grids", "stmlib", "resid", "ymfm",
           "snes_spc", "setbfree", "mame", "dexed", "sea codec"}


def origin_name(project):
    """an origin's project as one name: "Felucca (via SLOOP)" -> "felucca", "Mutable Instruments Plaits" -> "plaits" """
    s = project.split(" (")[0].split(" via ")[0].split(",")[0].strip().lower()
    s = re.sub(r"^mutable instruments\s+", "", s)
    s = re.sub(r"\s+(platform|firmware|engines?|fm-1|v\d[\w.]*|\d[\w.]*)$", "", s)
    return s


def short_date(s):
    return (s or "")[:10]


def hardware_label(text):
    """a review's hardware, as a short label and the rest as a note: ("Felucca's platform, in its tree", "via SLOOP ...")"""
    t = (text or "").strip()
    if not t.lower().startswith("other:"):
        return t, ""
    note = t[6:].strip()
    low = note.lower()
    if low.startswith(("none", "not a firmware", "unknown")) or "emulat" in low[:60]:
        label = "none" if not low.startswith("unknown") else ""
    elif "foma" in low:
        label = "foma (Felucca's platform)"
    elif "fm1-dock" in low:
        label = "fm1-dock"
    elif "pendel-bsp" in low:
        label = "pendel-bsp (from felucca-bsp)"
    elif "stock firmware" in low:
        label = "M-VAVE's stock firmware, patched"
    elif "jieli" in low:
        label = "JieLi's AC79 SDK"
    elif "esp32" in low:
        label = "ESP32 (drives the FM-1 over USB)"
    elif "remotefm1" in low:
        label = "RemoteFM1 hosts"
    elif any(w in low for w in ("felucca", "dinghy", "x0x", "sloop")):
        label = "Felucca's platform, in its tree"
    else:
        label = note.split(" (")[0].split(",")[0]
    return label, note


def ref_origin(ref, m, licence_of):
    """a reference project's code the scan found in a repository's own files, as an origin"""
    name, author = REF_NAME.get(ref, (ref, ""))
    ex = m["examples"]
    lic = licence_of(ref)
    if ref.startswith("distrho/"):
        name, author, lic = ref.split("/", 1)[1] + " (DISTRHO Ports)", "", "GPL (DISTRHO port)"
    if ref == "dexed" and ex and all("/msfa/" in e["ref_file"] for e in ex):
        name, author, lic = "msfa (via Dexed)", "Raph Levien / Google", "Apache-2.0"
    if ref == "mutable-eurorack":
        mods = sorted({e["ref_file"].split("/")[0] for e in ex if e["ref_file"].split("/")[0] in MI_MODULES})
        if mods:
            name = "Mutable Instruments " + ", ".join(m.capitalize() for m in mods)
    best = max((e["share"] for e in ex), default=0)
    own = [e for e in ex if e["where"] == "own"] or ex
    evidence = "; ".join(f"{e['file']} ~ {ref}:{e['ref_file']} ({min(1.0, e['share']):.0%})" for e in own[:3])
    return {"project": name, "author": author, "license": lic, "what": f"{m['files']} source file{'s' if m['files'] != 1 else ''}",
            "how": "code", "evidence": evidence, "confidence": "high" if best >= 0.8 else "medium" if best >= 0.4 else "low"}


def languages(lines):
    out = {}
    for ext, n in lines.items():
        lang = LANG.get(ext)
        if lang:
            out[lang] = out.get(lang, 0) + n
    return dict(sorted(out.items(), key=lambda x: -x[1]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default=str(Path.home() / "FirmwareFacts"))
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "Resources" / "FirmwareFacts.json"))
    a = ap.parse_args()
    work = Path(a.work)
    auto = work / "auto"
    summary = json.loads((auto / "summary.json").read_text())
    listed = json.loads((work / "repos.json").read_text())
    done = work / "review" / "done"

    # the lists' ids -> (repo, name): a listed base by its id
    by_id = {}
    for repo, entries in listed.items():
        for e in entries:
            if e.get("id"):
                by_id.setdefault(e["id"].lower(), (repo, e.get("name") or e["id"]))
    fm1_names = set(FM1_PLATFORMS)
    for repo, entries in listed.items():
        fm1_names.add(repo.split("/")[-1].lower())
        for e in entries:
            if e.get("name"):
                fm1_names.add(origin_name(e["name"]))
    fm1_names -= NOT_FM1
    reports = {k: json.loads((auto / f"{k}.json").read_text()) for k in summary}
    reviews = {p.stem: json.loads(p.read_text()) for p in done.glob("*.json")}
    key_of_repo = {(r.get("repo") or "").lower(): k for k, r in reports.items()}

    def licence_of(ref):
        return review.LICENCE_OF.get(ref, "")

    out, kept = {}, {}
    for k, s in sorted(summary.items()):
        r = reports[k]
        repo = r.get("repo") or s.get("repo")
        if not repo:
            continue
        gh = r.get("github") or {}
        plat = r["platform"]
        f = {"repo": repo, "commit": (r.get("commit") or "")[:12], "committed": short_date(r.get("commit_date")),
             "created": short_date(r.get("created")), "reviewed": k in reviews}
        lin = r["lineage"]
        if k in reviews:
            v = reviews[k]
            for field in ("summary", "original", "base", "hardware", "engines", "origins", "techniques", "assets", "findings"):
                f[field] = v.get(field)
            # Dinghy is a starter template, and mutant.cloud lists those on it as built on it: one whose review
            # calls it the platform has it as its base, its template
            if f["base"] is None and re.match(r"(?i)other:\s*(the |a copy of the )?dinghy", f["hardware"] or ""):
                f["base"] = {"repo": "zvenson/dinghy", "name": "Dinghy", "how": "template", "confidence": "high",
                             "evidence": "it runs on Dinghy's starter template: " + f["hardware"][6:].strip()}
            f["hardware"], f["hardware_note"] = hardware_label(f["hardware"])
            # felucca-bsp is the split-out repository: a copy of Felucca's hardware layer in its own tree is that
            subs = " ".join((x.get("url") or "") for x in r.get("submodules") or []).lower()
            if f["hardware"] == "felucca-bsp" and "felucca-bsp" not in subs and "hugelton/felucca-bsp" not in plat.get("hardware_layer", []):
                f["hardware"] = "Felucca's platform, in its tree"
        else:
            # what the scan can stand behind: the base its list, its fork and its code agree on, the reference code in
            # its own files
            base = None
            nearest = lin.get("nearest_bases") or []
            for lb in lin.get("listed_base") or []:
                if lb.lower() == "original":
                    continue  # mutant.cloud's word for its own code
                brepo, bname = by_id.get(lb.lower(), ("", lb))
                how = "listed"
                if lin.get("fork_source") and brepo and lin["fork_source"].lower() == brepo.lower():
                    how = "fork"
                elif brepo and any(n.lower() == brepo.lower() for n in nearest):
                    how = "code"
                d = next((o for o in lin.get("code_in_bases", []) if brepo and o["base"].lower() == brepo.lower()), None)
                ev = [f"mutant.cloud lists its base as {bname}"]
                if how == "fork":
                    ev.append(f"a GitHub fork of {lin['fork_source']}")
                if d:
                    ev.append(f"it holds {d['distinctive']:.0%} of the base's distinctive code")
                base = {"repo": brepo, "name": bname, "how": how, "confidence": "high" if how != "listed" else "medium",
                        "evidence": "; ".join(ev)}
                break
            if base is None and lin.get("fork_source"):
                brepo = lin["fork_source"]
                bk = key_of_repo.get(brepo.lower())
                bname = (reviews.get(bk) or {}).get("repo", brepo).split("/")[-1] if bk else brepo.split("/")[-1]
                base = {"repo": brepo, "name": bname, "how": "fork", "confidence": "high", "evidence": f"a GitHub fork of {brepo}"}
            f["summary"] = ""
            f["original"] = base is None and (not nearest or [b.lower() for b in lin.get("listed_base") or []] == ["original"])
            f["base"] = base
            hw = plat.get("hardware_layer") or []
            f["hardware"] = {"charlesvestal/fm1-base": "fm1-base", "hugelton/felucca-bsp": "felucca-bsp",
                             "m-vave/fm1_open": "fm1_open"}.get(hw[0], hw[0]) if hw else ""
            f["hardware_note"] = ""
            f["engines"] = []
            f["origins"] = [ref_origin(ref, m, licence_of) for ref, m in sorted(r["matches"].items(), key=lambda x: -x[1]["files"])
                            if m["own_files"]]
            f["techniques"] = []
            f["assets"] = ""
            findings = []
            for ref, theirs in review.licence_clash(gh.get("license"), s.get("own_refs", {})):
                m = r["matches"][ref]
                best = max((e["share"] for e in m["examples"]), default=0)
                findings.append({"kind": "licence", "text": f"It is licensed {gh.get('license') or 'without a licence'} but holds "
                                 f"{REF_NAME.get(ref, (ref,))[0]}'s code, which is {theirs}.",
                                 "evidence": "; ".join(f"{e['file']} ({min(1.0, e['share']):.0%})" for e in m["examples"][:3]),
                                 "confidence": "high" if best >= 0.8 else "medium"})
            f["findings"] = findings
        # AI traces at its top level are facts whoever read it
        ai = r["ai"]
        if ai["files"] and not any(x.get("kind") == "ai" for x in f["findings"] or []):
            names = ", ".join(ai["files"])
            f["findings"] = (f["findings"] or []) + [{"kind": "ai", "text": f"AI tools' files at its top level: {names}.",
                                                      "evidence": names, "confidence": "high"}]
        elif ai.get("own") and not any(x.get("kind") == "ai" for x in f["findings"] or []):
            own = [x for x in ai["mentions"] if x["where"] == "own"]
            tools = sorted({m.group(0).capitalize() for x in own for m in [AI_NAMES.search(x["text"])] if m})
            if tools:
                f["findings"] = (f["findings"] or []) + [{"kind": "ai", "text": f"Its documents mention {', '.join(tools)}.",
                                                          "evidence": ", ".join(sorted({x['file'] for x in own})[:4]),
                                                          "confidence": "low"}]
        f["license"] = gh.get("license") or ""
        f["midi"] = plat.get("midi") or []
        f["languages"] = languages(plat.get("lines") or {})
        out[repo.lower()] = f
        if f["base"] and f["base"].get("repo"):
            d = next((o["distinctive"] for o in lin.get("code_in_bases", []) if o["base"].lower() == f["base"]["repo"].lower()), 0.0)
            kept[repo.lower()] = d

    # one not reviewed has its base's hardware layer (a base's base's, along the chain); if it keeps most of a reviewed
    # base's own code, that base's outside code too
    for _ in range(4):
        for key in kept:
            f = out[key]
            b = out.get(f["base"]["repo"].lower())
            if not f["reviewed"] and not f["hardware"] and b and b["hardware"]:
                f["hardware"], f["hardware_note"] = b["hardware"], f"as its base, {f['base']['name']}, has it"
    for key, d in kept.items():
        f = out[key]
        b = out.get(f["base"]["repo"].lower())
        if f["reviewed"] or d < 0.5 or not b or not b["reviewed"]:
            continue
        have = {o["project"] for o in f["origins"]}
        for o in b["origins"] or []:
            if o["project"] not in have:
                f["origins"].append({**o, "what": f"via {f['base']['name']}: {o['what']}",
                                     "confidence": o["confidence"] if d >= 0.8 else "medium" if o["confidence"] == "high" else "low"})

    # an origin that is another FM-1 firmware or platform is lineage (BUILT ON says it), not outside code
    def is_fm1(project):
        head = project.split(" (")[0].split(" via ")[0].split(" with ")[0]
        for part in re.split(r"\s+and\s+|\s*/\s*|,\s*", head):
            n = re.sub(r"^m-vave\s+|\s+(sdk|template)$", "", origin_name(part))
            if n in NOT_FM1:
                return False
            if n in fm1_names or (n.endswith("-1") and n[:-2] in fm1_names):
                return True
        return False

    for f in out.values():
        for o in f["origins"] or []:
            o["fm1"] = is_fm1(o.get("project") or "")

    db = {"version": 1, "scanned": datetime.date.today().isoformat(), "firmwares": out}
    path = Path(a.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    # one firmware a line, so a change shows as that firmware's line
    body = ",\n".join(f"{json.dumps(k)}:{json.dumps(v, ensure_ascii=False, separators=(',', ':'))}" for k, v in out.items())
    path.write_text(f'{{"version":1,"scanned":"{db["scanned"]}","firmwares":{{\n{body}\n}}}}\n')
    n_rev = sum(1 for v in out.values() if v["reviewed"])
    print(f"{len(out)} firmwares ({n_rev} reviewed) -> {path} ({path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
