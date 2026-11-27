#pragma once

#include "JuceHeader.h"

#include "KnobPages.h"
#include "MidiController.h"

#include <map>
#include <memory>
#include <optional>

namespace midikraft {
	class BCR2000;
}

// Uses a detected BCR2000 as a front panel for the parameter grid: its knobs edit the parameters of the current
// page (see knob_pages), the two user buttons at the lower right turn pages, and the LED rings follow the patch.
// The layout goes into the BCR2000's edit buffer only, so its stored presets stay as they are.
class BCR2000FrontPanel : private Timer {
public:
	BCR2000FrontPanel();
	~BCR2000FrontPanel() override;

	// The grid's current parameters. Call after every change; only the knobs whose value changed are sent.
	void show(midikraft::PatchParameters const& parameters, bool editable);

	// A knob was turned: a parameter id and its new raw value
	std::function<void(std::string const&, int)> onKnobTurned;
	// The page or its knobs changed, e.g. for marking the cells
	std::function<void()> onPageChanged;

	// Sends the whole layout again, e.g. after a preset was recalled on the BCR2000 itself
	void reload();

	// Knob numbers (1-32) of the parameters on the current page, by id
	std::map<std::string, int> knobAssignments() const;
	// E.g. "BCR2000: String 1 (2 of 9)", empty when no BCR2000 is detected or nothing can be edited
	std::string status() const;

private:
	void timerCallback() override;
	std::shared_ptr<midikraft::BCR2000> findBcr() const;
	void connect(std::shared_ptr<midikraft::BCR2000> const& bcr);
	void disconnect();
	void handleMessage(MidiMessage const& message);
	void turnPage(int delta);
	void programPage();
	void sendNextLine();
	void finishUpload(bool ok);
	void sendValues();
	midikraft::PatchParameter const* parameterOnKnob(int knob) const;

	std::weak_ptr<midikraft::BCR2000> bcr_;
	juce::MidiDeviceInfo input_;
	midikraft::MidiController::HandlerHandle handler_ = midikraft::MidiController::makeNoneHandle();

	midikraft::PatchParameters parameters_;
	std::vector<knob_pages::Page> pages_;
	int pageIndex_ = -1;
	std::string pageTitle_;

	bool presetLoaded_ = false; // The full preset is in the BCR2000's edit buffer
	std::string programmedPage_; // pageBcl of the knobs as the BCR2000 has them
	std::map<int, int> knobValues_; // What the BCR2000 shows, by knob

	// Upload of BCL lines, one at a time: the BCR2000 answers each line before it takes the next
	std::vector<MidiMessage> upload_;
	size_t uploadNext_ = 0;
	std::string uploadingPage_;
	bool uploadAgain_ = false;
	int64 lastUploadActivity_ = 0;

	JUCE_DECLARE_WEAK_REFERENCEABLE(BCR2000FrontPanel)
};
