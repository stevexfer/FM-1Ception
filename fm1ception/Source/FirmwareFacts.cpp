#include "FirmwareFacts.h"
#include "FM1CeptionData.h"
#include "Theme.h"

namespace fm1c
{
namespace
{
juce::String text (const juce::var& o, const char* name)
{
    const auto v = o[name];
    return v.isVoid() || v.isUndefined() ? juce::String() : v.toString();
}

juce::StringArray strings (const juce::var& v)
{
    juce::StringArray out;
    if (const auto* a = v.getArray())
        for (const auto& s : *a)
            out.add (s.toString());
    return out;
}

FirmwareFacts::Facts parse (const juce::var& o)
{
    FirmwareFacts::Facts f;
    f.repo = text (o, "repo");
    f.commit = text (o, "commit");
    f.committed = text (o, "committed");
    f.created = text (o, "created");
    f.reviewed = (bool) o["reviewed"];
    f.summary = text (o, "summary");
    f.original = (bool) o["original"];
    if (const auto b = o["base"]; b.isObject())
        f.base = FirmwareFacts::Base { text (b, "repo"), text (b, "name"), text (b, "how"), text (b, "confidence"), text (b, "evidence") };
    f.hardware = text (o, "hardware");
    f.hardwareNote = text (o, "hardware_note");
    if (const auto* a = o["engines"].getArray())
        for (const auto& e : *a)
            f.engines.push_back ({ text (e, "name"), text (e, "kind"), text (e, "origin"), text (e, "evidence"), text (e, "confidence") });
    if (const auto* a = o["origins"].getArray())
        for (const auto& e : *a)
            f.origins.push_back ({ text (e, "project"), text (e, "author"), text (e, "license"), text (e, "what"), text (e, "how"),
                                   text (e, "evidence"), text (e, "confidence"), (bool) e["fm1"] });
    f.techniques = strings (o["techniques"]);
    f.assets = text (o, "assets");
    if (const auto* a = o["findings"].getArray())
        for (const auto& e : *a)
            f.findings.push_back ({ text (e, "kind"), text (e, "text"), text (e, "evidence"), text (e, "confidence") });
    f.license = text (o, "license");
    f.midi = strings (o["midi"]);
    if (const auto* langs = o["languages"].getDynamicObject())
        for (const auto& p : langs->getProperties())
            f.languages.push_back ({ p.name.toString(), (int) p.value });
    std::stable_sort (f.languages.begin(), f.languages.end(), [] (const auto& a, const auto& b) { return a.second > b.second; });
    return f;
}

/** "Mutable Instruments Plaits (eurorack)" -> "Mutable Instruments Plaits": names short enough for a row. */
juce::String shortName (const juce::String& project)
{
    auto s = project.upToFirstOccurrenceOf (" (", false, false).trim();
    return s.isNotEmpty() ? s : project;
}

juce::String howBase (const juce::String& how)
{
    if (how == "fork")      return "a GitHub fork";
    if (how == "copy")      return "its code copied in";
    if (how == "submodule") return "a git submodule";
    if (how == "stated")    return "as its documents say";
    if (how == "code")      return "as its code shows";
    if (how == "listed")    return "as mutant.cloud lists it";
    if (how == "template")  return "its starter template";
    return how;
}

juce::String howOrigin (const juce::String& how)
{
    if (how == "code")      return "its code";
    if (how == "port")      return "ported";
    if (how == "credited")  return "credited";
    if (how == "technique") return "its design";
    return how;
}

juce::String sureness (const juce::String& confidence)
{
    if (confidence == "high")   return "high confidence";
    if (confidence == "medium") return "medium confidence";
    if (confidence == "low")    return "low confidence: a lead";
    return {};
}

juce::String kindName (const juce::String& kind)
{
    if (kind == "ai")         return "AI tools";
    if (kind == "licence")    return "licence";
    if (kind == "uncredited") return "uncredited code";
    return "notes";
}
} // namespace

//==============================================================================
FirmwareFacts::FirmwareFacts (const juce::String& json)
{
    const auto root = juce::JSON::parse (json);
    when = text (root, "scanned");
    if (const auto* all = root["firmwares"].getDynamicObject())
        for (const auto& p : all->getProperties())
            byRepo.emplace (p.name.toString(), parse (p.value));
}

const FirmwareFacts& FirmwareFacts::get()
{
    static const FirmwareFacts facts { juce::String::fromUTF8 (FM1CeptionData::FirmwareFacts_json, FM1CeptionData::FirmwareFacts_jsonSize) };
    return facts;
}

juce::String FirmwareFacts::keyOf (const juce::String& repo)
{
    auto s = repo.trim();
    if (s.contains ("://"))
        s = s.fromFirstOccurrenceOf ("://", false, false);
    if (s.startsWithIgnoreCase ("www."))
        s = s.substring (4);
    if (s.startsWithIgnoreCase ("github.com/"))
        s = s.substring (11);
    else if (s.containsChar ('.') && s.upToFirstOccurrenceOf ("/", false, false).containsChar ('.'))
        return {}; // another host
    juce::StringArray parts;
    parts.addTokens (s.upToFirstOccurrenceOf ("?", false, false).upToFirstOccurrenceOf ("#", false, false), "/", {});
    parts.removeEmptyStrings();
    if (parts.size() < 2)
        return {};
    auto name = parts[1];
    if (name.endsWithIgnoreCase (".git"))
        name = name.dropLastCharacters (4);
    return (parts[0] + "/" + name).toLowerCase();
}

const FirmwareFacts::Facts* FirmwareFacts::of (const juce::String& repo) const
{
    const auto k = keyOf (repo);
    if (k.isEmpty())
        return nullptr;
    const auto it = byRepo.find (k);
    return it != byRepo.end() ? &it->second : nullptr;
}

//==============================================================================
juce::String FirmwareFacts::Facts::builtOn() const
{
    if (base.has_value() && base->name.isNotEmpty())
        return base->name + (base->how == "fork" ? " (a fork)" : base->how == "template" ? " (template)" : "");
    return original ? juce::String ("Its own code") : juce::String();
}

juce::String FirmwareFacts::Facts::sound() const
{
    std::vector<std::pair<juce::String, int>> kinds;
    for (const auto& e : engines)
    {
        if (e.kind.isEmpty())
            continue;
        auto it = std::find_if (kinds.begin(), kinds.end(), [&e] (const auto& k) { return k.first == e.kind; });
        if (it == kinds.end())
            kinds.push_back ({ e.kind, 1 });
        else
            ++it->second;
    }
    std::stable_sort (kinds.begin(), kinds.end(), [] (const auto& a, const auto& b) { return a.second > b.second; });
    juce::StringArray out;
    for (const auto& [k, n] : kinds)
        if (k != "other" || kinds.size() == 1)
            out.add (k);
    return out.joinIntoString (", ");
}

juce::String FirmwareFacts::Facts::codeFrom() const
{
    juce::StringArray out;
    for (const auto& o : origins)
        if ((o.how == "code" || o.how == "port") && ! o.fm1)
            out.addIfNotAlreadyThere (shortName (o.project));
    return out.joinIntoString (", ");
}

juce::String FirmwareFacts::Facts::findingKinds() const
{
    juce::StringArray out;
    for (const auto& f : findings)
        out.addIfNotAlreadyThere (kindName (f.kind));
    return out.joinIntoString (", ");
}

juce::String FirmwareFacts::Facts::searchText() const
{
    juce::StringArray s { summary, builtOn(), hardware, assets };
    for (const auto& e : engines)
        s.addArray ({ e.name, e.kind, e.origin });
    for (const auto& o : origins)
        s.addArray ({ o.project, o.author });
    s.addArray (techniques);
    return s.joinIntoString (" ");
}

juce::AttributedString FirmwareFacts::Facts::describe() const
{
    juce::AttributedString s;
    s.setWordWrap (juce::AttributedString::byWord);
    const auto body = theme::font (12.5f), bold = theme::font (12.5f, true), small = theme::font (11.0f),
               head = theme::font (10.5f, true);
    bool first = true;
    auto heading = [&] (const juce::String& h)
    {
        s.append ((first ? "" : "\n\n") + h.toUpperCase() + "\n", head, theme::amber);
        first = false;
    };
    // a short empty line between one item and the next
    auto gap = [&] { s.append ("\n\n", theme::font (5.0f), theme::silk); };
    auto line = [&] (const juce::String& t, const juce::String& evidence, const juce::String& confidence)
    {
        s.append (t, body, theme::silk);
        juce::StringArray dim;
        if (evidence.isNotEmpty())
            dim.add (evidence);
        if (const auto c = sureness (confidence); c.isNotEmpty())
            dim.add (c);
        if (! dim.isEmpty())
            s.append ("\n" + dim.joinIntoString ("  -  "), small, theme::dimSilk);
    };

    s.append (repo + "\n", bold, theme::silk);
    s.append ("Read at commit " + commit.substring (0, 7) + (committed.isNotEmpty() ? " of " + committed : juce::String())
                  + (reviewed ? ", by hand and by its automatic scan" : ", by its automatic scan only")
                  + (created.isNotEmpty() ? ". Its repository was created " + created + "." : juce::String (".")),
              small, theme::dimSilk);
    first = false;
    if (summary.isNotEmpty())
        s.append ("\n\n" + summary, body, theme::silk);

    heading ("Built on");
    if (base.has_value())
        line (base->name + (base->repo.isNotEmpty() ? "  (" + base->repo + ")" : juce::String()) + ", " + howBase (base->how),
              base->evidence, base->confidence);
    else
        s.append (original ? "Its own code" : "Not known", body, theme::silk);
    if (hardware.isNotEmpty())
    {
        s.append ("\nHardware layer: " + hardware, body, theme::silk);
        if (hardwareNote.isNotEmpty())
            s.append ("\n" + hardwareNote, small, theme::dimSilk);
    }

    if (! engines.empty())
    {
        heading ("Engines");
        for (size_t i = 0; i < engines.size(); ++i)
        {
            const auto& e = engines[i];
            if (i > 0)
                gap();
            s.append (e.name, bold, theme::silk);
            s.append ("  " + e.kind + (e.origin.isNotEmpty() && e.origin != "own" ? ", from " + e.origin : juce::String()), body, theme::silk);
            if (e.evidence.isNotEmpty())
                s.append ("\n" + e.evidence, small, theme::dimSilk);
        }
    }

    if (! origins.empty())
    {
        heading ("Outside code and sources");
        for (size_t i = 0; i < origins.size(); ++i)
        {
            const auto& o = origins[i];
            if (i > 0)
                gap();
            s.append (o.project, bold, theme::silk);
            juce::StringArray by;
            if (o.author.isNotEmpty())
                by.add ("by " + o.author);
            if (o.license.isNotEmpty())
                by.add (o.license);
            by.add (howOrigin (o.how));
            s.append ("  " + by.joinIntoString (", ") + "\n", body, theme::silk);
            line (o.what, o.evidence, o.confidence);
        }
    }

    if (! techniques.isEmpty())
    {
        heading ("Techniques");
        s.append (techniques.joinIntoString (", "), body, theme::silk);
    }
    if (assets.isNotEmpty())
    {
        heading ("Assets");
        s.append (assets, body, theme::silk);
    }
    if (! findings.empty())
    {
        heading ("Findings");
        for (size_t i = 0; i < findings.size(); ++i)
        {
            const auto& f = findings[i];
            if (i > 0)
                gap();
            s.append (kindName (f.kind).toUpperCase() + "  ", small, f.kind == "licence" || f.kind == "uncredited" ? theme::warn : theme::dimSilk);
            line (f.text, f.evidence, f.confidence);
        }
    }

    heading ("Code");
    juce::StringArray langs;
    for (const auto& [lang, lines] : languages)
        if (lines >= 100)
            langs.add (lang + " " + (lines >= 10000 ? juce::String (lines / 1000) + "k" : juce::String (lines)) + " lines");
    juce::StringArray code;
    code.add (license.isNotEmpty() ? license : juce::String ("no licence GitHub recognises"));
    if (! langs.isEmpty())
        code.add (langs.joinIntoString (", "));
    if (! midi.isEmpty())
        code.add ("MIDI: " + midi.joinIntoString (", "));
    s.append (code.joinIntoString ("\n"), body, theme::silk);
    s.append ("\n\nFindings from reading its source, each with where it was found; confidence says how sure.", small, theme::dimSilk);
    return s;
}
} // namespace fm1c
