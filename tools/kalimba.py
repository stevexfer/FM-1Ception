#!/usr/bin/env python3
"""Make web/kalimba (the USB audio in's kalimba, web/worklet.js) from Serum 2's factory Kalimba.sfz:
its velocity layers 01-03 (the zones), each note at 32 kHz, at most 2.5 s with a fade, as FLAC, and
kalimba.json: per sample its file, MIDI key, zone and tuning (the SFZ's tune, cents).
Needs macOS's afconvert and flac.

  tools/kalimba.py "/Library/Audio/Presets/Xfer Records/Serum 2 Presets/Multisamples/Factory/Plucked/Kalimba.sfz"
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
import wave
from array import array
from pathlib import Path

ZONES = ["01", "02", "03"]
RATE = 32000
MAX_S, FADE_S = 2.5, 0.4
OUT = Path(__file__).resolve().parent.parent / "web" / "kalimba"


def regions(sfz):
    text = sfz.read_text()
    for block in text.split("<region>")[1:]:
        kv = dict(re.findall(r"(\w+)=(.+?)(?=\s+\w+=|\s*$)", block, re.M))
        yield kv["sample"].strip(), int(kv.get("pitch_keycenter", kv.get("key"))), int(kv.get("tune", 0))


def main():
    sfz = Path(sys.argv[1])
    folder = sfz.parent / "Kalimba Samples"
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    listed = []
    with tempfile.TemporaryDirectory() as tmp:
        for sample, key, tune in regions(sfz):
            zone = sample.split()[1]
            if zone not in ZONES:
                continue
            wav = Path(tmp) / "a.wav"
            subprocess.run(["afconvert", "-f", "WAVE", "-d", f"LEI16@{RATE}", "-c", "1", folder / sample, wav], check=True)
            with wave.open(str(wav)) as w:
                pcm = array("h", w.readframes(w.getnframes()))
            n, fade = min(len(pcm), int(MAX_S * RATE)), int(FADE_S * RATE)
            pcm = pcm[:n]
            if n == int(MAX_S * RATE):
                for i in range(fade):
                    pcm[n - fade + i] = int(pcm[n - fade + i] * (1 - i / fade))
            with wave.open(str(wav), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(RATE)
                w.writeframes(pcm.tobytes())
            name = f"kalimba-{zone}-{key}.flac"
            subprocess.run(["flac", "-s", "-8", "-f", "--no-padding", "-o", OUT / name, wav], check=True)
            listed.append({"file": name, "key": key, "zone": ZONES.index(zone), "tune": tune})
    (OUT / "kalimba.json").write_text(json.dumps(listed, indent=1) + "\n")
    size = sum(p.stat().st_size for p in OUT.iterdir())
    print(f"{OUT}: {len(listed)} samples, {size // 1024} KB")


if __name__ == "__main__":
    main()
