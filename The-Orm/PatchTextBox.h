/*
   Copyright (c) 2021 Christof Ruch. All rights reserved.

   Dual licensed: Distributed under Affero GPL license by default, an MIT license is available for purchase
*/

#pragma once

#include "JuceHeader.h"

#include "PatchHolder.h"
#include "PatchTextCapability.h"
#include "PatchParameterGrid.h"

class PatchTextBox : public Component {
public:
	PatchTextBox(std::function<void()> forceResize = {}, bool showParams = true);

	void fillTextBox(std::shared_ptr<midikraft::PatchHolder> patch);

	virtual void resized() override;

	String makeHexDocument(std::shared_ptr<midikraft::PatchHolder> patch);
	static String makeTextDocument(std::shared_ptr<midikraft::PatchHolder> patch);
	static std::string patchToTextRaw(std::shared_ptr<midikraft::Patch> patch, bool onlyActive);

	// Height needed at the given width; a negative width uses the current width
	float desiredHeight(int width = -1) const;

private:
	void refreshText();
	void updateContentVisibility();
	bool gridSelected() const;

	std::function<void()> forceResize_;
	bool showParams_;
	std::shared_ptr<midikraft::PatchHolder> patch_;
	std::unique_ptr<CodeDocument> document_;
	std::unique_ptr<CodeEditorComponent> textBox_;
	TextButton hexBased_;
	ComboBox viewSelector_;
	midikraft::PatchTextViews customViews_;
	std::optional<int> lastLayoutedWidth_;
	PatchParameterGrid grid_;
	bool preferGrid_ = true; // Show the grid when a patch has parameters, until the user picks another view
	bool toggleTouched_ = false; // The user has opened or closed the panel themselves
};



