/*
   Copyright (c) 2021 Christof Ruch. All rights reserved.

   Dual licensed: Distributed under Affero GPL license by default, an MIT license is available for purchase
*/

#include "PatchTextBox.h"

#include "Capability.h"
#include "DetailedParametersCapability.h"
#include "LayeredPatchCapability.h"
#include "PatchTextViews.h"
#include "PatchParameterViews.h"

namespace {
	constexpr int kGridId = 1000; // Custom text views use ids from 3 upwards
	constexpr int kTopRowHeight = 20;
}

#include <fmt/format.h>

PatchTextBox::PatchTextBox(std::function<void()> forceResize, bool showParams /* = true */) : forceResize_(forceResize), showParams_(showParams)
{
	document_ = std::make_unique<CodeDocument>();
	textBox_ = std::make_unique<CodeEditorComponent>(*document_, nullptr);
	textBox_->setScrollbarThickness(10);
	textBox_->setReadOnly(true);
	textBox_->setLineNumbersShown(false);
	addChildComponent(*textBox_);
	textBox_->setVisible(showParams_);

	addChildComponent(hexBased_);
	hexBased_.setVisible(!showParams_);
	hexBased_.setButtonText("Hex Dump");
	hexBased_.setClickingTogglesState(true);
	hexBased_.onClick = [this]() {
		toggleTouched_ = true;
		updateContentVisibility();
		if (forceResize_) forceResize_();
	};

	addChildComponent(grid_);
	grid_.onValueChanged = [this](std::string const& id, int value) {
		if (session_.setValue(id, value)) refreshGrid();
	};

	saveEdits_.setButtonText("Save as new");
	saveEdits_.setTooltip("Store the edited patch as a new patch in the library. The original stays as it is.");
	saveEdits_.onClick = [this]() {
		auto edited = session_.makeEditedPatch();
		if (edited && onSaveEditedPatch) onSaveEditedPatch(edited);
	};
	addChildComponent(saveEdits_);

	revertEdits_.setButtonText("Revert");
	revertEdits_.setTooltip("Discard the edits and send the original patch to the synth again.");
	revertEdits_.onClick = [this]() {
		session_.revert();
		refreshGrid();
	};
	addChildComponent(revertEdits_);

	addChildComponent(viewSelector_);
	viewSelector_.setVisible(showParams_);
	viewSelector_.addItem("Raw hex", 1);
	viewSelector_.setSelectedId(1, dontSendNotification);
	viewSelector_.onChange = [this]() {
		preferGrid_ = gridSelected();
		refreshText();
		updateContentVisibility();
		if (forceResize_) forceResize_();
	};
}

void PatchTextBox::fillTextBox(std::shared_ptr<midikraft::PatchHolder> patch)
{
	auto previousId = viewSelector_.getSelectedId();
	std::string previousName;
	if (previousId >= 3 && previousId != kGridId) previousName = customViews_.at(static_cast<size_t>(previousId - 3)).first;
	bool firstPatch = !patch_;
	patch_ = patch;
	// Keep the edits when the same library patch is shown again, e.g. after a category change
	if (!session_.isEditing(patch ? patch->patch() : nullptr)) session_.start(patch);
	customViews_ = patch ? patch_text::viewsFor(*patch) : midikraft::PatchTextViews{};
	viewSelector_.clear(dontSendNotification);
	auto parameters = session_.canEdit() ? session_.parameters() : (patch ? patch_parameters::parametersFor(*patch) : midikraft::PatchParameters{});
	bool hasGrid = !parameters.empty();
	grid_.setParameters(std::move(parameters));
	grid_.setEditable(session_.canEdit());
	grid_.setChangedIds(session_.changedIds());
	if (hasGrid) viewSelector_.addItem("Parameter grid", kGridId);
	viewSelector_.addItem("Raw hex", 1);
	bool hasParams = patch && midikraft::Capability::hasCapability<midikraft::DetailedParametersCapability>(patch->patch());
	if (hasParams) viewSelector_.addItem("Parameter values", 2);
	int selectedId = hasParams && (previousId == 2 || (firstPatch && showParams_)) ? 2 : 1;
	for (size_t i = 0; i < customViews_.size(); ++i) {
		auto id = 3 + static_cast<int>(i);
		viewSelector_.addItem(String::fromUTF8(customViews_[i].first.c_str()), id);
		if (previousId >= 3 && customViews_[i].first == previousName) selectedId = id;
	}
	if (hasGrid && (preferGrid_ || previousId == kGridId)) selectedId = kGridId;
	viewSelector_.setSelectedId(selectedId, dontSendNotification);
	// Open the panel for patches with parameters, unless the user has opened or closed it themselves
	if (!showParams_ && !toggleTouched_) hexBased_.setToggleState(hasGrid, dontSendNotification);
	hexBased_.setButtonText(hasGrid ? "Parameters" : (viewSelector_.getNumItems() > 1 ? "Patch text" : "Hex Dump"));
	refreshText();
	updateContentVisibility();
	if (forceResize_) forceResize_();
}

bool PatchTextBox::gridSelected() const {
	return viewSelector_.getSelectedId() == kGridId;
}

void PatchTextBox::updateContentVisibility() {
	bool open = showParams_ || hexBased_.getToggleState();
	textBox_->setVisible(open && !gridSelected());
	grid_.setVisible(open && gridSelected());
	viewSelector_.setVisible(showParams_ || (open && viewSelector_.getNumItems() > 1));
	updateEditButtons();
	resized();
}

bool PatchTextBox::editButtonsShown() const {
	return grid_.isVisible() && session_.canEdit();
}

bool PatchTextBox::wouldDiscardEdits(midikraft::PatchHolder const& next) const
{
	return session_.wouldDiscardEdits(next.patch());
}

std::shared_ptr<midikraft::PatchHolder> PatchTextBox::makeEditedPatch() const
{
	return session_.makeEditedPatch();
}

void PatchTextBox::discardEdits()
{
	session_.revert();
	refreshGrid();
}

void PatchTextBox::refreshGrid() {
	grid_.setParameters(session_.parameters());
	grid_.setChangedIds(session_.changedIds());
	updateEditButtons();
}

void PatchTextBox::updateEditButtons() {
	bool shown = editButtonsShown();
	bool dirty = session_.isDirty();
	saveEdits_.setVisible(shown);
	revertEdits_.setVisible(shown);
	saveEdits_.setEnabled(dirty);
	revertEdits_.setEnabled(dirty);
}

void PatchTextBox::refreshText() {
	String text;
	auto selectedId = viewSelector_.getSelectedId();
	if (selectedId == kGridId) text = {};
	else if (selectedId == 1) text = makeHexDocument(patch_);
	else if (selectedId == 2) text = makeTextDocument(patch_);
	else text = String::fromUTF8(customViews_.at(static_cast<size_t>(selectedId - 3)).second.c_str());
	// No reflow, trimming, or newline normalization of adaptation-provided text.
	document_->replaceAllContent(text);
}

void PatchTextBox::resized()
{
	auto area = getLocalBounds();

	auto topRow = area.removeFromTop(kTopRowHeight);
	if (!showParams_) hexBased_.setBounds(topRow.removeFromLeft(100));
	if (editButtonsShown()) {
		revertEdits_.setBounds(topRow.removeFromRight(70).withTrimmedLeft(4));
		saveEdits_.setBounds(topRow.removeFromRight(100).withTrimmedLeft(4));
	}
	viewSelector_.setBounds(topRow);

	textBox_->setBounds(area);
	grid_.setBounds(area.withTrimmedTop(4));

	if (viewSelector_.getSelectedId() == 1 && lastLayoutedWidth_.has_value() && *lastLayoutedWidth_ != area.getWidth() && patch_) {
		refreshText();
	}
}

String PatchTextBox::makeHexDocument(std::shared_ptr<midikraft::PatchHolder> patch)
{
	if (!patch || !patch->patch())
		return "No patch active";

	String result;
	std::vector<uint8> binaryData = patch->patch()->data();

	// Find out how many characters we can display
	auto fontUsed = textBox_->getFont();
	auto width = textBox_->getWidth();
	std::string testLine = "0000";
	int testLineLength = 0;
	do {
		testLine += " 00";
		testLineLength += 1;
	} while (TextLayout::getStringWidth(fontUsed, testLine) < width - 22);
	testLineLength = std::max(testLineLength-1, 1);
	lastLayoutedWidth_ = width;

	uint8 *line = binaryData.data();
	int consumed = 0;
	while (consumed < (int)binaryData.size()) {
		uint8 posLSB = consumed & 0xff;
		uint8 posMSB = (consumed >> 8) & 0xff;
		result += String::toHexString(&posMSB, 1, 1) + String::toHexString(&posLSB, 1, 1) + " ";
		int lineLength = std::min(testLineLength, ((int)binaryData.size()) - consumed);
		String hex = String::toHexString(line, lineLength, 1);
		result += hex;
		result += "\n";

		line += lineLength;
		consumed += lineLength;
	}

	return result;
}

float PatchTextBox::desiredHeight(int width) const {
	if (width < 0) width = getWidth();
	if (grid_.isVisible() || ((showParams_ || hexBased_.getToggleState()) && gridSelected())) {
		return static_cast<float>(kTopRowHeight + 4 + grid_.desiredHeight(width));
	}
	auto fontUsed = textBox_->getFont();
	auto linesNeeded = (showParams_ || hexBased_.getToggleState()) ? document_->getNumLines() : 0;
	return fontUsed.getHeight() * (linesNeeded + 4);
}

String PatchTextBox::makeTextDocument(std::shared_ptr<midikraft::PatchHolder> patch) {
	if (!patch || !patch->patch())
		return "No patch active";

	auto realPatch = std::dynamic_pointer_cast<midikraft::Patch>(patch->patch());
	if (realPatch) {
		return patchToTextRaw(realPatch, false);
	}
	else {
		return "makeTextDocument not implemented yet";
	}
}

std::string PatchTextBox::patchToTextRaw(std::shared_ptr<midikraft::Patch> patch, bool onlyActive)
{
	std::string result;

	int numLayers = 1;
	auto layers = midikraft::Capability::hasCapability<midikraft::LayeredPatchCapability>(patch);
	if (layers) {
		numLayers = layers->numberOfLayers();
	}

	auto parameterDetails = midikraft::Capability::hasCapability<midikraft::DetailedParametersCapability>(patch);

	if (parameterDetails) {
		for (int layer = 0; layer < numLayers; layer++) {
			if (layers) {
				if (layer > 0) result += "\n";
				result = result + fmt::format("Layer: {}\n", layers->layerName(layer));
			}
			for (auto param : parameterDetails->allParameterDefinitions()) {
				if (layers) {
					auto multiLayerParam = midikraft::Capability::hasCapability<midikraft::SynthMultiLayerParameterCapability>(param);
					jassert(multiLayerParam);
					if (multiLayerParam) {
						multiLayerParam->setSourceLayer(layer);
					}
				}
				auto activeCheck = midikraft::Capability::hasCapability<midikraft::SynthParameterActiveDetectionCapability>(param);
				if (!onlyActive || !activeCheck || !(activeCheck->isActive(patch.get()))) {
					result = result + fmt::format("{}: {}\n",param->description(), param->valueInPatchToText(*patch));
				}
			}
		}
	}
	return result;
}

