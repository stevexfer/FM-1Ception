#include "AutoSampleWindow.h"
#include "Theme.h"

namespace fm1c
{
namespace
{
enum Col { colInclude = 1, colNumber, colName, colSaid };
constexpr int kRow = 30, kGap = 8, kLabelW = 96;

void noteItems (juce::ComboBox& c)
{
    for (int n = 0; n < 128; ++n)
        c.addItem (AutoSampleSettings::noteName (n), n + 1);
}

void programItems (juce::ComboBox& c)
{
    for (int n = 1; n <= 127; ++n)
        c.addItem (juce::String (n), n);
}
} // namespace

//==============================================================================
AutoSampleView::AutoSampleView (std::shared_ptr<EngineHandle> h, juce::String fw, int ch)
    : engine (std::move (h)), firmware (std::move (fw)), channel (ch)
{
    lnf.setColourScheme (juce::LookAndFeel_V4::getMidnightColourScheme());
    lnf.setColour (juce::PopupMenu::backgroundColourId, theme::header);
    lnf.setColour (juce::PopupMenu::textColourId, theme::silk);
    lnf.setColour (juce::PopupMenu::highlightedBackgroundColourId, theme::amber.withAlpha (0.85f));
    lnf.setColour (juce::PopupMenu::highlightedTextColourId, theme::header);
    lnf.setColour (juce::TextButton::buttonColourId, theme::tray);
    lnf.setColour (juce::TextButton::buttonOnColourId, theme::amber);
    lnf.setColour (juce::TextButton::textColourOffId, theme::silk);
    lnf.setColour (juce::TextButton::textColourOnId, theme::header);
    lnf.setColour (juce::ComboBox::backgroundColourId, theme::header);
    lnf.setColour (juce::ComboBox::outlineColourId, theme::tray.brighter (0.2f));
    lnf.setColour (juce::ComboBox::textColourId, theme::silk);
    lnf.setColour (juce::ComboBox::arrowColourId, theme::dimSilk);
    lnf.setColour (juce::TextEditor::backgroundColourId, theme::header);
    lnf.setColour (juce::TextEditor::textColourId, theme::silk);
    lnf.setColour (juce::TextEditor::outlineColourId, theme::tray.brighter (0.2f));
    lnf.setColour (juce::TextEditor::focusedOutlineColourId, theme::amber);
    lnf.setColour (juce::TextEditor::highlightColourId, theme::amber.withAlpha (0.35f));
    lnf.setColour (juce::CaretComponent::caretColourId, theme::amber);
    lnf.setColour (juce::ToggleButton::textColourId, theme::silk);
    lnf.setColour (juce::ToggleButton::tickColourId, theme::amber);
    lnf.setColour (juce::ToggleButton::tickDisabledColourId, theme::dimSilk);
    lnf.setColour (juce::Slider::thumbColourId, theme::amber);
    lnf.setColour (juce::Slider::trackColourId, theme::amber.withAlpha (0.5f));
    lnf.setColour (juce::Slider::backgroundColourId, theme::tray);
    lnf.setColour (juce::Slider::textBoxTextColourId, theme::silk);
    lnf.setColour (juce::Slider::textBoxBackgroundColourId, theme::header);
    lnf.setColour (juce::Slider::textBoxOutlineColourId, theme::tray.brighter (0.2f));
    lnf.setColour (juce::Label::textColourId, theme::silk);
    lnf.setColour (juce::ProgressBar::foregroundColourId, theme::amber);
    lnf.setColour (juce::ProgressBar::backgroundColourId, theme::tray);
    lnf.setColour (juce::ListBox::backgroundColourId, theme::header);
    lnf.setColour (juce::ListBox::outlineColourId, juce::Colours::black);
    lnf.setColour (juce::TableHeaderComponent::backgroundColourId, theme::header);
    lnf.setColour (juce::TableHeaderComponent::textColourId, theme::dimSilk);
    lnf.setColour (juce::TableHeaderComponent::outlineColourId, theme::tray);
    lnf.setColour (juce::ScrollBar::thumbColourId, theme::dimSilk.withAlpha (0.6f));
    setLookAndFeel (&lnf);

    const auto s = AutoSampleSettings::load();
    name.setText (firmware, false);
    name.setTextToShowWhenEmpty (firmware, theme::dimSilk);
    name.onTextChange = [this] { updateSummary(); };

    noteItems (root);
    noteItems (top);
    root.setSelectedId (s.root + 1, juce::dontSendNotification);
    top.setSelectedId (s.top + 1, juce::dontSendNotification);
    for (int st = 1; st <= 24; ++st)
        span.addItem (juce::String (st) + " st", st);
    span.setSelectedId (s.span, juce::dontSendNotification);
    hold.addItemList (AutoSampleSettings::holdNames(), 1);
    hold.setSelectedItemIndex (s.hold, juce::dontSendNotification);
    tempo.setSliderStyle (juce::Slider::LinearBar);
    tempo.setRange (20.0, 400.0, 1.0);
    tempo.setValue (s.tempo, juce::dontSendNotification);
    tempo.setTextValueSuffix (" BPM");
    velocity.setSliderStyle (juce::Slider::LinearBar);
    velocity.setRange (1.0, 127.0, 1.0);
    velocity.setValue (s.velocity, juce::dontSendNotification);
    loops.setToggleState (s.loops, juce::dontSendNotification);
    programs.setToggleState (s.programs, juce::dontSendNotification);
    strip.setToggleState (s.stripNumbers, juce::dontSendNotification);
    programItems (firstProgram);
    programItems (lastProgram);
    firstProgram.setSelectedId (s.firstProgram, juce::dontSendNotification);
    lastProgram.setSelectedId (s.lastProgram, juce::dontSendNotification);

    for (auto* c : { &root, &top, &span, &hold, &firstProgram, &lastProgram })
        c->onChange = [this] { updateSummary(); };
    for (auto* b : { &loops, &programs, &strip })
        b->onClick = [this] { updateSummary(); };
    tempo.onValueChange = [this] { updateSummary(); };

    for (auto* c : std::initializer_list<juce::Component*> { &name, &root, &top, &span, &hold, &tempo, &velocity, &loops,
                                                             &programs, &strip, &firstProgram, &lastProgram, &summary })
        addAndMakeVisible (c);
    for (auto* t : { "Name", "Root", "Top", "Span", "Duration", "Tempo", "Velocity", "Programs", "From", "To" })
        label (t);

    summary.setColour (juce::Label::textColourId, theme::dimSilk);
    summary.setFont (theme::font (13.0f));
    summary.setJustificationType (juce::Justification::topLeft);
    statusText.setFont (theme::font (13.0f));
    statusText.setJustificationType (juce::Justification::topLeft);
    addAndMakeVisible (statusText);
    addChildComponent (bar);

    list.setModel (this);
    list.setRowHeight (24);
    list.setHeaderHeight (24);
    auto& hd = list.getHeader();
    hd.addColumn ("", colInclude, 30, 30, 30, juce::TableHeaderComponent::notResizableOrSortable);
    hd.addColumn ("#", colNumber, 40, 40, 60, juce::TableHeaderComponent::notResizableOrSortable);
    hd.addColumn ("NAME", colName, 220, 80, 600, juce::TableHeaderComponent::notSortable);
    hd.addColumn ("WHAT THE FIRMWARE SAID", colSaid, 360, 80, 2000, juce::TableHeaderComponent::notSortable);
    addChildComponent (list);

    startButton.onClick = [this]
    {
        if (job != nullptr && job->status().stage == AutoSampler::Stage::listed)
            captureListed();
        else
            start();
    };
    cancelButton.onClick = [this] { stop(); };
    revealButton.setButtonText (juce::SystemStats::getOperatingSystemType() & juce::SystemStats::Windows ? "Show in Explorer"
                                                                                                         : "Show in Finder");
    revealButton.onClick = [this]
    {
        if (job != nullptr)
        {
            const auto f = job->status().folder;
            (f.exists() ? f : AutoSampleSettings::serumFolder()).revealToUser();
        }
    };
    addAndMakeVisible (startButton);
    addChildComponent (cancelButton);
    addChildComponent (revealButton);

    updateSummary();
    setSize (680, 560);
}

AutoSampleView::~AutoSampleView()
{
    stopTimer();
    list.setModel (nullptr);
    job.reset();
    setLookAndFeel (nullptr);
}

juce::Label& AutoSampleView::label (const juce::String& text)
{
    auto* l = labels.add (new juce::Label (text, text));
    l->setFont (theme::font (13.0f));
    l->setColour (juce::Label::textColourId, theme::dimSilk);
    l->setJustificationType (juce::Justification::centredRight);
    addAndMakeVisible (l);
    return *l;
}

AutoSampleSettings AutoSampleView::settings() const
{
    AutoSampleSettings s;
    s.root = root.getSelectedId() - 1;
    s.top = top.getSelectedId() - 1;
    s.span = juce::jmax (1, span.getSelectedId());
    s.hold = juce::jmax (0, hold.getSelectedItemIndex());
    s.tempo = tempo.getValue();
    s.velocity = (int) velocity.getValue();
    s.loops = loops.getToggleState();
    s.programs = programs.getToggleState();
    s.firstProgram = firstProgram.getSelectedId();
    s.lastProgram = juce::jmax (s.firstProgram, lastProgram.getSelectedId());
    s.stripNumbers = strip.getToggleState();
    s.name = name.getText().trim().isNotEmpty() ? name.getText().trim() : firmware;
    s.channel = channel;
    return s;
}

void AutoSampleView::updateSummary()
{
    const auto s = settings();
    const auto notes = s.notes();
    juce::StringArray names;
    for (int n : notes)
        names.add (AutoSampleSettings::noteName (n));
    const auto ms = s.holdMs();
    auto text = juce::String (notes.size()) + (notes.size() == 1 ? " note: " : " notes: ") + names.joinIntoString (" ")
              + "\nHeld " + (ms == 0 ? "until each settles (steady for 2 s, at most "
                                           + juce::String ((int) AutoSampleSettings::kMaxHoldMs / 1000) + " s)"
                                     : juce::String ((int) ms) + " ms")
              + ", then its release until quiet, on MIDI channel " + juce::String (channel) + "."
              + "\nTo " + AutoSampleSettings::serumFolder().getChildFile (AutoSampler::fileSafe (s.name)).getFullPathName();
    summary.setText (text, juce::dontSendNotification);
    tempo.setEnabled (ms != 0);
    for (auto* c : { &firstProgram, &lastProgram })
        c->setEnabled (s.programs);
    strip.setEnabled (s.programs);
}

void AutoSampleView::paint (juce::Graphics& g)
{
    g.fillAll (theme::room);
}

void AutoSampleView::resized()
{
    auto r = getLocalBounds().reduced (16);
    auto row = [&r] { auto x = r.removeFromTop (kRow); r.removeFromTop (kGap); return x; };
    int li = 0;
    auto put = [this, &li] (juce::Rectangle<int>& x, juce::Component& c, int w)
    {
        labels[li++]->setBounds (x.removeFromLeft (kLabelW).withTrimmedRight (8));
        c.setBounds (x.removeFromLeft (w));
        x.removeFromLeft (12);
    };

    auto a = row();
    put (a, name, a.getWidth() - kLabelW);
    auto b = row();
    put (b, root, 90);
    labels[li++]->setBounds (b.removeFromLeft (50).withTrimmedRight (8));
    top.setBounds (b.removeFromLeft (90));
    b.removeFromLeft (12);
    labels[li++]->setBounds (b.removeFromLeft (50).withTrimmedRight (8));
    span.setBounds (b.removeFromLeft (90));
    auto c = row();
    put (c, hold, 160);
    labels[li++]->setBounds (c.removeFromLeft (60).withTrimmedRight (8));
    tempo.setBounds (c.removeFromLeft (120));
    auto d = row();
    put (d, velocity, 160);
    auto e = row();
    e.removeFromLeft (kLabelW);
    loops.setBounds (e.removeFromLeft (200));
    strip.setBounds (e.removeFromLeft (280));
    auto f = row();
    labels[li++]->setBounds (f.removeFromLeft (kLabelW).withTrimmedRight (8));
    programs.setBounds (f.removeFromLeft (210));
    labels[li++]->setBounds (f.removeFromLeft (50).withTrimmedRight (8));
    firstProgram.setBounds (f.removeFromLeft (70));
    labels[li++]->setBounds (f.removeFromLeft (36).withTrimmedRight (8));
    lastProgram.setBounds (f.removeFromLeft (70));

    r.removeFromTop (4);
    summary.setBounds (r.removeFromTop (54).withTrimmedLeft (kLabelW));

    auto buttons = r.removeFromBottom (32);
    startButton.setBounds (buttons.removeFromRight (170));
    buttons.removeFromRight (8);
    cancelButton.setBounds (buttons.removeFromRight (100));
    revealButton.setBounds (buttons.removeFromLeft (150));
    r.removeFromBottom (10);
    auto st = r.removeFromBottom (44);
    bar.setBounds (st.removeFromTop (16));
    statusText.setBounds (st.withTrimmedTop (4));
    r.removeFromBottom (8);
    list.setBounds (r);
}

void AutoSampleView::start()
{
    const auto s = settings();
    s.save();
    rows.clear();
    list.updateContent();
    list.setVisible (false);
    listShown = false;
    job = std::make_unique<AutoSampler> (engine, s, firmware);
    startButton.setEnabled (false);
    cancelButton.setVisible (true);
    revealButton.setVisible (false);
    bar.setVisible (true);
    startTimerHz (10);
    timerCallback();
}

void AutoSampleView::captureListed()
{
    job->capture (rows);
    startButton.setEnabled (false);
    list.setEnabled (false);
}

void AutoSampleView::stop()
{
    if (job != nullptr)
        job->cancel();
}

void AutoSampleView::timerCallback()
{
    if (job == nullptr)
        return;
    using Stage = AutoSampler::Stage;
    const auto st = job->status();
    progress = st.progress;
    statusText.setText (st.text, juce::dontSendNotification);
    statusText.setColour (juce::Label::textColourId, st.stage == Stage::failed ? theme::warn : theme::silk);

    if (st.stage == Stage::listed && ! listShown)
    {
        listShown = true;
        rows = job->programs();
        list.updateContent();
        list.setVisible (true);
        list.setEnabled (true);
        startButton.setEnabled (! rows.empty());
        startButton.setButtonText ("Capture " + juce::String ((int) rows.size()) + (rows.size() == 1 ? " Program" : " Programs"));
    }
    const bool over = st.stage == Stage::done || st.stage == Stage::failed || st.stage == Stage::cancelled;
    if (over)
    {
        stopTimer();
        bar.setVisible (st.stage == Stage::done);
        cancelButton.setVisible (false);
        startButton.setEnabled (true);
        startButton.setButtonText ("Start");
        list.setEnabled (false);
        revealButton.setVisible (st.stage == Stage::done && st.written > 0);
    }
}

//==============================================================================
int AutoSampleView::getNumRows() { return (int) rows.size(); }

void AutoSampleView::paintRowBackground (juce::Graphics& g, int row, int, int, bool)
{
    g.fillAll (row % 2 ? theme::header : theme::room);
}

void AutoSampleView::paintCell (juce::Graphics& g, int row, int column, int w, int h, bool)
{
    if (! juce::isPositiveAndBelow (row, (int) rows.size()))
        return;
    const auto& p = rows[(size_t) row];
    auto r = juce::Rectangle<int> (w, h).reduced (6, 0);
    if (column == colInclude)
    {
        const auto box = juce::Rectangle<float> (14.0f, 14.0f).withCentre (r.toFloat().getCentre());
        g.setColour (theme::dimSilk);
        g.drawRoundedRectangle (box, 2.0f, 1.0f);
        if (p.include)
        {
            g.setColour (theme::amber);
            g.fillRoundedRectangle (box.reduced (3.0f), 1.0f);
        }
        return;
    }
    g.setFont (theme::font (13.0f));
    g.setColour (p.include ? (column == colSaid ? theme::dimSilk : theme::silk) : theme::dimSilk.withAlpha (0.5f));
    if (column == colNumber)
        g.drawText (juce::String (settings().firstProgram + row), r, juce::Justification::centredLeft);
    else if (column == colSaid)
        g.drawText (p.said.isEmpty() ? juce::String ("(nothing)") : p.said, r, juce::Justification::centredLeft, true);
}

juce::Component* AutoSampleView::refreshComponentForCell (int row, int column, bool, juce::Component* existing)
{
    if (column != colName)
    {
        delete existing;
        return nullptr;
    }
    auto* l = dynamic_cast<juce::Label*> (existing);
    if (l == nullptr)
    {
        delete existing;
        l = new juce::Label();
        l->setEditable (false, true, false);
        l->setFont (theme::font (13.0f));
        l->setColour (juce::Label::textColourId, theme::silk);
        l->setColour (juce::Label::textWhenEditingColourId, theme::silk);
        l->setColour (juce::Label::backgroundWhenEditingColourId, theme::header);
    }
    l->getProperties().set ("row", row);
    l->setText (juce::isPositiveAndBelow (row, (int) rows.size()) ? rows[(size_t) row].name : juce::String(), juce::dontSendNotification);
    l->onTextChange = [this, l]
    {
        const int r = l->getProperties()["row"];
        if (juce::isPositiveAndBelow (r, (int) rows.size()))
            rows[(size_t) r].name = l->getText().trim();
    };
    return l;
}

void AutoSampleView::cellClicked (int row, int column, const juce::MouseEvent&)
{
    if (column != colInclude || ! juce::isPositiveAndBelow (row, (int) rows.size()) || ! list.isEnabled())
        return;
    rows[(size_t) row].include = ! rows[(size_t) row].include;
    int n = 0;
    for (const auto& p : rows)
        n += p.include ? 1 : 0;
    startButton.setEnabled (n > 0);
    startButton.setButtonText ("Capture " + juce::String (n) + (n == 1 ? " Program" : " Programs"));
    list.repaintRow (row);
}

//==============================================================================
AutoSampleWindow::AutoSampleWindow (std::shared_ptr<EngineHandle> h, const juce::String& fw, int channel, const juce::String& title)
    : juce::DocumentWindow (title, theme::room, juce::DocumentWindow::closeButton | juce::DocumentWindow::minimiseButton, true)
{
    setUsingNativeTitleBar (true);
    setContentOwned (new AutoSampleView (std::move (h), fw, channel), true);
    setResizable (true, false);
    setResizeLimits (620, 480, 4000, 3000);
    centreWithSize (getWidth(), getHeight());
    setVisible (true);
    toFront (true);
}

void AutoSampleWindow::closeButtonPressed()
{
    view().settings().save();
    if (onClose)
        onClose();
}
} // namespace fm1c
