#include "AutoSampler.h"
#include "FirmwarePrefs.h"
#include <thread>

namespace fm1c
{
namespace
{
// note values at the tempo: 1/64 note to four bars of 4/4
struct HoldChoice { const char* name; double beats; };
constexpr HoldChoice kHolds[] = {
    { "Until It Settles", 0.0 }, { "1/64", 1.0 / 16 }, { "1/32", 1.0 / 8 }, { "1/16", 0.25 }, { "1/8", 0.5 },
    { "1/4", 1.0 }, { "1/2", 2.0 }, { "1 Bar", 4.0 }, { "2 Bars", 8.0 }, { "4 Bars", 16.0 },
};

juce::String seconds (double s, int places = 3)
{
    auto t = juce::String (s, places);
    while (t.containsChar ('.') && (t.endsWithChar ('0') || t.endsWithChar ('.')))
        t = t.dropLastCharacters (1);
    return t;
}
} // namespace

//==============================================================================
juce::Array<int> AutoSampleSettings::notes() const
{
    juce::Array<int> out;
    const int lo = juce::jlimit (0, 127, juce::jmin (root, top)), hi = juce::jlimit (0, 127, juce::jmax (root, top));
    for (int n = lo; n <= hi; n += juce::jmax (1, span))
        out.add (n);
    if (out.getLast() != hi)
        out.add (hi);
    return out;
}

juce::uint32 AutoSampleSettings::holdMs() const
{
    const auto& h = kHolds[juce::jlimit (0, (int) std::size (kHolds) - 1, hold)];
    return h.beats <= 0.0 ? 0u : (juce::uint32) juce::jmax (1.0, std::round (h.beats * 60000.0 / juce::jlimit (20.0, 400.0, tempo)));
}

juce::StringArray AutoSampleSettings::holdNames()
{
    juce::StringArray s;
    for (const auto& h : kHolds)
        s.add (h.name);
    return s;
}

juce::String AutoSampleSettings::noteName (int note)
{
    static const char* names[] = { "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B" };
    return juce::String (names[note % 12]) + juce::String (note / 12 - 2);
}

juce::File AutoSampleSettings::serumFolder()
{
   #if JUCE_MAC
    const juce::File presets ("/Library/Audio/Presets/Xfer Records/Serum 2 Presets");
   #else
    const auto presets = juce::File::getSpecialLocation (juce::File::userDocumentsDirectory)
                             .getChildFile ("Xfer").getChildFile ("Serum 2 Presets");
   #endif
    return presets.getChildFile ("Multisamples").getChildFile ("FM-1");
}

static juce::File settingsFile()
{
    return prefs::folder().getParentDirectory().getChildFile ("AutoSample.json");
}

AutoSampleSettings AutoSampleSettings::load()
{
    AutoSampleSettings s;
    const auto v = juce::JSON::parse (settingsFile());
    auto get = [&v] (const char* key, int def) { return (int) v.getProperty (key, def); };
    s.root = juce::jlimit (0, 127, get ("root", s.root));
    s.top = juce::jlimit (0, 127, get ("top", s.top));
    s.span = juce::jlimit (1, 24, get ("span", s.span));
    s.velocity = juce::jlimit (1, 127, get ("velocity", s.velocity));
    s.hold = juce::jlimit (0, (int) std::size (kHolds) - 1, get ("hold", s.hold));
    s.tempo = juce::jlimit (20.0, 400.0, (double) v.getProperty ("tempo", s.tempo));
    s.loops = (bool) v.getProperty ("loops", s.loops);
    s.programs = (bool) v.getProperty ("programs", s.programs);
    s.firstProgram = juce::jlimit (1, 127, get ("firstProgram", s.firstProgram));
    s.lastProgram = juce::jlimit (1, 127, get ("lastProgram", s.lastProgram));
    s.stripNumbers = (bool) v.getProperty ("stripNumbers", s.stripNumbers);
    return s;
}

void AutoSampleSettings::save() const
{
    auto* o = new juce::DynamicObject();
    o->setProperty ("root", root);
    o->setProperty ("top", top);
    o->setProperty ("span", span);
    o->setProperty ("velocity", velocity);
    o->setProperty ("hold", hold);
    o->setProperty ("tempo", tempo);
    o->setProperty ("loops", loops);
    o->setProperty ("programs", programs);
    o->setProperty ("firstProgram", firstProgram);
    o->setProperty ("lastProgram", lastProgram);
    o->setProperty ("stripNumbers", stripNumbers);
    settingsFile().getParentDirectory().createDirectory();
    settingsFile().replaceWithText (juce::JSON::toString (juce::var (o)));
}

//==============================================================================
AutoSampler::AutoSampler (std::shared_ptr<EngineHandle> h, AutoSampleSettings s, juce::String fw)
    : juce::Thread ("FM-1Ception AutoSample"), engine (std::move (h)), settings (std::move (s)), firmware (std::move (fw))
{
    startThread();
}

AutoSampler::~AutoSampler()
{
    cancel();
    stopThread (30000);
    fm1e_sampler_destroy (sampler);
}

AutoSampler::Status AutoSampler::status() const
{
    const juce::ScopedLock sl (lock);
    auto st = state;
    if (st.stage == Stage::scouting && sampler != nullptr)
    {
        // the PRESETS knob's progress through first..last, and the name it reached last
        const int first = juce::jlimit (1, 127, settings.firstProgram), last = juce::jlimit (first, 127, settings.lastProgram);
        const int k = juce::jlimit (first, last, (int) fm1e_sampler_scouted (sampler));
        std::string said (fm1e_sampler_scouting_said (sampler, nullptr, 0), '\0');
        fm1e_sampler_scouting_said (sampler, (juce::uint8*) said.data(), said.size());
        std::string name (256, '\0');
        name.resize (fm1e_preset_name (said.c_str(), settings.stripNumbers, (juce::uint8*) name.data(), name.size()));
        st.progress = (double) (k - first + 1) / (double) (last - first + 1);
        st.text = "Finding the programs: " + juce::String (k) + " of " + juce::String (last)
                + (name.empty() ? juce::String() : "  (" + juce::String (name) + ")");
    }
    return st;
}

std::vector<AutoSampler::Program> AutoSampler::programs() const
{
    const juce::ScopedLock sl (lock);
    return found;
}

void AutoSampler::capture (std::vector<Program> p)
{
    {
        const juce::ScopedLock sl (lock);
        if (state.stage != Stage::listed)
            return;
        found = std::move (p);
        state.stage = Stage::capturing;
    }
    go.signal();
}

void AutoSampler::cancel()
{
    cancelled = true;
    go.signal();
}

void AutoSampler::set (Stage stage, double progress, const juce::String& text)
{
    const juce::ScopedLock sl (lock);
    state.stage = stage;
    state.progress = progress;
    state.text = text;
}

void AutoSampler::report (const juce::String& line)
{
    const juce::ScopedLock sl (lock);
    lines.add (line);
    state.logLines = lines.size();
}

juce::StringArray AutoSampler::log() const
{
    const juce::ScopedLock sl (lock);
    return lines;
}

juce::String AutoSampler::fileSafe (const juce::String& s)
{
    auto t = s.replaceCharacters ("/\\:*?\"<>|", "---------").removeCharacters ("\r\n\t").trim();
    while (t.endsWithChar ('.'))
        t = t.dropLastCharacters (1).trimEnd();
    return t.isEmpty() ? juce::String ("AutoSample") : t.substring (0, 80);
}

void AutoSampler::run()
{
    char msg[512] = {};
    set (Stage::starting, -1.0, "Taking the engine's machine...");
    sampler = fm1e_sampler_create (engine->get(), (juce::uint8) settings.channel, msg, sizeof msg);
    engine.reset();
    if (sampler == nullptr)
        return set (Stage::failed, 0.0, juce::String ("Could not start: ") + juce::String (msg));
    if (cancelled)
        return set (Stage::cancelled, 0.0, "Cancelled");

    const bool quiet = fm1e_sampler_quiet (sampler);
    {
        juce::StringArray names;
        for (int n : settings.notes())
            names.add (AutoSampleSettings::noteName (n));
        report (firmware + ": " + names.joinIntoString (" ") + " at velocity " + juce::String (settings.velocity)
                + ", MIDI channel " + juce::String (settings.channel));
    }
    if (! quiet)
        report ("Something plays with no note held (a sequencer?): it will be in the samples");
    if (settings.programs)
    {
        const int first = juce::jlimit (1, 127, settings.firstProgram), last = juce::jlimit (first, 127, settings.lastProgram);
        set (Stage::scouting, -1.0, "Finding the programs...");
        const int n = fm1e_sampler_scout (sampler, (juce::uint32) first, (juce::uint32) last, &cancelled, msg, sizeof msg);
        if (cancelled)
            return set (Stage::cancelled, 0.0, "Cancelled");
        if (n < 0)
        {
            report (juce::String ("Could not step through the programs: ") + juce::String (msg));
            return set (Stage::failed, 0.0, juce::String ("Could not step through the programs: ") + juce::String (msg));
        }
        report ("The PRESETS knob reached " + juce::String (n) + (n == 1 ? " program" : " programs")
                + (n < last - first + 1 ? " (it went no further, or came round to the first)" : juce::String()));
    }

    std::vector<Program> list;
    for (juce::uint32 i = 0, n = fm1e_sampler_programs (sampler); i < n; ++i)
    {
        Program p;
        std::string said (fm1e_sampler_said (sampler, i, nullptr, 0), '\0');
        fm1e_sampler_said (sampler, i, (juce::uint8*) said.data(), said.size());
        p.said = juce::String (said);
        std::string name (256, '\0');
        name.resize (fm1e_preset_name (said.c_str(), settings.stripNumbers, (juce::uint8*) name.data(), name.size()));
        p.name = juce::String (name);
        if (p.name.isEmpty() && settings.programs)
            p.name = juce::String (settings.firstProgram + (int) i).paddedLeft ('0', 3);
        list.push_back (p);
    }
    {
        const juce::ScopedLock sl (lock);
        found = list;
    }

    if (settings.programs)
    {
        set (Stage::listed, 1.0, juce::String ((int) list.size()) + (list.size() == 1 ? " program" : " programs")
                                     + " found: untick or rename, then Capture");
        while (! cancelled)
        {
            go.wait (200);
            if (status().stage == Stage::capturing)
                break;
        }
        if (cancelled)
            return set (Stage::cancelled, 0.0, "Cancelled");
    }

    capturePrograms();
}

bool AutoSampler::capturePrograms()
{
    const auto progs = programs();
    const double rate = fm1e_sampler_rate (sampler);
    const auto base = fileSafe (settings.name.isNotEmpty() ? settings.name : firmware);

    const auto parent = settings.parent != juce::File() ? settings.parent : settings.serumFolder();
    auto folder = parent.getChildFile (base);
    for (int k = 2; folder.exists(); ++k)
        folder = parent.getChildFile (base + " " + juce::String (k));
    if (! folder.createDirectory())
    {
        set (Stage::failed, 0.0, "Could not make " + folder.getFullPathName());
        return false;
    }

    int todo = 0, written = 0, silentRun = 0, skipped = 0, done = 0;
    for (const auto& p : progs)
        todo += p.include ? 1 : 0;
    juce::StringArray names;
    std::vector<Note> previous;
    const auto notesList = settings.notes();
    // the note that tells a silent program: the middle one
    const int probe = notesList.size() / 2;
    const auto probeName = AutoSampleSettings::noteName (notesList[probe]);
    for (size_t i = 0; i < progs.size(); ++i)
    {
        if (! progs[i].include)
            continue;
        const auto label = progs.size() > 1 ? (progs[i].name.isNotEmpty() ? progs[i].name : juce::String ((int) i + 1)) : base;
        const auto number = progs.size() > 1 ? juce::String (settings.firstProgram + (int) i).paddedLeft ('0', 3) + "  " : juce::String();
        set (Stage::capturing, (double) done / juce::jmax (1, todo), "Capturing " + label + "...");

        std::vector<Note> notes ((size_t) notesList.size());
        for (int k = 0; k < notesList.size(); ++k)
            notes[(size_t) k].note = notesList[k];
        const bool ok = renderProgram ((int) i, notes, probe) && (notes[(size_t) probe].info.silent || renderProgram ((int) i, notes));
        if (! ok)
        {
            if (! cancelled)
                return false;
            folder.deleteRecursively (true);
            report ("Cancelled");
            set (Stage::cancelled, 0.0, "Cancelled");
            return false;
        }
        ++done;

        if (notes[(size_t) probe].info.silent)
        {
            ++skipped;
            report (number + label + ": silent (" + probeName + " made no sound), skipped");
            if (written == 0 && ++silentRun >= kSilentStop)
            {
                folder.deleteRecursively (true);
                const auto why = juce::String (silentRun) + " programs in a row made no sound, so the run stopped. Does this firmware play "
                               + "MIDI notes on channel " + juce::String (settings.channel) + "? Try a note from your keyboard on this engine.";
                report (why);
                set (Stage::failed, 0.0, why);
                return false;
            }
            if (progs.size() == 1)
            {
                folder.deleteRecursively (true);
                const auto why = probeName + " on MIDI channel " + juce::String (settings.channel)
                               + " made no sound: nothing written. Does this firmware play MIDI notes on that channel?";
                set (Stage::failed, 0.0, why);
                return false;
            }
            continue;
        }
        silentRun = 0;

        auto same = [&previous] (const std::vector<Note>& now)
        {
            if (previous.size() != now.size())
                return false;
            for (size_t k = 0; k < now.size(); ++k)
            {
                const auto &a = previous[k], &b = now[k];
                if (a.data.size() != b.data.size())
                    return false;
                for (size_t j = 0; j < a.data.size(); ++j)
                    if (std::abs (a.data[j] - b.data[j]) > 1.0e-4f)
                        return false;
            }
            return true;
        };
        if (progs.size() > 1 && same (notes))
        {
            ++skipped;
            report (number + label + ": the same as the one before, skipped");
            continue;
        }

        auto file = progs.size() > 1 ? fileSafe (label) : base;
        for (int k = 2; names.contains (file, true); ++k)
            file = fileSafe (label) + " " + juce::String (k);
        names.add (file);
        const auto error = writeProgram (folder, file, progs[i], notes, rate);
        if (error.isNotEmpty())
        {
            report (error);
            set (Stage::failed, 0.0, error);
            return false;
        }
        ++written;
        int sounded = 0, looped = 0, capped = 0;
        for (const auto& n : notes)
        {
            sounded += n.info.silent ? 0 : 1;
            looped += n.info.hasLoop ? 1 : 0;
            capped += settings.holdMs() == 0 && ! n.info.silent && ! n.info.settled ? 1 : 0;
        }
        report (number + label + ": written, " + juce::String (sounded) + " notes, " + juce::String (looped) + " looped"
                + (capped > 0 ? ", " + juce::String (capped) + " never settled (held "
                                    + juce::String ((int) AutoSampleSettings::kMaxHoldMs / 1000) + " s)" : juce::String())
                + (sounded < (int) notes.size() ? ", " + juce::String ((int) notes.size() - sounded) + " silent" : juce::String()));
        previous = std::move (notes);
    }

    const juce::ScopedLock sl (lock);
    state.stage = Stage::done;
    state.progress = 1.0;
    state.folder = folder;
    state.written = written;
    state.text = juce::String (written) + (written == 1 ? " SFZ" : " SFZs") + " written"
               + (skipped == 0 ? juce::String() : ", " + juce::String (skipped) + " skipped");
    if (written == 0)
        folder.deleteRecursively (true);
    lines.add (state.text);
    state.logLines = lines.size();
    return true;
}

bool AutoSampler::renderProgram (int program, std::vector<Note>& notes, int only)
{
    std::vector<int> todo;
    for (int k = 0; k < (int) notes.size(); ++k)
        if (! notes[(size_t) k].rendered && (only < 0 || k == only))
            todo.push_back (k);
    if (todo.empty())
        return true;

    Fm1eSampleSpec spec {};
    spec.velocity = (juce::uint8) juce::jlimit (1, 127, settings.velocity);
    spec.loopPoints = settings.loops ? 1 : 0;
    spec.holdMs = settings.holdMs();
    spec.maxHoldMs = AutoSampleSettings::kMaxHoldMs;
    spec.maxTailMs = AutoSampleSettings::kMaxTailMs;

    std::atomic<int> next { 0 }, finished { 0 };
    std::atomic<bool> failed { false };
    juce::String error;
    juce::CriticalSection errorLock;
    const double base = juce::jmax (0.0, status().progress);
    const int total = (int) notes.size();
    auto work = [&]
    {
        for (int t; ! failed && ! cancelled && (t = next++) < (int) todo.size();)
        {
            auto& n = notes[(size_t) todo[(size_t) t]];
            auto s = spec;
            s.note = (juce::uint8) n.note;
            char msg[512] = {};
            auto* smp = fm1e_sampler_note (sampler, (juce::uint32) program, &s, &cancelled, &n.info, msg, sizeof msg);
            if (smp == nullptr)
            {
                const juce::ScopedLock sl (errorLock);
                error = AutoSampleSettings::noteName (n.note) + ": " + juce::String (msg);
                failed = true;
                return;
            }
            const auto* d = fm1e_sample_data (smp);
            n.data.assign (d, d + n.info.frames * n.info.channels);
            n.rendered = true;
            fm1e_sample_free (smp);
            ++finished;
        }
    };
    const int threads = juce::jlimit (1, 8, (int) std::thread::hardware_concurrency() - 2);
    std::vector<std::thread> pool;
    for (int t = 0; t < juce::jmin (threads, (int) todo.size()); ++t)
        pool.emplace_back (work);
    for (bool running = true; running;)
    {
        juce::Thread::sleep (100);
        running = finished < (int) todo.size() && ! failed && ! cancelled;
        const juce::ScopedLock sl (lock);
        int programsToDo = 0;
        for (const auto& p : found)
            programsToDo += p.include ? 1 : 0;
        state.progress = juce::jmin (1.0, base + (double) finished / (double) total / juce::jmax (1, programsToDo));
    }
    for (auto& t : pool)
        t.join();
    if (failed && ! cancelled)
    {
        report ("Could not render " + error);
        set (Stage::failed, 0.0, "Could not render " + error);
    }
    return ! failed && ! cancelled;
}

juce::String AutoSampler::writeProgram (const juce::File& folder, const juce::String& base, const Program& prog,
                                        std::vector<Note>& notes, double rate)
{
    std::vector<Note*> kept;
    for (auto& n : notes)
        if (! n.info.silent && ! n.data.empty())
            kept.push_back (&n);
    std::sort (kept.begin(), kept.end(), [] (const Note* a, const Note* b) { return a->note < b->note; });
    float peak = 0.0f;
    for (auto* n : kept)
        for (float v : n->data)
            peak = juce::jmax (peak, std::abs (v));
    const float gain = peak > 0.0f ? juce::Decibels::decibelsToGain (-1.0f) / peak : 1.0f;

    const auto samplesDir = folder.getChildFile (base + " Samples");
    if (! samplesDir.createDirectory())
        return "Could not make " + samplesDir.getFullPathName();

    const int fileRate = (int) std::round (rate);
    juce::FlacAudioFormat flac;
    juce::String regions;
    for (size_t i = 0; i < kept.size(); ++i)
    {
        auto& n = *kept[i];
        const auto name = base + " " + AutoSampleSettings::noteName (n.note) + ".flac";
        const auto file = samplesDir.getChildFile (name);
        const int ch = (int) n.info.channels, frames = (int) n.info.frames;
        juce::AudioBuffer<float> buf (ch, frames);
        for (int c = 0; c < ch; ++c)
            for (int f = 0; f < frames; ++f)
                buf.setSample (c, f, n.data[(size_t) (f * ch + c)] * gain);
        std::unique_ptr<juce::OutputStream> out = file.createOutputStream();
        if (out == nullptr)
            return "Could not write " + file.getFullPathName();
        auto writer = flac.createWriterFor (out, juce::AudioFormatWriterOptions().withSampleRate (fileRate)
                                                     .withNumChannels (ch).withBitsPerSample (16)
                                                     .withQualityOptionIndex (flac.getQualityOptions().size() - 1));
        if (writer == nullptr || ! writer->writeFromAudioSampleBuffer (buf, 0, frames))
            return "Could not write " + file.getFullPathName();
        writer.reset();

        const int lo = i == 0 ? 0 : kept[i - 1]->note + (n.note - kept[i - 1]->note - 1) / 2 + 1;
        const int hi = i + 1 == kept.size() ? 127 : n.note + (kept[i + 1]->note - n.note - 1) / 2;
        const double tail = (double) (n.info.frames - juce::jmin (n.info.frames, n.info.noteOff)) / rate;
        auto line = "<region> sample=" + name + " pitch_keycenter=" + juce::String (n.note) + " lokey=" + juce::String (lo)
                  + " hikey=" + juce::String (hi);
        if (n.info.hasLoop)
            line << " loop_start=" << (juce::int64) n.info.loopStart << " loop_end=" << (juce::int64) n.info.loopEnd - 1
                 << " loop_crossfade=" << seconds ((double) n.info.crossfade / rate);
        else
            line << " loop_mode=no_loop";
        line << " ampeg_release=" << seconds (juce::jmax (0.05, tail), 2);
        regions << line << "\n";
    }

    const auto hold = settings.holdMs();
    juce::String sfz;
    sfz << "// " << base << "\n"
        << "// FM-1Ception AutoSample of " << firmware << (prog.said.isNotEmpty() ? " (" + prog.said.upToFirstOccurrenceOf (". ", false, false) + ")" : juce::String())
        << ", " << juce::Time::getCurrentTime().formatted ("%Y-%m-%d") << "\n"
        << "// every " << settings.span << " semitones from " << AutoSampleSettings::noteName (settings.root) << " to "
        << AutoSampleSettings::noteName (settings.top) << ", velocity " << settings.velocity << ", held "
        << (hold == 0 ? juce::String ("until it settled") : juce::String ((int) hold) + " ms") << "\n\n"
        << "<control> default_path=" << base << " Samples/\n"
        << "<global> ampeg_attack=0.001 amp_veltrack=25 loop_mode=loop_sustain\n\n"
        << regions;
    if (! folder.getChildFile (base + ".sfz").replaceWithText (sfz, false, false, "\n"))
        return "Could not write " + base + ".sfz";
    return {};
}
} // namespace fm1c
