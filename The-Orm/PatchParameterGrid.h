#pragma once

#include "JuceHeader.h"

#include "PatchParametersCapability.h"

// Read-only grid of labelled patch parameters, laid out in sections by group.
class PatchParameterGrid : public Component, public TooltipClient {
public:
	void setParameters(midikraft::PatchParameters parameters);
	bool hasParameters() const { return !parameters_.empty(); }

	int desiredHeight(int width) const;

	void paint(Graphics& g) override;
	String getTooltip() override;

private:
	struct Section {
		String title;
		std::vector<size_t> indices;
	};

	struct Cell {
		size_t index;
		Rectangle<int> bounds;
	};

	std::vector<Cell> layoutCells(int width, std::vector<std::pair<String, Rectangle<int>>>* headers, int* height) const;

	midikraft::PatchParameters parameters_;
	std::vector<Section> sections_;
};
