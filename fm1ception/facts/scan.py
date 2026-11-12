#!/usr/bin/env python3
"""The automatic scan: for each harvested repository, what its code and files say of where it comes from.

  scan.py [--work DIR] [--jobs N] [--only REPO...]   -> DIR/auto/<key>.json, DIR/auto/summary.json, DIR/auto/bases.json

Each report has:
  lineage    the GitHub fork's parent and source, the list's base, and per known base the share of the repository's
             code (its fingerprints) found in it and the share of the base's distinctive code (what no unrelated base
             has) found in the repository, the most specific base first
  matches    reference projects (refs.py) whose code it holds: per project the files, the reference file each matches,
             the share of the file that does (distinct fingerprints in common / the file's), and where the file sits:
             the repository's own code, a submodule, or a bundled third-party folder. The references' own bundled
             libraries (JUCE, Lua, dr_wav, catch, ...) are left out, so a match is the project's code
  signatures names, authors and techniques its sources and documents mention (SIGNATURES), with a few places each
  credits    its licence, credit and notice files (names, the first part of each), and the README's lines that say
             where it comes from
  synthesis  how often each kind of synthesis, filter and effect is named in its sources (KINDS)
  assets     embedded samples, wavetables and fonts (counts, folders)
  platform   its hardware layer (fm1-base, felucca-bsp, M-VAVE's fm1_open, the JieLi SDK, its own), the languages'
             lines, whether it uses the second core, MIDI's parts it implements
  ai         traces of AI tools: their files, and what its documents say
These are findings for a person to review, each with where it was found, not conclusions.
"""
import argparse
import collections
import json
import multiprocessing as mp
import os
import pickle
import re
from pathlib import Path

# the bases: the repositories others are built on (mutant.cloud's bases, the forks' sources, the submodules most used)
BASES = ["hugelton/Felucca", "hugelton/Felucca-Engines", "hugelton/felucca-bsp", "charlesvestal/fm1-base", "zvenson/dinghy",
         "isod89/sloop-fm1", "keremimo/melodee", "charlesvestal/fm1-x0x", "Quixotic7/ChoralRootFM1", "illuminus5/skiff",
         "math0ne/fm1-chord", "charlesvestal/fm1-amb", "FicusFicusov/CoralFlower", "cartesive/fumi-1", "joakimeriksson/fm1-emu",
         "joakimeriksson/fm1-sid", "m-vave/fm1_open"]

# (project, regex over sources and documents); case-sensitive unless (?i)
SIGNATURES = [
    ("Mutable Instruments", r"Mutable Instruments|pichenettes|Emilie Gillet|Olivier Gillet|\bstmlib\b|namespace (?:plaits|braids|rings|clouds|elements|warps|tides|marbles|stages|streams|peaks|yarns|frames)\b"),
    ("Mutable Plaits engines", r"\b(?:VirtualAnalogEngine|WaveshapingEngine|FMEngine|GrainEngine|AdditiveEngine|WavetableEngine|ChordEngine|SpeechEngine|SwarmEngine|ParticleEngine|StringEngine|ModalEngine|BassDrumEngine|SnareDrumEngine|HiHatEngine)\b"),
    ("Mutable Braids", r"(?i)\bbraids\b|MacroOscillator|DigitalOscillator"),
    ("Mutable Rings/Elements", r"\b(?:rings|elements)::|(?i:\bmutable rings\b)"),
    ("Mutable Clouds", r"\bclouds::|GranularProcessor"),
    ("STK", r"\bnamespace stk\b|stk::|Synthesis ToolKit|Perry R\.? Cook|Gary P\.? Scavone"),
    ("Surge", r"Surge Synth Team|Vember Audio|\bsst::|(?i:\bsurge(?:xt| xt)?\b)"),
    ("Vital / Helm", r"\bvital::|Matt Tytel|mtytel|\bmopo::"),
    ("DaisySP", r"(?i)daisysp|Electrosmith"),
    ("msfa / Dexed", r"(?i)\bmsfa\b|music-synthesizer-for-android|\bdexed\b|Raph Levien|\bFmCore\b|\bDx7Note\b"),
    ("Erica Synths", r"(?i)erica synths|ericasynths|\bperkons\b|pico voice|sample drum"),
    ("Teensy Audio", r"Paul Stoffregen|PJRC|\bAudioSynth\w+|\bAudioEffect\w+"),
    ("Soundpipe", r"(?i)soundpipe|\bsp_data\b|Paul Batchelor"),
    ("ymfm", r"\bymfm\b|Aaron Giles"),
    ("Nuked", r"(?i)\bnuked-?op[lmn]|nukeykt|Alexey Khokholov"),
    ("reSID", r"\breSID\b|Dag Lem"),
    ("snes_spc / Game_Music_Emu", r"(?i)snes_spc|game_music_emu|\bblargg\b|Shay Green"),
    ("blip_buf", r"(?i)blip_buf"),
    ("Freeverb", r"(?i)freeverb|\bJezar\b"),
    ("Dattorro reverb", r"(?i)dattorro"),
    ("Griesinger reverb", r"(?i)griesinger"),
    ("KISS FFT", r"(?i)kiss_?fft"),
    ("CMSIS-DSP", r"\barm_math\.h\b|CMSIS-DSP|\barm_(?:biquad|fir|rfft|cfft)_\w+"),
    ("SAM speech", r"Software Automatic Mouth|\bSAM\b.*(?i:speech)|s-macke"),
    ("eSpeak", r"(?i)\bespeak"),
    ("Faust", r"(?i)generated with faust|\bfaust\b"),
    ("Airwindows", r"(?i)airwindows|Chris Johnson"),
    ("JUCE", r"\bjuce::|JUCE_"),
    ("VCV Rack", r"(?i)\bvcv\b|VCVRack|rack::"),
    ("Cytomic / Simper SVF", r"(?i)cytomic|andrew simper|\bsimper\b"),
    ("Zavalishin TPT", r"(?i)zavalishin|topology.preserving|\bTPT\b"),
    ("Huovilainen ladder", r"(?i)huovilainen"),
    ("Stilson ladder", r"(?i)stilson"),
    ("Audio EQ Cookbook (RBJ)", r"(?i)bristow.johnson|audio eq cookbook|\bRBJ\b"),
    ("Chamberlin SVF", r"(?i)chamberlin"),
    ("musicdsp.org", r"(?i)musicdsp"),
    ("Will Pirkle", r"(?i)pirkle"),
    ("Julius O. Smith", r"(?i)julius o\.? smith|ccrma"),
    ("PolyBLEP / minBLEP", r"(?i)poly_?blep|min_?blep|blamp"),
    ("Karplus-Strong", r"(?i)karplus"),
    ("Klatt formant", r"(?i)\bklatt\b"),
    ("Mozzi", r"(?i)\bmozzi\b"),
    ("Maximilian", r"(?i)maximilian|maxiOsc"),
    ("libpd / Pure Data", r"(?i)libpd|pure data"),
    ("Doom", r"(?i)doomgeneric|\bid software\b"),
    ("LVGL", r"\blvgl\b|\blv_obj\b"),
    ("AKWF wavetables", r"(?i)\bakwf\b|adventure kid"),
    ("M-VAVE stock firmware", r"(?i)m-?vave|fm1_open|\bjieli\b|\bjl_"),
]
SIG_RE = [(n, re.compile(p)) for n, p in SIGNATURES]

KINDS = {
    "FM / phase modulation": r"(?i)\boperator|\bmodulator\b|\bcarrier\b|\bdx7\b|\bphase.?mod|\bfm[46]?\b",
    "wavetable": r"(?i)wavetable|wt_?pos",
    "virtual analog": r"(?i)\bsaw(?:tooth)?\b.*\bsquare\b|\bvco\b|\bpulse.?width",
    "samples": r"(?i)\bsampler?\b|\.wav\b|\badpcm\b|\bpcm\b",
    "granular": r"(?i)\bgrain|granular",
    "physical modelling": r"(?i)karplus|waveguide|\bstring\b.*\bpluck|\bmodal\b|resonator|\bexciter\b",
    "additive": r"(?i)additive|\bpartials?\b",
    "formant / speech": r"(?i)formant|vowel|\bspeech\b|\bphoneme",
    "chip emulation": r"(?i)\bsid\b|\bnes\b|\bapu\b|\bopl[23]?\b|ym2612|\bay-?3|game ?boy|\bpokey\b|\bspc700\b",
    "drum synthesis": r"(?i)\bkick\b|\bsnare\b|\bhi.?hat|\b808\b|\b909\b",
    "ladder filter": r"(?i)\bladder\b|\bmoog\b",
    "state-variable filter": r"(?i)\bsvf\b|state.?variable",
    "biquad filter": r"(?i)biquad",
    "comb filter": r"(?i)\bcomb\b",
    "reverb": r"(?i)reverb",
    "delay": r"(?i)\bdelay\b",
    "chorus / flanger / phaser": r"(?i)chorus|flanger|phaser",
    "distortion / waveshaping": r"(?i)distort|waveshap|overdrive|saturat|bitcrush|wavefold",
    "compressor": r"(?i)compressor|\bott\b|limiter",
    "arpeggiator": r"(?i)arpegg",
    "sequencer": r"(?i)sequencer|\bstep.?seq",
}
KINDS_RE = {k: re.compile(v) for k, v in KINDS.items()}

SRC = {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".inl", ".rs", ".s", ".S"}
DOC = {".md", ".txt", ".rst", ""}
AI_FILES = ["CLAUDE.md", "AGENTS.md", "GEMINI.md", ".claude", ".cursor", ".cursorrules", ".windsurfrules",
            ".github/copilot-instructions.md", "codex.md", ".aider.conf.yml", ".clinerules", "CONVENTIONS.md"]
AI_TEXT = re.compile(r"(?i)\b(?:claude(?: code)?|chatgpt|gpt-?[345]|openai codex|codex|copilot|cursor ai|gemini|ai coding agents?|"
                     r"llm|vibe.?cod\w*|generated with|written with the help of ai|ai[- ]assisted|ai[- ]generated)\b")
ORIGIN_TEXT = re.compile(r"(?i)\b(?:based on|fork(?:ed)? (?:of|from)|derived from|port(?:ed)? (?:of|from)|inspired by|adapted from|"
                         r"borrows?|credits?|thanks to|uses? (?:the )?\w+ (?:engine|library|code)|built on)\b")
SDK_HINT = re.compile(r"(?i)\bwl82\b|\bac79\b|include_lib|jl_sdk|\bjieli\b")
VENDORED_REF = re.compile(r"(?i)(?:^|/)(?:third_?party|3rdparty|vendor|external|extern|deps|libs|juce|juced|catch2?|tests?|doc)/|"
                          r"(?:^|/)(?:RtAudio|RtMidi|dsound|dr_(?:wav|mp3|flac)|stb_\w+|catch|ff|ffconf|diskio|\w*BinaryData)\.\w+$")
BUNDLED = re.compile(r"(?i)(?:^|/)(?:third_?party|3rdparty|vendor(?:ed)?|external|extern|deps|contrib|attic)/")
SAMPLE_EXT = {".wav", ".aif", ".aiff", ".raw", ".sf2", ".pcm", ".flac", ".mp3", ".ogg"}
TABLE_EXT = {".wt", ".syx"}


def walk(root):
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules")]
        for f in files:
            yield os.path.join(dirpath, f)


def text(p, limit=400_000):
    try:
        with open(p, "rb") as f:
            return f.read(limit).decode("utf-8", "replace")
    except OSError:
        return ""


def load_fp(work):
    with open(work / "fp" / "refs.pkl", "rb") as f:
        refs = pickle.load(f)
    with open(work / "fp" / "repos.pkl", "rb") as f:
        repos = pickle.load(f)
    return refs, repos


def ref_owner(owner, path):
    """the project a reference file is from: DISTRHO's ports are each their plugin's"""
    if owner == "tal-noisemaker":
        m = re.match(r"ports-juce[\w.]*/([^/]+)/", path)
        if m:
            plug = m.group(1)
            return plug if plug in ("dexed", "obxd", "tal-noisemaker") else "distrho/" + plug
    return owner


def ref_index(refs):
    """fingerprint -> the reference files holding it, kept only for fingerprints at most 3 projects share; and each
    file's project. The references' bundled libraries are left out."""
    files = refs["files"]
    owner = [ref_owner(o, p) for o, p, _ in files]
    by_sha = collections.defaultdict(dict)
    for i, (_, path, sha) in enumerate(files):
        if not VENDORED_REF.search(path):
            by_sha[sha].setdefault(owner[i], i)
    by_sha = {sha: list(per.values()) for sha, per in by_sha.items()}
    idx = {}
    for sha, ids in by_sha.items():
        for h in set(refs["fps"].get(sha, ())):
            lst = idx.setdefault(h, [])
            for i in ids:
                if len(lst) < 12:
                    lst.append(i)
    for h in list(idx):
        projects = {owner[i] for i in idx[h]}
        if len(projects) > 3 or len(idx[h]) >= 12:
            del idx[h]
    return idx, owner


_JOB = None


def _run(k):
    return _JOB(k)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default=str(Path.home() / "FirmwareFacts"))
    ap.add_argument("--jobs", type=int, default=max(1, mp.cpu_count() - 4))
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    work = Path(a.work)
    out = work / "auto"
    out.mkdir(exist_ok=True)
    refs, repos = load_fp(work)
    print("indexing the references", flush=True)
    idx, rowner = ref_index(refs)
    rfiles = refs["files"]

    # the distinct firmware files' matches: {sha: [(ref file, shared, share of the file)]}
    print("matching the firmware files", flush=True)
    fps = repos["fps"]
    matches = {}
    for sha, hs in fps.items():
        hs = set(hs)
        if len(hs) < 12:
            continue
        cnt = collections.Counter()
        for h in hs:
            for i in idx.get(h, ()):
                cnt[i] += 1
        best = [(i, n, n / len(hs)) for i, n in cnt.most_common(3) if n >= 10 and n / len(hs) >= 0.15]
        if best:
            matches[sha] = best

    # each repository's files, and its fingerprints
    by_repo = collections.defaultdict(list)
    for owner, path, sha in repos["files"]:
        by_repo[owner].append((path, sha))
    meta = {p.stem: json.loads(p.read_text()) for p in (work / "meta").glob("*.json")}
    key_of = {m.get("repo", "").lower(): k for k, m in meta.items()}
    for k, m in meta.items():
        if m.get("listed_as"):
            key_of.setdefault(m["listed_as"].lower(), k)

    print("the bases' fingerprints", flush=True)
    base_fp = {}
    for b in BASES:
        k = key_of.get(b.lower())
        if k:
            s = set()
            for _, sha in by_repo.get(k, ()):
                s.update(fps.get(sha, ()))
            base_fp[b] = (k, s)
    # holds[x, y]: the share of base y's code in base x. A base's distinctive code is what the bases not built on it lack.
    holds = {(x, y): len(sx & sy) / len(sy) for x, (_, sx) in base_fp.items() for y, (_, sy) in base_fp.items() if x != y and sy}
    uniq = {}
    for b, (_, s) in base_fp.items():
        others = set()
        for x, (_, sx) in base_fp.items():
            if x != b and holds.get((x, b), 0) < 0.5:
                others |= sx
        uniq[b] = s - others
    (out / "bases.json").write_text(json.dumps(
        {b: {"key": bk, "fingerprints": len(s), "distinctive": len(uniq[b]),
             "holds": {y: round(holds[b, y], 2) for y in base_fp if y != b and holds.get((b, y), 0) >= 0.3}}
         for b, (bk, s) in base_fp.items()}, indent=1))
    listed = json.loads((work / "repos.json").read_text())
    listed_of = {r.lower(): v for r, v in listed.items()}

    keys = sorted(meta) if not a.only else [key_of.get(o.lower(), o) for o in a.only]
    keys.sort(key=lambda k: -len(by_repo.get(k, ())))

    def scan_one(k):
        m = meta.get(k, {})
        root = work / "repos" / k
        if not root.exists():
            return None
        files = by_repo.get(k, [])
        own = set()
        for _, sha in files:
            own.update(fps.get(sha, ()))
        subs = sorted((s["path"] for s in m.get("submodules") or [] if s.get("path")), key=len, reverse=True)

        def where(rel):
            for sp in subs:
                if rel == sp or rel.startswith(sp + "/"):
                    return "submodule " + sp
            return "bundled" if BUNDLED.search(rel) else "own"

        # lineage
        overlap = []
        for b, (bk, s) in base_fp.items():
            if bk == k or not own:
                continue
            share = len(own & s) / len(own)
            u = uniq[b]
            dist = len(own & u) / len(u) if u else 0.0
            if share >= 0.05 or dist >= 0.05:
                overlap.append({"base": b, "share": round(share, 3), "distinctive": round(dist, 3)})
        overlap.sort(key=lambda x: (-x["distinctive"], -x["share"]))
        held = [o["base"] for o in overlap if o["distinctive"] >= 0.3]
        nearest = [b for b in held if not any(holds.get((c, b), 0) >= 0.5 for c in held if c != b)]
        entries = listed_of.get((m.get("listed_as") or m.get("repo") or "").lower(), [])
        lineage = {"fork_parent": m.get("parent"), "fork_source": m.get("source"),
                   "listed_base": sorted({e.get("base") for e in entries if e.get("base")}),
                   "nearest_bases": nearest, "code_in_bases": overlap[:8]}

        # the reference projects' code it holds
        per_ref = collections.defaultdict(list)
        for path, sha in files:
            for i, shared, share in matches.get(sha, ()):
                per_ref[rowner[i]].append({"file": path, "where": where(path), "ref_file": rfiles[i][1],
                                           "shared": shared, "share": round(share, 2)})
        ref_out = {}
        for r, v in per_ref.items():
            ref_out[r] = {"files": len({e["file"] for e in v}), "own_files": len({e["file"] for e in v if e["where"] == "own"}),
                          "examples": sorted(v, key=lambda x: (x["where"] != "own", -x["shared"]))[:8]}

        # signatures, credits, kinds, assets, platform, AI
        sig = collections.defaultdict(list)
        sig_n = collections.Counter()
        ai_n = collections.Counter()
        kinds = collections.Counter()
        langs = collections.Counter()
        assets = collections.Counter()
        asset_dirs = collections.Counter()
        credits, readme_lines, ai_text = [], [], []
        ai_files = [f for f in AI_FILES if (root / f).exists()]
        core2 = midi = None
        midi_parts = set()
        sdk = False
        for p in walk(root):
            rel = os.path.relpath(p, root)
            ext = os.path.splitext(p)[1]
            low = rel.lower()
            name = os.path.basename(low)
            if ext.lower() in SAMPLE_EXT:
                assets["samples"] += 1
                asset_dirs[os.path.dirname(rel)] += 1
                continue
            if ext.lower() in TABLE_EXT or "wavetable" in low and ext.lower() in {".bin", ".wav"}:
                assets["wavetables"] += 1
            if ext.lower() in {".ttf", ".otf", ".bdf"}:
                assets["fonts"] += 1
            is_src = ext in SRC
            is_doc = ext.lower() in DOC and os.path.getsize(p) < 300_000 if os.path.exists(p) else False
            if not (is_src or is_doc):
                continue
            t = text(p)
            w = where(rel)
            if is_src:
                langs[ext.lower().lstrip(".")] += t.count("\n")
                for kn, kr in KINDS_RE.items():
                    c = len(kr.findall(t))
                    if c:
                        kinds[kn] += c
                if SDK_HINT.search(t) or SDK_HINT.search(rel):
                    sdk = True
                if re.search(r"(?i)core_?1|cpu_?1|second core|core 2\b|multicore|dual.?core", t):
                    core2 = core2 or rel
                for part, rx in (("NRPN", r"(?i)\bnrpn"), ("SysEx", r"(?i)sysex|0xF0\b"), ("clock", r"(?i)midi.?clock|0xF8\b"),
                                 ("program change", r"(?i)program.?change|0xC0\b"), ("CC", r"(?i)control.?change|\bcc\b"),
                                 ("USB audio", r"(?i)\buac\b|usb.?audio")):
                    if re.search(rx, t):
                        midi_parts.add(part)
            for sn, sr in SIG_RE:
                if sig_n[sn, w == "own"] < (4 if w == "own" else 2):
                    mm = sr.search(t)
                    if mm:
                        sig_n[sn, w == "own"] += 1
                        line = t.count("\n", 0, mm.start()) + 1
                        sig[sn].append({"file": rel, "where": w, "line": line,
                                        "text": t[max(0, mm.start() - 60):mm.end() + 60].replace("\n", " ")[:180]})
            if is_doc and (re.match(r"(?i)(licen[cs]e|copying|notice|credits|third.?party|acknowledg|authors|contributors)", name)
                           or low.startswith("licenses/")):
                credits.append({"file": rel, "head": t[:1500]})
            if is_doc and name.startswith("readme"):
                for line in t.splitlines():
                    if ORIGIN_TEXT.search(line) and len(readme_lines) < 25:
                        readme_lines.append({"file": rel, "text": line.strip()[:300]})
            if is_doc:
                for mm in AI_TEXT.finditer(t):
                    if ai_n[w == "own"] < (8 if w == "own" else 3):
                        ai_n[w == "own"] += 1
                        ai_text.append({"file": rel, "where": w,
                                        "text": t[max(0, mm.start() - 80):mm.end() + 80].replace("\n", " ")[:220]})
        ai_own = bool(ai_files) or any(x["where"] == "own" for x in ai_text)
        hw = []
        for b in ("charlesvestal/fm1-base", "hugelton/felucca-bsp", "m-vave/fm1_open"):
            if any(s.get("url") and b.lower() in s["url"].lower() for s in m.get("submodules") or []) or \
               any(o["base"] == b and o["distinctive"] >= 0.3 for o in overlap):
                hw.append(b)
        report = {
            "repo": m.get("repo"), "commit": m.get("commit"), "commit_date": m.get("commit_date"), "created": m.get("created"),
            "github": {k2: m.get(k2) for k2 in ("description", "homepage", "topics", "license", "stars", "archived", "languages", "size_kb")},
            "listed": entries,
            "submodules": m.get("submodules"),
            "lineage": lineage,
            "matches": ref_out,
            "signatures": {n: v for n, v in sig.items() if v},
            "credits": credits[:20],
            "readme_origin_lines": readme_lines,
            "synthesis": dict(kinds.most_common()),
            "assets": {**assets, "sample_folders": [d for d, _ in asset_dirs.most_common(6)]},
            "platform": {"hardware_layer": hw, "jieli_sdk": sdk, "second_core_hint": core2, "midi": sorted(midi_parts),
                         "lines": dict(langs.most_common())},
            "ai": {"files": ai_files, "mentions": ai_text, "own": ai_own},
        }
        (out / f"{k}.json").write_text(json.dumps(report, indent=1))
        return k, {"repo": report["repo"], "fork_source": lineage["fork_source"], "listed_base": lineage["listed_base"],
                   "nearest_bases": nearest, "top_base": overlap[0] if overlap else None,
                   "refs": {r: v["files"] for r, v in ref_out.items()},
                   "own_refs": {r: v["own_files"] for r, v in ref_out.items() if v["own_files"]},
                   "signatures": sorted(report["signatures"]),
                   "own_signatures": sorted(n for n, v in sig.items() if any(x["where"] == "own" for x in v)),
                   "ai": ai_own, "lines": sum(langs.values())}

    global _JOB
    _JOB = scan_one
    summary = {}
    if a.only and (out / "summary.json").exists():
        summary = json.loads((out / "summary.json").read_text())
    print(f"scanning {len(keys)} repositories, {a.jobs} at a time", flush=True)
    with mp.get_context("fork").Pool(a.jobs) as pool:
        for n, r in enumerate(pool.imap_unordered(_run, keys)):
            if r:
                summary[r[0]] = r[1]
            if (n + 1) % 50 == 0:
                print(f"  {n + 1}/{len(keys)}", flush=True)
    (out / "summary.json").write_text(json.dumps(summary, indent=1, sort_keys=True))
    print(f"{len(summary)} reports -> {out}")


if __name__ == "__main__":
    main()
