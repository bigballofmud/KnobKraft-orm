#pragma once

#include "JuceHeader.h"

#include "PatchParametersCapability.h"

#include <map>
#include <set>

// Grid of labelled patch parameters, laid out in sections by group. When editable, dragging a number
// up or down changes it, and clicking a choice opens a menu of its options.
class PatchParameterGrid : public Component, public TooltipClient {
public:
	void setParameters(midikraft::PatchParameters parameters);
	bool hasParameters() const { return !parameters_.empty(); }

	void setEditable(bool editable);
	void setChangedIds(std::set<std::string> changedIds);
	// Knob numbers of the parameters a hardware controller currently edits, by id, shown on their cells
	void setKnobAssignments(std::map<std::string, int> knobs);

	// Called with a parameter id and its new raw value
	std::function<void(std::string const&, int)> onValueChanged;

	int desiredHeight(int width) const;

	void paint(Graphics& g) override;
	String getTooltip() override;

	void mouseMove(MouseEvent const& e) override;
	void mouseDown(MouseEvent const& e) override;
	void mouseDrag(MouseEvent const& e) override;
	void mouseUp(MouseEvent const& e) override;

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
	midikraft::PatchParameter const* parameterAt(Point<int> position) const;
	bool isChoice(midikraft::PatchParameter const& parameter) const;
	void showOptionsMenu(midikraft::PatchParameter const& parameter);

	midikraft::PatchParameters parameters_;
	std::vector<Section> sections_;
	bool editable_ = false;
	std::set<std::string> changedIds_;
	std::map<std::string, int> knobs_;

	// Drag state, kept by id because the parameters are replaced after every change
	std::string dragId_;
	int dragStartValue_ = 0;
	int dragLastValue_ = 0;
	int dragMin_ = 0;
	int dragMax_ = 0;
};
