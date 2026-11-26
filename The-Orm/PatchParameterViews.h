#pragma once

#include "Capability.h"
#include "DetailedParametersCapability.h"
#include "PatchHolder.h"
#include "PatchParametersCapability.h"

namespace patch_parameters {

	// Parameters from a synth's PatchParametersCapability (Python adaptations), else from the
	// older per-patch DetailedParametersCapability that the native C++ synths implement.
	inline midikraft::PatchParameters parametersFor(midikraft::PatchHolder const& patch) {
		auto data = patch.patch();
		if (!data) return {};

		auto capability = midikraft::Capability::hasCapability<midikraft::PatchParametersCapability>(patch.synth());
		if (capability) {
			auto parameters = capability->getPatchParameters(*data);
			if (!parameters.empty()) return parameters;
		}

		midikraft::PatchParameters result;
		auto detailed = midikraft::Capability::hasCapability<midikraft::DetailedParametersCapability>(data);
		if (detailed) {
			for (auto const& definition : detailed->allParameterDefinitions()) {
				midikraft::PatchParameter parameter;
				parameter.id = definition->name();
				parameter.name = definition->description().empty() ? definition->name() : definition->description();
				parameter.text = definition->valueInPatchToText(*data);
				auto intParameter = midikraft::Capability::hasCapability<midikraft::SynthIntParameterCapability>(definition);
				if (intParameter) {
					int value = 0;
					if (intParameter->valueInPatch(*data, value)) parameter.value = value;
					parameter.minValue = intParameter->minValue();
					parameter.maxValue = intParameter->maxValue();
				}
				result.push_back(parameter);
			}
		}
		return result;
	}

}
