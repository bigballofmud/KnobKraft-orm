#define DOCTEST_CONFIG_IMPLEMENT
#include "doctest/doctest.h"

#include "The-Orm/KnobPages.h"
#include "The-Orm/PatchCopyName.h"
#include "The-Orm/PatchEditSession.h"
#include "The-Orm/PatchParameterViews.h"

#include "KawaiK3.h"
#include "MKS80.h"
#include "Matrix1000.h"
#include "Rev2.h"
#include "Settings.h"

#include <cctype>
#include <map>
#include <set>

int main(int argc, char** argv) {
	juce::ScopedJuceInitialiser_GUI gui;
	Settings::setSettingsID("KnobKraftPatchParameterTests");
	const auto result = doctest::Context(argc, argv).run();
	Settings::shutdown();
	return result;
}

namespace {

	std::map<std::string, int> valuesById(midikraft::PatchParameters const& parameters) {
		std::map<std::string, int> result;
		for (auto const& parameter : parameters) result[parameter.id] = parameter.value;
		return result;
	}

	// Gives every readable parameter a legal value, so patches made from zeros are valid
	std::shared_ptr<midikraft::DataFile> legalPatch(std::shared_ptr<midikraft::Synth> synth, size_t size) {
		auto patch = synth->patchFromPatchData(midikraft::Synth::PatchData(size, 0), MidiProgramNumber::fromZeroBase(0));
		auto detailed = midikraft::Capability::hasCapability<midikraft::DetailedParametersCapability>(patch);
		REQUIRE(detailed);
		for (auto const& definition : detailed->allParameterDefinitions()) {
			auto intParameter = patch_parameters::detail::editableInt(definition);
			if (intParameter && intParameter->minValue() > 0) intParameter->setInPatch(*patch, intParameter->minValue());
		}
		return patch;
	}

	// Sets each editable parameter to an extreme value and checks that exactly that parameter changed
	void checkEveryParameterEditsAlone(std::shared_ptr<midikraft::Synth> synth, size_t size) {
		auto original = legalPatch(synth, size);
		auto originalBytes = original->data();
		auto parameters = patch_parameters::parametersFor(synth, original);
		REQUIRE(!parameters.empty());
		auto before = valuesById(parameters);
		int edited = 0;
		for (auto const& parameter : parameters) {
			if (!parameter.editable) continue;
			REQUIRE(parameter.minValue);
			REQUIRE(parameter.maxValue);
			if (*parameter.minValue == *parameter.maxValue) continue;
			int newValue = parameter.value != *parameter.maxValue ? *parameter.maxValue : *parameter.minValue;
			CAPTURE(parameter.id);
			CAPTURE(newValue);
			auto changed = patch_parameters::applyNativeValue(synth, original, MidiProgramNumber::fromZeroBase(0), parameter.id, newValue);
			REQUIRE(changed);
			auto after = valuesById(patch_parameters::parametersFor(synth, changed));
			CHECK(after[parameter.id] == newValue);
			for (auto const& [id, value] : before) {
				if (id == parameter.id) continue;
				// Some synths name one byte twice (the Rev2's Seq Mode and Poly Seq Start/Stop); such an alias follows along
				bool alias = value == parameter.value && after[id] == newValue;
				CAPTURE(id);
				CHECK((after[id] == value || alias));
			}
			edited++;
		}
		CHECK(edited > 0);
		CHECK(original->data() == originalBytes); // The library patch is never changed
	}

}

TEST_CASE("Matrix 1000 parameters edit independently, including single-bit ones") {
	checkEveryParameterEditsAlone(std::make_shared<midikraft::Matrix1000>(), 134);
}

TEST_CASE("Kawai K3 parameters edit independently, including signed ones") {
	checkEveryParameterEditsAlone(std::make_shared<midikraft::KawaiK3>(), 34);
}

TEST_CASE("MKS-80 parameters are written into the patch") {
	checkEveryParameterEditsAlone(std::make_shared<midikraft::MKS80>(), 126);
}

TEST_CASE("Rev2 shows and edits both layers") {
	auto synth = std::make_shared<midikraft::Rev2>();
	checkEveryParameterEditsAlone(synth, 2048);

	auto patch = synth->patchFromPatchData(midikraft::Synth::PatchData(2048, 0), MidiProgramNumber::fromZeroBase(0));
	auto parameters = patch_parameters::parametersFor(synth, patch);
	bool hasLayerA = false, hasLayerB = false;
	for (auto const& parameter : parameters) {
		hasLayerA = hasLayerA || parameter.group == "Layer A";
		hasLayerB = hasLayerB || parameter.group == "Layer B";
	}
	CHECK(hasLayerA);
	CHECK(hasLayerB);
}

TEST_CASE("Unknown ids and out-of-range values are refused") {
	auto synth = std::make_shared<midikraft::Matrix1000>();
	auto patch = legalPatch(synth, 134);
	auto parameters = patch_parameters::parametersFor(synth, patch);
	auto first = std::find_if(parameters.begin(), parameters.end(), [](midikraft::PatchParameter const& p) { return p.editable && p.maxValue; });
	REQUIRE(first != parameters.end());
	CHECK_FALSE(patch_parameters::applyNativeValue(synth, patch, MidiProgramNumber::fromZeroBase(0), "no such parameter", 1));
	CHECK_FALSE(patch_parameters::applyNativeValue(synth, patch, MidiProgramNumber::fromZeroBase(0), first->id, *first->maxValue + 1));
}

TEST_CASE("Switching patches warns only when edits would be lost") {
	auto synth = std::make_shared<midikraft::Matrix1000>();
	auto source = std::make_shared<midikraft::FromFileSource>("session.syx", "/tmp/session.syx", MidiProgramNumber::fromZeroBase(0));
	auto original = std::make_shared<midikraft::PatchHolder>(synth, source, legalPatch(synth, 134));
	auto other = legalPatch(synth, 134);

	PatchEditSession session;
	session.start(original);
	REQUIRE(session.canEdit());
	CHECK_FALSE(session.wouldDiscardEdits(other)); // Nothing edited yet

	auto parameters = session.parameters();
	auto editable = std::find_if(parameters.begin(), parameters.end(), [](midikraft::PatchParameter const& p) {
		return p.editable && p.minValue && p.maxValue && *p.minValue != *p.maxValue;
	});
	REQUIRE(editable != parameters.end());
	int newValue = editable->value != *editable->maxValue ? *editable->maxValue : *editable->minValue;
	REQUIRE(session.setValue(editable->id, newValue));
	REQUIRE(session.isDirty());

	CHECK(session.wouldDiscardEdits(other));
	CHECK(session.wouldDiscardEdits(original->patch())); // Going back to the unedited patch loses the edits too
	CHECK(session.wouldDiscardEdits(nullptr));
	auto saved = session.makeEditedPatch();
	REQUIRE(saved);
	CHECK_FALSE(session.wouldDiscardEdits(saved->patch())); // Selecting the saved copy keeps the sound

	// The copy has its own data: renaming it (which writes into the bytes on synths that store names) leaves the session alone
	CHECK(saved->patch() != session.makeEditedPatch()->patch());
	auto before = session.makeEditedPatch()->patch()->data();
	saved->setName("RENAMED");
	CHECK(session.makeEditedPatch()->patch()->data() == before);

	session.revert();
	CHECK_FALSE(session.wouldDiscardEdits(other));
}

TEST_CASE("Saved copies get the lowest free number that fits the synth") {
	std::set<std::string> names;
	auto taken = [&names](std::string const& name) { return names.count(name) > 0; };
	auto keepAll = [](std::string const& name) { return name; };
	auto cutTo = [](size_t length) {
		return [length](std::string const& name) { return name.substr(0, length); };
	};

	SUBCASE("first copy") {
		names = { "Pedal Steel" };
		CHECK(patch_copy_name::nameForCopy("Pedal Steel", taken, keepAll) == "Pedal Steel 2");
	}
	SUBCASE("skips numbers in use") {
		names = { "Pedal Steel", "Pedal Steel 2", "Pedal Steel 3" };
		CHECK(patch_copy_name::nameForCopy("Pedal Steel", taken, keepAll) == "Pedal Steel 4");
	}
	SUBCASE("a copy of a copy counts on") {
		names = { "Pedal Steel", "Pedal Steel 2" };
		CHECK(patch_copy_name::nameForCopy("Pedal Steel 2", taken, keepAll) == "Pedal Steel 3");
	}
	SUBCASE("a number that belongs to the name stays") {
		names = { "Jupiter 8" };
		CHECK(patch_copy_name::nameForCopy("Jupiter 8", taken, keepAll) == "Jupiter 8 2");
	}
	SUBCASE("long names are shortened so the number shows") {
		names = { "V-sw Ster Guitar" };
		CHECK(patch_copy_name::nameForCopy("V-sw Ster Guitar", taken, cutTo(16)) == "V-sw Ster Guit 2");
		CHECK(patch_copy_name::nameForCopy("Steel Gtr", taken, cutTo(10)) == "Steel Gt 2"); // GR-50 tone names have 10 characters
	}
	SUBCASE("a shortened name in use moves on to the next number") {
		names = { "V-sw Ster Guitar", "V-sw Ster Guit 2" };
		CHECK(patch_copy_name::nameForCopy("V-sw Ster Guitar", taken, cutTo(16)) == "V-sw Ster Guit 3");
	}
	SUBCASE("trailing blanks from padded names are dropped") {
		CHECK(patch_copy_name::nameForCopy("Bass    ", taken, keepAll) == "Bass 2");
	}
	SUBCASE("synths that change the name, e.g. to capitals, still get a number") {
		auto upper = [](std::string name) { for (auto& c : name) c = (char)std::toupper((unsigned char)c); return name; };
		names = { "BRASS", "BRASS 2" };
		CHECK(patch_copy_name::nameForCopy("BRASS", taken, upper) == "BRASS 3");
	}
	SUBCASE("keeps the original name when no number fits") {
		CHECK(patch_copy_name::nameForCopy("AB", taken, cutTo(2)) == "AB");
		CHECK(patch_copy_name::nameForCopy("", taken, keepAll) == "");
	}
}

TEST_CASE("Live sends wait as long as the synth needs for the messages") {
	using patch_edit_timing::kMinSendIntervalMs;
	using patch_edit_timing::sendIntervalMs;
	auto sysexOfSize = [](int totalBytes) {
		std::vector<uint8> payload(static_cast<size_t>(totalBytes - 2), 0x01); // F0 and F7 are added
		return juce::MidiMessage::createSysExMessage(payload.data(), static_cast<int>(payload.size()));
	};

	// Small dumps at full speed keep the minimum interval
	CHECK(sendIntervalMs({}, 0) == kMinSendIntervalMs);
	CHECK(sendIntervalMs({ sysexOfSize(275) }, 0) == kMinSendIntervalMs); // Matrix 1000: 88 ms on the wire

	// A GR-50 patch: one 198-byte DT1 after the adaptation's 100 ms pause, 64 ms on the wire, plus 50 ms
	CHECK(sendIntervalMs({ sysexOfSize(198) }, 100) == 100 + 64 + 50);

	// Each message gets its pause; big dumps are paced by the wire (a Rev2 program is about 1 KB at 31250 baud)
	CHECK(sendIntervalMs({ sysexOfSize(100), sysexOfSize(100), sysexOfSize(100) }, 30) == 90 + 96 + 50);
	CHECK(sendIntervalMs({ sysexOfSize(1000) }, 0) == 320 + 50);

	// A negative delay from a broken adaptation counts as none
	CHECK(sendIntervalMs({ sysexOfSize(1000) }, -500) == 320 + 50);

	// Native synths send at full speed unless they say otherwise
	CHECK(std::make_shared<midikraft::Matrix1000>()->generalMessageDelayMs() == 0);
}

TEST_CASE("MKS-80 shows and edits the upper and lower sections") {
	auto synth = std::make_shared<midikraft::MKS80>();
	auto original = legalPatch(synth, 126);
	auto parameters = patch_parameters::parametersFor(synth, original);
	REQUIRE(parameters.size() % 2 == 0);
	auto half = parameters.size() / 2;
	for (size_t i = 0; i < parameters.size(); ++i) {
		CAPTURE(parameters[i].id);
		CHECK(parameters[i].group == (i < half ? "Upper" : "Lower"));
	}
	auto values = valuesById(parameters);
	REQUIRE(values.count("LFO1_RATE_U"));
	REQUIRE(values.count("LFO1_RATE_L"));

	// Tone data: upper at bytes 30-77, lower at 78-125
	auto upper = patch_parameters::applyNativeValue(synth, original, MidiProgramNumber::fromZeroBase(0), "LFO1_RATE_U", 77);
	REQUIRE(upper);
	auto upperValues = valuesById(patch_parameters::parametersFor(synth, upper));
	CHECK(upperValues["LFO1_RATE_U"] == 77);
	CHECK(upperValues["LFO1_RATE_L"] == values["LFO1_RATE_L"]);
	for (size_t i = 0; i < 126; ++i) {
		if (i >= 30 && i < 78) continue;
		CAPTURE(i);
		CHECK(upper->data()[i] == original->data()[i]);
	}

	// Patch data: upper at bytes 0-14, lower at 15-29
	auto lower = patch_parameters::applyNativeValue(synth, original, MidiProgramNumber::fromZeroBase(0), "LFO2_RATE_L", 55);
	REQUIRE(lower);
	CHECK(valuesById(patch_parameters::parametersFor(synth, lower))["LFO2_RATE_L"] == 55);
	for (size_t i = 0; i < 126; ++i) {
		if (i >= 15 && i < 30) continue;
		CAPTURE(i);
		CHECK(lower->data()[i] == original->data()[i]);
	}
}

namespace {
	midikraft::PatchParameter knobParameter(std::string const& id, std::string const& group, int minValue, int maxValue, int value = 0) {
		midikraft::PatchParameter parameter;
		parameter.id = id;
		parameter.name = id;
		parameter.group = group;
		parameter.minValue = minValue;
		parameter.maxValue = maxValue;
		parameter.value = value;
		return parameter;
	}
}

TEST_CASE("BCR2000 pages follow the grid sections, 32 knobs at most") {
	midikraft::PatchParameters parameters;
	for (int i = 0; i < 4; ++i) parameters.push_back(knobParameter("c" + std::to_string(i), "Common", 0, 7));
	for (int i = 0; i < 40; ++i) parameters.push_back(knobParameter("p" + std::to_string(i), "Partial 1", 0, 100));
	auto readOnly = knobParameter("name", "Common", 0, 0);
	parameters.push_back(readOnly); // No range: no knob
	auto locked = knobParameter("locked", "Common", 0, 9);
	locked.editable = false;
	parameters.push_back(locked);
	parameters.push_back(knobParameter("s0", "String 1", 0, 1));

	auto pages = knob_pages::makePages(parameters);
	// Common fits the top row, so it stays there and the pages use the 24 knobs below
	REQUIRE(pages.size() == 3);
	std::vector<std::string> common{ "c0", "c1", "c2", "c3", "", "", "", "" };
	for (auto const& page : pages) {
		CAPTURE(page.title);
		REQUIRE(page.ids.size() > 8);
		CHECK(std::vector<std::string>(page.ids.begin(), page.ids.begin() + 8) == common);
	}
	CHECK(pages[0].title == "Partial 1 (1/2)");
	CHECK(pages[0].ids.size() == 32);
	CHECK(pages[0].ids[8] == "p0");
	CHECK(pages[0].ids[31] == "p23");
	CHECK(pages[1].title == "Partial 1 (2/2)");
	CHECK(pages[1].ids.size() == 8 + 16);
	CHECK(pages[1].ids[8] == "p24");
	CHECK(pages[2].title == "String 1");
	CHECK(pages[2].ids[8] == "s0");

	// On the BCR2000: Common on the top row, the page from the first encoder of the rows below
	auto bcl = knob_pages::pageBcl(pages[0], parameters);
	CHECK(bcl.find("$encoder 1\n  .easypar CC 16 1 0 7 absolute") != std::string::npos);
	CHECK(bcl.find("$encoder 5\n  .easypar CC 16 5 0 0 absolute\n  .mode off") != std::string::npos);
	CHECK(bcl.find("$encoder 33\n  .easypar CC 16 9 0 100 absolute") != std::string::npos);

	// Another patch keeps the page by title, else the position
	CHECK(knob_pages::pageIndexFor(pages, "String 1", 0) == 2);
	CHECK(knob_pages::pageIndexFor(pages, "Partial 7", 1) == 1);
	CHECK(knob_pages::pageIndexFor(pages, "Partial 7", 9) == 2);
	CHECK(knob_pages::pageIndexFor({}, "Common", 0) == -1);
}

TEST_CASE("BCR2000 pages use all knobs when the first section doesn't fit the top row") {
	midikraft::PatchParameters parameters;
	for (int i = 0; i < 9; ++i) parameters.push_back(knobParameter("u" + std::to_string(i), "Upper", 0, 100));
	for (int i = 0; i < 40; ++i) parameters.push_back(knobParameter("l" + std::to_string(i), "Lower", 0, 100));
	auto pages = knob_pages::makePages(parameters);
	REQUIRE(pages.size() == 3);
	CHECK(pages[0].title == "Upper");
	CHECK(pages[0].ids.size() == 9);
	CHECK(pages[0].ids[0] == "u0");
	CHECK(pages[1].title == "Lower (1/2)");
	CHECK(pages[1].ids.size() == 32);
	CHECK(pages[2].ids.size() == 8);

	// A single small section isn't pinned either: it is the only page
	midikraft::PatchParameters single{ knobParameter("a", "Common", 0, 7) };
	auto onePage = knob_pages::makePages(single);
	REQUIRE(onePage.size() == 1);
	CHECK(onePage[0].ids == std::vector<std::string>{ "a" });
}

TEST_CASE("BCR2000 knobs are the top row, then the three rows below") {
	CHECK(knob_pages::encoderNumber(0) == 1);
	CHECK(knob_pages::encoderNumber(7) == 8);
	CHECK(knob_pages::encoderNumber(8) == 33);
	CHECK(knob_pages::encoderNumber(31) == 56);
	CHECK(knob_pages::knobForController(1) == 0);
	CHECK(knob_pages::knobForController(32) == 31);
	CHECK(knob_pages::knobForController(33) == -1);
	CHECK(knob_pages::knobForController(knob_pages::kNextPageController) == -1);
}

TEST_CASE("BCR2000 knobs send parameter values as they are when they fit, else scaled") {
	auto choice = knobParameter("type", "Common", 0, 7);
	auto range = knob_pages::knobRange(choice);
	CHECK(range.low == 0);
	CHECK(range.high == 7);
	CHECK_FALSE(range.scaled);
	CHECK(knob_pages::toKnobValue(choice, 5) == 5);
	CHECK(knob_pages::fromKnobValue(choice, 5) == 5);
	CHECK(knob_pages::fromKnobValue(choice, 100) == 7); // Clamped to the range

	auto wide = knobParameter("wide", "", 0, 254);
	CHECK(knob_pages::knobRange(wide).scaled);
	CHECK(knob_pages::toKnobValue(wide, 0) == 0);
	CHECK(knob_pages::toKnobValue(wide, 254) == 127);
	CHECK(knob_pages::fromKnobValue(wide, 0) == 0);
	CHECK(knob_pages::fromKnobValue(wide, 127) == 254);

	auto signedRange = knobParameter("signed", "", -24, 24);
	CHECK(knob_pages::knobRange(signedRange).scaled);
	CHECK(knob_pages::fromKnobValue(signedRange, 0) == -24);
	CHECK(knob_pages::fromKnobValue(signedRange, 127) == 24);
	CHECK(knob_pages::toKnobValue(signedRange, 0) == 64);
	for (int value = -24; value <= 24; ++value) {
		CAPTURE(value);
		CHECK(knob_pages::fromKnobValue(signedRange, knob_pages::toKnobValue(signedRange, value)) == value);
	}
}

TEST_CASE("BCR2000 setup sets each knob's range and switches unused knobs off") {
	midikraft::PatchParameters parameters{ knobParameter("type", "Common", 0, 7), knobParameter("level", "Common", 0, 100) };
	auto pages = knob_pages::makePages(parameters);
	REQUIRE(pages.size() == 1);
	auto page = knob_pages::pageBcl(pages[0], parameters);
	CHECK(page.rfind("$rev R1\n", 0) == 0);
	CHECK(page.find("$encoder 1\n  .easypar CC 16 1 0 7 absolute\n  .mode 1dot") != std::string::npos);
	CHECK(page.find("$encoder 2\n  .easypar CC 16 2 0 100 absolute") != std::string::npos);
	CHECK(page.find("$encoder 3\n  .easypar CC 16 3 0 0 absolute\n  .mode off") != std::string::npos);
	CHECK(page.find("$encoder 56\n") != std::string::npos);
	CHECK(page.find("$preset") == std::string::npos);
	CHECK(page.size() > 6);
	CHECK(page.substr(page.size() - 5) == "$end\n");

	auto preset = knob_pages::presetBcl(pages[0], parameters);
	CHECK(preset.find("  .name 'KnobKraft grid'\n") != std::string::npos);
	CHECK(preset.find("  .init\n") != std::string::npos);
	CHECK(preset.find("  .fkeys off\n") != std::string::npos); // The page buttons must send, not change presets
	CHECK(preset.find("$button 49\n  .easypar CC 16 102 127 0 toggleoff") != std::string::npos);
	CHECK(preset.find("$button 50\n  .easypar CC 16 103 127 0 toggleoff") != std::string::npos);
	CHECK(preset.find("$store") == std::string::npos); // Never overwrites the BCR2000's own presets
}
