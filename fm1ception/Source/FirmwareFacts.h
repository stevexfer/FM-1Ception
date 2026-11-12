#pragma once

#include <JuceHeader.h>

namespace fm1c
{
//==============================================================================
// What is known of a firmware's source that won't change: what it is built on,
// where its engines and DSP come from, the outside code it holds, and a few
// findings, each with where it was found and how sure. Read from each
// firmware's repository at one commit (fm1ception/facts/), then built in
// (Resources/FirmwareFacts.json). A firmware is found by its repository.
//==============================================================================
class FirmwareFacts
{
public:
    struct Base { juce::String repo, name, how, confidence, evidence; };
    struct Engine { juce::String name, kind, origin, evidence, confidence; };
    struct Origin
    {
        juce::String project, author, license, what, how, evidence, confidence;
        /** Another FM-1 firmware or platform (its lineage), not outside code. */
        bool fm1 = false;
    };
    struct Finding { juce::String kind, text, evidence, confidence; };

    struct Facts
    {
        juce::String repo, commit, committed, created;
        /** A person read it: the summary, engines and techniques are a review's only. */
        bool reviewed = false;
        juce::String summary;
        /** Its own code, built on no other firmware (a hardware layer aside). */
        bool original = false;
        std::optional<Base> base;
        /** Its hardware layer: "fm1-base", "felucca-bsp", "fm1_open", "own", ...; "" not known. The note says more
            ("as SLOOP carries it, in firmware/hal/"). */
        juce::String hardware, hardwareNote;
        std::vector<Engine> engines;
        std::vector<Origin> origins;
        juce::StringArray techniques;
        juce::String assets;
        std::vector<Finding> findings;
        juce::String license;
        juce::StringArray midi;
        /** Its source lines by language, most first. */
        std::vector<std::pair<juce::String, int>> languages;

        /** "Felucca (a fork)", "Dinghy (template)", "Its own code", "" for not known. */
        juce::String builtOn() const;
        /** Its engines' kinds, most engines first ("FM, samples"). */
        juce::String sound() const;
        /** The outside projects its code holds or ports ("Mutable Instruments Plaits, msfa"). */
        juce::String codeFrom() const;
        /** Its findings' kinds ("AI tools, licence"). */
        juce::String findingKinds() const;
        /** All of it, for search. */
        juce::String searchText() const;
        /** All of it laid out to read, with the evidence. */
        juce::AttributedString describe() const;
    };

    /** The built-in database, read once. */
    static const FirmwareFacts& get();

    /** One from its JSON (as Resources/FirmwareFacts.json holds). */
    explicit FirmwareFacts (const juce::String& json);

    /** A repository's: "https://github.com/Owner/Name", "github.com/owner/name/tree/x", "owner/name". */
    const Facts* of (const juce::String& repo) const;
    /** "owner/name" (lowercase) of a GitHub repository's URL, "" for none. */
    static juce::String keyOf (const juce::String& repo);

    int size() const { return (int) byRepo.size(); }
    /** The day the repositories were read. */
    juce::String scanned() const { return when; }

private:
    std::map<juce::String, Facts> byRepo;
    juce::String when;

    JUCE_DECLARE_NON_COPYABLE (FirmwareFacts)
};
} // namespace fm1c
