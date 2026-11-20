#pragma once

#include <JuceHeader.h>
#include "EngineHandle.h"

namespace fm1c
{
//==============================================================================
// AutoSample: an engine's sound as an SFZ multisample (engine/src/autosample.rs
// renders the notes). The notes go from Root to Top every Span semitones (and Top
// itself), each held for a time or until it settles, its release recorded after.
// Each program is one SFZ: its samples normalised together to -1 dB peak, as 24-bit
// FLAC at the firmware's own rate, mono where left and right are the same, each
// sample's zone centred on it, one line per region. A run goes in a folder of its
// own in Serum 2's Multisamples/FM-1 (macOS: /Library/Audio/Presets/Xfer Records/Serum 2
// Presets; Windows: Documents\Xfer\Serum 2 Presets).
//==============================================================================
struct AutoSampleSettings
{
    int root = 24, top = 84, span = 7;   // C0, C5 (C3 = 60)
    int velocity = 127;
    int hold = 0;                        // an index into holdNames(): 0 until it settles
    double tempo = 120.0;
    bool loops = true;
    bool programs = false;
    int firstProgram = 1, lastProgram = 127;
    bool stripNumbers = true;
    juce::String name;
    int channel = 1;                     // the MIDI channel the firmware hears the notes on
    juce::File parent;                   // where the run's folder goes (none: serumFolder())

    juce::Array<int> notes() const;
    /** 0: until it settles. */
    juce::uint32 holdMs() const;

    static juce::StringArray holdNames();
    /** "C3" for 60, "C-2" for 0. */
    static juce::String noteName (int note);
    static juce::File serumFolder();

    /** The window's last settings (the name aside), in AutoSample.json beside the firmware
        settings' folder. */
    static AutoSampleSettings load();
    void save() const;
    static constexpr juce::uint32 kMaxHoldMs = 10000, kMaxTailMs = 10000;
};

class AutoSampler : private juce::Thread
{
public:
    struct Program
    {
        juce::String said, name;
        bool include = true;
    };

    enum class Stage { starting, scouting, listed, capturing, done, failed, cancelled };

    struct Status
    {
        Stage stage = Stage::starting;
        double progress = 0.0;    // 0..1, -1 not known
        juce::String text;
        juce::File folder;        // done: where the run went
        int written = 0;          // done: programs written
    };

    /** Starts at once: takes the engine's machine, then (with Multiple Programs) finds the
        programs and waits at Stage::listed for capture(); else captures straight away. */
    AutoSampler (std::shared_ptr<EngineHandle>, AutoSampleSettings, juce::String firmwareName);
    ~AutoSampler() override;

    Status status() const;
    /** The programs found (Stage::listed on), named as the settings say. */
    std::vector<Program> programs() const;
    /** At Stage::listed: capture these (the same order as programs(), names as edited). */
    void capture (std::vector<Program>);
    void cancel();

    /** A name made safe for a file. */
    static juce::String fileSafe (const juce::String&);

private:
    struct Note
    {
        int note = 0;
        Fm1eSampleInfo info {};
        std::vector<float> data;
    };

    void run() override;
    bool capturePrograms();
    bool renderProgram (int program, std::vector<Note>&);
    juce::String writeProgram (const juce::File& folder, const juce::String& base, const Program&,
                               std::vector<Note>&, double rate);
    void set (Stage, double progress, const juce::String& text);

    std::shared_ptr<EngineHandle> engine;
    const AutoSampleSettings settings;
    const juce::String firmware;
    Fm1eSampler* sampler = nullptr;
    std::atomic<bool> cancelled { false };
    juce::WaitableEvent go;

    mutable juce::CriticalSection lock;
    Status state;
    std::vector<Program> found;

    JUCE_DECLARE_NON_COPYABLE (AutoSampler)
};
} // namespace fm1c
