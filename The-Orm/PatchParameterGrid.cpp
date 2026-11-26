#include "PatchParameterGrid.h"

namespace {
	constexpr int kMinCellWidth = 140;
	constexpr int kCellHeight = 38;
	constexpr int kGap = 4;
	constexpr int kHeaderHeight = 24;
	constexpr int kSectionGap = 8;
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
			return tip;
		}
	}
	return {};
}
