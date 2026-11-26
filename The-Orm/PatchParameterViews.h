#pragma once

#include "Capability.h"
#include "DetailedParametersCapability.h"
#include "LayeredPatchCapability.h"
#include "PatchHolder.h"
#include "PatchParametersCapability.h"
#include "Synth.h"

#include <fmt/format.h>

namespace patch_parameters {

	namespace detail {
		constexpr size_t kMaxOptions = 64;

		// Points a multi-layer parameter definition at one layer, and back to layer 0 afterwards.
		// The native synths share their definition objects, so always restore the default.
		class LayerScope {
		public:
			LayerScope(std::shared_ptr<midikraft::SynthParameterDefinition> const& definition, int layer)
				: multiLayer_(midikraft::Capability::hasCapability<midikraft::SynthMultiLayerParameterCapability>(definition)) {
				if (multiLayer_) {
					multiLayer_->setSourceLayer(layer);
					multiLayer_->setTargetLayer(layer);
				}
			}
			~LayerScope() {
				if (multiLayer_) {
					multiLayer_->setSourceLayer(0);
					multiLayer_->setTargetLayer(0);
				}
			}
		private:
			std::shared_ptr<midikraft::SynthMultiLayerParameterCapability> multiLayer_;
		};

		// Number of layers to show: only when the patch has layers and its parameters can address them
		inline int layerCount(std::shared_ptr<midikraft::DataFile> const& data, std::vector<std::shared_ptr<midikraft::SynthParameterDefinition>> const& definitions) {
			auto layers = midikraft::Capability::hasCapability<midikraft::LayeredPatchCapability>(data);
			if (!layers || layers->numberOfLayers() < 2 || definitions.empty()) return 1;
			for (auto const& definition : definitions) {
				if (!midikraft::Capability::hasCapability<midikraft::SynthMultiLayerParameterCapability>(definition)) return 1;
			}
			return layers->numberOfLayers();
		}

		inline std::string layerGroup(std::shared_ptr<midikraft::DataFile> const& data, int layer) {
			auto layers = midikraft::Capability::hasCapability<midikraft::LayeredPatchCapability>(data);
			if (layers) {
				auto titles = layers->layerTitles();
				if (layer < static_cast<int>(titles.size()) && !titles[static_cast<size_t>(layer)].empty()) return titles[static_cast<size_t>(layer)];
			}
			return fmt::format("Layer {}", layer + 1);
		}

		inline std::string nativeId(std::string const& name, int layer, int layerCount) {
			return layerCount > 1 ? fmt::format("L{}:{}", layer, name) : name;
		}

		// Only plain integer parameters can be changed by dragging; arrays are shown read-only
		inline std::shared_ptr<midikraft::SynthIntParameterCapability> editableInt(std::shared_ptr<midikraft::SynthParameterDefinition> const& definition) {
			auto type = definition->type();
			if (type != midikraft::SynthParameterDefinition::ParamType::INT && type != midikraft::SynthParameterDefinition::ParamType::LOOKUP) return nullptr;
			return midikraft::Capability::hasCapability<midikraft::SynthIntParameterCapability>(definition);
		}

		inline midikraft::PatchParameters nativeParameters(std::shared_ptr<midikraft::DataFile> const& data) {
			midikraft::PatchParameters result;
			auto detailed = midikraft::Capability::hasCapability<midikraft::DetailedParametersCapability>(data);
			if (!detailed) return result;
			auto definitions = detailed->allParameterDefinitions();
			int layers = layerCount(data, definitions);
			for (int layer = 0; layer < layers; ++layer) {
				for (auto const& definition : definitions) {
					LayerScope scope(definition, layer);
					midikraft::PatchParameter parameter;
					parameter.id = nativeId(definition->name(), layer, layers);
					parameter.name = definition->description().empty() ? definition->name() : definition->description();
					parameter.group = layers > 1 ? layerGroup(data, layer) : "";
					parameter.text = definition->valueInPatchToText(*data);
					auto intParameter = editableInt(definition);
					int value = 0;
					// A parameter whose value can't be read has no place in the patch to write to either
					parameter.editable = intParameter && intParameter->valueInPatch(*data, value);
					if (parameter.editable) {
						parameter.value = value;
						parameter.minValue = intParameter->minValue();
						parameter.maxValue = intParameter->maxValue();
						auto lookup = midikraft::Capability::hasCapability<midikraft::SynthLookupParameterCapability>(definition);
						int count = intParameter->maxValue() - intParameter->minValue() + 1;
						if (lookup && count > 0 && static_cast<size_t>(count) <= kMaxOptions) {
							for (int v = intParameter->minValue(); v <= intParameter->maxValue(); ++v) {
								parameter.options.push_back(lookup->valueAsText(v));
							}
						}
					}
					result.push_back(parameter);
				}
			}
			return result;
		}
	}

	// Parameters from a synth's PatchParametersCapability (Python adaptations), else from the
	// older per-patch DetailedParametersCapability that the native C++ synths implement.
	inline midikraft::PatchParameters parametersFor(std::shared_ptr<midikraft::Synth> synth, std::shared_ptr<midikraft::DataFile> data) {
		if (!data) return {};

		auto capability = synth ? midikraft::Capability::hasCapability<midikraft::PatchParametersCapability>(synth.get()) : nullptr;
		if (capability) {
			auto parameters = capability->getPatchParameters(*data);
			if (!parameters.empty()) return parameters;
		}
		return detail::nativeParameters(data);
	}

	inline midikraft::PatchParameters parametersFor(midikraft::PatchHolder const& patch) {
		return parametersFor(patch.smartSynth(), patch.patch());
	}

	// True when a native synth's patch can be edited through its parameter definitions
	inline bool canEditNatively(std::shared_ptr<midikraft::Synth> synth, std::shared_ptr<midikraft::DataFile> data) {
		return synth && data && midikraft::Capability::hasCapability<midikraft::DetailedParametersCapability>(data);
	}

	// Applies one value to a copy of a native synth's patch. The given patch is never changed.
	inline std::shared_ptr<midikraft::DataFile> applyNativeValue(std::shared_ptr<midikraft::Synth> synth, std::shared_ptr<midikraft::DataFile> data,
		MidiProgramNumber place, std::string const& id, int value) {
		if (!canEditNatively(synth, data)) return nullptr;
		auto definitions = midikraft::Capability::hasCapability<midikraft::DetailedParametersCapability>(data)->allParameterDefinitions();
		int layers = detail::layerCount(data, definitions);
		for (int layer = 0; layer < layers; ++layer) {
			for (auto const& definition : definitions) {
				if (detail::nativeId(definition->name(), layer, layers) != id) continue;
				auto intParameter = detail::editableInt(definition);
				if (!intParameter || value < intParameter->minValue() || value > intParameter->maxValue()) return nullptr;
				auto copy = synth->patchFromPatchData(data->data(), place);
				if (!copy || copy->data() != data->data()) return nullptr; // The synth must rebuild the same patch from its bytes
				detail::LayerScope scope(definition, layer);
				intParameter->setInPatch(*copy, value);
				return copy;
			}
		}
		return nullptr;
	}

}
