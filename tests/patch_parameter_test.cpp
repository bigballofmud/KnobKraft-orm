#define DOCTEST_CONFIG_IMPLEMENT
#include "doctest/doctest.h"

#include "The-Orm/PatchParameterViews.h"

#include "KawaiK3.h"
#include "MKS80.h"
#include "Matrix1000.h"
#include "Rev2.h"
#include "Settings.h"

#include <map>

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
