#include "PatchParameterGrid.h"

namespace {
	constexpr int kMinCellWidth = 140;
	constexpr int kCellHeight = 38;
	constexpr int kGap = 4;
	constexpr int kHeaderHeight = 24;
	constexpr int kSectionGap = 8;
	constexpr int kDefaultMax = 127; // Range assumed when the synth gives none
	constexpr int kMaxOptionsInMenu = 64;
}

void PatchParameterGrid::setParameters(midikraft::PatchParameters parameters)
{
	parameters_ = std::move(parameters);
	sections_.clear();
	// Sections in order of first appearance, so the adaptation controls the order
	for (size_t i = 0; i < parameters_.size(); ++i) {
		auto title = String::fromUTF8(parameters_[i].group.c_str());
		auto section = std::find_if(sections_.begin(), sections_.end(), [&](Section const& s) { return s.title == title; });
		if (section == sections_.end()) {
			sections_.push_back({ title, { i } });
		}
		else {
			section->indices.push_back(i);
		}
	}
	repaint();
}

std::vector<PatchParameterGrid::Cell> PatchParameterGrid::layoutCells(int width, std::vector<std::pair<String, Rectangle<int>>>* headers, int* height) const
{
	std::vector<Cell> cells;
	int columns = std::max(1, (width + kGap) / (kMinCellWidth + kGap));
	int cellWidth = std::max(1, (width - (columns - 1) * kGap) / columns);
	int y = 0;
	for (auto const& section : sections_) {
		if (section.title.isNotEmpty()) {
			if (headers) headers->emplace_back(section.title, Rectangle<int>(0, y, width, kHeaderHeight));
			y += kHeaderHeight;
		}
		for (size_t i = 0; i < section.indices.size(); ++i) {
			int column = static_cast<int>(i) % columns;
			int row = static_cast<int>(i) / columns;
			cells.push_back({ section.indices[i], Rectangle<int>(column * (cellWidth + kGap), y + row * (kCellHeight + kGap), cellWidth, kCellHeight) });
		}
		int rows = (static_cast<int>(section.indices.size()) + columns - 1) / columns;
		y += rows * (kCellHeight + kGap) + kSectionGap;
	}
	if (height) *height = y;
	return cells;
}

void PatchParameterGrid::setEditable(bool editable)
{
	editable_ = editable;
	if (!editable_) dragId_.clear();
	repaint();
}

void PatchParameterGrid::setChangedIds(std::set<std::string> changedIds)
{
	changedIds_ = std::move(changedIds);
	repaint();
}

void PatchParameterGrid::setKnobAssignments(std::map<std::string, int> knobs)
{
	if (knobs == knobs_) return;
	knobs_ = std::move(knobs);
	repaint();
}

midikraft::PatchParameter const* PatchParameterGrid::parameterAt(Point<int> position) const
{
	for (auto const& cell : layoutCells(getWidth(), nullptr, nullptr)) {
		if (cell.bounds.contains(position)) {
			return &parameters_[cell.index];
		}
	}
	return nullptr;
}

bool PatchParameterGrid::isChoice(midikraft::PatchParameter const& parameter) const
{
	return !parameter.options.empty() && parameter.options.size() <= kMaxOptionsInMenu;
}

void PatchParameterGrid::mouseMove(MouseEvent const& e)
{
	auto parameter = editable_ ? parameterAt(e.getPosition()) : nullptr;
	if (!parameter || !parameter->editable) setMouseCursor(MouseCursor::NormalCursor);
	else if (isChoice(*parameter)) setMouseCursor(MouseCursor::PointingHandCursor);
	else setMouseCursor(MouseCursor::UpDownResizeCursor);
}

void PatchParameterGrid::mouseDown(MouseEvent const& e)
{
	dragId_.clear();
	if (!editable_ || !onValueChanged) return;
	auto parameter = parameterAt(e.getPosition());
	if (!parameter || !parameter->editable) return;
	if (isChoice(*parameter)) {
		showOptionsMenu(*parameter);
		return;
	}
	dragId_ = parameter->id;
	dragStartValue_ = parameter->value;
	dragLastValue_ = parameter->value;
	dragMin_ = parameter->minValue.value_or(0);
	dragMax_ = parameter->maxValue.value_or(kDefaultMax);
}

void PatchParameterGrid::mouseDrag(MouseEvent const& e)
{
	if (dragId_.empty() || dragMax_ <= dragMin_) return;
	// About 200 pixels for the whole range, but never less than 2 or more than 12 pixels per step; Shift for fine steps
	float pixelsPerStep = jlimit(2.0f, 12.0f, 200.0f / static_cast<float>(dragMax_ - dragMin_));
	if (e.mods.isShiftDown()) pixelsPerStep *= 4.0f;
	int steps = static_cast<int>(-e.getDistanceFromDragStartY() / pixelsPerStep);
	int newValue = jlimit(dragMin_, dragMax_, dragStartValue_ + steps);
	if (newValue != dragLastValue_) {
		dragLastValue_ = newValue;
		onValueChanged(dragId_, newValue);
	}
}

void PatchParameterGrid::mouseUp(MouseEvent const&)
{
	dragId_.clear();
}

void PatchParameterGrid::showOptionsMenu(midikraft::PatchParameter const& parameter)
{
	PopupMenu menu;
	int minValue = parameter.minValue.value_or(0);
	for (size_t i = 0; i < parameter.options.size(); ++i) {
		int value = minValue + static_cast<int>(i);
		menu.addItem(static_cast<int>(i) + 1, String::fromUTF8(parameter.options[i].c_str()), true, value == parameter.value);
	}
	auto id = parameter.id;
	Component::SafePointer<PatchParameterGrid> safeThis(this);
	menu.showMenuAsync(PopupMenu::Options().withTargetComponent(this).withMousePosition(), [safeThis, id, minValue](int result) {
		if (result > 0 && safeThis && safeThis->onValueChanged) {
			safeThis->onValueChanged(id, minValue + result - 1);
		}
	});
}

int PatchParameterGrid::desiredHeight(int width) const
{
	if (parameters_.empty() || width <= 0) return 0;
	int height = 0;
	layoutCells(width, nullptr, &height);
	return height;
}

void PatchParameterGrid::paint(Graphics& g)
{
	auto background = getLookAndFeel().findColour(ResizableWindow::backgroundColourId);
	auto text = getLookAndFeel().findColour(Label::textColourId);
	auto cellColour = background.contrasting(0.06f);
	auto changedColour = getLookAndFeel().findColour(Slider::thumbColourId);
	auto knobColour = getLookAndFeel().findColour(TextButton::buttonOnColourId);

	std::vector<std::pair<String, Rectangle<int>>> headers;
	auto cells = layoutCells(getWidth(), &headers, nullptr);

	g.setFont(FontOptions(14.0f, Font::bold));
	g.setColour(text);
	for (auto const& [title, bounds] : headers) {
		g.drawText(title, bounds.withTrimmedLeft(2), Justification::centredLeft, true);
	}

	for (auto const& cell : cells) {
		auto const& parameter = parameters_[cell.index];
		auto area = cell.bounds;
		g.setColour(cellColour);
		g.fillRoundedRectangle(area.toFloat(), 4.0f);
		if (changedIds_.count(parameter.id)) {
			g.setColour(changedColour);
			g.drawRoundedRectangle(area.toFloat().reduced(0.75f), 4.0f, 1.5f);
		}
		auto knob = knobs_.find(parameter.id);
		if (knob != knobs_.end()) {
			// A small badge with the knob number in the top right corner
			auto badge = Rectangle<float>(static_cast<float>(area.getRight() - 22), static_cast<float>(area.getY() + 3), 19.0f, 13.0f);
			g.setColour(knobColour);
			g.fillRoundedRectangle(badge, 3.0f);
			g.setColour(knobColour.contrasting(0.8f));
			g.setFont(FontOptions(10.0f, Font::bold));
			g.drawText(String(knob->second), badge, Justification::centred, false);
			area.removeFromRight(22);
		}
		area = area.reduced(6, 3);
		g.setColour(text.withAlpha(0.6f));
		g.setFont(FontOptions(11.0f));
		g.drawText(String::fromUTF8(parameter.name.c_str()), area.removeFromTop(14), Justification::centredLeft, true);
		g.setColour(text);
		g.setFont(FontOptions(14.0f, Font::bold));
		g.drawText(String::fromUTF8(parameter.text.c_str()), area, Justification::centredLeft, true);
	}
}

String PatchParameterGrid::getTooltip()
{
	auto position = getMouseXYRelative();
	for (auto const& cell : layoutCells(getWidth(), nullptr, nullptr)) {
		if (cell.bounds.contains(position)) {
			auto const& parameter = parameters_[cell.index];
			String tip = String::fromUTF8(parameter.name.c_str()) + ": " + String::fromUTF8(parameter.text.c_str());
			tip << "\nRaw value " << parameter.value;
			if (parameter.minValue && parameter.maxValue) {
				tip << " (range " << *parameter.minValue << " to " << *parameter.maxValue << ")";
			}
			auto knob = knobs_.find(parameter.id);
			if (knob != knobs_.end()) {
				tip << "\nOn BCR2000 knob " << knob->second;
			}
			if (editable_ && !parameter.editable) {
				tip << "\nCan't be edited here";
			}
			else if (editable_) {
				tip << (isChoice(parameter) ? "\nClick to choose" : "\nDrag up or down to change, Shift for fine steps");
			}
			return tip;
		}
	}
	return {};
}
