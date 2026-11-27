#pragma once

#include "JuceHeader.h"

#include "PatchHolder.h"
#include "PatchParametersCapability.h"

#include <map>
#include <set>

namespace patch_edit_timing {
	// Shortest gap between two live sends, so a fast drag doesn't flood older synths
	constexpr int kMinSendIntervalMs = 150;
	// Time the synth needs before the next send of these messages can follow: the synth's pause before each
	// message, the bytes at MIDI's 31250 baud (10 bits each), and a little time to digest them. Never below kMinSendIntervalMs.
	int sendIntervalMs(std::vector<juce::MidiMessage> const& messages, int delayPerMessageMs);
}

// Edits one patch through its synth's PatchParametersCapability. The library patch is never changed:
// edits go to a working copy, which is sent to the synth's edit buffer (throttled) and can be saved as a new patch.
class PatchEditSession : private Timer {
public:
	~PatchEditSession() override;

	void start(std::shared_ptr<midikraft::PatchHolder> original);
	bool isEditing(std::shared_ptr<midikraft::DataFile> const& libraryPatch) const;

	bool canEdit() const;
	bool isDirty() const;
	// True when showing next would lose edits: there are edits, and next isn't the edited sound itself (e.g. its saved copy)
	bool wouldDiscardEdits(std::shared_ptr<midikraft::DataFile> const& next) const;

	midikraft::PatchParameters parameters() const;
	std::set<std::string> changedIds() const;

	bool setValue(std::string const& id, int value);
	void revert();

	// A new library patch holding the edited data and the original's metadata
	std::shared_ptr<midikraft::PatchHolder> makeEditedPatch() const;

private:
	void timerCallback() override;
	void scheduleSend();
	int sendNow(); // Returns the time to wait before the next send
	midikraft::PatchParametersCapability* capability() const;
	bool usesAdaptation() const; // Python adaptation with setPatchParameters, else the native parameter definitions

	std::shared_ptr<midikraft::PatchHolder> original_;
	std::shared_ptr<midikraft::DataFile> current_;
	std::map<std::string, int> originalValues_;
	bool sendPending_ = false;
};
