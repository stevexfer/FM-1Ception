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
    return presets.getChildFile ("Multisamples").getChildFile ("User");
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
    return state;
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
    if (settings.programs)
    {
        const int first = juce::jlimit (1, 127, settings.firstProgram), last = juce::jlimit (first, 127, settings.lastProgram);
        set (Stage::scouting, -1.0, "Finding the programs...");
        const int n = fm1e_sampler_scout (sampler, (juce::uint32) first, (juce::uint32) last, &cancelled, msg, sizeof msg);
        if (cancelled)
            return set (Stage::cancelled, 0.0, "Cancelled");
        if (n < 0)
            return set (Stage::failed, 0.0, juce::String ("Could not step through the programs: ") + juce::String (msg));
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
        set (Stage::listed, 1.0, juce::String ((int) list.size()) + (list.size() == 1 ? " program" : " programs") + " found"
                                     + (quiet ? "" : ". Something plays with no note held (a sequencer?): it will be in the samples"));
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

    int todo = 0, written = 0;
    for (const auto& p : progs)
        todo += p.include ? 1 : 0;
    juce::StringArray skipped, names;
    std::vector<Note> previous;
    int done = 0;
    for (size_t i = 0; i < progs.size(); ++i)
    {
        if (! progs[i].include)
            continue;
        std::vector<Note> notes;
        const auto label = progs.size() > 1 ? progs[i].name : base;
        set (Stage::capturing, (double) done / juce::jmax (1, todo),
             "Capturing " + (label.isEmpty() ? juce::String ("program ") + juce::String ((int) i + 1) : label) + "...");
        if (! renderProgram ((int) i, notes))
        {
            if (! cancelled)
                return false;
            folder.deleteRecursively (true);
            set (Stage::cancelled, 0.0, "Cancelled");
            return false;
        }
        ++done;

        const bool silent = std::all_of (notes.begin(), notes.end(), [] (const Note& n) { return n.info.silent != 0; });
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
        if (silent || (progs.size() > 1 && same (notes)))
        {
            skipped.add (progs[i].name + (silent ? " (silent)" : " (the same as the one before)"));
            continue;
        }

        auto file = progs.size() > 1 ? fileSafe (progs[i].name.isNotEmpty() ? progs[i].name : juce::String ((int) i + 1)) : base;
        for (int k = 2; names.contains (file, true); ++k)
            file = fileSafe (progs[i].name) + " " + juce::String (k);
        names.add (file);
        const auto error = writeProgram (folder, file, progs[i], notes, rate);
        if (error.isNotEmpty())
        {
            set (Stage::failed, 0.0, error);
            return false;
        }
        ++written;
        previous = std::move (notes);
    }

    const juce::ScopedLock sl (lock);
    state.stage = Stage::done;
    state.progress = 1.0;
    state.folder = folder;
    state.written = written;
    state.text = juce::String (written) + (written == 1 ? " SFZ" : " SFZs") + " written"
               + (skipped.isEmpty() ? juce::String() : ", skipped: " + skipped.joinIntoString (", "));
    if (written == 0)
        folder.deleteRecursively (true);
    return true;
}

bool AutoSampler::renderProgram (int program, std::vector<Note>& notes)
{
    const auto list = settings.notes();
    notes.assign ((size_t) list.size(), {});
    for (int k = 0; k < list.size(); ++k)
        notes[(size_t) k].note = list[k];

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
    auto work = [&]
    {
        for (int k; ! failed && ! cancelled && (k = next++) < (int) notes.size();)
        {
            auto& n = notes[(size_t) k];
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
            fm1e_sample_free (smp);
            ++finished;
        }
    };
    const int threads = juce::jlimit (1, 8, (int) std::thread::hardware_concurrency() - 2);
    std::vector<std::thread> pool;
    for (int t = 0; t < juce::jmin (threads, (int) notes.size()); ++t)
        pool.emplace_back (work);
    for (bool running = true; running;)
    {
        running = false;
        juce::Thread::sleep (100);
        if (finished < (int) notes.size() && ! failed && ! cancelled)
            running = true;
        const juce::ScopedLock sl (lock);
        const auto todo = juce::jmax (1, (int) found.size());
        state.progress = juce::jmin (1.0, base + (double) finished / (double) notes.size() / todo);
        if (! running)
            break;
    }
    for (auto& t : pool)
        t.join();
    if (failed && ! cancelled)
        set (Stage::failed, 0.0, "Could not render " + error);
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
                                                     .withNumChannels (ch).withBitsPerSample (24));
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
