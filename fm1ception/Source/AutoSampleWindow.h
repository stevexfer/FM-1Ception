#pragma once

#include "AutoSampler.h"

namespace fm1c
{
//==============================================================================
// The engine menu's AutoSample...: the notes (Root, Top, Span), how long each is
// held (Duration at Tempo), Velocity, loops, the programs, the name. Start takes
// the engine as it is now; with Capture Multiple Programs it lists the programs
// the PRESETS knob reaches, named by the firmware's screen reader where it has
// one, to untick or rename before Capture. The run goes to Serum 2's
// Multisamples/FM-1 folder (AutoSampler).
//==============================================================================
class AutoSampleView : public juce::Component,
                       private juce::TableListBoxModel,
                       private juce::Timer
{
public:
    AutoSampleView (std::shared_ptr<EngineHandle>, juce::String firmwareName, int channel);
    ~AutoSampleView() override;

    void paint (juce::Graphics&) override;
    void resized() override;

    /** For the smoke test: the settings as the controls show them, and a run started with them. */
    AutoSampleSettings settings() const;
    AutoSampler* sampler() { return job.get(); }
    void start();

private:
    int getNumRows() override;
    void paintRowBackground (juce::Graphics&, int row, int w, int h, bool selected) override;
    void paintCell (juce::Graphics&, int row, int column, int w, int h, bool selected) override;
    juce::Component* refreshComponentForCell (int row, int column, bool selected, juce::Component* existing) override;
    void cellClicked (int row, int column, const juce::MouseEvent&) override;
    void timerCallback() override;

    void showing();
    void captureListed();
    void stop();
    void updateSummary();
    juce::Label& label (const juce::String&);

    juce::LookAndFeel_V4 lnf;
    std::shared_ptr<EngineHandle> engine;
    const juce::String firmware;
    const int channel;

    juce::OwnedArray<juce::Label> labels;
    juce::TextEditor name;
    juce::ComboBox root, top, span, hold, firstProgram, lastProgram;
    juce::Slider tempo, velocity;
    juce::ToggleButton loops { "Generate Loop Points" }, programs { "Capture Multiple Programs" },
                       strip { "Strip Preset Numbers (if present)" };
    juce::Label summary, statusText;
    double progress = 0.0;
    juce::ProgressBar bar { progress };
    juce::TableListBox list;
    juce::TextButton startButton { "Start" }, cancelButton { "Cancel" }, revealButton;

    std::unique_ptr<AutoSampler> job;
    std::vector<AutoSampler::Program> rows;
    bool listShown = false;

    JUCE_DECLARE_NON_COPYABLE (AutoSampleView)
};

class AutoSampleWindow : public juce::DocumentWindow
{
public:
    AutoSampleWindow (std::shared_ptr<EngineHandle>, const juce::String& firmwareName, int channel, const juce::String& title);
    void closeButtonPressed() override;
    AutoSampleView& view() { return *static_cast<AutoSampleView*> (getContentComponent()); }

    std::function<void()> onClose;

private:
    JUCE_DECLARE_NON_COPYABLE (AutoSampleWindow)
};
} // namespace fm1c
