#define DOCTEST_CONFIG_IMPLEMENT
#include "doctest/doctest.h"

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
