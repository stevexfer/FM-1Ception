//! AutoSample: an engine's sound as a multisample. The engine's whole machine is taken once (a
//! save-state) and every note is rendered from a copy of it on the caller's threads, flat out and
//! silent, so the engine plays on untouched and each note starts from the same moment.
//!
//! - The start: the copy is sent All Notes Off and run until it is quiet (`Sampler::new`).
//! - Programs: one click of the PRESETS encoder at a time (`Sampler::scout`). A second copy with a
//!   USB cable to this computer hears what the firmware's screen reader says (fm1-base's
//!   announce.c: SysEx F0 7D 53 52) to name each one. The audio comes from the copy without the
//!   cable, which plays a little differently when USB is serviced.
//! - A note (`Sampler::note`): held for a time, or until its level has stayed put for two seconds
//!   (or has died away), then released and recorded until it is quiet again; trimmed to its onset
//!   and its end, with a loop found in its sustain (`find_loop`).

use crate::engine::Machine;
use fm1_soc::Action;
use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};
use std::sync::{Arc, Mutex};

type Sectors = Vec<(u32, Vec<u8>)>;

/// A machine to start from: the flash it was saved with, and the save-state.
#[derive(Clone)]
struct Moment {
    sectors: Arc<Sectors>,
    state: Arc<Vec<u8>>,
}

/// One program the PRESETS encoder reached.
pub struct Program {
    /// what the screen reader said once it got there (empty: nothing)
    pub said: String,
    moment: Moment,
}

pub struct Sampler {
    pkg: Arc<Vec<u8>>,
    frame_ns: Option<u64>,
    pub rate: f64,
    /// MIDI channel 0..15 the notes go out on
    channel: u8,
    /// whether the start fell quiet with no note held
    pub quiet: bool,
    programs: Mutex<Vec<Program>>,
    /// programs scouted so far, for a progress bar
    pub scouted: AtomicU32,
}

/// What a note is held for.
#[derive(Clone, Copy, Debug)]
pub enum Hold {
    Ms(u32),
    /// until its level stays put for `STABLE_MS` or it dies away, at most this long
    UntilSettled(u32),
}

#[derive(Clone, Copy, Debug)]
pub struct Spec {
    pub note: u8,
    pub velocity: u8,
    pub hold: Hold,
    pub loop_points: bool,
    /// the release recorded after the note-off, at most
    pub max_tail_ms: u32,
}

/// A rendered note.
#[derive(Default)]
pub struct Sample {
    /// interleaved, `channels` (1: left and right were the same throughout)
    pub data: Vec<f32>,
    pub channels: usize,
    pub frames: usize,
    pub silent: bool,
    /// its level settled (or it died away) before the hold ran out
    pub settled: bool,
    /// it died away while held: a one-shot, no loop
    pub decayed: bool,
    /// the frame the note-off went in at
    pub note_off: usize,
    pub lp: Option<Loop>,
    pub peak: f32,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Loop {
    pub start: usize,
    /// the frame after the loop's last
    pub end: usize,
    /// the crossfade's length, frames
    pub crossfade: usize,
}

const STABLE_MS: usize = 2000;
/// a level that has settled stays within this range over `STABLE_MS`
const STABLE_DB: f32 = 2.0;
const QUIET_DB: f32 = -70.0;
/// a click of PRESETS and the time the firmware gets to show and say the program it reached
const SETTLE_MS: u64 = 700;
const HELLO: [u8; 7] = [0xF0, 0x7D, 0x53, 0x52, 0x01, 0x01, 0xF7];
/// the PRESETS encoder (fm1-live's panel.rs ENCS)
const PRESETS_ENC: u8 = 6;

fn db(ms: f32) -> f32 {
    10.0 * (ms.max(1e-14)).log10()
}

impl Sampler {
    /// From an engine's machine: the package it runs, the flash and save-state taken together,
    /// its codec frame time. Sends All Notes Off on `channel` and runs (up to 4 s) until quiet.
    pub fn new(pkg: Arc<Vec<u8>>, sectors: Sectors, state: Vec<u8>, frame_ns: Option<u64>, channel: u8) -> Result<Self, String> {
        let rate = crate::engine::sample_hz(frame_ns);
        let mut m = Machine::restore(&pkg, &sectors, &state, frame_ns)?;
        let ch = channel & 15;
        for b in [0xB0 | ch, 123, 0, 0xB0 | ch, 120, 0, 0xB0 | ch, 64, 0] {
            m.soc.periph.apply(&Action::Midi { b });
        }
        let block = (rate / 10.0) as usize;
        let mut quiet_blocks = 0;
        let mut quiet = false;
        let mut audio = Vec::new();
        let t0 = m.soc.periph.ms();
        while m.soc.periph.ms() - t0 < 4000 && !m.halted {
            run(&mut m, &mut audio);
            while audio.len() >= block * 2 {
                let ms = audio[..block * 2].iter().map(|&s| (s as f32 / 32768.0).powi(2)).sum::<f32>() / (block * 2) as f32;
                audio.drain(..block * 2);
                quiet_blocks = if db(ms) < QUIET_DB { quiet_blocks + 1 } else { 0 };
            }
            if quiet_blocks >= 3 && m.soc.periph.ms() - t0 >= 300 {
                quiet = true;
                break;
            }
        }
        if m.halted {
            return Err("the firmware stopped".into());
        }
        let (sectors, state) = m.save_state(&pkg)?;
        let moment = Moment { sectors: Arc::new(sectors), state: Arc::new(state) };
        Ok(Sampler {
            pkg,
            frame_ns,
            rate,
            channel: ch,
            quiet,
            programs: Mutex::new(vec![Program { said: String::new(), moment }]),
            scouted: AtomicU32::new(1),
        })
    }

    fn restore(&self, at: &Moment) -> Result<Machine, String> {
        Machine::restore(&self.pkg, &at.sectors, &at.state, self.frame_ns)
    }

    pub fn programs(&self) -> usize {
        self.programs.lock().unwrap().len()
    }

    pub fn said(&self, program: usize) -> Option<String> {
        self.programs.lock().unwrap().get(program).map(|p| p.said.clone())
    }

    /// Programs `first..=last` (1: the one the engine is on, each next one a PRESETS click on),
    /// in place of the start alone. Stops early where a click changes nothing (neither the screen
    /// nor what the reader says) or comes back round to program 1. Returns how many were found.
    pub fn scout(&self, first: usize, last: usize, cancel: &AtomicBool) -> Result<usize, String> {
        let first = first.max(1);
        let last = last.max(first);
        let start = self.programs.lock().unwrap()[0].moment.clone();
        let mut step = self.restore(&start)?;
        let mut ear = self.restore(&start)?;
        ear.soc.usb_plug();
        let mut reader = Reader::default();
        // enumeration, then the reader's HELLO and the whole screen the firmware answers with
        reader.run(&mut ear, 3000);
        // program 1's name: a click on and back (on the cable's copy only) makes the firmware say it
        let mut said1 = String::new();
        if reader.on {
            click(&mut ear, 1);
            reader.run(&mut ear, SETTLE_MS);
            reader.said.clear();
            click(&mut ear, -1);
            reader.run(&mut ear, SETTLE_MS);
            said1 = reader.said.first().cloned().unwrap_or_default();
        }
        let mut found: Vec<Program> = Vec::new();
        let screen1 = screen_hash(&step);
        let mut screen = screen1;
        if first == 1 {
            found.push(Program { said: said1.clone(), moment: start.clone() });
        }
        for k in 2..=last {
            if cancel.load(Ordering::Relaxed) {
                return Err("cancelled".into());
            }
            click(&mut step, 1);
            run_ms(&mut step, SETTLE_MS);
            reader.said.clear();
            if reader.on {
                click(&mut ear, 1);
                reader.run(&mut ear, SETTLE_MS);
            }
            if step.halted {
                break;
            }
            let said = reader.said.first().cloned().unwrap_or_default();
            let now = screen_hash(&step);
            let moved = now != screen || !said.is_empty();
            let round = (!said1.is_empty() && said == said1) || (said1.is_empty() && now == screen1);
            if !moved || round {
                break;
            }
            screen = now;
            if k >= first {
                let (sectors, state) = step.save_state(&self.pkg)?;
                found.push(Program { said, moment: Moment { sectors: Arc::new(sectors), state: Arc::new(state) } });
            }
            self.scouted.store(k as u32, Ordering::Relaxed);
        }
        if found.is_empty() {
            return Err(format!("the PRESETS knob reached no program from {first} on"));
        }
        let n = found.len();
        *self.programs.lock().unwrap() = found;
        Ok(n)
    }

    /// One note of a program, rendered and trimmed. Any thread; several at once.
    pub fn note(&self, program: usize, spec: &Spec, cancel: &AtomicBool) -> Result<Sample, String> {
        let moment = self.programs.lock().unwrap().get(program).map(|p| p.moment.clone()).ok_or("no such program")?;
        let mut m = self.restore(&moment)?;
        let take = record(&mut m, self, spec, cancel)?;
        Ok(finish(take, spec, self.rate))
    }
}

/// One stretch of the machine, its audio onto `out`.
fn run(m: &mut Machine, out: &mut Vec<i16>) {
    m.run(20_000);
    out.extend(std::mem::take(&mut m.soc.periph.audio));
}

fn run_ms(m: &mut Machine, ms: u64) {
    let t0 = m.soc.periph.ms();
    while m.soc.periph.ms() - t0 < ms && !m.halted {
        m.run(20_000);
        m.soc.periph.audio.clear();
    }
}

fn click(m: &mut Machine, clicks: i32) {
    m.soc.periph.apply(&Action::Enc { enc: PRESETS_ENC, clicks });
}

fn screen_hash(m: &Machine) -> u64 {
    use std::hash::{Hash, Hasher};
    let mut h = std::collections::hash_map::DefaultHasher::new();
    m.soc.lcd.fb.hash(&mut h);
    h.finish()
}

/// The screen reader's end of the cable: HELLO every 1.5 s, and the SAYs the firmware sends.
#[derive(Default)]
struct Reader {
    on: bool,
    hello_at: Option<u64>,
    said: Vec<String>,
}

impl Reader {
    fn run(&mut self, m: &mut Machine, ms: u64) {
        let t0 = m.soc.periph.ms();
        while m.soc.periph.ms() - t0 < ms && !m.halted {
            let now = m.soc.periph.ms();
            if self.hello_at.map_or(true, |t| now >= t + if self.on { 1500 } else { 500 }) {
                m.soc.usb.midi_send(&HELLO);
                self.hello_at = Some(now);
            }
            m.run(20_000);
            m.soc.periph.audio.clear();
            for msg in m.soc.usb.midi_take() {
                if msg.len() >= 7 && msg[..4] == [0xF0, 0x7D, 0x53, 0x52] {
                    match msg[4] {
                        1 => self.on = true,
                        16 => {
                            let text: String = msg[6..msg.len() - 1].iter().map(|&b| b as char).collect();
                            if !text.trim().is_empty() {
                                self.said.push(text.trim().to_owned());
                            }
                        }
                        _ => {}
                    }
                }
            }
        }
    }
}

/// A note as recorded: stereo frames from the note-on.
struct Take {
    frames: Vec<[f32; 2]>,
    note_off: usize,
    settled: bool,
    decayed: bool,
    /// where the settled stretch began (UntilSettled)
    settled_from: Option<usize>,
}

/// Note on, held as `spec` says, note off, the release until quiet.
fn record(m: &mut Machine, s: &Sampler, spec: &Spec, cancel: &AtomicBool) -> Result<Take, String> {
    let ch = s.channel;
    for b in [0x90 | ch, spec.note & 127, spec.velocity.clamp(1, 127)] {
        m.soc.periph.apply(&Action::Midi { b });
    }
    let block = ((s.rate / 100.0).round() as usize).max(1); // 10 ms
    let stable_blocks = STABLE_MS / 10;
    let mut frames: Vec<[f32; 2]> = Vec::new();
    let mut raw = Vec::new();
    let mut levels: Vec<f32> = Vec::new(); // dB of each 10 ms block (both channels)
    let mut onset: Option<usize> = None;
    let mut off: Option<usize> = None;
    let (mut settled, mut decayed, mut settled_from) = (false, false, None);
    let hold_cap = match spec.hold {
        Hold::Ms(ms) => ms as usize,
        Hold::UntilSettled(cap) => cap as usize,
    } * s.rate as usize / 1000;
    let tail_cap = spec.max_tail_ms as usize * s.rate as usize / 1000;
    let mut peak_db = -200.0f32;
    let mut quiet_run = 0usize;
    loop {
        if cancel.load(Ordering::Relaxed) {
            return Err("cancelled".into());
        }
        run(m, &mut raw);
        if m.halted {
            return Err("the firmware stopped".into());
        }
        for f in raw.chunks_exact(2) {
            frames.push([f[0] as f32 / 32768.0, f[1] as f32 / 32768.0]);
        }
        raw.clear();
        // the 10 ms blocks finished since the last look
        while (levels.len() + 1) * block <= frames.len() {
            let b = &frames[levels.len() * block..(levels.len() + 1) * block];
            let ms = b.iter().map(|f| (f[0] * f[0] + f[1] * f[1]) * 0.5).sum::<f32>() / block as f32;
            let d = db(ms);
            levels.push(d);
            peak_db = peak_db.max(d);
            if onset.is_none() && d > QUIET_DB {
                onset = Some(levels.len() - 1);
            }
            let i = levels.len();
            match off {
                None => {
                    let held = i * block;
                    let mut release = held >= hold_cap;
                    if let (Hold::UntilSettled(_), Some(o)) = (spec.hold, onset) {
                        // died away: the last 300 ms quiet, after the onset
                        if i >= o + 30 && levels[i - 30..].iter().all(|&l| l < QUIET_DB) {
                            (settled, decayed, release) = (true, true, true);
                        } else if i >= o + stable_blocks + 30 {
                            // settled: the level over 300 ms (a chorus's or a detuned pad's beating
                            // averaged out) stays within STABLE_DB for STABLE_MS
                            let smooth = |j: usize| {
                                let ms = levels[j - 30..j].iter().map(|&l| 10f32.powf(l / 10.0)).sum::<f32>() / 30.0;
                                db(ms)
                            };
                            let (mut lo, mut hi) = (f32::MAX, f32::MIN);
                            for j in i - stable_blocks..=i {
                                let v = smooth(j);
                                (lo, hi) = (lo.min(v), hi.max(v));
                            }
                            // or it moves (a pulse, a tremolo) but no longer grows or fades: the
                            // two seconds' halves the same on average
                            let mean = |r: &[f32]| db(r.iter().map(|&l| 10f32.powf(l / 10.0)).sum::<f32>() / r.len() as f32);
                            let half = stable_blocks / 2;
                            let even = (mean(&levels[i - stable_blocks..i - half]) - mean(&levels[i - half..i])).abs() <= 0.75;
                            if (hi - lo <= STABLE_DB || even) && hi > QUIET_DB + 10.0 {
                                (settled, release) = (true, true);
                                settled_from = Some((i - stable_blocks) * block);
                            }
                        }
                    }
                    // nothing at all within 2 s: a note this firmware does not play
                    if onset.is_none() && held >= 2 * s.rate as usize {
                        return Ok(Take { frames, note_off: held, settled: false, decayed: true, settled_from: None });
                    }
                    if release {
                        off = Some(held);
                        for b in [0x80 | ch, spec.note & 127, 0] {
                            m.soc.periph.apply(&Action::Midi { b });
                        }
                    }
                }
                Some(o) => {
                    quiet_run = if d < QUIET_DB.max(peak_db - 80.0) { quiet_run + 1 } else { 0 };
                    if quiet_run >= 30 || i * block >= o + tail_cap {
                        frames.truncate(i * block);
                        return Ok(Take { frames, note_off: o, settled, decayed, settled_from });
                    }
                }
            }
        }
    }
}

/// The take trimmed to its onset and its end (a short fade), mono if both sides were the same,
/// and its loop.
fn finish(t: Take, spec: &Spec, rate: f64) -> Sample {
    let peak = t.frames.iter().map(|f| f[0].abs().max(f[1].abs())).fold(0.0f32, f32::max);
    if peak < 10f32.powf(QUIET_DB / 20.0) {
        return Sample { silent: true, ..Default::default() };
    }
    let on_th = (peak * 1e-3).max(3e-5);
    let onset = t.frames.iter().position(|f| f[0].abs().max(f[1].abs()) > on_th).unwrap_or(0);
    let start = onset.saturating_sub(16);
    let end_th = (peak * 1e-4).max(1e-5);
    let last = t.frames.iter().rposition(|f| f[0].abs().max(f[1].abs()) > end_th).unwrap_or(t.frames.len() - 1);
    let end = (last + (rate * 0.01) as usize).min(t.frames.len());
    let mut fr: Vec<[f32; 2]> = t.frames[start..end].to_vec();
    let fade = ((rate * 0.005) as usize).min(fr.len());
    let n = fr.len();
    for (k, f) in fr[n - fade..].iter_mut().enumerate() {
        let g = 1.0 - (k + 1) as f32 / fade as f32;
        f[0] *= g;
        f[1] *= g;
    }
    let note_off = t.note_off.saturating_sub(start).min(fr.len());
    let mono = fr.iter().all(|f| f[0] == f[1]);
    let lp = if spec.loop_points && !t.decayed && note_off > 0 {
        let x: Vec<f32> = fr.iter().map(|f| (f[0] + f[1]) * 0.5).collect();
        let on = onset - start;
        let half = on + (note_off - on) / 2;
        let from = t.settled_from.map_or(half, |s| half.max(s.saturating_sub(start)));
        let p0 = rate / (440.0 * 2f64.powf((spec.note as f64 - 69.0) / 12.0));
        find_loop(&x, from, note_off, on, p0, rate)
    } else {
        None
    };
    let data = if mono { fr.iter().map(|f| f[0]).collect() } else { fr.iter().flat_map(|f| [f[0], f[1]]).collect() };
    Sample {
        data,
        channels: if mono { 1 } else { 2 },
        frames: fr.len(),
        silent: false,
        settled: t.settled,
        decayed: t.decayed,
        note_off,
        lp,
        peak,
    }
}

// ------------------------------------------------------------------------------------ loops

/// The period near `p0` (within a quarter either way) the window repeats at, by normalised
/// autocorrelation; `p0` if nothing repeats clearly.
fn period(x: &[f32], p0: f64) -> f64 {
    let lo = (p0 * 0.8).floor().max(2.0) as usize;
    let hi = (p0 * 1.25).ceil() as usize;
    let n = (4 * hi).max(2048).min(x.len().saturating_sub(hi + 1));
    if n < 2 * hi {
        return p0;
    }
    let mid = (x.len() - n - hi) / 2;
    let seg = &x[mid..mid + n + hi];
    let r = |lag: usize| {
        let (mut xy, mut xx, mut yy) = (0.0f64, 0.0f64, 0.0f64);
        for i in 0..n {
            let (a, b) = (seg[i] as f64, seg[i + lag] as f64);
            xy += a * b;
            xx += a * a;
            yy += b * b;
        }
        xy / (xx * yy).sqrt().max(1e-20)
    };
    let rs: Vec<f64> = (lo..=hi).map(r).collect();
    let (k, &best) = rs.iter().enumerate().max_by(|a, b| a.1.total_cmp(b.1)).unwrap();
    if best < 0.3 {
        return p0;
    }
    // the peak between its neighbours
    let frac = if k > 0 && k + 1 < rs.len() {
        let (a, b, c) = (rs[k - 1], rs[k], rs[k + 1]);
        let d = a - 2.0 * b + c;
        if d.abs() > 1e-12 { (0.5 * (a - c) / d).clamp(-0.5, 0.5) } else { 0.0 }
    } else {
        0.0
    };
    (lo + k) as f64 + frac
}

/// How much the sound at `e` differs from the sound at `s`, over `c` samples around each:
/// 0 the same, 1 unrelated.
fn join_err(x: &[f32], s: usize, e: usize, c: usize) -> f32 {
    let h = c / 2;
    let (mut d, mut p) = (0.0f32, 0.0f32);
    for i in 0..c {
        let (a, b) = (x[s + i - h], x[e + i - h]);
        d += (a - b) * (a - b);
        p += a * a + b * b;
    }
    d / p.max(1e-12)
}

/// A loop in `x[from..to]` (mono): a whole number of periods long, between 50 ms (or four
/// periods) and 2.5 s, where the sound at its end runs on into its start and its level stays
/// even; the longest of the good ones. Its ends on rising zero crossings, a crossfade of a tenth
/// of it (5..200 ms, no more than there is before its start after `onset`). None if the window
/// is too short or nothing joins well.
pub fn find_loop(x: &[f32], from: usize, to: usize, onset: usize, p0: f64, rate: f64) -> Option<Loop> {
    let to = to.min(x.len());
    if to <= from || (to - from) as f64 <= 8.0 * p0 {
        return None;
    }
    let p = period(&x[from..to], p0).max(2.0);
    let c = ((2.0 * p) as usize).clamp(64, 2048);
    let h = c / 2;
    let lmin = (4.0 * p).max(0.05 * rate);
    let lmax = (2.5 * rate).min((to - from) as f64 - c as f64 - 1.0);
    if lmax < lmin {
        return None;
    }
    // levels of 50 ms blocks (three periods if longer), for how even the level is across a loop
    let block = ((0.05 * rate).max(3.0 * p) as usize).max(1);
    let lv: Vec<f32> = x.chunks(block).map(|b| db(b.iter().map(|v| v * v).sum::<f32>() / b.len() as f32)).collect();
    // how far the level is from even across a loop: the step at its join, and a trend between its
    // halves (movement within it, a pad's pulse or a tremolo, is the sound's own)
    let spread = |s: usize, e: usize| {
        let (a, b) = (s / block, (e / block).max(s / block + 1).min(lv.len()));
        let join = (lv[a] - lv[b - 1]).abs();
        let m = (a + b) / 2;
        let mean = |r: &[f32]| if r.is_empty() { 0.0 } else { db(r.iter().map(|&l| 10f32.powf(l / 10.0)).sum::<f32>() / r.len() as f32) };
        let trend = if b - a >= 4 { (mean(&lv[a..m]) - mean(&lv[m..b])).abs() } else { 0.0 };
        join + trend
    };
    let r = (p / 2.0).ceil() as usize;
    let reach = ((p / 2.0) as usize).max(1);
    // room past the end for the refinements below to move it
    let margin = h + r + reach + 9;
    let lo_s = from.max(onset + h).max(h) + reach + 1;
    let hi_s = to.saturating_sub(lmin as usize + margin);
    if hi_s <= lo_s {
        return None;
    }
    // starts every 25 ms (or period), at most 48 of them; from each, every whole number of periods
    // as the end, so a long loop can land where a chorus or a beating pad comes round again
    let step = ((p.round() as usize).max((0.025 * rate) as usize)).max((hi_s - lo_s) / 48).max(1);
    let mut best: Option<(f32, usize, usize)> = None;
    let debug = std::env::var("FM1C_LOOP_DEBUG").is_ok();
    let mut s = lo_s;
    while s < hi_s {
        let mut k = (lmin / p).ceil();
        loop {
            let l = (k * p).round() as usize;
            if l as f64 > lmax || s + l + margin >= to {
                break;
            }
            let err = join_err(x, s, s + l, c);
            if err < 0.35 {
                let score = err + spread(s, s + l) / 30.0 - 0.2 * (l as f64 / lmax) as f32
                    // later is better: a loop that ends near the note-off leaves the release prompt
                    - 0.05 * ((s + l - from) as f32 / (to - from) as f32);
                if best.map_or(true, |b| score < b.0) {
                    best = Some((score, s, l));
                }
            }
            k += 1.0;
        }
        s += step;
    }
    if debug {
        let (sc, bs, bl) = best.unwrap_or((0.0, 0, 0));
        eprintln!("  p {p:.2} (p0 {p0:.2}), window {from}..{to}: loop {bl} ({:.0} ms) at {bs}, err {:.3}, spread {:.1} dB, score {sc:.3}",
                  bl as f64 * 1000.0 / rate, if bl > 0 { join_err(x, bs, bs + bl, c) } else { 0.0 },
                  if bl > 0 { spread(bs, bs + bl) } else { 0.0 });
    }
    let (_, s, l) = best?;
    // the length to the sample, within half a period
    let mut e = s + l;
    let mut e_err = join_err(x, s, e, c);
    for cand in (s + l).saturating_sub(r)..=(s + l + r) {
        if cand + h >= to || cand <= s + c {
            continue;
        }
        let err = join_err(x, s, cand, c);
        if err < e_err {
            (e, e_err) = (cand, err);
        }
    }
    // both ends to the nearest rising zero crossing of the start, moved together
    let rising = |i: usize| i > 0 && x[i - 1] < 0.0 && x[i] >= 0.0;
    let snap = (0..=reach).flat_map(|d| [s + d, s.wrapping_sub(d)]).find(|&i| i > onset + h && i < to && rising(i)).unwrap_or(s);
    let shift = snap as i64 - s as i64;
    let (s, mut e) = (snap, (e as i64 + shift) as usize);
    // the end to its own crossing within a few samples, if one is there
    if let Some(z) = (0..=8usize).flat_map(|d| [e + d, e.wrapping_sub(d)]).find(|&i| i > s && i + h < to && rising(i)) {
        e = z;
    }
    if e + h >= x.len() || e <= s {
        return None;
    }
    let len = e - s;
    let crossfade = ((len as f64 * 0.1) as usize).clamp((0.005 * rate) as usize, (0.2 * rate) as usize).min(s - onset);
    Some(Loop { start: s, end: e, crossfade })
}

// ------------------------------------------------------------------------------------ C ABI

impl crate::Fm1e {
    /// The machine now: its package, the flash and save-state taken together, its frame time.
    fn moment(&self) -> Result<(Arc<Vec<u8>>, Sectors, Vec<u8>, Option<u64>), String> {
        let pkg = self.params.firmware.lock().unwrap().pkg.clone();
        if pkg.is_empty() {
            return Err("load a firmware first".into());
        }
        let (tx, rx) = std::sync::mpsc::channel();
        self.cmds.send(crate::engine::Cmd::SaveState { reply: tx }).map_err(|_| "the engine stopped".to_owned())?;
        let (sectors, state) = rx
            .recv_timeout(std::time::Duration::from_secs(5))
            .map_err(|_| "the engine did not answer".to_owned())??;
        let sectors = sectors.iter().map(|s| (s.at, s.data.to_vec())).collect();
        Ok((pkg, sectors, state, self.params.audio.value().frame_ns()))
    }
}

#[repr(C)]
pub struct Fm1eSampleSpec {
    pub note: u8,
    pub velocity: u8,
    pub loop_points: u8,
    /// 0: until it settles, at most max_hold_ms
    pub hold_ms: u32,
    pub max_hold_ms: u32,
    pub max_tail_ms: u32,
}

#[repr(C)]
pub struct Fm1eSampleInfo {
    pub frames: u64,
    pub channels: u32,
    pub silent: u8,
    pub settled: u8,
    pub decayed: u8,
    pub has_loop: u8,
    pub loop_start: u64,
    /// the frame after the loop's last
    pub loop_end: u64,
    pub crossfade: u64,
    pub note_off: u64,
    pub peak: f32,
}

unsafe fn result<T>(r: Result<T, String>, msg: *mut std::ffi::c_char, cap: usize) -> Option<T> {
    match r {
        Ok(v) => Some(v),
        Err(why) => {
            crate::message(&why, msg, cap);
            None
        }
    }
}

fn guarded<T>(f: impl FnOnce() -> Result<T, String>) -> Result<T, String> {
    std::panic::catch_unwind(std::panic::AssertUnwindSafe(f)).unwrap_or_else(|_| Err("the firmware could not be run".into()))
}

/// A sampler from the engine's machine as it is now, its notes on MIDI `channel` (1..16).
/// Blocks (a second or so). Null on failure (msg: why).
///
/// # Safety
/// `e` a live handle; `msg` writable for `cap` bytes (or null).
#[no_mangle]
pub unsafe extern "C" fn fm1e_sampler_create(e: *const crate::Fm1e, channel: u8, msg: *mut std::ffi::c_char, cap: usize) -> *mut Sampler {
    let e = &*e;
    let r = guarded(|| {
        let (pkg, sectors, state, frame_ns) = e.moment()?;
        Sampler::new(pkg, sectors, state, frame_ns, channel.clamp(1, 16) - 1)
    });
    result(r, msg, cap).map_or(std::ptr::null_mut(), |s| Box::into_raw(Box::new(s)))
}

/// # Safety
/// `s` from fm1e_sampler_create (or null), no call on it running.
#[no_mangle]
pub unsafe extern "C" fn fm1e_sampler_destroy(s: *mut Sampler) {
    if !s.is_null() {
        drop(Box::from_raw(s));
    }
}

/// # Safety
/// `s` a live sampler.
#[no_mangle]
pub unsafe extern "C" fn fm1e_sampler_rate(s: *const Sampler) -> f64 {
    (*s).rate
}

/// # Safety
/// `s` a live sampler.
#[no_mangle]
pub unsafe extern "C" fn fm1e_sampler_quiet(s: *const Sampler) -> bool {
    (*s).quiet
}

/// Programs first..last by the PRESETS knob (see Sampler::scout). Blocks; `cancel` stops it.
/// Returns how many, or -1 (msg: why).
///
/// # Safety
/// `s` a live sampler; `cancel` valid while it runs; `msg` as fm1e_sampler_create's.
#[no_mangle]
pub unsafe extern "C" fn fm1e_sampler_scout(s: *const Sampler, first: u32, last: u32, cancel: *const AtomicBool,
                                            msg: *mut std::ffi::c_char, cap: usize) -> i32 {
    let s = &*s;
    let never = AtomicBool::new(false);
    let cancel = if cancel.is_null() { &never } else { &*cancel };
    result(guarded(|| s.scout(first as usize, last as usize, cancel)), msg, cap).map_or(-1, |n| n as i32)
}

/// The program fm1e_sampler_scout has reached so far (1-based), for its progress.
///
/// # Safety
/// `s` a live sampler.
#[no_mangle]
pub unsafe extern "C" fn fm1e_sampler_scouted(s: *const Sampler) -> u32 {
    (*s).scouted.load(Ordering::Relaxed)
}

/// # Safety
/// `s` a live sampler.
#[no_mangle]
pub unsafe extern "C" fn fm1e_sampler_programs(s: *const Sampler) -> u32 {
    (*s).programs() as u32
}

/// What the screen reader said at program `i` (0-based; ASCII, not terminated); its length.
///
/// # Safety
/// `s` a live sampler; `out` writable for `cap` bytes (or null).
#[no_mangle]
pub unsafe extern "C" fn fm1e_sampler_said(s: *const Sampler, i: u32, out: *mut u8, cap: usize) -> usize {
    crate::copy_out((*s).said(i as usize).unwrap_or_default().as_bytes(), out, cap)
}

/// A program's name from what the reader said (preset_name); its length.
///
/// # Safety
/// `said` NUL-terminated; `out` writable for `cap` bytes (or null).
#[no_mangle]
pub unsafe extern "C" fn fm1e_preset_name(said: *const std::ffi::c_char, strip: bool, out: *mut u8, cap: usize) -> usize {
    let said = if said.is_null() { String::new() } else { std::ffi::CStr::from_ptr(said).to_string_lossy().into_owned() };
    crate::copy_out(preset_name(&said, strip).as_bytes(), out, cap)
}

/// One note of program `program` (0-based). Blocks (a second or so); any thread, several at once.
/// Null on failure or cancel (msg: why); else the sample, whose `info` is filled in.
///
/// # Safety
/// `s` a live sampler; `spec` and `info` valid; `cancel` as fm1e_sampler_scout's; `msg` as ever.
#[no_mangle]
pub unsafe extern "C" fn fm1e_sampler_note(s: *const Sampler, program: u32, spec: *const Fm1eSampleSpec, cancel: *const AtomicBool,
                                           info: *mut Fm1eSampleInfo, msg: *mut std::ffi::c_char, cap: usize) -> *mut Sample {
    let s = &*s;
    let sp = &*spec;
    let never = AtomicBool::new(false);
    let cancel = if cancel.is_null() { &never } else { &*cancel };
    let spec = Spec {
        note: sp.note,
        velocity: sp.velocity,
        hold: if sp.hold_ms == 0 { Hold::UntilSettled(sp.max_hold_ms.max(1000)) } else { Hold::Ms(sp.hold_ms) },
        loop_points: sp.loop_points != 0,
        max_tail_ms: sp.max_tail_ms,
    };
    let Some(smp) = result(guarded(|| s.note(program as usize, &spec, cancel)), msg, cap) else { return std::ptr::null_mut() };
    *info = Fm1eSampleInfo {
        frames: smp.frames as u64,
        channels: smp.channels as u32,
        silent: smp.silent as u8,
        settled: smp.settled as u8,
        decayed: smp.decayed as u8,
        has_loop: smp.lp.is_some() as u8,
        loop_start: smp.lp.map_or(0, |l| l.start as u64),
        loop_end: smp.lp.map_or(0, |l| l.end as u64),
        crossfade: smp.lp.map_or(0, |l| l.crossfade as u64),
        note_off: smp.note_off as u64,
        peak: smp.peak,
    };
    Box::into_raw(Box::new(smp))
}

/// The sample's frames, interleaved by its channels.
///
/// # Safety
/// `smp` from fm1e_sampler_note, not yet freed.
#[no_mangle]
pub unsafe extern "C" fn fm1e_sample_data(smp: *const Sample) -> *const f32 {
    (*smp).data.as_ptr()
}

/// # Safety
/// `smp` from fm1e_sampler_note (or null).
#[no_mangle]
pub unsafe extern "C" fn fm1e_sample_free(smp: *mut Sample) {
    if !smp.is_null() {
        drop(Box::from_raw(smp));
    }
}

// ------------------------------------------------------------------------------------ names

/// A program's name from what the screen reader said: its first sentence, without the reader's
/// page and counter words. With `strip`, a preset number before the name goes too ("P02 Warm Pad",
/// "045 SYNC LEAD", "Program 2, Bright Piano") when a name is left after it.
pub fn preset_name(said: &str, strip: bool) -> String {
    let parts: Vec<&str> = said
        .split(". ")
        .next()
        .unwrap_or("")
        .trim_end_matches('.')
        .split(", ")
        .map(str::trim)
        .filter(|p| !p.is_empty())
        .collect();
    let counter = |p: &str| {
        // "2 of 17", "2/10", "1 OF 32"
        let w: Vec<&str> = p.split_whitespace().collect();
        (w.len() == 3 && w[1].eq_ignore_ascii_case("of") && number(w[0]) && number(w[2]))
            || (w.len() == 1 && w[0].split_once('/').is_some_and(|(a, b)| number(a) && number(b)))
    };
    let kept: Vec<String> = parts
        .iter()
        .filter(|p| !counter(p) && !(strip && label_and_number(p)))
        .map(|p| {
            let p = drop_counter_suffix(p);
            if strip { strip_number(&p) } else { p }
        })
        .filter(|p| !p.is_empty())
        .collect();
    match kept.first() {
        Some(k) => k.clone(),
        None => parts.first().map(|p| p.to_string()).unwrap_or_default(),
    }
}

fn number(w: &str) -> bool {
    !w.is_empty() && w.bytes().all(|b| b.is_ascii_digit())
}

/// a preset number: "02", "P02", "U02", "A-2", "1-02", "#5", "045:", "3)"
fn number_token(w: &str) -> bool {
    let w = w.trim_end_matches([':', '.', ')', '-']).trim_start_matches('#');
    let digits = w.bytes().filter(u8::is_ascii_digit).count();
    digits > 0
        && w.len() <= 5
        && w.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-')
        && w.bytes().filter(u8::is_ascii_alphabetic).count() <= 1
}

const LABELS: [&str; 12] =
    ["preset", "program", "prog", "progression", "patch", "pgm", "slot", "factory", "user", "no", "number", "bank"];

fn label(w: &str) -> bool {
    LABELS.iter().any(|l| w.trim_end_matches([':', '.']).eq_ignore_ascii_case(l))
}

/// "Program 2", "FACTORY SLOT 2", "PRESET 1", "P02": labels and a number, nothing else
fn label_and_number(p: &str) -> bool {
    let w: Vec<&str> = p.split_whitespace().collect();
    !w.is_empty() && number_token(w[w.len() - 1]) && w[..w.len() - 1].iter().all(|x| label(x))
}

/// "WOODEN RAIN 2/10" -> "WOODEN RAIN"
fn drop_counter_suffix(p: &str) -> String {
    match p.rsplit_once(' ') {
        Some((head, tail)) if tail.split_once('/').is_some_and(|(a, b)| number(a) && number(b)) => head.trim().to_owned(),
        _ => p.to_owned(),
    }
}

/// "P02 Warm Pad" -> "Warm Pad", "PROGRESSION P2 Ballad" -> "Ballad", "045 SYNC LEAD" -> "SYNC LEAD"
fn strip_number(p: &str) -> String {
    let w: Vec<&str> = p.split_whitespace().collect();
    let mut i = 0;
    while i < w.len() && label(w[i]) {
        i += 1;
    }
    if i < w.len() && number_token(w[i]) && i + 1 < w.len() {
        return w[i + 1..].join(" ");
    }
    p.to_owned()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn preset_names_from_what_the_reader_says() {
        let cases = [
            ("Guppo. Sing page: Vowel 50, Head 21 cm, Breath 5, Glide 50", "Guppo", "Guppo"),
            ("P02 Warm Pad", "P02 Warm Pad", "Warm Pad"),
            ("045 SYNC LEAD", "045 SYNC LEAD", "SYNC LEAD"),
            ("Program 2, Bright Piano", "Program 2", "Bright Piano"),
            ("PROGRESSION P2 Ballad", "PROGRESSION P2 Ballad", "Ballad"),
            ("ACID TB SQUARE, 2 of 17", "ACID TB SQUARE", "ACID TB SQUARE"),
            ("FACTORY SLOT 2, PAD PWM Chorus", "FACTORY SLOT 2", "PAD PWM Chorus"),
            ("WOODEN RAIN 2/10", "WOODEN RAIN", "WOODEN RAIN"),
            ("1-2 STRINGS", "1-2 STRINGS", "STRINGS"),
            ("A-2 Ensemble Str", "A-2 Ensemble Str", "Ensemble Str"),
            ("PIECE Burren, G Mixolyd., tempo 84", "PIECE Burren", "PIECE Burren"),
            ("POLAR NIGHT", "POLAR NIGHT", "POLAR NIGHT"),
            ("P2", "P2", "P2"),
            ("808 Kick", "808 Kick", "Kick"),
            ("", "", ""),
        ];
        for (said, plain, stripped) in cases {
            assert_eq!(preset_name(said, false), plain, "{said:?}");
            assert_eq!(preset_name(said, true), stripped, "{said:?} stripped");
        }
    }

    fn tone(rate: f64, hz: f64, secs: f64, lfo: f64) -> Vec<f32> {
        (0..(rate * secs) as usize)
            .map(|i| {
                let t = i as f64 / rate;
                let a = 0.5 * (1.0 + 0.1 * (2.0 * std::f64::consts::PI * lfo * t).sin());
                (a * ((2.0 * std::f64::consts::PI * hz * t).sin() + 0.3 * (6.0 * std::f64::consts::PI * hz * t).sin())) as f32
            })
            .collect()
    }

    #[test]
    fn a_loop_in_a_steady_tone_joins_on_its_period() {
        let rate = 44_100.0;
        let hz = 220.0;
        let x = tone(rate, hz, 3.0, 0.0);
        let lp = find_loop(&x, x.len() / 2, x.len(), 0, rate / hz, rate).expect("a loop");
        let periods = (lp.end - lp.start) as f64 * hz / rate;
        assert!((periods - periods.round()).abs() < 0.02, "{periods} periods");
        assert!(join_err(&x, lp.start, lp.end, 256) < 0.01);
        assert!(x[lp.start - 1] < 0.0 && x[lp.start] >= 0.0, "the start on a rising zero crossing");
        assert!(lp.crossfade >= (0.005 * rate) as usize && lp.crossfade <= lp.start);
        assert!(lp.end - lp.start >= (0.5 * rate) as usize, "a long loop: {} frames", lp.end - lp.start);
    }

    #[test]
    fn a_detuned_tone_gets_its_own_period() {
        // a firmware a third of a semitone sharp of the note it was sent
        let rate = 48_076.9;
        let hz = 261.63 * 2f64.powf(0.33 / 12.0);
        let x = tone(rate, hz, 3.0, 2.0);
        let lp = find_loop(&x, x.len() / 2, x.len(), 0, rate / 261.63, rate).expect("a loop");
        assert!(join_err(&x, lp.start, lp.end, 256) < 0.02);
    }

    #[test]
    fn no_loop_in_a_window_too_short_or_in_noise() {
        let rate = 44_100.0;
        let x = tone(rate, 110.0, 0.05, 0.0);
        assert_eq!(find_loop(&x, 0, x.len(), 0, rate / 110.0, rate), None);
        let mut seed = 1u32;
        let noise: Vec<f32> = (0..(rate * 2.0) as usize)
            .map(|_| {
                seed = seed.wrapping_mul(1_664_525).wrapping_add(1_013_904_223);
                (seed >> 8) as f32 / (1u32 << 24) as f32 - 0.5
            })
            .collect();
        assert_eq!(find_loop(&noise, noise.len() / 2, noise.len(), 0, rate / 220.0, rate), None);
    }

    /// FM1C_AUTOSAMPLE=path/to.fwsc cargo test --release real_firmware -- --nocapture
    #[test]
    fn real_firmware() {
        let Ok(path) = std::env::var("FM1C_AUTOSAMPLE") else { return };
        let pkg = Arc::new(std::fs::read(path).unwrap());
        let mut m = Machine::boot(&pkg, &[], 240, false, None).unwrap();
        run_ms(&mut m, 3000);
        let (sectors, state) = m.save_state(&pkg).unwrap();
        let s = Sampler::new(pkg, sectors, state, None, 0).unwrap();
        println!("quiet start: {}", s.quiet);
        let cancel = AtomicBool::new(false);
        let n = s.scout(1, 4, &cancel).unwrap();
        for p in 0..n {
            let said = s.said(p).unwrap();
            println!("program {}: {:?} -> {:?}", p + 1, said, preset_name(&said, true));
        }
        let program = std::env::var("FM1C_AUTOSAMPLE_PROGRAM").ok().and_then(|v| v.parse::<usize>().ok()).unwrap_or(1);
        for note in [36u8, 60, 84] {
            let t = std::time::Instant::now();
            let spec = Spec { note, velocity: 127, hold: Hold::UntilSettled(10_000), loop_points: true, max_tail_ms: 10_000 };
            let smp = s.note(program.clamp(1, n) - 1, &spec, &cancel).unwrap();
            println!("note {note}: {} frames x{} ({:.2} s), off at {:.2} s, settled {} decayed {}, peak {:.3}, loop {:?} ({:.0} ms)",
                     smp.frames, smp.channels, smp.frames as f64 / s.rate, smp.note_off as f64 / s.rate, smp.settled, smp.decayed,
                     smp.peak, smp.lp, t.elapsed().as_secs_f64() * 1000.0);
        }
    }
}
