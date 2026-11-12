#!/usr/bin/env python3
"""The open-source DSP projects FM-1 firmwares may take code from, cloned shallow, for the scan's fingerprints:
code of a firmware's that matches one of these (comments and spacing aside) is reported with the project's name and
the file it matches, whether the firmware says so or not.

  refs.py [--work DIR]      (default ~/FirmwareFacts: refs/<name>/)
"""
import argparse
import concurrent.futures as cf
import os
import subprocess
from pathlib import Path

# name: (repository, what it is, its licence as the project gives it)
REFS = {
    "mutable-eurorack": ("pichenettes/eurorack", "Mutable Instruments' modules (Plaits, Braids, Rings, Clouds, Elements, Warps, Tides, ...)", "MIT / GPL-3.0"),
    "mutable-stmlib": ("pichenettes/stmlib", "Mutable Instruments' DSP and utility library", "MIT"),
    "mutable-avril": ("pichenettes/avril", "Mutable Instruments' AVR library (Shruthi, Ambika)", "GPL-3.0"),
    "mutable-shruthi": ("pichenettes/shruthi-1", "Mutable Instruments Shruthi-1", "GPL-3.0"),
    "mutable-ambika": ("pichenettes/ambika", "Mutable Instruments Ambika", "GPL-3.0"),
    "stk": ("thestk/stk", "The Synthesis ToolKit (Cook, Scavone)", "STK (MIT-like)"),
    "surge": ("surge-synthesizer/surge", "Surge XT (Vember Audio)", "GPL-3.0"),
    "surge-sst-filters": ("surge-synthesizer/sst-filters", "Surge's filters", "GPL-3.0"),
    "surge-sst-effects": ("surge-synthesizer/sst-effects", "Surge's effects", "GPL-3.0"),
    "surge-sst-basic-blocks": ("surge-synthesizer/sst-basic-blocks", "Surge's basic DSP blocks", "MIT"),
    "vital": ("mtytel/vital", "Vital (Matt Tytel)", "GPL-3.0"),
    "helm": ("mtytel/helm", "Helm (Matt Tytel)", "GPL-3.0"),
    "daisysp": ("electro-smith/DaisySP", "Electrosmith DaisySP", "MIT"),
    "msfa": ("google/music-synthesizer-for-android", "Music Synthesizer for Android (msfa), the DX7 engine", "Apache-2.0"),
    "dexed": ("asb2m10/dexed", "Dexed, msfa's DX7 plug-in", "GPL-3.0"),
    "teensy-audio": ("PaulStoffregen/Audio", "Teensy Audio Library", "MIT"),
    "soundpipe": ("PaulBatchelor/Soundpipe", "Soundpipe", "MIT"),
    "ymfm": ("aaronsgiles/ymfm", "ymfm, Yamaha FM chip emulation", "BSD-3-Clause"),
    "nuked-opn2": ("nukeykt/Nuked-OPN2", "Nuked-OPN2 (YM2612)", "LGPL-2.1"),
    "nuked-opl3": ("nukeykt/Nuked-OPL3", "Nuked-OPL3", "LGPL-2.1"),
    "nuked-opm": ("nukeykt/Nuked-OPM", "Nuked-OPM (YM2151)", "LGPL-2.1"),
    "resid": ("libsidplayfp/resid", "reSID, the C64 SID emulation", "GPL-2.0"),
    "airwindows": ("airwindows/airwindows", "Airwindows plug-ins", "MIT"),
    "freeverb": ("sinshu/freeverb", "Freeverb (Jezar)", "Public domain"),
    "kissfft": ("mborgerding/kissfft", "KISS FFT", "BSD-3-Clause"),
    "sam": ("s-macke/SAM", "SAM, Software Automatic Mouth", "abandonware"),
    "vcv-fundamental": ("VCVRack/Fundamental", "VCV Rack Fundamental modules", "GPL-3.0"),
    "befaco": ("VCVRack/Befaco", "Befaco modules for VCV Rack", "GPL-3.0"),
    "audible-instruments": ("VCVRack/AudibleInstruments", "VCV's ports of Mutable Instruments' modules", "GPL-3.0"),
    "gme": ("libgme/game-music-emu", "Game_Music_Emu (NES, Game Boy, ... sound chips)", "LGPL-2.1"),
    "blip-buf": ("Kanickel/blip_buf", "blip_buf band-limited synthesis", "LGPL-2.1"),
    "cmsis-dsp": ("ARM-software/CMSIS-DSP", "ARM CMSIS-DSP", "Apache-2.0"),
    "q": ("cycfi/q", "Q audio DSP library (Cycfi)", "MIT"),
    "chowdsp": ("Chowdhury-DSP/chowdsp_utils", "chowdsp_utils", "BSD-3-Clause / GPL-3.0"),
    "signalsmith-dsp": ("Signalsmith-Audio/dsp", "Signalsmith Audio DSP library", "MIT"),
    "mverb": ("martineastwood/mverb", "MVerb (Dattorro plate)", "GPL-3.0"),
    "zynaddsubfx": ("zynaddsubfx/zynaddsubfx", "ZynAddSubFX", "GPL-2.0"),
    "obxd": ("reales/OB-Xd", "OB-Xd", "GPL-3.0"),
    "tal-noisemaker": ("DISTRHO/DISTRHO-Ports", "DISTRHO's ports (TAL-NoiseMaker, ...)", "GPL"),
    "mi-plaits-pico": ("pichenettes/eurorack", "", ""),   # (eurorack again under the name some ports use; skipped)
}
REFS.pop("mi-plaits-pico")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default=str(Path.home() / "FirmwareFacts"))
    a = ap.parse_args()
    root = Path(a.work) / "refs"
    root.mkdir(parents=True, exist_ok=True)

    def one(item):
        name, (repo, _, _) = item
        d = root / name
        if (d / ".git").exists():
            return name, "kept"
        r = subprocess.run(["git", "clone", "--quiet", "--depth", "1", "--no-tags", f"https://github.com/{repo}.git", str(d)],
                           capture_output=True, text=True, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
        return name, "cloned" if r.returncode == 0 else f"FAILED {r.stderr.strip()[-200:]}"

    with cf.ThreadPoolExecutor(6) as ex:
        for name, status in ex.map(one, REFS.items()):
            print(f"  {name}: {status}")


if __name__ == "__main__":
    main()
