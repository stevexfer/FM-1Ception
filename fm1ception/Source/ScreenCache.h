#pragma once

#include <JuceHeader.h>
#include <deque>
#include <list>
#include <set>

namespace fm1c
{
//==============================================================================
// A firmware's screens, for the library's info panel: its display a moment
// after a fresh boot (kEarlyMs) and once it has settled (kLateMs), captured
// with no engine (fm1e_screenshots) on a thread of its own and kept as PNGs by
// the package's digest, so a copy renamed or moved keeps them. One capture at a
// time: the one asked for last. The FM-1 Firmware Hub's artwork for a firmware
// (its card) is fetched and kept beside them.
//==============================================================================
class ScreenCache : public juce::ChangeBroadcaster,
                    private juce::Thread,
                    private juce::AsyncUpdater
{
public:
    static constexpr juce::uint32 kEarlyMs = 300, kLateMs = 5000;

    /** Screens/ beside the library's database. */
    static juce::File defaultFolder();

    explicit ScreenCache (juce::File folder);
    ~ScreenCache() override;

    struct Shots
    {
        juce::Image early, late;
        /** Why there are none (the last capture failed). */
        juce::String error;
        /** Being captured now, or next. */
        bool capturing = false;
        bool has() const { return early.isValid() || late.isValid(); }
    };
    /** What is kept for `key` (a package's digest). */
    Shots shotsOf (const juce::String& key);

    /** Brings a package's bytes, on the capture thread: "" or why not. */
    using Fetch = std::function<juce::String (juce::MemoryBlock&)>;
    /** Captures the screens of `package` for `key`, unless they are kept (or failed) already and
        not `again`. A change message when they come. */
    void capture (const juce::String& key, const juce::File& package, bool again = false);
    /** As above, the package from `fetch` (the Cloud's, not downloaded). */
    void capture (const juce::String& key, Fetch fetch, bool again = false);

    /** The image at `url` (the Hub's card), kept: null until it has been fetched, then a change
        message. */
    juce::Image cardOf (const juce::String& url);

    /** Its settled screen (else the early one) for a tile, null if none is kept. The last kThumbs
        asked for stay in memory; the rest are read again from disk. */
    juce::Image thumbOf (const juce::String& key);
    static constexpr size_t kThumbs = 160;
    /** What to capture after what capture() asks for, one at a time: the tiles on screen, in
        place of those asked for before and not begun. Those kept (or failed) are left out. */
    void captureInBackground (std::vector<std::pair<juce::String, juce::File>> keysAndPackages);
    /** Its capture failed (it cannot be run here). */
    bool hasFailed (const juce::String& key);
    /** Waiting in the background queue, or being captured from it now. */
    bool isQueued (const juce::String& key);

    /** The captures and fetches asked for, done: for a test, with no message loop. */
    bool waitForIdle (int timeoutMs);
    juce::File getFolder() const { return folder; }

    /** A package's screens at kEarlyMs and kLateMs, now: "" or why none (late may be missing if
        it stopped in between). */
    static juce::String captureNow (const juce::MemoryBlock& package, juce::Image& early, juce::Image& late);

private:
    struct Job
    {
        juce::String key;
        juce::File file;
        Fetch fetch;
    };

    juce::File shotFile (const juce::String& key, bool late) const;
    juce::File failedFile (const juce::String& key) const;
    juce::File cardFile (const juce::String& url) const;
    /** Its screens kept, or why there are none: on disk or in memory. Under `lock`. */
    bool known (const juce::String& key) const;
    void want (Job, bool again);
    void run() override;
    void handleAsyncUpdate() override;

    const juce::File folder;
    juce::CriticalSection lock;
    std::map<juce::String, Shots> shots;
    std::optional<Job> wanted;
    std::deque<Job> background;
    juce::String backgroundNow;
    std::list<std::pair<juce::String, juce::Image>> thumbs;
    std::map<juce::String, juce::Image> cards;
    std::set<juce::String> cardsTried;
    std::deque<juce::String> cardQueue;
    std::atomic<int> busy { 0 };
    juce::WaitableEvent work;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (ScreenCache)
};
} // namespace fm1c
